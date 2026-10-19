#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Evaluar lo hecho contra el plan: veredicto por sesion, resumen de la semana y ajuste propuesto.

Es el ultimo paso del parte. Con el parte relleno (grupos, material, intensidad) y el plan en numeros
(bloques), ya se puede contestar a la pregunta: **se ha cumplido lo que tocaba?**

Lo que hace:

1. **Empareja** cada bloque prescrito con el grupo que se ha hecho: por distancia de la repeticion (o metros
   del tiron), por material y por repeticiones. Antes de emparejar, une los bloques continuos que el reloj
   partio sin descanso por medio (un 2.500 que aparece en dos laps seguidos es un solo bloque).
2. **Compara el ritmo** con el rango objetivo del plan (con tolerancia) y cuenta las repeticiones.
3. **Veredicto por sesion** ponderado por metros: cumplida / a medias / floja / cambiada / sin parte.
4. **Resumen de la semana** (km hechos frente a los del plan, sesiones cumplidas) y el **ajuste propuesto**
   aplicando las reglas que ya estaban escritas en el plan (subir como mucho un 10 %, repetir si no se llega
   al 70 % de las sesiones, bajar si hay deriva).

El ajuste **no se aplica solo**: queda propuesto (tabla `plan_ajuste`) para que el atleta lo acepte. Y las
sesiones del entrenador no se evaluan ni se tocan: no hay nada con que compararlas, y su trabajo no se
reescribe.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

from . import correcciones, db, descanso, plan

TOLERANCIA_RITMO = 1.5      # s/100 de margen antes de decir que un bloque ha ido lento o rapido
MIN_CUMPLE_REPS = 0.8       # con el 80 % de las repeticiones se da el bloque por hecho
DESCANSO_FUSION_S = 15.0    # por debajo de esto, dos bloques continuos seguidos son el mismo bloque
ESTADOS = {
    "cumplida": "Cumplida",
    "a_medias": "A medias",
    "floja": "Floja",
    "cambiada": "Cambiada (se hizo otra cosa)",
    "a_mi_manera": "Hecha a tu manera (cambiaste el plan)",
    "apuntada": "Apuntada a mano (sin reloj)",
    "sin_parte": "Sin parte (no se puede comparar)",
    "pendiente": "Pendiente (aun no toca)",
    "no_hecha": "No hecha",
    "descanso": "Descanso / del entrenador",
}


# ------------------------------------------------------------------ piezas

def _laps(cn: sqlite3.Connection, actividad_id: int) -> dict[int, dict]:
    return {int(f["lap_idx"]): dict(f) for f in cn.execute(
        "SELECT lap_idx, dist_m, timer_s, es_descanso, estilo FROM natacion_lap"
        " WHERE actividad_id = ? ORDER BY lap_idx", (actividad_id,))}


def unir_continuos(grupos: list[dict], laps: dict[int, dict]) -> list[dict]:
    """Une bloques continuos que el reloj partio sin descanso real de por medio.

    El reloj no siempre hace un lap por bloque: un 2.500 nadado del tiron puede aparecer en dos o tres laps
    porque se pulso el boton al pasar. Si entre el final de un grupo y el principio del siguiente no hay mas
    de `DESCANSO_FUSION_S` de parada, es el mismo bloque y se une; si no, se respeta la separacion (es
    descanso de verdad).
    """
    salida: list[dict] = []
    for g in grupos:
        if salida and g["tipo"] == "continuo" and salida[-1]["tipo"] == "continuo" and g.get("laps") \
                and salida[-1].get("laps"):
            anterior = salida[-1]
            descanso = sum(laps[i]["timer_s"] or 0 for i in range(anterior["laps"][-1] + 1, g["laps"][0])
                           if i in laps and laps[i]["es_descanso"])
            if descanso <= DESCANSO_FUSION_S:
                metros = (anterior["metros"] or 0) + (g["metros"] or 0)
                tiempo = (anterior["tiempo_s"] or 0) + (g["tiempo_s"] or 0)
                salida[-1] = dict(anterior, metros=round(metros, 1), tiempo_s=round(tiempo, 1),
                                  ritmo_100=round(100.0 * tiempo / metros, 1) if metros else None,
                                  reps=anterior["reps"] + g["reps"],
                                  laps=anterior["laps"] + g["laps"], n_reps=anterior["n_reps"] + g["n_reps"])
                continue
        salida.append(dict(g))
    for i, g in enumerate(salida):
        g["orden"] = i
    return salida


def _encaje(prescrito: dict, hecho: dict) -> float | None:
    """Cuanto se parece un grupo hecho a un bloque del plan. None si no encajan. Mas alto = mejor."""
    reps = prescrito.get("reps") or 1
    dist = prescrito.get("dist_m") or 0
    material = prescrito.get("material") or []
    nota = 0.0
    if reps > 1:                                     # serie: la repeticion tiene que ser la misma
        if hecho.get("tipo") != "serie" or not hecho.get("rep_m"):
            return None
        dif = abs(hecho["rep_m"] - dist)
        if dif > max(2.0, dist * 0.05):
            return None
        nota += 60 - dif * 5
    else:                                            # bloque del tiron: metros parecidos (el plan da rangos)
        if hecho.get("tipo") != "continuo":
            return None
        metros = hecho.get("metros") or 0
        if not metros:
            return None
        dif = abs(metros - dist) / dist
        if dif > 0.35:
            return None
        nota += 60 - dif * 60
    # Un pataleo no es nado. Si el grupo va marcado como `pies`, no encaja con un bloque de brazo libre (ni al
    # reves), que es lo que evita que un 8x50 de pies "cumpla" un bloque pedido y que su ritmo se juzgue.
    if (hecho.get("intensidad") == "pies") != (prescrito.get("intensidad") == "pies"):
        return None
    tiene = bool(hecho.get("material"))
    if material and not tiene:
        nota -= 35                                   # el plan pedia material y consta brazo libre
    elif material:
        nota += 20 + 10 * len(set(material) & set(hecho["material"]))
    elif tiene:
        nota -= 25                                   # se hizo con material lo que era a brazo libre
    else:
        nota += 10
    if prescrito.get("intensidad") and hecho.get("intensidad") == prescrito["intensidad"]:
        nota += 5
    return nota


def _estado_ritmo(prescrito: dict, hecho: dict) -> tuple[str, str]:
    """('en_rango'|'algo_lento'|'lento'|'algo_rapido'|'rapido'|'sin_objetivo', explicacion)."""
    if hecho.get("intensidad") == "pies":
        return "sin_objetivo", "pies (pataleo): el reloj mide igual, pero el ritmo no se juzga"
    objetivo = prescrito.get("ritmo_100")
    ritmo = hecho.get("ritmo_100")
    if not objetivo:
        return "sin_objetivo", "el plan no da ritmo para este bloque: solo se comprueba que se ha hecho"
    if not ritmo:
        return "sin_objetivo", "el grupo hecho no tiene ritmo fiable (cronometro mal disparado)"
    bajo, alto = objetivo
    if bajo - TOLERANCIA_RITMO <= ritmo <= alto + TOLERANCIA_RITMO:
        return "en_rango", f"{ritmo} s/100 dentro de lo pedido ({bajo}-{alto})"
    if ritmo > alto:
        desviacion = (ritmo - alto) / alto * 100
        etiqueta = "algo_lento" if desviacion <= 4 else "lento"
        return etiqueta, f"{ritmo} s/100, {desviacion:.1f} % mas lento de lo pedido ({bajo}-{alto})"
    desviacion = (bajo - ritmo) / bajo * 100
    etiqueta = "algo_rapido" if desviacion <= 4 else "rapido"
    intensidad = prescrito.get("intensidad") or ""
    if intensidad in ("cal", "ae1"):
        return "de_mas", f"{ritmo} s/100, {desviacion:.1f} % mas rapido de lo pedido: era {intensidad}"
    return etiqueta, f"{ritmo} s/100, {desviacion:.1f} % mas rapido de lo pedido ({bajo}-{alto})"


def comparar_sesion(sesion: dict, grupos: list[dict]) -> dict:
    """Cruza una sesion del plan con los grupos de su parte. Devuelve el detalle bloque a bloque."""
    prescritos = plan.bloques_de(sesion)
    usados: set[int] = set()
    detalle = []
    for b in prescritos:
        mejor, mejor_nota = None, None
        for i, g in enumerate(grupos):
            if i in usados:
                continue
            nota = _encaje(b, g)
            if nota is not None and (mejor_nota is None or nota > mejor_nota):
                mejor, mejor_nota = i, nota
        if mejor is None:
            detalle.append({"que": b.get("que"), "prescrito": b, "hecho": None, "grado": 0.0,
                            "estado": "no_hecho", "ritmo": None,
                            "nota": "no aparece ningun bloque que corresponda a esto"})
            continue
        usados.add(mejor)
        g = grupos[mejor]
        estado_ritmo, explicacion = _estado_ritmo(b, g)
        reps_pedidas = b.get("reps") or 1
        reps_hechas = g.get("n_reps") or 0
        grado = 1.0
        if reps_pedidas > 1 and reps_hechas < reps_pedidas:
            grado = min(1.0, reps_hechas / reps_pedidas)
            if grado < MIN_CUMPLE_REPS:
                explicacion = f"hechas {reps_hechas} de {reps_pedidas} repeticiones. " + explicacion
        if estado_ritmo in ("lento", "de_mas"):
            grado = min(grado, 0.6)
        elif estado_ritmo in ("algo_lento", "algo_rapido"):
            grado = min(grado, 0.85)
        material_plan = set(b.get("material") or [])
        material_hecho = set(g.get("material") or [])
        if material_plan and material_plan != material_hecho:
            explicacion += f" | material: pedia {sorted(material_plan) or ['brazo libre']} y consta " \
                           f"{sorted(material_hecho) or ['brazo libre']}"
        if not material_plan and material_hecho:
            explicacion += f" | se hizo con {sorted(material_hecho)} lo que era a brazo libre: no cuenta " \
                           "como marca"
        detalle.append({"que": b.get("que"), "prescrito": b, "hecho": g, "grado": round(grado, 2),
                        "estado": "cumplido" if grado >= 0.95 else ("parcial" if grado >= 0.6 else "flojo"),
                        "ritmo": estado_ritmo, "nota": explicacion})
    faltan = [g for i, g in enumerate(grupos) if i not in usados]
    return {"sesion": sesion, "detalle": detalle, "grupos_sin_plan": faltan}


def veredicto(sesion: dict, parte: dict | None, grupos: list[dict]) -> dict:
    """El veredicto de una sesion: cumplida, a medias, floja, cambiada, sin parte o no hecha."""
    prescritos = plan.bloques_de(sesion)
    metros_plan = plan.metros_de_sesion(sesion)
    base = {"fecha": sesion["fecha"], "dia": sesion["dia"], "semana": sesion.get("semana"),
            "titulo": sesion["titulo"], "quien": sesion.get("quien"), "tipo": sesion.get("tipo"),
            "metros_plan": metros_plan, "metros_hechos": None, "estado": None, "resumen": "", "detalle": [],
            "bloques": len(prescritos)}
    if sesion.get("quien") != "nosotros" or not prescritos:
        return dict(base, estado="descanso", resumen=sesion.get("detalle") or "")
    if not parte:
        return dict(base, estado="sin_parte",
                    resumen="hay sesion del reloj pero sin parte: no se puede saber el material ni la "
                            "intensidad, asi que no se compara el ritmo")
    grupos = [dict(g) for g in grupos]
    for g in grupos:
        if isinstance(g.get("material"), str):
            g["material"] = [m for m in g["material"].split(",") if m]
    metros_hechos = parte.get("metros") or sum(g.get("metros") or 0 for g in grupos)
    # Lo que vale es lo nadado: si el volumen llega al 80 % de lo que pedia el plan, la sesion esta hecha
    # aunque los bloques no coincidan. El atleta cambia cosas en la piscina y eso se acepta.
    volumen_esta = bool(metros_plan) and float(metros_hechos or 0) >= MIN_CUMPLE_REPS * float(metros_plan)
    comp = comparar_sesion(sesion, grupos)
    if not any(d["hecho"] for d in comp["detalle"]):
        if volumen_esta:
            return dict(base, estado="a_mi_manera", metros_hechos=metros_hechos,
                        resumen=(f"se hizo otra cosa de lo que pedia el plan ({metros_hechos:.0f} m nadados frente "
                                 f"a los {round(metros_plan)} m): el volumen esta, asi que cuenta como hecha"),
                        detalle=comp["detalle"])
        return dict(base, estado="cambiada", metros_hechos=metros_hechos,
                    resumen="ningun bloque coincide con lo que pedia el plan", detalle=comp["detalle"])
    total = sum((b.get("reps") or 1) * (b.get("dist_m") or 0) for b in prescritos) or 1
    hecho = sum(d["grado"] * ((d["prescrito"].get("reps") or 1) * (d["prescrito"].get("dist_m") or 0))
                for d in comp["detalle"])
    cumplimiento = round(hecho / total, 2)
    if cumplimiento >= 0.9:
        estado, resumen = "cumplida", f"cumplimiento del {cumplimiento:.0%} del plan"
    elif cumplimiento >= 0.6:
        estado, resumen = "a_medias", f"cumplimiento del {cumplimiento:.0%}: la mitad hecha"
    elif volumen_esta:
        estado = "a_mi_manera"
        resumen = (f"los bloques salen al {cumplimiento:.0%}, pero el volumen esta ({metros_hechos:.0f} m frente a "
                   f"los {round(metros_plan)} m del plan): lo que vale es lo nadado")
    else:
        estado, resumen = "floja", f"cumplimiento del {cumplimiento:.0%}"
    flojos = [d for d in comp["detalle"] if d["estado"] != "cumplido"]
    if flojos:
        resumen += " | " + "; ".join(f"{d['que']}: {d['nota']}" for d in flojos[:3])
    return dict(base, estado=estado, metros_hechos=metros_hechos, cumplimiento=cumplimiento,
                resumen=resumen, detalle=comp["detalle"],
                grupos_sin_plan=[{"metros": g.get("metros"), "ritmo_100": g.get("ritmo_100"),
                                  "material": g.get("material"), "intensidad": g.get("intensidad")}
                                 for g in comp["grupos_sin_plan"]])


# ------------------------------------------------------------------ acceso a los datos

def _parte_de(cn: sqlite3.Connection, fecha: str) -> dict | None:
    fila = cn.execute("SELECT * FROM parte WHERE fecha = ? ORDER BY id DESC LIMIT 1", (fecha,)).fetchone()
    if not fila:
        return None
    from . import partes
    p = dict(fila)
    laps = _laps(cn, p.get("actividad_id") or 0)
    p["series"] = []
    for s in cn.execute("SELECT * FROM parte_serie WHERE parte_id = ? ORDER BY orden", (fila["id"],)):
        g = dict(s)
        g["material"] = [m for m in (g.get("material") or "").split(",") if m]
        try:
            g["laps"] = [int(x) for x in json.loads(g.get("laps") or "[]")]
        except (TypeError, ValueError):
            g["laps"] = []
        p["series"].append(partes.rellenar_reps(g, laps))
    return p


def _actividad_de(cn: sqlite3.Connection, fecha: str) -> dict | None:
    return cn.execute(
        """SELECT a.id, a.inicio_local, a.distancia_m, a.nombre, s.largo_piscina_m
           FROM actividad a LEFT JOIN natacion_sesion s ON s.actividad_id = a.id
           WHERE substr(a.inicio_local, 1, 10) = ? AND a.disciplina = 'natacion'
           ORDER BY a.inicio_local LIMIT 1""", (fecha,)).fetchone()


def _apunte_de(cn: sqlite3.Connection, fecha: str) -> dict | None:
    """El apunte de natacion de ese dia, si lo hay.

    Es la via para los entrenamientos que se hacen **sin reloj**: lo que vale es lo que se ha nadado y lo que
    apunta el atleta, asi que un apunte de natacion cuenta como la sesion de ese dia (ver `evaluar_semana`).
    Si hay mas de uno, manda el ultimo apuntado.
    """
    return cn.execute(
        """SELECT id, fecha, distancia_m, minutos, material, piscina_m, notas
           FROM apunte WHERE fecha = ? AND lower(tipo) = 'natacion'
           ORDER BY id DESC LIMIT 1""", (fecha,)).fetchone()


def _veredicto_apuntado(sesion: dict, ap) -> dict:
    """El veredicto de una sesion del plan hecha **sin reloj** y apuntada a mano.

    Sin reloj no hay laps: no se pueden comparar bloques, asi que se mira si lo nadado llega a lo que pedia el
    plan (el mismo 80 % que se usa para dar un bloque por hecho). Si llega, la sesion cuenta como hecha. Es el
    caso de los entrenamientos que se hacen sin reloj: lo que vale es lo que se ha nadado.
    """
    metros = float(ap["distancia_m"] or 0)
    pedia = plan.metros_de_sesion(sesion) or 0
    notas = (ap["notas"] or "").strip()
    llena = bool(pedia) and metros >= MIN_CUMPLE_REPS * pedia
    resumen = f"sin reloj: apuntado a mano, {metros:.0f} m"
    if pedia:
        resumen += f" de los {round(pedia)} m que pedia el plan ({metros / pedia:.0%})"
    resumen += ". Cuenta como hecha: lo que vale es lo que se ha nadado." if llena else \
               ". Se queda corta frente a lo que pedia el plan."
    if ap["minutos"] and metros:
        seg100 = float(ap["minutos"]) * 60.0 / (metros / 100.0)
        resumen += f" Ritmo medio: {int(seg100 // 60)}:{seg100 % 60:04.1f} por 100."
    if notas:
        resumen += f" Lo apuntado: {notas[:160]}"
    return dict(veredicto(sesion, None, []), estado="apuntada" if llena else "a_medias",
                metros_hechos=metros, apunte_id=ap["id"], sin_reloj=1, notas=notas[:300], resumen=resumen)


def evaluar_semana(cn: sqlite3.Connection, clave: str, hoy: date | None = None) -> dict:
    """Evalua todas las sesiones de una semana del plan y saca el resumen y el ajuste propuesto."""
    semana = next((s for s in plan.SEMANAS if s["clave"] == clave.upper()), None)
    if semana is None:
        raise ValueError(f"no hay semana {clave} (hay: {', '.join(s['clave'] for s in plan.SEMANAS)})")
    d = hoy or date.today()
    veredictos = []
    for sesion in plan.sesiones_para_evaluar(semana["desde"], semana["hasta"]):
        if plan._fecha(sesion["fecha"]) > d:                    # noqa: SLF001
            v = veredicto(sesion, None, [])
            veredictos.append(dict(v, estado="pendiente", resumen="esa sesion todavia no ha llegado"))
            continue
        parte = _parte_de(cn, sesion["fecha"])
        if parte:
            grupos = unir_continuos(parte["series"], _laps(cn, parte["actividad_id"] or 0))
            veredictos.append(veredicto(sesion, parte, grupos))
        else:
            act = _actividad_de(cn, sesion["fecha"])
            ap = None if act else _apunte_de(cn, sesion["fecha"])
            v = veredicto(sesion, None, [])
            if act:
                v["metros_hechos"] = act["distancia_m"]
                v["actividad_id"] = act["id"]
                v["resumen"] = (f"el reloj tiene {act['distancia_m']:.0f} m ese dia, pero sin parte: "
                                "rellena el parte para poder comparar")
            elif ap:
                # Entrenamiento hecho SIN reloj y apuntado a mano: cuenta como la sesion del dia. Lo que vale
                # es lo que se ha nadado; sin reloj no hay laps, asi que se juzga por metros, no por bloques.
                v = _veredicto_apuntado(sesion, ap)
            veredictos.append(v)
    nuestras = [v for v in veredictos if v["estado"] not in ("descanso", "pendiente")]
    # El descanso y la sensacion de cada dia, colgados de la semana: es lo que lee `_ajuste_bruto` para no leer un
    # bajon con explicacion fuera del agua como una senal de entrenamiento (V1.2-04).
    descanso.de_la_semana(cn, veredictos)
    evaluables = [v for v in nuestras
                  if v["estado"] in ("cumplida", "a_medias", "floja", "cambiada", "a_mi_manera", "apuntada")]
    hechas = [v for v in evaluables if v["estado"] in ("cumplida", "a_medias", "a_mi_manera", "apuntada")]
    km_hechos = round(sum((v["metros_hechos"] or 0) for v in nuestras) / 1000.0, 1)
    return {
        "clave": semana["clave"], "desde": semana["desde"], "hasta": semana["hasta"], "km_plan": semana["km"],
        "foco": semana["foco"], "sesiones": veredictos,
        "sesiones_plan": len(nuestras), "sesiones_hechas": len(hechas),
        "sesiones_evaluables": len(evaluables),
        "km_hechos_nuestras": km_hechos,
        # En curso hasta el ultimo dia: el domingo por la tarde la semana todavia no esta cerrada y la sesion
        # puede estar por hacer, asi que lo que salga de ella es provisional.
        "en_curso": d <= plan._fecha(semana["hasta"]),                            # noqa: SLF001
        # El cumplimiento solo cuenta lo que se puede juzgar: una sesion sin parte no se da por no hecha.
        "cumplimiento": round(len(hechas) / len(evaluables), 2) if evaluables else None,
    }


def _deriva(sesiones: list[dict]) -> tuple[float | None, list[str]]:
    """Deriva mas alta encontrada (ultima repeticion mas lenta que la primera) y donde."""
    peor, donde = None, []
    for v in sesiones:
        for d in v.get("detalle") or []:
            g = d.get("hecho")
            reps = (g or {}).get("reps") or []
            ritmos = [r.get("ritmo_100") for r in reps if r.get("ritmo_100")]
            if len(ritmos) < 3:
                continue
            der = round(ritmos[-1] - ritmos[0], 1)
            if der > 5:
                donde.append(f"{v['fecha']} {d['que']}: +{der} s/100 de la primera a la ultima")
                peor = der if peor is None else max(peor, der)
    return peor, donde


def _ajuste_bruto(semana: dict, siguiente: dict | None) -> dict:
    """Aplica las reglas del plan a lo que ha pasado en la semana. Propone, no aplica."""
    motivos = []
    pct = semana["cumplimiento"]
    if pct is None:
        return {"accion": "sin_datos", "km_propuestos": None,
                "motivos": ["aun no hay ninguna sesion de la semana con el parte relleno: sin parte no se sabe "
                            "el material ni la intensidad, asi que no se juzga si se cumple (solo el volumen)"]}
    if pct < 0.7:
        return {"accion": "repetir", "km_propuestos": semana["km_plan"],
                "motivos": [f"regla del plan: con menos del 70 % de las sesiones hechas ({pct:.0%}) la semana "
                            "siguiente repite, no sube"]}
    deriva, donde = _deriva(semana["sesiones"])
    if deriva and deriva > 5:
        # Un dia lastrado (poco sueno o mal cuerpo en el agua) explica el bajon sin que el entrenamiento tenga la
        # culpa: la deriva se sigue midiendo y diciendo, pero el plan NO se toca por ella (V1.2-04).
        lastrados = descanso.lastrados(semana["sesiones"])
        if lastrados:
            quien = "; ".join(f"el {v['dia']}, {descanso.texto(v['descanso']).split(' (')[0]}"
                              for v in lastrados[:2])
            return {"accion": "mantener", "km_propuestos": semana["km_plan"],
                    "motivos": [f"la deriva pasa de 5 s/100 ({deriva:.1f} s/100) y la regla del plan bajaria un "
                                f"20 %, pero no se toca: hay dias lastrados ({quien}) y un bajon con explicacion "
                                "fuera del agua no es una senal de entrenamiento (V1.2-04, criterio del entrenador)"]
                                + donde}
        return {"accion": "bajar", "km_propuestos": round(semana["km_plan"] * 0.8, 1),
                "motivos": ["regla del plan: deriva de mas de 5 s/100 entre la primera y la ultima repeticion "
                            "en dos sesiones clave seguidas -> la semana siguiente baja un 20 %"] + donde}
    if siguiente is None:
        return {"accion": "mantener", "km_propuestos": semana["km_plan"],
                "motivos": [f"semana cumplida al {pct:.0%} y sin deriva: sigue el plan tal cual"]}
    subida = round((siguiente["km"] / semana["km_plan"] - 1) * 100)
    tope = 10
    if subida > tope:
        return {"accion": "subir_menos", "km_propuestos": round(semana["km_plan"] * (1 + tope / 100), 1),
                "motivos": [f"la semana siguiente del plan sube un {subida} %, por encima del 10 % que permite "
                            "la regla: se queda en un 10 %"]}
    return {"accion": "seguir", "km_propuestos": siguiente["km"],
            "motivos": [f"semana cumplida al {pct:.0%} y sin deriva: la siguiente sube un {subida} %, dentro "
                        "de lo permitido"]}


def ajuste_propuesto(semana: dict, siguiente: dict | None) -> dict:
    """El ajuste que sale de la semana, con el aviso de que aun esta en curso cuando lo esta."""
    a = _ajuste_bruto(semana, siguiente)
    if semana.get("en_curso"):
        faltan = semana["sesiones_plan"] - semana["sesiones_evaluables"]
        a["provisional"] = True
        a["motivos"] = a["motivos"] + [
            f"la semana esta en curso (hasta el {semana['hasta'][-2:]}/{semana['hasta'][5:7]}): esto es "
            f"provisional" + (f" y quedan {faltan} de nuestras por hacer o por rellenar" if faltan else "")]
    return a


def propuesta(cn: sqlite3.Connection, clave: str, hoy: date | None = None) -> dict:
    """La semana evaluada + el ajuste que sale de ella (lo que se le propone al atleta)."""
    semana = evaluar_semana(cn, clave, hoy)
    claves = [s["clave"] for s in plan.SEMANAS]
    i = claves.index(semana["clave"])
    siguiente = plan.SEMANAS[i + 1] if i + 1 < len(claves) else None
    semana["siguiente"] = siguiente["clave"] if siguiente else None
    semana["ajuste"] = ajuste_propuesto(semana, siguiente)
    return semana


def guardar_propuesta(cn: sqlite3.Connection, prop: dict) -> str:
    """Deja el ajuste propuesto en la tabla `plan_ajuste` (estado `propuesto`). No toca el plan."""
    clave = f"{prop['clave']}:{prop['ajuste']['accion']}"
    cn.execute("""INSERT INTO plan_ajuste (clave, semana, propuesto_en, que, motivo, estado)
                  VALUES (?,?,?,?,?, 'propuesto')
                  ON CONFLICT(clave) DO UPDATE SET propuesto_en=excluded.propuesto_en, que=excluded.que,
                                                   motivo=excluded.motivo""",
               (clave, prop["clave"], db.ahora(), json.dumps({"accion": prop["ajuste"]["accion"],
                                                              "km_propuestos": prop["ajuste"]["km_propuestos"],
                                                              "siguiente": prop.get("siguiente")},
                                                             ensure_ascii=False),
                " | ".join(prop["ajuste"]["motivos"])))
    cn.commit()
    return clave


def evaluar_hasta(cn: sqlite3.Connection, hoy: date | str | None = None, semanas: int = 3) -> dict:
    """Evalua las ultimas `semanas` semanas que ya han empezado (la ultima, la que esta en curso)."""
    d = plan._fecha(hoy) if isinstance(hoy, str) else (hoy or date.today())     # noqa: SLF001
    evaluadas = []
    for s in plan.SEMANAS:
        if plan._fecha(s["desde"]) <= d:                                        # noqa: SLF001
            evaluadas.append(propuesta(cn, s["clave"], d))
    evaluadas = evaluadas[-semanas:]
    return {
        "hoy": d.isoformat(),
        "semanas": evaluadas,
        "recientes": [v for s in evaluadas for v in s["sesiones"] if v["estado"] not in ("descanso",)][-8:],
        "cortes": _cortes_texto(cn),
    }


def _cortes_texto(cn: sqlite3.Connection) -> str:
    """Una linea con lo que se puede y lo que no se puede comparar todavia."""
    partes = cn.execute("SELECT COUNT(*) FROM parte").fetchone()[0]
    from . import partes as partes_mod
    if not partes:
        return ("No hay ningun parte todavia: sin parte no se sabe el material ni la intensidad, asi que lo "
                "unico que se puede comparar es el volumen.")
    pendientes = cn.execute(
        """SELECT COUNT(*) FROM natacion_sesion s JOIN actividad a ON a.id = s.actividad_id
           WHERE s.largo_piscina_m IS NOT NULL AND substr(a.inicio_local, 1, 10) >= ?
             AND NOT EXISTS (SELECT 1 FROM parte p WHERE p.actividad_id = a.id)""",
        (partes_mod.PRIMER_DIA_CON_PARTE,)).fetchone()[0]
    return (f"{partes} partes en la base; quedan {pendientes} sesiones de piscina del reloj sin parte "
            "(se rellenan en Entrenamientos, pinchando la sesion).")


def datos_panel(cn: sqlite3.Connection, semanas: int = 3) -> dict:
    return evaluar_hasta(cn, semanas=semanas)


# ------------------------------------------- la valoracion de un entrenamiento suelto

def _grupos_del_parte(cn: sqlite3.Connection, parte: dict) -> list[dict]:
    """Los grupos del parte, con los continuos ya unidos (igual que al evaluar la semana)."""
    return unir_continuos(parte.get("series") or [], _laps(cn, parte.get("actividad_id") or 0))


def _material_leible(material) -> str:
    from . import partes
    if isinstance(material, str):
        material = [m for m in material.split(",") if m]
    return ", ".join(partes.NOMBRE_MATERIAL.get(m, m) for m in (material or []))


def _titulo_grupo(g) -> str:
    """Como se lee un grupo: `7x50 m` si es una serie, `425 m seguidos` si es un bloque del tiron."""
    n = int((g.get("n_reps") or len(g.get("laps") or []) or 1))
    rep = int(g.get("rep_m") or 0)
    if n > 1 and rep:
        return f"{n}x{rep} m"
    return f"{int(g.get('metros') or 0)} m seguidos"


def valorar_actividad(cn: sqlite3.Connection, actividad_id: int) -> dict | None:
    """La valoracion del sistema para UN entrenamiento, para enseñarla al abrir su parte.

    Si ese dia el plan tiene sesion nuestra, manda el veredicto del plan (cumplida, a medias, floja, cambiada,
    sin parte). Si es un entrenamiento propio (o del entrenador), se dice tal cual y se da lo que si se puede
    medir sin plan: volumen, ritmo y material. Sin parte todavia, se pide el parte y se enseña lo que trae el reloj.
    """
    act = cn.execute(
        """SELECT a.id, a.inicio_local, a.distancia_m, a.nombre, s.largo_piscina_m
           FROM actividad a LEFT JOIN natacion_sesion s ON s.actividad_id = a.id
           WHERE a.id = ?""", (actividad_id,)).fetchone()
    if not act:
        return None
    from . import partes
    fecha = (act["inicio_local"] or "")[:10]
    parte = _parte_de(cn, fecha) if fecha else None
    sesion = plan.sesion_de(fecha) if fecha else None
    es_nuestra = bool(sesion and sesion.get("quien") == "nosotros" and plan.bloques_de(sesion))
    titulo = (sesion or {}).get("titulo") or act["nombre"] or "Entrenamiento propio"
    hecho = (parte.get("metros") if parte else None) or act["distancia_m"] or 0
    # El descanso va con la valoracion de cualquier entrenamiento: si el dia venia lastrado se dice antes de
    # juzgar el ritmo, porque cambia la lectura (V1.2-04).
    dia = descanso.de(cn, fecha) if fecha else {}
    aviso = (f" Ojo con el dia: {dia.get('texto')}: el ritmo de hoy no se lee igual." if dia.get("lastrado") else "")
    # Lo que el atleta ha corregido de este entrenamiento (V1.2-06): se dice siempre, y su dato del reloj no se toca.
    corregidas = correcciones.de(cn, actividad_id)
    for c in corregidas:
        aviso += " " + correcciones.texto(c) + "."

    if es_nuestra:
        grupos = _grupos_del_parte(cn, parte) if parte else []
        v = veredicto(sesion, parte, grupos)
        resumen = v.get("resumen") or ""
        detalle = [{"que": d.get("que"), "nota": d.get("nota"), "estado": d.get("estado")}
                   for d in (v.get("detalle") or [])]
        if not parte:
            # Sin parte no se puede comparar, pero si se puede decir lo que trae el reloj y lo que pedia el plan.
            laps_sesion = partes._laps_de(cn, act["id"])
            traidos = partes.proponer_grupos(laps_sesion, partes.cortes_intensidad(cn))
            # Y si el atleta ha corregido algo, lo que se enseña aqui es SU tiempo, no el del reloj (V1.2-06).
            traidos = correcciones.aplicar(cn, act["id"], laps_sesion, traidos)
            pedia = plan.metros_de_sesion(sesion)
            resumen = (f"El reloj trae {round(hecho)} m en {len(traidos)} bloques, pero falta el parte: sin "
                       f"marcar material e intensidad no se puede comparar con el plan"
                       + (f", que pedia {round(pedia)} m." if pedia else "."))
            detalle = detalle + [{"que": _titulo_grupo(g),
                                  "nota": ((f"{g['ritmo_100']:.0f} s/100" if g.get("ritmo_100") else "sin ritmo")
                                           + " · sin material ni intensidad marcados"),
                                  "estado": "sin_parte"} for g in traidos]
        return {
            "origen": "plan", "fecha": fecha, "titulo": titulo,
            "estado": v.get("estado"), "etiqueta": ESTADOS.get(v.get("estado"), v.get("estado")),
            "plan": plan.metros_de_sesion(sesion), "hecho": round(hecho),
            "resumen": resumen + aviso, "detalle": detalle, "descanso": dia, "correcciones": corregidas,
        }

    # Entrenamiento propio: no hay bloque del plan que comparar, pero si se puede decir como salio.
    if not parte:
        anterior = bool(fecha and fecha < partes.PRIMER_DIA_CON_PARTE)
        return {
            "origen": "propia", "fecha": fecha, "titulo": titulo, "estado": "sin_parte", "etiqueta": "sin parte",
            "hecho": round(hecho), "plan": None,
            "resumen": ("Entrenamiento anterior al 12/10/2026: se da por rellenado, no hace falta parte."
                        if anterior else
                        "El reloj trae esta sesion pero todavia no tiene parte: marca el material y la intensidad "
                        "y ya se puede valorar (y dejara de contar como brazo libre en las marcas).") + aviso,
            "detalle": [], "descanso": dia, "correcciones": corregidas,
        }
    grupos = _grupos_del_parte(cn, parte)
    detalle, swolfs = [], []
    for g in grupos:
        que = _titulo_grupo(g)
        ritmo = g.get("ritmo_100")
        partes_nota = [f"{ritmo:.0f} s/100" if ritmo else "sin ritmo"]
        if g.get("material"):
            partes_nota.append(_material_leible(g["material"]))
        if g.get("intensidad"):
            partes_nota.append(partes.ETIQUETA_INTENSIDAD.get(g["intensidad"], g["intensidad"]))
        detalle.append({"que": que, "nota": " · ".join(x for x in partes_nota if x), "estado": "hecho"})
        for r in (g.get("reps") or []):
            if r.get("swolf"):
                swolfs.append(r["swolf"])
    resumen = (f"Entrenamiento tuyo: {round(hecho)} m en {len(grupos)} bloques. Sin bloque del plan que "
               "comparar, asi que se apunta tal cual.")
    if swolfs:
        resumen += f" SWOLF medio de lo medido: {sum(swolfs)/len(swolfs):.0f}."
    return {"origen": "propia", "fecha": fecha, "titulo": titulo, "estado": "propia", "etiqueta": "por tu cuenta",
            "hecho": round(hecho), "plan": None, "resumen": resumen + aviso, "detalle": detalle, "descanso": dia,
            "correcciones": corregidas}


def valoraciones_de(cn: sqlite3.Connection, actividad_ids) -> dict:
    """`{actividad_id: valoracion}` (y tambien por fecha) para las sesiones que se miran en el portal."""
    salida: dict[str, dict] = {}
    for i in actividad_ids:
        if not i:
            continue
        try:
            v = valorar_actividad(cn, int(i))
        except (TypeError, ValueError):
            continue
        if not v:
            continue
        salida[str(i)] = v
        if v.get("fecha"):
            salida.setdefault(v["fecha"], v)
    return salida


# ------------------------------------------------------------------ consola

def mostrar(cn: sqlite3.Connection, clave: str | None = None, semanas: int = 3) -> None:
    if clave:
        prop = propuesta(cn, clave)
        _imprimir_semana(prop)
        return
    datos = evaluar_hasta(cn, semanas=semanas)
    print(f"Evaluacion a {datos['hoy']}  ({datos['cortes']})\n")
    for s in datos["semanas"]:
        _imprimir_semana(s)


def _imprimir_semana(s: dict) -> None:
    print(f"=== {s['clave']} ({s['desde']} a {s['hasta']}) - plan {s['km_plan']} km - {s['foco']} ===")
    for v in s["sesiones"]:
        estado = ESTADOS.get(v["estado"], v["estado"])
        metros = f"{v['metros_hechos']:.0f} m" if v.get("metros_hechos") else ""
        print(f"  {v['fecha']} {v['titulo']:<42} {estado:<32}{metros:>8}")
        if v["resumen"]:
            print(f"      {v['resumen'][:150]}")
    pct = s["cumplimiento"]
    print(f"  -> {s['sesiones_hechas']} de {s['sesiones_plan']} sesiones nuestras "
          f"({pct:.0%} de cumplimiento)" if pct is not None else "  -> sin sesiones evaluables")
    a = s["ajuste"]
    km = f" -> {a['km_propuestos']} km" if a.get("km_propuestos") else ""
    print(f"  -> AJUSTE PROPUESTO: {a['accion'].replace('_', ' ').upper()}{km}")
    for m in a["motivos"]:
        print(f"       - {m}")
    print()
