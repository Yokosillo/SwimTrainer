#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lectura de ficheros FIT (reloj Garmin) y GPX, sin dependencias de la base de datos.

Devuelve diccionarios planos en unidades del sistema internacional (metros y segundos).
Mantener este modulo puro (sin efectos secundarios) permite probarlo por separado.
"""

from __future__ import annotations

import gzip
import hashlib
import os

import fitdecode

DISCIPLINAS = {
    "swimming": "natacion",
    "cycling": "ciclismo",
    "running": "carrera",
    "walking": "caminata",
    "hiking": "senderismo",
    "training": "gimnasio",
    "fitness_equipment": "gimnasio",
    "rowing": "remo",
    "stand_up_paddleboarding": "sup",
    "transition": "transicion",
}

SUB_DISCIPLINAS = {
    "lap_swimming": "piscina",
    "open_water": "aguas_abiertas",
    "indoor_cycling": "rodillo",
    "generic": None,
    "road": "carretera",
    "mountain": "montana",
    "trail": "trail",
    "treadmill": "cinta",
    "strength_training": "fuerza",
}

ESTILOS = {
    # fitdecode devuelve el nombre del enum, no el numero (comprobado en los ficheros del reloj).
    "freestyle": "libre", "backstroke": "espalda", "breaststroke": "braza",
    "butterfly": "mariposa", "drill": "drill", "mixed": "mixto",
    "im": "mixto", "individual_medley": "mixto", "no_event": None, "invalid": None,
    # por si alguna version devuelve el numero en lugar del nombre
    0: None, 1: "espalda", 2: "espalda", 3: "braza", 4: "mariposa", 5: "mariposa",
    6: "libre", 7: "drill", 8: "mixto",
}

DISPARADORES = {"manual": "manual", "time": "tiempo", "distance": "distancia",
                "heart_rate_less_than": "otro", "power_less_than": "otro",
                "location": "otro", "session_end": "otro", "activity_end": "otro",
                0: "manual", 1: "tiempo", 2: "distancia", 3: "otro"}

INTENSIDADES = {"active": "activo", "rest": "descanso", "warmup": "calentamiento",
                "cooldown": "enfriamiento", "recovery": "descanso", "interval": "activo",
                0: "activo", 1: "descanso", 2: "calentamiento", 3: "enfriamiento"}


def hash_fichero(ruta: str) -> str:
    """Huella del fichero: sirve para detectar duplicados sin depender del nombre."""
    h = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for bloque in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def abrir(ruta: str):
    """Abre el fichero, sea .fit o .fit.gz."""
    if ruta.endswith(".gz"):
        return gzip.open(ruta, "rb")
    return open(ruta, "rb")


def _valor(fr, nombre, por_defecto=None):
    """Lee un campo del mensaje devolviendo el valor por defecto si no existe.

    fitdecode lanza KeyError cuando el campo no esta presente en el mensaje, que es
    justo lo que ocurre con los campos opcionales (sensacion, RPE, caloria...).
    """
    try:
        v = fr.get_value(nombre)
    except Exception:
        return por_defecto
    return por_defecto if v is None else v


def leer_fit(ruta: str, con_traza: bool = False) -> dict:
    """Lee un FIT y devuelve {actividad, sesion, laps, largos, puntos}.

    `actividad` siempre existe si el fichero es legible; `sesion`, `laps`, `largos` y `puntos`
    pueden estar vacios en ficheros raros o truncados. `puntos` (la traza GPS) solo se rellena si se
    pide con `con_traza=True`, porque no hace falta para la natacion y encarece la lectura.
    """
    act = {
        "fichero": os.path.basename(ruta),
        "id_garmin": os.path.basename(ruta).split(".")[0],
        "hash": hash_fichero(ruta),
    }
    sesion, laps, largos, puntos = None, [], [], []
    with abrir(ruta) as fh:
        with fitdecode.FitReader(fh) as fit:
            for fr in fit:
                if fr.frame_type != fitdecode.FIT_FRAME_DATA:
                    continue
                if fr.name == "record" and con_traza:
                    punto = _punto_record(fr)
                    if punto:
                        puntos.append(punto)
                elif fr.name == "session" and sesion is None:
                    sport = str(_valor(fr, "sport", ""))
                    sub = str(_valor(fr, "sub_sport", ""))
                    act["disciplina"] = DISCIPLINAS.get(sport, sport or None)
                    act["sub_disciplina"] = SUB_DISCIPLINAS.get(sub, sub or None)
                    inicio = _valor(fr, "start_time")
                    act["inicio_utc"] = inicio.isoformat() if inicio else None
                    act["inicio_local"] = (
                        inicio.astimezone().replace(tzinfo=None).isoformat(sep=" ") if inicio else None
                    )
                    act["duracion_s"] = _valor(fr, "total_timer_time") or _valor(fr, "total_elapsed_time")
                    act["distancia_fit_m"] = _valor(fr, "total_distance")
                    largos_piscina = _valor(fr, "pool_length")
                    sesion = {
                        "largo_piscina_m": largos_piscina,
                        "n_largos": _valor(fr, "num_lengths"),
                        "n_largos_activos": _valor(fr, "num_active_lengths"),
                        "brazadas": _valor(fr, "total_strokes"),
                        "fc_media": _valor(fr, "avg_heart_rate"),
                        "fc_max": _valor(fr, "max_heart_rate"),
                        "calorias": _valor(fr, "total_calories"),
                        "sensacion": _valor(fr, "workout_feel"),
                        "rpe": _valor(fr, "workout_rpe"),
                        "carga_aerobica": _valor(fr, "total_training_effect"),
                    }
                elif fr.name == "lap":
                    laps.append(
                        {
                            "lap_idx": len(laps),
                            "inicio": (_valor(fr, "start_time").isoformat()
                                       if _valor(fr, "start_time") else None),
                            "dist_m": _valor(fr, "total_distance"),
                            "timer_s": _valor(fr, "total_timer_time"),
                            "elapsed_s": _valor(fr, "total_elapsed_time"),
                            "n_largos": _valor(fr, "num_lengths"),
                            "n_largos_activos": _valor(fr, "num_active_lengths"),
                            "primer_largo_idx": _valor(fr, "first_length_index"),
                            "estilo": None,   # el lap no trae estilo: se deduce de sus largos
                            "fc_media": _valor(fr, "avg_heart_rate"),
                            "fc_max": _valor(fr, "max_heart_rate"),
                            "brazadas": _valor(fr, "total_strokes"),
                            "disparador": DISPARADORES.get(_valor(fr, "lap_trigger")),
                            "intensidad": INTENSIDADES.get(_valor(fr, "intensity")),
                        }
                    )
                elif fr.name == "length":
                    vel = _valor(fr, "avg_speed")
                    largos.append(
                        {
                            "len_idx": len(largos),
                            "inicio": (_valor(fr, "start_time").isoformat()
                                       if _valor(fr, "start_time") else None),
                            "tipo": _valor(fr, "length_type", "active"),
                            "estilo": ESTILOS.get(_valor(fr, "swim_stroke")),
                            "timer_s": _valor(fr, "total_timer_time"),
                            "elapsed_s": _valor(fr, "total_elapsed_time"),
                            "brazadas": _valor(fr, "total_strokes"),
                            "cadencia": _valor(fr, "avg_swimming_cadence"),
                            "vel_m_s": round(vel, 4) if vel else None,
                        }
                    )
    _estilo_por_lap(laps, largos)
    return {"actividad": act, "sesion": sesion, "laps": laps, "largos": largos, "puntos": puntos}


def _punto_record(fr) -> tuple | None:
    """Un punto de traza a partir de un mensaje `record` del FIT.

    Las coordenadas vienen en semicirculos (grados = valor x 180 / 2^31), que es el formato del estandar
    FIT; devolverlas en grados es lo que hace falta para medir distancias y compararlas con un GPX.
    """
    lat = _valor(fr, "position_lat")
    lon = _valor(fr, "position_long")
    if lat is None or lon is None:
        return None
    ele = _valor(fr, "enhanced_altitude")
    if ele is None:
        ele = _valor(fr, "altitude")
    t = _valor(fr, "timestamp")
    return (float(lat) * (180.0 / 2 ** 31), float(lon) * (180.0 / 2 ** 31),
            float(ele) if ele is not None else None, t.timestamp() if t is not None else None)


def _estilo_por_lap(laps: list[dict], largos: list[dict]) -> None:
    """Deduce el estilo de cada lap a partir de sus largos.

    El reloj **no** guarda el estilo en el lap (comprobado en los ficheros): solo en el largo.
    Se asigna el estilo mayoritario de los largos que caen dentro del lap, que es la unica
    forma de tener el dato sin inventarlo. Si el lap no tiene largos asociados, queda vacio.
    """
    for lap in laps:
        primero = lap.get("primer_largo_idx")
        n = lap.get("n_largos")
        if primero is None or not n:
            continue
        trozo = largos[primero:primero + int(n)]
        estilos = [l.get("estilo") for l in trozo if l.get("estilo")]
        if estilos:
            lap["estilo"] = max(set(estilos), key=estilos.count)


def distancia_natacion(act: dict, sesion: dict | None, laps: list[dict], largos: list[dict]) -> float | None:
    """Distancia en metros, con criterio explicito por tipo de natacion.

    - **Piscina**: se calcula con `largos activos x largo de piscina`, que es la unica forma
      que no depende de la configuracion del reloj. Si no hay largos, se usa la suma de laps.
    - **Aguas abiertas**: no hay largos; se usa el campo del reloj (en metros).
    """
    activos = [l for l in largos if l.get("tipo") == "active"]
    largo = (sesion or {}).get("largo_piscina_m")
    if activos and largo:
        return len(activos) * float(largo)
    distancia = sum((l.get("dist_m") or 0) for l in laps)
    if distancia:
        return distancia
    return act.get("distancia_fit_m")
