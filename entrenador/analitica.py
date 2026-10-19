#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Analitica de entrenamiento: descubre los segmentos mas habituales del atleta.

Idea (peticion del atleta, 11/10/2026): en vez de fiarse de lo que recuerda, que el programa **descubra**
que segmentos repite mas a lo largo de los anos, dando **mas valor a los largos** (un bloque de 1.000 m
seguidos dice mucho mas que un 100 m suelto).

Dos familias de segmentos, con nombres que se entiendan sin ser tecnico:

- **Bloque continuo**: metros nadados del tiron, sin parar (laps activos consecutivos se suman en uno solo).
- **Serie**: repeticiones con descanso entre ellas (10x100 m, 5x200 m...), tal como las reconstruye
  `series.py`.

Sobre la piscina: las sesiones de 25 m y de 50 m se agrupan por separado, porque el mismo esfuerzo da ritmos
distintos. Cada segmento guarda la piscina en la que se hizo.

Sobre el material: el reloj no registra palas ni aletas (comprobado), asi que los ritmos historicos son
"sin etiquetar". El programa no lo disimula: lo dice y, a partir de ahora, basta con poner la palabra en el
nombre de la actividad en Garmin Connect para que la sesion quede etiquetada.

Este modulo **solo lee** de la base de datos y devuelve diccionarios; quien escribe los ficheros es `panel.py`
y la orden `analizar` de `cli.py`.
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics as st
from collections import defaultdict
from datetime import date, datetime, timedelta

# Un bloque tiene que llegar a esta distancia para contar como "bloque continuo".
MIN_BLOQUE_M = 200.0
# Redondeo de distancias para agrupar segmentos (las piscinas son de 25 m: los multiplos de 25 son naturales).
PASO_M = 25.0
# Ritmo creible de un bloque: fuera de este rango el cronometro del lap esta mal disparado. El bloque se
# conserva (existe en el historico) pero sin ritmo y marcado como sospechoso, para no contaminar las medias.
RITMO_MIN, RITMO_MAX = 60.0, 300.0
# Brazadas por metro: el atleta da entre 8 y 11 brazadas por largo de 25 m. Fuera de este rango, el lap esta
# mal medido (piscina configurada como 50 m en un vaso de 25, cronometro disparado a destiempo...) y su ritmo
# no se puede usar como marca, aunque el bloque siga contando para el catalogo.
BRAZADAS_MIN_M, BRAZADAS_MAX_M = 0.20, 0.80
# Los bloques se agrupan tambien por estilo: nadar 400 m a braza no es comparable con 400 m libres.
TIERS = [(0, "corto"), (400, "medio"), (800, "largo"), (1500, "muy largo")]


def _sufijo(estilo: str | None, piscina: float | None) -> str:
    """Sufijo del nombre del segmento: estilo (si no es libre) y piscina (si no es la habitual, 25 m)."""
    partes = []
    if estilo == "drill":
        partes.append("tecnica")
    elif estilo and estilo != "libre":
        partes.append(estilo)
    if piscina is None:
        partes.append("aguas abiertas")
    elif float(piscina) >= 40:
        partes.append(f"{piscina:g} m")
    return (" (" + ", ".join(partes) + ")") if partes else ""


def _ronda(dist: float, paso: float = PASO_M) -> float:
    """Redondea una distancia al multiplo de `paso` mas cercano (evita duplicar 395 y 400 m)."""
    return round(dist / paso) * paso


def _tier(dist: float) -> str:
    etiqueta = "corto"
    for limite, nombre in TIERS:
        if dist >= limite:
            etiqueta = nombre
    return etiqueta


def _ritmo_100(dist_m: float, tiempo_s: float) -> float | None:
    if not dist_m or not tiempo_s or dist_m <= 0 or tiempo_s <= 0:
        return None
    ritmo = tiempo_s / (dist_m / 100.0)
    return ritmo if RITMO_MIN <= ritmo <= RITMO_MAX else None


# ----------------------------------------------------------------------------- bloques continuos


def bloques(cn: sqlite3.Connection, min_bloque_m: float = MIN_BLOQUE_M) -> list[dict]:
    """Devuelve todos los bloques continuos de natacion (metros del tiron) del historico.

    `min_bloque_m` es el minimo para que un tiron cuente como bloque. El valor de siempre (200 m) sirve para
    buscar **marcas** de referencia, pero deja fuera las series de 100 m: para medir de que esta hecho un dia
    hay que bajarlo (`series_dia.MIN_SERIE_M`), porque si no un dia de 3.900 m sale con 1.050 m.
    """
    # De que sesiones hay parte subido: el parte es lo unico que dice con que material se hizo el bloque. Sin
    # parte, el material NO es "nada", es **desconocido**, y eso no se puede confundir con nadar a brazo libre.
    con_parte = {r[0] for r in cn.execute("SELECT DISTINCT actividad_id FROM parte")}
    filas = cn.execute(
        """SELECT l.actividad_id, l.lap_idx, l.dist_m, l.timer_s, l.estilo, l.es_descanso, l.fc_media,
                  l.brazadas, l.material, a.inicio_local, a.id_garmin, a.nombre, a.distancia_m AS sesion_m,
                  s.largo_piscina_m
           FROM natacion_lap l
           JOIN actividad a ON a.id = l.actividad_id
           JOIN natacion_sesion s ON s.actividad_id = l.actividad_id
           ORDER BY l.actividad_id, l.lap_idx"""
    ).fetchall()

    bloques: list[dict] = []
    actual: list[sqlite3.Row] = []

    def cerrar(grupo: list[sqlite3.Row]) -> None:
        dist = sum(float(g["dist_m"] or 0) for g in grupo)
        tiempo = sum(float(g["timer_s"] or 0) for g in grupo)
        if dist < min_bloque_m or not tiempo:
            return
        estilos = [g["estilo"] for g in grupo if g["estilo"]]
        total_sesion = float(grupo[0]["sesion_m"] or 0)
        cobertura = (dist / total_sesion) if total_sesion else None
        # Verificacion de coherencia con las brazadas: el atleta da entre 8 y 11 brazadas por largo de 25 m,
        # o sea entre 0,22 y 0,75 brazadas por metro. Un bloque muy fuera de ese rango es un lap mal medido
        # (tipico: piscina configurada como 50 m en un vaso de 25), asi que su ritmo no vale como marca.
        brazadas = sum(g["brazadas"] or 0 for g in grupo) or None
        brazadas_m = round(brazadas / dist, 3) if brazadas else None
        ritmo = _ritmo_100(dist, tiempo)
        # El material que llevaba el bloque (lo pone el parte): un bloque con aletas o palas **no** es una marca
        # de brazo libre, asi que la valoracion tiene que poder descartarlo o descontar la ayuda. Si el bloque
        # mezcla materiales se queda la lista entera, para no vender como "con aletas" lo que llevaba palas.
        materiales = sorted({g["material"] for g in grupo
                             if g["material"] and g["material"] != "sin_etiquetar"})
        # Tres motivos para no fiarse de un bloque: sin ritmo creible, con brazadas incoherentes con la
        # distancia, o sin ninguna brazada y aun asi muy rapido (un pataleo con tabla no baja de 90 s/100).
        fiable = ritmo is not None
        if brazadas_m is not None and not (BRAZADAS_MIN_M <= brazadas_m <= BRAZADAS_MAX_M):
            fiable = False
        if brazadas_m is None and ritmo is not None and ritmo < 90:
            fiable = False
        bloques.append({
            "fecha": (grupo[0]["inicio_local"] or "")[:10],
            "inicio_local": grupo[0]["inicio_local"],
            "actividad_id": grupo[0]["actividad_id"],
            "id_garmin": grupo[0]["id_garmin"],
            "nombre": grupo[0]["nombre"],
            "dist_m": round(dist, 1),
            "tiempo_s": round(tiempo, 1),
            "ritmo_100": _ritmo_100(dist, tiempo),
            "estilo": _mayoria(estilos),
            "piscina_m": grupo[0]["largo_piscina_m"],
            "n_laps": len(grupo),
            # Un bloque que ocupa casi toda la sesion puede ser una sesion continua o una sesion en la que
            # el reloj no registro descansos: se marca para no venderlo como lo que no es.
            "cobertura": round(cobertura, 2) if cobertura is not None else None,
            "domina_sesion": bool(cobertura is not None and cobertura > 0.9),
            "fc_media": (st.mean([g["fc_media"] for g in grupo if g["fc_media"]])
                         if any(g["fc_media"] for g in grupo) else None),
            "brazadas": sum(g["brazadas"] or 0 for g in grupo) or None,
            "brazadas_m": brazadas_m,
            "fiable": fiable,
            # Con que se hizo el bloque (del parte): `brazo_libre` en True solo si no llevaba nada.
            "material": ",".join(materiales) or None,
            "brazo_libre": not materiales,
            # Si el dia tiene parte subido, el material se sabe (y no llevar nada tambien se sabe, porque el
            # parte se rellena entero). Si no hay parte, el material es desconocido: el bloque no vale como
            # marca de brazo libre, por rapido que sea.
            "material_conocido": grupo[0]["actividad_id"] in con_parte,
        })

    actividad_actual = None
    for fila in filas:
        if fila["actividad_id"] != actividad_actual:
            if actual:
                cerrar(actual)
                actual = []
            actividad_actual = fila["actividad_id"]
        if fila["es_descanso"] or not fila["dist_m"]:
            if actual:
                cerrar(actual)
                actual = []
            continue
        actual.append(fila)
    if actual:
        cerrar(actual)
    return bloques


# ----------------------------------------------------------------------------- catalogo de segmentos


def _mediana(valores: list[float]) -> float | None:
    return round(st.median(valores), 1) if valores else None


def _mayoria(valores: list) -> object:
    """Valor mas repetido, con desempate deterministico.

    Sin ordenar antes, `max(set(...))` depende del orden interno del conjunto (que cambia entre ejecuciones):
    el mismo historico daria segmentos ligeramente distintos en cada pasada. Ordenando, el empate lo rompe
    siempre el valor mas bajo y el cuadro de mando sale igual todas las veces.
    """
    if not valores:
        return None
    return max(sorted(set(valores), key=str), key=valores.count)


def _mejor_fiable(ritmos: list[float]) -> float | None:
    """Marca de referencia: mediana de las 3 mejores, para que un solo lap mal cronometrado no la falsee."""
    if not ritmos:
        return None
    mejores = sorted(ritmos)[:3]
    return round(st.median(mejores), 1)


def _tendencia(apariciones: list[dict]) -> float | None:
    """Compara el ritmo de la primera mitad de las veces con el de la segunda (negativo = ha mejorado).

    Solo se comparan las veces hechas en la **misma piscina** (la mas habitual del segmento): un 400 m en
    piscina de 50 m no se puede mezclar con uno de 25 m, porque el tiempo cambia solo por el vaso.
    """
    piscinas = [a.get("piscina_m") for a in apariciones if a.get("piscina_m")]
    piscina = _mayoria(piscinas)
    con_ritmo = [a for a in apariciones
                 if a.get("ritmo_100") and (piscina is None or a.get("piscina_m") == piscina)]
    if len(con_ritmo) < 4:
        return None
    mitad = len(con_ritmo) // 2
    antes = st.median([a["ritmo_100"] for a in con_ritmo[:mitad]])
    despues = st.median([a["ritmo_100"] for a in con_ritmo[mitad:]])
    return round(despues - antes, 1)


def _segmento(nombre: str, tipo: str, apariciones: list[dict]) -> dict:
    """Resume un segmento (todas las veces que se ha hecho) en una ficha."""
    fiables = [a for a in apariciones if a.get("fiable", True)]
    ritmos = [a["ritmo_100"] for a in fiables if a.get("ritmo_100")]
    ritmos_todos = [a["ritmo_100"] for a in apariciones if a.get("ritmo_100")]
    largos = [a["dist_m"] for a in apariciones]
    fechas = sorted(a["inicio_local"] for a in apariciones if a.get("inicio_local"))
    piscinas = sorted({a["piscina_m"] for a in apariciones if a.get("piscina_m")})
    dist_media = st.mean(largos) if largos else 0
    return {
        "nombre": nombre,
        "tipo": tipo,
        "apariciones": len(apariciones),
        "dist_m": round(dist_media, 1),
        "tier": _tier(dist_media),
        "ritmo_mediana": _mediana(ritmos),
        "ritmo_mejor": _mejor_fiable(ritmos),
        "ritmo_mejor_absoluto": round(min(ritmos_todos), 1) if ritmos_todos else None,
        "ritmo_peor": round(max(ritmos), 1) if ritmos else None,
        "primera_vez": fechas[0][:10] if fechas else None,
        "ultima_vez": fechas[-1][:10] if fechas else None,
        "tendencia_s": _tendencia(apariciones),
        "piscinas": [p for p in piscinas if p],
        "estilo": apariciones[0].get("estilo"),
        "tecnica": apariciones[0].get("estilo") == "drill",
        "sin_ritmo": len(apariciones) - len(ritmos_todos),      # veces descartadas por cronometro imposible
        "no_fiable": len(apariciones) - len(fiables),           # veces descartadas por incoherencia
        # Peso = veces x longitud relativa: cuanto mas larga es la serie/bloque, mas valor tiene cada vez
        # que aparece (peticion expresa del atleta: "cuanto mas largos mejor").
        "peso": round(len(apariciones) * dist_media / 100.0, 1),
        "historial": [{"f": a["inicio_local"][:10], "r": round(a["ritmo_100"], 1)}
                      for a in fiables if a.get("ritmo_100")][-24:],
    }


def catalogo_segmentos(cn: sqlite3.Connection, bloques_: list[dict]) -> list[dict]:
    """Agrupa bloques y series en segmentos con nombre ("1.000 m seguidos", "10x100 m") y los resume."""
    agrupado: dict[tuple, list[dict]] = defaultdict(list)
    for b in bloques_:
        clave = ("bloque", _ronda(b["dist_m"]), b["estilo"], b["piscina_m"])
        agrupado[clave].append(b)

    for fila in cn.execute(
        """SELECT s.rep_m, s.n_reps, s.n_reps_validas, s.ritmo_medio_100, s.estilo,
                  s.material, s.calidad, s.comparable, s.descanso_medio_s, a.inicio_local, l.largo_piscina_m
           FROM serie s JOIN actividad a ON a.id = s.actividad_id
           JOIN natacion_sesion l ON l.actividad_id = a.id
           WHERE s.material = 'sin_etiquetar'"""
    ):
        dist = float(fila["rep_m"] or 0) * int(fila["n_reps_validas"] or 0)
        if dist < MIN_BLOQUE_M:
            continue
        agrupado[("serie", _ronda(fila["rep_m"]), int(fila["n_reps_validas"]), fila["estilo"],
                  fila["largo_piscina_m"])].append({
            "inicio_local": fila["inicio_local"],
            "dist_m": dist,
            "ritmo_100": fila["ritmo_medio_100"],
            "estilo": fila["estilo"],
            "piscina_m": fila["largo_piscina_m"],
            "fecha": (fila["inicio_local"] or "")[:10],
        })

    segmentos: list[dict] = []
    for clave, apariciones in agrupado.items():
        if clave[0] == "bloque":
            _, dist, estilo, piscina = clave
            nombre = f"{int(dist)} m seguidos{_sufijo(estilo, piscina)}"
            tipo = "bloque"
        else:
            _, rep, reps, estilo, piscina = clave
            nombre = f"{reps}x{int(rep)} m{_sufijo(estilo, piscina)}"
            tipo = "serie"
        if len(apariciones) >= 2:            # un segmento se repite: si solo se hizo una vez, es anecdota
            segmentos.append(_segmento(nombre, tipo, apariciones))

    segmentos.sort(key=lambda s: (-s["peso"], -s["dist_m"]))
    return segmentos


# ----------------------------------------------------------------------------- resumen y series temporales


def volumen(cn: sqlite3.Connection) -> dict:
    """Volumen de natacion por ano y por mes, con la duracion y el numero de sesiones."""
    por_ano: dict[str, dict] = defaultdict(lambda: {"sesiones": 0, "metros": 0.0, "segundos": 0.0})
    por_mes: dict[str, dict] = defaultdict(lambda: {"sesiones": 0, "metros": 0.0, "segundos": 0.0})
    for fila in cn.execute(
        """SELECT a.inicio_local, a.distancia_m, a.duracion_s FROM actividad a
           JOIN natacion_sesion s ON s.actividad_id = a.id WHERE a.inicio_local IS NOT NULL"""
    ):
        fecha = fila["inicio_local"][:10]
        for contador, clave in ((por_ano, fecha[:4]), (por_mes, fecha[:7])):
            contador[clave]["sesiones"] += 1
            contador[clave]["metros"] += float(fila["distancia_m"] or 0)
            contador[clave]["segundos"] += float(fila["duracion_s"] or 0)
    # Los entrenamientos apuntados a mano (sin reloj) cuentan igual: son metros nadados y sesiones de piscina.
    for fila in cn.execute("SELECT fecha, distancia_m, minutos FROM apunte WHERE lower(tipo) = 'natacion'"):
        if not fila["fecha"]:
            continue
        for contador, clave in ((por_ano, fila["fecha"][:4]), (por_mes, fila["fecha"][:7])):
            contador[clave]["sesiones"] += 1
            contador[clave]["metros"] += float(fila["distancia_m"] or 0)
            contador[clave]["segundos"] += 60.0 * float(fila["minutos"] or 0)
    return {
        "por_ano": [dict(clave=k, **{**v, "metros": round(v["metros"]), "horas": round(v["segundos"] / 3600, 1)})
                    for k, v in sorted(por_ano.items())],
        "por_mes": [dict(clave=k, **{**v, "metros": round(v["metros"]), "horas": round(v["segundos"] / 3600, 1)})
                    for k, v in sorted(por_mes.items())][-30:],
    }


def sesiones_recientes(cn: sqlite3.Connection, n: int = 25) -> list[dict]:
    """Ultimas sesiones de natacion con lo esencial de cada una."""
    filas = cn.execute(
        """SELECT a.id, a.inicio_local, a.id_garmin, a.nombre, a.distancia_m, a.duracion_s, s.largo_piscina_m,
                  s.sensacion, s.rpe, s.fc_media, s.fc_max
           FROM actividad a JOIN natacion_sesion s ON s.actividad_id = a.id
           WHERE a.inicio_local IS NOT NULL
           ORDER BY a.inicio_local DESC LIMIT ?""", (n,)
    ).fetchall()
    salida = []
    for fila in filas:
        dist, dur = float(fila["distancia_m"] or 0), float(fila["duracion_s"] or 0)
        n_laps = cn.execute("SELECT COUNT(*) FROM natacion_lap WHERE actividad_id = "
                            "(SELECT id FROM actividad WHERE id_garmin = ? AND disciplina='natacion')",
                            (fila["id_garmin"],)).fetchone()[0]
        salida.append({
            # `actividad_id` es la llave con la que el portal abre el parte de la sesion al pincharla.
            "actividad_id": fila["id"],
            "fecha": fila["inicio_local"][:10],
            "hora": fila["inicio_local"][11:16],
            "id_garmin": fila["id_garmin"],
            "nombre": fila["nombre"],
            "dist_m": round(dist),
            "min": round(dur / 60, 1),
            "ritmo_100": round(dur / (dist / 100), 1) if dist else None,
            "piscina_m": fila["largo_piscina_m"],
            "sensacion": fila["sensacion"],
            "rpe": fila["rpe"],
            "fc_media": fila["fc_media"],
            "laps": n_laps,
        })
    # Los entrenamientos apuntados a mano (sin reloj) tambien son sesiones y tienen que verse. Se saltan los
    # dias en los que ya hay una sesion del reloj, para no contar dos veces lo mismo.
    fechas_reloj = {s["fecha"] for s in salida}
    for a in cn.execute(
        """SELECT id, fecha, distancia_m, minutos, material, piscina_m, notas FROM apunte
           WHERE lower(tipo) = 'natacion' ORDER BY fecha DESC, id DESC LIMIT ?""", (n,)
    ):
        if a["fecha"] in fechas_reloj:
            continue
        dist = float(a["distancia_m"] or 0)
        mins = float(a["minutos"]) if a["minutos"] else None
        salida.append({
            # Sin `actividad_id` (no hay parte del reloj que abrir), pero con `apunte_id`: el portal pincha la
            # fila y lleva a la pestana Apuntes, que es donde esta el detalle de lo apuntado.
            "actividad_id": None, "apunte_id": a["id"], "fecha": a["fecha"], "hora": "",
            "id_garmin": None, "nombre": "Entrenamiento apuntado a mano (sin reloj)", "sin_reloj": True,
            "dist_m": round(dist), "min": mins,
            "ritmo_100": round(mins * 60 / (dist / 100), 1) if (mins and dist) else None,
            "piscina_m": a["piscina_m"], "sensacion": None, "rpe": None, "fc_media": None,
            "laps": 0, "material": a["material"], "notas": a["notas"],
        })
    salida.sort(key=lambda s: (s["fecha"] or "", s["hora"] or ""), reverse=True)
    return salida[:n]


def calendario(cn: sqlite3.Connection, dias: int = 400) -> list[dict]:
    """Un cuadro por dia, para pintar el **mes de verdad** en el portal: metros, sesiones y a donde lleva el clic.

    `metros == 0` significa que ese dia no hubo piscina: el portal lo marca aparte, que es lo que pidio el atleta
    ("marcar de manera diferente los dias que no he nadado"). El rango por defecto son 400 dias, para poder
    retroceder de mes en mes sin recargar. `actividad_id` es el nado mas largo del dia (a ese se va al pinchar) y
    `apunte_id` esta cuando el dia se apunto a mano, sin reloj.
    """
    hoy = date.today()
    desde = hoy - timedelta(days=dias)
    por_dia: dict[str, dict] = {}

    def _dia(fecha: str) -> dict:
        return por_dia.setdefault(fecha, {"metros": 0.0, "sesiones": 0, "actividad_id": None,
                                          "apunte_id": None, "apunte": False})

    # El ORDER BY deja primero el nado mas largo del dia: ese es el que se abre al pinchar.
    for fila in cn.execute(
        """SELECT a.id, a.inicio_local, a.distancia_m FROM actividad a JOIN natacion_sesion s
           ON s.actividad_id = a.id WHERE a.inicio_local >= ? ORDER BY a.distancia_m DESC""",
        (desde.isoformat(),)
    ):
        if not fila["inicio_local"]:
            continue
        d = _dia(fila["inicio_local"][:10])
        d["metros"] += float(fila["distancia_m"] or 0)
        d["sesiones"] += 1
        if d["actividad_id"] is None:
            d["actividad_id"] = fila["id"]

    # Y los apuntados a mano (sin reloj): si se nadaron, cuentan en el calendario, pero quedan marcados.
    for fila in cn.execute(
        """SELECT id, fecha, distancia_m FROM apunte
           WHERE lower(tipo) = 'natacion' AND fecha IS NOT NULL AND fecha >= ?""",
        (desde.isoformat(),)
    ):
        d = _dia(fila["fecha"])
        d["metros"] += float(fila["distancia_m"] or 0)
        d["sesiones"] += 1
        d["apunte"] = True
        if d["apunte_id"] is None:
            d["apunte_id"] = fila["id"]

    salida = []
    for i in range(dias + 1):
        fecha = (desde + timedelta(days=i)).isoformat()
        d = por_dia.get(fecha)
        salida.append({
            "fecha": fecha,
            "metros": round(d["metros"]) if d else 0,
            "sesiones": d["sesiones"] if d else 0,
            "actividad_id": d["actividad_id"] if d else None,
            "apunte_id": d["apunte_id"] if d else None,
            "apunte": bool(d and d["apunte"]),
        })
    return salida


def ritmos_por_distancia(cn: sqlite3.Connection, minima_m: float = 300.0) -> list[dict]:
    """Mejor y mediana de ritmo para cada distancia redonda nadada del tiron (300, 400, 500, 1.000...).

    Solo entran los bloques verificados (`fiable`): los laps con cronometro raro no pueden fijar una marca.
    """
    contador: dict[tuple, list[dict]] = defaultdict(list)
    for b in bloques(cn):
        if b["dist_m"] < minima_m or not b["ritmo_100"] or not b["fiable"]:
            continue
        contador[(_ronda(b["dist_m"]), b["estilo"], b["piscina_m"])].append(b)
    salida = []
    for (dist, estilo, piscina), lista in contador.items():
        if len(lista) < 3:
            continue
        ritmos = [x["ritmo_100"] for x in lista]
        salida.append({
            "dist_m": int(dist),
            "estilo": estilo,
            "piscina_m": piscina,
            "veces": len(lista),
            "mediana": round(st.median(ritmos), 1),
            "mejor": _mejor_fiable(ritmos),
            "absoluto": round(min(ritmos), 1),
            "ultima_vez": max(x["fecha"] for x in lista),
        })
    salida.sort(key=lambda r: (r["dist_m"], r["piscina_m"] or 0))
    return salida


def resumen_kpis(cn: sqlite3.Connection, bloques_: list[dict], segmentos: list[dict]) -> dict:
    """Cifras de cabecera del cuadro de mando."""
    uno = lambda sql, *a: cn.execute(sql, a).fetchone()[0]          # noqa: E731
    # Solo bloques de brazo libre, con ritmo creible y verificados por brazadas: la referencia de verdad. El
    # material (aletas, palas, pull) baja el ritmo sin que el atleta nade mejor, asi que no puede ser referencia.
    libras = [b for b in bloques_ if b["estilo"] == "libre" and b["ritmo_100"] and b["fiable"]
              and b.get("brazo_libre")]
    largos = [b for b in bloques_ if b["dist_m"] >= 800]

    def mejor(minimo_m: float) -> dict | None:
        """Marca de referencia en bloques de esa distancia (hasta un 25% mas) en piscina de 25 m.

        Se acota por arriba a proposito: "400 m" son bloques de 400 a 500 m, no cualquier cosa mas larga.
        """
        candidatos = [b for b in libras if minimo_m <= b["dist_m"] < minimo_m * 1.25 and b["piscina_m"] == 25]
        if not candidatos:
            return None
        ritmos = sorted(b["ritmo_100"] for b in candidatos)
        el_mejor = min(candidatos, key=lambda x: x["ritmo_100"])
        return {"fiable": _mejor_fiable(ritmos), "absoluto": round(ritmos[0], 1), "veces": len(candidatos),
                "poca_base": len(candidatos) < 3, "dist_m": int(el_mejor["dist_m"]), "fecha": el_mejor["fecha"],
                "id_garmin": el_mejor["id_garmin"]}

    return {
        "sesiones": uno("SELECT COUNT(*) FROM natacion_sesion"),
        "metros_totales": int(uno("SELECT COALESCE(SUM(distancia_m),0) FROM actividad WHERE disciplina='natacion'")),
        "primera": uno("SELECT MIN(inicio_local) FROM actividad WHERE disciplina='natacion'")[:10],
        "ultima": uno("SELECT MAX(inicio_local) FROM actividad WHERE disciplina='natacion'")[:10],
        "bloques": len(bloques_),
        "bloques_largos": len(largos),
        "bloques_800": len(largos),
        "verificados": sum(1 for b in bloques_ if b["fiable"]),
        "series": uno("SELECT COUNT(*) FROM serie"),
        "series_comparables": uno("SELECT COUNT(*) FROM serie WHERE comparable=1"),
        "segmentos": len(segmentos),
        "material_etiquetado": uno("SELECT COUNT(*) FROM serie WHERE material <> 'sin_etiquetar'"),
        "60dias": uno("SELECT COUNT(*) FROM actividad WHERE disciplina='natacion' "
                      "AND inicio_local >= date('now','-60 day')"),
        "mejor_400": mejor(400),
        "mejor_1000": mejor(1000),
        "mejor_1500": mejor(1500),
        "bloque_mas_largo": max((b["dist_m"] for b in bloques_), default=0),
    }


def fuerza(cn: sqlite3.Connection) -> dict:
    """La fuerza que sostiene el hombro, como la mide el modulo de fuerza (V1.4-01, V1.4-02).

    El portal pinta esto tal cual: la dosis preventiva del anexo T.7 con su estado, el aviso de abandono, el
    aviso de seguridad si hay dolor declarado y la carga de la semana (sesiones, series, repeticiones y kilos,
    solo de lo que se apunta a mano: el reloj no sabe de ejercicios).
    """
    from . import fuerza as _fuerza
    return _fuerza.datos(cn)


def gimnasio(cn: sqlite3.Connection) -> dict:
    """Lo poco que hay de gimnasio, dicho tal cual.

    El reloj solo guarda la duracion y la fecha: **no hay ni un ejercicio, ni una serie, ni un peso**, asi que
    aqui no se inventa nada. La seccion existe para que se vea el hueco y se decida de donde se saca el dato.
    """
    filas = [dict(r) for r in cn.execute(
        "SELECT substr(inicio_local, 1, 10) AS fecha, substr(inicio_local, 12, 5) AS hora, nombre, duracion_s"
        " FROM actividad WHERE disciplina = 'gimnasio' ORDER BY inicio_local DESC")]
    por_anio = {}
    for f in filas:
        d = por_anio.setdefault(f["fecha"][:4], {"anio": f["fecha"][:4], "sesiones": 0, "minutos": 0.0})
        d["sesiones"] += 1
        d["minutos"] += (f["duracion_s"] or 0) / 60.0
    for d in por_anio.values():
        d["minutos"] = round(d["minutos"])
    minutos = [f["duracion_s"] / 60.0 for f in filas if f["duracion_s"]]
    return {
        "sesiones": filas,
        "por_anio": [por_anio[a] for a in sorted(por_anio, reverse=True)],
        "n": len(filas),
        "minutos_media": round(sum(minutos) / len(minutos)) if minutos else None,
        "ultima": filas[0]["fecha"] if filas else None,
        "nota": ("El reloj no guarda ejercicios, series ni pesos de gimnasio: solo la duracion. Para poder "
                 "analizar la fuerza hay que decidir de donde se saca el dato (apuntarlo a mano o con una app "
                 "que si lo registre). Hasta entonces, esta parte queda vacia y el programa no la rellena."),
    }


def analizar(cn: sqlite3.Connection) -> dict:
    """Construye todo el paquete de analitica (lo que consume el cuadro de mando).

    Incluye las dos partes del proyecto: el entrenamiento (natacion) y el portal de bici (segmentos repetidos
    y comparacion de resultados). El portal de bici se importa aqui dentro para no obligar a tener datos de
    bici cuando solo se mira la natacion.
    """
    from . import bici, evaluacion as _evaluacion, partes as _partes

    bl = bloques(cn)
    segmentos = catalogo_segmentos(cn, bl)
    datos = {
        "generado": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "kpis": resumen_kpis(cn, bl, segmentos),
        "segmentos": segmentos,
        "bloques_largos": sorted([b for b in bl if b["ritmo_100"]],
                                 key=lambda b: -b["dist_m"])[:25],
        "ritmos_por_distancia": ritmos_por_distancia(cn),
        "volumen": volumen(cn),
        "calendario": calendario(cn),
        "sesiones_recientes": sesiones_recientes(cn),
        "gimnasio": gimnasio(cn),
        "fuerza": fuerza(cn),
        "bici": bici.datos_panel(cn),
        # El parte de cada sesion de natacion (grupos, material e intensidad) y la evaluacion contra el plan.
        "partes": _partes.datos_panel(cn),
        "evaluacion": _evaluacion.datos_panel(cn),
        "nota_material": ("El reloj no registra palas, aletas ni la intensidad: eso se pone en el parte "
                          "(en Entrenamientos, pinchando la sesion) agrupando los intervalos. Lo que lleve "
                          "material sale de las comparaciones de brazo libre."),
    }
    # Lo que no sale del entrenamiento y el cuadro de mando tambien pinta: las marcas oficiales de competicion
    # (tabla `competicion`) y el plan de las semanas hasta el 400 y el 3.000 (modulo `plan`). Se hace aqui, y no
    # solo en la orden de consola, para que cualquier consumidor de la analitica (consola, pruebas, futuras
    # paginas) reciba lo mismo: si no, una pasada de pruebas dejaba el cuadro de mando sin estas secciones.
    from . import panel as _panel
    datos.update(_panel.datos_panel(cn))

    # El bucle cerrado (V1.3): el credito de cada regla y las ultimas propuestas con su porque, para la vista
    # Reglas del portal. Sale de la base, no se calcula en el navegador.
    from . import decision as _decision
    datos["entrenador"] = _decision.datos_entrenador(cn)
    # La valoracion del entrenador (el discurso del Resumen): se compone con los datos ya calculados, para que
    # hable con los numeros de verdad y se recalcule sola en cada pasada.
    from . import valoracion as _valoracion
    datos["valoracion"] = _valoracion.discurso(cn, bl, datos)
    return datos


def guardar_json(datos: dict, ruta: str) -> str:
    """Escribe el paquete de analitica en JSON (para el cuadro de mando y para consultas a mano)."""
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False, indent=1)
    return ruta
