#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""El plan de las proximas semanas, como datos (lo leen la consola y el cuadro de mando).

Los datos personales del atleta (objetivos, semanas, bloques, reglas y decisiones) viven en
`entrenador/plan_local.py`, que es privado y esta en `.gitignore`. Este modulo solo los carga y
ofrece la API publica. Sin `plan_local.py` el plan queda vacio y la aplicacion sigue arrancando:
las funciones devuelven vacio/None y el panel no muestra plan.

Uso:
    .venv/Scripts/python.exe -m entrenador.cli plan              # la semana en curso
    .venv/Scripts/python.exe -m entrenador.cli plan --semana S2  # una semana concreta
"""

from __future__ import annotations

from datetime import date, datetime

# Fallback generico: sin datos personales. Si existe `plan_local.py` (privado), sus valores mandan.
KILOMETROS_SEMANA: dict[str, float] = {}
OBJETIVO_B: dict = {}
OBJETIVO_A: dict = {}
OBJETIVOS: tuple[dict, ...] = ()
ENTRENADOR: str = ""
SEMANAS: list[dict] = []
BLOQUES: list[dict] = []
FASES: tuple[str, ...] = ()
FASE_POR_DEFECTO: str = "especifico_400"
PISCINA: str = ""
REGLAS: list[str] = []
DECISIONES: list[str] = []

try:  # pragma: no cover - depende de la maquina, no del codigo
    from .plan_local import (  # noqa: F401
        BLOQUES, DECISIONES, ENTRENADOR, FASES, FASE_POR_DEFECTO, KILOMETROS_SEMANA,
        OBJETIVO_A, OBJETIVO_B, OBJETIVOS, PISCINA, REGLAS, SEMANAS,
    )
except ImportError:  # sin fichero privado: plan vacio, la app arranca igual
    pass


def objetivo_de(estilo: str | None = None, distancia: int | None = None,
                piscina: int | None = None) -> dict | None:
    """El objetivo del plan que corresponde a una prueba, o None si no hay ninguno.

    Se usa para no repetir la marca objetivo en dos sitios: la pone el plan y la leen el comparador de
    marcas y la evaluacion de preparacion. Sin plan configurado devuelve None.
    """
    for o in OBJETIVOS:
        p = o["prueba"]
        if estilo and p["estilo"] != (estilo or "").strip().lower():
            continue
        if distancia and p["distancia_m"] != int(distancia):
            continue
        if piscina and p["piscina_m"] != int(piscina):
            continue
        return o
    return None


def _fecha(texto: str) -> date:
    return datetime.strptime(texto, "%Y-%m-%d").date()


def semana_de(cuando: date | str | None = None) -> dict | None:
    """La semana del plan que contiene esa fecha (o la primera si es anterior al plan)."""
    d = _fecha(cuando) if isinstance(cuando, str) else (cuando or date.today())
    if not SEMANAS:
        return None
    for s in SEMANAS:
        if _fecha(s["desde"]) <= d <= _fecha(s["hasta"]):
            return s
    return SEMANAS[0] if d < _fecha(SEMANAS[0]["desde"]) else None


def fase_de(cuando: date | str | None = None) -> str:
    """La fase del plan que toca en una fecha (V1.2-01), para que el motor sepa que reparto exigir.

    Hasta la prueba del 400 manda `especifico_400`; despues, la fase del bloque en el que cae (`base` en
    el bloque de base, `umbral_3000` camino del 3.000). Sin plan configurado devuelve `FASE_POR_DEFECTO`.
    """
    d = _fecha(cuando) if isinstance(cuando, str) else (cuando or date.today())
    if SEMANAS and d <= _fecha(SEMANAS[-1]["hasta"]):
        return "especifico_400"
    for b in BLOQUES:
        if _fecha(b["desde"]) <= d <= _fecha(b["hasta"]):
            return b.get("fase") or FASE_POR_DEFECTO
    if BLOQUES:
        return BLOQUES[-1].get("fase") or FASE_POR_DEFECTO  # despues de la prueba: sigue la ultima fase
    return FASE_POR_DEFECTO


# Los nombres de los dias, de lunes (0) a domingo (6), como los usa el resto del proyecto.
DIAS_SEMANA = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


def pruebas_de(cuando: date | str | None = None) -> tuple[str, ...]:
    """Los dias de la semana de `cuando` que son prueba o test, por nombre de dia ("domingo").

    Sale del plan escrito, que es el que manda las pruebas: las sesiones del calendario marcadas `tipo` "test" o
    "prueba". Es lo que necesita el motor para no prescribir nada el dia de la prueba y no poner trabajo de calidad
    delante de ella (V1.2-02). Las pruebas de los bloques (el 3.000 de marzo) no traen dia de la semana en el plan:
    esas no salen aqui.
    """
    d = _fecha(cuando) if isinstance(cuando, str) else (cuando or date.today())
    s = semana_de(d)
    if not s:
        return ()
    fuera: list[str] = []
    for sesion in s.get("sesiones") or []:
        if sesion.get("tipo") not in ("test", "prueba") or not sesion.get("fecha"):
            continue
        f = _fecha(sesion["fecha"])
        if _fecha(s["desde"]) <= f <= _fecha(s["hasta"]):
            fuera.append(DIAS_SEMANA[f.weekday()])
    return tuple(dict.fromkeys(fuera))      # sin repetir, y en el orden en que salen en el plan


def siguiente(cuando: date | str | None = None) -> dict | None:
    """La proxima sesion del plan desde esa fecha (incluida). Si el plan ya se acabo, None."""
    d = _fecha(cuando) if isinstance(cuando, str) else (cuando or date.today())
    for s in SEMANAS:
        for sesion in s["sesiones"]:
            if _fecha(sesion["fecha"]) >= d:
                return dict(sesion, semana=s["clave"])
    return None


def texto(cuando: date | str | None = None, clave: str | None = None) -> str:
    """El plan en texto: la semana pedida (o la que contiene esa fecha) y la sesion siguiente."""
    d = _fecha(cuando) if isinstance(cuando, str) else (cuando or date.today())
    if not OBJETIVOS:
        return "No hay plan configurado (falta entrenador/plan_local.py)."
    anios, meses = divmod((_fecha(OBJETIVO_A["fecha"]) - d).days, 365)
    lineas = [
        "OBJETIVO B: %s el %s -> %s (rango %s)" % (OBJETIVO_B["nombre"], OBJETIVO_B["fecha"],
                                                   OBJETIVO_B["que"], OBJETIVO_B["rango"]),
        "OBJETIVO A: %s el %s -> %s (rango %s)" % (OBJETIVO_A["nombre"], OBJETIVO_A["fecha"],
                                                   OBJETIVO_A["que"], OBJETIVO_A["rango"]),
        "Hoy: %s | quedan %d dias para el 400 y %d para el 3.000"
        % (d.isoformat(), (_fecha(OBJETIVO_B["fecha"]) - d).days, (_fecha(OBJETIVO_A["fecha"]) - d).days),
        "",
        ENTRENADOR,
        "",
    ]
    s = None
    if clave:
        s = next((x for x in SEMANAS if x["clave"] == clave.upper()), None)
        if s is None:
            lineas.append("No hay ninguna semana con la clave %s (hay: %s)."
                          % (clave, ", ".join(x["clave"] for x in SEMANAS)))
    else:
        s = semana_de(d)
    if s:
        lineas += ["%s (%s a %s) - %.1f km - %s" % (s["clave"], s["desde"], s["hasta"], s["km"], s["foco"]), ""]
        lineas.append("  %-8s %-9s %s" % ("dia", "quien", "sesion"))
        for x in s["sesiones"]:
            lineas.append("  %-8s %-9s %s" % (x["dia"], x["quien"], x["titulo"]))
            lineas.append("  %-8s %-9s   %s" % ("", "", x["detalle"]))
    prox = siguiente(d)
    if prox:
        lineas += ["", "Siguiente sesion: %s (%s, %s) - %s" % (prox["dia"], prox["fecha"], prox["semana"], prox["titulo"])]
    lineas += ["", "Despues de la prueba (hasta el 3.000):"]
    for b in BLOQUES:
        lineas.append("  %-34s %s a %s  %s km  [%s]  %s"
                      % (b["nombre"], b["desde"], b["hasta"], b["km"], b.get("fase") or FASE_POR_DEFECTO, b["que"]))
    lineas += ["", "Reglas:"] + ["  - " + r for r in REGLAS]
    lineas += ["", "Falta por decidir:"] + ["  - " + x for x in DECISIONES]
    return "\n".join(lineas)


def bloques_de(sesion: dict) -> list[dict]:
    """Los bloques en numeros de una sesion (lista vacia en las sesiones del entrenador y en los descansos)."""
    return [dict(b) for b in (sesion.get("bloques") or [])]


def metros_de_sesion(sesion: dict) -> float:
    """Los metros que suma una sesion segun sus bloques (0 si no los tiene: del entrenador o descanso)."""
    return round(sum((b.get("reps") or 1) * (b.get("dist_m") or 0) for b in bloques_de(sesion)), 1)


def sesion_de(cuando: date | str) -> dict | None:
    """La sesion del plan de esa fecha exacta (con la clave de su semana), o None."""
    d = _fecha(cuando) if isinstance(cuando, str) else cuando
    for s in SEMANAS:
        for sesion in s["sesiones"]:
            if sesion["fecha"] == d.isoformat():
                return dict(sesion, semana=s["clave"], km_semana=s["km"])
    return None


def sesiones_para_evaluar(desde: date | str, hasta: date | str) -> list[dict]:
    """Las sesiones del plan entre dos fechas, en orden: es lo que se cruza con lo que se ha hecho."""
    d0 = _fecha(desde) if isinstance(desde, str) else desde
    d1 = _fecha(hasta) if isinstance(hasta, str) else hasta
    salida = []
    for s in SEMANAS:
        for sesion in s["sesiones"]:
            f = _fecha(sesion["fecha"])
            if d0 <= f <= d1:
                salida.append(dict(sesion, semana=s["clave"], km_semana=s["km"]))
    return sorted(salida, key=lambda x: x["fecha"])


def datos() -> dict:
    """El plan como diccionario, para incrustarlo en el cuadro de mando."""
    return {
        "objetivo_b": OBJETIVO_B,
        "objetivo_a": OBJETIVO_A,
        "entrenador": ENTRENADOR,
        "fase": fase_de(),
        "semanas": SEMANAS,
        "bloques": BLOQUES,
        "reglas": REGLAS,
        "decisiones": DECISIONES,
    }
