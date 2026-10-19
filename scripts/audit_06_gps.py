#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Auditoria 06: datos GPS (bicicleta, carrera, caminata, senderismo).

- Que actividades tienen coordenadas y de que calidad (puntos, huecos, elevacion).
- Cuantos recorridos se repiten de verdad (cluster de punto de salida + forma).
- Que se puede y que no se puede calcular.
Salida: informes/audit_06_gps.json + resumen por consola. Solo LEE.
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import os
import re
import statistics as st
from collections import Counter, defaultdict
from datetime import datetime

import gpxpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORT = os.path.join(ROOT, "data", "export_2026-10-11")
ACTS = os.path.join(EXPORT, "activities")
OUT = os.path.join(ROOT, "informes")
MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
         "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12}


def fecha_dt(s):
    m = re.match(r"^(\d{1,2}) (\w{3,4}) (\d{4}), (\d{1,2}):(\d{2}):(\d{2})$", (s or "").strip())
    if not m:
        return None
    d, mon, y, hh, mm, ss = m.groups()
    return datetime(int(y), MESES[mon], int(d), int(hh), int(mm), int(ss)) if mon in MESES else None


def haversine(a, b):
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def main():
    with open(os.path.join(EXPORT, "activities.csv"), encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    header = rows[0]
    idx = {}
    for i, h in enumerate(header):
        idx.setdefault(h, i)
    recs = [r for r in rows[1:] if r and r[0].strip()]

    def col(r, name):
        i = idx.get(name)
        return r[i] if i is not None and i < len(r) else ""

    def dist_m(row):
        """La ultima columna 'Distancia' del export esta siempre en metros."""
        pos = [i for i, h in enumerate(header) if h == "Distancia"]
        for i in reversed(pos):
            if i < len(row) and row[i].strip():
                try:
                    return float(row[i].replace(",", "."))
                except ValueError:
                    pass
        return None

    tipos = ("Bicicleta", "Carrera", "Caminata", "Senderismo", "Natación")
    stats = defaultdict(lambda: {"n": 0, "con_gps": 0, "sin_gps": 0, "error": 0,
                                 "puntos": [], "con_ele": 0, "con_time": 0, "huecos": []})
    tracks = []
    for r in recs:
        t = col(r, "Tipo de actividad").strip()
        if t not in tipos:
            continue
        stats[t]["n"] += 1
        base = os.path.basename(col(r, "Nombre del archivo").strip())
        if not base:
            print("  [aviso] actividad sin fichero:", col(r, "ID de actividad"), col(r, "Fecha de la actividad"),
                  "dist=", col(r, "Distancia"), "tipo=", t)
            continue
        path = os.path.join(ACTS, base)
        if not os.path.exists(path):
            continue
        if base.endswith(".fit.gz"):
            continue  # los FIT GPS se leen aparte
        try:
            opener = gzip.open if base.endswith(".gz") else open
            with opener(path, "rb") as fh2:
                g = gpxpy.parse(fh2)
        except Exception as e:  # noqa: BLE001
            stats[t]["error"] += 1
            continue
        pts = [p for trk in g.tracks for seg in trk.segments for p in seg.points]
        if not pts:
            stats[t]["sin_gps"] += 1
            continue
        stats[t]["con_gps"] += 1
        stats[t]["puntos"].append(len(pts))
        if any(p.elevation is not None for p in pts):
            stats[t]["con_ele"] += 1
        if any(p.time is not None for p in pts):
            stats[t]["con_time"] += 1
        # huecos temporales entre puntos consecutivos
        ts = [p.time for p in pts if p.time]
        if len(ts) > 2:
            gaps = [(ts[i + 1] - ts[i]).total_seconds() for i in range(len(ts) - 1)]
            stats[t]["huecos"].append(max(gaps))
        d = fecha_dt(col(r, "Fecha de la actividad"))
        tracks.append({
            "id": col(r, "ID de actividad"), "tipo": t, "fecha": col(r, "Fecha de la actividad"),
            "anio": d.year if d else None,
            "fichero": base,
            "inicio": (round(pts[0].latitude, 5), round(pts[0].longitude, 5)),
            "fin": (round(pts[-1].latitude, 5), round(pts[-1].longitude, 5)),
            "n_pts": len(pts),
            "dist_csv_m": dist_m(r),
            "dist_gpx_m": None,
        })
        # distancia del propio GPX (para contrastar con la del CSV)
        try:
            coords = [(p.latitude, p.longitude) for p in pts]
            dist = sum(haversine(coords[i], coords[i + 1]) for i in range(len(coords) - 1))
            tracks[-1]["dist_gpx_m"] = round(dist)
        except Exception:
            pass

    print("=== Cobertura GPS por tipo ===")
    for t, s in stats.items():
        p = s["puntos"]
        print(f"  {t:12s} n={s['n']:4d} con_gps={s['con_gps']:4d} sin_gps={s['sin_gps']:3d} error={s['error']:2d} "
              f"con_elevacion={s['con_ele']:4d} con_hora={s['con_time']:4d} "
              f"puntos(min/mediana/max)={min(p) if p else '-'}/{int(st.median(p)) if p else '-'}/{max(p) if p else '-'} "
              f"mayor_hueco_mediano={round(st.median(s['huecos']),1) if s['huecos'] else '-'} s")

    # ---- contraste distancia CSV vs GPX ----
    print("\n=== Contraste distancia CSV vs distancia del GPX ===")
    dif = []
    for tr in tracks:
        c = tr["dist_csv_m"]
        if c is None:
            continue
        if tr["dist_gpx_m"]:
            dif.append((tr["tipo"], c, tr["dist_gpx_m"]))
    por_tipo = defaultdict(list)
    for t, c, g in dif:
        por_tipo[t].append(abs(g - c) / c if c else 0)
    for t, v in por_tipo.items():
        p90 = st.quantiles(v, n=10)[8] if len(v) >= 10 else max(v)
        print(f"  {t:12s} n={len(v):4d}  desviacion relativa GPX vs CSV: mediana={st.median(v)*100:.2f}%  p90={p90*100:.2f}%")

    # ---- cluster de rutas por punto de salida ----
    print("\n=== Rutas repetidas (agrupadas por punto de salida, radio 300 m) ===")
    clusters = []
    for tr in tracks:
        asignado = None
        for c in clusters:
            if haversine(c["centro"], tr["inicio"]) < 300:
                asignado = c
                break
        if asignado is None:
            clusters.append({"centro": tr["inicio"], "items": [tr]})
        else:
            asignado["items"].append(tr)
            n = len(asignado["items"])
            asignado["centro"] = (
                sum(x["inicio"][0] for x in asignado["items"]) / n,
                sum(x["inicio"][1] for x in asignado["items"]) / n,
            )
    clusters.sort(key=lambda c: -len(c["items"]))
    print(f"  clusters de salida: {len(clusters)} para {len(tracks)} actividades GPS")
    for c in clusters[:12]:
        tipos_c = Counter(x["tipo"] for x in c["items"])
        print(f"   {len(c['items']):4d} salidas desde {c['centro'][0]:.4f},{c['centro'][1]:.4f}  {dict(tipos_c)}")
    repetidos = sum(len(c["items"]) for c in clusters if len(c["items"]) >= 3)
    print(f"  actividades que comparten salida con >=3 (potencial de segmentos): {repetidos}")

    # ---- rutas declaradas por el atleta ----
    with open(os.path.join(EXPORT, "routes.csv"), encoding="utf-8-sig", newline="") as fh:
        rr = list(csv.reader(fh))
    print(f"\n=== Rutas guardadas por el atleta en Strava: {len(rr)-1} ===")
    for r in rr[1:]:
        print("   ", r)

    with open(os.path.join(OUT, "audit_06_gps.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "por_tipo": {t: {k: (v if k != "puntos" and k != "huecos" else None) for k, v in s.items()} for t, s in stats.items()},
            "n_tracks_gps": len(tracks),
            "clusters_salida": [{"n": len(c["items"]), "centro": c["centro"]} for c in clusters[:40]],
            "rutas_guardadas": rr[1:],
        }, fh, ensure_ascii=False, indent=2)
    print("\nEscrito:", os.path.join(OUT, "audit_06_gps.json"))


if __name__ == "__main__":
    main()
