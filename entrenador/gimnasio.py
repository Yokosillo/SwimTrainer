"""El gimnasio: su plantilla de ejercicios y lo que va levantando.

El reloj no sabe nada de esto (no ve series, ni kilos, ni maquinas): lo apunta el atleta. La plantilla es **suya**,
con sus palabras para que reconozca la maquina alli mismo; de cada sesion se guarda lo que dicta la plantilla —
series, repeticiones y kilos — y nada mas. Todo lo que se apunta se puede corregir volviendo a apuntar ese dia: la
sesion de una fecha es una sola y manda lo ultimo que dice el atleta.
"""
from __future__ import annotations

import json
from datetime import date
import sqlite3

from . import db

# La plantilla de la casa, con las palabras del atleta (18/10/2026). `como` es para que reconozca la maquina en el
# gimnasio; el nombre corto es el que sale en el portal. El orden es el de una sesion suya normal.
PLANTILLA = (
    {"nombre": "core", "grupo": "core", "como": "core, en el suelo"},
    {"nombre": "lumbares", "grupo": "lumbares", "como": "lumbares"},
    {"nombre": "triceps en polea (cuerdas)", "grupo": "triceps",
     "como": "la maquina que es como un poste, con cuerdas: tiro hacia abajo"},
    {"nombre": "press banca", "grupo": "pecho", "como": "tumbado en el banco, levanto una barra con el pecho"},
    {"nombre": "press inclinado", "grupo": "pecho", "como": "igual pero con el banco inclinado"},
    {"nombre": "press hombros (maquina)", "grupo": "hombro", "como": "la maquina de hombros"},
    {"nombre": "curl biceps (polea)", "grupo": "biceps", "como": "el jalon de biceps de la maquina"},
    {"nombre": "gemelos (maquina)", "grupo": "gemelos",
     "como": "apoyas el peso sobre los hombros y levantas los talones"},
)

# Sin kilos (core, lumbares) el volumen no se puede sumar: se deja en None y se dice tal cual, no se inventa un cero.
UNIDAD = "kg"


def _texto(v) -> str:
    return (v or "").strip() if isinstance(v, str) else ("" if v is None else str(v).strip())


def _entero(v):
    """Un numero entero, o None. Acepta '12', 12.0 y '12 reps'."""
    if v is None or v == "":
        return None
    try:
        return int(round(float(str(v).replace(",", ".").replace(" ", "").split("x")[0])))
    except (TypeError, ValueError):
        return None


def _kilos(v):
    """Los kilos, o None si no los hay (no hay cero: cero no es un peso)."""
    if v is None or v == "":
        return None
    try:
        n = float(str(v).replace(",", ".").replace(" ", "").replace("kg", ""))
    except (TypeError, ValueError):
        return None
    return round(n, 1) if n > 0 else None


def sembrar(cn: sqlite3.Connection) -> int:
    """Mete en el catalogo los ejercicios de la plantilla que falten. Idempotente: no pisa los que ya estan (si el
    atleta les cambio el nombre o el orden, se respeta lo suyo)."""
    nuevos = 0
    for i, e in enumerate(PLANTILLA):
        cur = cn.execute(
            """INSERT INTO gimnasio_ejercicio (nombre, grupo, como, orden, activo, creado_en)
               VALUES (?,?,?,?,1,?) ON CONFLICT(nombre) DO NOTHING""",
            (e["nombre"], e.get("grupo"), e.get("como"), i * 10, db.ahora()))
        nuevos += cur.rowcount if cur.rowcount > 0 else 0
    cn.commit()
    return nuevos


def catalogo(cn: sqlite3.Connection) -> list[dict]:
    """Los ejercicios de su plantilla, en su orden."""
    return [dict(r) for r in cn.execute(
        "SELECT id, nombre, grupo, como, orden FROM gimnasio_ejercicio WHERE activo = 1"
        " ORDER BY orden, nombre")]


def _sesion_de(cn: sqlite3.Connection, fecha: str) -> dict | None:
    """La sesion apuntada de ese dia (o None)."""
    fila = cn.execute("SELECT * FROM gimnasio_sesion WHERE clave = ?", ("portal|" + fecha,)).fetchone()
    return dict(fila) if fila else None


def _ejercicios_de(fila: dict | None) -> list[dict]:
    if not fila:
        return []
    try:
        datos = json.loads(fila.get("ejercicios") or "[]")
    except ValueError:
        return []
    return [d for d in datos if isinstance(d, dict)]


def apuntar(cn: sqlite3.Connection, fecha: str, filas: list[dict], notas: str = "") -> dict:
    """Apunta lo que ha hecho un dia: una fila por ejercicio con sus series, repeticiones, kilos y RPE.

    El RPE (1-10, lo duro que le parecio) es opcional: sin el, la sesion cuenta igual pero no se puede decir si fue
    intensa. `notas` vale para lo que hay que decir del dia (por ejemplo, una molestia: eso manda parar).

    Se puede apuntar el dia entero de una vez o ir ampliandolo: lo que llega se **funde** con lo que ya habia de ese
    dia (por nombre de ejercicio, sin distinguir mayusculas) y lo que no llega se queda como estaba. Un ejercicio que
    no este en la plantilla se anade al catalogo: la plantilla crece con lo que hace, no al reves.
    """
    fecha = _texto(fecha)[:10]
    if not fecha:
        raise ValueError("Sin fecha no se puede apuntar la sesion.")
    limpio = []
    for f in filas or []:
        if not isinstance(f, dict):
            continue
        nombre = _texto(f.get("ejercicio") or f.get("nombre"))
        if not nombre:
            continue
        series, reps, kg = _entero(f.get("series")), _entero(f.get("reps")), _kilos(f.get("kg") or f.get("peso"))
        rpe = _entero(f.get("rpe") or f.get("esfuerzo") or f.get("duro"))
        if rpe is not None:
            rpe = max(1, min(10, rpe))    # el RPE es 1-10: lo que salga de ahi es un error de dedo, no un dato
        if series is None and reps is None and kg is None and rpe is None:
            continue              # una fila vacia no es una serie: no se apunta nada
        limpio.append({"ejercicio": nombre, "series": series, "reps": reps, "kg": kg, "rpe": rpe,
                       "nota": _texto(f.get("nota"))})
    if not limpio:
        raise ValueError("No hay nada que apuntar: hace falta al menos un ejercicio con sus series o sus kilos.")

    ya = {d["ejercicio"].lower(): d for d in _ejercicios_de(_sesion_de(cn, fecha))}
    for f in limpio:
        ya[f["ejercicio"].lower()] = f          # lo nuevo manda sobre lo que ya estaba de ese ejercicio
        if not cn.execute("SELECT 1 FROM gimnasio_ejercicio WHERE lower(nombre) = lower(?)",
                          (f["ejercicio"],)).fetchone():
            n = cn.execute("SELECT COALESCE(MAX(orden), 0) + 10 FROM gimnasio_ejercicio").fetchone()[0]
            cn.execute("""INSERT INTO gimnasio_ejercicio (nombre, grupo, como, orden, activo, creado_en)
                          VALUES (?,?,?,?,1,?)""", (f["ejercicio"], None, "anadido desde el portal", n, db.ahora()))
    hechos = list(ya.values())
    series = sum(x["series"] or 0 for x in hechos)
    reps = sum((x["series"] or 0) * (x["reps"] or 0) for x in hechos)
    volumen = round(sum((x["series"] or 0) * (x["reps"] or 0) * (x["kg"] or 0) for x in hechos), 1)
    con_peso = any(x["kg"] for x in hechos)
    cn.execute(
        """INSERT INTO gimnasio_sesion (clave, fecha, ejercicios, series, repeticiones, volumen_kg, notas, importado_en)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(clave) DO UPDATE SET
               fecha = excluded.fecha, ejercicios = excluded.ejercicios, series = excluded.series,
               repeticiones = excluded.repeticiones, volumen_kg = excluded.volumen_kg,
               notas = excluded.notas, importado_en = excluded.importado_en""",
        ("portal|" + fecha, fecha, json.dumps(hechos, ensure_ascii=False), series, reps,
         volumen if con_peso else None, _texto(notas), db.ahora()))
    cn.commit()
    return {"fecha": fecha, "ejercicios": hechos, "series": series, "repeticiones": reps,
            "volumen_kg": volumen if con_peso else None}


def ultimo_de(cn: sqlite3.Connection, ejercicio: str) -> dict | None:
    """La ultima vez que hizo ese ejercicio y como le fue (para no empezar a ciegas la proxima)."""
    filas = cn.execute("SELECT fecha, ejercicios FROM gimnasio_sesion ORDER BY fecha DESC, id DESC").fetchall()
    for f in filas:
        for d in _ejercicios_de(dict(f)):
            if _texto(d.get("ejercicio")).lower() == _texto(ejercicio).lower():
                return {"fecha": f["fecha"], **d}
    return None


def historial(cn: sqlite3.Connection, ejercicio: str | None = None, limite: int = 12) -> list[dict]:
    """Lo apuntado, lo mas nuevo primero. Con `ejercicio`, solo ese (y con su mejor dia)."""
    salida = []
    for f in cn.execute("SELECT fecha, ejercicios, volumen_kg FROM gimnasio_sesion"
                        " ORDER BY fecha DESC, id DESC LIMIT ?", (limite,)):
        filas = _ejercicios_de(dict(f))
        if ejercicio:
            filas = [d for d in filas if _texto(d.get("ejercicio")).lower() == _texto(ejercicio).lower()]
            if not filas:
                continue
        salida.append({"fecha": f["fecha"], "volumen_kg": f["volumen_kg"], "ejercicios": filas})
    return salida


DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


def dia_de(fecha: str) -> str:
    """El nombre del dia de esa fecha, o cadena vacia si la fecha no se puede leer."""
    try:
        return DIAS[date.fromisoformat((fecha or "")[:10]).weekday()]
    except ValueError:
        return ""


def carga_semanal(cn: sqlite3.Connection, desde: str | None = None, hasta: str | None = None) -> dict:
    """Lo que ha cargado el gimnasio en un tramo: sesiones, series, repeticiones, kilos y por ejercicio (V1.4-01).

    Una sesion a peso corporal (sin kilos) cuenta en ejercicios y series, pero **no** suma volumen: cero no es un
    peso y no se inventa. El RPE es opcional; sin el, la sesion cuenta igual, solo que no se sabe si fue intensa.
    """
    desde = (desde or "0000-01-01")[:10]
    hasta = (hasta or "9999-12-31")[:10]
    filas = cn.execute("SELECT fecha, ejercicios, series, repeticiones, volumen_kg, notas FROM gimnasio_sesion"
                       " WHERE fecha >= ? AND fecha <= ? ORDER BY fecha", (desde, hasta)).fetchall()
    por_ejercicio: dict[str, dict] = {}
    por_dia: list[dict] = []
    for f in filas:
        detalle = _ejercicios_de(dict(f))
        dia = {"fecha": f["fecha"], "dia": dia_de(f["fecha"]), "sesiones": 1,
               "series": f["series"] or 0, "repeticiones": f["repeticiones"] or 0,
               "volumen_kg": f["volumen_kg"], "rpe_max": None, "notas": f["notas"] or "",
               "ejercicios": [d["ejercicio"] for d in detalle]}
        for d in detalle:
            e = por_ejercicio.setdefault(d["ejercicio"], {"ejercicio": d["ejercicio"], "sesiones": 0, "series": 0,
                                                          "repeticiones": 0, "kg_max": None, "con_kilos": 0})
            e["sesiones"] += 1
            e["series"] += d.get("series") or 0
            e["repeticiones"] += (d.get("series") or 0) * (d.get("reps") or 0)
            if d.get("kg"):
                e["kg_max"] = max(e["kg_max"] or 0, d["kg"])
                e["con_kilos"] += 1
            if d.get("rpe"):
                dia["rpe_max"] = max(dia["rpe_max"] or 0, d["rpe"])
        por_dia.append(dia)
    volumen = round(sum(d["volumen_kg"] or 0 for d in por_dia), 1)
    return {"desde": desde, "hasta": hasta, "sesiones": len(filas), "dias": len(por_dia),
            "series": sum(d["series"] for d in por_dia), "repeticiones": sum(d["repeticiones"] for d in por_dia),
            "volumen_kg": volumen or None, "por_dia": por_dia, "con_rpe": sum(1 for d in por_dia if d["rpe_max"]),
            "por_ejercicio": sorted(por_ejercicio.values(), key=lambda x: (-x["sesiones"], x["ejercicio"]))}


def mejor_de(cn: sqlite3.Connection, ejercicio: str) -> dict | None:
    """Su mejor dia en ese ejercicio, por kilos (y a igualdad, por repeticiones)."""
    mejor = None
    for s in historial(cn, ejercicio, limite=500):
        for d in s["ejercicios"]:
            if not d.get("kg"):
                continue
            clave = (d["kg"], (d.get("series") or 0) * (d.get("reps") or 0))
            if mejor is None or clave > (mejor["kg"], (mejor["series"] or 0) * (mejor["reps"] or 0)):
                mejor = {**d, "fecha": s["fecha"]}
    return mejor


def hoja(cn: sqlite3.Connection) -> dict:
    """Lo que pinta el portal: su plantilla, con lo ultimo de cada ejercicio para no empezar de cero, y las ultimas
    sesiones apuntadas."""
    sembrar(cn)
    ejercicios = []
    for e in catalogo(cn):
        ultimo = ultimo_de(cn, e["nombre"])
        ejercicios.append({**e, "ultimo": ultimo,
                           "mejor": mejor_de(cn, e["nombre"])})
    return {"fecha_hoy": db.ahora()[:10], "ejercicios": ejercicios, "sesiones": historial(cn, limite=6)}


def texto(cn: sqlite3.Connection) -> str:
    """La plantilla y lo ultimo, para la consola."""
    h = hoja(cn)
    lineas = ["Plantilla de gimnasio (lo que haces habitualmente):"]
    for e in h["ejercicios"]:
        u = e.get("ultimo")
        dicho = ""
        if u:
            dicho = " | ultima vez " + (u.get("fecha") or "")
            if u.get("series") and u.get("reps"):
                dicho += f": {u['series']}x{u['reps']}"
            if u.get("kg"):
                dicho += f" a {u['kg']:g} kg"
        lineas.append(f"  · {e['nombre']}" + (f" ({e['grupo']})" if e.get("grupo") else "") + dicho)
        if e.get("como"):
            lineas.append(f"      {e['como']}")
    if not h["sesiones"]:
        lineas.append("Todavia no hay ninguna sesion de gimnasio apuntada.")
    else:
        lineas.append("Ultimas sesiones:")
        for s in h["sesiones"]:
            hechos = ", ".join(
                d["ejercicio"] + " " + "x".join(str(x) for x in (d.get("series"), d.get("reps")) if x)
                + (f" a {d['kg']:g} kg" if d.get("kg") else "")
                for d in s["ejercicios"])
            lineas.append(f"  · {s['fecha']}: {hechos}")
    return "\n".join(lineas)
