#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Auditoria 07: forma reciente, huecos de entrenamiento y aguas abiertas.

Salida: informes/audit_07_forma_reciente.md (+ json). Solo LEE derived/*.csv
"""
from __future__ import annotations

import csv
import json
import os
import re
import statistics as st
from collections import defaultdict
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DERIVED = os.path.join(ROOT, "data", "derived")
OUT = os.path.join(ROOT, "informes")
MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
         "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12}


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fecha_dt(s):
    m = re.match(r"^(\d{1,2}) (\w{3,4}) (\d{4}), (\d{1,2}):(\d{2}):(\d{2})$", (s or "").strip())
    if not m:
        return None
    d, mon, y, hh, mm, ss = m.groups()
    return datetime(int(y), MESES[mon], int(d), int(hh), int(mm), int(ss)) if mon in MESES else None


def fmt(s):
    mm, ss = divmod(s, 60)
    return f"{int(mm)}:{ss:04.1f}"


def main():
    sess = {s["swim_id"]: s for s in csv.DictReader(open(os.path.join(DERIVED, "swims_session.csv"), encoding="utf-8"))}
    series = list(csv.DictReader(open(os.path.join(DERIVED, "series_v2.csv"), encoding="utf-8")))

    fechas = []
    for sid, s in sess.items():
        d = fecha_dt(s["fecha"])
        if d:
            fechas.append((d, sid))
    fechas.sort()
    ultimo = fechas[-1][0]
    print("ultima natacion registrada:", fechas[-1][0], "| primera:", fechas[0][0], "| total:", len(fechas))

    # huecos
    huecos = []
    for i in range(1, len(fechas)):
        delta = (fechas[i][0] - fechas[i - 1][0]).days
        if delta >= 21:
            huecos.append((fechas[i - 1][0].strftime("%Y-%m-%d"), fechas[i][0].strftime("%Y-%m-%d"), delta))
    L = []
    A = L.append
    A("# Forma reciente y estructura del historico de natacion")
    A("")
    A(f"- Ultima sesion: {ultimo:%d/%m/%Y}")
    A(f"- Primer registro: {fechas[0][0]:%d/%m/%Y}")
    A(f"- Sesiones totales: {len(fechas)}")
    A("")
    A("## Huecos de mas de 3 semanas sin nadar")
    A("")
    A("| desde | hasta | dias |")
    A("|---|---|---|")
    for a, b, d in huecos:
        A(f"| {a} | {b} | {d} |")
    A("")

    # ultimos 18 meses por mes
    A("## Ultimos 18 meses de natacion")
    A("")
    A("| mes | sesiones | km | horas | s/100 m de sesion | series 100/200/400 |")
    A("|---|---|---|---|---|---|")
    mes = defaultdict(lambda: {"n": 0, "m": 0.0, "h": 0.0, "series": []})
    for sid, s in sess.items():
        d = fecha_dt(s["fecha"])
        if not d or d < ultimo - timedelta(days=548):
            continue
        k = f"{d.year}-{d.month:02d}"
        mes[k]["n"] += 1
        mes[k]["m"] += f(s["dist_m"]) or 0
        mes[k]["h"] += (f(s["timer_s"]) or 0) / 3600
    for s in series:
        d = fecha_dt(s["fecha"])
        if not d or d < ultimo - timedelta(days=548):
            continue
        k = f"{d.year}-{d.month:02d}"
        if s["rep_m"] in ("100", "200", "400"):
            mes[k]["series"].append(f"{s['n_reps']}x{s['rep_m']}@{s['ritmo_medio_100']}")
    for k in sorted(mes):
        v = mes[k]
        pace = (v["h"] * 3600) / (v["m"] / 100) if v["m"] else 0
        A(f"| {k} | {v['n']} | {v['m']/1000:.2f} | {v['h']:.1f} | {pace:.1f} | {', '.join(v['series'][:4])} |")
    A("")

    # mejores series por anio (todas las distancias relevantes)
    A("## Mejores series por anio (ritmo medio de la serie)")
    A("")
    A("| anio | distancia | serie | ritmo medio | mejor rep | sd | descanso | fecha |")
    A("|---|---|---|---|---|---|---|---|")
    buenas = [s for s in series if s["drill"] in ("False","false","0","") and int(s["n_reps"]) >= 3 and s["rep_m"] in ("100", "200", "400", "500", "1000")]
    for anio in sorted({s["anio"] for s in buenas if s["anio"]}, reverse=True):
        sub = [s for s in buenas if s["anio"] == anio]
        for d in ("100", "200", "400"):
            c = sorted([s for s in sub if s["rep_m"] == d], key=lambda x: float(x["ritmo_medio_100"]))
            for s in c[:2]:
                A(f"| {anio} | {d} m | {s['n_reps']}x{d} | {s['ritmo_medio_100']} | {s['mejor_100']} | {s['sd_100']} | {s['descanso_medio_s']} s | {s['fecha'][:16]} |")
    A("")

    # aguas abiertas
    A("## Sesiones en aguas abiertas (sub_sport = open_water)")
    A("")
    A("| fecha | distancia | tiempo | ritmo/100 |")
    A("|---|---|---|---|")
    ow = [(s, fecha_dt(s["fecha"])) for s in sess.values() if (s["sub_sport"] or "") == "open_water"]
    ow.sort(key=lambda x: x[1] or datetime(1900, 1, 1), reverse=True)
    for s, d in ow[:25]:
        dist = f(s["dist_m"]) or 0
        t = f(s["timer_s"]) or 0
        A(f"| {s['fecha'][:16]} | {dist/1000:.2f} km | {fmt(t)} | {t/(dist/100) if dist else 0:.1f} |")
    anios_ow = defaultdict(int)
    for s, d in ow:
        if d:
            anios_ow[d.year] += 1
    A("")
    A(f"Total aguas abiertas: {len(ow)} sesiones. Por anio: {dict(sorted(anios_ow.items()))}")
    A("")

    txt = "\n".join(L)
    with open(os.path.join(OUT, "audit_07_forma_reciente.md"), "w", encoding="utf-8") as fh:
        fh.write(txt)
    print(txt)


if __name__ == "__main__":
    main()
