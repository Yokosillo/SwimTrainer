"""Los pasos de cada 100 m dentro de una repeticion larga (V1.2-08).

Cuando la repeticion pasa de 400 m (el 1.500 del test, un 4x400, un 800 seguido), el tiempo total no dice donde se
ha ido ni si has salido fuerte y has pagado al final. Los pasos de cada 100 si. Salen de los largos del reloj
(`natacion_largo`), que traen el tiempo de cada 25 m: se agrupan de cuatro en cuatro.

**Los largos se reparten por hora de inicio, no contando.** Contar `n_largos` desplaza la cuenta (los descansos
tambien ocupan largos y los laps de descanso no los declaran), y probado con el 1.500 del 18/10 sale mal: por hora,
el lap del 1.500 son los largos 44 a 103 y sus tiempos suman 1.340,2 s, **clavados** al lap. Por recuento, no.

**Lo que el atleta corrige se aplica al paso que le toca**: la correccion se guarda en metros acumulados de la
sesion, igual que los tramos que se miden aqui, asi que el "quita 10 s del ultimo 100" del 1.500 sale en su paso y
los demas no se tocan.

**Solo se calcula a partir de `MIN_PASOS_M`**: en una serie de 100 cada repeticion ya es un 100 y no hay nada que
desglosar (y un 200 tampoco se lee mejor partido).
"""
from __future__ import annotations

import sqlite3

from . import correcciones

MIN_PASOS_M = 400.0     # de aqui para arriba (400, 800, 1500...) la repeticion se desglosa
CADA_M = 100.0          # el paso que se enseña
# Y solo si va a ritmo de serie: el calentamiento no se desglosa (no dice nada de como has nadado la serie). Regla
# del atleta (2026-10-18): por debajo de 1:30 de media por 100 en un 400 y de 1:33 en las distancias mayores.
RITMO_TOPE_400_S = 90.0
RITMO_TOPE_LARGO_S = 93.0


def pasa_el_ritmo(metros: float, segundos: float, minimo_m: float = MIN_PASOS_M) -> bool:
    """¿Esta repeticion se desglosa, o es calentamiento?

    Un 400 entra a partir de 1:30 de media por 100; de 400 para arriba, de 1:33. La media es la que vale: la que
    nadó, con la correccion del atleta dentro si la hay.
    """
    if not metros or not segundos:
        return False
    tope = RITMO_TOPE_400_S if float(metros) <= minimo_m else RITMO_TOPE_LARGO_S
    return (100.0 * float(segundos) / float(metros)) < tope


def _laps(cn: sqlite3.Connection, actividad_id: int) -> list[dict]:
    """Los intervalos de la sesion, en orden."""
    return [dict(f) for f in cn.execute(
        "SELECT lap_idx, inicio, dist_m, timer_s, n_largos, estilo, es_descanso FROM natacion_lap "
        "WHERE actividad_id = ? ORDER BY lap_idx", (actividad_id,))]


def _largos(cn: sqlite3.Connection, actividad_id: int) -> list[dict]:
    """Los largos de la sesion, en orden."""
    return [dict(f) for f in cn.execute(
        "SELECT len_idx, inicio, tipo, estilo, timer_s, brazadas FROM natacion_largo "
        "WHERE actividad_id = ? ORDER BY len_idx", (actividad_id,))]


def largos_por_lap(cn: sqlite3.Connection, actividad_id: int) -> dict[int, list[dict]]:
    """Cada largo con su intervalo: del inicio de un lap al inicio del siguiente.

    Un largo cae en el ultimo lap que ha empezado antes que el. Los laps sin largos salen con lista vacia (los hay
    con el cronometro mal disparado y sin largos grabados: no se inventa nada).
    """
    laps = _laps(cn, actividad_id)
    salida: dict[int, list[dict]] = {l["lap_idx"]: [] for l in laps}
    for largo in _largos(cn, actividad_id):
        dentro = [l for l in laps if l["inicio"] and largo["inicio"] and l["inicio"] <= largo["inicio"]]
        if dentro:
            salida[dentro[-1]["lap_idx"]].append(largo)
    return salida


def _desde_de(laps: list[dict], lap_idx: int) -> float:
    """Los metros que ya llevaba nadados la sesion cuando empezo ese intervalo (acumulado, como las correcciones)."""
    return round(sum(float(l["dist_m"] or 0) for l in laps if l["lap_idx"] < lap_idx), 1)


def de_rep(cn: sqlite3.Connection, actividad_id: int, lap_idx: int,
           cada_m: float = CADA_M, minimo_m: float = MIN_PASOS_M) -> list[dict]:
    """Los pasos de cada `cada_m` metros de una repeticion, con lo que el atleta haya corregido dentro.

    Cada paso lleva su tramo en metros **acumulados de la sesion** (para poder cruzarlo con `correcciones`), su
    tiempo, su ritmo de 100, las brazadas y, si hay correccion en ese tramo, los segundos que quita o suma y el
    tiempo corregido. Lista vacia si la repeticion no tiene largos con tiempo (no se puede desglosar).
    """
    laps = _laps(cn, actividad_id)
    lap = next((l for l in laps if l["lap_idx"] == lap_idx), None)
    if lap is None:
        return []
    largos = [x for x in largos_por_lap(cn, actividad_id).get(lap_idx, [])
              if x["tipo"] == "active" and x["timer_s"]]
    if not largos:
        return []

    metros = float(lap["dist_m"] or 0)
    if metros < minimo_m:
        return []          # por debajo del minimo no hay nada que desglosar: el paso ya es la repeticion
    paso_m = (metros / len(largos)) if metros else 0.0     # el largo de piscina que le toca a esta repeticion
    if paso_m <= 0:
        return []
    inicio = _desde_de(laps, lap_idx)

    pasos: list[dict] = []
    acumulado = 0.0
    actual = {"segundos": 0.0, "brazadas": 0.0, "largos": 0}
    for largo in largos:
        actual["segundos"] += float(largo["timer_s"] or 0)
        actual["brazadas"] += float(largo["brazadas"] or 0)
        actual["largos"] += 1
        acumulado += paso_m
        if acumulado + 1e-6 >= cada_m * (len(pasos) + 1):
            desde = round(inicio + cada_m * len(pasos), 1)
            hasta = round(desde + cada_m, 1)
            corregido = correcciones.segundos_en(cn, actividad_id, desde, hasta)
            # Con centesimas: dos pasos de 85,94 y 85,87 son distintos y con una decimal los dos salian 85,9 (el
            # atleta lo vio: "veo poco probable que el primero y el segundo 100 sean al mismo tiempo"). El reloj
            # guarda milesimas de segundo por largo; tirarlas aqui es perder lo unico que distingue un paso de otro.
            segundos = round(actual["segundos"], 2)
            pasos.append({
                "n": len(pasos) + 1,
                "desde_m": desde, "hasta_m": hasta,
                "segundos": segundos,
                "ritmo_100": round(100.0 * segundos / cada_m, 2) if segundos else None,
                "brazadas": int(actual["brazadas"]) if actual["brazadas"] else None,
                "largos": actual["largos"],
                "correccion_s": corregido or None,
                "segundos_corregidos": round(segundos + corregido, 2) if corregido else None,
            })
            actual = {"segundos": 0.0, "brazadas": 0.0, "largos": 0}

    # El calentamiento no se desglosa: solo las repeticiones que van a ritmo de serie (regla del atleta). Se mira la
    # media de verdad, la que nadó, con la correccion dentro si la hay.
    segundos_reales = sum(p["segundos_corregidos"] or p["segundos"] for p in pasos)
    if not pasa_el_ritmo(metros, segundos_reales, minimo_m):
        return []
    return pasos


def pasos_de(cn: sqlite3.Connection, actividad_id: int, grupos: list[dict],
             minimo_m: float = MIN_PASOS_M) -> list[dict]:
    """Pega los pasos a las repeticiones que pasan del minimo. Devuelve los mismos grupos, tocados.

    Se llama donde ya hay base de datos y los grupos armados (las dos puertas del portal: la sesion que espera parte y
    la que ya lo tiene), para que el portal no tenga que saber de largos.

    Y **el total de la repeticion pasa a ser la suma de sus pasos** (regla del atleta, 2026-10-18: "el total debe ser
    la suma de los pasos y que se aplique mi corrección"): el numero de arriba es exactamente el que suman los de
    abajo. El lap entero del reloj no se pierde: se guarda en `lap_del_reloj_s`, y el bloque se ajusta por la
    diferencia que esto cause, para que siga cuadrando con lo de dentro.
    """
    for grupo in grupos:
        delta = 0.0
        for rep in grupo.get("reps", []):
            rep.pop("pasos", None)
            if float(rep.get("dist_m") or 0) < minimo_m:
                continue
            pasos = de_rep(cn, actividad_id, rep["lap_idx"])
            if not pasos:
                continue
            rep["pasos"] = pasos
            delos_pasos = round(sum(float(p["segundos"]) for p in pasos), 2)
            for campo in ("timer_s", "tiempo_s"):
                if rep.get(campo) is None:
                    continue
                if rep.get("lap_del_reloj_s") is None:
                    rep["lap_del_reloj_s"] = round(float(rep[campo]), 2)
                antes = float(rep[campo])
                rep[campo] = delos_pasos
                if campo == "timer_s":
                    delta += delos_pasos - antes
            if rep.get("dist_m"):
                rep["ritmo_100"] = round(100.0 * delos_pasos / float(rep["dist_m"]), 1)
        if delta:
            if grupo.get("tiempo_s") is not None:
                grupo["tiempo_s"] = round(float(grupo["tiempo_s"]) + delta, 2)
            if grupo.get("total_s") is not None:
                grupo["total_s"] = round(float(grupo["total_s"]) + delta, 2)
            if grupo.get("ritmo_100") and grupo.get("metros"):
                grupo["ritmo_100"] = round(100.0 * float(grupo["tiempo_s"]) / float(grupo["metros"]), 1)
    return grupos
