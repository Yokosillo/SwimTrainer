#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Importacion incremental de actividades.

Dos vias, ambas idempotentes (volver a importar lo mismo no duplica nada):

- `importar_carpeta(ruta)`: recorre una carpeta buscando `.fit`, `.fit.gz`, `.gpx` y `.gpx.gz`.
  Es la via del **reloj por cable USB** (copiar `GARMIN\\ACTIVITY` a una carpeta) y la del
  **export de Garmin Connect** (viene con FIT dentro).
- `importar_export_strava(ruta)`: lee `activities.csv` del export de Strava y enlaza el numero de
  actividad de Strava con el fichero FIT (que es el identificador de Garmin), de modo que una misma
  sesion importada por dos vias se reconozca y no se cuente dos veces.

Regla del proyecto: **solo se lee** de los datos de origen; se escribe unicamente en la base de datos.
"""

from __future__ import annotations

import csv
import os

from . import db, series
from .lector_fit import distancia_natacion, hash_fichero, leer_fit
from .lector_gpx import empaquetar, leer_gpx

EXTENSIONES = (".fit", ".fit.gz", ".gpx", ".gpx.gz")

# Disciplina segun el `Tipo de actividad` del CSV del export (el GPX no siempre lo dice).
DISCIPLINAS_CSV = {
    "bicicleta": "ciclismo", "bicicleta de montaña": "ciclismo", "bicicleta eléctrica": "ciclismo",
    "carrera": "carrera", "carrera a pie": "carrera", "natación": "natacion", "entrenamiento": "gimnasio",
    "senderismo": "senderismo", "caminata": "caminata", "esquí": "esqui", "remo": "remo",
}

# Disciplinas que se mueven por el mundo: su traza GPS merece guardarse (la piscina no tiene traza).
DISCIPLINAS_CON_GPS = ("ciclismo", "carrera", "senderismo", "caminata", "esqui", "remo", "sup")
CAMPOS_ACTIVIDAD = (
    "id_garmin", "id_strava", "fichero", "hash", "fuente", "disciplina", "sub_disciplina", "nombre",
    "inicio_utc", "inicio_local", "duracion_s", "distancia_m", "distancia_fit_m", "importado_en",
)


PLURAL_ESTADO = {"nuevo": "nuevos", "actualizado": "actualizados", "omitido": "omitidos"}


def _buscar_ficheros(ruta: str, recursivo: bool = True) -> list[str]:
    encontrados = []
    if os.path.isfile(ruta):
        return [ruta] if ruta.endswith(EXTENSIONES) else []
    for raiz, _, ficheros in os.walk(ruta):
        for nombre in ficheros:
            if nombre.endswith(EXTENSIONES):
                encontrados.append(os.path.join(raiz, nombre))
        if not recursivo:
            break
    return sorted(encontrados)


def _id_existente(cn, hash_: str, id_garmin: str | None):
    fila = cn.execute("SELECT id, id_garmin, id_strava FROM actividad WHERE hash = ?", (hash_,)).fetchone()
    if fila:
        return fila
    if id_garmin:
        return cn.execute(
            "SELECT id, id_garmin, id_strava FROM actividad WHERE id_garmin = ?", (id_garmin,)
        ).fetchone()
    return None


def _guardar_natacion(cn, actividad_id: int, datos: dict, etiqueta_material: str | None) -> int:
    """Inserta sesion, laps, largos, etiquetas y series. Devuelve el numero de series."""
    sesion = datos["sesion"] or {}
    laps = datos["laps"]
    largos = datos["largos"]
    cn.execute(
        """INSERT OR REPLACE INTO natacion_sesion
           (actividad_id, largo_piscina_m, n_largos, n_largos_activos, n_laps, brazadas,
            fc_media, fc_max, calorias, sensacion, rpe, carga_aerobica, swolf_medio)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
        (actividad_id, sesion.get("largo_piscina_m"), sesion.get("n_largos"),
         sesion.get("n_largos_activos"), len(laps), sesion.get("brazadas"),
         sesion.get("fc_media"), sesion.get("fc_max"), sesion.get("calorias"),
         sesion.get("sensacion"), sesion.get("rpe"), sesion.get("carga_aerobica")),
    )
    material = etiqueta_material or "sin_etiquetar"
    cn.execute("DELETE FROM natacion_lap WHERE actividad_id = ?", (actividad_id,))
    for lap in laps:
        cn.execute(
            """INSERT INTO natacion_lap
               (actividad_id, lap_idx, inicio, dist_m, timer_s, elapsed_s, n_largos, n_largos_activos,
                estilo, fc_media, fc_max, brazadas, disparador, intensidad, es_descanso, material)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (actividad_id, lap["lap_idx"], lap.get("inicio"), lap.get("dist_m"), lap.get("timer_s"),
             lap.get("elapsed_s"), lap.get("n_largos"), lap.get("n_largos_activos"), lap.get("estilo"),
             lap.get("fc_media"), lap.get("fc_max"), lap.get("brazadas"), lap.get("disparador"),
             lap.get("intensidad"), 1 if (lap.get("dist_m") or 0) <= 0 else 0,
             material if (lap.get("dist_m") or 0) > 0 else "sin_etiquetar"),
        )
    cn.execute("DELETE FROM natacion_largo WHERE actividad_id = ?", (actividad_id,))
    cn.executemany(
        """INSERT INTO natacion_largo
           (actividad_id, len_idx, inicio, tipo, estilo, timer_s, elapsed_s, brazadas, cadencia, vel_m_s)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        [(actividad_id, l["len_idx"], l.get("inicio"), l.get("tipo"), l.get("estilo"),
          l.get("timer_s"), l.get("elapsed_s"), l.get("brazadas"), l.get("cadencia"),
          l.get("vel_m_s")) for l in largos],
    )
    if etiqueta_material:
        cn.execute(
            """INSERT OR IGNORE INTO etiqueta (actividad_id, tipo, valor, origen, confianza)
               VALUES (?, 'material', ?, 'nombre_garmin', 'media')""",
            (actividad_id, etiqueta_material),
        )
    cn.execute("DELETE FROM serie WHERE actividad_id = ?", (actividad_id,))
    reconstruidas = series.reconstruir_series(
        [dict(l, material=material if (l.get("dist_m") or 0) > 0 else "sin_etiquetar") for l in laps]
    )
    for s in reconstruidas:
        cn.execute(
            """INSERT INTO serie
               (actividad_id, orden, rep_m, n_reps, n_reps_validas, volumen_m, ritmo_medio_100,
                mejor_100, peor_100, sd_100, descanso_medio_s, deriva_s, estilo, material, calidad,
                comparable)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (actividad_id, s["orden"], s["rep_m"], s["n_reps"], s["n_reps_validas"], s["volumen_m"],
             s["ritmo_medio_100"], s["mejor_100"], s["peor_100"], s["sd_100"], s["descanso_medio_s"],
             s["deriva_s"], s["estilo"], s["material"], s["calidad"], s["comparable"]),
        )
    return len(reconstruidas)


def recalcular_series_de(cn, actividad_id: int) -> int:
    """Rehace las series de UNA sesion a partir de sus laps (lo usa el parte, al marcar material).

    Es la version de una sola sesion de `recalcular_series`: cuando se etiqueta el material de una sesion no
    hace falta rehacer las 856 sesiones de natacion, solo la que ha cambiado.
    """
    laps = [dict(r) for r in cn.execute(
        """SELECT lap_idx, dist_m, timer_s, n_largos, estilo, material, es_descanso
           FROM natacion_lap WHERE actividad_id = ? ORDER BY lap_idx""", (actividad_id,))]
    cn.execute("DELETE FROM serie WHERE actividad_id = ?", (actividad_id,))
    total = 0
    for s in series.reconstruir_series(laps):
        cn.execute(
            """INSERT INTO serie (actividad_id, orden, rep_m, n_reps, n_reps_validas, volumen_m,
                                  ritmo_medio_100, mejor_100, peor_100, sd_100, descanso_medio_s,
                                  deriva_s, estilo, material, calidad, comparable)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (actividad_id, s["orden"], s["rep_m"], s["n_reps"], s["n_reps_validas"],
             s["volumen_m"], s["ritmo_medio_100"], s["mejor_100"], s["peor_100"], s["sd_100"],
             s["descanso_medio_s"], s["deriva_s"], s["estilo"], s["material"], s["calidad"],
             s["comparable"]),
        )
        total += 1
    return total


def recalcular_series(cn) -> int:
    """Rehace la tabla de series a partir de los laps que ya estan en la base de datos.

    Sirve para cambiar los criterios de agrupacion sin volver a leer los 1.000 ficheros del reloj
    (que tarda casi cuatro minutos): los laps no cambian, lo que cambia es como se agrupan.
    """
    total = 0
    filas = cn.execute("SELECT actividad_id FROM natacion_sesion ORDER BY actividad_id").fetchall()
    for fila in filas:
        total += recalcular_series_de(cn, fila["actividad_id"])
    cn.commit()
    return total


def _guardar_ruta(cn, actividad_id: int, puntos: list[tuple]) -> None:
    """Guarda la traza GPS comprimida (una fila por actividad)."""
    if not puntos:
        return
    lats = [p[0] for p in puntos]
    lons = [p[1] for p in puntos]
    eles = [p[2] for p in puntos if p[2] is not None]
    cn.execute(
        "INSERT OR REPLACE INTO ruta (actividad_id, n_puntos, lat_min, lat_max, lon_min, lon_max,"
        " ele_min, ele_max, con_hora, puntos) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (actividad_id, len(puntos), min(lats), max(lats), min(lons), max(lons),
         min(eles) if eles else None, max(eles) if eles else None,
         1 if any(p[3] is not None for p in puntos) else 0, empaquetar(puntos)),
    )


def importar_fichero(cn, ruta: str, fuente: str = "carpeta", id_strava: str | None = None,
                     nombre: str | None = None, disciplina: str | None = None) -> str:
    """Importa un fichero FIT o GPX. Devuelve 'nuevo', 'actualizado' u 'omitido'."""
    es_gpx = ruta.endswith((".gpx", ".gpx.gz"))
    datos = leer_gpx(ruta, disciplina=disciplina, nombre=nombre) if es_gpx else leer_fit(ruta)
    act = datos["actividad"]
    existente = _id_existente(cn, act["hash"], act.get("id_garmin"))
    # La natacion solo se detalla a partir de un FIT (sesion, laps y largos). Un GPX de natacion en aguas
    # abiertas se guarda como actividad y su traza, sin el detalle de largos.
    es_natacion = (not es_gpx and act.get("disciplina") == "natacion")
    if not es_gpx and act.get("disciplina") in DISCIPLINAS_CON_GPS:
        # Segunda lectura pidiendo la traza: solo interesa en deportes con coordenadas y encarece la lectura.
        datos = leer_fit(ruta, con_traza=True)
        act = datos["actividad"]
    if existente and existente["id_strava"] == id_strava and not es_natacion:
        # Ya estaba: si ahora traemos una traza GPS que antes no se guardo, se aprovecha el viaje.
        if datos.get("puntos") and not cn.execute("SELECT 1 FROM ruta WHERE actividad_id = ?",
                                                  (existente["id"],)).fetchone():
            _guardar_ruta(cn, existente["id"], datos["puntos"])
            cn.commit()
            return "actualizado"
        return "omitido"
    act.update(
        id_strava=id_strava,
        nombre=nombre or act.get("nombre"),
        fuente=fuente,
        distancia_m=distancia_natacion(act, datos["sesion"], datos["laps"], datos["largos"])
        if es_natacion else act.get("distancia_fit_m"),
        importado_en=db.ahora(),
    )
    columnas = ", ".join(CAMPOS_ACTIVIDAD)
    marcas = ", ".join("?" for _ in CAMPOS_ACTIVIDAD)
    valores = [act.get(c) for c in CAMPOS_ACTIVIDAD]
    if existente:
        cn.execute(
            f"UPDATE actividad SET {', '.join(f'{c}=?' for c in CAMPOS_ACTIVIDAD)} WHERE id = ?",
            valores + [existente["id"]],
        )
        actividad_id = existente["id"]
        estado = "actualizado"
    else:
        cur = cn.execute(f"INSERT INTO actividad ({columnas}) VALUES ({marcas})", valores)
        actividad_id = cur.lastrowid
        estado = "nuevo"
    if es_natacion:
        _guardar_natacion(cn, actividad_id, datos, series.material_desde_nombre(nombre))
    elif datos.get("puntos"):
        # Traza GPS (bici, carrera, senderismo, caminata): lo que permite medir segmentos y pintar mapas.
        _guardar_ruta(cn, actividad_id, datos["puntos"])
    return estado


def importar_carpeta(cn, ruta: str, fuente: str = "carpeta") -> dict:
    """Importa todos los FIT de una carpeta (reloj por USB o export de Garmin)."""
    ficheros = _buscar_ficheros(ruta)
    resumen = {"leidos": 0, "nuevos": 0, "actualizados": 0, "omitidos": 0, "incidencias": 0}
    for ruta_f in ficheros:
        resumen["leidos"] += 1
        try:
            estado = importar_fichero(cn, ruta_f, fuente=fuente)
            resumen[PLURAL_ESTADO[estado]] += 1
        except Exception as exc:                                    # noqa: BLE001
            resumen["incidencias"] += 1
            print(f"  [aviso] {os.path.basename(ruta_f)}: {exc}")
        if resumen["leidos"] % 250 == 0:
            cn.commit()
            print(f"  ... {resumen['leidos']} ficheros leidos")
    cn.commit()
    cn.execute(
        "INSERT INTO importacion (momento, fuente, ruta, leidos, nuevos, actualizados, omitidos, incidencias)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (db.ahora(), fuente, ruta, resumen["leidos"], resumen["nuevos"], resumen["actualizados"],
         resumen["omitidos"], resumen["incidencias"]),
    )
    cn.commit()
    return resumen


def importar_export_strava(cn, carpeta_export: str) -> dict:
    """Importa un export de Strava: primero el CSV (para tener los identificadores y los nombres),
    despues los FIT de `activities/` enlazados a su fila del CSV."""
    csv_actividades = os.path.join(carpeta_export, "activities.csv")
    if not os.path.isfile(csv_actividades):
        raise FileNotFoundError(f"no encuentro {csv_actividades}")
    carpeta_fit = os.path.join(carpeta_export, "activities")
    resumen = {"leidos": 0, "nuevos": 0, "actualizados": 0, "omitidos": 0, "incidencias": 0,
               "filas_csv": 0, "con_fit": 0, "sin_fit": 0}
    with open(csv_actividades, encoding="utf-8-sig", newline="") as fh:
        filas = list(csv.DictReader(fh))
    resumen["filas_csv"] = len(filas)
    for fila in filas:
        # El CSV guarda la ruta relativa (p.ej. "activities/21683931039.fit.gz"): nos quedamos
        # con el nombre del fichero, que ademas es el identificador de Garmin.
        nombre_fichero = os.path.basename((fila.get("Nombre del archivo") or "").strip())
        if not nombre_fichero or not nombre_fichero.endswith(EXTENSIONES):
            resumen["sin_fit"] += 1
            continue
        ruta_f = os.path.join(carpeta_fit, nombre_fichero)
        if not os.path.isfile(ruta_f):
            resumen["sin_fit"] += 1
            continue
        resumen["con_fit"] += 1
        resumen["leidos"] += 1
        tipo = (fila.get("Tipo de actividad") or "").strip().lower()
        try:
            estado = importar_fichero(
                cn, ruta_f, fuente="strava_export",
                id_strava=(fila.get("ID de actividad") or "").strip() or None,
                nombre=(fila.get("Nombre de la actividad") or "").strip() or None,
                disciplina=DISCIPLINAS_CSV.get(tipo),
            )
            resumen[PLURAL_ESTADO[estado]] += 1
        except Exception as exc:                                    # noqa: BLE001
            resumen["incidencias"] += 1
            print(f"  [aviso] {nombre_fichero}: {exc}")
        if resumen["leidos"] % 250 == 0:
            cn.commit()
            print(f"  ... {resumen['leidos']} ficheros leidos")
    cn.commit()
    cn.execute(
        "INSERT INTO importacion (momento, fuente, ruta, leidos, nuevos, actualizados, omitidos, incidencias)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (db.ahora(), "strava_export", carpeta_export, resumen["leidos"], resumen["nuevos"],
         resumen["actualizados"], resumen["omitidos"], resumen["incidencias"]),
    )
    cn.commit()
    return resumen
