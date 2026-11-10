"""Punti di misura, letture e generazione esplicita di dati sintetici."""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta, timezone

from .db import ValidationError, coordinate, optional, required


def station_fields(form: dict[str, str]) -> tuple:
    code = required(str(form.get("code", "")), "Codice punto", 40)
    parcel = required(str(form.get("parcel", "")), "Zona", 100)
    latitude = coordinate(str(form.get("latitude", "")), "Latitudine", -90, 90)
    longitude = coordinate(str(form.get("longitude", "")), "Longitudine", -180, 180)
    if (latitude is None) != (longitude is None):
        raise ValidationError("Inserisci entrambe le coordinate o lasciale vuote.")
    depth_raw = str(form.get("depth_cm", "")).strip()
    depth = None
    if depth_raw:
        if not depth_raw.isdigit() or not 1 <= int(depth_raw) <= 300:
            raise ValidationError("Profondità: inserisci un valore tra 1 e 300 cm.")
        depth = int(depth_raw)
    mode = str(form.get("mode", ""))
    if mode not in ("synthetic", "real"):
        raise ValidationError("Seleziona una modalità valida.")
    try:
        threshold = float(str(form.get("dry_threshold", "")).replace(",", "."))
    except ValueError as exc:
        raise ValidationError("Soglia di umidità non valida.") from exc
    if not math.isfinite(threshold) or not 0 <= threshold <= 100:
        raise ValidationError("Soglia di umidità: valore tra 0 e 100%.")
    notes = optional(str(form.get("notes", "")), "Note")
    return code, parcel, latitude, longitude, depth, mode, threshold, notes


def save_station(conn: sqlite3.Connection, form: dict[str, str], station_id: int | None = None) -> int:
    fields = station_fields(form)
    try:
        if station_id is None:
            cur = conn.execute("INSERT INTO stations (code,parcel,latitude,longitude,depth_cm,mode,dry_threshold,notes) VALUES (?,?,?,?,?,?,?,?)", fields)
            return cur.lastrowid
        cur = conn.execute("UPDATE stations SET code=?,parcel=?,latitude=?,longitude=?,depth_cm=?,mode=?,dry_threshold=?,notes=? WHERE id=?", (*fields, station_id))
        if cur.rowcount == 0:
            raise ValidationError("Punto di misura non trovato.")
        return station_id
    except sqlite3.IntegrityError as exc:
        raise ValidationError("Questo codice è già assegnato a un altro punto.") from exc


def parse_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("measured_at: usa una data ISO 8601 con fuso orario.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError("measured_at: specifica il fuso orario.")
    now = datetime.now(timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    if parsed > now + timedelta(minutes=5):
        raise ValidationError("measured_at: data futura non ammessa.")
    if parsed < now - timedelta(days=3650):
        raise ValidationError("measured_at: data troppo vecchia.")
    return parsed.isoformat(timespec="seconds")


def finite_number(value: object, label: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"{label}: numero non valido.") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise ValidationError(f"{label}: valore fuori intervallo ({low}–{high}).")
    return number


def add_reading(conn: sqlite3.Connection, payload: dict, source: str = "real") -> bool:
    code = required(str(payload.get("station_code", "")), "station_code", 40)
    station = conn.execute("SELECT * FROM stations WHERE code=? COLLATE NOCASE", (code,)).fetchone()
    if station is None:
        raise ValidationError("Punto di misura non trovato.")
    if station["mode"] != source:
        raise ValidationError(f"Il punto è in modalità {station['mode']}; cambiala prima di inviare letture {source}.")
    measured_at = parse_time(str(payload.get("measured_at", "")))
    moisture = finite_number(payload.get("moisture_pct"), "moisture_pct", 0, 100)
    temperature = payload.get("temperature_c")
    temperature = None if temperature is None or temperature == "" else finite_number(temperature, "temperature_c", -40, 80)
    cur = conn.execute("INSERT OR IGNORE INTO readings (station_id,measured_at,moisture_pct,temperature_c,source) VALUES (?,?,?,?,?)", (station["id"], measured_at, moisture, temperature, source))
    return cur.rowcount > 0


def generate_synthetic(conn: sqlite3.Connection, station_id: int, now: datetime | None = None) -> int:
    station = conn.execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone()
    if station is None:
        raise ValidationError("Punto di misura non trovato.")
    if station["mode"] != "synthetic":
        raise ValidationError("I dati sintetici sono disponibili solo per punti in modalità simulazione.")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    inserted = 0
    for index in range(15):
        measured = (now - timedelta(hours=12 * (14 - index))).isoformat(timespec="seconds")
        moisture = round(max(5, min(80, 36 - index * .9 + 6 * math.sin(index * .75 + station_id))), 1)
        temperature = round(18 + 6 * math.sin(index * .5 + station_id), 1)
        cur = conn.execute("INSERT OR IGNORE INTO readings (station_id,measured_at,moisture_pct,temperature_c,source) VALUES (?,?,?,?, 'synthetic')", (station_id, measured, moisture, temperature))
        inserted += cur.rowcount
    return inserted


def list_stations(conn: sqlite3.Connection):
    return conn.execute("""
        SELECT s.*, r.measured_at AS latest_at, r.moisture_pct AS latest_moisture,
               r.temperature_c AS latest_temperature, r.source AS latest_source,
               (SELECT COUNT(*) FROM trees t WHERE t.parcel=s.parcel COLLATE NOCASE) AS tree_count
        FROM stations s LEFT JOIN readings r ON r.id=(
            SELECT id FROM readings WHERE station_id=s.id AND source=s.mode
            ORDER BY measured_at DESC,id DESC LIMIT 1
        ) ORDER BY s.code COLLATE NOCASE
    """).fetchall()


def get_station(conn: sqlite3.Connection, station_id: int):
    return conn.execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone()


def recent_readings(conn: sqlite3.Connection, station_id: int, source: str, limit: int = 60):
    return conn.execute("SELECT * FROM readings WHERE station_id=? AND source=? ORDER BY measured_at DESC,id DESC LIMIT ?", (station_id, source, limit)).fetchall()


def status(station, now: datetime | None = None) -> str:
    if station["latest_at"] is None:
        return "Senza dati"
    now = now or datetime.now(timezone.utc)
    last = datetime.fromisoformat(station["latest_at"])
    if now - last > timedelta(hours=48):
        return "Dati non recenti"
    if station["latest_moisture"] < station["dry_threshold"]:
        return "Sotto soglia"
    return "Nella norma"
