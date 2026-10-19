"""Lo que el sistema aprende de sus entrenamientos: cuanto bailan los datos y como agrupa las series.

Los datos que captura el reloj **no son exactos**: se equivoca con algun largo, los tiempos varian uno o
dos segundos y una repeticion puede salir con el cronometro mal disparado. En vez de clavar margenes a
mano, aqui se miden de sus propios partes:

- **Cuanto baila un tiempo** respecto a la linea del bloque (`ruido`): eso da el margen con el que
  `concepto.medir` decide si una repeticion es mas rapida o "igual" que la anterior.
- **Como agrupa las repeticiones** (`agrupacion`): cuanto descanso hay dentro de un bloque suyo y cuanto
  entre bloques. Ese es el umbral que dice "esto es la misma serie", y sale de sus partes, no de un
  numero inventado.

El resultado se guarda en `data/derived/aprendizaje.json` en cada pasada de `analizar`, y se puede volver
a mirar con `leer()` / `resumen()`. Con pocos partes manda el valor por defecto declarado, y el resumen lo
dice (`basado_en`).
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics as st
from datetime import datetime

from . import concepto as _concepto
from . import series as _series

RUTA = os.path.join("data", "derived", "aprendizaje.json")

# Lo que se usa mientras no haya de donde aprender (o sea muy poco). Son los valores que ya estaban en el
# codigo, ahora declarados como lo que son: el punto de partida hasta que sus datos digan otra cosa.
MARGEN_POR_DEFECTO = _concepto.MARGEN_POR_DEFECTO     # s/100
DESCANSO_MISMO_BLOQUE_S = 180.0                       # mas que esto cierra la serie (`series.DESCANSO_MAX_S`)
MIN_BLOQUES_RUIDO = 3                                 # menos que esto no basta para hablar de su ruido
MIN_REPS_MARGEN = 3


def _hora(txt) -> float | None:
    """La hora de un lap (su `inicio`) en segundos, para poder restar dos. Se mide aqui en vez de tirar de
    `partes` para que este modulo no dependa de el (es `partes` quien va a usar lo que aqui se aprende)."""
    texto = str(txt or "").strip()
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _ritmos_y_descansos(cn: sqlite3.Connection, actividad_id: int, laps, reps) -> tuple[list, list]:
    """Los ritmos de las repeticiones de un bloque (del reloj, por su lap) y el descanso de detras de cada una.

    El descanso es lo que va del final de una repeticion al principio de la siguiente, que es lo que se lee en
    el reloj aunque el parte no lo guarde. Las repeticiones sin `lap` (apuntadas a mano) no tienen tiempo del
    reloj: se quedan fuera.
    """
    idxs = [int(x) for x in (laps or []) if x is not None]
    if not idxs:
        return [], []
    marcas = ",".join("?" * len(idxs))
    filas = {r["lap_idx"]: r for r in cn.execute(
        f"""SELECT lap_idx, inicio, dist_m, timer_s FROM natacion_lap
            WHERE actividad_id = ? AND lap_idx IN ({marcas})""", (actividad_id, *idxs))}
    por_lap = {}
    for r in (reps or []):
        if isinstance(r, dict) and r.get("lap") is not None:
            por_lap[int(r["lap"])] = r
    ritmos, descansos = [], []
    for k, lap in enumerate(idxs):
        f = filas.get(lap)
        if not f or not f["dist_m"] or not f["timer_s"]:
            continue
        ritmos.append(_series.ritmo_100(f["dist_m"], f["timer_s"]))
        d = por_lap.get(lap, {}).get("descanso_s")
        if d:
            descansos.append(float(d))
            continue
        # El descanso de una repeticion llega hasta la siguiente del mismo bloque (la ultima se queda sin
        # medir: lo que venga despues ya es otra cosa).
        arranque = _hora(f["inicio"])
        fin = None if arranque is None else arranque + float(f["timer_s"])
        siguiente = filas.get(idxs[k + 1]) if k + 1 < len(idxs) else None
        arranque_sig = _hora(siguiente["inicio"]) if siguiente else None
        if fin is not None and arranque_sig is not None and 0 < arranque_sig - fin < 900:
            descansos.append(round(arranque_sig - fin, 1))
        else:
            descansos.append(0.0)
    return ritmos, descansos


def bloques_de_los_partes(cn: sqlite3.Connection) -> list[dict]:
    """Todos los bloques de los partes ya subidos, con lo necesario para medir ruido y agrupacion."""
    filas = cn.execute(
        """SELECT p.id AS parte_id, p.fecha, p.actividad_id, s.orden, s.tipo, s.n_reps, s.metros,
                  s.ritmo_100, s.intensidad, s.material, s.laps, s.reps, s.descanso_s
           FROM parte_serie s JOIN parte p ON p.id = s.parte_id
           ORDER BY p.fecha, s.orden""").fetchall()
    salida = []
    for f in filas:
        try:
            laps = json.loads(f["laps"]) if isinstance(f["laps"], str) else (f["laps"] or [])
            reps = json.loads(f["reps"]) if isinstance(f["reps"], str) else (f["reps"] or [])
        except (TypeError, ValueError):
            laps, reps = [], []
        ritmos, descansos = _ritmos_y_descansos(cn, f["actividad_id"], laps, reps)
        salida.append({
            "parte_id": f["parte_id"], "fecha": f["fecha"], "actividad_id": f["actividad_id"],
            "orden": f["orden"], "tipo": f["tipo"], "n_reps": f["n_reps"], "metros": f["metros"],
            "intensidad": f["intensidad"], "material": f["material"],
            "ritmos": ritmos, "descansos": descansos,
        })
    return salida


def ruido(bloques: list[dict]) -> dict:
    """Cuanto se aparta una repeticion de la linea del bloque, en s/100. Ese es el margen de la forma."""
    desviaciones = []
    for b in bloques:
        vals = [v for v in (b["ritmos"] or []) if v is not None]
        if len(vals) < MIN_REPS_MARGEN:
            continue
        pend = _concepto.pendiente(vals)
        linea = [vals[0] + pend * i for i in range(len(vals))] if pend is not None else list(vals)
        desviaciones.append(st.median([abs(v - l) for v, l in zip(vals, linea)]))
    if len(desviaciones) < MIN_BLOQUES_RUIDO:
        return {"margen_s_100": float(MARGEN_POR_DEFECTO), "basado_en": len(desviaciones),
                "p75_s_100": None, "max_s_100": None, "por_defecto": True}
    return {
        "margen_s_100": round(max(MARGEN_POR_DEFECTO, st.median(desviaciones)), 2),
        "p75_s_100": round(sorted(desviaciones)[int(0.75 * (len(desviaciones) - 1))], 2),
        "max_s_100": round(max(desviaciones), 2),
        "basado_en": len(desviaciones),
        "por_defecto": False,
    }


def agrupacion(bloques: list[dict]) -> dict:
    """Como agrupa: cuanto descanso cabe dentro de un bloque suyo. Ese es el umbral que dice "misma serie"."""
    dentro: list[float] = []
    for b in bloques:
        dentro += [float(d) for d in (b["descansos"] or []) if d and d > 0]
    reps = [int(b["n_reps"] or 0) for b in bloques if b["tipo"] == "serie" and b["n_reps"]]
    if len(dentro) < 5:
        return {"descanso_mismo_bloque_s": float(DESCANSO_MISMO_BLOQUE_S), "basado_en": len(dentro),
                "dentro_mediana_s": None, "dentro_max_s": None, "por_defecto": True, "reps_por_serie": None}
    # El umbral sale de lo que hace de verdad: el descanso mas largo que ha usado dentro de un bloque, mas un
    # margen. Si nunca ha pasado de 60 s, una pausa de 90 s ya es otra cosa; y nunca por encima del tope de
    # siempre (180 s), que es el que cierra la serie en `series.reconstruir_series`.
    umbral = min(float(DESCANSO_MISMO_BLOQUE_S), max(60.0, max(dentro) + 15.0))
    return {
        "descanso_mismo_bloque_s": round(umbral, 1),
        "dentro_mediana_s": round(st.median(dentro), 1),
        "dentro_max_s": round(max(dentro), 1),
        "reps_por_serie": round(st.median(reps), 1) if reps else None,
        "basado_en": len(dentro),
        "por_defecto": False,
    }


def conceptos(bloques: list[dict], margen: float) -> dict:
    """Cuantas series de cada forma, y con que intensidad suele usar cada una (lo que ya ha hecho)."""
    cuenta: dict = {}
    por_intensidad: dict = {}
    for b in bloques:
        vals = [v for v in (b["ritmos"] or []) if v is not None]
        e = _concepto.medir(vals, margen=margen)
        clave = e.get("concepto")
        if not clave:
            continue
        cuenta[clave] = cuenta.get(clave, 0) + 1
        por_intensidad.setdefault(b["intensidad"] or "sin_intensidad", {})
        por_intensidad[b["intensidad"] or "sin_intensidad"][clave] = \
            por_intensidad[b["intensidad"] or "sin_intensidad"].get(clave, 0) + 1
    return {"cuenta": cuenta, "por_intensidad": por_intensidad,
            "n_bloques_medidos": sum(cuenta.values())}


def aprender(cn: sqlite3.Connection, guardar: bool = True) -> dict:
    """Lo mide todo, lo deja en `data/derived/aprendizaje.json` y lo devuelve."""
    bloques = bloques_de_los_partes(cn)
    r = ruido(bloques)
    a = agrupacion(bloques)
    c = conceptos(bloques, r["margen_s_100"])
    datos = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "partes": len({b["parte_id"] for b in bloques}),
        "bloques": len(bloques),
        "margen_s_100": r["margen_s_100"],
        "ruido": r,
        "agrupacion": a,
        "conceptos": c,
    }
    if guardar:
        os.makedirs(os.path.dirname(RUTA) or ".", exist_ok=True)
        with open(RUTA, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=1)
    return datos


def leer() -> dict:
    """Lo aprendido la ultima vez (vacio si todavia no se ha medido nunca)."""
    try:
        with open(RUTA, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def margen() -> float:
    """El margen aprendido para decidir si una repeticion es "igual" que la anterior (s/100)."""
    return float(leer().get("margen_s_100") or MARGEN_POR_DEFECTO)


def descanso_mismo_bloque() -> float:
    """El descanso que, segun sus partes, todavia es "la misma serie" (s)."""
    a = leer().get("agrupacion") or {}
    try:
        return float(a.get("descanso_mismo_bloque_s") or DESCANSOS_MISMO_BLOQUE_S)
    except (TypeError, ValueError):
        return float(DESCANSOS_MISMO_BLOQUE_S)


def resumen() -> dict:
    """Cuatro cifras para el portal y el discurso: que ha aprendido y con cuantos datos."""
    d = leer()
    r = d.get("ruido") or {}
    a = d.get("agrupacion") or {}
    return {
        "partes": d.get("partes", 0),
        "bloques": d.get("bloques", 0),
        "margen_s_100": d.get("margen_s_100", MARGEN_POR_DEFECTO),
        "basado_en_bloques": r.get("basado_en", 0),
        "por_defecto": bool(r.get("por_defecto", True)),
        "descanso_mismo_bloque_s": a.get("descanso_mismo_bloque_s", DESCANSO_MISMO_BLOQUE_S),
        "reps_por_serie": a.get("reps_por_serie"),
        "conceptos": (d.get("conceptos") or {}).get("cuenta") or {},
        "generado": d.get("generado"),
    }
