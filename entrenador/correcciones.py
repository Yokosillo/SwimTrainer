"""Lo que el atleta corrige de un entrenamiento, con su motivo (V1.2-06).

El reloj no siempre acierta y **el atleta tiene la ultima palabra sobre su propio entrenamiento**: si dice que los
10 segundos del ultimo 100 del 1.500 no son suyos (se paso de ritmo, el reloj conto de mas), se apunta aqui. Lo que
no se hace nunca es **tocar el dato del reloj**: la correccion va encima, con autor y motivo, y se dice siempre que
se enseñe el tramo corregido. Un dato corregido sin decirlo es un dato falso.

Donde cae: `desde_m` y `hasta_m` son metros **acumulados dentro de la sesion**, no del bloque. El 1.500 de la
sesion de hoy (3.100 m) va del metro 800 al 2.300, asi que su 100 final es el tramo 2.200-2.300. Cualquier trozo que
se mida despues (el total, un bloque, el parcial de cada 100) pregunta cuanto se corrige dentro de su tramo con
`segundos_en` y lo aplica al decirlo. El signo manda: negativo resta, positivo suma.
"""
from __future__ import annotations

import sqlite3

from . import db


def _mil(numero: float) -> str:
    """El numero con coma decimal, como se lee en castellano."""
    return f"{abs(numero):.1f}".replace(".", ",")


def de(cn: sqlite3.Connection, actividad_id: int) -> list[dict]:
    """Las correcciones de una sesion, de la primera a la ultima en el tiempo."""
    return [dict(f) for f in cn.execute(
        "SELECT * FROM correccion WHERE actividad_id = ? ORDER BY desde_m, id", (actividad_id,))]


def segundos_en(cn: sqlite3.Connection, actividad_id: int, desde_m: float, hasta_m: float) -> float:
    """Lo que hay que sumar al tiempo de un tramo (metros acumulados) por las correcciones que caen dentro.

    Se aplica la correccion entera si el tramo la cubre; si el tramo la parte (una correccion de 100 m mirada por
    tramos de 50), se reparte por metros. Asi el total y los parciales cuadran entre si.
    """
    total = 0.0
    for c in de(cn, actividad_id):
        largo = c["hasta_m"] - c["desde_m"]
        if largo <= 0:
            continue
        solape = min(hasta_m, c["hasta_m"]) - max(desde_m, c["desde_m"])
        if solape <= 0:
            continue
        total += c["segundos"] * (solape / largo)
    return round(total, 1)


def anotar(cn: sqlite3.Connection, actividad_id: int, desde_m: float, hasta_m: float, segundos: float,
           motivo: str, fuente: str = "atleta") -> int:
    """Apunta una correccion del atleta sobre una sesion. Devuelve su id."""
    if not motivo or not motivo.strip():
        raise ValueError("una correccion sin motivo no entra: hay que decir por que (es lo que la hace tuya)")
    if hasta_m <= desde_m:
        raise ValueError("el tramo de la correccion tiene que acabar despues de empezar (metros acumulados)")
    cur = cn.execute(
        "INSERT INTO correccion (actividad_id, desde_m, hasta_m, segundos, motivo, fuente, creado_en) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (actividad_id, float(desde_m), float(hasta_m), float(segundos), motivo.strip(), fuente, db.ahora()))
    cn.commit()
    return cur.lastrowid


def texto(c: dict) -> str:
    """Una correccion en una linea, en llano, con el tramo y el motivo."""
    signo = "quita" if c["segundos"] < 0 else "suma"
    return (f"Corregido por ti: {signo} {_mil(c['segundos'])} s en los metros "
            f"{int(c['desde_m'])}-{int(c['hasta_m'])} ({c['motivo']})")


def por_lap(cn: sqlite3.Connection, actividad_id: int, laps: list[dict]) -> dict[int, float]:
    """Los segundos que el atleta corrigio, repartidos por intervalo: {lap_idx: segundos}.

    El atleta corrige en metros acumulados de la sesion ("del 2.250 al 2.350") y cada intervalo ocupa un tramo de
    esos metros: aqui se reparte. Una correccion a caballo de dos intervalos se parte sola, porque `segundos_en`
    devuelve la parte que cae dentro de cada tramo.
    """
    fuera: dict[int, float] = {}
    acumulado = 0.0
    for lap in sorted(laps, key=lambda l: float(l.get("lap_idx") or 0)):
        metros = float(lap.get("dist_m") or 0)
        if metros > 0:
            trozo = segundos_en(cn, actividad_id, acumulado, acumulado + metros)
            if trozo:
                fuera[int(lap.get("lap_idx"))] = trozo
        acumulado += metros
    return fuera


def aplicar(cn: sqlite3.Connection, actividad_id: int, laps: list[dict],
            grupos: list[dict]) -> list[dict]:
    """Mete la correccion del atleta en los tiempos de los grupos que van al portal.

    **Su palabra es la buena**: el tiempo de la repeticion pasa a ser el suyo, y con el el ritmo y el total del bloque
    (que es la suma de lo de dentro). El dato del reloj **no se borra**: se queda en `tiempo_del_reloj_s`, para poder
    enseñar los dos. Se aplica **por diferencia**, asi que no pisa lo que el atleta haya escrito a mano en su parte:
    se le suma.
    """
    repartido = por_lap(cn, actividad_id, laps)
    if not repartido:
        return grupos
    for grupo in grupos:
        delta = 0.0
        for rep in grupo.get("reps") or []:
            lap_idx = rep.get("lap_idx")
            suyo = float(repartido.get(int(lap_idx), 0.0)) if lap_idx is not None else 0.0
            campo = "tiempo_s" if rep.get("tiempo_s") is not None else "timer_s"
            if rep.get(campo) is None:
                continue
            antes = float(rep[campo])
            rep["tiempo_del_reloj_s"] = round(float(rep.get("lap_del_reloj_s") or antes), 2)
            if suyo:
                ahora = round(antes + suyo, 2)
                for c in ("timer_s", "tiempo_s"):
                    if rep.get(c) is not None:
                        rep[c] = ahora
                rep["corregido_s"] = round(float(rep.get("corregido_s") or 0.0) + suyo, 2)
                if rep.get("dist_m"):
                    rep["ritmo_100"] = round(100.0 * ahora / float(rep["dist_m"]), 1)
            delta += float(rep[campo]) - antes
        if delta:
            if grupo.get("tiempo_s") is not None:
                grupo["tiempo_s"] = round(float(grupo["tiempo_s"]) + delta, 2)
            if grupo.get("total_s") is not None:
                grupo["total_s"] = round(float(grupo["total_s"]) + delta, 2)
            if grupo.get("ritmo_100") and grupo.get("metros"):
                grupo["ritmo_100"] = round(100.0 * float(grupo["tiempo_s"]) / float(grupo["metros"]), 1)
    return grupos


def texto_de(cn: sqlite3.Connection, actividad_id: int) -> str:
    """Todas las correcciones de una sesion, en una linea. Vacio si no hay ninguna."""
    dichas = [texto(c) for c in de(cn, actividad_id)]
    return "; ".join(dichas)
