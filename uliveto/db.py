"""Persistenza SQLite e regole per il registro dell'uliveto."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

HEALTH = {"sano": "Sano", "attenzione": "Da osservare", "critico": "Critico"}
ACTIVITIES = {"potatura": "Potatura", "irrigazione": "Irrigazione", "concimazione": "Concimazione", "trattamento": "Trattamento", "raccolta": "Raccolta", "altro": "Altro"}

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS trees (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    cultivar TEXT NOT NULL,
    parcel TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    planted_year INTEGER,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY,
    tree_id INTEGER NOT NULL REFERENCES trees(id) ON DELETE CASCADE,
    observed_on TEXT NOT NULL,
    health TEXT NOT NULL CHECK (health IN ('sano', 'attenzione', 'critico')),
    symptoms TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS observations_tree_date ON observations(tree_id, observed_on DESC, id DESC);
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    tree_id INTEGER NOT NULL REFERENCES trees(id) ON DELETE CASCADE,
    done_on TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('potatura', 'irrigazione', 'concimazione', 'trattamento', 'raccolta', 'altro')),
    notes TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS activities_tree_date ON activities(tree_id, done_on DESC, id DESC);
"""


class ValidationError(ValueError):
    pass


@contextmanager
def connect(path: str | Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def required(value: str, label: str, limit: int = 200) -> str:
    value = value.strip()
    if not value:
        raise ValidationError(f"{label}: campo obbligatorio.")
    if len(value) > limit:
        raise ValidationError(f"{label}: massimo {limit} caratteri.")
    return value


def optional(value: str, label: str, limit: int = 2000) -> str:
    value = value.strip()
    if len(value) > limit:
        raise ValidationError(f"{label}: massimo {limit} caratteri.")
    return value


def coordinate(value: str, label: str, low: float, high: float) -> float | None:
    value = value.strip().replace(",", ".")
    if not value:
        return None
    try:
        result = float(value)
    except ValueError as exc:
        raise ValidationError(f"{label}: inserisci un numero valido.") from exc
    if not low <= result <= high:
        raise ValidationError(f"{label}: valore fuori intervallo ({low}–{high}).")
    return result


def valid_date(value: str, label: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{label}: data non valida.") from exc
    if parsed > date.today():
        raise ValidationError(f"{label}: la data non può essere futura.")
    return parsed.isoformat()


def tree_fields(form: dict[str, str]) -> tuple:
    code = required(form.get("code", ""), "Codice", 40)
    cultivar = required(form.get("cultivar", ""), "Cultivar", 100)
    parcel = required(form.get("parcel", ""), "Zona", 100)
    latitude = coordinate(form.get("latitude", ""), "Latitudine", -90, 90)
    longitude = coordinate(form.get("longitude", ""), "Longitudine", -180, 180)
    if (latitude is None) != (longitude is None):
        raise ValidationError("Inserisci entrambe le coordinate o lasciale vuote.")
    raw_year = form.get("planted_year", "").strip()
    year = None
    if raw_year:
        if not raw_year.isdigit() or not 1800 <= int(raw_year) <= date.today().year:
            raise ValidationError("Anno d'impianto: inserisci un anno valido.")
        year = int(raw_year)
    notes = optional(form.get("notes", ""), "Note")
    return code, cultivar, parcel, latitude, longitude, year, notes


def save_tree(conn: sqlite3.Connection, form: dict[str, str], tree_id: int | None = None) -> int:
    fields = tree_fields(form)
    try:
        if tree_id is None:
            cur = conn.execute("INSERT INTO trees (code,cultivar,parcel,latitude,longitude,planted_year,notes) VALUES (?,?,?,?,?,?,?)", fields)
            return cur.lastrowid
        cur = conn.execute("UPDATE trees SET code=?,cultivar=?,parcel=?,latitude=?,longitude=?,planted_year=?,notes=? WHERE id=?", (*fields, tree_id))
        if cur.rowcount == 0:
            raise ValidationError("Ulivo non trovato.")
        return tree_id
    except sqlite3.IntegrityError as exc:
        raise ValidationError("Questo codice è già assegnato a un altro ulivo.") from exc


def add_observation(conn: sqlite3.Connection, tree_id: int, form: dict[str, str]) -> None:
    if conn.execute("SELECT 1 FROM trees WHERE id=?", (tree_id,)).fetchone() is None:
        raise ValidationError("Ulivo non trovato.")
    observed_on = valid_date(form.get("observed_on", ""), "Data osservazione")
    health = form.get("health", "")
    if health not in HEALTH:
        raise ValidationError("Seleziona uno stato di salute valido.")
    symptoms = optional(form.get("symptoms", ""), "Sintomi", 500)
    notes = optional(form.get("notes", ""), "Note")
    conn.execute("INSERT INTO observations (tree_id,observed_on,health,symptoms,notes) VALUES (?,?,?,?,?)", (tree_id, observed_on, health, symptoms, notes))


def add_activity(conn: sqlite3.Connection, tree_id: int, form: dict[str, str]) -> None:
    if conn.execute("SELECT 1 FROM trees WHERE id=?", (tree_id,)).fetchone() is None:
        raise ValidationError("Ulivo non trovato.")
    done_on = valid_date(form.get("done_on", ""), "Data intervento")
    kind = form.get("kind", "")
    if kind not in ACTIVITIES:
        raise ValidationError("Seleziona un tipo di intervento valido.")
    notes = required(form.get("notes", ""), "Descrizione intervento", 2000)
    conn.execute("INSERT INTO activities (tree_id,done_on,kind,notes) VALUES (?,?,?,?)", (tree_id, done_on, kind, notes))


def list_trees(conn: sqlite3.Connection, query: str = "", health: str = ""):
    params: list[str] = []
    where = []
    if query:
        where.append("(t.code LIKE ? OR t.cultivar LIKE ? OR t.parcel LIKE ?)")
        params.extend([f"%{query}%"] * 3)
    if health == "mai_osservato":
        where.append("o.health IS NULL")
    elif health in HEALTH:
        where.append("o.health = ?")
        params.append(health)
    clause = " WHERE " + " AND ".join(where) if where else ""
    return conn.execute("""
        SELECT t.*, o.health AS latest_health, o.observed_on AS latest_date,
               (SELECT COUNT(*) FROM observations WHERE tree_id=t.id) AS observation_count,
               (SELECT COUNT(*) FROM activities WHERE tree_id=t.id) AS activity_count
        FROM trees t LEFT JOIN observations o ON o.id=(
          SELECT id FROM observations WHERE tree_id=t.id ORDER BY observed_on DESC,id DESC LIMIT 1
        )
    """ + clause + " ORDER BY t.code COLLATE NOCASE", params).fetchall()


def get_tree(conn: sqlite3.Connection, tree_id: int):
    return conn.execute("SELECT * FROM trees WHERE id=?", (tree_id,)).fetchone()


def timeline(conn: sqlite3.Connection, tree_id: int):
    return conn.execute("""
      SELECT 'observation' AS event_type, id, observed_on AS event_date, health AS category, symptoms, notes
      FROM observations WHERE tree_id=?
      UNION ALL
      SELECT 'activity', id, done_on, kind, '' AS symptoms, notes
      FROM activities WHERE tree_id=?
      ORDER BY event_date DESC, id DESC
    """, (tree_id, tree_id)).fetchall()


def summary(conn: sqlite3.Connection) -> dict[str, int]:
    rows = list_trees(conn)
    return {"total": len(rows), "sano": sum(r["latest_health"] == "sano" for r in rows), "attenzione": sum(r["latest_health"] == "attenzione" for r in rows), "critico": sum(r["latest_health"] == "critico" for r in rows), "mai_osservato": sum(r["latest_health"] is None for r in rows)}
