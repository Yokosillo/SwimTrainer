"""Las pruebas de medicion: los bloques que el atleta marca para compararse consigo mismo en el tiempo.

Una prueba es **un bloque**, no la sesion entera: el 1.500 de un entrenamiento, un 400 suelto, una serie de
100 (10x100), una escalera... Y la marca es suya: el sistema no la deduce de nada, la guarda donde le dice
(`parte_serie.prueba`), igual que el material o la intensidad.

Lo que se puede comparar entre epocas es poco, y hay que elegirlo bien:

- **Los metros**, porque un 10x100 no se mide contra un 1.500: por eso la comparacion va por nombre *y* metros.
- **El tiempo de la serie**, sin los descansos: los descansos los cambia el y no dicen nada de su natacion.
- **El ritmo de cada cien**, que es lo unico que aguanta el paso del tiempo (los segundos del reloj no: ese
  mismo 1.500 lo nada hoy en una piscina y en enero en otra).

Asi que de cada prueba se guarda el ritmo de cada cien y el tiempo, y el historial se enseña por ano: es la
unica forma de responder a la pregunta del atleta, que es "como voy respecto a otras epocas".
"""

from __future__ import annotations

import re
import sqlite3

# Los nombres que se le ofrecen en el portal (una ayuda para no escribir, no una jaula: puede marcar el bloque
# como quiera y su nombre se le anade a la lista).
TIPOS = ("1500", "escalera", "30 minutos", "series de 100 cada 1:30")
LARGO_NOMBRE = 28

# Que es "mejor" en cada prueba: lo dice el atleta, y no es lo mismo en todas.
#   - El 1.500: **tiempo total** (es la distancia, y el crono es la marca).
#   - La escalera: **ritmo de cada cien** (el total depende de la escalera de ese dia, que cambia).
#   - La serie de 100 cada 1:30: **ritmo medio** (lo que se compara es a como lo nadas, no cuanto duras).
#   - Los 30 minutos: **metros** (el tiempo es siempre el mismo: lo que cambia es lo que avanzas).
MEDIDA_POR_DEFECTO = "ritmo"
MEDIDAS = {
    "1500": "tiempo",
    "escalera": "ritmo",
    "series de 100 cada 1:30": "ritmo",
    "30 minutos": "metros",
}
ETIQUETA_MEDIDA = {"tiempo": "tiempo total", "ritmo": "ritmo de cada cien", "metros": "metros en 30:00"}


def medida_de(nombre) -> str:
    """Con que se mide una prueba. Lo que no esta declarado va por ritmo, que es lo unico que aguanta los anos."""
    if not nombre:
        return MEDIDA_POR_DEFECTO
    return MEDIDAS.get(str(nombre).strip().lower(), MEDIDA_POR_DEFECTO)


# Las pruebas de tiempo fijo: el reloj marca unos segundos de mas (hasta que el atleta lo para), asi que los metros
# no son los de los 30:00 exactos. Se ajustan al tiempo exacto con el ritmo de la propia prueba: es la misma cuenta
# del ritmo de cada cien mirada al reves, y es lo unico comparable de una vez a otra (el atleta lo pidio asi).
SEGUNDOS_FIJOS = {"30 minutos": 1800.0}


def segundos_de(nombre) -> float | None:
    """Los segundos exactos de una prueba de tiempo fijo (30 minutos -> 1800). None si no lo es."""
    if not nombre:
        return None
    return SEGUNDOS_FIJOS.get(str(nombre).strip().lower())


def valor_de(e, nombre) -> float | None:
    """El numero con el que se compara una marca, en su unidad: los metros ajustados al tiempo exacto (los 30:00
    de la prueba de 30 minutos), el tiempo total o el ritmo de cada cien. En la unidad que sea, menos es mejor."""
    medida = medida_de(nombre)
    if medida == "tiempo":
        return e.get("tiempo_s")
    if medida == "metros":
        segundos = segundos_de(nombre)
        if segundos and e.get("ritmo_100"):
            return round(float(segundos) * 100.0 / float(e["ritmo_100"]), 1)
        return e.get("metros")
    return e.get("ritmo_100")


def _orden(nombre):
    """Como se ordenan las marcas de una prueba: en tiempo y en ritmo gana el mas bajo; en metros, el mas alto (y a
    igualdad de metros, el mejor ritmo). Las que no tienen dato se van al final."""
    if medida_de(nombre) == "metros":
        return lambda e: (-(valor_de(e, nombre) or 0), valor_de(e, nombre) is None, e.get("ritmo_100") or 1e9)
    return lambda e: (valor_de(e, nombre) if valor_de(e, nombre) is not None else 1e9, e.get("ritmo_100") or 1e9)


def limpiar(x) -> str | None:
    """El nombre de una prueba, tal como lo escribio el atleta: en una linea, sin espacios de sobra.

    Vacio (o solo espacios) significa "este bloque no es prueba": devuelve None, que en la base es NULL.
    """
    if x is None:
        return None
    t = re.sub(r"\s+", " ", str(x))
    t = "".join(c for c in t if c.isprintable()).strip()
    return t[:LARGO_NOMBRE] or None


def catalogo(cn: sqlite3.Connection) -> list[str]:
    """Los nombres de prueba que se le ofrecen en el portal: primero los de la casa y luego los suyos."""
    usados: list[str] = []
    for f in cn.execute("SELECT DISTINCT prueba FROM parte_serie"
                        " WHERE prueba IS NOT NULL AND TRIM(prueba) <> ''"):
        nombre = limpiar(f[0])
        if nombre and nombre not in TIPOS and nombre.lower() not in [u.lower() for u in usados]:
            usados.append(nombre)
    return list(TIPOS) + sorted(usados, key=str.lower)


def _ritmo(f) -> float | None:
    """El ritmo de cada cien del bloque: el suyo si esta guardado y, si no, el que salga de metros y tiempo."""
    if f["ritmo_100"]:
        return round(float(f["ritmo_100"]), 1)
    metros, tiempo = f["metros"], f["tiempo_s"]
    if metros and tiempo:
        return round(100.0 * float(tiempo) / float(metros), 1)
    return None


def historico(cn: sqlite3.Connection) -> list[dict]:
    """Las pruebas marcadas, agrupadas por nombre y metros, con su evolucion (por ano y bloque a bloque).

    Cada entrada lleva la ultima vez, la anterior, la mejor y la lista entera: con eso el portal puede decir
    "vas mejor o peor que la ultima vez" y "como estabas cada ano" sin inventarse nada.
    """
    filas = cn.execute(
        """SELECT p.fecha, p.actividad_id, s.orden, s.tipo, s.metros, s.tiempo_s, s.ritmo_100, s.n_reps, s.rep_m,
                  s.prueba
             FROM parte_serie s JOIN parte p ON p.id = s.parte_id
            WHERE s.prueba IS NOT NULL AND TRIM(s.prueba) <> ''
            ORDER BY p.fecha, s.orden""").fetchall()
    cajas: dict[tuple[str, int], dict] = {}
    for f in filas:
        nombre = limpiar(f["prueba"])
        if not nombre:
            continue
        metros = int(round(float(f["metros"] or 0)))
        entrada = {
            "fecha": f["fecha"], "actividad_id": f["actividad_id"], "orden": f["orden"], "tipo": f["tipo"],
            "metros": metros, "tiempo_s": round(float(f["tiempo_s"]), 2) if f["tiempo_s"] else None,
            "ritmo_100": _ritmo(f), "n_reps": f["n_reps"], "rep_m": f["rep_m"],
        }
        # Las pruebas de tiempo fijo (los 30 minutos) NO se parten por metros: los metros son **la medida**, no la
        # distancia de la prueba, asi que todas sus veces son la misma prueba. Lo demas (un 10x100, un 1.500) si se
        # separa por metros: no se compara una cosa con otra.
        clave_metros = 0 if segundos_de(nombre) else metros
        entrada["valor"] = valor_de(entrada, nombre)
        caja = cajas.setdefault((nombre, clave_metros), {"todas": [], "anos": {}})
        caja["todas"].append(entrada)
        if entrada["ritmo_100"]:
            ano = (entrada["fecha"] or "")[:4] or "sin fecha"
            caja["anos"].setdefault(ano, []).append(entrada["ritmo_100"])

    salida = []
    for (nombre, clave_metros), caja in sorted(cajas.items(), key=lambda x: (x[0][0].lower(), -x[0][1])):
        todas = caja["todas"]
        medida = medida_de(nombre)
        ultima, antes = todas[-1], (todas[-2] if len(todas) > 1 else None)
        # El "mejor" no es lo mismo en todas: manda la medida que el atleta declaro para esa prueba.
        mejores = sorted([e for e in todas if valor_de(e, nombre) is not None], key=_orden(nombre))[:3]
        mejor = mejores[0] if mejores else None
        delta = None
        if ultima["ritmo_100"] and antes and antes["ritmo_100"]:
            delta = round(ultima["ritmo_100"] - antes["ritmo_100"], 1)
        salida.append({
            "nombre": nombre, "metros": clave_metros, "veces": len(todas),
            "medida": medida, "etiqueta_medida": ETIQUETA_MEDIDA.get(medida, medida),
            "ultima": ultima, "antes": antes, "mejor": mejor, "mejores": mejores, "delta_ultima_s": delta,
            "por_ano": [{"ano": ano, "veces": len(r), "mejor_ritmo": min(r),
                         "media_ritmo": round(sum(r) / len(r), 1)}
                        for ano, r in sorted(caja["anos"].items())],
            "todas": todas,
        })
    return salida


def resumen(cn: sqlite3.Connection, cuantos: int = 3) -> list[dict]:
    """Los mejores de cada prueba, para la pagina resumen: el atleta pidio los tres mejores de cada una.

    Salen las cuatro pruebas declaradas aunque todavia no tenga ninguna marcada (asi ve cual le falta) y cada una
    con su medida, que es lo que dice que es "mejor" y con que se compara.
    """
    por_nombre = {h["nombre"].strip().lower(): h for h in historico(cn)}
    salida = []
    for tipo in TIPOS:
        h = por_nombre.get(tipo.lower())
        medida = medida_de(tipo)
        salida.append({
            "nombre": tipo, "medida": medida, "etiqueta_medida": ETIQUETA_MEDIDA.get(medida, medida),
            "veces": (h or {}).get("veces", 0),
            "mejores": ((h or {}).get("mejores") or [])[:cuantos],
            "por_ano": (h or {}).get("por_ano") or [],
        })
    return salida
