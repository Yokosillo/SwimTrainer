#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""En que dia de la semana cae cada sesion que propone el motor (tarea V1.1-03 del anexo U).

**Por que existe.** `estimulos` saca los deficits y sabe que receta los arregla, pero cada receta traia su dia
preferido escrito a mano (`RECETAS[x]["desde"]`). Con la ventana real del 17/10/2026 eso ponia el 8x100 a ritmo de
prueba y el 8x50 a tope **el mismo jueves**: dos sesiones duras en el mismo dia, y encima despues de las series
largas del martes. Tres cosas mal en una linea de texto.

**Que manda aqui.**

  1. **El calendario pactado** (regla R6): lunes, miercoles y viernes son del entrenador y no se les anade nada;
     el sabado es bici. Al atleta le quedan **martes, jueves y domingo**.
  2. **La recuperacion de cada clase** (`estimulos.CLASES[c]["recuperacion"]`, en horas): dos sesiones duras no
     caen el mismo dia ni en dias seguidos. Una clase que pide 36 h y otra que pide 36 h no caben a 24 h de
     distancia.
  3. **El dia que pide la receta**, que no es capricho: el bloque continuo largo va el domingo, que es cuando hay
     tiempo y no hay que competir con la calidad; las series de calidad van martes y jueves.
  4. **La prioridad del deficit**: si hay mas deficits que dias, los que no caben **no se colocan a la fuerza**:
     salen en `fuera` con su aviso. Un plan que promete cuatro sesiones y solo tiene tres dias no es un plan.

Lo que este modulo NO hace: escribir en la base, decidir por el atleta ni rellenar la semana del entrenador. Solo
coloca las sesiones que el motor propone y dice, en claro, lo que no ha podido colocar.

Uso:
    from . import planificador, series_dia, estimulos
    v = series_dia.ventana(cn, "2026-10-04", "2026-10-17", 75.0)
    d = estimulos.deficits(v, "especifico_400", dias_al_reto=28, objetivo_100=75.0)
    planificador.reparto(d, objetivo_100=75.0)
"""

from __future__ import annotations

from . import estimulos, reglas

# --------------------------------------------------------------------------- el calendario y sus reglas

DIAS: tuple[str, ...] = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")

# Regla R6 (anexo L): los lunes, miercoles y viernes los manda el entrenador y no se les anade nada.
DIAS_ENTRENADOR: tuple[str, ...] = ("lunes", "miercoles", "viernes")
DIA_BICI = "sabado"
DIAS_PROPIOS: tuple[str, ...] = ("martes", "jueves", "domingo")

# Los dos dias con margen para trabajo duro, y el dia del bloque largo continuo.
DIAS_CALIDAD: tuple[str, ...] = ("martes", "jueves")
DIAS_LARGOS: tuple[str, ...] = ("domingo",)

# A partir de cuantas horas de recuperacion una clase cuenta como carga dura. Las suaves (fondo facil, pataleo:
# 12 h) pueden ir pegadas a cualquier cosa; las duras no.
DURO_H = 24.0


def _recuperacion(clase: str) -> float:
    """Las horas que pide recuperar una clase de estimulo. Lo que no es clase (afinar, descarga) no recupera."""
    c = estimulos.CLASES.get(clase) or {}
    return float(c.get("recuperacion") or 0.0)


def _distancia_dias(a: str, b: str) -> int:
    """Cuanto separan dos dias de la semana, en dias (0 el mismo dia, 1 los seguidos por cualquiera de los lados)."""
    i, j = DIAS.index(a), DIAS.index(b)
    return min((i - j) % 7, (j - i) % 7)


def _dias_candidatos(deficit: dict, receta: dict) -> list[str]:
    """Por que dias se puede repartir una sesion, en orden de preferencia."""
    clave = deficit.get("receta") or ""
    if deficit.get("id") in ("afinar", "descarga") or clave == "descarga":
        # El afinado y la descarga no son carga: caben en cualquier dia propio, empezando por el que pide.
        pref = receta.get("desde")
        orden = [pref] if pref in DIAS_PROPIOS else []
        return orden + [d for d in DIAS_PROPIOS if d not in orden]
    if clave == "continuo":
        return list(DIAS_LARGOS)
    pref = receta.get("desde")
    otros = [d for d in DIAS_CALIDAD if d != pref]
    return ([pref] if pref in DIAS_CALIDAD else []) + otros


def _cabe(dia: str, plan: dict, clase: str, vetados: frozenset = frozenset()) -> bool:
    """Si esa sesion cabe ese dia, mirando la recuperacion de lo que ya hay puesto.

    Dos reglas, y las dos son de sentido comun: **dos dias duros no van seguidos**, y entre dos sesiones tiene que
    pasar al menos la recuperacion que pide la que ya estaba (36 h no caben en 24). `vetados` son los dias en que
    no entra trabajo de calidad (el dia de antes de una prueba): ahi solo cabe lo suave.
    """
    if dia in plan:
        return False
    if dia in vetados and _recuperacion(clase) >= DURO_H:
        return False                                # delante de la prueba no se pone calidad
    pide = _recuperacion(clase)
    for otro, s in plan.items():
        otras = float(s.get("recuperacion") or 0.0)
        if pide < DURO_H and otras < DURO_H:
            continue                                # ninguna de las dos es carga: no hay nada que mirar
        sep = _distancia_dias(dia, otro)
        if sep == 1:
            return False                            # pegadas, no
        if 24.0 * sep < max(pide, otras):
            return False                            # la anterior todavia no ha recuperado
    return True


def reparto(deficits: list[dict], objetivo_100: float = 75.0, material: list[str] | None = None,
            ocupados: tuple[str, ...] = (), tests: tuple[str, ...] = (),
            cargados: dict[str, dict] | None = None) -> dict:
    """Reparte las sesiones que piden los deficits por los dias propios de la semana.

    `deficits` = lo que devuelve `estimulos.deficits` (ya con una entrada por clase). Los deficits vienen por
    orden de importancia: los que no caben se quedan en `fuera`, no se apilan. `tests` = los dias de la semana con
    prueba o competicion: ese dia no se prescribe nada y el de antes no admite trabajo de calidad.
    `cargados` = {dia: {...}} de lo que ya lleva carga ajena al plan (la fuerza, la sesion del entrenador): ese dia
    cuenta como ocupado con la recuperacion que traiga, y el de al lado tampoco admite calidad (V1.3-05, V1.4-03).

    Devuelve:
      `semana`  los siete dias, cada uno con de quien es (`entrenador`, `bici`, `test`, `propio` o `libre`);
      `dias`    solo los dias propios con sesion, por dia;
      `fuera`   los deficits que esta semana no caben, con su aviso;
      `avisos`  lo que hay que decirle al atleta en castellano llano.
    """
    tests = tuple(t for t in tests if t in DIAS)
    # El dia de antes de la prueba: no entra calidad (pero si un rodaje suave o nada).
    vetados = frozenset(DIAS[(DIAS.index(t) - 1) % 7] for t in tests) - set(tests)
    plan: dict[str, dict] = {d: {"clase": "duro", "recuperacion": 24.0}
                             for d in (tuple(ocupados) + tests) if d in DIAS}
    ya_cargados = {d: v for d, v in (cargados or {}).items() if d in DIAS}
    for d, v in ya_cargados.items():
        plan[d] = {"clase": v.get("clase") or "duro",
                   "recuperacion": float(v.get("recuperacion") or DURO_H),
                   "de": v.get("de") or "cargado"}
    sitios: dict[str, dict] = {}
    fuera: list[dict] = []
    avisos: list[str] = []

    for d in deficits or []:
        receta = estimulos.RECETAS.get(d.get("receta") or "")
        if not receta:
            continue
        clase = d.get("id") or ""
        puesto = None
        for dia in _dias_candidatos(d, receta):
            if _cabe(dia, plan, clase, vetados):
                puesto = dia
                break
        if puesto is None:
            fuera.append({"id": clase, "titulo": d.get("titulo"), "porque": (
                "solo hay tres dias propios (martes, jueves y domingo) y el entrenador manda los otros, "
                "asi que no cabe una sesion mas")})
            continue
        libre = estimulos.receta_libre(d["receta"], objetivo_100, material)
        sitios[puesto] = {
            "dia": puesto, "clase": clase, "receta": d["receta"], "titulo": d.get("titulo"),
            "sesion": libre.get("sesion"), "ritmo_desde": libre.get("ritmo_desde"),
            "ritmo_hasta": libre.get("ritmo_hasta"), "cada_s": libre.get("cada_s"),
            "porque": d.get("porque"), "seccion_T": list(d.get("seccion_T") or []),
            "grado": d.get("grado") or "criterio", "motivos": list(d.get("motivos") or []),
        }
        plan[puesto] = {"clase": clase, "recuperacion": _recuperacion(clase)}

    semana: list[dict] = []
    for dia in DIAS:
        if dia in sitios:
            semana.append({"dia": dia, "de": "propio", **sitios[dia]})
        elif dia in tests:
            semana.append({"dia": dia, "de": "test", "sesion": None,
                           "nota": "es la prueba: ese dia no se prescribe nada"})
        elif dia in DIAS_ENTRENADOR:
            semana.append({"dia": dia, "de": "entrenador", "sesion": None,
                           "nota": "la manda el entrenador: no se le anade nada (regla R6)"})
        elif dia == DIA_BICI:
            semana.append({"dia": dia, "de": "bici", "sesion": None, "nota": "bici"})
        else:
            semana.append({"dia": dia, "de": "propio", "sesion": None, "nota": "libre"})

    for e in semana:
        v = ya_cargados.get(e["dia"])
        if not v or e.get("sesion") is not None:
            continue
        if e["de"] == "propio":
            e["de"] = v.get("de") or "cargado"
            e["nota"] = v.get("detalle") or "ya lleva carga"
        elif e["de"] == "entrenador":
            e["nota"] = (e.get("nota") or "") + f" | y ademas {v.get('detalle') or 'carga de gimnasio'}"

    puestas = sorted(sitios, key=DIAS.index)
    for t in tests:
        avisos.append(f"el {t} hay prueba: ese dia no se prescribe nada y el de antes no lleva trabajo de calidad")
    if len(puestas) == 1:
        avisos.append(f"esta semana solo cabe una sesion propia de calidad: {puestas[0]}")
    avisos_carga: list[str] = []
    for d, v in ya_cargados.items():
        avisos_carga.append(v.get("aviso") or f"el {d} ya lleva carga ({v.get('de') or 'gimnasio'})")
    avisos.extend(avisos_carga)
    for f in fuera:
        avisos.append(f["porque"])
    if not deficits:
        avisos.append("no hay deficits que repartir: sin datos suficientes o sin hueco que arreglar")
    duracion = sum(_recuperacion(s["clase"]) for s in sitios.values())
    return {"semana": semana, "dias": sitios, "fuera": fuera, "avisos": avisos,
            "cargados": sorted(ya_cargados), "avisos_carga": avisos_carga,
            "orden": list(sitios),          # el orden en que se colocaron = el de importancia de los deficits
            "dias_ocupados": list(ocupados), "dias_de_prueba": list(tests), "vetados": sorted(vetados),
            "recuperacion_total_h": duracion,
            "reglas": [r["id"] for r in reglas.REGLAS if r["id"] in ("R6", "R7")]}


def propuesta_semana(deficits: list[dict], objetivo_100: float = 75.0, material: list[str] | None = None,
                     ocupados: tuple[str, ...] = (), tests: tuple[str, ...] = (),
                     km_semana: float | None = None,
                     fijos_m: dict[str, float] | None = None,
                     cargados: dict[str, dict] | None = None) -> dict:
    """La semana entera propuesta (V1.2-02): los siete dias, con metros, y si cabe en el volumen de la semana.

    `reparto` dice **en que dia** cae cada sesion; esto ademas dice **cuanto** suma cada una (los metros de la
    receta, no una cifra a mano) y **si el total cabe** en el volumen que el plan deja para las sesiones propias.
    Ese volumen no se inventa aqui: lo trae el plan recalculado, que ya lleva el tope del 10 % sobre la semana
    anterior. Cuenta **lo nuestro**, como lo cuenta el plan (`km_hechos_nuestras`): los metros de los dias del
    entrenador no se restan del presupuesto, solo se dicen, porque esa agua ya esta pactada fuera del plan.

    Lo que no cabe **no se coloca a la fuerza**: cae a `fuera` con el numero que lo manda ("el plan deja 6.000 m y
    esta sesion pide 3.300"). Y si sobra hueco, tambien se dice: significa que la semana da mas de lo que el motor
    pide.

    Args:
      `km_semana`  los km del plan para esa semana (None si no se sabe: entonces no se recorta nada y se avisa).
      `fijos_m`    {dia: metros} de lo que ya traen los dias que no se proponen (los del entrenador), medidos de lo
                   que el atleta hace de verdad esos dias. Es informacion, no presupuesto.
    """
    r = reparto(deficits, objetivo_100=objetivo_100, material=material, ocupados=ocupados, tests=tests,
                cargados=cargados)

    # Cuantos metros pone cada sesion propuesta: lo que dicen las series de su receta.
    for s in r["dias"].values():
        receta = estimulos.RECETAS.get(s.get("receta") or "") or {}
        s["metros"] = int(receta.get("metros") or 0)
        s["metros_serie"] = int((receta.get("reps") or 0) * (receta.get("dist_m") or 0))

    semana: list[dict] = []
    for d in r["semana"]:
        if d["dia"] in r["dias"]:
            semana.append({**d, "metros": r["dias"][d["dia"]]["metros"]})
        else:
            m = (fijos_m or {}).get(d["dia"])
            semana.append({**d, "metros": int(m) if m else None})

    tope = int(round(float(km_semana) * 1000)) if km_semana else None
    fijos = int(round(sum((fijos_m or {}).values()))) if fijos_m else 0
    propio = sum(s["metros"] for s in r["dias"].values())
    deja = tope
    fuera_volumen: list[dict] = []

    # Si no cabe, se caen las sesiones menos importantes (los deficits vienen por orden de importancia).
    if deja is not None:
        for dia in reversed(r["orden"]):
            if propio <= deja:
                break
            s = r["dias"].pop(dia)
            propio -= s["metros"]
            semana = [d for d in semana if d["dia"] != dia] + [{"dia": dia, "de": "propio", "sesion": None,
                                                                "nota": "libre", "metros": None}]
            semana.sort(key=lambda d: DIAS.index(d["dia"]))
            fuera_volumen.append({
                "id": s.get("clase"), "titulo": s.get("titulo"), "metros": s["metros"], "dia": dia,
                "porque": (f"no cabe en el volumen de la semana: el plan deja {deja} m para las sesiones propias "
                           f"y esta pide {s['metros']} m mas"),
            })
        for f in fuera_volumen:
            r["avisos"].append(f["porque"])

    if deja is not None and not fuera_volumen:
        hueco = deja - propio
        if hueco >= 500:
            r["avisos"].append(
                f"el motor pide {propio} m y la semana deja {deja} m: quedan {hueco} m de volumen facil, que se "
                f"pueden nadar sueltos (no son series)")
    if km_semana is None:
        r["avisos"].append("no se sabe el volumen de esa semana del plan: la propuesta no se ha recortado")

    return {**r, "semana": semana, "fuera": list(r["fuera"]) + fuera_volumen, "fuera_volumen": fuera_volumen,
            "volumen": {"km_plan": km_semana, "tope_m": tope, "fijos_m": fijos, "fijos_por_dia": dict(fijos_m or {}),
                        "propio_m": propio, "deja_m": deja, "cabe": not fuera_volumen,
                        "hueco_m": (None if deja is None else deja - propio)}}
