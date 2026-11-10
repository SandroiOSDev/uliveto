"""Interfaccia web locale di Uliveto, senza dipendenze esterne."""

from __future__ import annotations

import argparse
import csv
import html
import io
import os
import secrets
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import db

CSS = Path(__file__).with_name("static").joinpath("style.css")


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def page(title: str, body: str, *, notice: str = "", error: str = "") -> str:
    message = f'<div class="notice">{esc(notice)}</div>' if notice else ""
    message += f'<div class="error" role="alert">{esc(error)}</div>' if error else ""
    return f"""<!doctype html><html lang="it"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta name="description" content="Registro locale del tuo uliveto">
    <title>{esc(title)} · Uliveto</title><link rel="stylesheet" href="/static/style.css"></head>
    <body><header class="topbar"><a class="brand" href="/">◉ <span>Uliveto</span></a>
    <nav><a href="/">Registro</a><a href="/trees/new">Nuovo ulivo</a><a href="/export">Esporta CSV</a></nav></header>
    <main>{message}{body}</main><footer>I dati restano sul tuo computer · Uliveto v0.1</footer></body></html>"""


def badge(health: str | None) -> str:
    label = db.HEALTH.get(health or "", "Mai osservato")
    return f'<span class="badge {esc(health or "unknown")}">{esc(label)}</span>'


def dashboard(conn, query: str, health: str, notice: str = "") -> str:
    stats = db.summary(conn)
    rows = db.list_trees(conn, query, health)
    cards = "".join(f'<a href="/?health={quote(key)}" class="stat"><strong>{stats[key]}</strong><span>{esc(label)}</span></a>' for key, label in [("total", "Ulivi"), ("sano", "Sani"), ("attenzione", "Da osservare"), ("critico", "Critici"), ("mai_osservato", "Senza osservazioni")])
    options = '<option value="">Tutti gli stati</option>' + "".join(f'<option value="{key}" {"selected" if health == key else ""}>{esc(label)}</option>' for key, label in [*db.HEALTH.items(), ("mai_osservato", "Mai osservato")])
    search = f'''<form class="filters" method="get"><label class="sr-only" for="q">Cerca ulivi</label><input id="q" name="q" placeholder="Cerca codice, cultivar o zona" value="{esc(query)}"><label class="sr-only" for="health">Stato</label><select id="health" name="health">{options}</select><button type="submit">Filtra</button><a href="/">Azzera</a></form>'''
    if rows:
        entries = "".join(f'''<a class="tree-row" href="/trees/{r['id']}"><span class="tree-icon">♧</span><span class="tree-main"><strong>{esc(r['code'])}</strong><small>{esc(r['cultivar'])} · {esc(r['parcel'])}</small></span>{badge(r['latest_health'])}<span class="tree-meta">{esc(r['latest_date'] or 'Nessuna visita')}</span><span class="arrow">→</span></a>''' for r in rows)
    else:
        entries = '<div class="empty"><div class="empty-icon">♧</div><h3>Nessun ulivo trovato</h3><p>Registra il primo albero o cambia i filtri.</p><a class="button" href="/trees/new">Aggiungi un ulivo</a></div>'
    body = f'''<section class="hero"><div><p class="eyebrow">IL TUO REGISTRO</p><h1>Ogni ulivo ha una storia.</h1><p>Tieni traccia delle condizioni degli alberi e degli interventi, stagione dopo stagione.</p></div><a class="button primary" href="/trees/new">+ Aggiungi ulivo</a></section><section class="stats">{cards}</section><section class="panel"><div class="section-head"><div><p class="eyebrow">ANAGRAFICA</p><h2>Gli ulivi</h2></div><span>{len(rows)} risultati</span></div>{search}<div class="tree-list">{entries}</div></section>'''
    return page("Registro", body, notice=notice)


def text_input(name: str, label: str, value: object = "", *, required: bool = False, hint: str = "", type_: str = "text") -> str:
    req = " required" if required else ""
    hint_html = f"<small>{esc(hint)}</small>" if hint else ""
    return f'<label class="field"><span>{esc(label)}{" *" if required else ""}</span><input type="{esc(type_)}" name="{esc(name)}" value="{esc(value)}"{req}>{hint_html}</label>'


def tree_form(values, csrf: str, tree_id: int | None = None, error: str = "") -> str:
    editing = tree_id is not None
    action = f"/trees/{tree_id}/edit" if editing else "/trees/new"
    title = "Modifica ulivo" if editing else "Registra un ulivo"
    fields = text_input("code", "Codice identificativo", values.get("code", ""), required=True, hint="Un codice univoco, per esempio il numero sulla targhetta.")
    fields += text_input("cultivar", "Cultivar", values.get("cultivar", ""), required=True)
    fields += text_input("parcel", "Zona o particella", values.get("parcel", ""), required=True)
    fields += '<div class="grid-two">' + text_input("latitude", "Latitudine", values.get("latitude", ""), hint="Facoltativa, es. 40.12345") + text_input("longitude", "Longitudine", values.get("longitude", ""), hint="Facoltativa, es. 18.12345") + '</div>'
    fields += text_input("planted_year", "Anno d'impianto", values.get("planted_year", ""), type_="number")
    fields += f'<label class="field"><span>Note</span><textarea name="notes" rows="4">{esc(values.get("notes", ""))}</textarea></label>'
    back = f"/trees/{tree_id}" if editing else "/"
    body = f'''<div class="back"><a href="{back}">← Torna al registro</a></div><div class="form-wrap"><p class="eyebrow">ANAGRAFICA</p><h1>{title}</h1><p>Identifica l'albero e la sua posizione. Puoi aggiungere osservazioni e interventi dopo averlo salvato.</p><form class="panel form-panel" method="post" action="{action}"><input type="hidden" name="csrf" value="{esc(csrf)}">{fields}<div class="form-actions"><button class="button primary" type="submit">Salva ulivo</button><a href="{back}">Annulla</a></div></form></div>'''
    return page(title, body, error=error)


def detail(conn, tree_id: int, csrf: str, error: str = "", notice: str = "") -> str | None:
    tree = db.get_tree(conn, tree_id)
    if tree is None:
        return None
    events = db.timeline(conn, tree_id)
    latest = next((e for e in events if e["event_type"] == "observation"), None)
    coords = ""
    if tree["latitude"] is not None:
        maps = f'https://www.openstreetmap.org/?mlat={tree["latitude"]}&mlon={tree["longitude"]}#map=17/{tree["latitude"]}/{tree["longitude"]}'
        coords = f'<a href="{esc(maps)}" target="_blank" rel="noopener noreferrer">{esc(tree["latitude"])}, {esc(tree["longitude"])} ↗</a>'
    facts = f'''<div class="facts"><div><span>Cultivar</span><strong>{esc(tree['cultivar'])}</strong></div><div><span>Zona</span><strong>{esc(tree['parcel'])}</strong></div><div><span>Anno d'impianto</span><strong>{esc(tree['planted_year'] or '—')}</strong></div><div><span>Coordinate</span><strong>{coords or '—'}</strong></div></div>'''
    items = ""
    for e in events:
        observation = e["event_type"] == "observation"
        category = db.HEALTH[e["category"]] if observation else db.ACTIVITIES[e["category"]]
        subtitle = "Osservazione" if observation else "Intervento"
        content = f'<p><b>Sintomi:</b> {esc(e["symptoms"])}</p>' if observation and e["symptoms"] else ""
        content += f'<p>{esc(e["notes"])}</p>' if e["notes"] else ""
        items += f'''<article class="event"><div class="event-dot {"obs" if observation else "act"}"></div><div class="event-body"><div class="event-top"><div><small>{subtitle} · {esc(e['event_date'])}</small><h3>{esc(category)}</h3></div>{badge(e['category']) if observation else ''}</div>{content}</div></article>'''
    if not items:
        items = '<div class="empty compact"><p>Ancora nessun evento. Aggiungi la prima osservazione per iniziare lo storico.</p></div>'
    today = date.today().isoformat()
    observation_form = f'''<form class="panel form-panel" method="post" action="/trees/{tree_id}/observations"><input type="hidden" name="csrf" value="{esc(csrf)}"><h3>Nuova osservazione</h3>{text_input('observed_on', 'Data', today, required=True, type_='date')}<label class="field"><span>Stato di salute *</span><select name="health" required>{''.join(f'<option value="{k}">{esc(v)}</option>' for k,v in db.HEALTH.items())}</select></label>{text_input('symptoms','Sintomi o segnali')}<label class="field"><span>Note</span><textarea name="notes" rows="3" placeholder="Cosa hai notato?"></textarea></label><button class="button primary" type="submit">Salva osservazione</button></form>'''
    activity_form = f'''<form class="panel form-panel" method="post" action="/trees/{tree_id}/activities"><input type="hidden" name="csrf" value="{esc(csrf)}"><h3>Nuovo intervento</h3>{text_input('done_on','Data',today,required=True,type_='date')}<label class="field"><span>Tipo *</span><select name="kind" required>{''.join(f'<option value="{k}">{esc(v)}</option>' for k,v in db.ACTIVITIES.items())}</select></label><label class="field"><span>Descrizione *</span><textarea name="notes" rows="3" required placeholder="Cosa hai fatto?"></textarea></label><button class="button primary" type="submit">Salva intervento</button></form>'''
    body = f'''<div class="back"><a href="/">← Tutti gli ulivi</a></div><section class="detail-head"><div><p class="eyebrow">SCHEDA ULIVO</p><h1>{esc(tree['code'])}</h1><p>{esc(tree['cultivar'])} · {esc(tree['parcel'])}</p></div><div class="detail-actions">{badge(latest['category'] if latest else None)}<a class="button secondary" href="/trees/{tree_id}/edit">Modifica scheda</a></div></section><section class="panel info-panel">{facts}{f'<p class="tree-notes">{esc(tree["notes"])}</p>' if tree['notes'] else ''}</section><section class="detail-grid"><div><div class="section-head"><div><p class="eyebrow">CRONOLOGIA</p><h2>Storico</h2></div><span>{len(events)} eventi</span></div><div class="timeline">{items}</div></div><div class="forms-column">{observation_form}{activity_form}</div></section>'''
    return page(str(tree["code"]), body, notice=notice, error=error)


class AppHandler(BaseHTTPRequestHandler):
    database: Path
    csrf_token: str

    def respond(self, status: int, content: str | bytes, content_type: str = "text/html; charset=utf-8", extra: dict[str, str] | None = None):
        data = content.encode("utf-8") if isinstance(content, str) else content
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, path: str):
        self.respond(303, b"", extra={"Location": path})

    def do_GET(self):
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        args = parse_qs(parsed.query)
        if parsed.path == "/static/style.css":
            self.respond(200, CSS.read_bytes(), "text/css; charset=utf-8")
            return
        with db.connect(self.database) as conn:
            if not parts:
                self.respond(200, dashboard(conn, args.get("q", [""])[0][:100], args.get("health", [""])[0], args.get("saved", [""])[0] and "Salvato con successo."))
            elif parts == ["trees", "new"]:
                self.respond(200, tree_form({}, self.csrf_token))
            elif len(parts) in (2, 3) and parts[0] == "trees" and parts[1].isdigit():
                tree_id = int(parts[1])
                if len(parts) == 3 and parts[2] == "edit":
                    tree = db.get_tree(conn, tree_id)
                    if tree is None:
                        self.respond(404, page("Non trovato", "<h1>Ulivo non trovato</h1>"))
                    else:
                        self.respond(200, tree_form(dict(tree), self.csrf_token, tree_id))
                elif len(parts) == 2:
                    result = detail(conn, tree_id, self.csrf_token, notice="Salvato con successo." if "saved" in args else "")
                    self.respond(200 if result else 404, result or page("Non trovato", "<h1>Ulivo non trovato</h1>"))
                else:
                    self.respond(404, page("Non trovato", "<h1>Pagina non trovata</h1>"))
            elif parts == ["export"]:
                self.export_csv(conn)
            else:
                self.respond(404, page("Non trovato", "<h1>Pagina non trovata</h1>"))

    def do_POST(self):
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= 20000:
            self.respond(413, page("Errore", "<h1>Richiesta troppo grande</h1>"))
            return
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8", "replace"), keep_blank_values=True).items()}
        if not secrets.compare_digest(form.get("csrf", ""), self.csrf_token):
            self.respond(403, page("Errore", "<h1>Richiesta non valida</h1>"))
            return
        with db.connect(self.database) as conn:
            try:
                if parts == ["trees", "new"]:
                    tree_id = db.save_tree(conn, form)
                elif len(parts) == 3 and parts[0] == "trees" and parts[1].isdigit():
                    tree_id = int(parts[1])
                    if parts[2] == "edit":
                        db.save_tree(conn, form, tree_id)
                    elif parts[2] == "observations":
                        db.add_observation(conn, tree_id, form)
                    elif parts[2] == "activities":
                        db.add_activity(conn, tree_id, form)
                    else:
                        self.respond(404, page("Non trovato", "<h1>Pagina non trovata</h1>"))
                        return
                else:
                    self.respond(404, page("Non trovato", "<h1>Pagina non trovata</h1>"))
                    return
            except db.ValidationError as exc:
                if parts == ["trees", "new"]:
                    response = tree_form(form, self.csrf_token, error=str(exc))
                elif len(parts) == 3 and parts[2] == "edit":
                    response = tree_form(form, self.csrf_token, int(parts[1]), error=str(exc))
                else:
                    response = detail(conn, int(parts[1]), self.csrf_token, error=str(exc)) or page("Errore", "<h1>Ulivo non trovato</h1>")
                self.respond(422, response)
                return
            self.redirect(f"/trees/{tree_id}?saved=1")

    def export_csv(self, conn):
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["tipo", "codice_ulivo", "cultivar", "zona", "latitudine", "longitudine", "anno_impianto", "data", "categoria", "sintomi", "note"])
        for tree in db.list_trees(conn):
            base = [tree["code"], tree["cultivar"], tree["parcel"], tree["latitude"], tree["longitude"], tree["planted_year"]]
            writer.writerow(["ulivo", *base, "", "", "", tree["notes"]])
            for event in db.timeline(conn, tree["id"]):
                writer.writerow([event["event_type"], *base, event["event_date"], event["category"], event["symptoms"], event["notes"]])
        self.respond(200, "\ufeff" + out.getvalue(), "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="uliveto-export.csv"'})


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Registro locale per monitorare gli ulivi")
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("ULIVETO_DB", "data/uliveto.sqlite3")), help="Percorso del database SQLite")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    handler = type("UlivetoHandler", (AppHandler,), {"database": args.db, "csrf_token": secrets.token_urlsafe(32)})
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Uliveto è pronto su http://127.0.0.1:{args.port}  (Ctrl+C per fermarlo)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nUliveto fermato.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
