#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Auditoria 03: barrido completo de los FIT.

- Natacion (854): largo de piscina, numero de largos, numero de laps,
  tipos de largo (activo/reposo), estilos, disparador de lap.
- Entrenamiento/gimnasio (40): laps, intensidad, ciclos.
- Ficheros sin extension reconocida.
Genera informes/audit_03_fit_sweep.csv (+ resumen por consola).
Solo LEE.
"""
from __future__ import annotations

import csv
import gzip
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORT = os.path.join(ROOT, "data", "export_2026-10-11")
OUT = os.path.join(ROOT, "informes")
ACTS = os.path.join(EXPORT, "activities")
os.makedirs(OUT, exist_ok=True)

import fitdecode  # noqa: E402


def load_csv():
    with open(os.path.join(EXPORT, "activities.csv"), encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    header = rows[0]
    idx = {}
    for i, h in enumerate(header):
        idx.setdefault(h, i)
    recs = [r for r in rows[1:] if r and r[0].strip()]
    return idx, recs


def scan(path):
    """Devuelve un dict con lo relevante del FIT."""
    d = {
        "n_length": 0, "n_length_active": 0, "n_length_idle": 0,
        "n_lap": 0, "pool_length": None, "pool_unit": None,
        "lap_triggers": Counter(), "strokes": Counter(), "sub_sport": None,
        "num_active_lengths": None, "total_strokes": None,
        "total_distance": None, "total_timer_time": None, "total_elapsed_time": None,
        "n_record": 0, "hr_in_record": 0, "err": None,
        "lap_intensity": Counter(), "lap_distances": [], "lap_times": [],
        "len_times": [], "len_strokes": [],
    }
    opener = gzip.open if path.endswith(".gz") else open
    try:
        with opener(path, "rb") as fh:
            with fitdecode.FitReader(fh) as fit:
                for frame in fit:
                    if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                        continue
                    n = frame.name
                    if n == "length":
                        d["n_length"] += 1
                        lt = frame.get_value("length_type", fallback=None)
                        if lt is not None:
                            lt = getattr(lt, "value", lt)
                            if lt in (0, "idle"):
                                d["n_length_idle"] += 1
                            else:
                                d["n_length_active"] += 1
                        st = frame.get_value("swim_stroke", fallback=None)
                        if st is not None:
                            d["strokes"][str(getattr(st, "value", st))] += 1
                        tt = frame.get_value("total_elapsed_time", fallback=None)
                        ts = frame.get_value("total_strokes", fallback=None)
                        if lt in (1, "active") or lt is None:
                            if tt is not None:
                                d["len_times"].append(round(float(tt), 2))
                            if ts is not None:
                                d["len_strokes"].append(int(ts))
                    elif n == "lap":
                        d["n_lap"] += 1
                        trig = frame.get_value("lap_trigger", fallback=None)
                        if trig is not None:
                            d["lap_triggers"][str(getattr(trig, "value", trig))] += 1
                        inten = frame.get_value("intensity", fallback=None)
                        if inten is not None:
                            d["lap_intensity"][str(getattr(inten, "value", inten))] += 1
                        dist = frame.get_value("total_distance", fallback=None)
                        if dist is not None:
                            d["lap_distances"].append(round(float(dist), 1))
                        tm = frame.get_value("total_timer_time", fallback=None)
                        if tm is not None:
                            d["lap_times"].append(round(float(tm), 1))
                    elif n == "session":
                        d["pool_length"] = frame.get_value("pool_length", fallback=None)
                        d["pool_unit"] = frame.get_value("pool_length_unit", fallback=None)
                        d["sub_sport"] = str(getattr(frame.get_value("sub_sport", fallback=None), "value", frame.get_value("sub_sport", fallback=None)))
                        d["num_active_lengths"] = frame.get_value("num_active_lengths", fallback=None)
                        d["total_strokes"] = frame.get_value("total_strokes", fallback=None)
                        d["total_distance"] = frame.get_value("total_distance", fallback=None)
                        d["total_timer_time"] = frame.get_value("total_timer_time", fallback=None)
                        d["total_elapsed_time"] = frame.get_value("total_elapsed_time", fallback=None)
                    elif n == "record":
                        d["n_record"] += 1
                        if frame.get_value("heart_rate", fallback=None) is not None:
                            d["hr_in_record"] += 1
    except Exception as e:  # noqa: BLE001
        d["err"] = f"{type(e).__name__}: {e}"
    d["lap_triggers"] = dict(d["lap_triggers"])
    d["strokes"] = dict(d["strokes"])
    d["lap_intensity"] = dict(d["lap_intensity"])
    return d


def main():
    idx, recs = load_csv()

    def col(r, name):
        i = idx.get(name)
        return r[i] if i is not None and i < len(r) else ""

    # ficheros sin extension reconocida
    raros = Counter()
    for r in recs:
        b = os.path.basename(col(r, "Nombre del archivo").strip())
        if not b.endswith((".fit.gz", ".gpx.gz", ".gpx")):
            raros[(col(r, "Tipo de actividad"), b)] += 1
    print("--- Ficheros con extension no reconocida ---")
    for (t, b), n in raros.items():
        print(f"  {t:14s} {b!r} x{n}")

    rows_out = []
    for tipobjetivo in ("Natación", "Entrenamiento"):
        sub = [r for r in recs if col(r, "Tipo de actividad").strip() == tipobjetivo]
        print(f"\n=== {tipobjetivo}: analizando {len(sub)} FIT ===")
        for i, r in enumerate(sub, 1):
            base = os.path.basename(col(r, "Nombre del archivo").strip())
            path = os.path.join(ACTS, base)
            d = scan(path)
            rows_out.append({
                "id": col(r, "ID de actividad"),
                "fecha": col(r, "Fecha de la actividad"),
                "nombre": col(r, "Nombre de la actividad"),
                "tipo": tipobjetivo,
                "fichero": base,
                "csv_dist_m": col(r, "Distancia"),
                "csv_mov_s": col(r, "Tiempo en movimiento"),
                "csv_largo_piscina": col(r, "Largo de la piscina"),
                "csv_ciclos": col(r, "Ciclos en total"),
                **{k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in d.items()
                   if k not in ("len_times", "len_strokes", "lap_distances", "lap_times")},
                "n_len_times": len(d["len_times"]),
                "sum_len_times": round(sum(d["len_times"]), 1) if d["len_times"] else None,
            })
            if i % 100 == 0:
                print(f"  ... {i}/{len(sub)}", flush=True)

    campos = list(rows_out[0].keys())
    p = os.path.join(OUT, "audit_03_fit_sweep.csv")
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        w.writerows(rows_out)
    print("\nEscrito:", p, f"({len(rows_out)} filas)")

    # resumen natacion
    sw = [x for x in rows_out if x["tipo"] == "Natación"]
    print("\n--- NATACION: resumen del barrido FIT ---")
    print("  con error de lectura:", sum(1 for x in sw if x["err"]))
    print("  pool_length (FIT):", dict(Counter(str(x["pool_length"]) for x in sw)))
    print("  num_laps:", dict(Counter(x["n_lap"] for x in sw).most_common(8)))
    print("  n_length (largos registrados) min/mediana/max:",
          min(x["n_length"] for x in sw),
          sorted(x["n_length"] for x in sw)[len(sw) // 2],
          max(x["n_length"] for x in sw))
    print("  largos de reposo (length_type idle) detectados:",
          sum(1 for x in sw if x["n_length_idle"] > 0), "sesiones")
    print("  sesiones con >1 lap (estructura marcada):", sum(1 for x in sw if x["n_lap"] > 1))
    print("  lap_trigger mas frecuentes:", dict(Counter(json.dumps(x["lap_triggers"]) for x in sw).most_common(5)))
    print("  estilos:", dict(Counter(json.dumps(x["strokes"]) for x in sw).most_common(6)))
    print("  sub_sport:", dict(Counter(str(x["sub_sport"]) for x in sw)))
    print("  con total_strokes:", sum(1 for x in sw if x["total_strokes"] is not None))

    en = [x for x in rows_out if x["tipo"] == "Entrenamiento"]
    print("\n--- ENTRENAMIENTO (posible gimnasio) ---")
    print("  sesiones:", len(en), "| con error:", sum(1 for x in en if x["err"]))
    print("  sub_sport:", dict(Counter(str(x["sub_sport"]) for x in en)))
    print("  n_lap:", dict(Counter(x["n_lap"] for x in en)))
    print("  lap_intensity:", dict(Counter(json.dumps(x["lap_intensity"]) for x in en)))
    print("  con HR en records:", sum(1 for x in en if x["hr_in_record"] > 0))
    print("  nombres:", dict(Counter(x["nombre"] for x in en).most_common(10)))


if __name__ == "__main__":
    main()
