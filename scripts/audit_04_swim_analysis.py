#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Auditoria 04 (v2): estructura real de las sesiones de natacion.

Reglas de agrupacion (documentadas):
 - lap activo  = dist_m > 0
 - lap descanso = dist_m == 0 (el atleta pulsa el boton al acabar cada repeticion)
 - Se descartan laps fisicamente imposibles: ritmo < 30 s/100 m o > 400 s/100 m
   o timer < 5 s (artefactos de datos, no entrenamiento).
 - SERIE = reps consecutivas con la MISMA distancia y descanso entre ellas
   <= REST_MAX (120 s por defecto), sin cambio de estilo registrado.
 - Esfuerzo continuo = lap unico de >= 400 m.

Salida: informes/audit_04_natacion.json + catalogo de series en data/derived/series.csv
Solo LEE derived/*.csv
"""
from __future__ import annotations

import csv
import json
import os
import statistics as st
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DERIVED = os.path.join(ROOT, "data", "derived")
OUT = os.path.join(ROOT, "informes")

REST_MAX = 120.0
PACE_MIN = 30.0
PACE_MAX = 400.0


def load(name):
    with open(os.path.join(DERIVED, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    os.makedirs(OUT, exist_ok=True)
    sess = {s["swim_id"]: s for s in load("swims_session.csv")}
    laps = load("swims_laps.csv")
    by_swim = defaultdict(list)
    for l in laps:
        by_swim[l["swim_id"]].append(l)
    for k in by_swim:
        by_swim[k].sort(key=lambda x: int(x["lap_idx"]) if x["lap_idx"] else 0)

    # ---- clasificar laps ----
    descartados = Counter()
    seq = {}  # swim_id -> lista de eventos ordenada
    for sid, ls in by_swim.items():
        ev = []
        for l in ls:
            d = f(l["dist_m"]) or 0.0
            t = f(l["timer_s"]) or 0.0
            item = {"lap": l, "dist": round(d), "t": t,
                    "estilo": l["estilo"], "hr": f(l["hr_media"]), "brazadas": f(l["brazadas"])}
            if d <= 0:
                item["tipo"] = "descanso"
            else:
                pace = t / (d / 100.0) if d else None
                if t < 5 or pace is None or pace < PACE_MIN or pace > PACE_MAX:
                    item["tipo"] = "descartado"
                    descartados[f"ritmo_{int(pace) if pace else 'na'}"] += 1
                else:
                    item["tipo"] = "activo"
                    item["pace"] = pace
            ev.append(item)
        seq[sid] = ev

    n_act = sum(1 for sid in seq for e in seq[sid] if e["tipo"] == "activo")
    n_des = sum(1 for sid in seq for e in seq[sid] if e["tipo"] == "descanso")
    n_art = sum(1 for sid in seq for e in seq[sid] if e["tipo"] == "descartado")
    print(f"laps activos={n_act} descansos={n_des} descartados(artefacto)={n_art}")

    # ---- series ----
    series = []
    for sid, ev in seq.items():
        i = 0
        n = len(ev)
        while i < n:
            if ev[i]["tipo"] != "activo":
                i += 1
                continue
            j = i
            grupo = [ev[i]]
            restos = []
            while j + 1 < n:
                # busca el siguiente lap significativo (salta descartados)
                k = j + 1
                rest = 0.0
                while k < n and ev[k]["tipo"] != "activo":
                    if ev[k]["tipo"] == "descanso":
                        rest += ev[k]["t"]
                    k += 1
                if k >= n:
                    break
                if ev[k]["dist"] == grupo[0]["dist"] and rest <= REST_MAX:
                    grupo.append(ev[k])
                    restos.append(rest)
                    j = k
                else:
                    break
            if len(grupo) >= 2:
                dists = grupo[0]["dist"]
                paces = [g["pace"] for g in grupo]
                series.append({
                    "swim_id": sid, "fecha": sess[sid]["fecha"], "rep_m": dists,
                    "n_reps": len(grupo), "volumen_m": dists * len(grupo),
                    "ritmos_100": [round(p, 1) for p in paces],
                    "ritmo_medio_100": round(sum(paces) / len(paces), 1),
                    "mejor_100": round(min(paces), 1), "peor_100": round(max(paces), 1),
                    "sd_100": round(st.pstdev(paces), 2) if len(paces) > 1 else 0.0,
                    "descanso_medio_s": round(sum(restos) / len(restos), 1) if restos else None,
                    "descanso_min_s": round(min(restos), 1) if restos else None,
                    "deriva_1a_ultima_s": round(paces[-1] - paces[0], 1),
                    "estilo": grupo[0]["estilo"],
                    "piscina_m": f(sess[sid]["largo_piscina"]),
                })
            i = j + 1

    print(f"\nSERIES detectadas (>=2 reps iguales): {len(series)}")
    por_dist = Counter(s["rep_m"] for s in series)
    print("  por distancia de repeticion:", dict(por_dist.most_common(12)))

    # catalogo de las relevantes
    relevantes = [s for s in series if s["rep_m"] in (100, 200, 400) or (s["rep_m"] >= 400)]
    print(f"  relevantes (100/200/400 o >=400 m): {len(relevantes)}")
    for d in (100, 200, 400):
        sub = [s for s in series if s["rep_m"] == d]
        print(f"\n--- {d} m: {len(sub)} repeticiones en {len({s['swim_id'] for s in sub})} sesiones ---")
        for s in sorted(sub, key=lambda x: x["fecha"] or "")[-8:]:
            print(f"   {s['fecha']:>22s} {s['n_reps']:>2}x{d:<4d} medio {s['ritmo_medio_100']:6.1f} sd {s['sd_100']:5.2f} "
                  f"mejor {s['mejor_100']:6.1f} peor {s['peor_100']:6.1f} desc {s['descanso_medio_s']} deriva {s['deriva_1a_ultima_s']:+.1f}")

    # ---- esfuerzos continuos y mejores laps ----
    best = defaultdict(list)
    for sid, ev in seq.items():
        for e in ev:
            if e["tipo"] != "activo":
                continue
            best[e["dist"]].append((e["pace"], sess[sid]["fecha"], sid))
    print("\n--- MEJOR ritmo por distancia de lap continuo (s/100m) ---")
    for d in (100, 200, 300, 400, 500, 800, 1000, 1500, 2000, 2500, 3000):
        c = sorted(best.get(d, []))
        if not c:
            continue
        print(f"   {d:5d} m: " + " | ".join(f"{p:6.1f} ({fe[:11]})" for p, fe, _ in c[:3]))

    # ---- sumas de bloques continuos por sesion (mejor 1500/3000 dentro de una sesion) ----
    print("\n--- Mejores bloques CONTINUOS de una sesion (sin descanso entre reps) ---")
    continuos = defaultdict(list)
    for sid, ev in seq.items():
        # tramos de laps activos consecutivos sin descanso (o con descanso ~0)
        i = 0
        while i < len(ev):
            if ev[i]["tipo"] != "activo":
                i += 1
                continue
            j = i
            tot_m = ev[i]["dist"]
            tot_t = ev[i]["t"]
            best_local = (tot_m, tot_t, ev[i]["dist"])
            while j + 1 < len(ev):
                k = j + 1
                rest = 0.0
                while k < len(ev) and ev[k]["tipo"] != "activo":
                    if ev[k]["tipo"] == "descanso":
                        rest += ev[k]["t"]
                    k += 1
                if k >= len(ev) or rest > 5.0:
                    break
                j = k
                tot_m += ev[k]["dist"]
                tot_t += ev[k]["t"]
            for d in (400, 800, 1000, 1500, 2000, 3000):
                if tot_m >= d:
                    continuos[d].append((tot_t / (tot_m / 100.0), sess[sid]["fecha"], sid, tot_m))
            i = j + 1
    for d in (800, 1000, 1500, 2000, 3000):
        c = sorted(continuos.get(d, []))
        if not c:
            print(f"   {d:5d} m continuos: sin datos")
            continue
        print(f"   >={d:5d} m: " + " | ".join(f"{p:6.1f} ({fe[:11]}, {m} m)" for p, fe, _, m in c[:3]))

    # ---- evolucion anual ----
    print("\n--- Evolucion anual: ritmo medio (s/100m) de las series de 100 y 200 ---")
    for d in (100, 200, 400):
        sub = [s for s in series if s["rep_m"] == d]
        if not sub:
            continue
        poranio = defaultdict(list)
        for s in sub:
            anio = (s["fecha"] or "")[-4:]
            poranio[anio].append(s["ritmo_medio_100"])
        print(f"   {d} m:", {a: round(sum(v) / len(v), 1) for a, v in sorted(poranio.items())})

    # ---- volumen anual natacion ----
    print("\n--- Volumen de natacion por anio (sesiones | km | sesiones/semana) ---")
    vol = defaultdict(lambda: [0, 0.0])
    for sid, s in sess.items():
        anio = (s["fecha"] or "")[-4:]
        vol[anio][0] += 1
        vol[anio][1] += (f(s["dist_m"]) or 0) / 1000.0
    for a in sorted(vol):
        print(f"   {a}: {vol[a][0]:4d} sesiones  {vol[a][1]:7.1f} km  ~{vol[a][1]/52:5.2f} km/semana")

    # ---- guardar catalogo ----
    if series:
        with open(os.path.join(DERIVED, "series.csv"), "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(series[0].keys()))
            w.writeheader()
            for s in series:
                s = dict(s)
                for k in ("ritmos_100",):
                    s[k] = json.dumps(s[k])
                w.writerow(s)
        print("\nEscrito data/derived/series.csv:", len(series))

    with open(os.path.join(OUT, "audit_04_natacion.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "laps": {"activos": n_act, "descansos": n_des, "descartados": n_art},
            "series_total": len(series),
            "series_por_distancia": dict(por_dist),
            "mejores_laps": {str(d): [[round(p, 1), fe] for p, fe, _ in sorted(v)[:5]] for d, v in best.items() if d >= 100},
        }, fh, ensure_ascii=False, indent=2)
    print("Escrito informes/audit_04_natacion.json")


if __name__ == "__main__":
    main()
