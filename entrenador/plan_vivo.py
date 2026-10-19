#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""El plan recalculado con lo que ha entrado: no como se escribio, sino con lo que ha pasado.

El plan escrito (`plan.py`) es la referencia y no se toca. Esto coge las reglas de carga que ya estan escritas
en ese plan (las aplica `evaluacion`) y las encadena semana a semana con lo que el atleta ha hecho de verdad:
la semana que viene deja de decir lo mismo cuando la anterior no se cumplio, se cumplio de sobra o salio con
deriva. Los dias del entrenador (lunes, miercoles y viernes) no entran en ninguna de estas cuentas.

Las semanas que todavia no han pasado no se inventan: se quedan con lo que escribio el plan, con el tope del
10 % medido sobre el km que deja la semana anterior **recalculada**. Asi, si una semana repite o baja, la
siguiente ya no sube sobre el plan viejo: sube sobre lo que de verdad se va a nadar.

Se calcula **al vuelo** cada vez que se rehace el cuadro de mando, o sea con cada entrenamiento que entra: lo
dispara `analizar` (que corre al importar) y el propio servidor cuando se sube un parte. No se guarda en
ninguna tabla a proposito: un plan guardado se queda viejo y el atleta lee numeros que ya no valen.

Uso:
    .venv/Scripts/python.exe -m entrenador.cli plan --recalculado
"""

from __future__ import annotations

from datetime import date

from . import evaluacion, plan

# Los numeros de las reglas del plan (`plan.REGLAS`), con nombre para no repartirlos por el codigo.
TOPE_SUBIDA_PCT = 10.0      # "el volumen semanal sube como maximo un 10 %"
UMBRAL_CUMPLIR = 0.7        # "si una semana no se completa (menos del 70 % de las sesiones), la siguiente repite"
BAJADA_DERIVA = 0.8         # "deriva ... la semana siguiente baja un 20 % de volumen"
TOPE_DESCARGA = 0.8         # una bajada escrita de mas del 20 % es una descarga: no se recalcula

# Las reglas que aplica este modulo, tal y como estan escritas en el plan (hay prueba de que siguen ahi).
REGLAS_DE_CARGA = (
    "El volumen semanal sube como maximo un 10 % y cada cuarta semana baja un 25-30 %.",
    "Si una semana no se completa (menos del 70 % de las sesiones), la siguiente repite, no sube.",
    "Deriva: si en dos sesiones clave seguidas la ultima repeticion es mas de 5 s/100 mas lenta que la primera, "
    "la semana siguiente baja un 20 % de volumen.",
)


def _km(valor) -> str:
    """Los km como los lee el atleta (15,2): con coma."""
    if valor is None:
        return "-"
    return ("%.1f" % float(valor)).replace(".", ",")


def _bajada_escrita(km_antes, siguiente: dict) -> bool:
    """Si el plan ya baja la semana que viene a proposito (la descarga de cada cuatro semanas, o el taper)."""
    return bool(km_antes) and (siguiente.get("km") or 0) < km_antes * TOPE_DESCARGA


def _tope_de_subida(km_antes):
    """El km mas alto que permite la regla del 10 % sobre lo que deja la semana anterior."""
    return None if not km_antes else round(km_antes * (1 + TOPE_SUBIDA_PCT / 100.0), 1)


def _provisional(anterior: dict) -> list[str]:
    """El aviso de que la semana que manda esto todavia no ha terminado."""
    if not anterior.get("en_curso"):
        return []
    faltan = (anterior.get("sesiones_plan") or 0) - (anterior.get("sesiones_evaluables") or 0)
    cola = f" y le quedan {faltan} de nuestras" if faltan else ""
    return [f"ojo: la semana {anterior['clave']} todavia esta en curso (hasta el {anterior['hasta']}){cola}, "
            f"asi que esto es provisional y se rehace en cuanto entre lo que falte"]


def km_de_semana(anterior: dict | None, siguiente: dict | None) -> dict | None:
    """El km de la semana que viene recalculado con lo que paso en la anterior. None si no hay nada que calcular.

    `anterior` es una semana evaluada (lo que devuelve `evaluacion.evaluar_semana`, con el `km_plan` que de
    verdad acaba teniendo) y `siguiente` la semana del plan escrito. No toca la base ni escribe nada:
    devuelve `{accion, km, km_escrito, motivos}`.
    """
    if siguiente is None:
        return None
    escrito = siguiente.get("km")
    if anterior is None:
        return {"accion": "sin_anterior", "km": escrito, "km_escrito": escrito,
                "motivos": ["es la primera semana del plan: no hay una semana antes que la mande, asi que se "
                            "queda como esta escrita"]}
    a = evaluacion.ajuste_propuesto(anterior, siguiente)
    km = a["km_propuestos"] if a.get("km_propuestos") is not None else escrito
    salida = {"accion": a["accion"], "km": km, "km_escrito": escrito, "motivos": list(a["motivos"])}
    if a["accion"] not in ("bajar", "repetir") and _bajada_escrita(anterior.get("km_plan"), siguiente):
        salida.update(accion="descarga", km=escrito, motivos=[
            "la semana %s es una bajada escrita en el plan (de %s a %s km): es a proposito, no se recalcula"
            % (siguiente.get("clave"), _km(anterior.get("km_plan")), _km(escrito))] + salida["motivos"])
    if salida["accion"] in ("repetir", "bajar", "seguir", "subir_menos"):
        salida["motivos"] = list(a["motivos"])     # el aviso de "provisional" ya lo pone `evaluacion`
    return salida


def km_sin_datos(km_antes, siguiente: dict) -> dict:
    """El km de una semana cuya semana anterior no se puede juzgar (todavia no ha pasado, o no hay partes).

    Manda el plan escrito, con el tope del 10 % medido sobre lo que deja la anterior recalculada. Si el escrito
    ya baja a proposito (descarga o taper), se queda tal cual.
    """
    escrito = siguiente.get("km")
    if _bajada_escrita(km_antes, siguiente):
        return {"accion": "descarga", "km": escrito, "km_escrito": escrito,
                "motivos": ["es una bajada escrita en el plan (de %s a %s km): es a proposito, no se recalcula"
                            % (_km(km_antes), _km(escrito))]}
    if not km_antes:
        return {"accion": "sin_anterior", "km": escrito, "km_escrito": escrito,
                "motivos": ["es la primera semana del plan: se queda como esta escrita"]}
    tope = _tope_de_subida(km_antes)
    if (escrito or 0) > tope:
        return {"accion": "subir_menos", "km": tope, "km_escrito": escrito,
                "motivos": ["la semana que decide esto todavia no ha pasado, asi que se queda en lo que permite "
                            "la regla (+%d %% como maximo): %s km sobre los %s de la semana anterior"
                            % (int(TOPE_SUBIDA_PCT), _km(tope), _km(km_antes))]}
    return {"accion": "sin_juzgar", "km": escrito, "km_escrito": escrito,
            "motivos": ["la semana que decide esto todavia no ha pasado (o no tiene partes): de momento se queda "
                        "como esta escrita, y se recalcula cuando entre"]}


def recalcular(cn, hoy: date | str | None = None) -> list[dict]:
    """Las semanas del plan que quedan (la de ahora y las siguientes), con su km recalculado y su motivo."""
    d = plan._fecha(hoy) if isinstance(hoy, str) else (hoy or date.today())        # noqa: SLF001
    primera = next((i for i, s in enumerate(plan.SEMANAS)
                    if plan._fecha(s["hasta"]) >= d), None)                         # noqa: SLF001
    if primera is None:
        return []                     # el plan ya se acabo (el 400 y despues): no hay semanas que rehacer
    # El punto de partida es el km con el que acaba la ultima semana que ya paso (lo que se vivio, no lo que se
    # recalculo: esa semana ya esta hecha).
    km_antes = plan.SEMANAS[primera - 1]["km"] if primera else None
    salida = []
    for s in plan.SEMANAS[primera:]:
        j = plan.SEMANAS.index(s)
        anterior = evaluacion.evaluar_semana(cn, plan.SEMANAS[j - 1]["clave"], d) if j else None
        if anterior is not None and anterior.get("cumplimiento") is not None:
            if km_antes is not None:
                anterior = dict(anterior, km_plan=km_antes)      # el tope del 10 % va sobre lo que deja la anterior
            v = km_de_semana(anterior, s)
        else:
            v = km_sin_datos(km_antes, s)
            if anterior is not None and plan._fecha(anterior["desde"]) <= d:      # noqa: SLF001
                v["motivos"] = v["motivos"] + [
                    "de la semana %s no hay ningun parte: sin parte no se sabe el material ni la intensidad, asi "
                    "que no se juzga si se cumple" % anterior["clave"]]
        salida.append(dict(v, clave=s["clave"], desde=s["desde"], hasta=s["hasta"], foco=s["foco"],
                           en_curso=plan._fecha(s["desde"]) <= d <= plan._fecha(s["hasta"])))   # noqa: SLF001
        km_antes = v["km"]
    return salida


def datos(cn, hoy: date | str | None = None) -> dict:
    """El plan recalculado, para incrustarlo en el cuadro de mando (se rehace con cada entrenamiento)."""
    d = plan._fecha(hoy) if isinstance(hoy, str) else (hoy or date.today())        # noqa: SLF001
    return {"hoy": d.isoformat(), "semanas": recalcular(cn, d), "reglas": list(REGLAS_DE_CARGA),
            "tope_subida_pct": TOPE_SUBIDA_PCT, "umbral_cumplir": UMBRAL_CUMPLIR}


def texto(cn, hoy: date | str | None = None) -> str:
    """El plan recalculado en texto: cada semana que queda, su km y por que."""
    d = plan._fecha(hoy) if isinstance(hoy, str) else (hoy or date.today())        # noqa: SLF001
    lineas = ["Plan recalculado el %s (se rehace con cada entrenamiento que entra):" % d.isoformat(), ""]
    for s in recalcular(cn, d):
        marca = " <- esta semana" if s["en_curso"] else ""
        lineas.append("%s (%s a %s)  %s km (escrito: %s)  [%s]%s"
                      % (s["clave"], s["desde"], s["hasta"], _km(s["km"]), _km(s["km_escrito"]),
                         s["accion"], marca))
        for m in s["motivos"]:
            lineas.append("     - " + m)
    lineas += ["", "Reglas de carga que se aplican:"] + ["  - " + r for r in REGLAS_DE_CARGA]
    return "\n".join(lineas)
