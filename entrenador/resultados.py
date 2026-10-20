#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""F6: bucle de resultados recomendación -> decisión -> sesión -> verificación -> aprendizaje.

Tres piezas:

1. **Enlace** (`enlazar`): une una recomendación con la actividad/parte/apunte que la ejecutó. Si hay
   varias sesiones posibles no elige a ciegas: deja `ambiguo` con los candidatos y `--enlazar --actividad`
   permite decidir a mano.
2. **Verificación** (`evaluar`): mide antes/después con una métrica declarada por la regla/propuesta,
   calcula delta, confianza y confounders. Sin datos o con confounders importantes, `sin_datos` o
   `no_concluyente`; no se declara causalidad.
3. **Aprendizaje** (`informe`): por regla, cuántas propuestas, aceptadas/cambiadas/ignoradas y resultados.
   No cambia reglas automáticamente: solo propone revisión.

Todo es aditivo. El motor v1 y las recomendaciones por defecto no cambian.
"""

from __future__ import annotations

import json
import sqlite3
import statistics as st
import unicodedata
from datetime import date, timedelta

from . import db, fuerza, plan, planificador, reglas

# Catálogo mínimo de métricas por regla. `tipo` lo entiende `_valor_ventana`; las reglas sin métrica
# quedan en sin_datos con el motivo, no se inventa una consulta.
CATALOGO = {
    "R2": {"tipo": "oficial_400", "tabla": "competicion", "campo": "segundos", "ventana": 28,
           "mejor": "menor", "umbral": 1.0, "piscina_m": 25,
           "descripcion": "mejor 400 libre oficial de 25 m (menor es mejor)"},
    "R1": {"tipo": "ritmo_sesion", "tabla": "parte_serie", "campo": "ritmo_100", "ventana": 14,
           "mejor": "menor", "umbral": 0.5,
           "descripcion": "ritmo mediano de las series del parte (menor es mejor)"},
    "R1b": {"tipo": "ritmo_sesion", "tabla": "parte_serie", "campo": "ritmo_100", "ventana": 14,
            "mejor": "menor", "umbral": 0.5,
            "descripcion": "ritmo mediano de las series del parte (menor es mejor)"},
    "R3": {"tipo": "ritmo_sesion", "tabla": "parte_serie", "campo": "ritmo_100", "ventana": 14,
           "mejor": "menor", "umbral": 0.5,
           "descripcion": "ritmo mediano de las series del parte (menor es mejor)"},
    "R4": {"tipo": "ritmo_sesion", "tabla": "parte_serie", "campo": "ritmo_100", "ventana": 14,
           "mejor": "menor", "umbral": 0.5,
           "descripcion": "ritmo mediano de las series del parte (menor es mejor)"},
    "R5": {"tipo": "sin_datos", "tabla": "", "campo": "", "ventana": 0, "mejor": "menor",
           "descripcion": "R5 mide volumen semanal; el piloto no tiene una serie limpia de volumen propio"},
    "R6": {"tipo": "sin_datos", "tabla": "", "campo": "", "ventana": 0, "mejor": "menor",
           "descripcion": "R6 es una restriccion de calendario, no una metrica de rendimiento"},
    "R7": {"tipo": "sin_datos", "tabla": "", "campo": "", "ventana": 0, "mejor": "menor",
           "descripcion": "R7 es una regla de afinado; no hay metrica de sesion aislada en el piloto"},
    "R8": {"tipo": "sin_datos", "tabla": "", "campo": "", "ventana": 0, "mejor": "menor",
           "descripcion": "R8 es una restriccion de material; se audita en la valoracion, no en una sesion"},
}


def _texto(v) -> str:
    return "" if v is None else str(v).strip()


def _dia_de(texto: str) -> str | None:
    t = unicodedata.normalize("NFKD", _texto(texto)).encode("ascii", "ignore").decode().lower()
    for d in planificador.DIAS:
        if t.startswith(d) or f" {d}" in t:
            return d
    return None


def _rec(cn: sqlite3.Connection, rid: int) -> dict | None:
    f = cn.execute("SELECT * FROM recomendacion WHERE id = ?", (rid,)).fetchone()
    return dict(f) if f else None


def _opcion_elegida(cn: sqlite3.Connection, rid: int) -> dict:
    f = cn.execute("""SELECT sesion_json FROM recomendacion_opcion
                      WHERE recomendacion_id = ? ORDER BY recomendada DESC, id LIMIT 1""", (rid,)).fetchone()
    if not f:
        return {}
    try:
        return json.loads(f["sesion_json"] or "{}")
    except (TypeError, ValueError):
        return {}


def fecha_objetivo(cn: sqlite3.Connection, rid: int) -> str | None:
    """Fecha de la sesión propuesta. v2 la saca de la opción elegida; v1 del título/día y de la semana."""
    r = _rec(cn, rid)
    if not r:
        return None
    if r.get("fecha"):
        # En v1 `fecha` es la fecha de la propuesta, no la de la sesión; solo se usa si no hay semana/día.
        pass
    dia = _dia_de((_opcion_elegida(cn, rid) or {}).get("dia") or "") or _dia_de(r.get("titulo") or "")
    if not dia:
        return None
    semana = None
    for s in plan.SEMANAS:
        if s.get("clave") == r.get("semana"):
            semana = s
            break
    if not semana:
        return None
    try:
        return (date.fromisoformat(semana["desde"]) + timedelta(days=planificador.DIAS.index(dia))).isoformat()
    except (KeyError, ValueError):
        return None


def _parte_de_actividad(cn: sqlite3.Connection, actividad_id) -> int | None:
    if not actividad_id:
        return None
    f = cn.execute("SELECT id FROM parte WHERE actividad_id = ? ORDER BY id DESC LIMIT 1", (actividad_id,)).fetchone()
    return int(f["id"]) if f else None


def _candidatos(cn: sqlite3.Connection, fecha: str) -> list[dict]:
    fuera = []
    for f in cn.execute(
        """SELECT a.id, a.nombre, a.inicio_local, a.distancia_m,
                  (SELECT COUNT(*) FROM parte p WHERE p.actividad_id = a.id) AS partes
           FROM actividad a WHERE a.disciplina = 'natacion' AND substr(a.inicio_local, 1, 10) = ?
           ORDER BY a.id""", (fecha,)):
        fuera.append({"actividad_id": int(f["id"]), "nombre": f["nombre"], "inicio": f["inicio_local"],
                      "metros": f["distancia_m"], "partes": int(f["partes"] or 0)})
    if fuera:
        return fuera
    for f in cn.execute("SELECT id, distancia_m, notas FROM apunte WHERE lower(tipo) = 'natacion' AND fecha = ?",
                        (fecha,)):
        fuera.append({"apunte_id": int(f["id"]), "metros": f["distancia_m"], "notas": f["notas"]})
    return fuera


def _guardar_enlace(cn: sqlite3.Connection, rid: int, fecha: str | None, *, metodo: str, estado: str,
                    actividad_id=None, parte_id=None, apunte_id=None, confianza: str = "baja",
                    candidatos=None) -> dict:
    cn.execute(
        """INSERT INTO recomendacion_enlace
           (recomendacion_id, fecha, actividad_id, parte_id, apunte_id, metodo, estado, confianza,
            candidatos_json, creado_en, actualizado_en)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(recomendacion_id) DO UPDATE SET
             fecha = excluded.fecha, actividad_id = excluded.actividad_id, parte_id = excluded.parte_id,
             apunte_id = excluded.apunte_id, metodo = excluded.metodo, estado = excluded.estado,
             confianza = excluded.confianza, candidatos_json = excluded.candidatos_json,
             actualizado_en = excluded.actualizado_en""",
        (rid, fecha, actividad_id, parte_id, apunte_id, metodo, estado, confianza,
         json.dumps(candidatos or [], ensure_ascii=False, sort_keys=True), db.ahora(), db.ahora()))
    cn.commit()
    return enlace(cn, rid) or {}


def enlace(cn: sqlite3.Connection, rid: int) -> dict | None:
    f = cn.execute("SELECT * FROM recomendacion_enlace WHERE recomendacion_id = ?", (rid,)).fetchone()
    if not f:
        return None
    d = dict(f)
    try:
        d["candidatos"] = json.loads(d.get("candidatos_json") or "[]")
    except (TypeError, ValueError):
        d["candidatos"] = []
    return d


def enlazar(cn: sqlite3.Connection, rid: int, actividad_id: int | None = None) -> dict:
    """Enlaza una recomendación con una sesión. Idempotente y sin elegir a ciegas si hay ambigüedad."""
    r = _rec(cn, rid)
    if not r:
        raise ValueError(f"no existe la recomendacion {rid}")
    if actividad_id is None and r.get("actividad_id"):
        actividad_id = int(r["actividad_id"])
    if actividad_id is not None:
        a = cn.execute("SELECT id, disciplina, inicio_local FROM actividad WHERE id = ?", (actividad_id,)).fetchone()
        if not a:
            raise ValueError(f"no existe la actividad {actividad_id}")
        if a["disciplina"] != "natacion":
            raise ValueError(f"la actividad {actividad_id} no es de natacion ({a['disciplina']})")
        fecha_act = (a["inicio_local"] or "")[:10]
        objetivo = fecha_objetivo(cn, rid)
        # Una recomendacion v1 puede traer solo `actividad_id` y no semana/dia: manda la fecha de la
        # actividad enlazada. Si hay fecha objetivo, la actividad tiene que ser de ese dia.
        if objetivo and fecha_act != objetivo:
            raise ValueError(f"la actividad {actividad_id} es del {fecha_act}, no del dia de la recomendacion ({objetivo})")
        return _guardar_enlace(cn, rid, fecha_act, metodo="manual", estado="enlazado",
                               actividad_id=int(a["id"]), parte_id=_parte_de_actividad(cn, a["id"]),
                               confianza="alta", candidatos=[])
    fecha = fecha_objetivo(cn, rid)
    if not fecha:
        return _guardar_enlace(cn, rid, None, metodo="sin_enlace", estado="sin_enlace",
                               confianza="baja", candidatos=[])
    cands = _candidatos(cn, fecha)
    if len(cands) == 1:
        c = cands[0]
        return _guardar_enlace(cn, rid, fecha, metodo="fecha_unica", estado="enlazado",
                               actividad_id=c.get("actividad_id"), apunte_id=c.get("apunte_id"),
                               parte_id=_parte_de_actividad(cn, c.get("actividad_id")),
                               confianza="alta", candidatos=cands)
    if len(cands) > 1:
        return _guardar_enlace(cn, rid, fecha, metodo="ambiguo", estado="ambiguo",
                               confianza="baja", candidatos=cands)
    return _guardar_enlace(cn, rid, fecha, metodo="sin_enlace", estado="sin_enlace",
                           confianza="baja", candidatos=[])


# --------------------------------------------------------------------------- catálogo / valores

def catalogo(regla_id: str) -> dict | None:
    return dict(CATALOGO[regla_id]) if regla_id in CATALOGO else None


def reglas_de(cn: sqlite3.Connection, rid: int) -> list[str]:
    return [x["regla_id"] for x in cn.execute(
        "SELECT regla_id FROM recomendacion_regla WHERE recomendacion_id = ? ORDER BY id", (rid,))
        if str(x["regla_id"]).startswith("R")]


def _metrica_json(cn: sqlite3.Connection, rid: int) -> dict:
    r = _rec(cn, rid)
    if not r:
        return {}
    crudo = r.get("metrica_exito_json")
    try:
        return json.loads(crudo or "{}") if isinstance(crudo, str) else (crudo or {})
    except (TypeError, ValueError):
        return {}


def metrica_para(cn: sqlite3.Connection, rid: int, regla_id: str) -> dict | None:
    """Métrica de una regla concreta: R2 manda al 400 oficial; el resto respeta la declaración.

    Si la recomendación declara `sin_datos`, no se evalúa con el catálogo. Si no declara nada, se usa el
    catálogo de la regla.
    """
    m = _metrica_json(cn, rid)
    tipo = _texto(m.get("tipo")).lower()
    # Estas declaraciones NO son métricas de rendimiento: no se pueden convertir al catálogo.
    if tipo in ("sin_datos", "seguridad", "datos", "adherencia"):
        return {"tipo": "sin_datos", "tabla": "", "campo": "", "ventana": 0, "mejor": "menor",
                "umbral": 0,
                "descripcion": _texto(m.get("criterio")) or f"la recomendacion declara {tipo}: no evaluable"}
    # Solo R2 impone el 400 oficial cuando la métrica declarada es de rendimiento (o no hay
    # declaración explícita).
    if regla_id == "R2" and (not tipo or tipo in ("oficial_400", "ritmo_100", "ritmo_sesion")):
        return dict(CATALOGO["R2"])
    if tipo in ("oficial_400", "ritmo_100", "ritmo_sesion"):
        base = dict(CATALOGO["R2" if tipo == "oficial_400" else "R1"])
        base["descripcion"] = _texto(m.get("criterio")) or base["descripcion"]
        return base
    return catalogo(regla_id)


def metrica_de(cn: sqlite3.Connection, rid: int) -> dict | None:
    """Métrica principal de la recomendación (R2 si está, si no la primera regla)."""
    ids = reglas_de(cn, rid)
    if "R2" in ids:
        return metrica_para(cn, rid, "R2")
    if ids:
        return metrica_para(cn, rid, ids[0])
    return None


def _valor_ventana(cn: sqlite3.Connection, tipo: str, desde: str, hasta: str,
                   piscina: int | None = None) -> tuple[float | None, int, dict]:
    if tipo == "oficial_400":
        sql = ("""SELECT segundos FROM competicion WHERE estilo = 'libre' AND distancia_m = 400
                  AND valida = 1 AND segundos IS NOT NULL AND fecha BETWEEN ? AND ?""")
        args = [desde, hasta]
        if piscina is not None:
            sql += " AND piscina_m = ?"
            args.append(int(piscina))
        filas = [float(f["segundos"]) for f in cn.execute(sql, args)]
        if not filas:
            return None, 0, {}
        return round(min(filas), 2), len(filas), {"mejor": "menor", "piscina_m": piscina}
    if tipo == "ritmo_sesion":
        filas = [float(f["ritmo_100"]) for f in cn.execute(
            """SELECT ps.ritmo_100 FROM parte_serie ps JOIN parte p ON p.id = ps.parte_id
               WHERE p.fecha BETWEEN ? AND ? AND ps.ritmo_100 IS NOT NULL""", (desde, hasta))]
        if not filas:
            return None, 0, {}
        return round(float(st.median(filas)), 2), len(filas), {"mejor": "menor"}
    return None, 0, {}


def _ventanas(fecha: str, dias: int = 28) -> tuple[tuple[str, str], tuple[str, str]]:
    d = date.fromisoformat(fecha[:10])
    return ((d - timedelta(days=dias)).isoformat(), (d - timedelta(days=1)).isoformat()), \
           ((d + timedelta(days=1)).isoformat(), (d + timedelta(days=dias)).isoformat())


def _minutos(cn: sqlite3.Connection, desde: str, hasta: str) -> float:
    total = 0.0
    for f in cn.execute("""SELECT duracion_s FROM actividad
                           WHERE substr(inicio_local, 1, 10) BETWEEN ? AND ?""", (desde, hasta)):
        total += float(f["duracion_s"] or 0) / 60.0
    for f in cn.execute("SELECT minutos FROM apunte WHERE fecha BETWEEN ? AND ?", (desde, hasta)):
        total += float(f["minutos"] or 0)
    return total


def _confounders(cn: sqlite3.Connection, fecha: str, tipo: str, enl: dict) -> list[dict]:
    (a1, a2), (b1, b2) = _ventanas(fecha)
    fuera = []
    if tipo == "ritmo_sesion":
        aid = enl.get("actividad_id")
        if aid and not _parte_de_actividad(cn, aid):
            fuera.append({"tipo": "parte_incompleto", "detalle": "la sesion enlazada no tiene parte"})
    mats = [r["material"] for r in cn.execute(
        """SELECT ps.material FROM parte_serie ps JOIN parte p ON p.id = ps.parte_id
           WHERE p.fecha BETWEEN ? AND ? AND ps.material IS NOT NULL AND trim(ps.material) <> ''""",
        (a1, b2)) if r["material"]]
    if mats:
        fuera.append({"tipo": "material", "detalle": ", ".join(sorted(set(mats)))})
    piscinas = [r["largo_piscina_m"] for r in cn.execute(
        """SELECT DISTINCT ns.largo_piscina_m FROM natacion_sesion ns JOIN actividad a ON a.id = ns.actividad_id
           WHERE substr(a.inicio_local, 1, 10) BETWEEN ? AND ? AND ns.largo_piscina_m IS NOT NULL""",
        (a1, b2))]
    if len(set(piscinas)) > 1:
        fuera.append({"tipo": "piscina", "detalle": f"piscinas {sorted(set(piscinas))}"})
    piscinas_comp = [r["piscina_m"] for r in cn.execute(
        """SELECT DISTINCT piscina_m FROM competicion
           WHERE estilo = 'libre' AND distancia_m = 400 AND valida = 1 AND fecha BETWEEN ? AND ?
             AND piscina_m IS NOT NULL""", (a1, b2))]
    if len(set(piscinas_comp)) > 1:
        fuera.append({"tipo": "piscina_competicion", "detalle": f"piscinas oficiales {sorted(set(piscinas_comp))}"})
    sueno_a = [float(r["horas"]) for r in cn.execute("SELECT horas FROM sueno WHERE fecha BETWEEN ? AND ?", (a1, a2))
               if r["horas"] is not None]
    sueno_b = [float(r["horas"]) for r in cn.execute("SELECT horas FROM sueno WHERE fecha BETWEEN ? AND ?", (b1, b2))
               if r["horas"] is not None]
    if sueno_a and sueno_b and abs(st.mean(sueno_a) - st.mean(sueno_b)) > 1.5:
        fuera.append({"tipo": "sueno", "detalle": f"{st.mean(sueno_a):.1f} -> {st.mean(sueno_b):.1f} h"})
    ma, mb = _minutos(cn, a1, a2), _minutos(cn, b1, b2)
    if ma > 0 and mb > 0:
        ratio = mb / ma
        if ratio > 1.3 or ratio < 0.77:
            fuera.append({"tipo": "carga", "detalle": f"{ma:.0f} -> {mb:.0f} min"})
    for tabla in ("parte", "apunte"):
        for r in cn.execute(f"SELECT notas FROM {tabla} WHERE fecha BETWEEN ? AND ?", (a1, b2)):
            n = (_texto(r["notas"])).lower()
            if "viaje" in n or "viaj" in n:
                fuera.append({"tipo": "viaje", "detalle": "nota de viaje en la ventana"})
                break
    if fuerza.dolor_declarado(cn, a1):
        fuera.append({"tipo": "dolor", "detalle": "dolor declarado en la ventana"})
    return fuera


def _guardar_verificacion(cn: sqlite3.Connection, rid: int, regla_id: str, fecha: str, *, metrica: str,
                          antes, despues, veredicto: str, delta, confianza: str, aprendizaje: str,
                          confounders: list[dict], notas: str, n_antes: int = 0, n_despues: int = 0,
                          ventana: str = "") -> dict:
    cn.execute("DELETE FROM verificacion WHERE recomendacion_id = ? AND regla_id = ?", (rid, regla_id))
    cn.execute("""INSERT INTO verificacion
                  (recomendacion_id, regla_id, fecha, metrica, antes, despues, veredicto, notas,
                   resultado, delta, confianza, aprendizaje, confounders_json, n_antes, n_despues, ventana)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (rid, regla_id, fecha, metrica, antes, despues, veredicto, notas,
                veredicto, delta, confianza, aprendizaje,
                json.dumps(confounders, ensure_ascii=False, sort_keys=True),
                int(n_antes or 0), int(n_despues or 0), ventana))
    cn.commit()
    return {"recomendacion_id": rid, "regla_id": regla_id, "fecha": fecha, "metrica": metrica,
            "antes": antes, "despues": despues, "delta": delta, "n_antes": int(n_antes or 0),
            "n_despues": int(n_despues or 0), "ventana": ventana,
            "veredicto": veredicto, "resultado": veredicto, "confianza": confianza,
            "aprendizaje": aprendizaje, "confounders": confounders, "notas": notas}


def _sin_datos(cn: sqlite3.Connection, rid: int, regla_id: str, fecha: str, motivo: str) -> dict:
    return _guardar_verificacion(
        cn, rid, regla_id, fecha, metrica="", antes=None, despues=None, veredicto="sin_datos",
        delta=None, confianza="baja", aprendizaje=f"{regla_id}: sin_datos; {motivo}.",
        confounders=[], notas=motivo)


def _evaluar_regla(cn: sqlite3.Connection, rid: int, regla_id: str, met: dict | None,
                   enl: dict, fecha: str) -> dict:
    if not met or met.get("tipo") == "sin_datos":
        motivo = (met or {}).get("descripcion") or "la regla no declara una metrica evaluable"
        return _sin_datos(cn, rid, regla_id, fecha, motivo)
    if met.get("tipo") == "ritmo_sesion" and enl.get("actividad_id"):
        pid = _parte_de_actividad(cn, enl.get("actividad_id"))
        if not pid:
            return _sin_datos(cn, rid, regla_id, fecha,
                              "la sesion enlazada no tiene parte: no se puede medir el estimulo")
        if not cn.execute("SELECT COUNT(*) FROM parte_serie WHERE parte_id = ?", (pid,)).fetchone()[0]:
            return _sin_datos(cn, rid, regla_id, fecha,
                              "el parte enlazado no tiene series: no se puede medir el estimulo")
    (a1, a2), (b1, b2) = _ventanas(fecha, int(met.get("ventana") or 28))
    antes, n_a, _ = _valor_ventana(cn, met["tipo"], a1, a2, met.get("piscina_m"))
    despues, n_b, _ = _valor_ventana(cn, met["tipo"], b1, b2, met.get("piscina_m"))
    if antes is None or despues is None:
        falta = "antes" if antes is None else "despues"
        motivo = f"sin datos {falta} de la ventana para {met.get('descripcion') or met['tipo']}"
        return _guardar_verificacion(
            cn, rid, regla_id, fecha, metrica=met.get("descripcion") or met["tipo"],
            antes=antes, despues=despues, veredicto="sin_datos", delta=None, confianza="baja",
            aprendizaje=f"{regla_id}: sin_datos; {motivo}.", confounders=[], notas=motivo,
            n_antes=n_a, n_despues=n_b, ventana=f"{a1}..{b2}")
    conf = _confounders(cn, fecha, met["tipo"], enl)
    delta = round(float(despues) - float(antes), 2)
    umbral = float(met.get("umbral") or 0.5)
    if conf:
        veredicto = "no_concluyente"
        notas = "hay confounders: " + "; ".join(c["tipo"] for c in conf)
    elif delta <= -umbral:
        veredicto = "a_favor"
        notas = f"delta {delta:+.2f}: mejora"
    elif delta >= umbral:
        veredicto = "en_contra"
        notas = f"delta {delta:+.2f}: empeora"
    else:
        veredicto = "no_concluyente"
        notas = f"delta {delta:+.2f}: dentro del margen de {umbral}"
    n_min = min(n_a, n_b)
    confianza = "alta" if n_min >= 3 and not conf else ("media" if n_min >= 1 else "baja")
    aprendizaje = (f"{regla_id}: {veredicto}; delta {delta:+.2f} ({n_a} antes, {n_b} despues)"
                   + (f"; confounders: {', '.join(c['tipo'] for c in conf)}" if conf else "")
                   + ". No se cambia la regla automaticamente.")
    return _guardar_verificacion(
        cn, rid, regla_id, fecha, metrica=met.get("descripcion") or met["tipo"],
        antes=antes, despues=despues, veredicto=veredicto, delta=delta, confianza=confianza,
        aprendizaje=aprendizaje, confounders=conf, notas=notas,
        n_antes=n_a, n_despues=n_b, ventana=f"{a1}..{b2}")


def _resumen_evaluacion(rid: int, vs: list[dict]) -> dict:
    if not vs:
        return {"recomendacion_id": rid, "verificaciones": [], "veredicto": "sin_datos"}
    d = dict(vs[0])
    d["verificaciones"] = vs
    return d


def evaluar(cn: sqlite3.Connection, rid: int) -> dict:
    """Evalúa todas las reglas con métrica de una recomendación aceptada.

    Una fila por regla (R2 oficial, R1/R1b/R3/R4 de parte; R5/R6/R7/R8 quedan sin_datos con motivo).
    Idempotente por (recomendación, regla). No declara causalidad.
    """
    r = _rec(cn, rid)
    if not r:
        raise ValueError(f"no existe la recomendacion {rid}")
    reglas_ids = reglas_de(cn, rid) or ["R?"]
    enl = enlace(cn, rid) or enlazar(cn, rid)
    if enl.get("estado") != "enlazado":
        motivo = (f"enlace {enl.get('estado')}: no hay una sesion unica para evaluar"
                  if enl.get("estado") != "sin_enlace" else "sin enlace con una sesion")
        fecha = enl.get("fecha") or r.get("fecha") or ""
        vs = [_sin_datos(cn, rid, rid_regla, fecha, motivo) for rid_regla in reglas_ids]
        return _resumen_evaluacion(rid, vs)
    d = cn.execute("SELECT tomada, motivo FROM decision WHERE recomendacion_id = ?", (rid,)).fetchone()
    if not d or d["tomada"] != "aceptada":
        estado = d["tomada"] if d else "sin decision"
        motivo = f"decision {estado}: no se evalua la recomendacion original"
        fecha = enl.get("fecha") or r.get("fecha") or ""
        vs = [_sin_datos(cn, rid, rid_regla, fecha, motivo) for rid_regla in reglas_ids]
        return _resumen_evaluacion(rid, vs)
    fecha = enl.get("fecha") or r.get("fecha")
    if not fecha:
        vs = [_sin_datos(cn, rid, rid_regla, "", "falta fecha") for rid_regla in reglas_ids]
        return _resumen_evaluacion(rid, vs)
    vs = []
    for rid_regla in reglas_ids:
        met = metrica_para(cn, rid, rid_regla)
        vs.append(_evaluar_regla(cn, rid, rid_regla, met, enl, fecha))
    return _resumen_evaluacion(rid, vs)

def evaluar_todas(cn: sqlite3.Connection) -> dict:
    salida = []
    for f in cn.execute("SELECT id FROM recomendacion ORDER BY id"):
        rid = int(f["id"])
        try:
            if not enlace(cn, rid):
                enlazar(cn, rid)
            salida.append(evaluar(cn, rid))
        except Exception as exc:
            salida.append({"recomendacion_id": rid, "veredicto": "sin_datos", "notas": str(exc)})
    return {"evaluadas": len(salida), "resultados": salida}


# --------------------------------------------------------------------------- informe / panel

def _verif(cn: sqlite3.Connection, rid: int) -> dict | None:
    # La primaria es R2 si existe; si no, la primera regla de la recomendacion.
    ids = reglas_de(cn, rid)
    primaria = "R2" if "R2" in ids else (ids[0] if ids else None)
    f = (cn.execute("SELECT * FROM verificacion WHERE recomendacion_id = ? AND regla_id = ? "
                    "ORDER BY id DESC LIMIT 1", (rid, primaria)).fetchone() if primaria else None)
    if not f:
        f = cn.execute("SELECT * FROM verificacion WHERE recomendacion_id = ? ORDER BY id ASC LIMIT 1",
                       (rid,)).fetchone()
    if not f:
        return None
    d = dict(f)
    try:
        d["confounders"] = json.loads(d.get("confounders_json") or "[]")
    except (TypeError, ValueError):
        d["confounders"] = []
    return d


def listar(cn: sqlite3.Connection, limite: int = 50) -> list[dict]:
    fuera = []
    for f in cn.execute("SELECT * FROM recomendacion ORDER BY id DESC LIMIT ?", (int(limite),)):
        r = dict(f)
        enl = enlace(cn, r["id"]) or {}
        d = cn.execute("SELECT tomada, motivo, respuesta FROM decision WHERE recomendacion_id = ?",
                       (r["id"],)).fetchone()
        v = _verif(cn, r["id"])
        fuera.append({"id": r["id"], "fecha": r.get("fecha"), "semana": r.get("semana"),
                      "titulo": r.get("titulo"), "origen": r.get("origen"),
                      "enlace": {"estado": enl.get("estado"), "metodo": enl.get("metodo"),
                                 "actividad_id": enl.get("actividad_id"),
                                 "apunte_id": enl.get("apunte_id"), "fecha": enl.get("fecha"),
                                 "candidatos": len(enl.get("candidatos") or [])},
                      "decision": dict(d) if d else None,
                      "verificacion": v})
    return fuera


def detalle(cn: sqlite3.Connection, rid: int) -> dict:
    r = _rec(cn, rid)
    if not r:
        return {}
    d = cn.execute("SELECT * FROM decision WHERE recomendacion_id = ?", (rid,)).fetchone()
    return {"recomendacion": r, "enlace": enlace(cn, rid), "decision": dict(d) if d else None,
            "verificaciones": [dict(x) for x in cn.execute(
                "SELECT * FROM verificacion WHERE recomendacion_id = ? ORDER BY id", (rid,))]}


def resumen(cn: sqlite3.Connection) -> dict:
    recs = listar(cn, limite=1000)
    por = {"enlazado": 0, "sin_enlace": 0, "ambiguo": 0}
    for r in recs:
        por[r["enlace"].get("estado") or "sin_enlace"] = por.get(r["enlace"].get("estado") or "sin_enlace", 0) + 1
    ver = [dict(x) for x in cn.execute("SELECT * FROM verificacion ORDER BY id")]
    return {"recomendaciones": len(recs), "enlaces": por,
            "con_decision": sum(1 for r in recs if r.get("decision")),
            "aceptadas": sum(1 for r in recs if (r.get("decision") or {}).get("tomada") == "aceptada"),
            "cambiadas": sum(1 for r in recs if (r.get("decision") or {}).get("tomada") == "cambiada"),
            "ignoradas": sum(1 for r in recs if (r.get("decision") or {}).get("tomada") == "ignorada"),
            "evaluadas": len({v.get("recomendacion_id") for v in ver}),
            "verificaciones": len(ver),
            "a_favor": sum(1 for v in ver if v.get("veredicto") == "a_favor"),
            "en_contra": sum(1 for v in ver if v.get("veredicto") == "en_contra"),
            "sin_datos": sum(1 for v in ver if v.get("veredicto") == "sin_datos"),
            "no_concluyente": sum(1 for v in ver if v.get("veredicto") == "no_concluyente"),
            "ultimos": recs[:8]}


def informe(cn: sqlite3.Connection) -> dict:
    salida = []
    for r in reglas.REGLAS:
        rid = r["id"]
        props = [x for x in listar(cn, limite=1000)
                 if rid in [y["regla_id"] for y in cn.execute(
                     "SELECT regla_id FROM recomendacion_regla WHERE recomendacion_id = ?", (x["id"],))]]
        dec = {"aceptada": 0, "cambiada": 0, "ignorada": 0, "sin_registrar": 0}
        ver = {"a_favor": 0, "en_contra": 0, "sin_datos": 0, "no_concluyente": 0}
        for p in props:
            d = (p.get("decision") or {}).get("tomada") or "sin_registrar"
            dec[d] = dec.get(d, 0) + 1
            vf = cn.execute("""SELECT veredicto FROM verificacion
                               WHERE recomendacion_id = ? AND regla_id = ? ORDER BY id DESC LIMIT 1""",
                            (p["id"], rid)).fetchone()
            if vf:
                v = vf["veredicto"]
                ver[v] = ver.get(v, 0) + 1
        salida.append({"regla_id": rid, "enunciado": r.get("enunciado"), "propuestas": len(props),
                       "decisiones": dec, "verificaciones": ver,
                       "metrica": catalogo(rid),
                       "revisar": ver.get("en_contra", 0) >= 3,
                       "motivo_revision": ("3 o mas evaluaciones en contra" if ver.get("en_contra", 0) >= 3
                                           else "sin motivo automatico")})
    return {"reglas": salida}
