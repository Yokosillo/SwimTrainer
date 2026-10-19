#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Ingenieria inversa del historial propio: de que estaban hechas sus mejores rachas.

Pregunta que contesta: de 2021-2026 (los anios con entrenamientos registrados) **que habia en las semanas en
las que el atleta nadaba mas rapido** que no habia en las flojas. No busca causa-efecto: busca diferencias
grandes y repetidas, que son las que merecen convertirse en regla del motor (`entrenador/estimulos.py`).

Metodo:
  1. Coge todos los bloques continuos del historico (`analitica.bloques`), se queda con los fiables de brazo
     libre y los agrupa por dia y distancia parecida: un dia con 8 bloques de ~100 m es una serie de 8x100.
  2. Calcula el perfil de estimulos de cada semana con `estimulos.clasificar` (el criterio escrito a mano).
  3. Indicador de forma: el **ritmo mediano de la calidad** de la semana (sus series, no su fondo). Y un
     indicador de descanso medible de verdad: la **densidad de nado** (tiempo nadando / tiempo en el agua),
     porque el export no guarda la hora de cada lap y el descanso por repeticion no se puede reconstruir.
  4. Compara mejores y peores semanas **con volumen parecido**, que si no las semanas de 3 dias y 5 km ganan la
     comparacion solo porque en una sesion corta un 100 rapido manda en la mediana.

Salida: informe por consola y, con `--guardar`, en `informes/M_ingenieria_inversa.md`. Si algo no tiene datos
suficientes, se dice; no se rellena el hueco.

Uso:
    .venv/Scripts/python.exe scripts/ingenieria_inversa.py            # informe por consola
    .venv/Scripts/python.exe scripts/ingenieria_inversa.py --guardar  # y lo escribe en informes/
"""

from __future__ import annotations

import os
import statistics as st
import sys
from collections import defaultdict
from datetime import date, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from entrenador import analitica, db, estimulos  # noqa: E402

BD = os.path.join(RAIZ, "data", "entrenador.db")
OBJETIVO_100 = 75.0        # ritmo del reto del 400: las bandas del clasificador se miden contra el
MIN_CALIDAD_M = 1500.0     # metros de calidad que debe tener una semana para entrar en la comparacion
MIN_BLOQUE = 100.0         # por debajo de esto es tecnica o resto, no una repeticion
KM_MIN, KM_MAX = 5.0, 11.0  # rango de volumen para la comparacion controlada


def lunes(fecha: str) -> str:
    d = date.fromisoformat(fecha[:10])
    return (d - timedelta(days=d.weekday())).isoformat()


def agrupar_en_series(bloques_dia: list[dict]) -> list[dict]:
    """Junta los bloques sueltos de un mismo dia en series: 8 bloques de ~100 m = 8x100.

    El reloj no sabe que eran una serie: graba bloques separados por el descanso. Se agrupan por distancia
    parecida (a 25 m, que es el largo). El descanso por repeticion NO se rellena: el export no guarda la hora de
    cada lap, asi que inventarlo seria peor que dejarlo vacio (el descanso se mide por la densidad de la sesion).
    """
    por_dist: dict[int, list[dict]] = defaultdict(list)
    for b in bloques_dia:
        por_dist[int(round(b["dist_m"] / 25.0) * 25)].append(b)
    series: list[dict] = []
    for dist, grupo in sorted(por_dist.items()):
        if len(grupo) == 1:
            b = grupo[0]
            series.append({"metros": b["dist_m"], "n_reps": 1, "rep_m": b["dist_m"],
                           "tiempo_s": b["tiempo_s"], "ritmo_100": b["ritmo_100"],
                           "descanso_s": None, "material": (b.get("material") or ""),
                           "fiable": b.get("fiable", True)})
            continue
        reps = [b["dist_m"] for b in grupo]
        rep_m = st.median(reps)
        metros = sum(reps)
        tiempo = sum(b["tiempo_s"] for b in grupo)
        ritmo = (100.0 * tiempo / metros) if metros else None
        series.append({"metros": metros, "n_reps": len(grupo), "rep_m": rep_m, "tiempo_s": tiempo,
                       "ritmo_100": ritmo, "descanso_s": None,
                       "material": ", ".join(sorted({b.get("material") for b in grupo if b.get("material")})),
                       "fiable": all(b.get("fiable", True) for b in grupo)})
    return series


def duraciones(cn) -> dict:
    """Duracion de cada sesion: hace falta para la densidad (el descanso real de la sesion)."""
    return {f["id"]: f["duracion_s"] for f in
            cn.execute("SELECT id, duracion_s FROM actividad WHERE duracion_s IS NOT NULL")}


def semanas(bloques: list[dict], duras: dict) -> dict[str, dict]:
    """Perfil por semana (lunes-domingo): volumen, dias, estimulos, forma y densidad de nado."""
    por_dia: dict[str, list[dict]] = defaultdict(list)
    por_dia_id: dict[str, set] = defaultdict(set)
    for b in bloques:
        if not b.get("fecha"):
            continue
        if not b.get("fiable", True) or not b.get("brazo_libre", True):
            continue                      # con material el ritmo no es comparable entre epocas
        if float(b.get("dist_m") or 0) < MIN_BLOQUE:
            continue
        por_dia[b["fecha"]].append(b)
        por_dia_id[b["fecha"]].add(b["actividad_id"])

    por_semana: dict[str, list[str]] = defaultdict(list)
    for fecha in por_dia:
        por_semana[lunes(fecha)].append(fecha)

    fuera: dict[str, dict] = {}
    for sem, fechas in por_semana.items():
        perfiles, ritmos, densidades = [], [], []
        continuo_mas_largo, calidad_m, nadado_s, agua_s = 0.0, 0.0, 0.0, 0.0
        for fecha in sorted(fechas):
            series = agrupar_en_series(por_dia[fecha])
            p = estimulos.perfil(series, OBJETIVO_100)
            perfiles.append(p)
            calidad_m += p["calidad_m"]
            continuo_mas_largo = max(continuo_mas_largo, p["continuo_mas_largo"])
            # Densidad: de cada minuto en el agua, cuantos se nadan. El resto son descansos y charla.
            nado_dia = sum(s["tiempo_s"] or 0 for s in series)
            agua_dia = sum(float(duras.get(i) or 0) for i in por_dia_id[fecha])
            if agua_dia:
                densidades.append(nado_dia / agua_dia)
                nadado_s += nado_dia
                agua_s += agua_dia
            # Ritmo de la calidad del dia: la serie con mas metros que aprieta (no el bloque suelto corto).
            candidatas = [s for s in series if (s["n_reps"] >= 2 or s["metros"] >= 200)
                          and s["metros"] >= 100 and s["ritmo_100"]]
            if candidatas:
                ritmos.append(min(candidatas, key=lambda s: s["ritmo_100"])["ritmo_100"])
        por_clase: dict[str, float] = defaultdict(float)
        for p in perfiles:
            for k, v in p["por_clase"].items():
                por_clase[k] += v
        fuera[sem] = {
            "semana": sem, "dias": len(fechas),
            "km": sum(p["total_m"] for p in perfiles) / 1000.0,
            "calidad_km": calidad_m / 1000.0,
            "continuo_mas_largo": continuo_mas_largo,
            "ritmo_calidad": st.median(ritmos) if ritmos else None,
            "densidad": (nadado_s / agua_s) if agua_s else None,
            "por_clase": dict(por_clase),
        }
    return fuera


def media(lista, clave):
    vals = [x[clave] for x in lista if x.get(clave) is not None]
    return st.median(vals) if vals else None


def fmt(v, dec=1, unidad=""):
    return "—" if v is None else f"{v:.{dec}f}{unidad}"


def tabla_resumen(di, filas):
    """Las lineas de la tabla van por `di` (no directas a la lista): si no, no se ven en consola."""
    di("| | km/semana | Dias/semana | Continuo mas largo | Ritmo de calidad | Densidad de nado |")
    di("|---|---|---|---|---|---|")
    for nombre, grupo in filas:
        di(f"| **{nombre}** | {fmt(media(grupo, 'km'))} | {fmt(media(grupo, 'dias'))} | "
           f"{fmt(media(grupo, 'continuo_mas_largo'), 0, ' m')} | "
           f"{fmt(media(grupo, 'ritmo_calidad'))} s/100 | {fmt(media(grupo, 'densidad'), 2)} |")


def main() -> int:
    cn = db.conectar(BD)
    print("Leyendo los bloques del historico...")
    bloques = analitica.bloques(cn)
    duras = duraciones(cn)
    print(f"  {len(bloques)} bloques continuos")
    sem = semanas(bloques, duras)

    con_datos = [s for s in sem.values() if s["calidad_km"] * 1000 >= MIN_CALIDAD_M and s["ritmo_calidad"]]
    con_datos.sort(key=lambda s: s["semana"])

    lineas: list[str] = []

    def di(t=""):
        print(t)
        lineas.append(t)

    di(f"# Ingenieria inversa del historial (generado {date.today().isoformat()})")
    di()
    di("De que estaban hechas sus semanas, mirando solo bloques fiables y **a brazo libre** (con material el")
    di("ritmo no es comparable). Indicadores: el **ritmo mediano de la calidad** (sus series, no su fondo) y la")
    di("**densidad de nado** (tiempo nadando sobre tiempo en el agua: lo contrario del descanso).")
    di()
    di(f"Semanas con datos suficientes: **{len(con_datos)}** (de {len(sem)} con algun bloque), "
       f"minimo {MIN_CALIDAD_M:.0f} m de calidad.")
    di()

    di("## Por anio")
    di()
    di("| Anio | Semanas | km/semana | Dias/semana | Continuo mas largo | Ritmo de calidad | Densidad |")
    di("|---|---|---|---|---|---|---|")
    for anio in sorted({s["semana"][:4] for s in con_datos}):
        grupo = [s for s in con_datos if s["semana"].startswith(anio)]
        di(f"| {anio} | {len(grupo)} | {fmt(media(grupo, 'km'))} | {fmt(media(grupo, 'dias'))} | "
           f"{fmt(media(grupo, 'continuo_mas_largo'), 0, ' m')} | {fmt(media(grupo, 'ritmo_calidad'))} s/100 | "
           f"{fmt(media(grupo, 'densidad'), 2)} |")
    di()

    mitad = len(con_datos) // 2 or 1
    ordenadas = sorted(con_datos, key=lambda s: s["ritmo_calidad"])
    buenas, malas = ordenadas[:mitad], ordenadas[-mitad:]
    di(f"## Mejores y peores semanas ({mitad} de cada lado, por ritmo de calidad)")
    di()
    tabla_resumen(di, [("Todas: mejores", buenas), ("Todas: peores", malas)])
    di()
    # Control por volumen: si no, las semanas de 3 dias y 5 km ganan solo porque un 100 rapido manda en la mediana.
    comparables = [s for s in con_datos if KM_MIN <= s["km"] <= KM_MAX]
    if len(comparables) >= 8:
        m2 = len(comparables) // 2
        ord2 = sorted(comparables, key=lambda s: s["ritmo_calidad"])
        di(f"### Controlando por volumen ({KM_MIN:.0f}-{KM_MAX:.0f} km/semana, {len(comparables)} semanas)")
        di()
        di(f"Aqui se comparan semanas de tamano parecido: es la comparacion que vale.")
        di()
        tabla_resumen(di, [("Parecidas: mejores", ord2[:m2]), ("Parecidas: peores", ord2[-m2:])])
        buenas, malas = ord2[:m2], ord2[-m2:]
        di()
    else:
        di(f"_No hay semanas suficientes entre {KM_MIN:.0f} y {KM_MAX:.0f} km para controlar el volumen._")
        di()

    di("### Reparto de estimulos (metros de calidad por clase)")
    di()
    clases = [c for c in estimulos.CLASES if c not in ("calentamiento", "tecnica")]
    di("| Clase | Mejores (% del total) | Peores (% del total) | Diferencia |")
    di("|---|---|---|---|")

    def pct(grupo, c):
        total = sum(s["por_clase"].get(k, 0) for s in grupo for k in clases)
        return (100.0 * sum(s["por_clase"].get(c, 0) for s in grupo) / total) if total else None

    for c in clases:
        a, b = pct(buenas, c), pct(malas, c)
        dif = f"{a - b:+.1f}" if (a is not None and b is not None) else "—"
        di(f"| {estimulos.CLASES[c]['nombre']} | {fmt(a)} | {fmt(b)} | {dif} |")
    di()

    di("### Las 15 mejores semanas, una a una")
    di()
    di("| Semana | km | Dias | Continuo mas largo | Ritmo de calidad | Densidad | Clase dominante |")
    di("|---|---|---|---|---|---|---|")
    for s in ordenadas[:15]:
        carga = {k: v for k, v in s["por_clase"].items() if k in clases}
        dom = max(carga, key=carga.get) if carga else "—"
        di(f"| {s['semana']} | {fmt(s['km'])} | {s['dias']} | {fmt(s['continuo_mas_largo'], 0, ' m')} | "
           f"{fmt(s['ritmo_calidad'])} | {fmt(s['densidad'], 2)} | "
           f"{estimulos.CLASES[dom]['nombre'] if dom in estimulos.CLASES else dom} |")
    di()

    hoy = date.today()
    recientes = [s for s in con_datos if s["semana"] >= (hoy - timedelta(days=42)).isoformat()]
    di("## Ahora mismo (ultimas 6 semanas con datos)")
    di()
    if recientes:
        di("| | km/semana | Dias/semana | Continuo mas largo | Ritmo de calidad | Densidad |")
        di("|---|---|---|---|---|---|")
        tabla_resumen(di, [("Ahora", recientes), ("Sus mejores", buenas)])
    else:
        di("_Sin semanas con datos suficientes en las ultimas 6 semanas._")
    di()

    di("## Lo que estos datos pueden y no pueden decir")
    di()
    di("1. **Pueden**: cuanto nadaba, cuantos dias, de que tipo de series estaba hecho el trabajo y a que ritmo")
    di("   salia su calidad. Y con eso, si un estimulo aparece o no en su historial.")
    di("2. **Pueden**: la densidad de nado (cuanto del tiempo en el agua se nada). Es el unico indicador de")
    di("   descanso que sobrevive al export.")
    di("3. **No pueden**: el descanso de cada repeticion ni el *cada* de una serie de hace anios: el export no")
    di("   guarda la hora de cada lap. Reconstruirlo seria inventarlo.")
    di("4. **No pueden**: decir causa-efecto. Que las mejores semanas tengan mas fondo sostenido no prueba que")
    di("   fuera eso lo que las hizo mejores; puede ser que cuando esta bien nada mas de todo.")
    di()

    texto = "\n".join(lineas) + "\n"
    if "--guardar" in sys.argv:
        destino = os.path.join(RAIZ, "informes", "M_ingenieria_inversa.md")
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        with open(destino, "w", encoding="utf-8", newline="\n") as f:
            f.write(texto)
        print(f"\nEscrito: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
