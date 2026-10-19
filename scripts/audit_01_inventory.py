#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Auditoria 01: inventario del export de Strava.

Solo LEE los datos originales. Escribe resultados en informes/.
Uso: .venv/Scripts/python.exe scripts/audit_01_inventory.py
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORT = os.path.join(ROOT, "data", "export_2026-10-11")
OUT = os.path.join(ROOT, "informes")
os.makedirs(OUT, exist_ok=True)

CSV_PATH = os.path.join(EXPORT, "activities.csv")
ACTS = os.path.join(EXPORT, "activities")


def num(v):
    if v is None:
        return None
    v = v.strip()
    if v == "":
        return None
    v = v.replace("\u00a0", "").replace(" ", "")
    if "," in v and "." in v:
        v = v.replace(".", "").replace(",", ".")
    elif "," in v:
        v = v.replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def parse_fecha(s):
    s = s.strip()
    meses = {
        "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
        "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
    }
    m = re.match(r"^(\d{1,2}) (\w{3}) (\d{4}), (\d{1,2}):(\d{2}):(\d{2})$", s)
    if not m:
        return None
    d, mon, y, hh, mm, ss = m.groups()
    if mon not in meses:
        return None
    return datetime(int(y), meses[mon], int(d), int(hh), int(mm), int(ss))


def main():
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    header = rows[0]
    idx = {}
    for i, h in enumerate(header):
        idx.setdefault(h, i)

    def col(row, name):
        i = idx.get(name)
        return row[i] if i is not None and i < len(row) else ""

    recs = []
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        recs.append(row)

    print(f"CSV rows (actividades): {len(recs)}")
    print(f"Columnas: {len(header)} ({len(set(header))} unicas)")

    # ---------- inventario de ficheros ----------
    files_on_disk = set(os.listdir(ACTS))
    fmt_counter = Counter()
    missing = []
    referenced = set()
    for row in recs:
        name = col(row, "Nombre del archivo").strip()
        if not name:
            continue
        base = os.path.basename(name)
        referenced.add(base)
        if base.endswith(".fit.gz"):
            fmt_counter["fit.gz"] += 1
        elif base.endswith(".gpx.gz"):
            fmt_counter["gpx.gz"] += 1
        elif base.endswith(".gpx"):
            fmt_counter["gpx"] += 1
        elif base.endswith((".fit", ".tcx", ".csv", ".json", ".kml")):
            fmt_counter[base.rsplit(".", 1)[-1]] += 1
        else:
            fmt_counter["otro:" + base.rsplit(".", 1)[-1]] += 1
        if base not in files_on_disk:
            missing.append((col(row, "ID de actividad"), base))

    print("\nFormatos referenciados en activities.csv:", dict(fmt_counter))
    print("Ficheros en disco:", len(files_on_disk))
    print("Referenciados y ausentes en disco:", len(missing))
    huerfanos = sorted(files_on_disk - referenced)
    print("Ficheros en disco no referenciados:", len(huerfanos))
    if huerfanos[:5]:
        print("  ej:", huerfanos[:5])

    # ---------- por disciplina ----------
    by_type = Counter()
    dates_by_type = defaultdict(list)
    for row in recs:
        t = col(row, "Tipo de actividad").strip() or "(vacio)"
        by_type[t] += 1
        d = parse_fecha(col(row, "Fecha de la actividad"))
        if d:
            dates_by_type[t].append(d)

    print("\n--- Actividades por tipo ---")
    for t, n in by_type.most_common():
        ds = dates_by_type.get(t, [])
        if ds:
            print(f"  {t:22s} {n:5d}   {min(ds):%Y-%m-%d} -> {max(ds):%Y-%m-%d}")
        else:
            print(f"  {t:22s} {n:5d}   (sin fecha parseable)")

    # ---------- cobertura de campos por tipo ----------
    campos_clave = [
        "Distancia", "Tiempo en movimiento", "Tiempo transcurrido",
        "Frecuencia cardiaca promedio", "Frecuencia cardiaca máxima",
        "Calorías", "Largo de la piscina", "Sets totales",
        "Total de repeticiones", "Ciclos en total", "Recuperación",
        "Velocidad promedio", "Desnivel positivo", "Cadencia promedio",
        "Vatios promedio", "Esfuerzo Percibido",
    ]
    print("\n--- Cobertura de campos (% de actividades con valor no vacio) ---")
    print(f"{'campo':32s}" + "".join(f"{t[:12]:>14s}" for t, _ in by_type.most_common()))
    for c in campos_clave:
        line = f"{c:32s}"
        for t, _ in by_type.most_common():
            sub = [r for r in recs if (col(r, "Tipo de actividad").strip() or "(vacio)") == t]
            nonempty = sum(1 for r in sub if col(r, c).strip() != "")
            pct = 100.0 * nonempty / len(sub) if sub else 0
            line += f"{pct:13.1f}%"
        print(line)

    # ---------- duplicados ----------
    key_seen = defaultdict(list)
    for row in recs:
        d = parse_fecha(col(row, "Fecha de la actividad"))
        k = (
            d.strftime("%Y-%m-%d %H:%M") if d else "?",
            col(row, "Tipo de actividad").strip(),
            col(row, "Distancia").strip(),
            col(row, "Tiempo en movimiento").strip(),
        )
        key_seen[k].append(col(row, "ID de actividad"))
    dups = {k: v for k, v in key_seen.items() if len(v) > 1}
    print(f"\nGrupos de actividades posiblemente duplicadas (misma fecha-min, tipo, dist, t.mov): {len(dups)}")
    for k, v in list(dups.items())[:15]:
        print("  ", k, "->", v)

    # ---------- natacion en detalle ----------
    swims = [r for r in recs if col(r, "Tipo de actividad").strip().lower().startswith(("natac", "swim"))]
    print(f"\n=== NATACION: {len(swims)} sesiones ===")
    pool = Counter()
    swim_by_year = Counter()
    swim_no_gps = 0
    for r in swims:
        p = num(col(r, "Largo de la piscina"))
        pool["25" if p == 25 else "50" if p == 50 else f"otro:{p}"] += 1
        d = parse_fecha(col(r, "Fecha de la actividad"))
        if d:
            swim_by_year[d.year] += 1
    print("Largo de piscina:", dict(pool))
    print("Sesiones por anio:", dict(sorted(swim_by_year.items())))

    # ---------- gimnasio / fuerza ----------
    for t, n in by_type.most_common():
        if any(w in t.lower() for w in ("pesa", "fuerza", "entrenamiento con", "weight", "workout", "gimnas")):
            sub = [r for r in recs if col(r, "Tipo de actividad").strip() == t]
            ds = [parse_fecha(col(r, "Fecha de la actividad")) for r in sub]
            ds = [d for d in ds if d]
            print(f"\n=== TIPO '{t}': {n} sesiones, {min(ds):%Y-%m-%d} -> {max(ds):%Y-%m-%d} ===" if ds else f"\n=== TIPO '{t}': {n} ===")
            with_desc = sum(1 for r in sub if col(r, "Descripción de la actividad").strip())
            with_name = sum(1 for r in sub if col(r, "Nombre de la actividad").strip())
            print(f"  con descripcion: {with_desc}; con nombre: {with_name}")
            for r in sub[:6]:
                print(f"   - {col(r,'Fecha de la actividad')} | {col(r,'Nombre de la actividad')[:40]} | desc={col(r,'Descripción de la actividad')[:70]!r}")

    # ---------- resumen JSON ----------
    summary = {
        "csv_activities": len(recs),
        "files_on_disk": len(files_on_disk),
        "formatos_referenciados": dict(fmt_counter),
        "referenciados_ausentes": len(missing),
        "no_referenciados_en_disco": len(huerfanos),
        "por_tipo": dict(by_type),
        "natacion": {
            "sesiones": len(swims),
            "largo_piscina": dict(pool),
            "por_anio": dict(sorted(swim_by_year.items())),
        },
        "duplicados_grupos": len(dups),
    }
    with open(os.path.join(OUT, "audit_01_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print("\nEscrito:", os.path.join(OUT, "audit_01_summary.json"))


if __name__ == "__main__":
    main()
