"""La fuerza: la dosis preventiva, el aviso de abandono y lo que carga (V1.4-01, V1.4-02, V1.4-03).

De donde sale: anexo T, seccion T.7. La dosis (12 semanas, 2 sesiones por semana, 5 ejercicios, muchas
repeticiones) se **lee del anexo como dato**, no se escribe aqui: si cambia la fuente, cambia lo que dice el
motor. Y lo no negociable tambien viene de ahi: esto no prescribe rehabilitacion ni trata dolor; con dolor, parar
y ver a un profesional.

La carga la calcula `gimnasio.carga_semanal` (lo que de verdad se apunto): aqui se decide que cuenta como fuerza
intensa y que dias ya estan cargados, para que el reparto del agua no ponga calidad encima de la fuerza.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta

from . import conocimiento, db, gimnasio

# El unico numero que no viene del anexo: a partir de aqui una sesion se considera intensa. El RPE es 1-10, asi que
# 8 es "duro" en la escala del atleta. Va aqui y se dice, en vez de repartirlo por el codigo.
RPE_DURO = 8

# Lo que se lee de T.7 (12 semanas, dos sesiones, cinco ejercicios, muchas repeticiones) y sirve de suelo si el
# anexo cambia de redaccion: si el anexo dice otra cosa, manda el anexo (la prueba lo comprueba).
DOSIS_POR_DEFECTO = {"semanas": 12, "sesiones_semana": 2, "ejercicios": 5, "reps_min": 12}

# Grupos de la plantilla que cuentan para la dosis preventiva del hombro y el core (T.7: "el core tambien cuenta").
GRUPOS_QUE_CUENTAN = ("hombro", "core", "lumbares", "triceps", "espalda", "pecho")

# Palabras con las que el atleta declara dolor o molestia. Con cualquiera de ellas, el motor para: no adapta.
PALABRAS_DOLOR = ("duele", "dolor", "molestia", "pinchazo", "tiron", "tirón", "inflamad", "sobrecarga")


def _reps(rango) -> str:
    a, b = rango
    return f"{a}-{b} repeticiones"


def dosis_de_la_fuente() -> dict:
    """La dosis preventiva leida del anexo T.7 (V1.4-02).

    El anexo dice: "doce semanas de ... dos sesiones semanales ... cinco ejercicios" y "muchas repeticiones". Se
    sacan de ahi; si no se pueden leer, queda el suelo declarado en `DOSIS_POR_DEFECTO` y el grado baja a criterio.
    """
    s = conocimiento.seccion("T.7") or {}
    texto = (s.get("texto") or "").lower()
    d = dict(DOSIS_POR_DEFECTO)
    leido = bool(texto)
    m = re.search(r"doce semanas|(\d+)\s*semanas", texto)
    if m:
        d["semanas"] = int(m.group(1)) if m.group(1) else 12
    if "dos sesiones" in texto:
        d["sesiones_semana"] = 2
    else:
        m = re.search(r"(\d+)\s*sesiones?\s*semanales?", texto)
        if m:
            d["sesiones_semana"] = int(m.group(1))
    if "cinco ejercicios" in texto:
        d["ejercicios"] = 5
    else:
        m = re.search(r"(\d+)\s*ejercicios", texto)
        if m:
            d["ejercicios"] = int(m.group(1))
    return {"dosis": d, "leido_del_anexo": leido}


def _semana_de(hoy: str | None = None) -> tuple[str, str]:
    """La semana natural (lunes a domingo) que contiene esa fecha: es como se cuentan "dos por semana"."""
    d = date.fromisoformat((hoy or db.ahora()[:10])[:10])
    lunes = d - timedelta(days=d.weekday())
    return lunes.isoformat(), (lunes + timedelta(days=6)).isoformat()


def carga_semanal(cn: sqlite3.Connection, desde: str | None = None, hasta: str | None = None) -> dict:
    """La carga de fuerza de un tramo (por defecto, la semana natural de hoy), con su parte de agua.

    Es la puerta que usan el reparto y el portal: `gimnasio.carga_semanal` dice lo que se apunto, y aqui se anade
    lo que eso significa para el agua (que dias ya estan cargados y cuales son intensos).
    """
    if not desde:
        desde, hasta = _semana_de()
    return gimnasio.carga_semanal(cn, desde, hasta)


def dosis_preventiva(cn: sqlite3.Connection, hoy: str | None = None) -> dict:
    """La dosis preventiva que tiene respaldo (T.7): si esta sin empezar, a medias o cumplida.

    Sin ninguna sesion de gimnasio **no** se dice "hecha": se dice sin empezar, y se cita T.7. Con las sesiones de
    la semana que pide la fuente, se dice cumplida.
    """
    lunes, domingo = _semana_de(hoy)
    c = carga_semanal(cn, lunes, domingo)
    d = dosis_de_la_fuente()["dosis"]
    hechas = c["sesiones"]
    if hechas == 0:
        estado = "sin empezar"
    elif hechas >= d["sesiones_semana"]:
        estado = "cumplida"
    else:
        estado = "a medias"
    ficha = conocimiento.fuente_de("fuerza_y_hombro")
    plantilla = [e for e in gimnasio.catalogo(cn) if (e.get("grupo") or "").lower() in GRUPOS_QUE_CUENTAN]
    return {
        "estado": estado, "hechas": hechas, "dosis": d, "semana": [lunes, domingo],
        "carga": c, "cita": ficha["secciones"], "grado": ficha["grado"], "fuente": ficha["frase"],
        "de_tu_plantilla": [e["nombre"] for e in plantilla],
        "faltan_de_la_plantilla": max(0, d["ejercicios"] - len(plantilla)),
    }


def aviso_abandono(cn: sqlite3.Connection, hoy: str | None = None, semanas: int = 3) -> dict:
    """Si llevas tres semanas sin gimnasio, se dice, con lo que dice T.7 de por que importa (V1.4-02)."""
    hoy = (hoy or db.ahora()[:10])[:10]
    ultima = cn.execute("SELECT MAX(fecha) FROM gimnasio_sesion WHERE fecha IS NOT NULL").fetchone()[0]
    dias = None
    if ultima:
        dias = (date.fromisoformat(hoy) - date.fromisoformat(ultima[:10])).days
    c = carga_semanal(cn, *_semana_de(hoy))
    ficha = conocimiento.fuente_de("fuerza_y_hombro")
    if c["sesiones"] >= DOSIS_POR_DEFECTO["sesiones_semana"]:
        return {"aviso": False, "texto": "", "ultima": ultima, "dias": dias, "cita": ficha["secciones"]}
    if not ultima:
        return {"aviso": True, "ultima": None, "dias": None, "cita": ficha["secciones"],
                "texto": "No hay ni una sesion de gimnasio apuntada: la dosis preventiva del hombro esta sin empezar."}
    if dias is not None and dias >= semanas * 7:
        return {"aviso": True, "ultima": ultima, "dias": dias, "cita": ficha["secciones"],
                "texto": f"Llevas {dias} dias sin gimnasio (ultima, el {ultima[:10]}): la dosis que sostiene el "
                         f"hombro pierde sentido si se deja; lo agudo no sirve de nada."}
    return {"aviso": False, "ultima": ultima, "dias": dias, "cita": ficha["secciones"], "texto": ""}


def dolor_declarado(cn: sqlite3.Connection, desde: str | None = None) -> list[dict]:
    """Las sesiones donde el atleta ha declarado dolor o molestia. Con eso, el motor no propone: para (T.7)."""
    desde = (desde or "0000-01-01")[:10]
    fuera = []
    for f in cn.execute("SELECT fecha, notas FROM gimnasio_sesion WHERE fecha >= ? ORDER BY fecha DESC", (desde,)):
        notas = (f["notas"] or "").lower()
        if any(p in notas for p in PALABRAS_DOLOR):
            fuera.append({"fecha": f["fecha"], "notas": f["notas"]})
    for f in cn.execute("SELECT fecha, molestias FROM gimnasio_peticion WHERE fecha >= ? ORDER BY fecha DESC", (desde,)):
        mol = (f["molestias"] or "").lower()
        if any(p in mol for p in PALABRAS_DOLOR):
            fuera.append({"fecha": f["fecha"], "notas": f["molestias"]})
    return fuera


def aviso_seguridad(cn: sqlite3.Connection, desde: str | None = None) -> dict | None:
    """Si hay dolor declarado, el unico consejo es parar y que lo vea un profesional: nada de rehabilitacion (T.7)."""
    casos = dolor_declarado(cn, desde)
    if not casos:
        return None
    ficha = conocimiento.fuente_de("fuerza_y_hombro")
    return {"aviso": True, "casos": casos, "cita": ficha["secciones"],
            "texto": "Hay dolor o molestia apuntada: esto no adapta el entrenamiento ni trata nada. Parar esa parte "
                     "y que la vea un profesional (fisio); el plan de agua no se toca por su cuenta."}


def dias_con_carga(cn: sqlite3.Connection, desde: str, hasta: str) -> dict:
    """Que dias de ese tramo ya llevan carga de fuerza, y cuales son intensos (V1.4-03).

    Se usa antes de repartir el agua: un dia intenso de fuerza no es sitio para calidad, y el dia siguiente tampoco
    (la fuerza se paga despues). Devuelve `{"fechas": [...], "intensos": [...], "por_dia": {...}}`.
    """
    c = gimnasio.carga_semanal(cn, desde, hasta)
    por_dia = {}
    for d in c["por_dia"]:
        por_dia[d["fecha"]] = {"sesiones": d["sesiones"], "series": d["series"], "rpe_max": d["rpe_max"],
                               "intensa": bool(d["rpe_max"] and d["rpe_max"] >= RPE_DURO), "ejercicios": d["ejercicios"]}
    return {"fechas": sorted(por_dia), "intensos": sorted(k for k, v in por_dia.items() if v["intensa"]),
            "por_dia": por_dia, "desde": desde, "hasta": hasta}


def cargados_de_la_semana(cn: sqlite3.Connection, hoy: str | None = None) -> dict[str, dict]:
    """Los dias de esta semana que ya llevan carga ajena al plan: la fuerza y lo que manda el entrenador (V1.3-05).

    Es lo que se le pasa al reparto para que no ponga calidad encima de una sesion de fuerza ni del dia siguiente. La
    recuperacion que pide cada dia no se inventa: una sesion declarada dura (RPE 8 o mas) no esta recuperada a las
    24 h si a las 48 (T.8 [23]); una sesion de agua del entrenador, un dia (T.4 [17]); el resto de lo apuntado, un
    dia tambien, porque sin RPE no hay dato para pedir mas `[criterio]`.
    """
    lunes, domingo = _semana_de(hoy)
    dias: dict[str, dict] = {}
    de_fuerza = dias_con_carga(cn, lunes, domingo)
    for fecha, v in de_fuerza["por_dia"].items():
        dia = gimnasio.dia_de(fecha)
        if not dia:
            continue
        detalle = (f"gimnasio: {v['sesiones']} sesion(es), {v['series']} series"
                   + (f", RPE {v['rpe_max']}" if v["rpe_max"] else ", sin RPE apuntado"))
        dias[dia] = {"de": "gimnasio", "fecha": fecha, "clase": "fuerza", "intensa": v["intensa"],
                     "recuperacion": 48.0 if v["intensa"] else 24.0, "detalle": detalle,
                     "aviso": (f"el {dia} ya lleva carga de fuerza" + (" intensa" if v["intensa"] else "")
                               + " (T.7): no se le pone calidad encima y el dia siguiente va suave")}
    # El entrenador entra por dos vias, y las dos valen: la linea del apunte (`apunte.quien`) y el parte que el
    # atleta marca en el chat como "con el entrenador" (`parte.compania`). Si estan las dos, manda el apunte, que
    # es el que dice los metros a mano.
    suyas: dict[str, float] = {}
    for f in cn.execute("SELECT fecha, distancia_m FROM apunte WHERE quien = 'entrenador'"
                        " AND fecha >= ? AND fecha <= ? ORDER BY fecha", (lunes, domingo)):
        suyas.setdefault((f["fecha"] or "")[:10], f["distancia_m"] or 0.0)
    for f in cn.execute("SELECT fecha, metros FROM parte WHERE compania = 'entrenador'"
                        " AND fecha >= ? AND fecha <= ? ORDER BY fecha", (lunes, domingo)):
        suyas.setdefault((f["fecha"] or "")[:10], f["metros"] or 0.0)
    for fecha, metros in suyas.items():
        dia = gimnasio.dia_de(fecha)
        if not dia or dia in dias:
            continue
        dias[dia] = {"de": "entrenador", "fecha": fecha, "clase": "duro", "intensa": True,
                     "recuperacion": 24.0,
                     "detalle": f"la sesion del entrenador ({int(metros)} m)" if metros else "la sesion del entrenador",
                     "aviso": (f"el {dia} ya hay carga (la sesion del entrenador): el dia siguiente no lleva "
                               "trabajo de calidad")}
    return dias


def datos(cn: sqlite3.Connection, hoy: str | None = None) -> dict:
    """El bloque de fuerza para el cuadro de mando: la dosis con su estado, el aviso, el seguro y la carga (V1.4-02).

    El portal no calcula nada de esto: lo pinta. Si no hay ni una fila de gimnasio, el estado es "sin empezar" y la
    cita (T.7) sigue ahi: no se enseña un hueco vacio sin decir de donde saldria el dato.
    """
    d = dosis_preventiva(cn, hoy)
    a = aviso_abandono(cn, hoy)
    seg = aviso_seguridad(cn)
    lunes, domingo = _semana_de(hoy)
    c = gimnasio.carga_semanal(cn, lunes, domingo)
    return {
        "dosis": d["dosis"], "estado": d["estado"], "hechas": d["hechas"], "cita": d["cita"],
        "fuente": d.get("fuente"), "grado": d.get("grado"),
        "de_tu_plantilla": d.get("de_tu_plantilla") or [],
        "faltan_de_la_plantilla": d.get("faltan_de_la_plantilla"),
        "semana": {"desde": lunes, "hasta": domingo, "sesiones": c["sesiones"], "series": c["series"],
                   "repeticiones": c["repeticiones"], "volumen_kg": c["volumen_kg"],
                   "con_rpe": c["con_rpe"], "por_dia": c["por_dia"]},
        "abandono": a, "seguridad": seg,
        "nota": ("El reloj no guarda ejercicios, series ni pesos: esto sale de lo que se apunta a mano. Sin RPE, "
                 "una sesion cuenta igual, pero no se puede decir si fue dura."),
    }


def texto(cn: sqlite3.Connection, hoy: str | None = None) -> str:
    """La fuerza para la consola: la dosis, el aviso y la carga de la semana."""
    d = dosis_preventiva(cn, hoy)
    a = aviso_abandono(cn, hoy)
    seg = aviso_seguridad(cn)
    dd = d["dosis"]
    lineas = [f"Dosis preventiva del hombro (T.7): {dd['sesiones_semana']} sesiones por semana, {dd['ejercicios']} "
              f"ejercicios, muchas repeticiones ({_reps((dd['reps_min'], 20))}), {dd['semanas']} semanas.",
              f"Estado: {d['estado']} (esta semana, {d['hechas']} sesion(es)) | cita: {', '.join(d['cita']) or '-'}"]
    if d["de_tu_plantilla"]:
        lineas.append("De tu plantilla, los que cuentan: " + ", ".join(d["de_tu_plantilla"]))
    if d["faltan_de_la_plantilla"]:
        lineas.append(f"Te faltan {d['faltan_de_la_plantilla']} para los {dd['ejercicios']} de la dosis.")
    if a["aviso"]:
        lineas.append("AVISO: " + a["texto"])
    if seg:
        lineas.append("PARAR: " + seg["texto"] + " Casos: " +
                      ", ".join(f"{c['fecha']} ({c['notas'][:40]})" for c in seg["casos"][:3]))
    c = carga_semanal(cn, *_semana_de(hoy))
    lineas.append(f"Carga de la semana {c['desde']} a {c['hasta']}: {c['sesiones']} sesion(es), "
                  f"{c['series']} series, {c['repeticiones']} repeticiones, "
                  f"{c['volumen_kg'] if c['volumen_kg'] is not None else 'sin kilos'}.")
    return "\n".join(lineas)
