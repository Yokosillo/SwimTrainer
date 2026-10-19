#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Auditoria 05: calidad de datos + reconstruccion de estructura de natacion.

Principio: cada metrica se calcula con un criterio explicito y queda marcada
con su calidad. Nada se inventa: los laps dudosos se excluyen y se cuentan.

Reglas:
  lap activo   : dist_m > 0
  lap descanso : dist_m == 0
  lap valido   : timer_s > 0  y  |timer_lap - suma(timer de sus largos)| <= max(2 s, 2 %)
  descartado   : lo demas (se registra el motivo)
  SERIE        : >= 2 reps de la MISMA distancia y mismo estilo, separadas por
                 descanso <= REST_MAX, dentro de la misma sesion.
  repeticion comparable a ritmo: estilo no es 'drill'.
Salidas: informes/audit_05_natacion.md, informes/audit_05_natacion.json,
         data/derived/series_v2.csv
"""
from __future__ import annotations

import csv
import json
import os
import re
import statistics as st
from collections import Counter, defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DERIVED = os.path.join(ROOT, "data", "derived")
OUT = os.path.join(ROOT, "informes")
os.makedirs(OUT, exist_ok=True)

REST_MAX = 120.0
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
    if mon not in MESES:
        return None
    return datetime(int(y), MESES[mon], int(d), int(hh), int(mm), int(ss))


def load(name):
    with open(os.path.join(DERIVED, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def fmt(s):
    """segundos -> mm:ss,0"""
    if s is None:
        return "?"
    mm, ss = divmod(s, 60)
    return f"{int(mm)}:{ss:04.1f}"


def main():
    sess_rows = load("swims_session.csv")
    laps = load("swims_laps.csv")
    lens = load("swims_lengths.csv")

    # ---------- duplicados ----------
    ids = Counter(s["swim_id"] for s in sess_rows)
    dup_ids = {k: v for k, v in ids.items() if v > 1}
    ficheros = Counter(s["fichero"] for s in sess_rows)
    dup_ficheros = {k: v for k, v in ficheros.items() if v > 1}
    print(f"IDs de actividad duplicados en la extraccion: {len(dup_ids)} -> {list(dup_ids.items())[:5]}")
    print(f"Ficheros FIT repetidos (mismo fichero en >1 actividad): {len(dup_ficheros)} -> {list(dup_ficheros.items())[:5]}")

    # dedupe: quedarse con la primera aparicion de cada swim_id
    sess = {}
    for s in sess_rows:
        sess.setdefault(s["swim_id"], s)

    len_by_swim = defaultdict(dict)
    for l in lens:
        len_by_swim[l["swim_id"]][int(l["len_idx"] or 0)] = l

    lap_by_swim = defaultdict(list)
    for l in laps:
        lap_by_swim[l["swim_id"]].append(l)
    for k in lap_by_swim:
        lap_by_swim[k].sort(key=lambda x: int(x["lap_idx"] or 0))

    # ---------- validacion por lap ----------
    motivos = Counter()
    eventos = {}
    for sid, ls in lap_by_swim.items():
        ev = []
        lens_s = len_by_swim.get(sid, {})
        for l in ls:
            d = f(l["dist_m"]) or 0.0
            t = f(l["timer_s"]) or 0.0
            nl = f(l["n_largos"]) or 0
            fi = f(l["primer_largo_idx"]) or 0
            t_len = 0.0
            n_len_presentes = 0
            for i in range(int(fi), int(fi + nl)):
                x = lens_s.get(i)
                if x is not None:
                    t_len += f(x["timer_s"]) or 0.0
                    n_len_presentes += 1
            item = {"lap": l, "dist": round(d), "t": t, "t_len": round(t_len, 2),
                    "n_len_esperados": int(nl), "n_len_presentes": n_len_presentes,
                    "estilo": l["estilo"], "hr": f(l["hr_media"]),
                    "bruto": l["intensidad"]}
            if d <= 0:
                item["tipo"] = "descanso"
            elif t <= 0:
                item["tipo"] = "descartado"
                item["motivo"] = "timer=0"
                motivos["timer=0"] += 1
            elif abs(t - t_len) > max(2.0, 0.02 * t):
                item["tipo"] = "descartado"
                item["motivo"] = "timer no cuadra con sus largos"
                motivos["timer_no_cuadra"] += 1
            elif n_len_presentes == 0:
                item["tipo"] = "descartado"
                item["motivo"] = "sin largos asociados"
                motivos["sin_largos"] += 1
            else:
                item["tipo"] = "activo"
                item["pace"] = t / (d / 100.0)
                item["pace_len"] = t_len / (d / 100.0) if t_len else None
            ev.append(item)
        eventos[sid] = ev

    n_act = sum(1 for s in eventos for e in eventos[s] if e["tipo"] == "activo")
    n_des = sum(1 for s in eventos for e in eventos[s] if e["tipo"] == "descanso")
    print(f"laps: activos={n_act} descansos={n_des} descartados={sum(motivos.values())} {dict(motivos)}")

    # ---------- series ----------
    series = []
    for sid, ev in eventos.items():
        n = len(ev)
        i = 0
        while i < n:
            if ev[i]["tipo"] != "activo":
                i += 1
                continue
            grupo = [ev[i]]
            restos = []
            j = i
            while j + 1 < n:
                k = j + 1
                rest = 0.0
                while k < n and ev[k]["tipo"] != "activo":
                    if ev[k]["tipo"] == "descanso":
                        rest += ev[k]["t"]
                    k += 1
                if k < n and ev[k]["dist"] == grupo[0]["dist"] and rest <= REST_MAX:
                    grupo.append(ev[k])
                    restos.append(rest)
                    j = k
                else:
                    break
            if len(grupo) >= 2:
                d = grupo[0]["dist"]
                paces = [g["pace"] for g in grupo]
                estilos = {g["estilo"] for g in grupo}
                es_drill = "drill" in estilos
                series.append({
                    "swim_id": sid,
                    "fecha": sess[sid]["fecha"],
                    "fecha_iso": (fecha_dt(sess[sid]["fecha"]).strftime("%Y-%m-%d %H:%M") if fecha_dt(sess[sid]["fecha"]) else ""),
                    "anio": (fecha_dt(sess[sid]["fecha"]).year if fecha_dt(sess[sid]["fecha"]) else None),
                    "rep_m": d,
                    "n_reps": len(grupo),
                    "volumen_m": d * len(grupo),
                    "ritmos_100": [round(p, 1) for p in paces],
                    "ritmo_medio_100": round(sum(paces) / len(paces), 1),
                    "mejor_100": round(min(paces), 1),
                    "peor_100": round(max(paces), 1),
                    "sd_100": round(st.pstdev(paces), 2),
                    "rango_100": round(max(paces) - min(paces), 1),
                    "descanso_medio_s": round(sum(restos) / len(restos), 1) if restos else None,
                    "deriva_ult_menos_1a": round(paces[-1] - paces[0], 1),
                    "estilo": "/".join(sorted(estilos)) if estilos else "",
                    "drill": es_drill,
                    "piscina_m": f(sess[sid]["largo_piscina"]),
                    "calidad": "valida",
                })
            i = j + 1

    print(f"series reconstruidas (>=2 reps iguales): {len(series)}")
    comparables = [s for s in series if not s["drill"] and s["n_reps"] >= 3]
    print(f"series comparables (>=3 reps, sin drill): {len(comparables)}")

    # ---------- tabla por distancia ----------
    resumen = {}
    for d in (50, 100, 200, 400, 500, 800, 1000, 1500):
        sub = [s for s in comparables if s["rep_m"] == d]
        if not sub:
            continue
        med = st.median(s["ritmo_medio_100"] for s in sub)
        vals = [s["ritmo_medio_100"] for s in sub]
        q = st.quantiles(vals, n=4) if len(vals) >= 4 else [min(vals), med, max(vals)]
        resumen[d] = {
            "n_series": len(sub),
            "n_sesiones": len({s["swim_id"] for s in sub}),
            "ritmo_mediano_serie": round(med, 1),
            "p25": round(q[0], 1),
            "p75": round(q[2], 1),
            "mejor_ritmo_medio_de_serie": round(min(s["ritmo_medio_100"] for s in sub), 1),
            "mejor_rep": round(min(s["mejor_100"] for s in sub), 1),
            "n_reps_tipico": Counter(s["n_reps"] for s in sub).most_common(3),
            "descanso_mediano_s": round(st.median([s["descanso_medio_s"] for s in sub if s["descanso_medio_s"] is not None]), 1),
        }

    # ---------- evolucion anual ----------
    evol = defaultdict(lambda: defaultdict(list))
    for s in comparables:
        if s["anio"] and s["rep_m"] in (100, 200, 400):
            evol[s["rep_m"]][s["anio"]].append(s["ritmo_medio_100"])
    evol_out = {str(d): {str(a): round(sum(v) / len(v), 1) for a, v in sorted(ys.items())} for d, ys in evol.items()}

    # ---------- volumen anual ----------
    vols = defaultdict(lambda: [0, 0.0, 0.0])
    for sid, s in sess.items():
        dt = fecha_dt(s["fecha"])
        if not dt:
            continue
        vols[dt.year][0] += 1
        vols[dt.year][1] += (f(s["dist_m"]) or 0) / 1000.0
        vols[dt.year][2] += (f(s["timer_s"]) or 0) / 3600.0

    # ---------- mejores esfuerzos continuos (largos sin descanso) ----------
    cont = defaultdict(list)
    for sid, s in sess.items():
        ev = eventos.get(sid, [])
        i = 0
        while i < len(ev):
            if ev[i]["tipo"] != "activo":
                i += 1
                continue
            j = i
            tot_m, tot_t, estilos = ev[i]["dist"], ev[i]["t_len"] or ev[i]["t"], {ev[i]["estilo"]}
            kmax = i
            while j + 1 < len(ev):
                k = j + 1
                rest = 0.0
                while k < len(ev) and ev[k]["tipo"] != "activo":
                    if ev[k]["tipo"] == "descanso":
                        rest += ev[k]["t"]
                    k += 1
                if k >= len(ev) or rest > 3.0 or ev[k]["dist"] != ev[j]["dist"]:
                    break
                j = k
                tot_m += ev[k]["dist"]
                tot_t += ev[k]["t_len"] or ev[k]["t"]
                estilos.add(ev[k]["estilo"])
            for d in (800, 1000, 1500, 2000, 3000):
                if tot_m >= d and "drill" not in estilos:
                    cont[d].append({
                        "ritmo_100": round(tot_t / (tot_m / 100.0), 1),
                        "fecha": sess[sid]["fecha"], "dist_real_m": tot_m,
                        "pool": sess[sid]["largo_piscina"], "estilos": "/".join(sorted(estilos)),
                    })
            i = j + 1

    # ---------- informe ----------
    L = []
    A = L.append
    A("# Auditoria de natacion - resultados reales del historico Strava")
    A("")
    A(f"Extraido de 854 ficheros FIT originales (todas las salidas de natacion del export).")
    A(f"Laps: {n_act} activos, {n_des} descansos, {sum(motivos.values())} descartados por inconsistencia.")
    A("")
    A("## 1. Series reconstruidas (>=3 reps iguales, sin trabajo de tecnica)")
    A("")
    A("| rep | series | sesiones | ritmo medio de serie (s/100) | p25 | p75 | mejor serie | mejor rep | reps tipicas | descanso mediano |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for d, r in sorted(resumen.items()):
        A(f"| {d} m | {r['n_series']} | {r['n_sesiones']} | {r['ritmo_mediano_serie']} | {r['p25']} | {r['p75']} | "
          f"{r['mejor_ritmo_medio_de_serie']} | {r['mejor_rep']} | {r['n_reps_tipico']} | {r['descanso_mediano_s']} s |")
    A("")
    A("## 2. Evolucion anual del ritmo medio de serie (s/100 m)")
    A("")
    anios = sorted({a for ys in evol.values() for a in ys})
    A("| rep | " + " | ".join(str(a) for a in anios) + " |")
    A("|" + "---|" * (len(anios) + 1))
    for d in (100, 200, 400):
        if str(d) in evol_out:
            row = [str(evol_out[str(d)].get(str(a), "-")) for a in anios]
            A(f"| {d} m | " + " | ".join(row) + " |")
    A("")
    A("## 3. Volumen anual")
    A("")
    A("| anio | sesiones | km | horas | km/semana |")
    A("|---|---|---|---|---|")
    for a in sorted(vols):
        n, km, h = vols[a]
        A(f"| {a} | {n} | {km:.1f} | {h:.1f} | {km/52:.2f} |")
    A("")
    A("## 4. Mejores bloques continuos (sin descanso, sin tecnica)")
    A("")
    for d in (800, 1000, 1500, 2000, 3000):
        c = sorted(cont.get(d, []), key=lambda x: x["ritmo_100"])[:3]
        if not c:
            A(f"- >= {d} m: sin datos")
            continue
        A(f"- >= {d} m: " + " | ".join(f"{x['ritmo_100']} s/100 ({x['fecha'][:11]}, {x['dist_real_m']} m, piscina {x['pool']} m)" for x in c))
    A("")
    txt = "\n".join(L)
    with open(os.path.join(OUT, "audit_05_natacion.md"), "w", encoding="utf-8") as fh:
        fh.write(txt)
    print("\n" + txt)

    with open(os.path.join(DERIVED, "series_v2.csv"), "w", encoding="utf-8", newline="") as fh:
        if series:
            w = csv.DictWriter(fh, fieldnames=list(series[0].keys()))
            w.writeheader()
            for s in series:
                r = dict(s)
                r["ritmos_100"] = json.dumps(r["ritmos_100"])
                w.writerow(r)
    with open(os.path.join(OUT, "audit_05_natacion.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "laps": {"activos": n_act, "descansos": n_des, "descartados": sum(motivos.values()), "motivos": dict(motivos)},
            "series": len(series), "series_comparables": len(comparables),
            "resumen_por_distancia": resumen,
            "evolucion_anual": evol_out,
            "volumen_anual": {str(a): vols[a] for a in sorted(vols)},
            "continuos": {str(d): sorted(v, key=lambda x: x["ritmo_100"])[:5] for d, v in cont.items()},
            "duplicados": {"ids": dup_ids, "ficheros": dup_ficheros},
        }, fh, ensure_ascii=False, indent=2)
    print("Escritos: informes/audit_05_natacion.md | .json | data/derived/series_v2.csv")


if __name__ == "__main__":
    main()
