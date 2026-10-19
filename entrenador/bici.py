#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Segmentos de bici: medir los tramos que el atleta repite sobre sus propias trazas GPS.

Que hace y por que asi:

- El export de Strava trae los segmentos que el atleta ha hecho (`segments.csv`), pero **solo con el punto de
  inicio y el de fin**: ni distancia, ni desnivel, ni pendiente. Aqui la geometria se mide sobre sus propias
  trazas, que es el dato que de verdad le pertenece: asi el numero no depende de lo que diga la web.
- Un intento (esfuerzo) se detecta buscando en la traza un punto cerca del inicio y despues otro cerca del
  fin. Se exige que lo recorrido se parezca a la linea recta (si no, es otro camino) y que la velocidad sea
  de bici (si sale un avion, son dos puntos mal enganchados por el GPS).
- Se guarda el **mejor intento de cada salida** (igual que Strava): asi una vuelta con dos pasadas no cuenta
  dos veces.
- Si el segmento es una subida y la traza lo hace al reves (bajando), ese intento no cuenta: no es comparable
  y falsearia la marca.

Solo escribe en las tablas `segmento_bici` y `esfuerzo_bici` de la base de datos.
"""

from __future__ import annotations

import csv
import math
import os

from . import db
from .lector_gpx import desempaquetar, distancia_m

# Radio (metros) para dar por hecho que la traza pasa por un punto del segmento.
RADIO_M = 60.0
# Lo recorrido entre inicio y fin, comparado con la linea recta: fuera de este margen es otro camino.
RATIO_MIN, RATIO_MAX = 0.85, 3.0
# Velocidad imposible en bici (144 km/h): dos puntos mal enganchados por el GPS.
VMAX_M_S = 40.0
# Desnivel (metros) a partir del cual el sentido del recorrido importa: subir y bajar no se comparan.
DESNIVEL_SENTIDO_M = 20.0
# Duracion minima creible de un intento (segundos).
TIEMPO_MIN_S = 5.0
# Salto de altitud (metros) para contar una subida: por debajo de esto es ruido del GPS.
UMBRAL_DESNIVEL_M = 3.0
# Margen que se le permite a un intento respecto a la distancia tipica del segmento: lo que se aparte mas no es
# el mismo recorrido (es la misma pareja de puntos por otro camino) y su tiempo no se puede comparar con los
# demas.
#   - 6 % relativo: en Piscina-C-Islallana (18,1 km) deja fuera los 12 intentos de 20,4 km que suben por la otra
#     carretera (11,8 % mas largos), que ensuciaban el mejor tiempo y la mediana con tiempos de otro recorrido.
#   - 60 m de suelo: por debajo de un kilometro manda el suelo, porque la distancia de un tramo corto se mide
#     entre los centros de las celdas del minero (30 m) y su propio temblor pesa mas que el 6 %. Un intento de
#     500 m no es un tramo de 300 m, y con 200 m de suelo si colaba.
TOL_DISTANCIA = 0.06
TOL_DISTANCIA_MIN_M = 60.0


def distancia_encaja(dist: float, dist_ref: float) -> bool:
    """Si lo recorrido es el segmento, o es la misma pareja de puntos por otro camino (entonces no vale)."""
    if not dist_ref:
        return True
    return abs(dist - dist_ref) <= max(TOL_DISTANCIA_MIN_M, TOL_DISTANCIA * dist_ref)


# Intentos minimos para poder hablar de "distancia tipica" de un segmento.
MIN_INTENTOS_REF = 3
# Agrupacion de distancias: dos intentos caen en el mismo grupo si no se apartan mas de esto (5 % o 150 m).
CLUSTER_TOL = 0.05
CLUSTER_MIN_M = 150.0
# Un grupo manda cuando el siguiente no llega a ser tantas veces el mayor. Si no, el segmento es dudoso.
CLUSTER_DOMINANCIA = 1.5


def _mediana(valores: list[float]) -> float | None:
    """Mediana (deja fuera los casos raros del GPS mejor que la media)."""
    limpios = sorted(v for v in valores if v is not None)
    if not limpios:
        return None
    medio = len(limpios) // 2
    if len(limpios) % 2:
        return limpios[medio]
    return (limpios[medio - 1] + limpios[medio]) / 2


def importar_segmentos(cn, carpeta_export: str) -> dict:
    """Lee `segments.csv` del export de Strava y rellena la tabla de segmentos.

    El export da los segmentos que el atleta ya ha hecho (nombre y los dos puntos). No se pisan los datos
    medidos: si el segmento ya existe solo se actualizan los puntos si venian vacios.
    """
    ruta = os.path.join(carpeta_export, "segments.csv")
    if not os.path.isfile(ruta):
        raise FileNotFoundError(f"no encuentro {ruta}")
    resumen = {"leidos": 0, "nuevos": 0, "ya_estaban": 0, "sin_datos": 0}
    with open(ruta, encoding="utf-8") as fh:
        for fila in csv.DictReader(fh):
            resumen["leidos"] += 1
            nombre = (fila.get("Nombre del segmento") or "").strip()
            try:
                lat_i = float(fila["Latitud al inicio"])
                lon_i = float(fila["Longitud al inicio"])
                lat_f = float(fila["Latitud al final"])
                lon_f = float(fila["Longitud al final"])
            except (KeyError, TypeError, ValueError):
                resumen["sin_datos"] += 1
                continue
            if not nombre:
                resumen["sin_datos"] += 1
                continue
            existe = cn.execute("SELECT id FROM segmento_bici WHERE nombre=?", (nombre,)).fetchone()
            if existe:
                resumen["ya_estaban"] += 1
                continue
            cn.execute(
                "INSERT INTO segmento_bici (nombre, lat_ini, lon_ini, lat_fin, lon_fin, id_strava)"
                " VALUES (?,?,?,?,?,?)",
                (nombre, lat_i, lon_i, lat_f, lon_f, (fila.get("ID de actividad") or "").strip() or None),
            )
            resumen["nuevos"] += 1
    cn.commit()
    return resumen


def _candidatos(puntos: list[tuple], lat: float, lon: float, radio: float) -> list[int]:
    """Indices de los puntos de la traza que caen dentro del cuadrado de `radio` metros alrededor del punto."""
    dlat = radio / 111320.0
    dlon = radio / (111320.0 * max(0.2, abs(math.cos(math.radians(lat)))))
    cerca = []
    for i, p in enumerate(puntos):
        if abs(p[0] - lat) <= dlat and abs(p[1] - lon) <= dlon:
            cerca.append(i)
    return cerca


def _prefijos(puntos: list[tuple]) -> list[float]:
    """Distancias acumuladas de la traza: permite saber lo recorrido entre dos puntos sin recalcularlo."""
    pref = [0.0]
    for a, b in zip(puntos, puntos[1:]):
        pref.append(pref[-1] + distancia_m(a[0], a[1], b[0], b[1]))
    return pref


def _desnivel(puntos: list[tuple], i: int, j: int, umbral: float = UMBRAL_DESNIVEL_M) -> float:
    """Desnivel que sube entre dos puntos, contando solo los tramos de mas de `umbral` metros.

    La altitud del GPS tiembla +-1 m: sumando las diferencias punto a punto salen cientos de metros donde
    hay 80. Con el umbral se cuentan las subidas de verdad y los descensos reinician la referencia.
    """
    ganado = 0.0
    referencia = None
    for p in puntos[i:j + 1]:
        ele = p[2]
        if ele is None:
            continue
        if referencia is None:
            referencia = ele
        elif ele - referencia >= umbral:
            ganado += ele - referencia
            referencia = ele
        elif ele < referencia:
            referencia = ele
    return ganado


def _buscar_intento(puntos: list[tuple], pref: list[float], seg: dict,
                    dist_ref: float | None = None) -> dict | None:
    """Devuelve el mejor intento de esta traza en el segmento, o None si no pasa por ahi.

    `dist_ref` es la distancia tipica del segmento (lo que miden sus intentos habituales). Cuando se conoce,
    se exige que el intento se parezca a ella: asi no cuela un par de puntos que engancha **otro camino**
    (una vuelta larga que pasa cerca del principio y del final, pero por otro sitio).
    """
    dentro_i = _candidatos(puntos, seg["lat_ini"], seg["lon_ini"], RADIO_M)
    dentro_f = _candidatos(puntos, seg["lat_fin"], seg["lon_fin"], RADIO_M)
    if not dentro_i or not dentro_f:
        return None
    # La linea recta entre los dos puntos del segmento (lo que se recorreria sin curvas).
    recta = distancia_m(seg["lat_ini"], seg["lon_ini"], seg["lat_fin"], seg["lon_fin"])
    if recta < 50.0:
        return None
    mejor = None
    for i in dentro_i:
        if puntos[i][3] is None:
            continue
        for j in dentro_f:
            if j <= i or puntos[j][3] is None:
                continue
            tiempo = puntos[j][3] - puntos[i][3]
            if tiempo < TIEMPO_MIN_S:
                continue
            desvio = (distancia_m(puntos[i][0], puntos[i][1], seg["lat_ini"], seg["lon_ini"])
                      + distancia_m(puntos[j][0], puntos[j][1], seg["lat_fin"], seg["lon_fin"]))
            # El desvio manda: interesa el par de puntos que de verdad pisa el principio y el final.
            if mejor is not None and desvio >= mejor["desvio"]:
                continue
            dist = pref[j] - pref[i]
            if dist <= 0:
                continue
            ratio = dist / recta
            if not (RATIO_MIN <= ratio <= RATIO_MAX):
                continue
            if dist / tiempo > VMAX_M_S:
                continue
            if dist_ref and not distancia_encaja(dist, dist_ref):
                continue
            subida = _desnivel(puntos, i, j)
            mejor = {
                "desvio": desvio, "i": i, "j": j, "tiempo_s": tiempo, "dist_m": dist, "desnivel_m": subida,
                "pendiente_pct": 100.0 * subida / dist, "vel_media_kmh": 3.6 * dist / tiempo,
            }
    return mejor


def _agrupar(valores: list[float], tolerancia: float = CLUSTER_TOL, minimo_m: float = CLUSTER_MIN_M):
    """Agrupa distancias por parecido: los intentos que miden lo mismo caen juntos.

    Se compara con la primera distancia del grupo (no con la anterior), para que un grupo no se vaya
    estirando poco a poco y acabe juntando dos caminos distintos.
    """
    ordenados = sorted(valores)
    grupos: list[list[float]] = [[ordenados[0]]]
    for valor in ordenados[1:]:
        primero = grupos[-1][0]
        if valor - primero <= max(minimo_m, tolerancia * primero):
            grupos[-1].append(valor)
        else:
            grupos.append([valor])
    return grupos


def _referencia(valores: list[float], minimo: int = MIN_INTENTOS_REF) -> tuple[float | None, bool]:
    """(distancia tipica, dudoso) de una lista de distancias medidas en un segmento.

    Manda el grupo de intentos que coinciden en longitud. Si el segundo grupo se le parece mucho, el segmento
    es **dudoso**: el mismo par de puntos se cruza por caminos distintos y no todos los tiempos son del mismo
    recorrido. Se devuelve igualmente el grupo mayor (es lo mas util), pero avisando.
    """
    if not valores:
        return None, False
    grupos = sorted(_agrupar(valores), key=len, reverse=True)
    if len(grupos[0]) < minimo:
        return None, False
    dudoso = len(grupos) > 1 and len(grupos[1]) * CLUSTER_DOMINANCIA > len(grupos[0])
    return _mediana(grupos[0]), dudoso


def _distancias_tipicas(cn, minimo: int = MIN_INTENTOS_REF) -> tuple[dict[int, float], set[int]]:
    """Distancia tipica de cada segmento: (`{segmento: metros}`, `{segmentos dudosos}`).

    Un mismo par de puntos (inicio y fin del segmento) se puede cruzar por caminos distintos: un dia 13,1 km y
    otro 25,4 km, porque las trazas pasan cerca de los dos puntos pero por otro sitio. Se agrupan las
    distancias medidas y manda **el grupo mayor** (ver `_referencia`).

    Con menos de `minimo` intentos no se fija nada: no hay con que comparar.
    """
    por_segmento: dict[int, list[float]] = {}
    for r in cn.execute("SELECT segmento_id, dist_m FROM esfuerzo_bici"):
        if r[1]:
            por_segmento.setdefault(r[0], []).append(r[1])
    refs: dict[int, float] = {}
    dudosos: set[int] = set()
    for seg_id, valores in por_segmento.items():
        ref, dudoso = _referencia(valores, minimo)
        if ref is None:
            continue
        refs[seg_id] = ref
        if dudoso:
            dudosos.add(seg_id)
    return refs, dudosos


def medir_esfuerzos(cn, disciplinas: tuple[str, ...] = ("ciclismo",) , pasadas: int = 2) -> dict:
    """Mide los intentos de cada segmento en cada salida con traza y rehace `esfuerzo_bici`.

    Se hace en dos pasadas: la primera mide sin saber nada y sirve para **descubrir la distancia tipica** de
    cada segmento; la segunda vuelve a medir exigiendo que el intento se parezca a esa distancia. Es lo que
    separa "paso cerca del principio y del final" de "hice el segmento": sin la segunda pasada, una vuelta
    larga que pasa por los dos puntos por otro camino contaba como intento.

    Actualiza tambien la ficha del segmento (distancia, desnivel y pendiente: mediana de sus intentos).
    """
    segmentos = [dict(r) for r in cn.execute(
        "SELECT id, nombre, lat_ini, lon_ini, lat_fin, lon_fin FROM segmento_bici ORDER BY id")]
    marcadores = ",".join("?" * len(disciplinas))
    salidas = [dict(r) for r in cn.execute(
        f"SELECT a.id, a.inicio_local, a.nombre, r.puntos FROM actividad a JOIN ruta r ON r.actividad_id = a.id"
        f" WHERE a.disciplina IN ({marcadores}) ORDER BY a.inicio_local", disciplinas)]
    resumen = {"salidas": len(salidas), "segmentos": len(segmentos), "intentos": 0, "descartados": 0,
               "pasadas": 0, "con_distancia": 0}
    for pasada in range(1, pasadas + 1):
        if pasada == 1:
            dist_ref, dudosos = {}, set()
        else:
            dist_ref, dudosos = _distancias_tipicas(cn)
        cn.execute("DELETE FROM esfuerzo_bici")
        cn.commit()
        resumen["intentos"] = 0
        resumen["descartados"] = 0
        resumen["pasadas"] = pasada
        resumen["con_distancia"] = len(dist_ref)
        for salida in salidas:
            puntos = desempaquetar(salida["puntos"])
            if len(puntos) < 10:
                continue
            pref = _prefijos(puntos)
            for seg in segmentos:
                intento = _buscar_intento(puntos, pref, seg, dist_ref.get(seg["id"]))
                if intento is None:
                    resumen["descartados"] += 1
                    continue
                cn.execute(
                    "INSERT INTO esfuerzo_bici (segmento_id, actividad_id, tiempo_s, dist_m, desnivel_m,"
                    " pendiente_pct, vel_media_kmh, fecha) VALUES (?,?,?,?,?,?,?,?)",
                    (seg["id"], salida["id"], intento["tiempo_s"], intento["dist_m"], intento["desnivel_m"],
                     intento["pendiente_pct"], intento["vel_media_kmh"], salida["inicio_local"]),
                )
                resumen["intentos"] += 1
            cn.commit()
    _descartar_contrarios(cn)
    _actualizar_geometria(cn)
    _marcar_dudosos(cn, dudosos)
    cn.commit()
    resumen["dudosos"] = len(dudosos)
    return resumen


def _marcar_dudosos(cn, dudosos: set[int]) -> None:
    """Marca los segmentos que no se pueden dar por buenos (los cruza por caminos distintos)."""
    cn.execute("UPDATE segmento_bici SET dudoso=0")
    for seg_id in sorted(dudosos):
        cn.execute("UPDATE segmento_bici SET dudoso=1 WHERE id=?", (seg_id,))
    cn.commit()


def _descartar_contrarios(cn) -> int:
    """Tira los intentos hechos en el sentido contrario en segmentos con desnivel claro (subir != bajar)."""
    quitados = 0
    for seg in cn.execute("SELECT id, nombre, desnivel_m FROM segmento_bici").fetchall():
        mediana = cn.execute("SELECT desnivel_m FROM esfuerzo_bici WHERE segmento_id=?",
                             (seg["id"],)).fetchall()
        desniveles = [r[0] for r in mediana if r[0] is not None]
        referencia = _mediana(desniveles)
        if referencia is None or abs(referencia) < DESNIVEL_SENTIDO_M:
            continue
        signo = 1 if referencia > 0 else -1
        cur = cn.execute(
            "DELETE FROM esfuerzo_bici WHERE segmento_id=? AND desnivel_m IS NOT NULL"
            " AND desnivel_m * ? < 0", (seg["id"], signo))
        quitados += cur.rowcount or 0
    cn.commit()
    return quitados


def _actualizar_geometria(cn) -> None:
    """Rellena la ficha del segmento con lo medido en sus intentos (mediana, para no fiarse de un GPS malo)."""
    for seg in cn.execute("SELECT id FROM segmento_bici").fetchall():
        filas = cn.execute("SELECT dist_m, desnivel_m, pendiente_pct FROM esfuerzo_bici WHERE segmento_id=?",
                           (seg["id"],)).fetchall()
        if not filas:
            cn.execute("UPDATE segmento_bici SET n_esfuerzos=0, dist_m=NULL, desnivel_m=NULL,"
                       " pendiente_pct=NULL WHERE id=?", (seg["id"],))
            continue
        cn.execute(
            "UPDATE segmento_bici SET n_esfuerzos=?, dist_m=?, desnivel_m=?, pendiente_pct=? WHERE id=?",
            (len(filas), _mediana([f[0] for f in filas]), _mediana([f[1] for f in filas]),
             _mediana([f[2] for f in filas]), seg["id"]),
        )
    cn.commit()


def resumen_segmentos(cn, min_veces: int = 1, disciplina: str = "ciclismo") -> list[dict]:
    """Ficha de cada segmento con lo que hace falta para comparar: veces, mejor tiempo, mediana y tendencia.

    El **peso** es veces x distancia: los tramos largos pesan mas aunque se repitan menos (los largos son los
    que interesan para entrenar).
    """
    filas = []
    sql = """
        SELECT s.id, s.nombre, s.dist_m, s.desnivel_m, s.pendiente_pct, s.n_esfuerzos, s.dudoso,
               COUNT(e.id) AS veces,
               MIN(e.tiempo_s) AS mejor_s, MAX(e.tiempo_s) AS peor_s,
               MIN(e.fecha) AS primera, MAX(e.fecha) AS ultima,
               MAX(e.vel_media_kmh) AS mejor_vel
          FROM segmento_bici s
          LEFT JOIN esfuerzo_bici e ON e.segmento_id = s.id
          LEFT JOIN actividad a ON a.id = e.actividad_id
         WHERE a.disciplina IS NULL OR a.disciplina = ?
         GROUP BY s.id
        HAVING veces >= ?
         ORDER BY veces * COALESCE(s.dist_m, 0) DESC
    """
    for r in cn.execute(sql, (disciplina, min_veces)):
        tiempos = [x[0] for x in cn.execute(
            "SELECT tiempo_s FROM esfuerzo_bici WHERE segmento_id=? ORDER BY fecha", (r["id"],))]
        mediana = _mediana(tiempos)
        tendencia = None
        if len(tiempos) >= 4:
            mitad = len(tiempos) // 2
            antes, ahora = _mediana(tiempos[:mitad]), _mediana(tiempos[mitad:])
            if antes:
                tendencia = 100.0 * (ahora - antes) / antes
        filas.append({
            "id": r["id"], "nombre": r["nombre"], "dist_m": r["dist_m"], "desnivel_m": r["desnivel_m"],
            "pendiente_pct": r["pendiente_pct"], "veces": r["veces"], "mejor_s": r["mejor_s"],
            "peor_s": r["peor_s"], "mediana_s": mediana, "primera": (r["primera"] or "")[:10],
            "ultima": (r["ultima"] or "")[:10], "mejor_vel_kmh": r["mejor_vel"],
            "tendencia_pct": tendencia,
            "peso": (r["veces"] or 0) * (r["dist_m"] or 0.0),
            "dudoso": bool(r["dudoso"]),
            "mejor_ritmo": (r["mejor_s"] / (r["dist_m"] / 1000.0)) if r["dist_m"] else None,
        })
    filas.sort(key=lambda f: (-f["peso"], f["nombre"]))
    return filas


def historial(cn, referencia: str | int) -> list[dict]:
    """Todos los intentos de un segmento, del mas antiguo al mas nuevo (para comparar resultados)."""
    if isinstance(referencia, int) or str(referencia).isdigit():
        seg = cn.execute("SELECT id, nombre FROM segmento_bici WHERE id=?", (int(referencia),)).fetchone()
    else:
        seg = cn.execute("SELECT id, nombre FROM segmento_bici WHERE nombre=?", (referencia,)).fetchone()
    if seg is None:
        raise ValueError(f"no encuentro el segmento {referencia!r}")
    filas = []
    for r in cn.execute(
            "SELECT e.fecha, e.tiempo_s, e.vel_media_kmh, e.desnivel_m, e.pendiente_pct, a.nombre AS salida,"
            " a.id AS actividad_id, a.distancia_m AS dist_salida"
            " FROM esfuerzo_bici e JOIN actividad a ON a.id = e.actividad_id"
            " WHERE e.segmento_id=? ORDER BY e.fecha", (seg["id"],)):
        filas.append(dict(r))
    return filas


def nombre_segmento(cn, referencia: str) -> str:
    """Sugiere el segmento que mejor encaja con un texto (para usar los nombres desde la linea de comandos)."""
    exacto = cn.execute("SELECT nombre FROM segmento_bici WHERE nombre=?", (referencia,)).fetchone()
    if exacto:
        return exacto["nombre"]
    parecidos = [r[0] for r in cn.execute(
        "SELECT nombre FROM segmento_bici WHERE nombre LIKE ? ORDER BY nombre", (f"%{referencia}%",))]
    if len(parecidos) == 1:
        return parecidos[0]
    if not parecidos:
        raise ValueError(f"no encuentro ningun segmento que se parezca a {referencia!r}")
    raise ValueError("¿a cual te refieres? " + " | ".join(parecidos))


def horas(segundos: float | None) -> str:
    """Segundos a texto de cronometro (h:mm:ss o mm:ss), que es como se leen los tiempos de bici."""
    if segundos is None:
        return "—"
    segundos = int(round(segundos))
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def anotar_rutas(cn, disciplinas: tuple[str, ...] = ("ciclismo",)) -> dict:
    """Rellena en cada traza la distancia, el desnivel y la velocidad media (se calcula una vez).

    Asi el cuadro de mando no tiene que descomprimir las trazas cada vez que se abre.
    """
    marcadores = ",".join("?" * len(disciplinas))
    filas = cn.execute(
        f"SELECT r.actividad_id, r.puntos FROM ruta r JOIN actividad a ON a.id = r.actividad_id"
        f" WHERE a.disciplina IN ({marcadores})", disciplinas).fetchall()
    anotadas = 0
    for fila in filas:
        puntos = desempaquetar(fila["puntos"])
        if len(puntos) < 2:
            continue
        pref = _prefijos(puntos)
        dist = pref[-1]
        desnivel = _desnivel(puntos, 0, len(puntos) - 1)
        con_hora = [p[3] for p in puntos if p[3] is not None]
        duracion = (con_hora[-1] - con_hora[0]) if len(con_hora) > 1 else None
        cn.execute("UPDATE ruta SET dist_m=?, desnivel_m=?, vel_media_kmh=? WHERE actividad_id=?",
                   (round(dist, 1), round(desnivel, 1),
                    round(3.6 * dist / duracion, 2) if duracion else None, fila["actividad_id"]))
        anotadas += 1
    cn.commit()
    return {"trazas": len(filas), "anotadas": anotadas}


def datos_panel(cn, disciplinas: tuple[str, ...] = ("ciclismo",)) -> dict:
    """Todo lo que necesita el portal de bici: cifras de cabecera, segmentos con su historial y salidas."""
    marcadores = ",".join("?" * len(disciplinas))
    segmentos = resumen_segmentos(cn, min_veces=1)
    for seg in segmentos:
        intentos = [dict(r) for r in cn.execute(
            "SELECT substr(e.fecha,1,10) AS fecha, e.tiempo_s, e.vel_media_kmh AS vel, e.pendiente_pct AS pend,"
            " a.nombre AS salida, e.actividad_id AS id"
            " FROM esfuerzo_bici e JOIN actividad a ON a.id = e.actividad_id"
            " WHERE e.segmento_id=? ORDER BY e.fecha", (seg["id"],))]
        seg["historial"] = intentos
        por_anio: dict[str, dict] = {}
        for it in intentos:
            anio = it["fecha"][:4]
            d = por_anio.setdefault(anio, {"anio": anio, "veces": 0, "mejor_s": None})
            d["veces"] += 1
            if d["mejor_s"] is None or it["tiempo_s"] < d["mejor_s"]:
                d["mejor_s"] = it["tiempo_s"]
        seg["por_anio"] = [por_anio[a] for a in sorted(por_anio)]

    salidas = []
    for r in cn.execute(
            f"""SELECT a.id, substr(a.inicio_local,1,10) AS fecha, substr(a.inicio_local,12,5) AS hora,
                       a.nombre, a.distancia_m AS dist, a.duracion_s AS dur, r.desnivel_m AS desnivel,
                       r.vel_media_kmh AS vel, r.n_puntos,
                       (SELECT COUNT(*) FROM esfuerzo_bici e WHERE e.actividad_id = a.id) AS segmentos
                  FROM actividad a LEFT JOIN ruta r ON r.actividad_id = a.id
                 WHERE a.disciplina IN ({marcadores})
                 ORDER BY a.inicio_local DESC LIMIT 40""", disciplinas):
        salidas.append(dict(r))

    kpis = {
        "salidas": cn.execute(f"SELECT COUNT(*) FROM actividad WHERE disciplina IN ({marcadores})",
                              disciplinas).fetchone()[0],
        "con_traza": cn.execute(
            f"SELECT COUNT(*) FROM ruta r JOIN actividad a ON a.id=r.actividad_id"
            f" WHERE a.disciplina IN ({marcadores})", disciplinas).fetchone()[0],
        "km": round((cn.execute(f"SELECT SUM(distancia_m) FROM actividad WHERE disciplina IN ({marcadores})",
                                disciplinas).fetchone()[0] or 0) / 1000.0, 1),
        "desnivel": round(cn.execute(
            f"SELECT SUM(r.desnivel_m) FROM ruta r JOIN actividad a ON a.id=r.actividad_id"
            f" WHERE a.disciplina IN ({marcadores})", disciplinas).fetchone()[0] or 0),
        "segmentos": len(segmentos),
        "intentos": cn.execute("SELECT COUNT(*) FROM esfuerzo_bici").fetchone()[0],
        "repetidos": sum(1 for s in segmentos if s["veces"] >= 2),
        "primera": (cn.execute(f"SELECT MIN(substr(inicio_local,1,10)) FROM actividad"
                               f" WHERE disciplina IN ({marcadores})", disciplinas).fetchone()[0] or ""),
        "ultima": (cn.execute(f"SELECT MAX(substr(inicio_local,1,10)) FROM actividad"
                              f" WHERE disciplina IN ({marcadores})", disciplinas).fetchone()[0] or ""),
    }
    return {"kpis": kpis, "segmentos": segmentos, "salidas": salidas}
