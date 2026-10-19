#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""El bucle cerrado: cada consejo queda con sus datos, sus reglas, su decision y su verificacion.

Sin esto, lo que el motor propone se pierde en cuanto se cierra la consola: no se puede decir de donde salio, ni si
el atleta lo acepto, ni si acerto. Aqui vive todo eso, en cinco tablas (S.6.4):

    recomendacion        que se propuso, cuando y de que ambito
    recomendacion_dato   los numeros que la sostienen (fuente tipo `tabla.campo`)
    recomendacion_regla  las reglas que la motivan, la limitan o avisan
    decision             que hizo el atleta: aceptada, cambiada o ignorada
    verificacion         si la regla acerto: a favor, en contra o sin datos

Dos reglas que manda el proyecto y que este modulo hace cumplir:

  1. **Una recomendacion sin datos usados no se guarda.** Si no hay numeros detras, es una opinion (S.2.2).
  2. **Una regla sin seccion en el anexo T se guarda igual, pero se lee como criterio.** No se disfraza de saber:
     el grado y la seccion se resuelven al leer, con `conocimiento`, para que nunca se queden viejos.

Uso:
    from . import decision
    decision.registrar(cn, "semana", {"titulo": "Martes: series medias", "cuerpo": "8x200..."},
                       datos=[{"fuente": "estimulos.deficits", "ref": "series_medias.metros_actuales",
                               "valor": 1200, "nota": "lo que hace ahora"}],
                       reglas_usadas=[{"regla_id": "R1", "papel": "motiva"},
                                      {"regla_id": "R6", "papel": "limita"}])
    decision.decidir(cn, rid, "cambiada", motivo="el miercoles no puedo")
    decision.panel_reglas(cn)
"""

from __future__ import annotations

import sqlite3

from . import conocimiento, db, reglas

# Que regla motiva cada clase de estimulo: es el "porque" del dia propuesto. Si una clase no aparece aqui, el dia
# se guarda igual, con las reglas que limitan (R6) y avisan (R7); pero sin regla que lo motive.
MOTIVA: dict[str, str] = {
    "ritmo_prueba": "R2",
    "punta_velocidad": "R2",
    "velocidad_resistencia": "R2",
    "continuo_sostenido": "R1b",
    "continuo_aerobico": "R1",
    "series_medias": "R1",
    "series_largas": "R4",
    "pies": "R8",
}

# Con que se comprueba cada regla: que metrica, de donde sale y en que sentido es mejorar. La regla que no esta
# aqui **no se puede verificar todavia** y se declara `sin_datos` con el motivo, en vez de fingir un veredicto.
METRICAS: dict[str, dict] = {
    "R2": {
        "que": "el 400 oficial de la federacion",
        "mejor": "menor",
        "sql": ("SELECT fecha, segundos AS valor FROM competicion "
                "WHERE estilo = 'libre' AND distancia_m = 400 AND valida = 1"),
        "nota": "R2 dice que el ritmo de prueba y la punta deben acusarlo en el 400",
    },
}

ESTADOS = ("aceptada", "cambiada", "ignorada")


# ------------------------------------------------------------------ utilidades


def _texto(v) -> str:
    return "" if v is None else str(v).strip()


def _numero(v) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _papel(v) -> str:
    p = _texto(v).lower()
    return p if p in ("motiva", "limita", "avisa") else "motiva"


# ------------------------------------------------------------------ escribir


def registrar(cn: sqlite3.Connection, ambito: str, que: dict, datos: list[dict],
              reglas_usadas: list | None = None, semana: str | None = None,
              actividad_id: int | None = None, origen: str = "motor") -> int:
    """Guarda una recomendacion con sus datos y sus reglas. Devuelve su id.

    `que` es `{"titulo": ..., "cuerpo": ...}` (el cuerpo puede ser el texto de la sesion). `datos` son los numeros
    usados, cada uno con `fuente` (`tabla.campo` o `modulo.funcion`), `ref`, `valor` y `nota`. Sin un solo dato,
    esto levanta `ValueError`: lo que no se sostiene con numeros no entra en el bucle.
    """
    if ambito not in ("sesion", "semana", "bloque"):
        raise ValueError(f"ambito desconocido: {ambito!r} (sesion, semana o bloque)")
    limpios = [d for d in (datos or []) if isinstance(d, dict) and _texto(d.get("fuente"))]
    if not limpios:
        raise ValueError("una recomendacion sin datos usados no se guarda: seria una opinion, no una recomendacion")

    titulo = _texto((que or {}).get("titulo"))
    cuerpo = _texto((que or {}).get("cuerpo"))
    if not titulo:
        raise ValueError("una recomendacion sin titulo no se puede citar despues")

    cur = cn.execute(
        "INSERT INTO recomendacion (fecha, ambito, semana, actividad_id, titulo, cuerpo, origen, creada_en)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (db.ahora()[:10], ambito, semana, actividad_id, titulo, cuerpo, origen, db.ahora()))
    rid = cur.lastrowid

    for d in limpios:
        cn.execute("INSERT INTO recomendacion_dato (recomendacion_id, fuente, ref, valor, nota) VALUES (?,?,?,?,?)",
                   (rid, _texto(d.get("fuente")), _texto(d.get("ref")),
                    None if d.get("valor") is None else str(d.get("valor")), _texto(d.get("nota"))))

    vistas = set()
    for r in reglas_usadas or []:
        rid_regla = _texto(r.get("regla_id") if isinstance(r, dict) else r)
        if not rid_regla or rid_regla in vistas:
            continue
        vistas.add(rid_regla)
        cn.execute("INSERT INTO recomendacion_regla (recomendacion_id, regla_id, papel) VALUES (?,?,?)",
                   (rid, rid_regla, _papel(r.get("papel") if isinstance(r, dict) else None)))
    cn.commit()
    return int(rid)


def registrar_semana(cn: sqlite3.Connection, propuesta: dict, deficits: list[dict] | None = None,
                     semana: str | None = None) -> dict:
    """Guarda la propuesta de una semana entera: una recomendacion por dia propio con sesion.

    Cada una sale con al menos tres datos (lo que hace ahora de esa clase, lo que pide la receta y el volumen de la
    semana) y con dos reglas como minimo: las que la limitan (R6) y avisan (R7), mas la que la motiva.
    """
    por_clase = {d.get("id"): d for d in (deficits or []) if isinstance(d, dict)}
    volumen = propuesta.get("volumen") or {}
    dias = propuesta.get("dias") or {}
    ids: list[int] = []

    for dia, s in sorted(dias.items(), key=lambda kv: _orden_dia(kv[0])):
        clase = s.get("clase")
        d = por_clase.get(clase) or {}
        datos: list[dict] = []

        if d.get("metros_actuales") is not None:
            datos.append({"fuente": "estimulos.deficits", "ref": f"{clase}.metros_actuales",
                          "valor": d["metros_actuales"], "nota": "lo que hace ahora de esa clase"})
        if d.get("metros_minimos") is not None:
            datos.append({"fuente": "estimulos.deficits", "ref": f"{clase}.metros_minimos",
                          "valor": d["metros_minimos"], "nota": "el minimo que pide el plan"})
        if s.get("metros"):
            datos.append({"fuente": "estimulos.RECETAS", "ref": _texto(s.get("receta")),
                          "valor": s["metros"], "nota": "metros que propone la receta"})
        if s.get("ritmo_desde") and s.get("ritmo_hasta"):
            datos.append({"fuente": "estimulos.receta_libre", "ref": "ritmo_100",
                          "valor": f"{s['ritmo_desde']}-{s['ritmo_hasta']} s/100",
                          "nota": "la banda en la que hay que nadarla"})
        if volumen.get("propio_m") is not None:
            datos.append({"fuente": "planificador.propuesta_semana", "ref": "metros_propios",
                          "valor": volumen["propio_m"],
                          "nota": f"la semana deja {volumen.get('deja_m')} m para los dias propios"})
        if d.get("porque"):
            datos.append({"fuente": "estimulos.deficits", "ref": f"{clase}.porque", "valor": "—",
                          "nota": d["porque"]})

        reglas_usadas: list[dict] = [{"regla_id": "R6", "papel": "limita"}, {"regla_id": "R7", "papel": "avisa"}]
        motiva = MOTIVA.get(clase)
        if motiva:
            reglas_usadas.insert(0, {"regla_id": motiva, "papel": "motiva"})

        ids.append(registrar(cn, "semana",
                             {"titulo": f"{dia.capitalize()}: {_texto(s.get('titulo')) or clase}",
                              "cuerpo": _texto(s.get("sesion"))},
                             datos, reglas_usadas, semana=semana))
    return {"ids": ids, "cuantas": len(ids), "semana": semana,
            "sin_sesion": [d for d, s in (dias.items()) if not s.get("sesion")]}


def _orden_dia(dia: str) -> int:
    try:
        from . import planificador
        return planificador.DIAS.index(dia)
    except Exception:
        return 99


def decidir(cn: sqlite3.Connection, recomendacion_id: int, tomada: str, respuesta: str | None = None,
            motivo: str | None = None) -> None:
    """Apunta que hizo el atleta con una recomendacion. La ultima decision manda (una por recomendacion)."""
    tomada = _texto(tomada).lower()
    if tomada not in ESTADOS:
        raise ValueError(f"decision desconocida: {tomada!r} (aceptada, cambiada o ignorada)")
    if tomada == "cambiada" and not _texto(motivo):
        raise ValueError("una sesion cambiada se guarda con su motivo: sin motivo no se aprende nada")
    fila = cn.execute("SELECT 1 FROM recomendacion WHERE id = ?", (recomendacion_id,)).fetchone()
    if not fila:
        raise ValueError(f"no hay ninguna recomendacion con el numero {recomendacion_id}")
    cn.execute("DELETE FROM decision WHERE recomendacion_id = ?", (recomendacion_id,))
    cn.execute("INSERT INTO decision (recomendacion_id, fecha, tomada, respuesta, motivo, decidida_en)"
               " VALUES (?,?,?,?,?,?)",
               (recomendacion_id, db.ahora()[:10], tomada, _texto(respuesta), _texto(motivo), db.ahora()))
    cn.commit()


# ------------------------------------------------------------------ leer


def recomendaciones(cn: sqlite3.Connection, desde: str | None = None, hasta: str | None = None,
                    limite: int = 50) -> list[dict]:
    """Las recomendaciones guardadas, de la mas nueva a la mas vieja, con su decision y sus reglas."""
    sql = ["SELECT r.*, d.tomada, d.motivo, d.respuesta FROM recomendacion r"
           " LEFT JOIN decision d ON d.recomendacion_id = r.id WHERE 1=1"]
    args: list = []
    if desde:
        sql.append(" AND r.fecha >= ?")
        args.append(desde)
    if hasta:
        sql.append(" AND r.fecha <= ?")
        args.append(hasta)
    sql.append(" ORDER BY r.fecha DESC, r.id DESC LIMIT ?")
    args.append(int(limite))
    salida = []
    for f in cn.execute("".join(sql), args).fetchall():
        r = dict(f)
        r["reglas"] = [x["regla_id"] for x in cn.execute(
            "SELECT regla_id FROM recomendacion_regla WHERE recomendacion_id = ? ORDER BY id", (r["id"],))]
        r["datos"] = int(cn.execute("SELECT COUNT(*) FROM recomendacion_dato WHERE recomendacion_id = ?",
                                    (r["id"],)).fetchone()[0])
        salida.append(r)
    return salida


def detalle(cn: sqlite3.Connection, recomendacion_id: int) -> dict:
    """Una recomendacion entera: datos, reglas (con su seccion del anexo T), decision y verificacion.

    Es lo que abre el portal al pinchar un consejo: dato -> regla -> fuente. El grado y la seccion se resuelven
    ahora, con `conocimiento`, no se guardan copiados.
    """
    fila = cn.execute("SELECT * FROM recomendacion WHERE id = ?", (recomendacion_id,)).fetchone()
    if not fila:
        return {}
    r = dict(fila)
    r["datos"] = [dict(x) for x in cn.execute(
        "SELECT fuente, ref, valor, nota FROM recomendacion_dato WHERE recomendacion_id = ? ORDER BY id",
        (recomendacion_id,))]
    r["reglas"] = []
    for x in cn.execute("SELECT regla_id, papel FROM recomendacion_regla WHERE recomendacion_id = ? ORDER BY id",
                        (recomendacion_id,)):
        ficha = conocimiento.fuente_de(x["regla_id"]) or {}
        r["reglas"].append({"regla_id": x["regla_id"], "papel": x["papel"],
                            "seccion_T": list(ficha.get("secciones") or []),
                            "fuentes": list(ficha.get("fuentes") or []),
                            "grado": ficha.get("grado") or "criterio",
                            "criterio": bool(ficha.get("criterio"))})
    d = cn.execute("SELECT * FROM decision WHERE recomendacion_id = ?", (recomendacion_id,)).fetchone()
    r["decision"] = dict(d) if d else None
    r["verificacion"] = [dict(x) for x in cn.execute(
        "SELECT regla_id, fecha, metrica, antes, despues, veredicto, notas FROM verificacion"
        " WHERE recomendacion_id = ? ORDER BY id", (recomendacion_id,))]
    return r


def _valor_metrica(cn: sqlite3.Connection, metrica: dict, desde: str | None, hasta: str | None,
                   mejor: str = "menor") -> tuple[float | None, str | None]:
    """El valor de la metrica en la ventana: el mejor de los que hay (menor o mayor, segun la regla)."""
    sql = metrica["sql"]
    args: list = []
    if desde:
        sql += " AND fecha >= ?"
        args.append(desde)
    if hasta:
        sql += " AND fecha <= ?"
        args.append(hasta)
    filas = [f for f in cn.execute(sql, args).fetchall() if f["valor"] is not None]
    if not filas:
        return None, None
    filas.sort(key=lambda f: f["valor"], reverse=(mejor != "menor"))
    return float(filas[0]["valor"]), _texto(filas[0]["fecha"])


def verificar(cn: sqlite3.Connection, regla_id: str, desde: str, hasta: str) -> dict:
    """Comprueba una regla con lo que ha pasado en la ventana: a favor, en contra o sin datos.

    No se inventa el veredicto: si la regla no declara metrica, o si todavia no hay medida antes o despues, dice
    `sin_datos` y por que. Las filas de `verificacion` se rehacen en cada pasada (idempotente por regla y ventana).
    """
    recs = [r for r in recomendaciones(cn, desde, hasta, limite=1000) if regla_id in r["reglas"]]
    metrica = METRICAS.get(regla_id)
    cn.execute("DELETE FROM verificacion WHERE regla_id = ? AND fecha BETWEEN ? AND ?", (regla_id, desde, hasta))

    if not recs:
        salida = {"regla_id": regla_id, "veredicto": "sin_datos", "recomendaciones": 0,
                  "antes": None, "despues": None,
                  "notas": "no hay recomendaciones de esa regla en la ventana"}
        return salida
    if not metrica:
        salida = {"regla_id": regla_id, "veredicto": "sin_datos", "recomendaciones": len(recs),
                  "antes": None, "despues": None,
                  "notas": "esa regla no declara metrica: no se puede comprobar con numeros"}
        _guardar_verificacion(cn, recs, regla_id, desde, None, None, salida["veredicto"], salida["notas"])
        return salida

    antes, fecha_antes = _valor_metrica(cn, metrica, None, _dia_antes(desde), metrica["mejor"])
    despues, fecha_despues = _valor_metrica(cn, metrica, desde, hasta, metrica["mejor"])
    if antes is None or despues is None:
        falta = "antes" if antes is None else "despues"
        veredicto = "sin_datos"
        notas = (f"{metrica['que']} todavia no tiene medida {falta} de la ventana "
                 f"({metrica.get('nota') or ''})").strip()
    else:
        mejora = (despues < antes) if metrica["mejor"] == "menor" else (despues > antes)
        veredicto = "a_favor" if mejora else "en_contra"
        notas = f"{metrica['que']}: {antes:g} ({fecha_antes}) -> {despues:g} ({fecha_despues})"
    _guardar_verificacion(cn, recs, regla_id, desde, antes, despues, veredicto, notas)
    return {"regla_id": regla_id, "veredicto": veredicto, "recomendaciones": len(recs),
            "antes": antes, "despues": despues, "notas": notas}


def _dia_antes(fecha: str) -> str:
    """El dia anterior a una fecha ISO, para mirar el 'antes' de la ventana (el dia justo no cuenta)."""
    try:
        from datetime import date, timedelta
        d = date.fromisoformat(_texto(fecha)[:10])
        return (d - timedelta(days=1)).isoformat()
    except ValueError:
        return _texto(fecha)[:10]


def _guardar_verificacion(cn: sqlite3.Connection, recs: list[dict], regla_id: str, fecha: str,
                          antes: float | None, despues: float | None, veredicto: str, notas: str) -> None:
    for r in recs:
        cn.execute("INSERT INTO verificacion (recomendacion_id, regla_id, fecha, metrica, antes, despues,"
                   " veredicto, notas) VALUES (?,?,?,?,?,?,?,?)",
                   (r["id"], regla_id, fecha, (METRICAS.get(regla_id) or {}).get("que"), antes, despues,
                    veredicto, notas))
    cn.commit()


# ------------------------------------------------------------------ panel de reglas


def panel_reglas(cn: sqlite3.Connection, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """El credito de cada regla: cuantas veces se ha propuesto, que hizo el atleta y si ha acertado.

    Es el aprendizaje del sistema: las reglas no se reajustan, ganan o pierden credito. Una regla con tres
    ventanas seguidas en contra sale marcada para revisar (y no se retira sola: la retira el atleta).
    """
    salida = []
    for r in reglas.REGLAS:
        rid = r["id"]
        recs = [x for x in recomendaciones(cn, desde, hasta, limite=1000) if rid in x["reglas"]]
        estados = {"aceptada": 0, "cambiada": 0, "ignorada": 0, "sin_registrar": 0}
        for x in recs:
            estados[_texto(x.get("tomada")).lower() if x.get("tomada") else "sin_registrar"] = \
                estados.get(_texto(x.get("tomada")).lower() if x.get("tomada") else "sin_registrar", 0) + 1
        # La ventana por defecto no puede ser "desde siempre": el `antes` de una metrica es el ultimo valor
        # anterior a la primera propuesta, no el de 1900 (que no existe y dejaria todo en sin_datos).
        desde_ventana = desde or (min((x["fecha"] for x in recs if x.get("fecha")), default="1900-01-01")
                                  if recs else "1900-01-01")
        v = verificar(cn, rid, desde_ventana, hasta or db.ahora()[:10]) if recs else \
            {"veredicto": "sin_datos", "notas": "todavia no se ha propuesto", "recomendaciones": 0}
        en_contra = int(cn.execute(
            "SELECT COUNT(DISTINCT fecha) FROM verificacion WHERE regla_id = ? AND veredicto = 'en_contra'",
            (rid,)).fetchone()[0])
        salida.append({
            "regla_id": rid,
            "enunciado": (r.get("enunciado") or "").split(". ")[0][:180],
            "fuente": r.get("fuente"),
            "grado": r.get("grado") or "criterio",
            "seccion_T": list(r.get("seccion_t") or []),
            "porque": r.get("se_comprueba"),
            "propuestas": len(recs), "decisiones": estados,
            "veredicto": v.get("veredicto"), "notas": v.get("notas"),
            "ventanas_en_contra": en_contra, "revisar": en_contra >= 3,
        })
    return salida


def resumen(cn: sqlite3.Connection) -> dict:
    """Cuatro numeros para el portal: cuantas propuestas hay, cuantas decides, cuantas se verifican."""
    total = int(cn.execute("SELECT COUNT(*) FROM recomendacion").fetchone()[0])
    filas = cn.execute("SELECT d.tomada, COUNT(*) AS n FROM decision d GROUP BY d.tomada").fetchall()
    por_estado = {f["tomada"]: f["n"] for f in filas}
    reglas_panel = panel_reglas(cn)
    return {
        "recomendaciones": total,
        "decididas": sum(por_estado.values()),
        "por_estado": por_estado,
        "sin_decidir": total - sum(por_estado.values()),
        "reglas": len(reglas_panel),
        "reglas_a_favor": sum(1 for r in reglas_panel if r["veredicto"] == "a_favor"),
        "reglas_en_contra": sum(1 for r in reglas_panel if r["veredicto"] == "en_contra"),
        "reglas_sin_datos": sum(1 for r in reglas_panel if r["veredicto"] == "sin_datos"),
        "para_revisar": [r["regla_id"] for r in reglas_panel if r["revisar"]],
    }


def proponer_semana(cn: sqlite3.Connection, hoy=None) -> dict:
    """Guarda la propuesta de la semana que toca, con su porque, y devuelve lo que ha entrado (V1.3-02).

    No calcula nada nuevo: los numeros salen del mismo sitio que el discurso del entrenador (`valoracion.
    _falta_y_toca`: la ventana de 14 dias, los deficits, el reparto por dia y el volumen que deja el plan). Aqui
    solo se guarda, para que la propuesta no se pierda al cerrar la consola. Devuelve `propuesta` (lo que dijo el
    motor) y, encima, lo que dejo escrito (`ids`, `cuantas`, `semana`).
    """
    from datetime import date

    from . import plan, valoracion

    if hoy is None:
        hoy = date.fromisoformat(db.ahora()[:10])
    elif isinstance(hoy, str):
        hoy = date.fromisoformat(hoy[:10])
    if not plan.OBJETIVOS:
        return {"semana": None, "cuantas": 0, "ids": [], "propuesta": {}, "falta": "sin plan"}
    try:
        dias_al_reto = (date.fromisoformat(plan.OBJETIVO_B["fecha"]) - hoy).days
    except (KeyError, ValueError):
        dias_al_reto = 28

    m = valoracion._falta_y_toca(cn, hoy, plan.OBJETIVOS[0]["ritmo_objetivo_100"], dias_al_reto)
    propuesta = m.get("reparto") or {}
    if not propuesta.get("dias"):
        return {"semana": None, "cuantas": 0, "ids": [], "propuesta": propuesta, "falta": m.get("falta")}
    semana = (plan.semana_de(hoy) or {}).get("clave")
    r = registrar_semana(cn, propuesta, m.get("deficits"), semana=semana)
    return {**r, "propuesta": propuesta, "falta": None}


def datos_entrenador(cn: sqlite3.Connection) -> dict:
    """Lo que el portal necesita del bucle cerrado: el credito de cada regla y las ultimas propuestas enteras.

    Las propuestas van **enteras** (con sus datos y sus reglas) porque asi el atleta puede pinchar una y ver de
    donde sale cada numero sin pedirle nada mas al servidor (V1.5-01).
    """
    from . import conocimiento

    return {"resumen": resumen(cn),
            "conocimiento": conocimiento.cuadro_revision(cn),
            "reglas": panel_reglas(cn),
            "propuestas": [detalle(cn, r["id"]) for r in recomendaciones(cn, limite=20)]}
