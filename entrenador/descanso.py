"""Como se ha dormido y como se ha notado el dia (V1.2-04, V1.2-05 y V1.2-07).

El sueno entra por **dos puertas**: la del atleta y la del reloj. Manda la del atleta: si ha apuntado como ha dormido
(`apunte`, `tipo = 'sueno'`: los minutos en `minutos` y como se ha levantado (0-100) en `sensacion`), eso es la
verdad. Cuando no apunta nada, se usa **lo que midio el reloj** (tabla `sueno`, que llena
`scripts/garmin_conectar.py sueno` desde Garmin Connect: horas dormidas, tiempo despierto y la puntuacion 0-100 del
reloj). El dia dice de donde sale cada cosa (`sueno_fuente`), porque un dato del aparato y una palabra tuya no son
lo mismo.

La sensacion de la piscina la trae el parte (`parte.sensacion`, la que marcas tu) y, si ese dia no hay parte, el
reloj (`natacion_sesion.sensacion`, la de Garmin 0/25/50/75/100).

Lo que sostiene esto **no esta en el anexo T**: es **criterio del entrenador**, igual que los de T.8, y asi hay que
decirlo mientras no haya una cita que lo respalde. No se convierte en regla con fuente por escribirlo aqui.

La regla es una sola: **un dia lastrado no es una senal de entrenamiento**. No se borra ningun dato (el ritmo sigue
siendo el que es y se mide igual), pero cuando el plan va a cambiar de semana por un bajon, el descanso y la
sensacion tienen que estar delante: bajar un 20 % de kilometros por una noche de cuatro horas es un error de
lectura, no una decision de entrenamiento.
"""
from __future__ import annotations

import sqlite3

from . import sueno as sueno_del_reloj

# Cuando un dia viene "lastrado". Los umbrales son criterio del entrenador (no hay fuente): a partir de aqui el
# bajon tiene explicacion fuera del agua y el plan no debe leerlo como falta de entrenamiento. La sensacion va en la
# escala de la casa, 0-100, la misma del parte y la del reloj (que solo usa 0/25/50/75/100); la puntuacion del sueno
# tambien es 0-100, la que da Garmin.
SUENO_CORTO_H = 6.5            # horas dormidas: por debajo de seis y media, noche corta
SUENO_REGULAR = 70             # la puntuacion del reloj, 0-100: por debajo de 70, noche regular (hoy: 66)
SUENO_CORTO_COMO = 40          # como te has levantado, 0-100: 40 o menos es noche mala
SENSACION_BAJA = 40            # tu sensacion en la piscina, 0-100: 40 o menos, el dia no ha salido
FEEL_BAJO = 25                 # la del reloj, 0/25/50/75/100: 25 y menos = mal


def _mil(numero: float | None) -> str:
    """El numero con coma decimal, como se lee en castellano (5,5)."""
    if numero is None:
        return "-"
    return f"{numero:.1f}".replace(".", ",")


def _apunte_de(cn: sqlite3.Connection, fecha: str) -> dict | None:
    """El apunte de sueno de esa noche: minutos dormidos y como te has levantado."""
    fila = cn.execute(
        "SELECT minutos, sensacion, notas FROM apunte WHERE tipo = 'sueno' AND fecha = ? "
        "ORDER BY id DESC LIMIT 1", (fecha,)).fetchone()
    return dict(fila) if fila else None


def _sensacion_de(cn: sqlite3.Connection, fecha: str) -> tuple[float | None, int | None, str | None]:
    """La sensacion en el agua de ese dia: (0-100, la del reloj en crudo, de donde sale).

    Manda la tuya (el parte: es lo que has marcado tu); si ese dia no hay parte, se usa la del reloj, que es la
    misma idea medida por el aparato. Si no hay ninguna de las dos se devuelve (None, None, None): **no se sabe**,
    que no es lo mismo que un cero.
    """
    parte = cn.execute("SELECT sensacion FROM parte WHERE fecha = ? ORDER BY id DESC LIMIT 1", (fecha,)).fetchone()
    if parte and parte["sensacion"]:
        return float(parte["sensacion"]), None, "parte"
    reloj = cn.execute(
        "SELECT s.sensacion FROM natacion_sesion s JOIN actividad a ON a.id = s.actividad_id "
        "WHERE substr(a.inicio_local, 1, 10) = ? AND s.sensacion IS NOT NULL ORDER BY a.id DESC LIMIT 1",
        (fecha,)).fetchone()
    if reloj and reloj["sensacion"] is not None:
        return float(reloj["sensacion"]), int(reloj["sensacion"]), "reloj"
    return None, None, None


def de(cn: sqlite3.Connection, fecha: str) -> dict:
    """Lo que se sabe de esa noche y de ese dia. Lo que no hay viene `None`, **nunca un cero**.

    Devuelve las horas dormidas, como te has levantado, la sensacion en el agua (y de donde sale), si el dia viene
    lastrado y por que, en castellano llano, para poder decirlo tal cual.
    """
    ap = _apunte_de(cn, fecha) or {}
    reloj = sueno_del_reloj.de(cn, fecha) or {}
    # Manda tu palabra: si has apuntado cuantas horas has dormido, esas son las horas.
    horas = round(ap["minutos"] / 60.0, 1) if ap.get("minutos") else reloj.get("horas")
    como = int(ap["sensacion"]) if ap.get("sensacion") else None
    despierto_min = round(reloj["despierto_s"] / 60.0) if reloj.get("despierto_s") else None
    sensacion, feel, fuente = _sensacion_de(cn, fecha)
    dia = {"fecha": fecha, "sueno_h": horas, "sueno_como": como, "sueno_puntuacion": reloj.get("puntuacion"),
           "sueno_fuente": ("tu apunte" if ap.get("minutos") else ("el reloj" if reloj.get("horas") else None)),
           "despierto_min": despierto_min,
           "sensacion": sensacion, "feel_reloj": feel, "de_donde": fuente, "notas": ap.get("notas"),
           "se_sabe_algo": any(x is not None for x in (horas, como, reloj.get("puntuacion"), sensacion))}
    dia["motivos"] = motivos(dia)
    dia["lastrado"] = bool(dia["motivos"])
    dia["texto"] = texto(dia)
    return dia


def motivos(dia: dict) -> list[str]:
    """Por que el dia viene lastrado, en castellano llano. Lista vacia si el dia esta limpio o no se sabe nada."""
    fuera: list[str] = []
    horas = dia.get("sueno_h")
    if horas is not None and horas < SUENO_CORTO_H:
        fuera.append(f"dormiste {_mil(horas)} h (menos de {_mil(SUENO_CORTO_H)})")
    como = dia.get("sueno_como")
    if como is not None and como <= SUENO_CORTO_COMO:
        fuera.append(f"te has levantado {int(como)}/100")
    punt = dia.get("sueno_puntuacion")
    # La puntuacion del reloj solo opina cuando la noche es suya: si tu has apuntado como has dormido, manda tu
    # palabra y el aparato no te lleva la contraria (la fuente propone, tus datos disponen).
    if punt is not None and punt < SUENO_REGULAR and dia.get("sueno_fuente") == "el reloj":
        fuera.append(f"el reloj te da la noche {int(punt)}/100 (por debajo de {SUENO_REGULAR})")
    sens = dia.get("sensacion")
    if sens is not None and sens <= SENSACION_BAJA:
        fuera.append(f"te has notado {int(sens)}/100 en el agua")
    return fuera


def texto(dia: dict) -> str:
    """El dia en una linea, para el discurso: lo que se sabe y, si viene lastrado, por que."""
    if not dia or not dia.get("se_sabe_algo"):
        return "de esa noche no hay dato (ni apunte de sueno ni sensacion): no se puede juzgar el descanso"
    trozos: list[str] = []
    if dia.get("sueno_h") is not None:
        de = f" ({dia['sueno_fuente']})" if dia.get("sueno_fuente") else ""
        trozos.append(f"dormiste {_mil(dia['sueno_h'])} h{de}")
    if dia.get("sueno_puntuacion") is not None:
        trozos.append(f"el reloj te da {int(dia['sueno_puntuacion'])}/100 de sueno")
    if dia.get("sueno_como") is not None:
        trozos.append(f"te has levantado {int(dia['sueno_como'])}/100")
    if dia.get("sensacion") is not None:
        trozos.append(f"te has notado {int(dia['sensacion'])}/100 en el agua")
    dicho = " y ".join(trozos)
    if dia.get("lastrado"):
        return f"{dicho} (dia lastrado)"
    return f"{dicho} (dia limpio)"


def de_la_semana(cn: sqlite3.Connection, sesiones: list[dict]) -> list[dict]:
    """Colga el descanso de cada sesion de una semana evaluada (lo que lee `_ajuste_bruto`)."""
    for v in sesiones:
        v["descanso"] = de(cn, v["fecha"])
    return sesiones


def lastrados(sesiones: list[dict]) -> list[dict]:
    """Los dias de la semana que vienen lastrados (con el descanso ya colgado)."""
    return [v for v in sesiones if (v.get("descanso") or {}).get("lastrado")]
