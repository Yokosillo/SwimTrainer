#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Marcas de competicion oficiales (RFEN) dentro de la base del Entrenador.

Las marcas no salen del reloj: la federacion las publica en su intranet y se bajan con
`scripts/rfen_historial.py` a `data/competicion/historial_rfen.csv`. Este modulo las mete en la
tabla `competicion` (una fila por marca) y saca los resumenes que usan los informes.

Uso desde consola:
    .venv/Scripts/python.exe -m entrenador.competicion
    .venv/Scripts/python.exe -m entrenador.competicion --estilo libre --distancia 400
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sqlite3
import sys
import unicodedata

from . import db

RUTA_CSV = os.path.join("data", "competicion", "historial_rfen.csv")
CAMPOS_CSV = ["CLUB", "FECHA", "LUGAR", "ESTILO", "DISTANCIA", "CRONO", "PISCINA", "PARCIAL", "RELEVO", "RESULTADO"]


# ---------------------------------------------------------------- lectura del CSV de la federacion

def _plano(texto: str) -> str:
    """minusculas sin acentos (para comparar estilos y cronos)."""
    sin = unicodedata.normalize("NFKD", (texto or "").strip())
    return "".join(c for c in sin if not unicodedata.combining(c)).lower()


def segundos(marca: str) -> float | None:
    """'00:05:00.00' -> 300.0 segundos. None si la marca es imposible.

    En la base de la federacion hay marcas corruptas tipo '00:1394:14.12' (minutos > 59):
    se guardan marcadas como no validas para no ganar ninguna comparacion.
    """
    m = re.match(r"^\s*(\d+):(\d+):(\d+(?:\.\d+)?)\s*$", marca or "")
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    if mi > 59 or s >= 60 or h > 5:
        return None
    return h * 3600 + mi * 60 + s


def _fecha_y_hora(texto: str) -> tuple[str | None, str | None]:
    """'04/05/2019 18:10:00' -> ('2019-05-04', '18:10:00')."""
    t = (texto or "").strip()
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})(?:\s+(\d{1,2}:\d{2}:\d{2}))?$", t)
    if not m:
        return None, None
    return "%s-%s-%s" % (m.group(3), m.group(2), m.group(1)), m.group(4)


def _entero(texto: str) -> int | None:
    m = re.search(r"\d+", str(texto or ""))
    return int(m.group(0)) if m else None


def _normaliza(fila: dict) -> dict:
    """Convierte una fila del CSV en los campos de la tabla `competicion`."""
    fecha, hora = _fecha_y_hora(fila.get("FECHA", ""))
    estilo = _plano(fila.get("ESTILO", "")) or None
    crono = _plano(fila.get("CRONO", "")) or None
    if crono and crono.startswith("electr"):
        crono = "electronico"
    marca = (fila.get("RESULTADO") or "").strip()
    seg = segundos(marca)
    dist = _entero(fila.get("DISTANCIA", ""))
    huella = "|".join((fila.get(c) or "").strip() for c in CAMPOS_CSV)
    return {
        "fuente": "RFEN",
        "clave": hashlib.sha1(huella.encode("utf-8", "replace")).hexdigest(),
        "fecha": fecha,
        "hora": hora,
        "lugar": (fila.get("LUGAR") or "").strip() or None,
        "club": (fila.get("CLUB") or "").strip() or None,
        "estilo": estilo,
        "distancia_m": dist,
        "piscina_m": _entero(fila.get("PISCINA", "")),
        "crono": crono,
        "parcial": (fila.get("PARCIAL") or "").strip() or None,
        "relevo": (fila.get("RELEVO") or "").strip() or None,
        "marca": marca,
        "segundos": seg,
        "ritmo_100": round(seg * 100.0 / dist, 2) if seg and dist else None,
        "valida": 1 if seg else 0,
        "importado_en": db.ahora(),
    }


def importar(cn: sqlite3.Connection, ruta: str = RUTA_CSV) -> dict:
    """Carga (o refresca) el CSV de marcas en la tabla `competicion`. Se puede repetir: no duplica."""
    if not os.path.exists(ruta):
        raise FileNotFoundError(
            "no encuentro %s: bajalo antes con `.venv/Scripts/python.exe scripts/rfen_historial.py`" % ruta)
    with open(ruta, encoding="utf-8-sig", newline="") as fh:
        filas = list(csv.DictReader(fh, delimiter=";"))
    nuevas = actualizadas = invalidas = 0
    for fila in filas:
        reg = _normaliza(fila)
        if cn.execute("SELECT 1 FROM competicion WHERE clave = ?", (reg["clave"],)).fetchone():
            actualizadas += 1
        else:
            nuevas += 1
        if not reg["valida"]:
            invalidas += 1
        cn.execute(
            """INSERT INTO competicion (fuente, clave, fecha, hora, lugar, club, estilo, distancia_m, piscina_m,
                                        crono, parcial, relevo, marca, segundos, ritmo_100, valida, importado_en)
               VALUES (:fuente, :clave, :fecha, :hora, :lugar, :club, :estilo, :distancia_m, :piscina_m,
                       :crono, :parcial, :relevo, :marca, :segundos, :ritmo_100, :valida, :importado_en)
               ON CONFLICT(clave) DO UPDATE SET
                   fecha=excluded.fecha, hora=excluded.hora, lugar=excluded.lugar, club=excluded.club,
                   estilo=excluded.estilo, distancia_m=excluded.distancia_m, piscina_m=excluded.piscina_m,
                   crono=excluded.crono, parcial=excluded.parcial, relevo=excluded.relevo, marca=excluded.marca,
                   segundos=excluded.segundos, ritmo_100=excluded.ritmo_100, valida=excluded.valida,
                   importado_en=excluded.importado_en""", reg)
    cn.execute("INSERT INTO importacion (momento, fuente, ruta, leidos, nuevos, actualizados, omitidos, incidencias)"
               " VALUES (?,?,?,?,?,?,?,?)",
               (db.ahora(), "RFEN", ruta, len(filas), nuevas, actualizadas, 0, invalidas))
    cn.commit()
    tipos = clasificar_y_guardar(cn)
    return {"leidas": len(filas), "nuevas": nuevas, "actualizadas": actualizadas, "invalidas": invalidas,
            "tipos": tipos}


# ----------------------------------------------------------------------------------- consultas

# --- Que fila es una prueba suya y que fila es un paso de otra -------------------------------------------
# Dos datos, y ninguno de los dos vale solo:
#
#   1. El icono PARCIAL de la federacion (S/N) dice si ellos consideran esa fila un tramo de otra prueba.
#      Comprobado en 2019-05-04: 50, 100 y 200 libre vienen con S y el 400 con N -> los tres primeros son
#      los pasos del 400. Y en 2019-03-09 las seis distancias vienen con N -> ese dia nado la escalera de
#      verdad. Usarlo SOLO no vale (una marca suya puede venir con S, y al reves), pero es el punto de
#      partida y ahorra inventarse criterios.
#   2. La SESION COMPLETA (dia + hora), que es la peticion literal del atleta: "junta las marcas de cada dia
#      y examina cuales pueden ser pases... si hay un 400 libres, duda del 50, del 100 y del 200... lo logico
#      es que sea pase, porque si no, habria dos 100s".
#
# Con los dos juntos:
#   - La prueba mas larga de la sesion es SU PRUEBA.
#   - Las cortas de su estilo son sus PASOS si la federacion las da como parcial (S) y no hay otra fila de
#     esa distancia en la sesion. Si hay DOS filas de la misma distancia, una es su marca y la otra el paso
#     ("si no, habria dos 100s"): se queda de marca la individual completa (N), luego el tramo de relevo y,
#     si no hay nada de eso, la MAS RAPIDA (el paso siempre sale mas lento). Y si la federacion la da como
#     completa (N) y es la unica de esa distancia, es su MARCA, aunque ese dia nadara mas largo.
#   - El ESTILO de la prueba larga decide que puede ser paso. Un 400 estilos empieza con 100 de mariposa, asi
#     que un 50 y un 100 mariposa son sus pasos; un 100 espalda, braza o libre de ese mismo dia NO lo son (seria
#     el segundo, tercer o cuarto tramo, y eso la federacion no lo publica como parcial): ese 100 es suyo.
#   - Un parcial sin prueba de su estilo ese dia (un S huerfano) se queda como marca: no hay nada de lo que
#     sea paso, y perder el dato seria peor.
#
# Si la federacion sirvio la misma marca repetida (mismo tiempo y distancia), es un dato repetido del scraping:
# se queda una y la otra va a "rara". Distancia por debajo de 50 m o ritmo imposible = dato roto de origen.
DIST_MINIMA = 50
RITMO_RARO = 130.0


def _sesion(fila: dict) -> tuple:
    """La convocatoria donde se nado la fila: el dia, la hora (si la sirvio), la sede y la piscina."""
    return (fila["fecha"], fila["hora"] or "", fila["lugar"], fila["piscina_m"])


def _puede_ser_paso(prueba: dict, fila: dict) -> bool:
    """¿Esta fila puede ser un paso de esa prueba? La del mismo estilo; y si la prueba es de estilos, la
    mariposa de los dos primeros largos: un 400 estilos empieza con los 100 de mariposa. Un 100 espalda,
    braza o libre de un 400 estilos no es un paso de el."""
    if fila["distancia_m"] >= prueba["distancia_m"]:
        return False
    if fila["estilo"] == prueba["estilo"]:
        return True
    return prueba["estilo"] == "estilos" and fila["estilo"] == "mariposa" and fila["distancia_m"] <= 100


def _preferencia(fila: dict) -> tuple:
    """Orden dentro de un grupo de la misma distancia: primero la prueba individual completa, luego el tramo
    de relevo (se nada a tope, o sea que es suyo) y de ultimo el parcial; a igualdad, la mas rapida."""
    if fila["parcial"] == "N" and fila["relevo"] == "N":
        rango = 0
    elif fila["relevo"] == "S":
        rango = 1
    else:
        rango = 2
    return (rango, fila["segundos"] or 9e9)


def clasificar_sesion(filas: list) -> None:
    """Reparte `tipo` y `motivo` de todas las filas de UNA sesion (las modifica).

    Ademas deja `madre`: si la fila es un pase, el `id` de la prueba de la que es tramo (None en las pruebas
    y en los datos raros). No se guarda en la base: se recalcula al vuelo, como el tipo. Lo usa el portal para
    enseñar los pases de cada prueba y para compararlos entre competiciones.
    """
    for f in filas:
        f["madre"] = None
    # 1. lo que no puede ser marca de nada
    for f in filas:
        if not f["valida"] or f["segundos"] is None or f["ritmo_100"] is None:
            f["tipo"], f["motivo"] = "rara", "la federacion publico el tiempo roto"
        elif f["distancia_m"] < DIST_MINIMA:
            f["tipo"], f["motivo"] = "rara", f"distancia por debajo de {DIST_MINIMA} m (en master no es prueba)"
        elif f["ritmo_100"] > RITMO_RARO:
            f["tipo"], f["motivo"] = "rara", f"ritmo imposible ({f['ritmo_100']:.0f} s/100): dato mal puesto"
        else:
            f["tipo"] = None
    vivas = [f for f in filas if f["tipo"] is None]

    # 2. la misma marca servida dos veces (dato repetido del scraping)
    iguales: dict = {}
    for f in vivas:
        iguales.setdefault((f["estilo"], f["distancia_m"], round(f["segundos"], 2)), []).append(f)
    pendientes = []
    for grupo in iguales.values():
        if len(grupo) == 1:
            pendientes.append(grupo[0])
            continue
        orden = sorted(grupo, key=_preferencia)
        pendientes.append(orden[0])
        for f in orden[1:]:
            f["tipo"], f["motivo"] = "rara", "la federacion sirvio esta misma marca mas de una vez"

    # 3. la prueba mas larga de la sesion manda; las cortas de su estilo son sus pasos
    pendientes.sort(key=lambda f: (-f["distancia_m"], _preferencia(f)))
    while pendientes:
        prueba = pendientes[0]
        prueba["tipo"] = "prueba"
        prueba["motivo"] = f"la prueba mas larga de la sesion ({prueba['distancia_m']} m)"
        resto = pendientes[1:]
        mismas = [f for f in resto if f["estilo"] == prueba["estilo"] and f["distancia_m"] == prueba["distancia_m"]]
        for f in mismas:
            f["tipo"] = "pase"
            f["madre"] = prueba["id"]
            f["motivo"] = f"otra vez los {f['distancia_m']} m de la sesion: se queda la mas rapida como su marca"
        resto = [f for f in resto if f not in mismas]
        pasos = [f for f in resto if _puede_ser_paso(prueba, f)]
        pendientes = [f for f in resto if f not in pasos]
        for distancia in sorted({f["distancia_m"] for f in pasos}, reverse=True):
            del_mismo_largo = sorted([f for f in pasos if f["distancia_m"] == distancia], key=_preferencia)
            if len(del_mismo_largo) > 1:
                marca = del_mismo_largo[0]
                marca["tipo"] = "prueba"
                marca["motivo"] = (f"su marca de {distancia} m: ese dia nadó tambien el "
                                   f"{prueba['distancia_m']} m y de los dos {distancia} m sale uno como marca")
                del_mismo_largo = del_mismo_largo[1:]
            else:
                marca = None
            for f in del_mismo_largo:
                if marca is None and f["parcial"] == "N":
                    f["tipo"] = "prueba"
                    f["motivo"] = (f"la federacion la da como completa (parcial=N) aunque ese dia nadara el "
                                   f"{prueba['distancia_m']} m")
                else:
                    f["tipo"] = "pase"
                    f["madre"] = prueba["id"]
                    f["motivo"] = (f"paso de {distancia} m de la sesion del {prueba['distancia_m']} m "
                                   f"({f['ritmo_100']:.1f} frente a {prueba['ritmo_100']:.1f} s/100)")


def clasificar(cn: sqlite3.Connection) -> list:
    """Todas las filas del historial con su `tipo` y su `motivo` (no escribe en la base)."""
    sesiones: dict = {}
    for f in cn.execute("""SELECT id, fecha, COALESCE(hora,'') AS hora, estilo, distancia_m, piscina_m, marca,
                                  segundos, ritmo_100, COALESCE(parcial,'N') AS parcial,
                                  COALESCE(relevo,'N') AS relevo, lugar, valida
                           FROM competicion ORDER BY fecha"""):
        fila = dict(f)
        sesiones.setdefault(_sesion(fila), []).append(fila)
    salida = []
    for filas in sesiones.values():
        clasificar_sesion(filas)
        salida.extend(filas)
    return salida


def clasificar_y_guardar(cn: sqlite3.Connection) -> dict:
    """Escribe el `tipo` en la tabla (depende del dia, hay que rehacerlo en cada importacion) y lo cuenta."""
    filas = clasificar(cn)
    cn.executemany("UPDATE competicion SET tipo = ?, motivo = ? WHERE id = ?",
                   [(f["tipo"], f["motivo"], f["id"]) for f in filas])
    cn.commit()
    cuenta: dict = {}
    for f in filas:
        cuenta[f["tipo"]] = cuenta.get(f["tipo"], 0) + 1
    return cuenta


SOLO_COMPLETAS = "COALESCE(tipo, 'prueba') = 'prueba'"


def resumen(cn: sqlite3.Connection) -> dict:
    """Cuadro de la tabla `competicion`: volumenes, fechas y competiciones."""
    una = lambda sql, *p: cn.execute(sql, p).fetchone()[0]  # noqa: E731
    total = una("SELECT COUNT(*) FROM competicion")
    if not total:
        return {"total": 0}
    r = cn.execute("SELECT MIN(fecha) a, MAX(fecha) b FROM competicion WHERE fecha IS NOT NULL").fetchone()
    por_estilo = {f["estilo"]: f["n"] for f in cn.execute(
        "SELECT estilo, COUNT(*) n FROM competicion GROUP BY estilo ORDER BY n DESC")}
    return {
        "total": total,
        "validas": una("SELECT COUNT(*) FROM competicion WHERE valida = 1"),
        "invalidas": una("SELECT COUNT(*) FROM competicion WHERE valida = 0"),
        # Pases: filas que estan en el historial pero no son marcas de esa prueba. Se cuentan por `tipo`
        # (calculado mirando el dia entero), no por el icono: `parcial`/`relevo` es el dato crudo de la
        # federacion y se guarda para poder auditar la clasificacion.
        "pases": una("SELECT COUNT(*) FROM competicion WHERE valida = 1 AND tipo = 'pase'"),
        "raras": una("SELECT COUNT(*) FROM competicion WHERE valida = 1 AND tipo = 'rara'"),
        "relevos": una("SELECT COUNT(*) FROM competicion WHERE valida = 1 AND relevo = 'S'"),
        "completas": una("SELECT COUNT(*) FROM competicion WHERE valida = 1 AND " + SOLO_COMPLETAS),
        "desde": r["a"], "hasta": r["b"],
        "competiciones": una("SELECT COUNT(*) FROM (SELECT DISTINCT fecha, lugar FROM competicion)"),
        "pruebas": una("SELECT COUNT(*) FROM (SELECT DISTINCT estilo, distancia_m, piscina_m FROM competicion)"),
        "por_estilo": por_estilo,
    }


def temporada(fecha: str | None) -> str | None:
    """La temporada de natacion: de septiembre a agosto -> '2025/26'.

    La federacion agrupa los resultados asi (la temporada empieza en septiembre) y es mas util que el ano
    natural: un 400 de noviembre y otro de mayo pertenecen al mismo ciclo de preparacion.
    """
    if not fecha or len(fecha) < 7:
        return None
    try:
        anio, mes = int(fecha[:4]), int(fecha[5:7])
    except ValueError:
        return None
    if not 1 <= mes <= 12:
        return None
    inicio = anio if mes >= 9 else anio - 1
    return "%d/%02d" % (inicio, (inicio + 1) % 100)


def mediana(valores: list[float]) -> float | None:
    """Mediana (no la media: una salida mala no debe mandar)."""
    v = sorted(x for x in valores if x)
    if not v:
        return None
    n = len(v)
    return round(v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0, 2)


ORDENES = {
    "fecha": lambda f: (f["fecha"] or "", f["hora"] or ""),
    "marca": lambda f: f["segundos"] or 9e9,
    "distancia": lambda f: (f["distancia_m"] or 0, f["segundos"] or 9e9),
    "ritmo": lambda f: f["ritmo_100"] or 9e9,
}


def historial(cn: sqlite3.Connection, estilo: str | None = None, distancia: int | None = None,
              piscina: int | None = None, temporada_: str | None = None, desde: str | None = None,
              hasta: str | None = None, lugar: str | None = None, solo_validas: bool = True,
              orden: str = "fecha", completas: bool = False) -> list[sqlite3.Row]:
    """Todas las marcas que encajan con el filtro. Los filtros se pueden combinar (es lo que pide el portal).

    `orden`: fecha | marca | distancia | ritmo. `temporada_`: '2025/26'. `lugar`: busca en el lugar y en el club.
    `completas`: deja fuera los pases (tramos de otra prueba del mismo dia) y los datos raros; es lo correcto
    para comparar pruebas. El `tipo` de cada fila lo calcula `clasificar_y_guardar` mirando el dia entero.
    """
    sql = "SELECT * FROM competicion WHERE 1=1"
    p: list = []
    if estilo:
        sql += " AND estilo = ?"
        p.append(_plano(estilo))
    if distancia:
        sql += " AND distancia_m = ?"
        p.append(int(distancia))
    if piscina:
        sql += " AND piscina_m = ?"
        p.append(int(piscina))
    if lugar:
        sql += " AND (lugar LIKE ? OR club LIKE ?)"
        p += ["%%%s%%" % lugar, "%%%s%%" % lugar]
    if desde:
        sql += " AND fecha >= ?"
        p.append(desde)
    if hasta:
        sql += " AND fecha <= ?"
        p.append(hasta)
    if solo_validas:
        sql += " AND valida = 1"
    if completas:
        sql += " AND " + SOLO_COMPLETAS
    filas = [f for f in cn.execute(sql, p)]
    if temporada_:
        filas = [f for f in filas if temporada(f["fecha"]) == temporada_]
    return sorted(filas, key=ORDENES.get(orden, ORDENES["fecha"]))


def _tendencia(filas: list[sqlite3.Row]) -> dict | None:
    """Recta de ritmo (s/100) contra el tiempo, por minimos cuadrados: cuanto cambia al ano.

    Se necesitan al menos 5 marcas para que diga algo; con menos, se devuelve None en vez de un numero
    que parezca preciso. Es una tendencia observada, no una prediccion.
    """
    puntos = []
    for f in filas:
        if not f["fecha"] or not f["ritmo_100"]:
            continue
        try:
            anio = int(f["fecha"][:4]) + (int(f["fecha"][5:7]) - 1) / 12.0
        except ValueError:
            continue
        puntos.append((anio, f["ritmo_100"]))
    if len(puntos) < 5:
        return None
    n = len(puntos)
    mx = sum(x for x, _ in puntos) / n
    my = sum(y for _, y in puntos) / n
    den = sum((x - mx) ** 2 for x, _ in puntos)
    if not den:
        return None
    pendiente = sum((x - mx) * (y - my) for x, y in puntos) / den
    return {
        "pendiente_s_por_ano": round(pendiente, 2),
        "n": n,
        "desde": min(p[0] for p in puntos),
        "hasta": max(p[0] for p in puntos),
        "lectura": ("mejorando" if pendiente < -0.3 else
                    "empeorando" if pendiente > 0.3 else "estable"),
    }


def comparar(cn: sqlite3.Connection, estilo: str = "libre", distancia: int = 400,
             piscina: int | None = None) -> dict:
    """Compara la misma prueba temporada a temporada: mejor marca, diferencia absoluta y porcentual, tendencia.

    Ojo con la piscina: 25 y 50 m NO son equivalentes, asi que si no se fija una, cada temporada se compara
    dentro de su propia piscina y se avisa. Las diferencias son siempre de marcas oficiales de la misma prueba.
    """
    filas = historial(cn, estilo, distancia, piscina, orden="fecha", completas=True)
    base = {"estilo": _plano(estilo), "distancia_m": int(distancia), "piscina_m": piscina,
            "n": len(filas), "por_temporada": [], "tendencia": None, "mejor": None,
            "aviso_piscina": ("Se estan mezclando piscinas de 25 y 50 m: no son equivalentes. Fija una "
                              "piscina para comparar de verdad." if not piscina and
                              len({f["piscina_m"] for f in filas}) > 1 else None)}
    if not filas:
        return base
    mejor = min(filas, key=lambda f: f["segundos"])
    base["mejor"] = {"marca": mejor["marca"], "segundos": mejor["segundos"], "fecha": mejor["fecha"],
                     "lugar": mejor["lugar"], "piscina_m": mejor["piscina_m"], "ritmo_100": mejor["ritmo_100"]}
    grupos: dict[str, list] = {}
    for f in filas:
        grupos.setdefault(temporada(f["fecha"]) or "sin fecha", []).append(f)
    for t in sorted(grupos):
        g = grupos[t]
        m = min(g, key=lambda f: f["segundos"])
        anterior = base["por_temporada"][-1] if base["por_temporada"] else None
        d_abs = round(m["segundos"] - anterior["mejor_s"], 2) if anterior else None
        base["por_temporada"].append({
            "temporada": t, "n": len(g),
            "mejor_s": m["segundos"], "marca": m["marca"], "ritmo_100": m["ritmo_100"],
            "fecha": m["fecha"], "lugar": m["lugar"], "piscina_m": m["piscina_m"],
            "mediana_s": mediana([f["segundos"] for f in g]),
            "vs_anterior_s": d_abs,
            "vs_anterior_pct": round(100.0 * d_abs / anterior["mejor_s"], 2) if anterior and d_abs else None,
            "vs_mejor_s": round(m["segundos"] - mejor["segundos"], 2),
            "vs_mejor_pct": round(100.0 * (m["segundos"] - mejor["segundos"]) / mejor["segundos"], 2),
        })
    base["tendencia"] = _tendencia(filas)
    return base


def progreso(cn: sqlite3.Connection, estilo: str = "libre", distancia: int = 400,
             piscina: int | None = None, objetivo_s: float | None = None,
             ritmo_objetivo: float | None = None) -> dict:
    """Cuanto le falta (o le sobra) a la mejor marca oficial de una prueba para la marca objetivo del plan.

    Si no se le pasa la marca objetivo, la toma del plan (`entrenador/plan.py`). Devuelve None en los campos
    de objetivo cuando no hay ninguno definido para esa prueba: asi nadie compara contra algo que no existe.
    """
    from . import plan as _plan
    obj = _plan.objetivo_de(_plano(estilo), distancia, piscina) if objetivo_s is None else None
    if objetivo_s is None and obj:
        objetivo_s = obj.get("marca_objetivo_s")
        ritmo_objetivo = ritmo_objetivo or obj.get("ritmo_objetivo_100")
    filas = historial(cn, estilo, distancia, piscina, orden="marca")
    if not filas:
        return {"hay_marcas": False, "objetivo_s": objetivo_s, "objetivo_nombre": (obj or {}).get("nombre")}
    m = filas[0]
    d = round(m["segundos"] - objetivo_s, 2) if objetivo_s else None
    dr = round(m["ritmo_100"] - ritmo_objetivo, 2) if (ritmo_objetivo and m["ritmo_100"]) else None
    estado = None
    if d is not None:
        estado = ("por debajo del objetivo" if d <= 0 else
                  "al filo (menos del 1 %)" if d <= 0.01 * objetivo_s else "por encima")
    return {
        "hay_marcas": True,
        "objetivo_s": objetivo_s, "ritmo_objetivo_100": ritmo_objetivo,
        "objetivo_nombre": (obj or {}).get("nombre"), "objetivo_fecha": (obj or {}).get("fecha"),
        "mejor_s": m["segundos"], "mejor_marca": m["marca"], "mejor_fecha": m["fecha"],
        "mejor_lugar": m["lugar"], "piscina_m": m["piscina_m"], "ritmo_100": m["ritmo_100"],
        "diferencia_s": d, "diferencia_pct": (round(100.0 * d / objetivo_s, 2) if objetivo_s and d is not None else None),
        "diferencia_ritmo_100": dr, "estado": estado,
        # Lo que no se puede decir todavia, dicho claro (el plan lo pide expresamente).
        "sin_datos": ("La comparacion es entre marcas oficiales de la misma prueba y piscina. Si son de "
                      "piscinas distintas (25 y 50 m), la diferencia NO es equivalente sin conversion."),
    }


def mejores(cn: sqlite3.Connection, estilo: str = "libre") -> list[sqlite3.Row]:
    """La mejor marca valida de cada distancia y piscina de un estilo (solo pruebas completas)."""
    cond = SOLO_COMPLETAS
    return list(cn.execute(
        """SELECT c.* FROM competicion c
           JOIN (SELECT distancia_m, piscina_m, MIN(segundos) s FROM competicion
                 WHERE valida = 1 AND estilo = ? AND """ + cond + """ GROUP BY distancia_m, piscina_m) m
             ON m.distancia_m = c.distancia_m AND m.piscina_m = c.piscina_m AND m.s = c.segundos
           WHERE c.valida = 1 AND c.estilo = ? AND """ + cond + """
           ORDER BY c.distancia_m, c.piscina_m""", (_plano(estilo), _plano(estilo))))


# ------------------------------------------------------------------------------------- consola

def _crono(v: float | None) -> str:
    if not v:
        return "-"
    h, resto = divmod(v, 3600)
    m, s = divmod(resto, 60)
    return ("%d:%02d:%05.2f" % (h, m, s)) if h else ("%d:%05.2f" % (m, s))


def _tabla_temporadas(cn: sqlite3.Connection, estilo: str, distancia: int, piscina: int | None) -> None:
    """El cuadro temporada a temporada de una prueba, con la tendencia observada."""
    c = comparar(cn, estilo, distancia, piscina)
    if not c["n"]:
        print("\nNo hay marcas de %s %s m." % (estilo, distancia))
        return
    print("\n%s %d m%s, temporada a temporada (marcas oficiales, todas de la misma prueba):"
          % (estilo, distancia, (", piscina %d m" % piscina) if piscina else ""))
    print("  %-9s %4s %-12s %8s %9s %10s %9s" %
          ("temporada", "n", "mejor marca", "s/100", "vs ant.", "vs ant. %", "vs mejor"))
    for t in c["por_temporada"]:
        print("  %-9s %4d %-12s %8.1f %9s %10s %8.1f s"
              % (t["temporada"], t["n"], t["marca"], t["ritmo_100"] or 0,
                 ("%+.2f s" % t["vs_anterior_s"]) if t["vs_anterior_s"] is not None else "-",
                 ("%+.2f %%" % t["vs_anterior_pct"]) if t["vs_anterior_pct"] is not None else "-",
                 t["vs_mejor_s"] or 0))
    m = c["mejor"]
    print("  Mejor de siempre: %s (%s, %s, %s)" % (m["marca"], m["fecha"], m["piscina_m"], m["lugar"]))
    if c["tendencia"]:
        t = c["tendencia"]
        print("  Tendencia (%d marcas, de %.0f a %.0f): %+.2f s/100 por ano -> %s"
              % (t["n"], t["desde"], t["hasta"], t["pendiente_s_por_ano"], t["lectura"]))
    else:
        print("  Tendencia: con menos de 5 marcas no se calcula (no se inventa).")
    if c["aviso_piscina"]:
        print("  OJO: %s" % c["aviso_piscina"])
    p = progreso(cn, estilo, distancia, piscina)
    if p.get("objetivo_s") and p.get("hay_marcas"):
        print("  Objetivo del plan (%s, %s): %s -> le faltan %+.2f s (%+.2f %%), %s"
              % (p["objetivo_nombre"], p["objetivo_fecha"], _crono(p["objetivo_s"]),
                 p["diferencia_s"], p["diferencia_pct"], p["estado"]))
        print("  Ritmo: mejor %s s/100 frente al objetivo %s s/100 (%+.2f s/100)"
              % ("%.1f" % p["ritmo_100"], "%.1f" % p["ritmo_objetivo_100"], p["diferencia_ritmo_100"] or 0))


def mostrar(cn: sqlite3.Connection, estilo: str | None = None, distancia: int | None = None,
            piscina: int | None = None, temporada_: str | None = None, desde: str | None = None,
            hasta: str | None = None, lugar: str | None = None, orden: str = "fecha",
            comparar_: bool = False) -> None:
    """Imprime el resumen y, si se pide, el historial completo de una prueba (con comparativa si se pide)."""
    r = resumen(cn)
    if not r["total"]:
        print("No hay marcas de competicion en la base. Carga primero `entrenador competicion`.")
        return
    print("Marcas de competicion: %d (%d validas, %d corruptas en origen) | %s a %s"
          % (r["total"], r["validas"], r["invalidas"], r["desde"], r["hasta"]))
    print("%d competiciones, %d pruebas distintas | por estilo: %s"
          % (r["competiciones"], r["pruebas"], ", ".join("%s %d" % (k, v) for k, v in r["por_estilo"].items())))

    if comparar_ and estilo and distancia:
        _tabla_temporadas(cn, estilo, distancia, piscina)

    if estilo or comparar_:
        filas = historial(cn, estilo, distancia, piscina, temporada_, desde, hasta, lugar, orden=orden)
        titulo = " ".join(x for x in [estilo or "todas", ("%d m" % distancia) if distancia else None,
                                      ("piscina %d m" % piscina) if piscina else None,
                                      ("temporada %s" % temporada_) if temporada_ else None,
                                      ("lugar %s" % lugar) if lugar else None] if x)
        print("\n%s: %d marcas (orden: %s)" % (titulo, len(filas), orden))
        p = progreso(cn, estilo or "libre", distancia, piscina) if distancia else {}
        obj = p.get("objetivo_s")
        print("  %-10s %-24s %-5s %-12s %8s %-9s %12s %s" %
              ("fecha", "lugar", "pisc.", "marca", "s/100", "temporada", "vs objetivo", "que es"))
        for f in filas:
            fila_obj = "-"
            if obj and f["segundos"]:
                d = f["segundos"] - obj
                fila_obj = "%+.2f s %s" % (d, "OK" if d <= 0 else "")
            que = {"pase": "PASE (tramo de otra prueba)", "rara": "RARA (revisar)"}.get(f["tipo"], "")
            print("  %-10s %-24s %-5s %-12s %8s %-9s %12s %s"
                  % (f["fecha"], (f["lugar"] or "")[:24],
                     ("%dm" % f["piscina_m"]) if f["piscina_m"] else "?",
                     f["marca"], ("%.1f" % f["ritmo_100"]) if f["ritmo_100"] else "no valida",
                     temporada(f["fecha"]) or "-", fila_obj, que))
        if obj:
            print("  (objetivo del plan: %s)" % _crono(obj))
        return

    print("\nMejores marcas oficiales (libre):")
    print("  %-8s %-7s %-12s %-10s %-24s %8s" % ("dist.", "pisc.", "marca", "fecha", "lugar", "s/100"))
    for f in mejores(cn, "libre"):
        print("  %-8s %-7s %-12s %-10s %-24s %8s"
              % ("%d m" % f["distancia_m"], "%d m" % f["piscina_m"], f["marca"], f["fecha"],
                 (f["lugar"] or "")[:24], "%.1f" % f["ritmo_100"]))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="entrenador.competicion", description="Marcas oficiales de la RFEN.")
    p.add_argument("--bd", default=db.RUTA_POR_DEFECTO)
    p.add_argument("--csv", default=RUTA_CSV, help="CSV bajado con scripts/rfen_historial.py")
    p.add_argument("--sin-importar", action="store_true", help="solo consultar lo que ya hay en la base")
    p.add_argument("--estilo", help="libre | espalda | braza | mariposa | estilos")
    p.add_argument("--distancia", type=int, help="filtra por distancia (400, 1500, 3000...)")
    p.add_argument("--piscina", type=int, choices=(25, 50), help="25 o 50 m (no son equivalentes)")
    p.add_argument("--temporada", help="'2025/26' (de septiembre a agosto)")
    p.add_argument("--desde", help="fecha minima (YYYY-MM-DD)")
    p.add_argument("--hasta", help="fecha maxima (YYYY-MM-DD)")
    p.add_argument("--lugar", help="busca en el lugar y en el club")
    p.add_argument("--orden", default="fecha", choices=tuple(ORDENES), help="fecha | marca | distancia | ritmo")
    p.add_argument("--comparar", action="store_true", help="cuadro temporada a temporada y tendencia")
    a = p.parse_args(argv)

    cn = db.conectar(a.bd)
    if not a.sin_importar:
        r = importar(cn, a.csv)
        print("CSV %s: %d filas (nuevas %d, actualizadas %d, no validas %d)"
              % (a.csv, r["leidas"], r["nuevas"], r["actualizadas"], r["invalidas"]))
    mostrar(cn, a.estilo, a.distancia, a.piscina, a.temporada, a.desde, a.hasta, a.lugar, a.orden, a.comparar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
