#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lectura de ficheros GPX (traza con coordenadas, altitud y hora), sin tocar la base de datos.

Los GPX del export de Strava son la unica fuente de coordenadas: los FIT de actividad traen la sesion, los
laps y los largos, pero **no** la traza. Aqui se obtiene la traza y se empaqueta de forma compacta para
guardarla en la base de datos (una fila por actividad, con los puntos comprimidos).

Dos detalles del mundo real que este modulo trata a proposito:

- Los GPX viejos (S Health, Strava Android) a veces **no** estan en UTF-8 aunque lo declaren: se lee en bytes
  y se reintenta con latin-1 antes de darse por vencido.
- Muchos puntos seguidos estan en el mismo sitio (parado en un semaforo): se guardan solo los puntos que
  aportan algo (separados por metros o por segundos), que es lo que hace falta para medir un segmento.

Este modulo solo LEE el fichero que se le pasa; no escribe nada.
"""

from __future__ import annotations

import datetime as _dt
import gzip
import hashlib
import math
import os
import struct
import zlib
import xml.etree.ElementTree as ET

# `<type>` de GPX -> disciplina de la base de datos (solo como ultimo recurso: el CSV del export manda).
TIPOS = {
    "cycling": "ciclismo", "biking": "ciclismo", "cycling_road": "ciclismo",
    "running": "carrera", "running_road": "carrera", "walking": "caminata",
    "hiking": "senderismo", "swimming": "natacion", "multi_sport": None,
}

# Separacion minima entre dos puntos guardados (metros) y tiempo minimo (segundos).
MIN_METROS = 2.5
MIN_SEGUNDOS = 5.0

# Radio de la Tierra para la distancia entre dos puntos (metros).
RADIO_TIERRA = 6371008.8


def _bytes_utf8(ruta: str) -> bytes:
    """Devuelve el contenido del fichero como bytes UTF-8 validos (arregla codificaciones mal declaradas).

    Algunos GPX antiguos declaran UTF-8 y guardan latin-1 (o al reves). Se empaqueta el XML como bytes
    UTF-8 sea cual sea el caso, manteniendo la declaracion coherente para que el lector de XML no se queje.
    """
    if ruta.endswith(".gz"):
        with gzip.open(ruta, "rb") as fh:
            bruto = fh.read()
    else:
        with open(ruta, "rb") as fh:
            bruto = fh.read()
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError:
        texto = bruto.decode("latin-1")
    # La declaracion de codificacion del XML no tiene por que coincidir con lo que hay dentro.
    for declarada in ('encoding="UTF-8"', "encoding='UTF-8'", 'encoding="utf-8"', "encoding='utf-8'"):
        if declarada in texto[:200]:
            return texto.encode("utf-8")
    for mala in ('encoding="windows-1252"', "encoding='windows-1252'", 'encoding="ISO-8859-1"',
                 "encoding='ISO-8859-1'"):
        if mala in texto[:200]:
            texto = texto.replace(mala, 'encoding="UTF-8"')
            break
    return texto.encode("utf-8")


def distancia_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia entre dos puntos sobre la esfera (haversine), en metros."""
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df = f2 - f1
    dl = math.radians(lon2 - lon1)
    a = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    return 2 * RADIO_TIERRA * math.asin(math.sqrt(a))


def _local(etiqueta: str) -> str:
    """Nombre de la etiqueta XML sin el espacio de nombres (los GPX usan `xmlns`, que aqui estorba)."""
    return etiqueta.rsplit("}", 1)[-1]


def _hora(texto: str | None) -> float | None:
    """Hora ISO del GPX (`2026-08-13T09:40:30Z`) a segundos desde 1970."""
    if not texto:
        return None
    texto = texto.strip()
    if texto.endswith("Z"):
        texto = texto[:-1] + "+00:00"
    try:
        return _dt.datetime.fromisoformat(texto).timestamp()
    except ValueError:
        return None


def leer_gpx(ruta: str, disciplina: str | None = None, nombre: str | None = None) -> dict:
    """Lee un GPX (o .gpx.gz) y devuelve la actividad y la traza.

    Se lee el XML a mano (con la libreria estandar) en vez de con un lector estricto de GPX: los ficheros
    antiguos de S Health y de la aplicacion de Strava meten extensiones con formatos raros (un `number` con
    un identificador en vez de un numero) que tumban a los lectores estrictos. Aqui solo se necesita `trkpt`.

    Devuelve `{"actividad": {...}, "puntos": [(lat, lon, ele, t), ...]}` con `t` en segundos (epoch) o None
    si el fichero no trae horas.
    """
    bruto = _bytes_utf8(ruta)
    raiz = ET.fromstring(bruto)

    crudos: list[tuple[float, float, float | None, float | None]] = []
    tipo = None
    for elemento in raiz.iter():
        etiqueta = _local(elemento.tag)
        if etiqueta == "trkpt":
            try:
                lat, lon = float(elemento.get("lat")), float(elemento.get("lon"))
            except (TypeError, ValueError):
                continue
            ele, t = None, None
            for hijo in elemento:
                sub = _local(hijo.tag)
                if sub == "ele":
                    try:
                        ele = float((hijo.text or "").strip())
                    except ValueError:
                        ele = None
                elif sub == "time":
                    t = _hora(hijo.text)
            crudos.append((lat, lon, ele, t))
        elif etiqueta == "type" and tipo is None and elemento.text:
            tipo = TIPOS.get(elemento.text.strip().lower(), None)
    if not crudos:
        raise ValueError("el GPX no trae ningun punto de traza")

    puntos = _adelgazar(crudos)
    dist = 0.0
    for (lat1, lon1, _, _), (lat2, lon2, _, _) in zip(puntos, puntos[1:]):
        dist += distancia_m(lat1, lon1, lat2, lon2)

    con_hora = [p for p in puntos if p[3] is not None]
    inicio = con_hora[0][3] if con_hora else None
    duracion = (con_hora[-1][3] - con_hora[0][3]) if con_hora else None

    act = {
        "fichero": os.path.basename(ruta),
        "id_garmin": None,          # los GPX del export se llaman por el identificador de Strava, no de Garmin
        "hash": hashlib.sha256(bruto).hexdigest(),
        "disciplina": disciplina or tipo,
        "sub_disciplina": None,
        "nombre": nombre,
        "inicio_utc": (_dt.datetime.fromtimestamp(inicio, _dt.timezone.utc).isoformat()
                       if inicio else None),
        "inicio_local": (_dt.datetime.fromtimestamp(inicio).replace(tzinfo=None).isoformat(sep=" ")
                         if inicio else None),
        "duracion_s": duracion,
        "distancia_fit_m": round(dist, 1),
        "n_puntos": len(puntos),
    }
    return {"actividad": act, "puntos": puntos}


def _adelgazar(puntos: list[tuple], min_metros: float = MIN_METROS,
               min_segundos: float = MIN_SEGUNDOS) -> list[tuple]:
    """Quita los puntos que no aportan nada (parado, temblando el GPS) manteniendo el orden y las horas."""
    if not puntos:
        return []
    fuera = [puntos[0]]
    for p in puntos[1:]:
        ultimo = fuera[-1]
        if distancia_m(ultimo[0], ultimo[1], p[0], p[1]) >= min_metros:
            fuera.append(p)
            continue
        if p[3] is not None and ultimo[3] is not None and (p[3] - ultimo[3]) >= min_segundos:
            fuera.append(p)
    return fuera


# ---------------------------------------------------------------------------------------------
# Empaquetado compacto de la traza (para guardarla en una sola columna BLOB de la base de datos)
# ---------------------------------------------------------------------------------------------

def empaquetar(puntos: list[tuple]) -> bytes:
    """Comprime la traza: 16 bytes por punto (lat, lon, altitud y segundos desde el inicio)."""
    if not puntos:
        return b""
    t0 = min((p[3] for p in puntos if p[3] is not None), default=0.0)
    trozos = [struct.pack("<qI", int(t0), len(puntos))]
    for lat, lon, ele, t in puntos:
        dt = int(t - t0) if t is not None else 0
        trozos.append(struct.pack("<fffI", lat, lon, float(ele) if ele is not None else float("nan"),
                                  max(0, min(4_000_000_000, dt))))
    return zlib.compress(b"".join(trozos), 6)


def desempaquetar(blob: bytes) -> list[tuple]:
    """Deshace `empaquetar`: devuelve la lista de puntos (lat, lon, ele, t)."""
    if not blob:
        return []
    datos = zlib.decompress(blob)
    t0, n = struct.unpack_from("<qI", datos, 0)
    base = struct.calcsize("<qI")          # 12 bytes: la cabecera NO ocupa lo mismo que un punto
    puntos = []
    for i in range(n):
        lat, lon, ele, dt = struct.unpack_from("<fffI", datos, base + i * 16)
        puntos.append((lat, lon, None if math.isnan(ele) else ele, float(t0 + dt) if dt else None))
    return puntos
