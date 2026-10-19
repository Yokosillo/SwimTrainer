#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Reconstruccion de series de natacion y deteccion de material.

Criterio (identico al de la auditoria, para que las cifras nuevas y las viejas cuadren):

1. **Lap activo**: lap con distancia > 0. **Lap de descanso**: lap con distancia = 0.
2. **Serie**: repeticiones consecutivas con la **misma distancia** separadas por descansos de
   como maximo 180 s. Un descanso mayor cierra la serie.
3. **Ritmo de repeticion** = tiempo del lap / (distancia / 100).
4. **Deriva** = ritmo de la ultima repeticion menos el de la primera (positivo = se cansa).
5. **Serie comparable**: >= 3 repeticiones, sin trabajo de tecnica y con ritmo entre 45 y 400 s/100 m.

Material: el reloj **no lo registra**. Lo unico que se puede hacer de forma automatica es leer la
palabra clave del **nombre de la actividad** en Garmin Connect (mecanismo acordado con el atleta).
Todo lo demas queda como `sin_etiquetar` y **no se debe dar por brazo libre**.
"""

from __future__ import annotations

import re
import statistics as st

from . import concepto

PALABRAS_MATERIAL = {
    "palas": "palas",
    "aletas": "aletas",
    "pull": "pull",
    "boya": "pull",
    "tabla": "tabla",
    "kickboard": "tabla",
    "manoplas": "palas",
    "snorkel": "snorkel",
    "tuba": "snorkel",          # es el mismo material con el nombre que usa el atleta
}

DIST_MAX_SERIE_M = 3000.0
DESCANSO_MAX_S = 180.0     # tope de partida; manda el que ha aprendido de sus partes
RITMO_MIN, RITMO_MAX = 45.0, 400.0
MIN_REPS_SERIE = 2      # una repeticion suelta no es una serie: es un bloque continuo
MIN_REPS_COMPARABLE = 3
# Rango de una repeticion *creible* de este atleta. Fuera de ahi el lap tiene el reloj mal disparado
# (pulsaciones de lap con tiempo de cronometro irreal): se descarta la repeticion, no la serie entera.
RITMO_MIN_REP, RITMO_MAX_REP = 60.0, 300.0


def material_desde_nombre(nombre: str | None) -> str | None:
    """Devuelve el material si el nombre de la actividad lo menciona (mecanismo acordado)."""
    if not nombre:
        return None
    texto = nombre.lower()
    for clave, valor in PALABRAS_MATERIAL.items():
        if re.search(rf"\b{clave}", texto):
            return valor
    return None


def ritmo_100(dist_m: float, timer_s: float) -> float | None:
    """Ritmo en segundos por 100 m. Devuelve None si no es calculable."""
    if not dist_m or not timer_s or dist_m <= 0 or timer_s <= 0:
        return None
    return 100.0 * timer_s / dist_m


def descanso_max_serie() -> float:
    """Cuanto descanso cabe todavia dentro de una serie: lo aprendido de sus partes, o el tope de siempre.

    Su forma de agrupar sale de sus propios partes (`aprendizaje.agrupacion`): si nunca ha descansado mas de
    40 s dentro de una serie, una pausa de 90 s ya es otra cosa. El importe se lee aqui en vez de pasarlo
    desde fuera para que no haya forma de importar un entrenamiento agrupandolo con el criterio viejo.
    """
    try:
        from . import aprendizaje
        return float(aprendizaje.descanso_mismo_bloque())
    except Exception:      # sin partes de los que aprender, o sin fichero: el criterio de siempre
        return DESCANSO_MAX_S


def reconstruir_series(laps: list[dict], descanso_max_s: float | None = None) -> list[dict]:
    """Agrupa los laps en series segun el criterio documentado arriba.

    Solo se devuelven los grupos con `MIN_REPS_SERIE` repeticiones o mas: una repeticion suelta
    es un bloque continuo (se guarda como lap, no como serie) y mezclarlas inflaria el catalogo.
    """
    tope_descanso = float(descanso_max_s) if descanso_max_s else descanso_max_serie()
    series: list[dict] = []
    actual: list[dict] = []          # repeticiones de la serie en curso
    descansos: list[float] = []      # descansos dentro de la serie en curso
    for lap in laps:
        dist = lap.get("dist_m") or 0.0
        if dist <= 0:
            if actual:
                descansos.append(lap.get("timer_s") or 0.0)
            continue
        if dist > DIST_MAX_SERIE_M:
            # bloque continuo de fondo: no es una serie
            if actual:
                series.append(_cerrar(actual, descansos))
                actual, descansos = [], []
            continue
        if actual and (abs(dist - actual[0]["dist_m"]) > 0.5 or (descansos and descansos[-1] > tope_descanso)):
            series.append(_cerrar(actual, descansos))
            actual, descansos = [], []
        actual.append({"dist_m": dist, "timer_s": lap.get("timer_s") or 0.0,
                       "estilo": lap.get("estilo"), "material": lap.get("material")})
    if actual:
        series.append(_cerrar(actual, descansos))
    series = [s for s in series if s["n_reps_validas"] >= MIN_REPS_SERIE]
    for i, s in enumerate(series):
        s["orden"] = i
    return series


def _cerrar(reps: list[dict], descansos: list[float]) -> dict:
    todos = [ritmo_100(r["dist_m"], r["timer_s"]) for r in reps]
    # Se descartan las repeticiones con cronometro irreal (el reloj dispara laps con tiempos que no
    # cuadran con la distancia): mejor perder una repeticion que publicar un ritmo imposible.
    ritmos = [r for r in todos if r is not None and RITMO_MIN_REP <= r <= RITMO_MAX_REP]
    descartadas = len(todos) - len(ritmos)
    material = next((r["material"] for r in reps if r.get("material") and r["material"] != "sin_etiquetar"),
                    "sin_etiquetar")
    s = {
        "rep_m": reps[0]["dist_m"] if reps else 0.0,
        "n_reps": len(reps),
        "n_reps_validas": len(ritmos),
        "volumen_m": sum(r["dist_m"] for r in reps),
        "estilo": next((r["estilo"] for r in reps if r.get("estilo")), None),
        "material": material or "sin_etiquetar",
        "calidad": "sospechosa" if descartadas else "normal",
        "ritmo_medio_100": st.mean(ritmos) if ritmos else None,
        "mejor_100": min(ritmos) if ritmos else None,
        "peor_100": max(ritmos) if ritmos else None,
        "sd_100": st.pstdev(ritmos) if len(ritmos) > 1 else 0.0,
        "descanso_medio_s": st.mean(descansos) if descansos else None,
        "deriva_s": (ritmos[-1] - ritmos[0]) if len(ritmos) >= 2 else None,
    }
    # La forma de la serie (regular, progresiva, aflojando...) sale de sus propios tiempos, con el margen que
    # ha aprendido el sistema: no hay que declararla.
    evidencia = concepto.medir(ritmos) if len(ritmos) >= concepto.MIN_REPS else None
    s["concepto"] = (evidencia or {}).get("concepto")
    s["concepto_evidencia"] = evidencia
    s["comparable"] = int(
        s["n_reps_validas"] >= MIN_REPS_COMPARABLE
        and (s["estilo"] or "") != "drill"
        and s["ritmo_medio_100"] is not None
        and RITMO_MIN <= s["ritmo_medio_100"] <= RITMO_MAX
        and s["material"] == "sin_etiquetar"   # las series con material NO son comparables
    )
    return s
