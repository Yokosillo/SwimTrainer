#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Motor de decisión v2 (F5): prioridades, opciones, restricciones y explicación determinista.

No es un LLM ni un optimizador opaco. Para cada prioridad genera 2-4 opciones a partir de las recetas
que ya existen, las descarta si violan una restricción dura, las puntúa con una fórmula auditable y
elige una. Todo lo que aparece en la recomendación se puede reconstruir con el estado, el conocimiento
y las reglas.

Fórmula de puntuación (los pesos se pueden cambiar en `conocimiento/local/motor.toml`):

    score = (efecto * peso_efecto) * (confianza * peso_confianza)
            - (riesgo * peso_riesgo) - (coste * peso_coste)

Empate: menor riesgo; si sigue, menor coste; si sigue, id de opción.

Seguridad: dolor/lesión declarada no genera sesión, solo parar/derivar. Sin datos: `sin_datos`, sin
inventar una sesión. F9 activa `MOTOR_RECOMENDACION=v2` por defecto; `v1` sigue disponible para
rollback y `dual` solo compara sin escribir.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tomllib
from datetime import date, timedelta

from . import db, estimulos, estado, fuerza, plan, planificador, reglas

PESOS_POR_DEFECTO = {"efecto": 1.0, "confianza": 1.0, "riesgo": 1.0, "coste": 1.0}
RUTA_PESOS = os.path.join("conocimiento", "local", "motor.toml")
FORMULA_SCORE = "score = (efecto * peso_efecto) * (confianza * peso_confianza) - (riesgo * peso_riesgo) - (coste * peso_coste)"

# Afirmaciones/reglas que sostienen cada prioridad. Si una AF no esta en el conocimiento publico/local,
# se cae a una afirmacion disponible; nunca se cita una que no exista.
EVIDENCIA = {
    "ritmo_prueba": ["AF-002"],
    "velocidad_resistencia": ["AF-001"],
    "series_medias": ["AF-001"],
    "series_largas": ["AF-001"],
    "continuo_sostenido": ["AF-209", "AF-001"],
    "continuo_aerobico": ["AF-209", "AF-001"],
    "afinar": ["AF-207", "AF-003"],
    "descarga": ["AF-205", "AF-003"],
    "sin_datos": ["AF-003"],
}

PARAMETROS = {
    "ritmo_prueba": ["PA-101", "PA-102"],
    "velocidad_resistencia": ["PA-102"],
    "series_medias": ["PA-102"],
    "series_largas": ["PA-102"],
    "continuo_sostenido": ["PA-104"],
    "afinar": ["PA-113"],
    "descarga": ["PA-106"],
}

MOTIVA = {
    "ritmo_prueba": "R2", "velocidad_resistencia": "R2", "series_medias": "R1",
    "series_largas": "R4", "continuo_sostenido": "R1b", "continuo_aerobico": "R1",
    "afinar": "R7", "descarga": "R5", "pies": "R8",
}


def _texto(v) -> str:
    return "" if v is None else str(v).strip()


def _numero(v, defecto=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return defecto


def _ritmo(s100) -> str:
    if not s100:
        return ""
    s = float(s100)
    m, r = divmod(round(s * 10), 600)
    return f"{m}:{r / 10:04.1f}".replace(".", ",")


def _rango_ritmo(desde, hasta) -> str:
    if not desde or not hasta:
        return ""
    return f"{_ritmo(desde)}-{_ritmo(hasta)}"


def carga_pesos(ruta: str | None = None) -> dict:
    """Lee `[pesos]` de `conocimiento/local/motor.toml` si existe; si no, usa los valores auditables por defecto."""
    pesos = dict(PESOS_POR_DEFECTO)
    ruta = ruta or RUTA_PESOS
    if not os.path.isfile(ruta):
        return pesos
    try:
        with open(ruta, "rb") as fh:
            datos = tomllib.load(fh)
        for clave in pesos:
            if clave in (datos.get("pesos") or {}):
                pesos[clave] = float(datos["pesos"][clave])
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        pass
    return pesos


def _afirmaciones_disponibles() -> set[str]:
    try:
        from . import conocimiento_toml
        return {a.id for a in conocimiento_toml.cargar().afirmaciones}
    except Exception:
        return set()


def _parametros_disponibles() -> set[str]:
    try:
        from . import conocimiento_toml
        return {p.id for p in conocimiento_toml.cargar().parametros}
    except Exception:
        return set()


def _evidencia(clase: str) -> list[str]:
    disponibles = _afirmaciones_disponibles()
    candidatas = EVIDENCIA.get(clase) or ["AF-003", "AF-001"]
    fuera = [a for a in candidatas if a in disponibles]
    if fuera:
        return fuera[:2]
    for a in ("AF-003", "AF-001", "AF-002"):
        if a in disponibles:
            return [a]
    return []


def _parametros(clase: str) -> list[str]:
    disponibles = _parametros_disponibles()
    return [p for p in (PARAMETROS.get(clase) or []) if p in disponibles]


def _metrica_estado(e: estado.EstadoAtleta, clave: str):
    for s in e.secciones:
        for m in s.metricas:
            if m.clave == clave:
                return m
    return None


def _dolor(e: estado.EstadoAtleta) -> bool:
    # Puede haber una metrica de dolor en restricciones y otra copia en una seccion de prueba/estado:
    # manda cualquiera que diga "si"; no se tapa con una copia vacia anterior.
    return any(m.clave == "dolor_lesion" and m.valor == "si"
               for s in e.secciones for m in s.metricas)


def _fecha_mas(fecha: str, dias: int) -> str:
    return (date.fromisoformat(fecha[:10]) + timedelta(days=dias)).isoformat()


def _semana_de(fecha: str) -> str | None:
    try:
        return (plan.semana_de(fecha) or {}).get("clave")
    except Exception:
        return None


def _objetivo_100() -> float:
    try:
        return float(plan.OBJETIVOS[0]["ritmo_objetivo_100"])
    except (KeyError, IndexError, TypeError, ValueError):
        return 75.0


def _pasos_receta(clave: str) -> list[dict]:
    """Pasos estructurados de la receta (TOML publico + local), con sus metros."""
    try:
        from . import conocimiento_toml
        for r in conocimiento_toml.cargar().recetas:
            if r.clave == clave and r.pasos:
                return [{"orden": p.orden, "texto": p.texto, "tipo": p.tipo,
                         "metros": float(p.metros or 0), "descanso_s": p.descanso_s,
                         "ritmo_100": p.ritmo_100} for p in r.pasos]
    except Exception:
        pass
    return []


def _receta(clave: str, objetivo: float) -> dict:
    if clave not in estimulos.RECETAS:
        return {}
    libre = estimulos.receta_libre(clave, objetivo)
    r = estimulos.RECETAS[clave]
    return {"clave": clave, "nombre": libre.get("nombre") or clave,
            "sesion": libre.get("sesion") or r.get("sesion") or "",
            "metros": int(libre.get("metros") or 0),
            "reps": int(r.get("reps") or 1), "dist_m": int(r.get("dist_m") or 0),
            "descanso_s": float(r.get("descanso_s") or 0),
            "ritmo": _rango_ritmo(libre.get("ritmo_desde"), libre.get("ritmo_hasta")),
            "porque": libre.get("porque") or r.get("porque") or "",
            "pasos": _pasos_receta(clave),
            "recuperacion": float(estimulos.CLASES.get(clave, {}).get("recuperacion") or 24.0)}


def _alternativa(clave: str) -> str:
    orden = ["series_medias", "series_largas", "ritmo_prueba", "velocidad_resistencia",
             "continuo_sostenido", "continuo", "descarga"]
    for c in orden:
        if c != clave and c in estimulos.RECETAS:
            return c
    return "descarga"


def _minima(clave: str) -> str:
    """Compatibilidad: la clave base de la receta mínima (que ahora es la misma receta)."""
    return clave


def receta_minima(clave: str, objetivo: float) -> dict:
    """Versión reducida de la MISMA receta, con pasos y metros coherentes.

    Conserva calentamiento y suelta; reduce la parte principal (la de más metros). Si la parte principal
    tenía repeticiones, reduce reps a la mitad (mínimo 1) y mantiene el descanso cuando quedan >=2 reps;
    si queda 1, el descanso entre reps es 0 y se declara. `metros` es siempre la suma de los pasos.
    """
    base = _receta(clave, objetivo)
    if not base:
        return {}
    pasos = [dict(p) for p in (base.get("pasos") or [])]
    if not pasos:
        # Sin pasos estructurados no se puede prometer una sesion coherente: se reduce el texto base.
        metros = max(600, int(round(int(base.get("metros") or 600) * 0.55)))
        return {**base, "sesion": f"{base['nombre']} (minima): {metros} m",
                "metros": metros, "reps": 1, "dist_m": metros, "descanso_s": 0,
                "pasos": [{"orden": 1, "texto": f"{metros} m", "tipo": "continuo", "metros": metros}],
                "variante": "minima", "receta_base": base.get("clave") or clave,
                "nota": "sin pasos estructurados: se conserva el estimulo y se recorta el volumen"}
    # La parte principal es la serie/continuo, no el calentamiento: en velocidad el calentamiento
    # puede tener mas metros que la serie y no es lo que se recorta.
    candidatos = [i for i, p in enumerate(pasos) if (p.get("tipo") or "") in ("serie", "continuo")]
    idx = max(candidatos or range(len(pasos)), key=lambda i: float(pasos[i].get("metros") or 0))
    r = estimulos.RECETAS.get(base.get("clave") or clave) or {}
    reps = int(r.get("reps") or 1)
    dist = int(r.get("dist_m") or 0)
    descanso = float(r.get("descanso_s") or 0)
    principal = float(pasos[idx].get("metros") or 0)
    if reps > 1 and dist > 0:
        reps_min = max(1, reps // 2)
        metros_principal = reps_min * dist
        descanso_min = descanso if reps_min > 1 else 0.0
        texto_principal = (f"{reps_min}x{dist} m" +
                           (f" con {descanso_min:g} s" if reps_min > 1 and descanso_min else ""))
        nota_descanso = ("se mantiene el descanso de la receta" if reps_min > 1 and descanso_min
                         else "sin descanso entre repeticiones: queda 1")
        pasos[idx] = {**pasos[idx], "texto": texto_principal, "metros": float(metros_principal),
                      "tipo": "serie", "descanso_s": descanso_min}
        reps_out, dist_out, descanso_out = reps_min, dist, descanso_min
    else:
        metros_principal = max(600, int(round(principal * 0.50 / 50.0) * 50))
        pasos[idx] = {**pasos[idx], "texto": f"{metros_principal} m continuos",
                      "metros": float(metros_principal), "tipo": "continuo", "descanso_s": 0}
        reps_out, dist_out, descanso_out = 1, metros_principal, 0.0
        nota_descanso = "sin descanso entre repeticiones: es un continuo"
    # Preservar calentamiento/suelta (los demas pasos) y recalcular el total con la suma exacta.
    texto = " | ".join(str(p.get("texto") or "").strip() for p in pasos if str(p.get("texto") or "").strip())
    total = int(round(sum(float(p.get("metros") or 0) for p in pasos)))
    sesion = ("minima: " + texto) if texto else f"{base['nombre']} (minima)"
    return {**base, "sesion": sesion,
            "metros": total, "reps": reps_out, "dist_m": dist_out, "descanso_s": descanso_out,
            "pasos": pasos, "variante": "minima", "receta_base": base.get("clave") or clave,
            "nota": nota_descanso}


def _opcion(opcion_id: str, receta: dict, dia: str | None, tipo: str, *,
            efecto: float, confianza: float, riesgo: float, coste: float,
            porque: str, descartada: bool = False, motivo: str = "", pesos: dict | None = None) -> dict:
    pesos = pesos or PESOS_POR_DEFECTO
    score = round((efecto * pesos["efecto"]) * (confianza * pesos["confianza"])
                  - (riesgo * pesos["riesgo"]) - (coste * pesos["coste"]), 3)
    riesgo_label = "bajo" if riesgo < 1.0 else ("medio" if riesgo < 2.0 else "alto")
    coste_label = "bajo" if coste < 1.0 else ("medio" if coste < 2.0 else "alto")
    efecto_label = "alto" if efecto >= 6.0 else ("medio" if efecto >= 3.0 else "bajo")
    return {
        "id": opcion_id, "recomendada": False, "tipo": tipo,
        "sesion": receta.get("sesion") or "", "dia": dia,
        "metros": int(receta.get("metros") or 0), "ritmo": receta.get("ritmo") or "",
        "reps": int(receta.get("reps") or 1), "dist_m": int(receta.get("dist_m") or 0),
        "descanso_s": float(receta.get("descanso_s") or 0), "pasos": receta.get("pasos") or [],
        "efecto": efecto, "efecto_esperado": efecto_label,
        "confianza": round(float(confianza), 2), "riesgo": riesgo, "riesgo_etiqueta": riesgo_label,
        "coste": coste, "coste_etiqueta": coste_label,
        "porque": porque, "score": score,
        "descartada": bool(descartada), "motivo_descarte": motivo,
        "receta": receta.get("clave") or "", "variante": receta.get("variante") or "",
        "receta_base": receta.get("receta_base") or receta.get("clave") or "",
    }


def _clave_opcion(o: dict) -> tuple:
    return (-float(o.get("score") or 0), float(o.get("riesgo") or 99),
            float(o.get("coste") or 99), str(o.get("id")))


def _elegir(opciones: list[dict]) -> dict:
    validas = [o for o in opciones if not o.get("descartada")]
    if not validas:
        validas = [o for o in opciones if o.get("tipo") == "mantener"]
    if not validas:
        raise ValueError("no hay ninguna opcion valida")
    validas = sorted(validas, key=_clave_opcion)
    for o in opciones:
        o["recomendada"] = o is validas[0]
    return validas[0]


def _dias_libres(fecha: str, tests, ocupados, cargados, usados_global=()) -> list[str]:
    tests = set(tests or ())
    ocupados = set(ocupados or ())
    cargados = set(cargados or ())
    usados_global = set(usados_global or ())
    entrenador = set(planificador.DIAS_ENTRENADOR)
    bici = planificador.DIA_BICI
    vetados = {planificador.DIAS[(planificador.DIAS.index(t) - 1) % 7] for t in tests} - tests
    fuera = []
    for d in planificador.DIAS_PROPIOS:
        if (d in entrenador or d == bici or d in tests or d in vetados or d in ocupados
                or d in cargados or d in usados_global):
            continue
        fuera.append(d)
    return fuera


def _opciones_prioridad(deficit: dict, fecha: str, tests, ocupados, cargados, objetivo: float,
                        pesos: dict, dias_globales=()) -> tuple[list[dict], list[dict]]:
    clase = _texto(deficit.get("id"))
    base_clave = _texto(deficit.get("receta")) or clase
    base = _receta(base_clave, objetivo)
    if not base:
        base = _receta("series_medias", objetivo)
    alt = _receta(_alternativa(base.get("clave") or clase), objetivo)
    mini = receta_minima(base.get("clave") or clase, objetivo)
    dias = _dias_libres(fecha, tests, ocupados, cargados, dias_globales)
    usados: set[str] = set()

    def dame(preferido: str | None) -> str | None:
        if preferido and preferido in dias and preferido not in usados:
            usados.add(preferido)
            return preferido
        for d in dias:
            if d not in usados:
                usados.add(d)
                return d
        return None

    opciones = []
    for oid, r, efecto, conf, tipo, porque in (
        ("A", base, 8.0, 0.7, "recomendada", deficit.get("porque") or base.get("porque") or ""),
        ("B", alt, 5.0, 0.5, "alternativa", alt.get("porque") or "menos especifica, pero cabe si no puedes"),
        ("C", mini, 2.0, 0.55, "minima", mini.get("porque") or "minimo eficaz de una receta existente"),
    ):
        dia = dame(estimulos.RECETAS.get(r.get("clave") or "", {}).get("desde"))
        motivo = ""
        if dia is None:
            motivo = "no hay dia propio libre: entrenador, bici, prueba, carga o dia ocupado"
        riesgo = min(3.0, max(0.2, float(r.get("recuperacion") or 24.0) / 18.0))
        coste = min(3.0, max(0.2, float(r.get("metros") or 0) / 1200.0))
        opciones.append(_opcion(oid, r, dia, tipo, efecto=efecto, confianza=conf,
                                riesgo=riesgo, coste=coste, porque=porque,
                                descartada=dia is None, motivo=motivo, pesos=pesos))
    # Mantener / no hacer nada: siempre existe y no depende de un dia libre.
    mantener = {"clave": "mantener", "sesion": "No hacer nada: mantener la semana tal como esta",
                "metros": 0, "ritmo": "", "porque": "no anade carga y no rompe ninguna restriccion"}
    opciones.append(_opcion("D", mantener, None, "mantener", efecto=1.0, confianza=0.9,
                            riesgo=0.2, coste=0.1, porque=mantener["porque"], pesos=pesos))
    # Si no queda ningun dia libre, A/B/C se descartan y "mantener" seria la unica opcion viva. Para
    # que la recomendacion siga teniendo una alternativa real (y no solo descartes), se sustituye la
    # minima (que tampoco se puede colocar) por una descarga sin sesion, tambien sin dia.
    if not any(not o.get("descartada") for o in opciones if o.get("tipo") != "mantener"):
        descarga = {"clave": "descarga", "sesion": "Descarga: bajar el volumen sin anadir calidad",
                    "metros": 0, "ritmo": "", "porque": "si no hay dia para la sesion, al menos no cargar"}
        opciones[2] = _opcion("C", descarga, None, "descarga", efecto=1.0, confianza=0.55,
                              riesgo=0.2, coste=0.1, porque=descarga["porque"], pesos=pesos)
    _elegir(opciones)
    restricciones = []
    if tests:
        restricciones.append({"tipo": "prueba", "descripcion": f"dias de prueba: {', '.join(sorted(tests))}",
                              "fuente": "plan.pruebas_de"})
    if cargados:
        restricciones.append({"tipo": "carga", "descripcion": f"dias ya cargados: {', '.join(sorted(cargados))}",
                              "fuente": "fuerza.cargados_de_la_semana"})
    if ocupados:
        restricciones.append({"tipo": "ocupado", "descripcion": f"dias ocupados: {', '.join(sorted(ocupados))}",
                              "fuente": "entrada"})
    if not dias:
        restricciones.append({"tipo": "sin_dia", "descripcion": "no queda un dia propio libre esta semana",
                              "fuente": "planificador"})
    return opciones, restricciones


def _recomendacion(prioridad: int, deficit: dict, e: estado.EstadoAtleta, fecha: str, semana: str | None,
                   tests, ocupados, cargados, objetivo: float, pesos: dict, dias_globales=()) -> dict:
    clase = _texto(deficit.get("id"))
    opciones, restricciones = _opciones_prioridad(deficit, fecha, tests, ocupados, cargados, objetivo,
                                                  pesos, dias_globales)
    elegida = next(o for o in opciones if o.get("recomendada"))
    alternativa = next((o for o in opciones if o is not elegida and not o.get("descartada")), None)
    contra = []
    for o in opciones:
        if o.get("descartada") and o.get("motivo_descarte"):
            contra.append(o["motivo_descarte"])
    metrica = {"tipo": "ritmo_100" if elegida.get("tipo") != "mantener" else "adherencia",
               "criterio": (f"que la sesion de {clase} se sostenga dentro de la banda propuesta"
                            if elegida.get("tipo") != "mantener" else
                            "que no se anada carga y se mantenga el volumen de la semana"),
               "medir_en": _fecha_mas(fecha, 3)}
    revision = _fecha_mas(fecha, 7)
    estado_slice = {"estado_id": e.estado_id, "fecha": e.fecha, "clase": clase,
                    "confianza": elegida.get("confianza"),
                    "metros_actuales": deficit.get("metros_actuales"),
                    "metros_minimos": deficit.get("metros_minimos"), "pct": deficit.get("pct"),
                    "grado": deficit.get("grado"), "seccion_T": list(deficit.get("seccion_T") or [])}
    ev = _evidencia(clase)
    explicacion = (
        f"Que veo: {deficit.get('titulo') or clase}: {deficit.get('porque') or 'hay un hueco en la ventana'} "
        f"(confianza {elegida.get('confianza')}). "
        f"Por que importa: {deficit.get('porque') or 'es la clase que falta'} ({', '.join(ev) or 'criterio'}). "
        f"Que propongo: {elegida.get('sesion') or 'mantener'}"
        + (f" el {elegida['dia']}" if elegida.get("dia") else "")
        + f", {elegida.get('metros')} m. "
        f"Como lo medimos: {metrica['criterio']} el {metrica['medir_en']}. "
        f"Riesgo: {elegida.get('riesgo_etiqueta')}; si no puedes, "
        f"{alternativa.get('sesion') if alternativa else 'mantener'}. "
        f"Revision: {revision}."
    )
    return {
        "id": f"REC-PREVIEW-{e.estado_id}-{prioridad}",
        "fecha": fecha, "ambito": "semana", "semana": semana,
        "knowledge_version": e.version_conocimiento, "estado_id": e.estado_id,
        "prioridad": prioridad, "problema": deficit.get("titulo") or clase,
        "estado": estado_slice,
        "opciones": opciones,
        "evidencia": ev, "parametros": _parametros(clase),
        "contraindicaciones": contra,
        "metrica_exito": metrica, "revisar_en": revision,
        "explicacion": explicacion, "confianza": elegida.get("confianza"),
        "restricciones": restricciones, "pesos": dict(pesos),
        "datos": [
            {"fuente": "estado", "ref": f"{clase}.metros_actuales",
             "valor": deficit.get("metros_actuales"), "nota": "lo que hay en la ventana"},
            {"fuente": "estado", "ref": f"{clase}.metros_minimos",
             "valor": deficit.get("metros_minimos"), "nota": "minimo de la clase, si existe"},
            {"fuente": "motor.score", "ref": f"opcion.{elegida['id']}", "valor": elegida.get("score"),
             "nota": FORMULA_SCORE},
        ],
    }


def _sin_datos(e: estado.EstadoAtleta, fecha: str, semana: str | None, pesos: dict) -> dict:
    receta = {"clave": "sin_datos", "sesion": "No prescribir: faltan datos en la ventana",
              "metros": 0, "ritmo": "", "porque": "sin datos no se inventa una sesion"}
    a = _opcion("A", receta, None, "sin_datos", efecto=2.0, confianza=0.9, riesgo=0.1, coste=0.1,
                porque=receta["porque"], pesos=pesos)
    b = _opcion("B", {"clave": "mantener", "sesion": "Mantener lo que ya hay", "metros": 0, "ritmo": "",
                      "porque": "no anadir carga mientras faltan datos"}, None, "mantener",
                efecto=1.0, confianza=0.9, riesgo=0.1, coste=0.1,
                porque="no anadir carga mientras faltan datos", pesos=pesos)
    _elegir([a, b])
    return {
        "id": f"REC-PREVIEW-{e.estado_id}-sin-datos", "fecha": fecha, "ambito": "semana",
        "semana": semana, "knowledge_version": e.version_conocimiento, "estado_id": e.estado_id,
        "prioridad": 1, "problema": "Sin datos suficientes para decidir",
        "estado": {"estado_id": e.estado_id, "fecha": e.fecha, "clase": "sin_datos", "confianza": "baja"},
        "opciones": [a, b], "evidencia": _evidencia("sin_datos"), "parametros": [],
        "contraindicaciones": [], "metrica_exito": {"tipo": "datos", "criterio": "que haya parte/series en la ventana",
                                                     "medir_en": _fecha_mas(fecha, 3)},
        "revisar_en": _fecha_mas(fecha, 7),
        "explicacion": ("Que veo: sin datos suficientes en la ventana. Por que importa: sin ellos no se puede "
                        "decir que falta. Que propongo: no prescribir. Como lo medimos: que haya parte/series en la "
                        "ventana. Riesgo: bajo; alternativa: mantener. Revision: " + _fecha_mas(fecha, 7) + "."),
        "confianza": 0.9, "restricciones": [{"tipo": "sin_datos", "descripcion": "faltan datos en la ventana",
                                              "fuente": "estado"}], "pesos": dict(pesos),
        "datos": [{"fuente": "estado", "ref": "ventana", "valor": "sin datos",
                   "nota": "no hay series/partes en la ventana para sostener una sesion"}],
    }


def _derivar(e: estado.EstadoAtleta, fecha: str, semana: str | None, pesos: dict) -> dict:
    a = _opcion("A", {"clave": "seguridad", "sesion": "Parar y consultar a un profesional (no prescribir sesion)",
                      "metros": 0, "ritmo": "", "porque": "dolor o lesion declarada: no se adapta ni se trata"},
                None, "derivar", efecto=8.0, confianza=0.95, riesgo=0.0, coste=0.0,
                porque="dolor o lesion declarada: parar y derivar (T.7)", pesos=pesos)
    b = _opcion("B", {"clave": "seguridad", "sesion": "No prescribir carga hasta que lo valore un profesional",
                      "metros": 0, "ritmo": "", "porque": "la seguridad manda sobre el plan"},
                None, "derivar", efecto=5.0, confianza=0.9, riesgo=0.1, coste=0.0,
                porque="no prescribir carga mientras haya dolor", pesos=pesos)
    _elegir([a, b])
    return {
        "id": f"REC-PREVIEW-{e.estado_id}-derivar", "fecha": fecha, "ambito": "semana", "semana": semana,
        "knowledge_version": e.version_conocimiento, "estado_id": e.estado_id,
        "prioridad": 1, "problema": "Dolor o lesion declarada",
        "estado": {"estado_id": e.estado_id, "fecha": e.fecha, "clase": "dolor_lesion", "confianza": "alta"},
        "opciones": [a, b], "evidencia": ["T.7"], "parametros": [],
        "contraindicaciones": ["dolor_lesion", "lesion_activa"],
        "metrica_exito": {"tipo": "seguridad", "criterio": "no hay ninguna sesion prescrita con dolor",
                          "medir_en": fecha},
        "revisar_en": _fecha_mas(fecha, 7),
        "explicacion": ("Que veo: hay dolor o lesion declarada. Por que importa: no se trata ni se adapta por cuenta "
                        "propia (T.7). Que propongo: parar y consultar a un profesional. Como lo medimos: que no haya "
                        "sesion prescrita. Riesgo: alto si se fuerza; alternativa: no prescribir carga. Revision: "
                        + _fecha_mas(fecha, 7) + "."),
        "confianza": 0.95, "restricciones": [{"tipo": "dolor_lesion", "descripcion": "dolor o lesion declarada",
                                               "fuente": "estado"}], "pesos": dict(pesos),
        "datos": [{"fuente": "estado", "ref": "dolor_lesion", "valor": "si",
                   "nota": "dolor/lesion declarada: seguridad antes que entrenamiento (T.7)"}],
    }


def _mantener(e: estado.EstadoAtleta, fecha: str, semana: str | None, pesos: dict) -> dict:
    a = _opcion("A", {"clave": "mantener", "sesion": "Mantener la semana tal como esta", "metros": 0, "ritmo": "",
                      "porque": "no hay un deficit que exija cambiar la sesion"}, None, "mantener",
                efecto=1.0, confianza=0.9, riesgo=0.2, coste=0.1, porque="no anadir carga", pesos=pesos)
    b = _opcion("B", {"clave": "descarga", "sesion": estimulos.RECETAS["descarga"]["sesion"],
                      "metros": estimulos.RECETAS["descarga"]["metros"], "ritmo": "",
                      "porque": "si prefieres una semana suave"}, None, "alternativa",
                efecto=1.0, confianza=0.6, riesgo=0.2, coste=1.0, porque="semana suave", pesos=pesos)
    _elegir([a, b])
    return {
        "id": f"REC-PREVIEW-{e.estado_id}-mantener", "fecha": fecha, "ambito": "semana", "semana": semana,
        "knowledge_version": e.version_conocimiento, "estado_id": e.estado_id, "prioridad": 1,
        "problema": "No hay un deficit que exija cambiar la semana",
        "estado": {"estado_id": e.estado_id, "fecha": e.fecha, "clase": "mantener", "confianza": "media"},
        "opciones": [a, b], "evidencia": _evidencia("mantener") or _evidencia("sin_datos"), "parametros": [],
        "contraindicaciones": [],
        "metrica_exito": {"tipo": "adherencia", "criterio": "mantener el volumen y no anadir carga",
                          "medir_en": _fecha_mas(fecha, 7)},
        "revisar_en": _fecha_mas(fecha, 7),
        "explicacion": ("Que veo: no hay un deficit que exija cambiar la semana. Por que importa: no se anade carga "
                        "sin motivo. Que propongo: mantener. Como lo medimos: mantener el volumen. Riesgo: bajo; "
                        "alternativa: descarga. Revision: " + _fecha_mas(fecha, 7) + "."),
        "confianza": 0.9, "restricciones": [], "pesos": dict(pesos),
        "datos": [{"fuente": "estado", "ref": "deficits", "valor": "ninguno",
                   "nota": "no hay un deficit que exija cambiar la semana"}],
    }


def _deficits_por_defecto(cn, fecha: str):
    from . import valoracion
    try:
        d = date.fromisoformat(fecha)
        dias = (date.fromisoformat(plan.OBJETIVO_B["fecha"]) - d).days
    except (KeyError, TypeError, ValueError):
        dias = 0
    try:
        m = valoracion._falta_y_toca(cn, d, _objetivo_100(), dias)      # noqa: SLF001
        ventana = m.get("ventana") or {}
        return m.get("deficits") or [], bool(ventana.get("dias_con_dato")), m
    except Exception:
        return [], False, {}


def generar(cn: sqlite3.Connection, fecha: str | None = None, semana: str | None = None, *,
            deficits: list[dict] | None = None, estado_obj: estado.EstadoAtleta | None = None,
            pesos: dict | None = None, tests=None, ocupados=None, cargados=None,
            material_disponible=None, piscina=None, sin_datos: bool = False) -> dict:
    """Genera la decisión v2 (1-3 prioridades, 2-4 opciones por prioridad). No escribe en la base."""
    fecha = (fecha or date.today().isoformat())[:10]
    e = estado_obj or estado.calcular(cn, fecha)
    pesos = dict(pesos or carga_pesos())
    semana = semana or _semana_de(fecha)
    tests = tuple(tests if tests is not None else plan.pruebas_de(fecha))
    ocupados = tuple(ocupados or ())
    cargados = dict(cargados if cargados is not None else fuerza.cargados_de_la_semana(cn, fecha))
    if _dolor(e):
        recs = [_derivar(e, fecha, semana, pesos)]
    else:
        if deficits is None:
            deficits, hay_datos, _ = _deficits_por_defecto(cn, fecha)
            sin_datos = sin_datos or not hay_datos
        if sin_datos:
            recs = [_sin_datos(e, fecha, semana, pesos)]
        elif not deficits:
            recs = [_mantener(e, fecha, semana, pesos)]
        else:
            recs = []
            dias_usados: set[str] = set()
            for i, d in enumerate(deficits[:3], 1):
                rec = _recomendacion(i, d, e, fecha, semana, tests, ocupados, cargados,
                                     _objetivo_100(), pesos, dias_usados)
                recs.append(rec)
                elegida = next(o for o in rec["opciones"] if o.get("recomendada"))
                if elegida.get("dia"):
                    dias_usados.add(elegida["dia"])
    restricciones_globales = []
    piscina_estado = _metrica_estado(e, "piscina_habitual")
    piscina_efectiva = piscina if piscina is not None else (
        piscina_estado.valor if piscina_estado and piscina_estado.estado != "sin_datos" else None)
    if piscina_efectiva not in (None, 25, 50):
        restricciones_globales.append({"tipo": "piscina",
                                       "descripcion": f"piscina {piscina_efectiva} m: los ritmos no son "
                                                      "comparables con 25/50",
                                       "fuente": "estado.piscina_habitual"})
    if material_disponible is not None and not material_disponible:
        restricciones_globales.append({"tipo": "material",
                                       "descripcion": "sin material disponible: no se proponen sesiones que lo exijan",
                                       "fuente": "entrada"})
    for rec in recs:
        rec["restricciones"] = list(rec.get("restricciones") or []) + list(restricciones_globales)
    return {"motor": "v2", "fecha": fecha, "semana": semana, "estado_id": e.estado_id,
            "knowledge_version": e.version_conocimiento, "estado": e.a_dict(incluir_generado=False),
            "recomendaciones": recs, "pesos": pesos, "formula_score": FORMULA_SCORE,
            "restricciones": sorted({r["tipo"] for rec in recs for r in rec.get("restricciones", [])}),
            "sin_datos": any(r["estado"].get("clase") == "sin_datos" for r in recs),
            "material_disponible": material_disponible, "piscina": piscina_efectiva}


def v1(cn: sqlite3.Connection, fecha: str | None = None, semana: str | None = None, *,
       deficits: list[dict] | None = None, estado_obj: estado.EstadoAtleta | None = None,
       tests=None, cargados=None) -> dict:
    """Foto del motor v1 (una recomendación por día), sin escribir en la base."""
    fecha = (fecha or date.today().isoformat())[:10]
    semana = semana or _semana_de(fecha)
    e = estado_obj or estado.calcular(cn, fecha)
    if deficits is None:
        deficits, _, m = _deficits_por_defecto(cn, fecha)
        reparto = m.get("reparto") or {}
    else:
        try:
            reparto = planificador.propuesta_semana(
                deficits, objetivo_100=_objetivo_100(),
                tests=tuple(tests if tests is not None else plan.pruebas_de(fecha)),
                km_semana=None, fijos_m=None,
                cargados=dict(cargados if cargados is not None else fuerza.cargados_de_la_semana(cn, fecha)))
        except Exception:
            reparto = {}
    recs = []
    for dia, s in sorted((reparto.get("dias") or {}).items(), key=lambda kv: planificador.DIAS.index(kv[0])):
        recs.append({"dia": dia, "clase": s.get("clase"), "sesion": s.get("sesion"),
                     "metros": s.get("metros"), "ritmo_desde": s.get("ritmo_desde"),
                     "ritmo_hasta": s.get("ritmo_hasta"), "porque": s.get("porque")})
    return {"motor": "v1", "fecha": fecha, "semana": semana, "estado_id": e.estado_id,
            "knowledge_version": e.version_conocimiento, "recomendaciones": recs,
            "falta": reparto.get("falta"), "avisos": reparto.get("avisos") or []}


def dual(cn: sqlite3.Connection, fecha: str | None = None, semana: str | None = None, *,
         deficits: list[dict] | None = None, estado_obj: estado.EstadoAtleta | None = None,
         tests=None, cargados=None, carpeta: str | None = None) -> dict:
    """Genera v1 y v2 y deja la comparación en `data/derived/recomendacion/dual_*.json`. No toca la base."""
    fecha = (fecha or date.today().isoformat())[:10]
    a = v1(cn, fecha, semana, deficits=deficits, estado_obj=estado_obj, tests=tests, cargados=cargados)
    b = generar(cn, fecha, semana, deficits=deficits, estado_obj=estado_obj, tests=tests, cargados=cargados)
    v1_pares = {(x.get("dia"), x.get("clase")) for x in a.get("recomendaciones") or []}
    v1_clases = {x.get("clase") for x in a.get("recomendaciones") or [] if x.get("clase")}
    v2_clases = {p.get("estado", {}).get("clase") for p in b.get("recomendaciones") or []
                 if p.get("estado", {}).get("clase")}
    clasificacion = {"mejora": sorted(v2_clases - v1_clases),
                     "equivalente": sorted(v2_clases & v1_clases),
                     "regresion": sorted(v1_clases - v2_clases),
                     "error": []}
    dif = {"v1_sesiones": len(a.get("recomendaciones") or []),
           "v2_prioridades": len(b.get("recomendaciones") or []),
           "v2_opciones": sum(len(p.get("opciones") or []) for p in b.get("recomendaciones") or []),
           "solo_v1": sorted(str(x) for x in v1_pares if x not in {(y.get("estado", {}).get("clase"), None)
                                                                    for y in b.get("recomendaciones") or []}),
           "solo_v2": clasificacion["mejora"],
           "clasificacion": clasificacion,
           "n": 0}
    dif["n"] = len(dif["solo_v1"]) + len(dif["solo_v2"])
    salida = {"fecha": fecha, "semana": b.get("semana"), "v1": a, "v2": b,
              "clasificacion": clasificacion, "diferencias": dif, "formula_score": FORMULA_SCORE}
    destino = carpeta or os.path.join("data", "derived", "recomendacion")
    os.makedirs(destino, exist_ok=True)
    ruta = os.path.join(destino, f"dual_{fecha}.json")
    with open(ruta, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    salida["ruta"] = ruta
    return salida


def ejecutar(cn: sqlite3.Connection, modo: str | None = None, **kwargs) -> dict:
    """Punto de entrada que respeta `MOTOR_RECOMENDACION` (v1/v2/dual) para integraciones."""
    modo = (modo or modo_motor()).lower()
    if modo == "v1":
        return v1(cn, **kwargs)
    if modo == "dual":
        return dual(cn, **kwargs)
    return generar(cn, **kwargs)


# --------------------------------------------------------------------------- esquema y persistencia

def validar_recomendacion(r: dict) -> list[str]:
    """Valida el esquema mínimo de F5-01. Devuelve lista de errores; vacía = válida."""
    if not isinstance(r, dict):
        return ["la recomendacion no es un objeto"]
    errores = []
    for k in ("id", "fecha", "ambito", "semana", "knowledge_version", "estado_id", "prioridad",
              "problema", "estado", "opciones", "evidencia", "parametros", "contraindicaciones",
              "metrica_exito", "revisar_en", "explicacion"):
        if k not in r:
            errores.append(f"falta {k}")
    if r.get("ambito") not in ("sesion", "semana", "bloque"):
        errores.append("ambito invalido")
    for k in ("fecha", "knowledge_version", "estado_id", "problema", "revisar_en", "explicacion"):
        if not str(r.get(k) or "").strip():
            errores.append(f"{k} no puede estar vacio")
    if r.get("id") is None or not str(r.get("id")).strip():
        errores.append("id no puede estar vacio")
    if not isinstance(r.get("estado"), dict) or not r.get("estado"):
        errores.append("estado debe ser un objeto con datos")
    if not isinstance(r.get("prioridad"), int) or not 1 <= r["prioridad"] <= 3:
        errores.append("prioridad debe ser 1-3")
    opciones = r.get("opciones")
    if not isinstance(opciones, list) or not 2 <= len(opciones) <= 4:
        errores.append("opciones debe tener 2-4")
        opciones = []
    ids = [o.get("id") for o in opciones if isinstance(o, dict)]
    if len(ids) != len(set(ids)):
        errores.append("ids de opcion duplicados")
    recomendadas = [o for o in opciones if isinstance(o, dict) and o.get("recomendada")]
    if len(recomendadas) != 1:
        errores.append("debe haber exactamente una opcion recomendada")
    for o in opciones:
        if not isinstance(o, dict):
            errores.append("opcion no es objeto")
            continue
        for k in ("id", "recomendada", "sesion", "dia", "metros", "ritmo", "efecto", "confianza",
                  "riesgo", "coste", "porque"):
            if k not in o:
                errores.append(f"opcion {o.get('id')}: falta {k}")
        for k in ("id", "sesion", "porque"):
            if not str(o.get(k) or "").strip():
                errores.append(f"opcion {o.get('id')}: {k} no puede estar vacio")
        if not isinstance(o.get("descartada"), bool):
            errores.append(f"opcion {o.get('id')}: descartada debe ser booleano")
        if o.get("descartada") and not str(o.get("motivo_descarte") or "").strip():
            errores.append(f"opcion {o.get('id')}: descartada sin motivo_descarte")
        if not isinstance(o.get("metros"), (int, float)) or o.get("metros") < 0:
            errores.append(f"opcion {o.get('id')}: metros invalido")
        if not isinstance(o.get("confianza"), (int, float)) or not 0 <= o["confianza"] <= 1:
            errores.append(f"opcion {o.get('id')}: confianza fuera de 0-1")
        for k in ("efecto", "riesgo", "coste", "score"):
            if not isinstance(o.get(k), (int, float)):
                errores.append(f"opcion {o.get('id')}: {k} no numerico")
    validas = [o for o in opciones if isinstance(o, dict) and not o.get("descartada")]
    if recomendadas:
        elegida = recomendadas[0]
        if elegida.get("descartada"):
            errores.append("la opcion recomendada no puede estar descartada")
        if validas:
            mejor = min(validas, key=_clave_opcion)
            if _clave_opcion(elegida) != _clave_opcion(mejor):
                errores.append("la opcion recomendada no es la de mayor score entre las validas")
    if not isinstance(r.get("evidencia"), list) or not r.get("evidencia"):
        errores.append("evidencia debe ser una lista con al menos un ID")
    if not isinstance(r.get("parametros"), list):
        errores.append("parametros debe ser lista")
    if not isinstance(r.get("contraindicaciones"), list):
        errores.append("contraindicaciones debe ser lista")
    met = r.get("metrica_exito")
    if not isinstance(met, dict) or any(not str(met.get(k) or "").strip()
                                        for k in ("tipo", "criterio", "medir_en")):
        errores.append("metrica_exito incompleta")
    if not isinstance(r.get("explicacion"), str) or not r["explicacion"].strip():
        errores.append("explicacion vacia")
    return errores


def validar_salida(salida: dict) -> list[str]:
    recs = salida.get("recomendaciones") if isinstance(salida, dict) else None
    if not isinstance(recs, list) or not recs:
        return ["la salida no tiene recomendaciones"]
    errores = []
    for i, r in enumerate(recs):
        errores.extend(f"recomendacion {i}: {e}" for e in validar_recomendacion(r))
    return errores


def guardar(cn: sqlite3.Connection, salida: dict) -> list[int]:
    """Persiste la salida v2 en `recomendacion`, `recomendacion_opcion` y datos. Solo con `--guardar`."""
    errores = validar_salida(salida)
    if errores:
        raise ValueError("; ".join(errores))
    ids = []
    for r in salida["recomendaciones"]:
        cur = cn.execute(
            """INSERT INTO recomendacion
               (fecha, ambito, semana, titulo, cuerpo, origen, creada_en, knowledge_version, estado_id,
                prioridad, elegida, metrica_exito_json, revisar_en, confianza)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["fecha"], r["ambito"], r.get("semana"), r["problema"], r["explicacion"], "motor_v2",
             db.ahora(), r["knowledge_version"], r["estado_id"], r["prioridad"],
             next(o["id"] for o in r["opciones"] if o.get("recomendada")),
             json.dumps(r["metrica_exito"], ensure_ascii=False, sort_keys=True), r["revisar_en"], r["confianza"]))
        rid = int(cur.lastrowid)
        r["id"] = rid
        ids.append(rid)
        for d in r.get("datos") or []:
            cn.execute("INSERT INTO recomendacion_dato (recomendacion_id, fuente, ref, valor, nota) VALUES (?,?,?,?,?)",
                       (rid, _texto(d.get("fuente")), _texto(d.get("ref")),
                        None if d.get("valor") is None else str(d.get("valor")), _texto(d.get("nota"))))
        try:
            from . import conocimiento_toml
            conocimiento = conocimiento_toml.cargar()
            parametros = {p.id: p for p in conocimiento.parametros}
        except Exception:
            parametros = {}
        for pa in r.get("parametros") or []:
            p = parametros.get(str(pa))
            cn.execute("INSERT INTO recomendacion_dato (recomendacion_id, fuente, ref, valor, nota) VALUES (?,?,?,?,?)",
                       (rid, "parametro", str(pa),
                        None if p is None else str(p.valor),
                        (p.nombre + (f" ({p.unidad})" if p.unidad else "")) if p else "parametro no encontrado"))
        for ev in r.get("evidencia") or []:
            cn.execute("INSERT INTO recomendacion_dato (recomendacion_id, fuente, ref, valor, nota) VALUES (?,?,?,?,?)",
                       (rid, "evidencia", str(ev), "—", "sostiene la recomendacion"))
        for o in r["opciones"]:
            cn.execute(
                """INSERT OR REPLACE INTO recomendacion_opcion
                   (recomendacion_id, opcion_id, recomendada, sesion_json, efecto_esperado, confianza,
                    riesgo, coste, porque, score, descartada, motivo_descarte)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rid, o["id"], 1 if o.get("recomendada") else 0, json.dumps(o, ensure_ascii=False, sort_keys=True),
                 o.get("efecto_esperado"), o.get("confianza"), o.get("riesgo_etiqueta"), o.get("coste_etiqueta"),
                 o.get("porque"), o.get("score"), 1 if o.get("descartada") else 0, o.get("motivo_descarte")))
        reglas = {}
        clase = (r.get("estado") or {}).get("clase")
        if clase in MOTIVA:
            reglas[MOTIVA[clase]] = "motiva"
        for ev in r.get("evidencia") or []:
            reglas.setdefault(str(ev), "evidencia")
        reglas.setdefault("R6", "limita")
        if any(x.get("tipo") == "prueba" for x in r.get("restricciones") or []):
            reglas["R7"] = "avisa"
        if any(x.get("tipo") == "material" for x in r.get("restricciones") or []):
            reglas["R8"] = "avisa"
        for regla_id, papel in reglas.items():
            cn.execute("INSERT OR REPLACE INTO recomendacion_regla (recomendacion_id, regla_id, papel) VALUES (?,?,?)",
                       (rid, regla_id, papel))
    cn.commit()
    return ids


def modo_motor() -> str:
    """Flag de recomendación. F9 activa v2 por defecto; v1 queda para rollback."""
    valor = (os.environ.get("MOTOR_RECOMENDACION") or "").strip().lower()
    return valor if valor in ("v1", "v2", "dual") else "v2"
