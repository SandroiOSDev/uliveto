"""Interfaccia web locale di Uliveto, senza dipendenze esterne."""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
import secrets
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import db, sensors

CSS = Path(__file__).with_name("static").joinpath("style.css")


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def page(title: str, body: str, *, notice: str = "", error: str = "") -> str:
    message = f'<div class="notice">{esc(notice)}</div>' if notice else ""
    message += f'<div class="error" role="alert">{esc(error)}</div>' if error else ""
    return f"""<!doctype html><html lang="it"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta name="description" content="Registro locale del tuo uliveto">
    <title>{esc(title)} · Uliveto</title><link rel="stylesheet" href="/static/style.css"><link rel="stylesheet" href="/static/sensors.css"></head>
    <body><header class="topbar"><a class="brand" href="/">◉ <span>Uliveto</span></a>
    <nav><a href="/">Registro</a><a href="/sensors">Sensori</a><a href="/trees/new">Nuovo ulivo</a><a href="/export">Esporta CSV</a></nav></header>
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


def sensor_badge(mode: str) -> str:
    return f'<span class="badge {"attenzione" if mode == "synthetic" else "sano"}">{"Dati sintetici" if mode == "synthetic" else "Dati reali"}</span>'


def sparkline(readings) -> str:
    values = [r["moisture_pct"] for r in reversed(readings)]
    if len(values) < 2:
        return '<div class="chart-empty">Servono almeno due letture per vedere l’andamento.</div>'
    points = " ".join(f"{round(10 + i * 280 / (len(values) - 1), 1)},{round(100 - v * .85, 1)}" for i, v in enumerate(values))
    return f'<svg class="sparkline" viewBox="0 0 300 110" role="img" aria-label="Andamento umidità del suolo"><line x1="10" y1="83" x2="290" y2="83" stroke="#e5e8df"/><polyline points="{points}" fill="none" stroke="#50795c" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/></svg>'


def sensors_dashboard(conn, notice: str = "") -> str:
    stations = sensors.list_stations(conn)
    counts = {"total": len(stations), "dry": sum(sensors.status(s) == "Sotto soglia" for s in stations), "stale": sum(sensors.status(s) == "Dati non recenti" for s in stations), "empty": sum(sensors.status(s) == "Senza dati" for s in stations)}
    cards = f'''<div class="sensor-stats"><div><strong>{counts['total']}</strong><span>Punti di misura</span></div><div><strong>{counts['dry']}</strong><span>Sotto soglia</span></div><div><strong>{counts['stale']}</strong><span>Dati non recenti</span></div><div><strong>{counts['empty']}</strong><span>Senza dati</span></div></div>'''
    rows = ""
    for s in stations:
        label = sensors.status(s)
        status_class = "alert" if label == "Sotto soglia" else "muted" if label != "Nella norma" else "good"
        measure = f'{s["latest_moisture"]:.1f}%' if s["latest_moisture"] is not None else "—"
        readings = sensors.recent_readings(conn, s["id"], s["mode"], 15)
        rows += f'''<a class="sensor-card" href="/sensors/{s['id']}"><div class="sensor-card-top"><div><small>{esc(s['parcel'])} · {s['tree_count']} ulivi nella zona</small><h3>{esc(s['code'])}</h3></div>{sensor_badge(s['mode'])}</div><div class="sensor-reading"><strong>{measure}</strong><span>umidità del terreno</span></div>{sparkline(readings)}<div class="sensor-card-foot"><span class="sensor-status {status_class}">{esc(label)}</span><small>{esc(s['latest_at'][:16].replace('T', ' ') if s['latest_at'] else 'Nessuna lettura')} UTC</small></div></a>'''
    if not rows:
        rows = '<div class="empty"><div class="empty-icon">◌</div><h3>Nessun punto di misura</h3><p>Aggiungi un punto strategico del terreno per iniziare.</p><a class="button primary" href="/sensors/new">Aggiungi punto</a></div>'
    body = f'''<section class="hero sensor-hero"><div><p class="eyebrow">TERRENO · SENSORI</p><h1>Il terreno, sotto osservazione.</h1><p>Leggi umidità e temperatura nei punti di misura. Le soglie sono segnali operativi, non diagnosi della salute degli ulivi.</p></div><a class="button primary" href="/sensors/new">+ Nuovo punto</a></section>{cards}<div class="section-head"><div><p class="eyebrow">DASHBOARD</p><h2>Punti di misura</h2></div><a href="/sensors/export">Esporta letture CSV ↓</a></div><div class="sensor-grid">{rows}</div>'''
    return page("Sensori", body, notice=notice)


def station_form(values, csrf: str, station_id: int | None = None, error: str = "") -> str:
    editing = station_id is not None
    title = "Modifica punto di misura" if editing else "Nuovo punto di misura"
    action = f"/sensors/{station_id}/edit" if editing else "/sensors/new"
    mode = values.get("mode", "synthetic")
    fields = text_input("code", "Codice punto", values.get("code", ""), required=True, hint="Un codice univoco da usare anche dal gateway del sensore.")
    fields += text_input("parcel", "Zona o particella", values.get("parcel", ""), required=True, hint="Usa lo stesso nome zona delle schede degli ulivi da associare.")
    fields += '<div class="grid-two">' + text_input("latitude", "Latitudine", values.get("latitude", "")) + text_input("longitude", "Longitudine", values.get("longitude", "")) + '</div>'
    fields += '<div class="grid-two">' + text_input("depth_cm", "Profondità (cm)", values.get("depth_cm", ""), type_="number") + text_input("dry_threshold", "Soglia umidità (%)", values.get("dry_threshold", 20), required=True, hint="Da calibrare per terreno e sensore.") + '</div>'
    fields += f'''<label class="field"><span>Origine dati *</span><select name="mode"><option value="synthetic" {'selected' if mode == 'synthetic' else ''}>Sintetici, per la fase iniziale</option><option value="real" {'selected' if mode == 'real' else ''}>Reali, da gateway/sensore</option></select><small>Passando a dati reali, la dashboard mostra solo le nuove letture reali. Lo storico sintetico resta nel database.</small></label>'''
    fields += f'<label class="field"><span>Note sulla posizione</span><textarea name="notes" rows="3">{esc(values.get("notes", ""))}</textarea></label>'
    body = f'''<div class="back"><a href="/sensors">← Dashboard sensori</a></div><div class="form-wrap"><p class="eyebrow">RETE DI MONITORAGGIO</p><h1>{title}</h1><p>Definisci un punto rappresentativo del terreno. Può servire una zona con più alberi.</p><form class="panel form-panel" method="post" action="{action}"><input type="hidden" name="csrf" value="{esc(csrf)}">{fields}<div class="form-actions"><button class="button primary" type="submit">Salva punto</button><a href="/sensors">Annulla</a></div></form></div>'''
    return page(title, body, error=error)


def station_detail(conn, station_id: int, csrf: str, notice: str = "", error: str = "") -> str | None:
    station = sensors.get_station(conn, station_id)
    if station is None:
        return None
    readings = sensors.recent_readings(conn, station_id, station["mode"])
    trees = conn.execute("SELECT id,code FROM trees WHERE parcel=? COLLATE NOCASE ORDER BY code COLLATE NOCASE", (station["parcel"],)).fetchall()
    tree_links = ", ".join(f'<a href="/trees/{t["id"]}">{esc(t["code"])}</a>' for t in trees) or "Nessun ulivo registrato in questa zona"
    latest = readings[0] if readings else None
    current = next((s for s in sensors.list_stations(conn) if s["id"] == station_id), None)
    state = sensors.status(current)
    history = "".join(f'''<tr><td>{esc(r['measured_at'][:16].replace('T', ' '))} UTC</td><td>{r['moisture_pct']:.1f}%</td><td>{f"{r['temperature_c']:.1f} °C" if r['temperature_c'] is not None else '—'}</td><td>{"Sintetico" if r['source'] == 'synthetic' else 'Reale'}</td></tr>''' for r in readings)
    if not history:
        history = '<tr><td colspan="4">Nessuna lettura per questa modalità.</td></tr>'
    generate = f'''<form method="post" action="/sensors/{station_id}/generate"><input type="hidden" name="csrf" value="{esc(csrf)}"><button class="button secondary" type="submit">Genera 7 giorni sintetici</button></form>''' if station["mode"] == "synthetic" else '<p class="api-hint">In attesa di letture dal gateway. Configura <code>ULIVETO_INGEST_TOKEN</code> sul computer che esegue l’app.</p>'
    body = f'''<div class="back"><a href="/sensors">← Dashboard sensori</a></div><section class="detail-head"><div><p class="eyebrow">PUNTO DI MISURA</p><h1>{esc(station['code'])}</h1><p>{esc(station['parcel'])}</p></div><div class="detail-actions">{sensor_badge(station['mode'])}<a class="button secondary" href="/sensors/{station_id}/edit">Modifica punto</a></div></section><section class="panel info-panel"><div class="facts"><div><span>Stato letture</span><strong>{esc(state)}</strong></div><div><span>Ultima umidità</span><strong>{f"{latest['moisture_pct']:.1f}%" if latest else '—'}</strong></div><div><span>Ultima temperatura</span><strong>{f"{latest['temperature_c']:.1f} °C" if latest and latest['temperature_c'] is not None else '—'}</strong></div><div><span>Soglia configurata</span><strong>{station['dry_threshold']:.1f}%</strong></div></div><p class="tree-notes"><b>Ulivi nella zona:</b> {tree_links}</p>{f'<p class="tree-notes">{esc(station["notes"])}</p>' if station['notes'] else ''}</section><section class="detail-grid"><div><div class="section-head"><div><p class="eyebrow">ANDAMENTO</p><h2>Umidità del suolo</h2></div><span>Ultime {len(readings)} letture</span></div><div class="panel chart-panel">{sparkline(readings)}<p>Percentuale di umidità misurata o simulata; valori e soglia richiedono calibrazione sul campo.</p></div><div class="section-head readings-head"><div><p class="eyebrow">STORICO</p><h2>Letture</h2></div></div><div class="panel table-wrap"><table><thead><tr><th>Data e ora</th><th>Umidità</th><th>Temperatura</th><th>Origine</th></tr></thead><tbody>{history}</tbody></table></div></div><div class="forms-column"><div class="panel form-panel"><h3>Origine dei dati</h3><p>{'Queste letture sono generate per provare la dashboard. Non rappresentano misure del tuo terreno.' if station['mode'] == 'synthetic' else 'Il punto riceve letture reali dall’interfaccia di acquisizione locale.'}</p>{generate}</div></div></section>'''
    return page(str(station["code"]), body, notice=notice, error=error)


class AppHandler(BaseHTTPRequestHandler):
    database: Path
    csrf_token: str
    ingest_token: str = ""

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
        if parsed.path == "/static/sensors.css":
            self.respond(200, CSS.with_name("sensors.css").read_bytes(), "text/css; charset=utf-8")
            return
        with db.connect(self.database) as conn:
            if not parts:
                self.respond(200, dashboard(conn, args.get("q", [""])[0][:100], args.get("health", [""])[0], args.get("saved", [""])[0] and "Salvato con successo."))
            elif parts == ["trees", "new"]:
                self.respond(200, tree_form({}, self.csrf_token))
            elif parts == ["sensors"]:
                self.respond(200, sensors_dashboard(conn, "Salvato con successo." if "saved" in args else ""))
            elif parts == ["sensors", "export"]:
                self.export_sensor_csv(conn)
            elif parts == ["sensors", "new"]:
                self.respond(200, station_form({}, self.csrf_token))
            elif len(parts) in (2, 3) and parts[0] == "sensors" and parts[1].isdigit():
                station_id = int(parts[1])
                if len(parts) == 3 and parts[2] == "edit":
                    station = sensors.get_station(conn, station_id)
                    if station is None:
                        self.respond(404, page("Non trovato", "<h1>Punto di misura non trovato</h1>"))
                    else:
                        self.respond(200, station_form(dict(station), self.csrf_token, station_id))
                elif len(parts) == 2:
                    result = station_detail(conn, station_id, self.csrf_token, notice="Salvato con successo." if "saved" in args else "")
                    self.respond(200 if result else 404, result or page("Non trovato", "<h1>Punto di misura non trovato</h1>"))
                else:
                    self.respond(404, page("Non trovato", "<h1>Pagina non trovata</h1>"))
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
        if parts == ["api", "v1", "readings"]:
            self.ingest_reading()
            return
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
                    destination = f"/trees/{tree_id}?saved=1"
                elif parts == ["sensors", "new"]:
                    station_id = sensors.save_station(conn, form)
                    destination = f"/sensors/{station_id}?saved=1"
                elif len(parts) == 3 and parts[0] == "sensors" and parts[1].isdigit():
                    station_id = int(parts[1])
                    if parts[2] == "edit":
                        sensors.save_station(conn, form, station_id)
                    elif parts[2] == "generate":
                        sensors.generate_synthetic(conn, station_id)
                    else:
                        self.respond(404, page("Non trovato", "<h1>Pagina non trovata</h1>"))
                        return
                    destination = f"/sensors/{station_id}?saved=1"
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
                    destination = f"/trees/{tree_id}?saved=1"
                else:
                    self.respond(404, page("Non trovato", "<h1>Pagina non trovata</h1>"))
                    return
            except db.ValidationError as exc:
                if parts == ["trees", "new"]:
                    response = tree_form(form, self.csrf_token, error=str(exc))
                elif parts == ["sensors", "new"]:
                    response = station_form(form, self.csrf_token, error=str(exc))
                elif len(parts) == 3 and parts[0] == "sensors":
                    response = station_form(form, self.csrf_token, int(parts[1]), error=str(exc)) if parts[2] == "edit" else station_detail(conn, int(parts[1]), self.csrf_token, error=str(exc))
                elif len(parts) == 3 and parts[2] == "edit":
                    response = tree_form(form, self.csrf_token, int(parts[1]), error=str(exc))
                else:
                    response = detail(conn, int(parts[1]), self.csrf_token, error=str(exc)) or page("Errore", "<h1>Ulivo non trovato</h1>")
                self.respond(422, response or page("Errore", "<h1>Elemento non trovato</h1>"))
                return
            self.redirect(destination)

    def ingest_reading(self):
        def reply(status: int, payload: dict):
            self.respond(status, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")

        if not self.ingest_token:
            reply(503, {"error": "Acquisizione disabilitata: configura ULIVETO_INGEST_TOKEN."})
            return
        authorization = self.headers.get("Authorization", "")
        if not secrets.compare_digest(authorization, f"Bearer {self.ingest_token}"):
            reply(401, {"error": "Token non valido."})
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            reply(415, {"error": "Invia application/json."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= 4096:
            reply(413, {"error": "Dimensione richiesta non valida."})
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            reply(400, {"error": "JSON non valido."})
            return
        if not isinstance(payload, dict):
            reply(400, {"error": "Invia un oggetto JSON."})
            return
        with db.connect(self.database) as conn:
            try:
                inserted = sensors.add_reading(conn, payload)
            except db.ValidationError as exc:
                reply(422, {"error": str(exc)})
                return
        reply(201 if inserted else 200, {"status": "created" if inserted else "duplicate"})

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

    def export_sensor_csv(self, conn):
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["codice_punto", "zona", "origine", "data_ora_utc", "umidita_pct", "temperatura_c", "soglia_secco_pct"])
        rows = conn.execute("""
            SELECT s.code,s.parcel,r.source,r.measured_at,r.moisture_pct,r.temperature_c,s.dry_threshold
            FROM readings r JOIN stations s ON s.id=r.station_id
            ORDER BY s.code COLLATE NOCASE,r.measured_at DESC
        """).fetchall()
        for row in rows:
            writer.writerow(tuple(row))
        self.respond(200, "\ufeff" + out.getvalue(), "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="uliveto-sensori.csv"'})


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Registro locale per monitorare gli ulivi")
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("ULIVETO_DB", "data/uliveto.sqlite3")), help="Percorso del database SQLite")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    handler = type("UlivetoHandler", (AppHandler,), {"database": args.db, "csrf_token": secrets.token_urlsafe(32), "ingest_token": os.environ.get("ULIVETO_INGEST_TOKEN", "")})
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
