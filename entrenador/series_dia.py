#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""De que series se compone un dia, en una sola version (tarea V1.1-01 del anexo U).

**Por que existe.** La ventana de `estimulos` se estaba midiendo sobre la tabla `serie`, que solo guarda series
reconstruidas y comparables. Resultado: un dia con 3.400 m nadados podia salir como "continuo mas largo = 0 m",
y el motor pedia bloques continuos que el atleta si habia hecho. Aqui se junta lo que dice el dia, con una
prioridad escrita y comprobable:

  1. **El parte manda**, pero solo si esta entero: si el atleta subio el parte y sus lineas cubren al menos el
     90 % de lo que midio el reloj, las series del dia son las suyas (`parte_serie`), con material y ritmos.
  2. Si no hay parte, o el parte se quedo a medias, manda **el reloj**: los bloques del tiron de `analitica`,
     con los metros medidos. Sin parte el material es **desconocido**, y desconocido no es lo mismo que brazo
     libre (confundirlos fue el error del 1.000 m con aletas del 12/10/2026).
  3. Si no hay ninguna de las dos cosas, no hay series: no se rellena el hueco con una estimacion.

**Lo que este modulo NO puede hacer, y hay que decirlo.** Sin parte, el reloj da los metros del tiron pero no
la **estructura** de la serie: un 8x100 son ocho bloques de 100 m, no un 8x100. Esa estructura solo la declara
el parte, asi que `ventana` dice en cuantos dias se esta midiendo sin ella.

Uso:
    from . import series_dia
    series_dia.series_del_dia(cn, "2026-10-12")          # las series de ese dia, ya resueltas
    p = series_dia.ventana(cn, "2026-10-04", "2026-10-17", 75.0)   # el perfil de la ventana + de donde sale
"""

from __future__ import annotations

import sqlite3

from . import analitica, estimulos

# Cuanto del reloj tiene que cubrir el parte para que mande. Por debajo, el parte esta a medias y para medir
# metros manda el reloj (y se avisa): medir media sesion inventaria un deficit que no existe.
COBERTURA_MIN = 0.9

# Minimo de metros para que un tiron del reloj cuente como una serie del dia. El minimo de `analitica` (200 m)
# esta pensado para buscar marcas de referencia y deja fuera las series de 100 m: un dia de 3.900 m con 34
# descansos salia con 1.050 m. Aqui se baja a 50 m, que es el largo de piscina mas comun.
MIN_SERIE_M = 50.0


def _mil(metros: float) -> str:
    """Los metros con el punto de millar que se usa aqui: 1.000 m (para que los avisos se lean igual)."""
    return f"{int(round(float(metros or 0))):,}".replace(",", ".")


# --------------------------------------------------------------------------- las dos versiones del dia


def _series_del_parte(cn: sqlite3.Connection, fecha: str) -> list[dict]:
    """Las lineas del parte del dia, tal y como las declaro el atleta (con material y ritmos reales)."""
    filas = cn.execute(
        """SELECT s.*, p.id AS parte_id FROM parte_serie s JOIN parte p ON p.id = s.parte_id
           WHERE p.fecha = ? ORDER BY p.id, s.orden""", (fecha,)).fetchall()
    fuera: list[dict] = []
    for f in filas:
        d = dict(f)
        metros = float(d.get("metros") or 0)
        if metros <= 0:
            continue
        ritmo = d.get("ritmo_100")
        if not ritmo and d.get("tiempo_s"):
            ritmo = round(100.0 * float(d["tiempo_s"]) / metros, 1)
        material = (d.get("material") or "").strip()
        fuera.append({
            "fecha": fecha,
            "metros": metros,
            "n_reps": int(d.get("n_reps") or 1),
            "rep_m": float(d.get("rep_m") or metros),
            "descanso_s": d.get("descanso_s"),
            "ritmo_100": ritmo,
            "tiempo_s": d.get("tiempo_s"),
            "intensidad": d.get("intensidad"),
            "material": material or None,
            "materiales": [m for m in material.split(",") if m],
            # El parte se rellena entero: si no puso material, es que fue a brazo libre.
            "brazo_libre": material == "",
            "origen": "parte",
            "fiable": True,
            "parte_id": d.get("parte_id"),
            "orden": d.get("orden"),
            "nota": d.get("nota"),
        })
    return fuera


def _series_del_reloj(bloques: list[dict]) -> list[dict]:
    """Los bloques del reloj como series (una repeticion cada bloque: la estructura no la da el reloj)."""
    fuera: list[dict] = []
    for b in bloques:
        metros = float(b.get("dist_m") or 0)
        if metros <= 0:
            continue
        material = b.get("material")
        fuera.append({
            "fecha": b.get("fecha"),
            "metros": metros,
            "n_reps": 1,
            "rep_m": metros,
            "descanso_s": None,
            "ritmo_100": b.get("ritmo_100"),
            "tiempo_s": b.get("tiempo_s"),
            "intensidad": None,
            "material": material,
            "materiales": [m for m in (material or "").split(",") if m],
            # Sin parte no se sabe con que se hizo: None no es "brazo libre", es desconocido.
            "brazo_libre": True if (b.get("material_conocido") and b.get("brazo_libre")) else None,
            "origen": "reloj",
            "fiable": bool(b.get("fiable")),
            "actividad_id": b.get("actividad_id"),
            "n_laps": b.get("n_laps"),
            "domina_sesion": b.get("domina_sesion"),
            "material_conocido": b.get("material_conocido"),
        })
    return fuera


def _fechas(cn: sqlite3.Connection, desde: str, hasta: str, bloques: list[dict]) -> list[str]:
    """Los dias con algo que mirar: sesiones del reloj o partes subidos."""
    feas = {b["fecha"] for b in bloques if desde <= str(b["fecha"]) <= hasta}
    feas |= {r[0] for r in cn.execute(
        "SELECT DISTINCT fecha FROM parte WHERE fecha BETWEEN ? AND ?", (desde, hasta))}
    return sorted(f for f in feas if f)


def vistas_del_dia(cn: sqlite3.Connection, fecha: str, bloques: list[dict] | None = None) -> dict:
    """Las dos versiones del dia y cual manda, para poder decirlo en el portal sin adornos."""
    bloques = analitica.bloques(cn, MIN_SERIE_M) if bloques is None else bloques
    parte = _series_del_parte(cn, fecha)
    reloj = _series_del_reloj([b for b in bloques if str(b.get("fecha")) == fecha])
    m_parte = sum(s["metros"] for s in parte)
    m_reloj = sum(s["metros"] for s in reloj)
    cobertura = (m_parte / m_reloj) if m_reloj else None

    if not reloj:
        manda = "parte" if parte else None
    elif cobertura is not None and cobertura >= COBERTURA_MIN:
        manda = "parte"
    else:
        manda = "reloj"

    aviso = None
    if parte and manda == "reloj":
        aviso = (f"el parte del {fecha} declara {_mil(m_parte)} m y el reloj midio {_mil(m_reloj)} m "
                 f"({100.0 * (cobertura or 0):.0f} %): para medir metros manda el reloj, el parte esta a medias")
    elif not parte and reloj:
        aviso = (f"el {fecha} no tiene parte: los metros salen del reloj y el material queda desconocido")
    return {"fecha": fecha, "parte": parte, "reloj": reloj, "m_parte": m_parte, "m_reloj": m_reloj,
            "cobertura": round(cobertura, 2) if cobertura is not None else None, "manda": manda, "aviso": aviso}


def series_del_dia(cn: sqlite3.Connection, fecha: str, bloques: list[dict] | None = None) -> list[dict]:
    """Las series de un dia, ya resueltas: el parte si esta entero, el reloj si no. Sin datos, lista vacia."""
    v = vistas_del_dia(cn, fecha, bloques)
    if v["manda"] == "parte":
        return v["parte"]
    if v["manda"] == "reloj":
        return v["reloj"]
    return []


# --------------------------------------------------------------------------- la ventana


def series_por_fecha(cn: sqlite3.Connection, desde: str, hasta: str,
                     bloques: list[dict] | None = None) -> dict[str, list[dict]]:
    """`{fecha: [series]}` de la ventana: es lo que come `estimulos.perfil_de_ventana`."""
    bloques = analitica.bloques(cn, MIN_SERIE_M) if bloques is None else bloques
    return {f: series_del_dia(cn, f, bloques) for f in _fechas(cn, desde, hasta, bloques)}


def perfil_del_dia(cn: sqlite3.Connection, fecha: str, objetivo_100: float | None = None,
                   bloques: list[dict] | None = None) -> dict:
    """De que esta hecho un dia: metros por clase de estimulo y bloque continuo mas largo."""
    return estimulos.perfil(series_del_dia(cn, fecha, bloques), objetivo_100)


def ventana(cn: sqlite3.Connection, desde: str, hasta: str, objetivo_100: float | None = None,
            bloques: list[dict] | None = None) -> dict:
    """El perfil de la ventana, con todo lo que hace falta para juzgarlo (no solo el resultado).

    Devuelve lo mismo que `estimulos.perfil_de_ventana` (`por_clase`, `dominante`, `continuo_mas_largo`,
    `calidad_m`, `total_m`) y ademas: `por_fecha` (las series dia a dia), `fechas`, `dias_con_dato`,
    `dias_parte`, `dias_reloj`, `origen` y `avisos` (los dias en los que el dato viene cojo, dicho en claro).
    """
    bloques = analitica.bloques(cn, MIN_SERIE_M) if bloques is None else bloques
    vistas = {f: vistas_del_dia(cn, f, bloques) for f in _fechas(cn, desde, hasta, bloques)}
    por_fecha = {f: (v["parte"] if v["manda"] == "parte" else v["reloj"] if v["manda"] == "reloj" else [])
                 for f, v in vistas.items()}
    perfil = estimulos.perfil_de_ventana(por_fecha, desde, hasta, objetivo_100)

    dias_parte = sum(1 for v in vistas.values() if v["manda"] == "parte")
    dias_reloj = sum(1 for v in vistas.values() if v["manda"] == "reloj")
    avisos = [v["aviso"] for v in vistas.values() if v["aviso"] and v["parte"]]
    sin_parte = [f for f, v in vistas.items() if not v["parte"]]
    if sin_parte:
        avisos.append(f"{len(sin_parte)} de los {len(vistas)} dias de la ventana no tienen parte: los metros "
                      f"salen del reloj, sin estructura de serie")
    if dias_parte and dias_reloj:
        origen = "mixto"
    elif dias_parte:
        origen = "parte"
    elif dias_reloj:
        origen = "reloj"
    else:
        origen = "sin datos"

    fuera = dict(perfil)
    fuera.update({"por_fecha": por_fecha, "fechas": sorted(por_fecha), "dias_con_dato": len(por_fecha),
                  "dias_parte": dias_parte, "dias_reloj": dias_reloj, "origen": origen, "avisos": avisos,
                  "desde": desde, "hasta": hasta})
    return fuera
