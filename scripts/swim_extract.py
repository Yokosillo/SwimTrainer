#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Extraccion de natacion: convierte los 854 FIT en tablas normalizadas.

Salidas (en data/derived/, nunca sobre los originales):
  swims_laps.csv     una fila por lap (=repeticion o descanso)
  swims_lengths.csv  una fila por largo de piscina
  swims_session.csv  una fila por sesion (resumen + trazabilidad del fichero)
Solo LEE los FIT originales.
"""
from __future__ import annotations

import csv
import gzip
import os
import sys
from collections import Counter

import fitdecode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORT = os.path.join(ROOT, "data", "export_2026-10-11")
ACTS = os.path.join(EXPORT, "activities")
DERIVED = os.path.join(ROOT, "data", "derived")
os.makedirs(DERIVED, exist_ok=True)


def gv(frame, name, default=None):
    try:
        return frame.get_value(name, fallback=default)
    except KeyError:
        return default


def enum(frame, name):
    v = gv(frame, name)
    if v is None:
        return None
    return str(getattr(v, "value", v))


def read_activities():
    with open(os.path.join(EXPORT, "activities.csv"), encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    header = rows[0]
    idx = {}
    for i, h in enumerate(header):
        idx.setdefault(h, i)

    def col(r, name):
        i = idx.get(name)
        return r[i] if i is not None and i < len(r) else ""
    return col, [r for r in rows[1:] if r and r[0].strip()]


def dist_m(col, r):
    """Distancia en metros: la 2a columna 'Distancia' del CSV viene siempre en metros."""
    v = col(r, "Distancia")
    try:
        first = float(v.replace(",", "."))
    except ValueError:
        first = None
    # busca la ultima ocurrencia de 'Distancia' en la fila
    return first


def main():
    col, recs = read_activities()
    swims = [r for r in recs if col(r, "Tipo de actividad").strip() == "Natación"]
    print(f"Nataciones en CSV: {len(swims)}")

    laps_out, lens_out, sess_out = [], [], []
    errors = []
    for i, r in enumerate(swims, 1):
        aid = col(r, "ID de actividad")
        base = os.path.basename(col(r, "Nombre del archivo").strip())
        path = os.path.join(ACTS, base)
        fecha = col(r, "Fecha de la actividad")
        # la 2a 'Distancia' del CSV esta en metros (validado)
        csv_m = None
        for j, v in enumerate(r):
            if j == 0:
                continue
        try:
            pass
        except Exception:
            pass
        n_lap = 0
        opener = gzip.open
        try:
            with opener(path, "rb") as fh:
                with fitdecode.FitReader(fh) as fit:
                    for fr in fit:
                        if fr.frame_type != fitdecode.FIT_FRAME_DATA:
                            continue
                        if fr.name == "length":
                            lens_out.append({
                                "swim_id": aid, "fecha": fecha, "fichero": base,
                                "len_idx": gv(fr, "message_index"),
                                "start_time": gv(fr, "start_time"),
                                "tipo": enum(fr, "length_type"),
                                "estilo": enum(fr, "swim_stroke"),
                                "timer_s": gv(fr, "total_timer_time"),
                                "elapsed_s": gv(fr, "total_elapsed_time"),
                                "brazadas": gv(fr, "total_strokes"),
                                "cadencia": gv(fr, "avg_swimming_cadence"),
                                "vel_m_s": gv(fr, "avg_speed"),
                            })
                        elif fr.name == "lap":
                            n_lap += 1
                            laps_out.append({
                                "swim_id": aid, "fecha": fecha, "fichero": base,
                                "lap_idx": gv(fr, "message_index"),
                                "start_time": gv(fr, "start_time"),
                                "dist_m": gv(fr, "total_distance"),
                                "timer_s": gv(fr, "total_timer_time"),
                                "elapsed_s": gv(fr, "total_elapsed_time"),
                                "n_largos": gv(fr, "num_lengths"),
                                "n_largos_activos": gv(fr, "num_active_lengths"),
                                "primer_largo_idx": gv(fr, "first_length_index"),
                                "estilo": enum(fr, "swim_stroke"),
                                "hr_media": gv(fr, "avg_heart_rate"),
                                "hr_max": gv(fr, "max_heart_rate"),
                                "brazadas": gv(fr, "total_strokes"),
                                "dist_brazada": gv(fr, "avg_stroke_distance"),
                                "disparador": enum(fr, "lap_trigger"),
                                "intensidad": enum(fr, "intensity"),
                            })
                        elif fr.name == "session":
                            sess_out.append({
                                "swim_id": aid, "fecha": fecha, "fichero": base,
                                "nombre": col(r, "Nombre de la actividad"),
                                "inicio": str(gv(fr, "start_time")),
                                "dist_m": gv(fr, "total_distance"),
                                "timer_s": gv(fr, "total_timer_time"),
                                "elapsed_s": gv(fr, "total_elapsed_time"),
                                "largo_piscina": gv(fr, "pool_length"),
                                "unidad_piscina": enum(fr, "pool_length_unit"),
                                "sub_sport": enum(fr, "sub_sport"),
                                "n_largos": gv(fr, "num_lengths"),
                                "n_largos_activos": gv(fr, "num_active_lengths"),
                                "n_laps": gv(fr, "num_laps"),
                                "brazadas": gv(fr, "total_strokes"),
                                "hr_media": gv(fr, "avg_heart_rate"),
                                "hr_max": gv(fr, "max_heart_rate"),
                                "calorias": gv(fr, "total_calories"),
                                "csv_dist_col1": col(r, "Distancia"),
                                "csv_mov_s": col(r, "Tiempo en movimiento"),
                                "csv_largo": col(r, "Largo de la piscina"),
                            })
        except Exception as e:  # noqa: BLE001
            errors.append((aid, base, f"{type(e).__name__}: {e}"))
        if i % 100 == 0:
            print(f"  ... {i}/{len(swims)}", flush=True)

    def dump(path, rows):
        if not rows:
            print("vacio:", path)
            return
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"escrito {path}: {len(rows)} filas")

    dump(os.path.join(DERIVED, "swims_session.csv"), sess_out)
    dump(os.path.join(DERIVED, "swims_laps.csv"), laps_out)
    dump(os.path.join(DERIVED, "swims_lengths.csv"), lens_out)
    print("errores:", errors[:10], "... total", len(errors))
    print("sesiones con sesion FIT:", len(sess_out), "| laps:", len(laps_out), "| largos:", len(lens_out))


if __name__ == "__main__":
    main()
