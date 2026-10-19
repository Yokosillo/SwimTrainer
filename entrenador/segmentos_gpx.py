#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Descubre los segmentos que el atleta repite, a partir de sus propias trazas GPS (los GPX del reloj).

Que hace y por que asi:

- El export de Strava trae los segmentos que el atleta **ya habia hecho** y solo con el punto de inicio y el
  de fin: ni forma, ni distancia, ni pendiente. Para tener el catalogo entero hay que sacarlos de sus trazas.
- Cada traza se pasa a una **rejilla de celdas de 30 m**: dos salidas que van por la misma carretera pisan las
  mismas celdas, en el mismo orden. Eso es un tramo repetido.
- Los tramos se buscan con **anclas**: cada salida se corta en ventanas de 8 celdas (120 m) y se guarda donde
  aparece cada ventana. Dos salidas que comparten una ventana se comparan celda a celda hacia delante y hacia
  atras, con margen para saltarse 1-2 celdas por ruido del GPS. Comparar las 529 salidas dos a dos a lo bruto
  seria eterno; con anclas solo se compara lo que de verdad se toca, y antes de eso un filtro por rejilla
  gruesa (250 m) descarta las parejas que no comparten ni un kilometro.
- Un tramo es candidato si mide **300 m o mas** y sale en **3 salidas o mas**.
- Los candidatos que son el mismo recorrido se funden (Jaccard de celdas >= 0,7 y en el mismo sentido). Los
  que son **uno dentro de otro se dejan**: en Strava conviven "lardero-navarrete" y "lardero-navarrete primer
  tramo", y esa distincion es util.
- El segmento se guarda con la **polilinea real** de la salida que mejor lo cubre, y se mide el intento de
  cada salida: hay que pisar el 80 % de las celdas, en orden y en el mismo sentido. Se guarda el mejor intento
  de cada salida (igual que Strava).
- Los nombres salen de la poblacion mas cercana al inicio y al final (una sola consulta a OpenStreetMap para
  tener las poblaciones del entorno; despues se calcula sin conexion).

Escribe solo en `segmento_minado`, `esfuerzo_minado` y `poblacion`. No toca `segmento_bici` ni `esfuerzo_bici`.
"""

from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request

from . import db
from .bici import TIEMPO_MIN_S, VMAX_M_S, distancia_encaja
from .lector_gpx import desempaquetar, distancia_m, empaquetar

# --- Rejilla y umbrales ---------------------------------------------------------------------------

CELDA_M = 30.0                 # lado de la celda (30 m: aguanta el temblor del GPS entre salidas)
CELDA_GRUESA_M = 250.0         # rejilla gruesa: filtro rapido para no comparar salidas que no se tocan
LAT0, LON0 = 42.40, -2.50      # origen de la rejilla (La Rioja); da igual cual sea si es fijo
ESCALA_LAT_M = 111_320.0       # metros por grado de latitud

N_GRAMO = 3                    # ancla: 3 celdas seguidas = 90 m (con 8 el GPS desplaza la ventana y no ancla)
SALTOS = 2                     # celdas que se pueden saltar por ruido del GPS
MIN_TRAMO_M = 300.0            # un tramo mas corto que esto no es un segmento
MAX_TRAMO_M = 35_000.0         # ni mas largo que una salida entera
MIN_CELDAS = 12                # celdas minimas de un tramo (luego manda la distancia medida)
MIN_SALIDAS = 3                # tiene que repetirse en 3 salidas o mas
MIN_GRUESAS = 3                # celdas gruesas (750 m) que tienen que compartir dos salidas
JACCARD_FUSION = 0.70          # dos tramos con esto o mas en comun son el mismo segmento
TOL_IGUAL_M = 60.0             # dos tramos que arrancan (y acaban) a menos de esto son el mismo camino
TOL_IGUAL_DIST = 0.15          # ... y miden casi lo mismo (15 %)
COBERTURA_MIN = 0.80           # fraccion del segmento que hay que pisar para contar como intento
RADIO_PUEBLO_M = 5_000.0       # distancia maxima a un pueblo para darle el nombre

CONSULTA_OSM = ('[out:json][timeout:120];('
                'node["place"~"^(city|town|village|hamlet)$"](42.15,-3.00,42.80,-2.05);'
                ');out;')
URL_OSM = "https://overpass-api.de/api/interpreter"
CABECERA = {"User-Agent": "entrenador-personal/1.0 (uso particular, datos propios)"}


# --- Rejilla --------------------------------------------------------------------------------------

def _rejilla(lat: float, lon: float, lado_m: float = CELDA_M) -> tuple[int, int]:
    """Pasa una coordenada a (i, j) de la rejilla. Local, plano, suficiente para la comarca."""
    dn = (lat - LAT0) * ESCALA_LAT_M
    de = (lon - LON0) * ESCALA_LAT_M * math.cos(math.radians(lat))
    return int(round(dn / lado_m)), int(round(de / lado_m))


def _clave(i: int, j: int) -> int:
    """Empaqueta la celda en un entero (los conjuntos de enteros son mucho mas rapidos que los de tuplas)."""
    return (i + 1_000_000) * 2_000_000 + (j + 1_000_000)


def _desclave(c: int) -> tuple[int, int]:
    return (c // 2_000_000) - 1_000_000, (c % 2_000_000) - 1_000_000


def _celdas(puntos: list[tuple], lado_m: float = CELDA_M) -> tuple[list[int], list[int]]:
    """Celdas de la traza, sin repetir las consecutivas, y el primer punto de cada celda.

    Ademas se quita el vaiven: si una celda es la misma que la de dos pasos antes (A, B, A), es el GPS
    temblando en la linde entre dos celdas y ensuciaria la comparacion entre salidas.
    """
    claves: list[int] = []
    indices: list[int] = []
    anterior = None
    for k, p in enumerate(puntos):
        c = _clave(*_rejilla(p[0], p[1], lado_m))
        if c == anterior:
            continue
        if len(claves) >= 2 and c == claves[-2]:
            continue
        claves.append(c)
        indices.append(k)
        anterior = c
    return claves, indices


# --- Cargar las salidas ---------------------------------------------------------------------------

def leer_salidas(cn, disciplina: str = "ciclismo", limite: int | None = None) -> list[dict]:
    """Carga las trazas ya importadas y las prepara para comparar (celdas, anclas y distancias)."""
    filas = cn.execute(
        "SELECT a.id, a.inicio_local, r.puntos FROM ruta r JOIN actividad a ON a.id = r.actividad_id "
        "WHERE a.disciplina = ? AND r.puntos IS NOT NULL AND length(r.puntos) > 0 "
        "ORDER BY a.inicio_local", (disciplina,)).fetchall()
    if limite:
        filas = filas[-limite:]        # ya vienen por fecha: el limite coge las mas recientes
    salidas = []
    for id_salida, fecha, blob in filas:
        puntos = desempaquetar(blob)
        if len(puntos) < 50:
            continue
        claves, indices = _celdas(puntos)
        if len(claves) < MIN_CELDAS:
            continue
        pref = [0.0]
        for k in range(1, len(puntos)):
            pref.append(pref[-1] + distancia_m(puntos[k - 1][0], puntos[k - 1][1],
                                               puntos[k][0], puntos[k][1]))
        anclas: dict[int, int] = {}
        for k in range(max(0, len(claves) - N_GRAMO + 1)):
            h = hash(tuple(claves[k:k + N_GRAMO]))
            if h not in anclas:
                anclas[h] = k
        gruesas = {_clave(*_rejilla(p[0], p[1], CELDA_GRUESA_M)) for p in puntos}
        posiciones: dict[int, list[int]] = {}
        for k, c in enumerate(claves):
            posiciones.setdefault(c, []).append(k)
        salidas.append({"id": id_salida, "fecha": fecha, "puntos": puntos, "claves": claves,
                        "indices": indices, "pref": pref, "anclas": anclas, "gruesas": gruesas,
                        "posiciones": posiciones})
    return salidas


# --- Comparar dos salidas -------------------------------------------------------------------------

def _extender(ca: list[int], cb: list[int], ia: int, ib: int, adelante: bool,
              saltos: int = SALTOS) -> tuple[int, int]:
    """Camina desde el ancla mientras las dos salidas pisen las mismas celdas.

    Devuelve el ultimo par de celdas que coincide. Los saltos son de una sola celda de mas en una salida
    (un desvio de dos metros por el arcen) o de una celda que la otra no tiene.
    """
    n, m = len(ca), len(cb)
    paso = 1 if adelante else -1
    x, y = ia + paso, ib + paso
    ultimo = (ia, ib)
    while 0 <= x < n and 0 <= y < m:
        if ca[x] == cb[y]:
            ultimo = (x, y)
            x += paso
            y += paso
            continue
        avance = None
        for k in range(1, saltos + 1):
            if 0 <= y + k * paso < m and ca[x] == cb[y + k * paso]:
                avance = ("b", k)
                break
            if 0 <= x + k * paso < n and ca[x + k * paso] == cb[y]:
                avance = ("a", k)
                break
        if avance is None:
            break
        if avance[0] == "b":
            y += avance[1] * paso
        else:
            x += avance[1] * paso
    return ultimo


def _unir(tramos: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Junta los tramos de la misma pareja que se solapan (el ancla puede cortar un tramo en dos)."""
    if not tramos:
        return []
    tramos = sorted(tramos)
    fuera = [list(tramos[0])]
    for t in tramos[1:]:
        u = fuera[-1]
        if t[0] <= u[1] + 1 and t[2] <= u[3] + 1:
            u[1] = max(u[1], t[1])
            u[3] = max(u[3], t[3])
        else:
            fuera.append(list(t))
    return [(t[0], t[1], t[2], t[3]) for t in fuera]


def tramos_de_pareja(a: dict, b: dict, saltos: int = SALTOS) -> list[tuple[int, int, int, int]]:
    """Tramos comunes a dos salidas, como rangos de celdas (el inicio y el fin, en `a` y en `b`)."""
    comunes = a["anclas"].keys() & b["anclas"].keys()
    if not comunes:
        return []
    ca, cb = a["claves"], b["claves"]
    pares = sorted((a["anclas"][h], b["anclas"][h]) for h in comunes)
    usados: set[int] = set()
    crudos = []
    for ia, ib in pares:
        if ia in usados:
            continue
        ini_a, ini_b = _extender(ca, cb, ia, ib, False, saltos)
        fin_a, fin_b = _extender(ca, cb, ia + N_GRAMO - 1, ib + N_GRAMO - 1, True, saltos)
        if fin_a - ini_a + 1 < MIN_CELDAS:
            continue
        crudos.append((ini_a, fin_a, ini_b, fin_b))
        usados.update(range(ini_a, fin_a + 1))
    return _unir(crudos)


def _mismo_sentido(ini_a: tuple[int, int], fin_a: tuple[int, int],
                   ini_b: tuple[int, int], fin_b: tuple[int, int]) -> bool:
    """El mismo recorrido hecho al reves es otro segmento (como en Strava): subir y bajar no se comparan."""
    v1 = (fin_a[0] - ini_a[0], fin_a[1] - ini_a[1])
    v2 = (fin_b[0] - ini_b[0], fin_b[1] - ini_b[1])
    return v1[0] * v2[0] + v1[1] * v2[1] > 0


def _jaccard(a: set[int], b: set[int]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


# --- Minar los segmentos ---------------------------------------------------------------------------

def _proponer(candidatos: list[dict], cubos: dict[int, list[int]], a: dict, ia0: int, ia1: int,
              dist: float) -> None:
    """Apunta un tramo como candidato: si ya existe uno igual se le suma un voto; si no, se crea."""
    claves = a["claves"][ia0:ia1 + 1]
    ini = _desclave(claves[0])
    fin = _desclave(claves[-1])
    conjunto = set(claves)
    vistos: set[int] = set()
    mejor, mejor_j = None, 0.0
    for k in (0, len(claves) // 4, len(claves) // 2, 3 * len(claves) // 4, len(claves) - 1):
        for idx in cubos.get(claves[k], ()):
            if idx in vistos:
                continue
            vistos.add(idx)
            c = candidatos[idx]
            if not _mismo_sentido(c["ini"], c["fin"], ini, fin):
                continue
            j = _jaccard(c["conjunto"], conjunto)
            if j > mejor_j:
                mejor, mejor_j = idx, j
    if mejor is not None and mejor_j >= JACCARD_FUSION:
        c = candidatos[mejor]
        c["salidas"].add(a["id"])
        c["votos"] += 1
        if dist > c["dist"]:
            c["claves"] = claves
            c["conjunto"] = conjunto
            c["dist"] = dist
            c["ejemplo"] = (a["id"], a["indices"][ia0], a["indices"][ia1])
            c["fecha"] = a["fecha"]
        return
    idx = len(candidatos)
    candidatos.append({"claves": claves, "conjunto": conjunto, "ini": ini, "fin": fin, "dist": dist,
                       "salidas": {a["id"]}, "votos": 1, "fecha": a["fecha"],
                       "ejemplo": (a["id"], a["indices"][ia0], a["indices"][ia1])})
    for k in (0, len(claves) // 4, len(claves) // 2, 3 * len(claves) // 4, len(claves) - 1):
        cubos.setdefault(claves[k], []).append(idx)


def _limpiar_claves(claves: list[int]) -> list[int]:
    """Quita repeticiones y vaivenes de una lista de celdas (lo mismo que hace `_celdas` con una traza).

    Al unir dos trozos la celda del empalme queda repetida, y con la celda repetida la medida se corta en
    seco en el empalme: el intento no llega al 80 % del segmento y el tramo se queda sin tiempos.
    """
    fuera: list[int] = []
    for c in claves:
        if fuera and c == fuera[-1]:
            continue
        if len(fuera) >= 2 and c == fuera[-2]:
            continue
        fuera.append(c)
    return fuera


def _unir_fragmentos(candidatos: list[dict], pasadas: int = 8, saltos: int = 3,
                     solape_min: float = 0.50, log=print) -> list[dict]:
    """Junta los trozos de una misma carretera que la comparacion ha cortado (en un cruce, en un semaforo).

    Dos trozos son el mismo camino cuando el final de uno esta a menos de `saltos` celdas del principio del
    otro, van en el mismo sentido y los han hecho las mismas salidas. Sin esto, una carretera larga queda
    partida en trozos de 400 m con dos salidas cada uno en vez de un segmento de 6 km con las salidas de
    todos, que es lo que el atleta reconoce como "su" segmento.
    """
    fusiones = 0
    for _ in range(pasadas):
        cubos: dict[int, list[int]] = {}
        for idx, c in enumerate(candidatos):
            if c is None:
                continue
            for celda in c["claves"][-saltos:]:
                cubos.setdefault(celda, []).append(idx)
        hechas = 0
        for idx, a in enumerate(candidatos):
            if a is None:
                continue
            vecinos: set[int] = set()
            for celda in a["claves"][:saltos]:
                vecinos.update(cubos.get(celda, ()))
            for j in vecinos:
                if j <= idx:
                    continue
                b = candidatos[j]
                if b is None or not _mismo_sentido(a["ini"], a["fin"], b["ini"], b["fin"]):
                    continue
                solape = len(a["salidas"] & b["salidas"]) / min(len(a["salidas"]), len(b["salidas"]))
                if solape < solape_min:
                    continue
                claves = a["claves"] + b["claves"]
                if len(claves) * CELDA_M > MAX_TRAMO_M:
                    continue
                hueco = distancia_m(*_centro(_desclave(a["claves"][-1])),
                                    *_centro(_desclave(b["claves"][0])))
                a["claves"] = _limpiar_claves(a["claves"] + b["claves"])
                a["conjunto"] = a["conjunto"] | b["conjunto"]
                a["salidas"] |= b["salidas"]
                a["votos"] += b["votos"]
                a["dist"] = a["dist"] + b["dist"] + hueco
                a["fin"] = b["fin"]
                candidatos[j] = None
                hechas += 1
        fusiones += hechas
        if not hechas:
            break
    log(f"  trozos unidos: {fusiones}")
    return [c for c in candidatos if c is not None]


def _metros(a: tuple[int, int], b: tuple[int, int]) -> float:
    """Distancia en metros entre el centro de dos celdas."""
    return distancia_m(*_centro(a), *_centro(b))


_COS_LAT = math.cos(math.radians(LAT0))     # para pasar celdas a metros llanos (comparar caminos, rapido)


def _plano(celda, lado_m: float = CELDA_M) -> tuple[float, float]:
    """La celda en metros llanos, para medir distancias entre caminos con sumas y restas.

    Vale lo mismo la clave (un numero) que el par (i, j): segun de donde venga el camino se guarda de una
    forma o de otra.
    """
    if isinstance(celda, int):
        celda = _desclave(celda)
    i, j = celda
    return i * lado_m, j * lado_m * _COS_LAT


def _mismo_camino(a: list[int], b: list[int], tol_m: float = TOL_IGUAL_M) -> bool:
    """Mira si dos listas de celdas recorren el mismo camino: cada punto de una esta cerca de la otra.

    Se recorre una lista por puntos (ocho repartidos) y cada uno tiene que tener **algun punto de la otra a
    menos de `tol_m`**; despues lo mismo al reves. Asi da igual que una traza tenga la mitad de puntos que la
    otra, que empiece un poco antes o que se acabe un poco despues: lo que importa es que no se separen.

    Comparar los cinco puntos repartidos por el mismo porcentaje (que es lo que se hacia antes) fallaba con
    listas de distinta longitud: el punto al 100 % de una no era el final de la otra y salian desvios de 124 m
    en caminos que son el mismo.
    """
    for x, y in ((a, b), (b, a)):
        plano_y = [_plano(c) for c in y]
        paso = max(1, len(x) // 8)
        for k in range(0, len(x), paso):
            yx, xx = _plano(x[k])
            if not any((yx - yy) ** 2 + (xx - xy) ** 2 <= tol_m * tol_m for yy, xy in plano_y):
                return False
    return True


def _fundir_iguales(candidatos: list[dict], log=print) -> list[dict]:
    """Funde los tramos que son el mismo camino y han quedado repetidos.

    La rejilla de 30 m hace que dos salidas que pasan cinco metros a un lado no pisen la misma celda: del
    mismo trozo de carretera salen dos o tres candidatos con el mismo arranque, la misma llegada y casi la
    misma distancia (en Villamediana salian tres copias de 642 m, con 212, 209 y 204 salidas). La fusion de
    `_proponer` no los pilla porque sus conjuntos de celdas no llegan a solaparse lo suficiente (dos trazas
    del mismo camino pueden compartir la mitad de las celdas y eso no llega al 70 %).

    Aqui se juzga por la **forma**: misma distancia (8 %) y los cinco puntos de `_mismo_camino` a menos de
    60 m. Se queda el que mas salidas tiene y se le suman las de los gemelos.
    """
    candidatos = sorted(candidatos, key=lambda c: -len(c["salidas"]))
    cubos: dict[int, list[dict]] = {}
    fuera: list[dict] = []
    fusiones = 0
    mirados = [0, 0, 0, 0]                       # pares vistos / descartados por sentido, distancia y forma
    for c in candidatos:
        gi, gj = c["ini"]                       # celda fina (30 m): los caminos del mismo tramo arrancan juntos
        gemelo = None
        for di in (-2, -1, 0, 1, 2):            # +-60 m, que es la tolerancia de `_mismo_camino`
            for dj in (-2, -1, 0, 1, 2):
                for d in cubos.get(_clave(gi + di, gj + dj), ()):
                    mirados[0] += 1
                    if not _mismo_sentido(c["ini"], c["fin"], d["ini"], d["fin"]):
                        mirados[1] += 1
                        continue
                    if abs(c["dist"] - d["dist"]) > TOL_IGUAL_DIST * max(c["dist"], d["dist"]):
                        mirados[2] += 1
                        continue
                    if not _mismo_camino(c["claves"], d["claves"]):
                        mirados[3] += 1
                        continue
                    gemelo = d
                    break
                if gemelo is not None:
                    break
            if gemelo is not None:
                break
        if gemelo is None:
            fuera.append(c)
            cubos.setdefault(_clave(gi, gj), []).append(c)
        else:
            gemelo["salidas"] |= c["salidas"]
            gemelo["votos"] += c["votos"]
            fusiones += 1
    log(f"  copias del mismo tramo fundidas: {fusiones} (quedan {len(fuera)}; "
        f"pares vistos {mirados[0]}, descartados por sentido {mirados[1]}, por distancia {mirados[2]}, "
        f"por forma {mirados[3]})")
    return fuera


def _verificar(candidatos: list[dict], por_id: dict, cobertura_min: float = COBERTURA_MIN,
               log=print) -> list[dict]:
    """Comprueba cada tramo contra sus propias salidas: solo vale si alguna lo recorre de verdad.

    Al unir trozos es facil encadenar caminos que en realidad no van seguidos (cada union parece buena por
    separado y el resultado se va del camino). Aqui se tira todo lo que no aguanta la prueba, y de paso el
    numero de salidas que se guarda es el de las que de verdad pasan por el tramo, no el de las que lo
    propusieron.
    """
    fuera = []
    for c in candidatos:
        seg = _limpiar_claves(c["claves"])
        validas = [id_ for id_ in sorted(c["salidas"])
                   if (s := por_id.get(id_)) is not None and _intento(s, seg, cobertura_min) is not None]
        if validas:
            c["claves"] = seg
            c["conjunto"] = set(seg)
            c["salidas"] = set(validas)
            fuera.append(c)
    log(f"  tramos que aguantan la prueba: {len(fuera)} de {len(candidatos)}")
    return fuera


def minar(cn, disciplina: str = "ciclismo", limite: int | None = None, log=print) -> dict:
    """Descubre los segmentos y los guarda en `segmento_minado` (sin medir todavia los intentos).

    Rehace el catalogo entero: lo que hubiera de antes se borra, porque los tramos son los que salen de
    estas salidas. Asi no se duplican al repetir la mineria.
    """
    cn.execute("DELETE FROM esfuerzo_minado")
    cn.execute("DELETE FROM segmento_minado")
    cn.commit()
    salidas = leer_salidas(cn, disciplina, limite)
    log(f"  salidas con traza: {len(salidas)}")
    if len(salidas) < MIN_SALIDAS:
        return {"salidas": len(salidas), "candidatos": 0, "segmentos": 0, "parejas": 0, "segundos": 0.0}
    por_id = {s["id"]: s for s in salidas}
    candidatos: list[dict] = []
    cubos: dict[int, list[int]] = {}
    t0 = time.time()
    parejas = 0
    for x in range(len(salidas)):
        ax = salidas[x]
        for y in range(x + 1, len(salidas)):
            by = salidas[y]
            if len(ax["gruesas"] & by["gruesas"]) < MIN_GRUESAS:
                continue
            parejas += 1
            for (ia0, ia1, _ib0, _ib1) in tramos_de_pareja(ax, by):
                dist = ax["pref"][min(len(ax["pref"]) - 1, ax["indices"][ia1] + 1)] - ax["pref"][ax["indices"][ia0]]
                if not (MIN_TRAMO_M <= dist <= MAX_TRAMO_M):
                    continue
                _proponer(candidatos, cubos, ax, ia0, ia1, dist)
        if (x + 1) % 20 == 0 or x + 1 == len(salidas):
            log(f"  {x + 1}/{len(salidas)} salidas | {parejas} parejas | {len(candidatos)} candidatos | "
                f"{time.time() - t0:.0f} s")
    utiles = _unir_fragmentos(candidatos, log=log)
    utiles = _verificar(utiles, por_id, log=log)
    # La forma que se guarda es la traza de una de sus propias salidas, no la union de trozos (que queda con
    # saltos y celdas de mas). Comparar las copias sobre esa traza de verdad es lo que las quita: mirando la
    # union, dos candidatos del mismo camino podian tener listas de celdas que no se parecian en nada.
    limpios = []
    for c in utiles:
        s = por_id[c["ejemplo"][0]]
        p0, p1 = c["ejemplo"][1], c["ejemplo"][2]
        puntos = s["puntos"][max(0, p0):p1 + 1]
        claves = _limpiar_claves([_clave(*_rejilla(la, lo)) for la, lo, *_ in puntos])
        if len(puntos) < 2 or len(claves) < 2:
            continue
        c = dict(c)
        c.update({"puntos": puntos, "claves": claves, "conjunto": set(claves),
                  "ini": _desclave(claves[0]), "fin": _desclave(claves[-1]),
                  "dist": s["pref"][p1] - s["pref"][p0]})
        limpios.append(c)
    utiles = _fundir_iguales(limpios, log=log)
    utiles = [c for c in utiles if len(c["salidas"]) >= MIN_SALIDAS]
    utiles.sort(key=lambda c: (-len(c["salidas"]), -c["dist"]))
    cn.execute("DELETE FROM esfuerzo_minado")
    cn.execute("DELETE FROM segmento_minado")
    guardados = 0
    for c in utiles:
        s = por_id[c["ejemplo"][0]]
        p0, p1 = c["ejemplo"][1], c["ejemplo"][2]
        puntos = s["puntos"][max(0, p0):p1 + 1]
        if len(puntos) < 2:
            continue
        dist = s["pref"][p1] - s["pref"][p0]
        desnivel = _desnivel_neto(s["puntos"], p0, p1)
        fecha = c["fecha"] or ""
        cn.execute(
            "INSERT INTO segmento_minado (nombre, lat_ini, lon_ini, lat_fin, lon_fin, n_puntos, puntos, "
            "celdas, dist_m, desnivel_m, pendiente_pct, n_salidas, votos, primera, ultima) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"Tramo {guardados + 1:04d}", puntos[0][0], puntos[0][1], puntos[-1][0], puntos[-1][1],
             len(puntos), empaquetar(puntos), json.dumps(c["claves"]), dist, desnivel,
             100.0 * desnivel / dist if dist else None, len(c["salidas"]), c["votos"], fecha, fecha))
        guardados += 1
    cn.commit()
    resumen = {"salidas": len(salidas), "candidatos": len(candidatos), "segmentos": guardados,
               "parejas": parejas, "segundos": round(time.time() - t0, 1)}
    log(f"  candidatos: {len(candidatos)} | segmentos guardados: {guardados} | {resumen['segundos']} s")
    return resumen


# --- Medir los intentos ---------------------------------------------------------------------------

def _alinear(claves: list[int], x0: int, seg: list[int], saltos: int = SALTOS):
    """Alinea el segmento con la salida empezando en la celda x0.

    Devuelve (celdas pisadas, celda de la salida donde acaba) o (0, None) si no encaja. Se permite que la
    salida se salte un par de celdas (desvio del GPS) y que falten celdas del segmento, pero las que falten
    cuentan como no pisadas: de ahi sale la cobertura.
    """
    x, k = x0, 0
    cubiertas = 0
    ultimo = x0
    while k < len(seg) and x < len(claves):
        if claves[x] == seg[k]:
            cubiertas += 1
            ultimo = x
            k += 1
            x += 1
            continue
        salto = None
        for d in range(1, saltos + 1):
            if x + d < len(claves) and claves[x + d] == seg[k]:
                salto = ("salida", d)
                break
            if k + d < len(seg) and claves[x] == seg[k + d]:
                salto = ("segmento", d)
                break
        if salto is None:
            break
        if salto[0] == "salida":
            x += salto[1]
        else:
            k += salto[1]
    return cubiertas, ultimo


def _desnivel_neto(puntos: list[tuple], i: int, j: int, ventana: int = 8) -> float:
    """Desnivel **con signo** entre dos puntos (positivo si sube).

    Se comparan las medias de los primeros y de los ultimos puntos porque la altitud del GPS tiembla: la
    diferencia de dos puntos sueltos puede dar 20 m donde hay 2. Con el signo se distingue una subida de un
    descenso, que es lo que hace falta para saber en que sentido se ha hecho el segmento.
    """
    ini = [p[2] for p in puntos[max(0, i):i + ventana] if p[2] is not None]
    fin = [p[2] for p in puntos[max(0, j - ventana + 1):j + 1] if p[2] is not None]
    if not ini or not fin:
        return 0.0
    return sum(fin) / len(fin) - sum(ini) / len(ini)


_CACHE_GRUESA: dict[int, int] = {}


def _gruesa(celda_fina: int) -> int:
    """Celda gruesa (250 m) en la que cae una celda fina: sirve para descartar salidas en un pispas."""
    g = _CACHE_GRUESA.get(celda_fina)
    if g is None:
        g = _clave(*_rejilla(*_centro(_desclave(celda_fina)), CELDA_GRUESA_M))
        _CACHE_GRUESA[celda_fina] = g
    return g


def _intento(s: dict, seg: list[int], cobertura_min: float = COBERTURA_MIN):
    """El mejor intento de una salida sobre un segmento: (p_ini, p_fin, cobertura, tiempo) o None."""
    if not seg:
        return None
    mejor = None
    for x0 in s["posiciones"].get(seg[0], ()):
        cubiertas, x_fin = _alinear(s["claves"], x0, seg)
        cobertura = cubiertas / len(seg)
        if cobertura < cobertura_min or x_fin is None:
            continue
        p_ini = s["indices"][x0]
        p_fin = s["indices"][x_fin]
        if p_fin <= p_ini:
            continue
        tiempo = None
        if s["puntos"][p_fin][3] and s["puntos"][p_ini][3]:
            tiempo = s["puntos"][p_fin][3] - s["puntos"][p_ini][3]
        if mejor is None or (tiempo is not None and (mejor[3] is None or tiempo < mejor[3])):
            mejor = (p_ini, p_fin, cobertura, tiempo)
        if cobertura >= 0.99:
            break        # lo ha hecho entero: no hace falta buscar mas vueltas del mismo tramo
    return mejor


def _reubicar(cn, seg_id: int, salidas_por_id: dict, ref: tuple) -> None:
    """Pone la geometria del segmento segun la salida que mejor lo ha cubierto.

    El tramo descubierto puede haber salido con el principio y el fin de la salida que lo propuso; al medir
    aparece alguna salida que lo cubre entero, y es su traza la que queda guardada: asi el mapa, la distancia
    y la pendiente son los de un intento de verdad y no los de un trozo.
    """
    _, act_id, p_ini, p_fin = ref
    s = salidas_por_id.get(act_id)
    if s is None or p_fin <= p_ini:
        return
    puntos = s["puntos"][p_ini:p_fin + 1]
    if len(puntos) < 2:
        return
    dist = s["pref"][p_fin] - s["pref"][p_ini]
    desnivel = _desnivel_neto(s["puntos"], p_ini, p_fin)
    cn.execute("UPDATE segmento_minado SET puntos = ?, n_puntos = ?, lat_ini = ?, lon_ini = ?, "
               "lat_fin = ?, lon_fin = ?, dist_m = ?, desnivel_m = ?, pendiente_pct = ?, km = ? "
               "WHERE id = ?",
               (empaquetar(puntos), len(puntos), puntos[0][0], puntos[0][1], puntos[-1][0],
                puntos[-1][1], dist, desnivel, 100.0 * desnivel / dist if dist else None,
                s["pref"][p_ini] / 1000.0, seg_id))


def medir(cn, disciplina: str = "ciclismo", limite: int | None = None, log=print) -> dict:
    """Mide el intento de cada salida en cada segmento descubierto (se guarda el mejor de cada salida)."""
    salidas = leer_salidas(cn, disciplina, limite)
    salidas_por_id = {s["id"]: s for s in salidas}
    log(f"  salidas con traza: {len(salidas)}")
    filas = cn.execute("SELECT id, nombre, celdas, dist_m FROM segmento_minado ORDER BY id").fetchall()
    cn.execute("DELETE FROM esfuerzo_minado")
    intentos = 0
    sin_intentos = 0
    descartados = 0
    t0 = time.time()
    for k, (seg_id, nombre, celdas_txt, dist_seg) in enumerate(filas, 1):
        seg = json.loads(celdas_txt)
        gruesas_seg = {_gruesa(c) for c in seg[::2]}
        minimo = max(1, int(0.5 * len(gruesas_seg)))
        n = 0
        mejor_ref = None
        for s in salidas:
            if len(gruesas_seg & s["gruesas"]) < minimo:
                continue
            intento = _intento(s, seg)
            if intento is None:
                continue
            p_ini, p_fin, cobertura, tiempo = intento
            if tiempo is None or tiempo < TIEMPO_MIN_S:
                descartados += 1
                continue
            dist = s["pref"][p_fin] - s["pref"][p_ini]
            if dist <= 0:
                continue
            if dist_seg and not distancia_encaja(dist, dist_seg):
                descartados += 1        # lo que ha recorrido no es el segmento: otro camino
                continue
            if mejor_ref is None or cobertura > mejor_ref[0]:
                mejor_ref = (cobertura, s["id"], p_ini, p_fin)
            vel = 3.6 * dist / tiempo
            if vel > VMAX_M_S * 3.6:
                descartados += 1
                continue
            desnivel = _desnivel_neto(s["puntos"], p_ini, p_fin)
            cn.execute(
                "INSERT OR REPLACE INTO esfuerzo_minado (segmento_id, actividad_id, tiempo_s, dist_m, "
                "desnivel_m, pendiente_pct, vel_media_kmh, cobertura, fecha) VALUES (?,?,?,?,?,?,?,?,?)",
                (seg_id, s["id"], tiempo, dist, desnivel, 100.0 * desnivel / dist, vel, cobertura,
                 s["fecha"]))
            n += 1
        if mejor_ref is not None:
            _reubicar(cn, seg_id, salidas_por_id, mejor_ref)
        if n:
            # n_intentos y n_salidas salen de la medida de verdad: los intentos que han aguantado la prueba.
            # (n_salidas lo puso `_verificar` al descubrir el tramo y se queda corto: al reubicar la traza del
            # tramo hay salidas que entran y no se contaron).
            cn.execute("UPDATE segmento_minado SET n_intentos = ?, n_salidas = ?, "
                       "primera = (SELECT MIN(fecha) FROM esfuerzo_minado WHERE segmento_id = ?), "
                       "ultima = (SELECT MAX(fecha) FROM esfuerzo_minado WHERE segmento_id = ?) "
                       "WHERE id = ?", (n, n, seg_id, seg_id, seg_id))
        else:
            sin_intentos += 1
        intentos += n
        if k % 50 == 0 or k == len(filas):
            log(f"  {k}/{len(filas)} segmentos | {intentos} intentos | {time.time() - t0:.0f} s")
    if limite is None:
        # los tramos que no ha hecho nadie no sirven para compararse: fuera (solo en una pasada completa)
        cn.execute("DELETE FROM segmento_minado WHERE n_intentos = 0")
    cn.commit()
    return {"segmentos": len(filas), "intentos": intentos, "sin_intentos": sin_intentos,
            "descartados": descartados, "segundos": round(time.time() - t0, 1)}


def _centro(celda: tuple[int, int], lado_m: float = CELDA_M) -> tuple[float, float]:
    """Vuelve a coordenadas del centro de la celda (para poder agrupar celdas finas en gruesas)."""
    i, j = celda
    lat = LAT0 + (i * lado_m) / ESCALA_LAT_M
    lon = LON0 + (j * lado_m) / (ESCALA_LAT_M * math.cos(math.radians(lat)))
    return lat, lon


# --- Poner nombres --------------------------------------------------------------------------------

def cargar_poblaciones(cn, log=print, intentos: int = 3) -> int:
    """Trae de OpenStreetMap los pueblos y aldeas del entorno (una sola consulta, se guarda).

    Overpass se cae a menudo (504) cuando esta cargado: se reintenta unas cuantas veces y, si no hay manera,
    se sigue sin pueblos (los segmentos se quedan con su numero). Esto no puede tumbar la mineria.
    """
    url = URL_OSM + "?data=" + urllib.parse.quote(CONSULTA_OSM)
    datos = None
    for n in range(1, intentos + 1):
        try:
            peticion = urllib.request.Request(url, headers=CABECERA)
            with urllib.request.urlopen(peticion, timeout=180) as respuesta:
                datos = json.loads(respuesta.read().decode("utf-8"))
            break
        except Exception as ex:                       # red, 429, 504, lo que sea
            log(f"  OpenStreetMap no responde (intento {n}/{intentos}): {type(ex).__name__}: {ex}")
            time.sleep(5 * n)
    if datos is None:
        log("  sin pueblos de OpenStreetMap: los segmentos se quedan numerados")
        return 0
    n = 0
    for el in datos.get("elements", []):
        etiquetas = el.get("tags") or {}
        nombre = etiquetas.get("name")
        if not nombre or el.get("lat") is None:
            continue
        cn.execute("INSERT OR IGNORE INTO poblacion (nombre, tipo, lat, lon) VALUES (?,?,?,?)",
                   (nombre, etiquetas.get("place"), el["lat"], el["lon"]))
        n += 1
    cn.commit()
    log(f"  poblaciones guardadas: {n}")
    return n


def _pueblo_cerca(poblaciones: list[tuple], lat: float, lon: float,
                  radio: float = RADIO_PUEBLO_M):
    mejor = None
    for nombre, plat, plon in poblaciones:
        d = distancia_m(lat, lon, plat, plon)
        if d <= radio and (mejor is None or d < mejor[1]):
            mejor = (nombre, d)
    return mejor


def nombrar(cn, log=print) -> int:
    """Pone nombre a los segmentos con el pueblo mas cercano al inicio y al final."""
    poblaciones = cn.execute("SELECT nombre, lat, lon FROM poblacion").fetchall()
    if not poblaciones:
        log("  no hay poblaciones: se importan de OpenStreetMap")
        cargar_poblaciones(cn, log)
        poblaciones = cn.execute("SELECT nombre, lat, lon FROM poblacion").fetchall()
    if not poblaciones:
        log("  sin poblaciones: los segmentos se quedan con su numero")
        return 0
    usados: set[str] = set()
    filas = cn.execute("SELECT id, lat_ini, lon_ini, lat_fin, lon_fin, dist_m, nombre_manual "
                       "FROM segmento_minado ORDER BY dist_m DESC").fetchall()
    puestos = 0
    for seg_id, lat_i, lon_i, lat_f, lon_f, dist, manual in filas:
        if manual:
            continue
        a = _pueblo_cerca(poblaciones, lat_i, lon_i)
        b = _pueblo_cerca(poblaciones, lat_f, lon_f)
        if a and b and a[0] != b[0]:
            nombre = f"{a[0]} -> {b[0]}"
        elif a and b:
            nombre = f"Tramo de {a[0]}"
        elif a:
            nombre = f"Desde {a[0]}"
        elif b:
            nombre = f"Hasta {b[0]}"
        else:
            nombre = f"Tramo {seg_id:04d}"
        if nombre in usados:
            nombre = f"{nombre} ({dist / 1000:.2f} km)" if dist else f"{nombre} ({seg_id})"
        if nombre in usados:
            nombre = f"{nombre} ({seg_id})"
        usados.add(nombre)
        cn.execute("UPDATE segmento_minado SET nombre = ? WHERE id = ?", (nombre, seg_id))
        puestos += 1
    cn.commit()
    log(f"  segmentos nombrados: {puestos}")
    return puestos


# --- Resumen para la linea de ordenes -------------------------------------------------------------

def resumen(cn, top: int = 15) -> list[dict]:
    """Los segmentos descubiertos, los mas repetidos primero."""
    filas = cn.execute(
        "SELECT id, nombre, dist_m, desnivel_m, pendiente_pct, n_salidas, n_intentos, primera, ultima "
        "FROM segmento_minado WHERE n_intentos > 0 ORDER BY n_intentos DESC, dist_m DESC LIMIT ?",
        (top,)).fetchall()
    fuera = []
    for r in filas:
        mejor = None
        if r[6]:
            mejor = cn.execute("SELECT MIN(tiempo_s) FROM esfuerzo_minado WHERE segmento_id = ?",
                               (r[0],)).fetchone()[0]
        fuera.append({"id": r[0], "nombre": r[1], "dist_m": r[2], "desnivel_m": r[3],
                      "pendiente_pct": r[4], "n_salidas": r[5], "n_intentos": r[6],
                      "primera": r[7], "ultima": r[8], "mejor_s": mejor})
    return fuera


def historial(cn, referencia: str | int) -> list[dict]:
    """Todos los intentos de un segmento, del mejor al peor (por nombre o por numero)."""
    if isinstance(referencia, int) or str(referencia).isdigit():
        fila = cn.execute("SELECT id, nombre FROM segmento_minado WHERE id = ?",
                          (int(referencia),)).fetchone()
    else:
        fila = cn.execute("SELECT id, nombre FROM segmento_minado WHERE nombre = ? OR nombre LIKE ? "
                          "ORDER BY n_intentos DESC LIMIT 1",
                          (referencia, f"%{referencia}%")).fetchone()
    if not fila:
        return []
    seg_id, nombre = fila
    filas = cn.execute(
        "SELECT e.tiempo_s, e.dist_m, e.vel_media_kmh, e.fecha, e.cobertura, a.nombre, e.actividad_id "
        "FROM esfuerzo_minado e JOIN actividad a ON a.id = e.actividad_id "
        "WHERE e.segmento_id = ? ORDER BY e.tiempo_s", (seg_id,)).fetchall()
    return [{"segmento": nombre, "tiempo_s": r[0], "dist_m": r[1], "vel_kmh": r[2], "fecha": r[3],
             "cobertura": r[4], "salida": r[5], "actividad_id": r[6]} for r in filas]


def minar_todo(cn, disciplina: str = "ciclismo", limite: int | None = None, log=print) -> dict:
    """Las tres fases seguidas: descubrir, nombrar y medir."""
    log("1/3 descubriendo tramos repetidos en las trazas")
    a = minar(cn, disciplina, limite, log)
    log("2/3 poniendo nombres")
    c = nombrar(cn, log)
    log("3/3 midiendo los intentos")
    b = medir(cn, disciplina, limite, log)
    total = dict(a)
    total.update({"nombrados": c, **b})
    total["segundos"] = round(a["segundos"] + b["segundos"], 1)
    return total


if __name__ == "__main__":       # permiso directo para probar: python -m entrenador.segmentos_gpx
    conexion = db.conectar(os.environ.get("ENTRENADOR_BD", "data/entrenador.db"))
    print(minar_todo(conexion))
