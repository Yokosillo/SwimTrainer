#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""El parte de una sesion de natacion: agrupar los intervalos, marcar material e intensidad, y guardarlo.

El reloj da los **intervalos** (laps), pero no da dos cosas que hacen falta para saber que se ha hecho de
verdad: el **material** (palas, aletas, pull...) y la **intensidad** (si eso era calentamiento, aerobico
ligero, medio o intenso). Comprobado sobre el historico: 0 de 23.417 laps traen material y 23.148 no traen
intensidad; la que traen algunos ("activo") significa "en marcha", no "intenso".

Aqui se hace lo que el reloj puede dar y el atleta decide:

1. **Agrupar**: los intervalos se juntan en grupos (una serie de 6x100, un bloque de 1.000 del tiron) por
   distancia, estilo y descanso. Se **propone**, y el atleta puede partir, unir o quitar grupos en el portal.
2. **Marcar material e intensidad** por grupo. La intensidad se **sugiere** comparando el ritmo con el
   historico del propio atleta (misma distancia, mismo estilo, misma piscina) y se **avisa** cuando lo que
   ha marcado no cuadra con el ritmo medido. El selector manda: es su sensacion, no un calculo.
3. **Guardar el parte** (tablas `parte` y `parte_serie`) y **propagar el material** a los laps y a las
   series, para que lo hecho con material no cuente como marca de brazo libre. El fichero del reloj (FIT) no
   se toca nunca: el parte manda sobre el material y la intensidad, y lo que manda se reescribe entero cada
   vez que se importa (si el atleta quita un material, deja de estar).

Uso:
    python -m entrenador.cli partes                  # los partes que ya constan
    python -m entrenador.cli partes --pendientes      # sesiones del reloj sin parte, con los grupos propuestos
    python -m entrenador.cli servir                   # servidor local: el boton "Subir" del portal
    python -m entrenador.cli partes --importar        # (a mano) lee Descargas/partes_entrenador.json
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics as st

from . import aprendizaje, concepto, correcciones, db, parciales, pruebas

# Lo que se puede marcar como material. No hay "brazo libre" que marcar: no marcar nada ES nadar a brazo libre
# (esos laps se quedan en `sin_etiquetar`, que es justo lo que la analitica compara como marca suya).
# El primer dia que cuenta para el parte: lo anterior se da por rellenado (el atleta no va a meter esos datos).
PRIMER_DIA_CON_PARTE = "2026-10-12"
MATERIALES = ("pull", "aletas", "palas", "tabla", "snorkel")
MATERIALES_TODOS = MATERIALES + ("brazo_libre",)   # se sigue leyendo de ficheros y apuntes viejos
# La clave `snorkel` se queda como esta (es lo que hay guardado en la base y en los ficheros viejos): lo que
# cambia es el **nombre que se enseña**, que el atleta llama tuba.
NOMBRE_MATERIAL = {"pull": "pull-buoy", "aletas": "aletas", "palas": "palas", "tabla": "tabla",
                   "snorkel": "tuba", "brazo_libre": "brazo libre"}
# Las intensidades del parte. `tecnica` (educativos/drills) y `salida` (salida con crono) se marcan aparte
# porque no son ni carga ni nado a ritmo: la tecnica es economia y la salida es velocidad de reaccion.
INTENSIDADES = ("cal", "ae1", "ae2", "ae3", "swolf", "pies", "tecnica", "salida")
ETIQUETA_INTENSIDAD = {"cal": "Calentamiento/recuperar", "ae1": "AeLigero", "ae2": "AeMedio",
                       "ae3": "AeIntenso", "swolf": "SWOLF (series de 50)",
                       "pies": "Pies", "tecnica": "Tecnica", "salida": "Salida con crono"}
# Los estilos que se pueden marcar en un grupo (o en una repeticion). `libre` es crol; `estilos` es el
# combinado de los cuatro estilos (lo que en las listas de salida aparece como "estilos").
ESTILOS_PARTE = ("libre", "mariposa", "espalda", "braza", "estilos")
ETIQUETA_ESTILO = {"libre": "Crol", "mariposa": "Mariposa", "espalda": "Espalda",
                   "braza": "Braza", "estilos": "Estilos"}
ESTILOS_TODOS = ESTILOS_PARTE + ("drill",)   # `drill` es lo que mandan los relojes para educativos
# Con quien se ha hecho la sesion: las de lunes, miercoles y viernes las manda el entrenador del equipo y no
# se tocan; las demas son las del atleta. Saberlo separa "lo que me han mandado" de "lo que me he hecho yo".
COMPANIAS = ("solo", "entrenador")
ETIQUETA_COMPANIA = {"solo": "Mia en solitario", "entrenador": "Con el entrenador del equipo"}
# Un pataleo no es nado: se marca como `pies` y su ritmo **no** se compara con el del plan ni cuenta como
# marca de brazo libre (el reloj lo mide igual, pero 100 m de pataleo no son 100 m nadados).
# El SWOLF es el idioma de las series cortas: se apunta el medido, repeticion a repeticion.
SWOLF_MIN, SWOLF_MAX = 15.0, 150.0

DESCANSO_MAX_S = 180.0      # un descanso mas largo que esto corta el grupo
PASO_M = 0.5                # margen para considerar que dos intervalos son la misma repeticion
RITMO_MIN, RITMO_MAX = 60.0, 300.0
BRAZADAS_MIN_M, BRAZADAS_MAX_M = 0.20, 0.80
MIN_CORTES = 8              # con menos medidas, los cortes de intensidad no se usan (poca base)
NOMBRE_FICHERO = "partes_entrenador.json"


# ------------------------------------------------------------------ agrupar los intervalos del reloj


def _ritmo(dist_m: float, tiempo_s: float) -> float | None:
    if not dist_m or not tiempo_s or dist_m <= 0 or tiempo_s <= 0:
        return None
    return round(100.0 * tiempo_s / dist_m, 1)


def _clase_estilo(estilo: str | None) -> str | None:
    """Para agrupar: la tecnica (drill) es una clase aparte; lo demas se junta entre si."""
    if not estilo:
        return None
    return "tecnica" if estilo == "drill" else estilo


def _intensidad(x) -> str | None:
    """La intensidad de un grupo o de una repeticion, solo si es una de las que existen.

    Ojo con recortarla: `tecnica` y `salida` son mas largas que los codigos de antes (cal, ae1...) y un
    recorte silencioso las dejaba fuera del parte sin avisar.
    """
    valor = _texto(x).strip().lower()
    return valor if valor in INTENSIDADES else None


def _prueba(x) -> str | None:
    """La prueba de medicion que el atleta le marca a un grupo: el 1500, un 400, una serie de 100, su escalera.

    Es suya: no se deduce de nada. Vacio significa que el bloque no es prueba.
    """
    return pruebas.limpiar(x)


def _estilo_del_grupo(x) -> str | None:
    """El estilo de un grupo. Se acepta un nombre del catalogo o el `drill` del reloj; lo que no se reconoce
    se guarda igual (mejor no perder lo que mando el reloj), en minusculas."""
    return _texto(x).strip().lower() or None


def _compania(x) -> str | None:
    """Con quien se hizo la sesion. Solo valen los dos valores del catalogo; si no, se deja en blanco."""
    valor = _texto(x).strip().lower()
    return valor if valor in COMPANIAS else None


def _cerrar(grupo: dict, cortes: list[dict] | None = None) -> dict:
    """Cierra un grupo de intervalos: metros, tiempo, ritmo, descanso y avisos.

    Los intervalos con el cronometro disparado a destiempo (el reloj a veces marca 9 s en un 50 m) **no
    entran en el ritmo**: se sustituye su tiempo por el que le tocaria al ritmo mediano del propio grupo, y
    se avisa. Si no, un solo intervalo roto estropea la serie entera.
    """
    reps = grupo["reps"]
    metros = sum(r["dist_m"] for r in reps)
    ritmos = [r["ritmo_100"] for r in reps if r["ritmo_100"] and RITMO_MIN <= r["ritmo_100"] <= RITMO_MAX]
    import statistics as st

    referencia = st.median(ritmos) if ritmos else None
    tiempo = 0.0
    for r in reps:
        bueno = r["ritmo_100"] is not None and RITMO_MIN <= r["ritmo_100"] <= RITMO_MAX
        if bueno:
            tiempo += r["timer_s"]
        elif referencia is not None:
            tiempo += referencia * r["dist_m"] / 100.0
        else:
            tiempo += r["timer_s"]
    descansos = [d for d in grupo["descansos"] if d]
    # El "cada" de una serie es el **intervalo de salida**: del inicio de una repeticion al inicio de la
    # siguiente, que es como se canta en la piscina ("8x100 cada 2:00", "3x400 cada 6:30"). Dice mas que el
    # descanso suelto (que cambia de una repeticion a otra y no se lee de un vistazo).
    # Cada repeticion se queda con el descanso que va detras de ella: es lo que hace falta para rehacer el cada
    # cuando el bloque se parte o se junta a mano en el portal (alli ya no se sabe que intervalos eran descanso).
    for i, r in enumerate(reps):
        r["descanso_s"] = round(float(grupo["descansos"][i] or 0), 1) if i < len(grupo["descansos"]) else None
    salidas = [float(reps[i]["timer_s"]) + float(reps[i]["descanso_s"] or 0) for i in range(len(reps) - 1)]
    cada = _redondear_cada(st.median(salidas)) if salidas else None
    distancias = [r["dist_m"] for r in reps]
    uniforme = (max(distancias) - min(distancias)) <= PASO_M
    tipo = "serie" if (uniforme and len(reps) >= 2) else "continuo"

    avisos = []
    rotos = [r for r in reps if r["revisar"]]
    if rotos:
        avisos.append("intervalo con el cronometro mal disparado (" +
                      ", ".join(f"{r['dist_m']:.0f} m en {r['timer_s']:.0f} s" for r in rotos) +
                      "): su tiempo no cuenta para el ritmo")
    brazadas = sum(r["brazadas"] or 0 for r in reps)
    brazadas_m = round(brazadas / metros, 3) if (brazadas and metros) else None
    if brazadas_m is None:
        avisos.append("ningun intervalo trae brazadas: o es material (palas, aletas, pull) o es tecnica. Confirmalo")
    elif not (BRAZADAS_MIN_M <= brazadas_m <= BRAZADAS_MAX_M):
        avisos.append(f"brazadas por metro fuera de lo normal ({brazadas_m}): puede ser material")
    if not uniforme and len(reps) >= 3:
        avisos.append(f"intervalos de distinta distancia ({min(distancias):.0f}-{max(distancias):.0f} m): "
                      "separa o une los que quieras")

    # Lo que duro el bloque entero, con los descansos de dentro (del inicio de la primera repeticion al final de
    # la ultima): es lo que va en la cabecera del bloque, que a secas solo dice lo nadado y se queda corto.
    entre = sum(float(d or 0) for d in grupo["descansos"][:max(0, len(reps) - 1)])
    total = round(tiempo + entre, 1)

    ritmo = _ritmo(metros, tiempo)
    if not ritmos:
        ritmo = None
        avisos.append("todos los intervalos traen el cronometro mal disparado: el ritmo del grupo no es fiable")
    salida = {
        "tipo": tipo,
        "rep_m": round(reps[0]["dist_m"], 1) if uniforme else 0.0,
        "n_reps": len(reps),
        "metros": round(metros, 1),
        "tiempo_s": round(tiempo, 2),
        "total_s": total,
        "ritmo_100": ritmo,
        "descanso_s": round(sum(descansos) / len(descansos), 1) if descansos else None,
        "cada_s": cada,
        "estilo": grupo["estilo"],
        "brazadas_m": brazadas_m,
        "reps": reps,
        "laps": [r["lap_idx"] for r in reps],
        "avisos": avisos,
    }
    # La forma del bloque (regular, progresiva, aflojando...) se mide de los tiempos de sus repeticiones, con
    # el margen que el sistema ha aprendido de sus propios partes. Los intervalos con el cronometro mal
    # disparado se apartan: no cuentan para la forma, igual que no cuentan para el ritmo.
    evidencia = forma_del_grupo(reps)
    salida["concepto"] = evidencia.get("concepto")
    salida["concepto_evidencia"] = evidencia

    if cortes:
        sugerida, motivo = sugerir_intensidad(salida, cortes)
        salida["intensidad_sugerida"] = sugerida
        salida["motivo_intensidad"] = motivo
    return salida


def ritmos_de_reps(cn: sqlite3.Connection | None, actividad_id, reps: list[dict]) -> list:
    """El ritmo de cada repeticion de un bloque: el que trae la repeticion o el del intervalo del reloj.

    Las repeticiones guardadas en el parte solo apuntan a su intervalo del reloj (`lap`): el tiempo se lee de
    `natacion_lap`. Las de una propuesta recien hecha ya traen su ritmo calculado, y por eso `cn` es opcional.
    """
    idxs = [r.get("lap") for r in (reps or []) if r.get("lap") is not None]
    filas = {}
    if cn is not None and actividad_id is not None and idxs:
        marcas = ",".join("?" * len(idxs))
        filas = {f["lap_idx"]: f for f in cn.execute(
            f"SELECT lap_idx, dist_m, timer_s FROM natacion_lap "
            f"WHERE actividad_id = ? AND lap_idx IN ({marcas})", (actividad_id, *idxs))}
    salida = []
    for r in (reps or []):
        ritmo = r.get("ritmo_100")
        if not ritmo:
            dist = float(r.get("dist_m") or 0)
            tiempo = r.get("timer_s") or r.get("tiempo_s")
            lap = r.get("lap")
            if not tiempo and lap is not None and lap in filas:
                dist, tiempo = float(filas[lap]["dist_m"] or 0), filas[lap]["timer_s"]
            ritmo = _ritmo(dist, float(tiempo or 0))
        salida.append(ritmo)
    return salida


def forma_del_grupo(reps: list[dict], cn: sqlite3.Connection | None = None, actividad_id=None) -> dict:
    """La forma de un bloque a partir de sus repeticiones (las propuestas o las que ya estan guardadas).

    Los intervalos con el cronometro mal disparado se apartan: no cuentan para la forma, igual que no cuentan
    para el ritmo.
    """
    ritmos = ritmos_de_reps(cn, actividad_id, reps)
    malos = [i for i, r in enumerate(ritmos)
             if not (r and RITMO_MIN <= r <= RITMO_MAX)]
    return concepto.medir(ritmos, malos=malos)


def descanso_max_grupo() -> float:
    """Cuanto descanso todavia es "la misma serie": lo que ha aprendido de sus partes, o el tope de siempre.

    Es la regla que agrupa de verdad: cuando sube un entrenamiento, los intervalos se juntan en un bloque
    mientras el descanso entre ellos no pase de aqui. El tope se aprende de sus propios partes
    (`aprendizaje.agrupacion`): si nunca ha descansado mas de un minuto dentro de una serie, una pausa de
    minuto y medio ya es otro bloque.
    """
    try:
        return float(aprendizaje.descanso_mismo_bloque())
    except Exception:
        return DESCANSO_MAX_S


def proponer_grupos(laps: list[dict], cortes: list[dict] | None = None) -> list[dict]:
    """Agrupa los intervalos de una sesion en grupos revisables.

    Se corta el grupo cuando cambia la distancia de la repeticion (mas de `PASO_M`), cuando cambia el estilo
    (libre <-> tecnica) o cuando el descanso entre dos intervalos pasa del tope que ha aprendido de sus partes
    (`aprendizaje.descanso_mismo_bloque`, que arranca en `DESCANSO_MAX_S` y se ajusta con lo que hace de
    verdad). Nada se descarta: un intervalo suelto es un grupo de tipo `continuo`.
    """
    tope_descanso = descanso_max_grupo()
    grupos: list[dict] = []
    actual: dict | None = None
    pendiente = 0.0            # descanso acumulado desde el ultimo intervalo
    for lap in laps:
        dist = float(lap.get("dist_m") or 0)
        if dist <= 0:
            pendiente += float(lap.get("timer_s") or 0)
            continue
        estilo = lap.get("estilo")
        corte = False
        if actual is not None:
            corte = (abs(dist - actual["reps"][0]["dist_m"]) > PASO_M or pendiente > tope_descanso
                     or (_clase_estilo(estilo) is not None and _clase_estilo(actual["estilo"]) is not None
                         and _clase_estilo(estilo) != _clase_estilo(actual["estilo"])))
        if corte:
            grupos.append(_cerrar(actual, cortes))
            actual = None
        if actual is None:
            actual = {"reps": [], "descansos": [], "estilo": estilo}
        else:
            actual["descansos"].append(pendiente)
            if actual["estilo"] is None:
                actual["estilo"] = estilo
        pendiente = 0.0
        ritmo = _ritmo(dist, float(lap.get("timer_s") or 0))
        actual["reps"].append({
            "lap_idx": lap.get("lap_idx"),
            "dist_m": dist,
            "timer_s": float(lap.get("timer_s") or 0),
            "ritmo_100": ritmo,
            "brazadas": lap.get("brazadas"),
            "fc_media": lap.get("fc_media"),
            "estilo": estilo,
            # El SWOLF del reloj (tiempo + brazadas) se propone ya puesto: el atleta solo corrige si mide otro.
            "swolf": _swolf(lap),
            "revisar": ritmo is None or not (RITMO_MIN <= ritmo <= RITMO_MAX),
        })
    if actual is not None:
        grupos.append(_cerrar(actual, cortes))
    for i, g in enumerate(grupos):
        g["orden"] = i
    return grupos


# ------------------------------------------------------------------ intensidad: cortes del propio historico


def cortes_intensidad(cn: sqlite3.Connection, minimo: int = MIN_CORTES) -> list[dict]:
    """Percentiles del ritmo por tipo de grupo y distancia, sacados de su propio historico.

    Son la referencia para **sugerir** la intensidad y para **avisar** cuando lo marcado no cuadra. No
    deciden nada: el selector manda. Con menos de `minimo` medidas no se devuelve el corte (poca base) y el
    portal lo dice en vez de inventarse un rango.
    """
    from collections import defaultdict

    cubos: dict[tuple, list[float]] = defaultdict(list)
    for f in cn.execute("SELECT rep_m AS dist, ritmo_medio_100 AS ritmo FROM serie"
                        " WHERE comparable = 1 AND ritmo_medio_100 IS NOT NULL"):
        cubos[("serie", round(float(f["dist"]) / 25.0) * 25.0)].append(float(f["ritmo"]))
    # Los continuos que sirven de referencia son los de brazo libre: lo que lleva material (aletas, palas, pull)
    # baja el ritmo sin que el atleta nade mejor, asi que no puede marcar el nivel de nadie.
    for f in cn.execute("SELECT dist_m AS dist, 100.0 * timer_s / dist_m AS ritmo FROM natacion_lap"
                        " WHERE es_descanso = 0 AND dist_m >= 200 AND timer_s > 0"
                        "   AND (material IS NULL OR material = '' OR material = 'sin_etiquetar')"):
        r = float(f["ritmo"])
        if RITMO_MIN <= r <= RITMO_MAX:
            cubos[("continuo", round(float(f["dist"]) / 50.0) * 50.0)].append(r)

    salida = []
    for (tipo, dist), valores in sorted(cubos.items()):
        if len(valores) < minimo:
            continue
        valores.sort()

        def cuantil(p: float) -> float:
            return round(valores[min(len(valores) - 1, int(p * len(valores)))], 1)

        salida.append({"tipo": tipo, "dist_m": dist, "n": len(valores),
                       "p25": cuantil(0.25), "p50": cuantil(0.5), "p75": cuantil(0.75)})
    return salida


def _corte_de(grupo: dict, cortes: list[dict]) -> dict | None:
    """El corte que le toca a un grupo: misma clase de grupo y distancia parecida.

    En series se pide la misma distancia exacta (una serie de 100 no se compara con una de 400). En bloques
    continuos, donde hay menos medidas, se admite la distancia parecida mas cercana: un 100 m del tiron se
    mira contra los 100-200 m y se dice en el motivo.
    """
    tipo = "serie" if grupo["tipo"] == "serie" else "continuo"
    dist = grupo["rep_m"] if tipo == "serie" else grupo["metros"]
    if not dist:
        return None
    candidatos = [c for c in cortes if c["tipo"] == tipo and dist <= c["dist_m"] < dist * 1.25]
    if candidatos:
        return candidatos[0]
    if tipo == "continuo":
        cercanos = [c for c in cortes if c["tipo"] == "continuo" and dist * 0.5 <= c["dist_m"] <= dist * 1.75]
        if cercanos:
            return min(cercanos, key=lambda c: abs(c["dist_m"] - dist))
    return None


def sugerir_intensidad(grupo: dict, cortes: list[dict]) -> tuple[str | None, str | None]:
    """Intensidad sugerida (y por que) a partir del ritmo medido y de su historico. Sugerencia, no decision."""
    if not grupo.get("ritmo_100"):
        return None, None
    corte = _corte_de(grupo, cortes)
    if not corte:
        return None, "sin historico comparable para esta distancia: marcala tu"
    r = grupo["ritmo_100"]
    if r < corte["p25"]:
        cual, donde = "ae3", "mas rapido que tu cuarto mejor de cada 4 veces"
    elif r < corte["p50"]:
        cual, donde = "ae2", "por debajo de tu mediana"
    elif r < corte["p75"]:
        cual, donde = "ae1", "por encima de tu mediana"
    else:
        cual, donde = "cal", "en tu cuarto mas lento"
    return cual, (f"{r} s/100 {donde} ({corte['dist_m']:.0f} m {grupo['tipo']}: "
                   f"p25 {corte['p25']} | mediana {corte['p50']} | p75 {corte['p75']}, "
                   f"{corte['n']} veces)")


# ------------------------------------------------------------------ lo que consume el portal


def _laps_de(cn: sqlite3.Connection, actividad_id: int) -> list[dict]:
    return [dict(f) for f in cn.execute(
        "SELECT lap_idx, inicio, dist_m, timer_s, n_largos, estilo, fc_media, brazadas, es_descanso"
        " FROM natacion_lap WHERE actividad_id = ? ORDER BY lap_idx", (actividad_id,))]


def sesiones_sin_parte(cn: sqlite3.Connection, limite: int = 3) -> list[dict]:
    """Las ultimas sesiones de piscina del reloj que todavia no tienen parte, con su propuesta de grupos.

    Solo desde el 12/10/2026: lo de antes se da por rellenado a peticion del atleta (no va a meter esos datos).
    """
    cortes = cortes_intensidad(cn)
    filas = cn.execute(
        """SELECT a.id, a.id_garmin, a.inicio_local, a.nombre, a.distancia_m,
                  s.largo_piscina_m, s.sensacion, s.rpe, s.fc_media
           FROM natacion_sesion s JOIN actividad a ON a.id = s.actividad_id
           WHERE s.largo_piscina_m IS NOT NULL
             AND substr(a.inicio_local, 1, 10) >= ?
             AND NOT EXISTS (SELECT 1 FROM parte p WHERE p.actividad_id = a.id)
           ORDER BY a.inicio_local DESC LIMIT ?""", (PRIMER_DIA_CON_PARTE, limite)).fetchall()
    salida = []
    for f in filas:
        laps = _laps_de(cn, f["id"])
        activos = [x for x in laps if not x["es_descanso"] and (x["dist_m"] or 0) > 0]
        salida.append({
            "actividad_id": f["id"], "id_garmin": f["id_garmin"], "fecha": (f["inicio_local"] or "")[:10],
            "hora": (f["inicio_local"] or "")[11:16], "nombre": f["nombre"],
            "piscina_m": f["largo_piscina_m"], "metros": round(sum(x["dist_m"] for x in activos), 1),
            "n_intervalos": len(activos), "sensacion": f["sensacion"], "rpe": f["rpe"], "fc_media": f["fc_media"],
            "grupos": correcciones.aplicar(cn, f["id"], laps,
                                          parciales.pasos_de(cn, f["id"], proponer_grupos(laps, cortes))),
            "ya_importado": False,
        })
    return salida


def _swolf(lap: dict) -> float | None:
    """El SWOLF del reloj de esa repeticion: tiempo (s) + brazadas.

    Es la cuenta que usa el propio reloj. Verificado con los largos de 25 m reales: sale 30-43 por largo (por
    50 m, ~60). Si falta el tiempo o las brazadas no hay SWOLF del reloj: lo que haya medido el atleta manda.
    """
    brazadas = lap.get("brazadas")
    tiempo = float(lap.get("timer_s") or 0)
    if not brazadas or not tiempo:
        return None
    v = round(tiempo + float(brazadas), 1)
    return v if SWOLF_MIN <= v <= SWOLF_MAX else None


def rellenar_reps(grupo: dict, laps: dict[int, dict]) -> dict:
    """Completa un grupo leido de la base con sus repeticiones.

    La base guarda de cada grupo sus numeros y el JSON con los indices de lap; las repeticiones (con su
    ritmo, brazadas y pulso) se reconstruyen desde los laps del reloj, que no cambian. Asi lo que se lee de
    la base es igual que lo que se propuso al rellenar el parte, sin guardar lo mismo dos veces.
    """
    reps = []
    for i in grupo.get("laps") or []:
        lap = laps.get(int(i))
        if not lap:
            continue
        dist = float(lap.get("dist_m") or 0)
        tiempo = float(lap.get("timer_s") or 0)
        ritmo = _ritmo(dist, tiempo)
        reps.append({"lap_idx": int(i), "dist_m": dist, "timer_s": tiempo, "ritmo_100": ritmo,
                     "brazadas": lap.get("brazadas"), "fc_media": lap.get("fc_media"),
                     "estilo": lap.get("estilo"), "swolf": _swolf(lap),
                     "revisar": ritmo is None or not (RITMO_MIN <= ritmo <= RITMO_MAX)})
    # El descanso que va detras de cada repeticion, sumando los intervalos de descanso que caen antes de la
    # siguiente: con el se rehace el cada del bloque aunque el parte sea viejo y no lo traiga.
    for j, r in enumerate(reps):
        siguiente = reps[j + 1]["lap_idx"] if j + 1 < len(reps) else None
        r["descanso_s"] = (round(sum(float(l.get("timer_s") or 0) for k, l in laps.items()
                                    if r["lap_idx"] < k < siguiente), 1)
                          if siguiente is not None else None)
    grupo["reps"] = reps
    grupo.setdefault("avisos", [])
    if reps:
        grupo["n_reps"] = len(reps)
        metros = sum(r["dist_m"] for r in reps)
        brazadas = sum(r["brazadas"] or 0 for r in reps)
        grupo["brazadas_m"] = round(brazadas / metros, 3) if (brazadas and metros) else None
    return grupo


def partes_de(cn: sqlite3.Connection, limite: int = 12) -> list[dict]:
    """Los partes que ya constan en la base, con sus grupos."""
    filas = cn.execute("SELECT * FROM parte ORDER BY fecha DESC, id DESC LIMIT ?", (limite,)).fetchall()
    salida = []
    for f in filas:
        p = dict(f)
        p["series"] = [dict(s) for s in cn.execute(
            "SELECT * FROM parte_serie WHERE parte_id = ? ORDER BY orden", (f["id"],))]
        for s in p["series"]:
            s["material"] = [m for m in (s.get("material") or "").split(",") if m]
            # `laps` y `reps` se guardan como JSON de texto: el portal trabaja con listas.
            s["laps"] = json.loads(s.get("laps") or "[]")
            s["reps"] = json.loads(s.get("reps") or "[]")
            # La forma del bloque se mide de sus repeticiones al leerlo: no se guarda (sale de los tiempos y
            # cambiaria con el margen aprendido), asi que un parte viejo tambien la ensena.
            evidencia = forma_del_grupo(s["reps"], cn, p["actividad_id"])
            s["concepto"] = evidencia.get("concepto")
            s["concepto_evidencia"] = evidencia
        salida.append(p)
    return salida


def _actividad_de_fecha(cn: sqlite3.Connection, fecha: str | None, metros: float | None = None) -> int | None:
    """La sesion de natacion de ese dia (la mas parecida en metros, si ese dia hay varias).

    Un parte puede llegar sin `actividad_id` (ficheros viejos, partes escritos a mano): en vez de dejar el
    material y los tiempos sin propagar, se busca la sesion por fecha.
    """
    dia = _texto(fecha)[:10]
    if not dia:
        return None
    filas = cn.execute("SELECT a.id, a.distancia_m FROM actividad a"
                       " WHERE a.disciplina = 'natacion' AND substr(a.inicio_local, 1, 10) = ?"
                       " ORDER BY a.id", (dia,)).fetchall()
    if not filas:
        return None
    if len(filas) == 1 or not metros:
        return int(filas[0]["id"])
    return int(min(filas, key=lambda f: abs(float(f["distancia_m"] or 0) - float(metros)))["id"])


def _hora(txt) -> float | None:
    """La hora de un lap (`inicio`) en segundos desde su epoch, para poder restar dos."""
    texto = str(txt or "").strip()
    if not texto:
        return None
    try:
        import datetime as _dt
        return _dt.datetime.fromisoformat(texto.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _redondear_cada(seg: float | None, paso: float = 5.0) -> float | None:
    """El cada redondeado a los 5 s mas cercanos.

    En la piscina el cada se canta en numeros redondos ("4x100 cada 1:50", "3x400 cada 6:30") y la salida nunca
    es exacta al segundo, asi que un cada de 109,2 s es 1:50 y no 1:49,2. Lo pide el atleta.
    """
    if seg is None:
        return None
    return float(max(paso, round(float(seg) / paso) * paso))


def _cada_de_grupo(laps: list[dict], idxs: list) -> float | None:
    """El intervalo de salida de un grupo (el `cada`): del inicio de una repeticion al inicio de la siguiente.

    Es lo que el atleta canta en la piscina ("8x100 cada 2:00", "3x400 cada 6:30") y se lee de un vistazo mejor
    que el descanso. Se mide sobre los intervalos del reloj del grupo, sumando el tiempo de cada repeticion y lo
    que se descansa hasta la siguiente (los intervalos de descanso que caen en medio, que no son del grupo).
    No se usa la agrupacion que propone el reloj: el atleta puede juntar en una serie dos bloques que el reloj
    vio sueltos (descanso largo entre ellos), y el `cada` tiene que salir igual.
    """
    indice = {int(l["lap_idx"]): l for l in laps if l.get("lap_idx") is not None}
    orden = []
    for x in idxs:
        n = _numero(x)
        if n is None:                                  # hueco de una repeticion apuntada a mano: no es un largo
            continue
        n = int(n)
        if n in indice:
            orden.append(n)
    salidas = []
    for a, b in zip(orden, orden[1:]):
        # Lo que de verdad pasa en la piscina: del inicio de una repeticion al inicio de la siguiente, con las
        # horas del reloj. Asi el cada cuenta el descanso aunque el reloj no lo apunte como intervalo suelto.
        ta, tb = _hora(indice[a].get("inicio")), _hora(indice[b].get("inicio"))
        if ta is not None and tb is not None and tb > ta:
            salidas.append(tb - ta)
            continue
        en_medio = sum(float(l.get("timer_s") or 0) for i, l in indice.items() if a < i < b)
        salidas.append(float(indice[a].get("timer_s") or 0) + en_medio)
    return _redondear_cada(st.median(salidas)) if salidas else None


def _rellenar_cada(cn: sqlite3.Connection, actividad_id: int, series: list[dict]) -> int:
    """Pone el `cada` (intervalo de salida) a los grupos de un parte ya guardado.

    Un parte importado cuando el `cada` aun no existia lo tiene vacio: se recalcula de los intervalos de su
    grupo, que si estan en la base (`parte_serie.laps`).
    """
    laps = _laps_de(cn, actividad_id)
    if not laps:
        return 0
    puestos = 0
    for s in series:
        idxs = s.get("laps") or []
        if isinstance(idxs, str):                      # `partes_de` ya lo deserializa; un parte a mano puede no
            idxs = json.loads(idxs or "[]")
        if not idxs:
            continue
        # Al grupo que ya trae su `cada` no se le toca: puede ser el que escribio el atleta (que manda) o el que
        # dedujo el algoritmo en su dia. Aqui solo se rellenan los que estan vacios (partes importados antes de
        # que el `cada` existiera).
        if _numero(s.get("cada_s")):
            continue
        cada = _cada_de_grupo(laps, idxs)
        if cada is not None:
            cn.execute("UPDATE parte_serie SET cada_s = ? WHERE id = ?", (cada, s["id"]))
            puestos += 1
    return puestos


def reaplicar(cn: sqlite3.Connection, limite: int = 200) -> dict:
    """Vuelve a llevar a los laps el material y los tiempos de los partes que ya estan guardados.

    Hace falta porque un parte puede haberse importado **antes** de que existiera la propagacion (o sin
    `actividad_id`): los grupos constan en `parte_serie` pero los laps siguen `sin_etiquetar`, y asi la
    analitica no puede saber que ese 1.000 fue con aletas. Reimportar el parte no siempre es posible (el
    fichero del portal ya no esta), asi que se reaplica desde lo que hay en la base.
    """
    partes = partes_de(cn, limite)
    aplicados, sin_sesion, cadas = 0, 0, 0
    for p in partes:
        actividad_id = p.get("actividad_id") or _actividad_de_fecha(cn, p.get("fecha"), p.get("metros"))
        if not actividad_id:
            sin_sesion += 1
            continue
        if not p.get("actividad_id"):
            cn.execute("UPDATE parte SET actividad_id = ? WHERE id = ?", (actividad_id, p["id"]))
        _propagar_material(cn, actividad_id, p["series"])
        _propagar_tiempos(cn, actividad_id, p["series"], p["id"])
        cadas += _rellenar_cada(cn, actividad_id, p["series"])
        aplicados += 1
    cn.commit()
    return {"partes": len(partes), "aplicados": aplicados, "sin_sesion": sin_sesion, "cada": cadas}


def resumen(cn: sqlite3.Connection) -> dict:
    """Cuatro numeros para el cuadro de mando."""
    uno = lambda sql: cn.execute(sql).fetchone()[0]          # noqa: E731
    con_material = uno("SELECT COUNT(*) FROM parte_serie WHERE material <> '' AND material IS NOT NULL")
    return {
        "partes": uno("SELECT COUNT(*) FROM parte"),
        "grupos": uno("SELECT COUNT(*) FROM parte_serie"),
        "con_material": con_material,
        "ultimo": (uno("SELECT MAX(fecha) FROM parte") or None),
        "nota": ("El parte es lo unico que sabe el material y la intensidad: el reloj no los registra. "
                 "Lo que lleve material sale de las comparaciones de brazo libre."),
    }


def _grupos_guardados(cn: sqlite3.Connection, parte_id: int, laps: list[dict]) -> list[dict]:
    """Los grupos de un parte ya subido, en la forma que el portal usa para el desglose de una sesion.

    Se respeta lo que dejo el atleta: el orden de sus repeticiones, sus tiempos, la intensidad de cada una (el
    reloj no la registra) y el material. Lo que el reloj sabe del lap de cada repeticion (brazadas, pulso,
    estilo, SWOLF) se rellena desde sus laps, que no cambian.
    """
    por_lap = {int(x["lap_idx"]): x for x in laps if x.get("lap_idx") is not None}
    fuera = []
    for f in cn.execute("SELECT * FROM parte_serie WHERE parte_id = ? ORDER BY orden, id", (parte_id,)):
        s = dict(f)
        reps = []
        for r in json.loads(s.get("reps") or "[]"):
            if not isinstance(r, dict):
                continue
            fila = {"lap_idx": None, "dist_m": r.get("dist_m"), "tiempo_s": r.get("tiempo_s"), "timer_s": None,
                    "ritmo_100": None, "brazadas": None, "fc_media": None, "estilo": None,
                    "swolf": r.get("swolf"), "revisar": False,
                    "intensidad": r.get("intensidad"), "material_apuntado": r.get("material")}
            lap = por_lap.get(int(_numero(r["lap"]))) if r.get("lap") is not None else None
            if lap:
                fila["lap_idx"] = int(_numero(r["lap"]))
                fila["timer_s"] = lap.get("timer_s")
                fila["brazadas"] = lap.get("brazadas")
                fila["fc_media"] = lap.get("fc_media")
                fila["estilo"] = lap.get("estilo")
                fila["swolf"] = fila["swolf"] or _swolf(lap)
                if fila["dist_m"] is None:
                    fila["dist_m"] = lap.get("dist_m")
                fila["ritmo_100"] = _ritmo(fila["dist_m"], fila["tiempo_s"] or fila["timer_s"])
            reps.append(fila)
        fuera.append({
            "orden": s.get("orden"), "tipo": s.get("tipo"), "rep_m": s.get("rep_m"), "n_reps": s.get("n_reps"),
            "metros": s.get("metros"), "tiempo_s": s.get("tiempo_s"), "ritmo_100": s.get("ritmo_100"),
            "descanso_s": s.get("descanso_s"), "cada_s": s.get("cada_s"), "estilo": s.get("estilo"),
            "intensidad": s.get("intensidad"),
            "material": [m for m in (s.get("material") or "").split(",") if m],
            "nota": s.get("nota") or "", "avisos": [], "reps": reps,
            # La prueba de medicion que marco el atleta en este bloque (vacia si no lo es).
            "prueba": s.get("prueba"),
            "laps": [int(_numero(x)) for x in json.loads(s.get("laps") or "[]") if _numero(x) is not None],
        })
    return fuera


def sesiones_con_parte(cn: sqlite3.Connection, limite: int = 12) -> list[dict]:
    """Las sesiones que ya tienen parte, con la forma de una sesion del portal y su desglose dentro.

    El portal abre una sesion con `pintarSesion`: la cabecera, los grupos y, dentro de cada grupo, cada
    repeticion. Eso tiene que valer igual para una sesion que ya tiene parte; si no, al constar el parte el
    atleta deja de ver el desglose que acaba de ordenar y solo le queda la cabecera. Se leen de la base sus
    grupos tal y como los dejo, y el reloj solo aporta lo suyo lap a lap (brazadas, pulso, SWOLF).
    """
    filas = cn.execute(
        """SELECT a.id, a.id_garmin, a.inicio_local, a.nombre, a.distancia_m, s.largo_piscina_m,
                  s.sensacion, s.rpe, s.fc_media, p.id AS parte_id, p.notas, p.compania, p.metros AS metros_parte
           FROM parte p JOIN actividad a ON a.id = p.actividad_id
           LEFT JOIN natacion_sesion s ON s.actividad_id = a.id
           ORDER BY a.inicio_local DESC LIMIT ?""", (limite,)).fetchall()
    salida = []
    for f in filas:
        laps = _laps_de(cn, f["id"])
        activos = [x for x in laps if not x["es_descanso"] and (x["dist_m"] or 0) > 0]
        salida.append({
            "actividad_id": f["id"], "id_garmin": f["id_garmin"], "fecha": (f["inicio_local"] or "")[:10],
            "hora": (f["inicio_local"] or "")[11:16], "nombre": f["nombre"], "piscina_m": f["largo_piscina_m"],
            # Los metros que manda son los del parte (lo que el atleta dio por nadado): el reloj pierde las
            # repeticiones que se apuntan a mano, y su total no es el del entrenamiento.
            "metros": round(f["metros_parte"] or f["distancia_m"] or 0, 1), "n_intervalos": len(activos),
            "sensacion": f["sensacion"], "rpe": f["rpe"], "fc_media": f["fc_media"],
            "notas": f["notas"], "compania": f["compania"],
            "grupos": correcciones.aplicar(cn, f["id"], laps,
                                          parciales.pasos_de(cn, f["id"], _grupos_guardados(cn, f["parte_id"], laps))),
            "ya_importado": True,
        })
    return salida


def datos_panel(cn: sqlite3.Connection, limite: int = 3) -> dict:
    """Todo lo del parte para el portal: lo que falta por rellenar, lo que ya consta y los cortes."""
    from . import evaluacion
    pendientes = sesiones_sin_parte(cn, 25)
    ya = partes_de(cn, 12)
    # Las que ya tienen parte, con su desglose: el portal las abre igual que una sin rellenar.
    con_parte = sesiones_con_parte(cn, 12)
    ids = [s.get("actividad_id") for s in pendientes] + [p.get("actividad_id") for p in ya]
    return {
        "pendientes": pendientes,
        "partes": ya,
        "con_parte": con_parte,
        "cortes": cortes_intensidad(cn),
        # Las pruebas de medicion: los nombres que se le ofrecen en el portal y las que ya tiene marcadas, con su
        # historial para poder comparar como va el entrenamiento respecto a otras epocas.
        "pruebas": pruebas.catalogo(cn),
        "pruebas_historial": pruebas.historico(cn),
        # Los tres mejores de cada prueba, para la pagina resumen.
        "pruebas_resumen": pruebas.resumen(cn),
        "materiales": list(MATERIALES),
        "nombre_material": dict(NOMBRE_MATERIAL),
        "intensidades": [{"valor": k, "nombre": v} for k, v in ETIQUETA_INTENSIDAD.items()],
        "estilos": [{"valor": k, "nombre": v} for k, v in ETIQUETA_ESTILO.items()],
        # Las formas que puede tener un bloque (regular, progresiva, aflojando...). No se eligen: se miden de
        # los tiempos de sus repeticiones. Se mandan al portal para poder nombrarlas.
        "conceptos": [{"valor": k, "nombre": v} for k, v in concepto.NOMBRE.items()],
        # Lo que el sistema ha aprendido de sus partes (el margen de los tiempos y el descanso que todavia es
        # "la misma serie"), para poder enseñarlo.
        "aprendizaje": aprendizaje.resumen(),
        "companias": [{"valor": k, "nombre": v} for k, v in ETIQUETA_COMPANIA.items()],
        "swolf": {"min": SWOLF_MIN, "max": SWOLF_MAX},
        # La valoracion del sistema de cada entrenamiento, para enseñarla al abrir su parte.
        "valoraciones": evaluacion.valoraciones_de(cn, ids),
        "resumen": resumen(cn),
        "ruta": ruta_por_defecto(),
    }


# ------------------------------------------------------------------ guardar el parte (importar)


def ruta_por_defecto() -> str:
    return os.path.join(os.path.expanduser("~"), "Downloads", NOMBRE_FICHERO)


def _texto(v) -> str:
    return "" if v is None else str(v).strip()


def _numero(v) -> float | None:
    t = _texto(v).replace(",", ".")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _material_texto(v) -> str:
    """El material, venga como lista (del portal) o como texto (ya guardado). `brazo_libre` no se guarda."""
    if isinstance(v, (list, tuple, set)):
        return ",".join(_texto(m) for m in v if _texto(m) and _texto(m) != "brazo_libre")
    return _texto(v)


def _tiempo_s(v) -> float | None:
    """Segundos a partir de como lo escribe el atleta: `5:55`, `5,55`, `355`, `5:55,5` o `1:05:30`.

    Es el unico dato que el atleta puede corregirle al reloj: cuando el cronometro mide mal (o el reloj no
    registra la repeticion), lo que vale es lo que apunte el, igual que con el material.
    """
    if isinstance(v, (int, float)):
        s = float(v)
        return round(s, 1) if s > 0 else None
    t = _texto(v).replace(",", ".")
    if not t:
        return None
    partes = t.split(":")
    try:
        if len(partes) == 1:
            s = float(partes[0])
        elif len(partes) == 2:
            s = 60 * float(partes[0]) + float(partes[1])
        elif len(partes) == 3:
            s = 3600 * float(partes[0]) + 60 * float(partes[1]) + float(partes[2])
        else:
            return None
    except ValueError:
        return None
    return round(s, 1) if s > 0 else None


def _reps_del_grupo(g: dict) -> list[dict]:
    """Lo que el atleta cambio repeticion a repeticion: la distancia, el tiempo, la intensidad suelta, el
    material y el SWOLF que ha medido.

    El ritmo no se guarda (sale de la distancia y el tiempo). La distancia si: el reloj la saca del largo de la
    piscina y de las vueltas que ve, y con una vuelta contada de mas o de menos el numero que vale es el suyo.
    """
    salida = []
    for r in g.get("reps") or []:
        if not isinstance(r, dict):
            continue
        fila = {}
        if r.get("lap") is not None:
            fila["lap"] = int(_numero(r.get("lap")) or 0)
        material = _material_texto(r.get("material"))
        if material:
            fila["material"] = material
        intensidad = _intensidad(r.get("intensidad"))
        if intensidad:
            fila["intensidad"] = intensidad
        swolf = _numero(r.get("swolf"))
        if swolf is not None and SWOLF_MIN <= swolf <= SWOLF_MAX:
            fila["swolf"] = swolf
        # La distancia de esa repeticion, si la corrigio (una vuelta de mas o de menos, o un 50 dentro de un 100).
        dist = _numero(r.get("dist_m"))
        if dist is not None and dist > 0:
            fila["dist_m"] = dist
        # El descanso que va detras de esa repeticion: sin el, el cada del bloque no se puede rehacer en el
        # portal cuando el atleta parte o junta grupos a mano.
        descanso = _numero(r.get("descanso_s"))
        if descanso is not None and descanso > 0:
            fila["descanso_s"] = descanso
        # El tiempo que el atleta le corrige al reloj (lo escribe como 5:55 y aqui se guarda en segundos).
        tiempo = _tiempo_s(r.get("tiempo_s") if r.get("tiempo_s") is not None else r.get("tiempo_apuntado"))
        if tiempo is not None:
            fila["tiempo_s"] = tiempo
        # Solo el indice del lap no dice nada: se guarda lo que el atleta eligio. Una repeticion SIN lap (una
        # serie que se añade a mano, que el reloj no vio) se guarda con solo su tiempo: eso ya es un dato suyo.
        if len(fila) > (1 if "lap" in fila else 0):
            salida.append(fila)
    return salida


def clave_parte(p: dict) -> str:
    """Huella del parte: fecha, sesion y grupos. Reimportar lo mismo no duplica; corregirlo lo actualiza."""
    grupos = p.get("series") or p.get("grupos") or []
    limpio = [{"rep_m": g.get("rep_m"), "n_reps": g.get("n_reps"), "metros": g.get("metros"),
               "material": g.get("material"), "intensidad": g.get("intensidad"),
               # Lo que puede cambiar repeticion a repeticion (el swolf medido, la intensidad suelta, el material
               # o el tiempo que el atleta le corrige al reloj) tambien cuenta: si no, esa correccion no
               # actualizaria el parte ya importado y quedaria un parte viejo con otro nuevo al lado.
               "reps": [{"lap": r.get("lap"), "intensidad": r.get("intensidad"), "swolf": r.get("swolf"),
                         "tiempo_s": r.get("tiempo_s"), "material": r.get("material")}
                        for r in (g.get("reps") or []) if isinstance(r, dict)],
               "nota": g.get("nota")} for g in grupos
              if isinstance(g, dict)]
    return "|".join([_texto(p.get("fecha")), _texto(p.get("actividad_id")), _texto(p.get("metros")),
                     json.dumps(limpio, ensure_ascii=False, sort_keys=True)])


def _laps_del_grupo(g: dict) -> list[int]:
    """Los largos del reloj que el parte mete en un grupo, sin los huecos.

    El portal puede dejar un `null` entre los largos: es una repeticion que el atleta apunto a mano, sin
    largo del reloj detras. No es un largo, asi que no cuenta ni se puede convertir a numero.
    """
    salida = []
    for x in g.get("laps") or []:
        n = _numero(x)
        if n is None:
            continue
        salida.append(int(n))
    return salida


def _propagar_tiempos(cn: sqlite3.Connection, actividad_id: int | None, grupos: list[dict],
                      parte_id: int | None = None) -> int:
    """Lleva al reloj los tiempos que el atleta corrige repeticion a repeticion.

    Es el unico dato con el que el parte corrige al reloj, y es legitimo: el cronometro del reloj mide de
    pared a pared (o mide mal) y el atleta cronometra su serie. Lo que vale es lo suyo. Se escribe en el
    lap, se rehacen las series desde los laps ya corregidos y el grupo del parte se recalcula (tiempo y
    ritmo) con eso, para que el portal no enseñe un ritmo viejo al lado de un tiempo corregido.
    """
    if not actividad_id:
        return 0
    corregidos: dict[int, float] = {}
    for g in grupos:
        # Solo las repeticiones con largo del reloj: una apuntada a mano (sin `lap`) no corrige ningun lap, y
        # darla por el largo 0 le pisaria el primer largo de la sesion al atleta.
        por_lap = {}
        for r in (g.get("reps") or []):
            if not isinstance(r, dict) or r.get("lap") is None:
                continue
            segundos = _tiempo_s(r.get("tiempo_s") if r.get("tiempo_s") is not None
                                 else r.get("tiempo_apuntado"))
            if segundos:
                por_lap[int(_numero(r.get("lap")))] = segundos
        for lap_idx in _laps_del_grupo(g):
            suyo = por_lap.get(lap_idx)
            if suyo:
                corregidos[lap_idx] = suyo
    for lap_idx, segundos in corregidos.items():
        cn.execute("UPDATE natacion_lap SET timer_s = ? WHERE actividad_id = ? AND lap_idx = ?",
                   (segundos, actividad_id, lap_idx))
    if not corregidos:
        return 0
    # Las series se rehacen desde los laps corregidos: asi el ritmo de las comparables tambien es el del atleta.
    from . import importar as _importar
    _importar.recalcular_series_de(cn, actividad_id)
    if parte_id:
        for i, g in enumerate(grupos):
            laps = _laps_del_grupo(g)
            metros = _numero(g.get("metros"))
            # El tiempo del grupo lo manda el atleta: si apunto el tiempo de sus repeticiones y entre ellas
            # cubre la distancia del grupo (aunque alguna no tenga largo del reloj detras), vale la suma de
            # las suyas. Si no, la suma de los largos del reloj; y si no cuadra, se deja lo que ya hubiera.
            suyos = []
            for r in (g.get("reps") or []):
                if not isinstance(r, dict):
                    continue
                segundos = _tiempo_s(r.get("tiempo_s") if r.get("tiempo_s") is not None
                                     else r.get("tiempo_apuntado"))
                if segundos:
                    suyos.append((_numero(r.get("dist_m")) or 0.0, segundos))
            if suyos and metros and abs(sum(d for d, _ in suyos) - metros) <= 1.0:
                total = sum(t for _, t in suyos)
            else:
                tiempos = [float(f["timer_s"]) for f in
                           (cn.execute("SELECT timer_s FROM natacion_lap WHERE actividad_id = ? AND lap_idx = ?",
                                       (actividad_id, lap)).fetchone() for lap in laps)
                           if f and f["timer_s"]]
                total = sum(tiempos) if laps and len(tiempos) == len(laps) else None
            if total and metros:
                cn.execute("UPDATE parte_serie SET tiempo_s = ?, ritmo_100 = ? WHERE parte_id = ? AND orden = ?",
                           (round(total, 1), _ritmo(metros, total), parte_id, i))
    return len(corregidos)


def _propagar_material(cn: sqlite3.Connection, actividad_id: int | None, grupos: list[dict]) -> int:
    """Lleva el material del parte a los laps y a las series de esa sesion.

    El parte **manda**: primero se limpia lo que hubiera y despues se pone lo que diga el parte, asi que
    quitar un material tambien se aplica. Es lo que hace que lo nadado con palas o aletas deje de contar
    como marca de brazo libre en la analitica.
    """
    if not actividad_id:
        return 0
    cn.execute("UPDATE natacion_lap SET material = 'sin_etiquetar' WHERE actividad_id = ?", (actividad_id,))
    tocados = 0
    for g in grupos:
        material = _material_texto(g.get("material"))
        laps = _laps_del_grupo(g)
        # Una repeticion puede llevar material distinto del grupo (unas palas y otras no): manda la suya. Solo
        # cuenta en repeticiones con largo del reloj: una apuntada a mano no puede ser el largo 0.
        por_lap = {}
        for r in (g.get("reps") or []):
            if not isinstance(r, dict) or r.get("lap") is None:
                continue
            suyo = _material_texto(r.get("material"))
            if suyo:
                por_lap[int(_numero(r.get("lap")))] = suyo
        if not material and not por_lap:
            continue
        tocados_lap = 0
        for lap_idx in laps:
            suyo = por_lap.get(lap_idx) or material
            if not suyo:
                continue
            cn.execute("UPDATE natacion_lap SET material = ? WHERE actividad_id = ? AND lap_idx = ?",
                       (suyo, actividad_id, int(lap_idx)))
            tocados_lap += 1
        tocados += tocados_lap
    # Las series se rehacen con los laps ya etiquetados: heredan el material y dejan de ser comparables
    # (es la misma puerta que usa `etiquetar`, asi que no hay dos verdades distintas sobre el material).
    from . import importar as _importar
    _importar.recalcular_series_de(cn, actividad_id)
    return tocados


def partes_de_datos(datos) -> list[dict]:
    """Saca la lista de partes de lo que manda el portal: el fichero entero o la lista suelta."""
    if isinstance(datos, list):
        return [p for p in datos if isinstance(p, dict)]
    if isinstance(datos, dict):
        partes = datos.get("partes_natacion")
        if partes is None:
            partes = datos.get("partes")
        return [p for p in (partes or []) if isinstance(p, dict)]
    return []


def importar(cn: sqlite3.Connection, ruta: str) -> dict:
    """Mete en la base los partes del fichero del portal (bloque `partes_natacion`). Idempotente por `clave`."""
    if not os.path.isfile(ruta):
        raise FileNotFoundError(
            f"No encuentro {ruta}. En el cuadro de mando (cuadro/panel.html), abre el parte de la sesion "
            f"(Entrenamientos, pinchando la fila) y pulsa \"Subir\".")
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)
    return importar_datos(cn, datos, origen=ruta)


def importar_datos(cn: sqlite3.Connection, datos, origen: str = "portal") -> dict:
    """Igual que `importar` pero con los datos ya en memoria: es lo que usa el servidor del portal (`servir`)."""
    partes = partes_de_datos(datos)
    if not partes:
        raise ValueError("El fichero no trae el bloque 'partes_natacion' (o viene vacio).")

    nuevos = actualizados = 0
    for p in partes:
        if not isinstance(p, dict):
            continue
        grupos = [g for g in (p.get("series") or p.get("grupos") or []) if isinstance(g, dict)]
        if not grupos and not _texto(p.get("notas")):
            continue
        grupos = [g for g in grupos if g.get("no_cuenta") is not True]
        compania = _compania(p.get("compania"))
        # Sin `actividad_id` (ficheros viejos, partes escritos a mano) se busca la sesion por fecha: si no, el
        # material y los tiempos se quedan sin propagar a los laps y la analitica no los ve.
        actividad_id = p.get("actividad_id") or _actividad_de_fecha(cn, p.get("fecha"), p.get("metros"))
        clave = clave_parte(dict(p, actividad_id=actividad_id, series=grupos, grupos=grupos))
        fila = cn.execute("SELECT id FROM parte WHERE clave = ?", (clave,)).fetchone()
        if fila:
            actualizados += 1
            parte_id = fila["id"]
            cn.execute("DELETE FROM parte_serie WHERE parte_id = ?", (parte_id,))
            cn.execute("""UPDATE parte SET fecha=?, actividad_id=?, piscina_m=?, metros=?, minutos=?,
                                             sensacion=?, notas=?, compania=?, importado_en=? WHERE id=?""",
                       (_texto(p.get("fecha"))[:10], actividad_id, _numero(p.get("piscina_m")),
                        _numero(p.get("metros")), _numero(p.get("minutos")), _numero(p.get("sensacion")),
                        _texto(p.get("notas")), compania, db.ahora(), parte_id))
        else:
            nuevos += 1
            cur = cn.execute("""INSERT INTO parte (clave, fecha, actividad_id, piscina_m, metros, minutos,
                                                   sensacion, notas, compania, fuente, importado_en)
                                VALUES (?,?,?,?,?,?,?,?,?,'portal',?)""",
                             (clave, _texto(p.get("fecha"))[:10], actividad_id,
                              _numero(p.get("piscina_m")), _numero(p.get("metros")), _numero(p.get("minutos")),
                              _numero(p.get("sensacion")), _texto(p.get("notas")), compania, db.ahora()))
            parte_id = cur.lastrowid
        laps_del_reloj = _laps_de(cn, actividad_id) if actividad_id else []
        for i, g in enumerate(grupos):
            material = _material_texto(g.get("material"))
            laps = _laps_del_grupo(g)
            # El `cada` (intervalo de salida) se mide sobre los intervalos del reloj del grupo: asi sale bien
            # aunque el atleta reagrupe (el reloj puede haber visto sueltos dos bloques de la misma serie).
            # El "cada" (salida) lo dice el atleta: el reloj no lo registra. Si viene en el parte, manda el
            # suyo; si no, se deduce de los intervalos que vio el reloj.
            cada = _numero(g.get("cada_s")) or (_cada_de_grupo(laps_del_reloj, laps) if laps else None)
            cn.execute("""INSERT INTO parte_serie (parte_id, orden, tipo, rep_m, n_reps, metros, tiempo_s,
                                                   ritmo_100, descanso_s, cada_s, estilo, material, intensidad, nota,
                                                   prueba, laps, reps)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (parte_id, i, _texto(g.get("tipo")) or "serie", _numero(g.get("rep_m")),
                        int(_numero(g.get("n_reps")) or len(laps) or 0), _numero(g.get("metros")),
                        _numero(g.get("tiempo_s")), _numero(g.get("ritmo_100")), _numero(g.get("descanso_s")),
                        cada,
                        _estilo_del_grupo(g.get("estilo")), material, _intensidad(g.get("intensidad")),
                        _texto(g.get("nota")), _prueba(g.get("prueba")),
                        json.dumps(_laps_del_grupo(g), ensure_ascii=False),
                        json.dumps(_reps_del_grupo(g), ensure_ascii=False) or None))
        _propagar_material(cn, actividad_id, grupos)
        # Y los tiempos que el atleta le corrige al reloj: van al lap, rehacen las series y el grupo.
        _propagar_tiempos(cn, actividad_id, grupos, parte_id)
    cn.execute("INSERT INTO importacion (momento, fuente, ruta, leidos, nuevos, actualizados, omitidos, incidencias)"
               " VALUES (?,?,?,?,?,?,?,?)",
               (db.ahora(), "portal-partes", origen, len(partes), nuevos, actualizados, 0, 0))
    cn.commit()
    return {"leidos": len(partes), "nuevos": nuevos, "actualizados": actualizados}


# ------------------------------------------------------------------ consola


def marcar_prueba(cn: sqlite3.Connection, actividad_id: int, nombre: str, lap_idx: int | None = None,
                  metros: float | None = None, tolerancia_m: float = 60.0) -> dict:
    """Marca un bloque ya hecho como prueba de medicion, sin tener que rellenar el parte a mano.

    Es para las pruebas que el atleta hizo antes de que existiera la marca (su tiron de 30 minutos de 2023, un 1.500
    suelto): se elige el bloque del reloj (por su `lap_idx` o por los metros del tiron), el resto del parte va como
    lo propone el motor y lo unico que pone el atleta es el **nombre** de la prueba. Nada se deduce de los datos: el
    nombre es suyo. Devuelve el bloque marcado.
    """
    limpio = pruebas.limpiar(nombre)
    if not limpio:
        raise ValueError("Sin nombre no hay prueba de medicion.")
    laps = _laps_de(cn, actividad_id)
    activos = [x for x in laps if not x["es_descanso"] and (x["dist_m"] or 0) > 0]
    if not activos:
        raise ValueError(f"La sesion {actividad_id} no trae intervalos de natacion.")
    if lap_idx is not None:
        candidatos = [x for x in activos if int(x["lap_idx"]) == int(lap_idx)]
    elif metros is not None:
        candidatos = [x for x in activos if abs(float(x["dist_m"] or 0) - float(metros)) <= tolerancia_m]
    else:
        raise ValueError("Dime el bloque: el lap del tiron (`--lap`) o sus metros (`--metros`).")
    if not candidatos:
        raise ValueError(
            f"No encuentro ese bloque en la sesion {actividad_id}. Los que trae el reloj: "
            + ", ".join(f"lap {x['lap_idx']} ({int(x['dist_m'] or 0)} m)" for x in activos))
    elegido = max(candidatos, key=lambda x: x["dist_m"] or 0)

    # Si esa sesion ya tiene parte, la marca se pone en su bloque, como haria el atleta en el portal: no se crea otro
    # parte ni se le pisa la estructura que el ya tenia.
    for en_su_parte in cn.execute("""SELECT s.id, s.laps, s.metros, s.tiempo_s FROM parte_serie s
                                       JOIN parte p ON p.id = s.parte_id
                                      WHERE p.actividad_id = ? ORDER BY s.orden""", (actividad_id,)):
        if int(elegido["lap_idx"]) not in [int(i) for i in _laps_del_grupo({"laps": en_su_parte["laps"]})]:
            continue
        cn.execute("UPDATE parte_serie SET prueba = ? WHERE id = ?", (limpio, en_su_parte["id"]))
        return {"actividad_id": actividad_id, "prueba": limpio, "lap": int(elegido["lap_idx"]),
                "metros_del_bloque": round(float(en_su_parte["metros"] or 0), 1),
                "tiempo_s": en_su_parte["tiempo_s"],
                "ritmo_100": (round(float(en_su_parte["tiempo_s"]) * 100.0 / float(en_su_parte["metros"]), 1)
                              if en_su_parte["tiempo_s"] and en_su_parte["metros"] else None),
                "en_su_parte": True, "nuevos": 0, "actualizados": 1}

    grupos = correcciones.aplicar(cn, actividad_id, laps,
                                 parciales.pasos_de(cn, actividad_id,
                                                    proponer_grupos(laps, cortes_intensidad(cn))))
    suyos = [g for g in grupos if int(elegido["lap_idx"]) in [int(i) for i in (g.get("laps") or [])]]
    if not suyos:
        raise ValueError("El bloque elegido no esta en la propuesta del parte de esa sesion.")
    grupo = max(suyos, key=lambda g: g.get("metros") or 0)
    grupo["prueba"] = limpio
    # `reps` va vacio a proposito: ahi solo se guarda lo que el atleta cambia repeticion a repeticion, y va con el
    # lap (no con el `lap_idx` del motor). Vacio = el bloque entero sale del reloj, como en los partes suyos.
    for g in grupos:
        g["reps"] = []

    fila = cn.execute("""SELECT a.inicio_local, a.duracion_s, s.largo_piscina_m, s.sensacion
                           FROM actividad a LEFT JOIN natacion_sesion s ON s.actividad_id = a.id
                          WHERE a.id = ?""", (actividad_id,)).fetchone()
    if fila is None:
        raise ValueError(f"No encuentro la sesion {actividad_id}.")
    datos = {"partes_natacion": [{
        "fecha": (fila["inicio_local"] or "")[:10], "actividad_id": actividad_id,
        "piscina_m": fila["largo_piscina_m"], "metros": round(sum(x["dist_m"] for x in activos), 1),
        "minutos": round(float(fila["duracion_s"] or 0) / 60.0, 1), "sensacion": fila["sensacion"],
        "notas": f"bloque marcado como prueba de medicion ({limpio}); el resto del parte es la propuesta del motor",
        "compania": "solo", "series": grupos}]}
    res = importar_datos(cn, datos, origen=f"prueba {limpio}")
    return {"actividad_id": actividad_id, "prueba": limpio, "lap": int(elegido["lap_idx"]),
            "metros_del_bloque": round(float(grupo.get("metros") or 0), 1),
            "tiempo_s": grupo.get("tiempo_s"), "ritmo_100": grupo.get("ritmo_100"), **res}


def mostrar(cn: sqlite3.Connection) -> None:
    r = resumen(cn)
    if not r["partes"]:
        print("Todavia no hay ningun parte en la base.")
        print("Se rellena en el cuadro de mando (cuadro/panel.html), en Entrenamientos: se pincha la sesion,")
        print("se marca el material y la intensidad, y se le da a \"Subir\" (con el servidor abierto:")
        print("doble clic en servir-entrenador.bat). A mano tambien vale `partes --importar`.")
        return
    print(f"Partes en la base: {r['partes']} ({r['grupos']} grupos, {r['con_material']} con material), "
          f"el ultimo el {r['ultimo']}")
    for p in partes_de(cn, 6):
        print(f"\n  {p['fecha']}  {p.get('metros') or '?'} m  "
              f"({p.get('piscina_m') or '?'} m, sensacion {p.get('sensacion') if p.get('sensacion') else '-'})")
        for s in p["series"]:
            mat = ", ".join(s["material"]) or "brazo libre"
            rit = f"{s['ritmo_100']:.1f} s/100" if s.get("ritmo_100") else "-"
            reps = f"{s['n_reps']}x{s['rep_m']:.0f} m" if s.get("tipo") == "serie" else f"{s['metros']:.0f} m seguidos"
            print(f"    {reps:<18}{rit:>12}  {ETIQUETA_INTENSIDAD.get(s.get('intensidad') or '', s.get('intensidad') or 'sin marcar'):<24}{mat}")
        if p.get("notas"):
            print(f"    notas: {p['notas'][:70]}")


def mostrar_pendientes(cn: sqlite3.Connection, limite: int = 3) -> None:
    """Las sesiones del reloj que no tienen parte, con la agrupacion propuesta (para verla por consola)."""
    sesiones = sesiones_sin_parte(cn, limite)
    if not sesiones:
        print("Todas las sesiones recientes de piscina tienen parte.")
        return
    for s in sesiones:
        print(f"\n=== {s['fecha']} {s['hora']}  {s['metros']:.0f} m en {s['n_intervalos']} intervalos "
              f"({s['piscina_m']:g} m) -> {len(s['grupos'])} grupos propuestos ===")
        print(f"  {'grupo':<26}{'ritmo':>11}{'descanso':>10}  intensidad sugerida")
        for g in s["grupos"]:
            reps = f"{g['n_reps']}x{g['rep_m']:.0f} m" if g["tipo"] == "serie" else f"{g['metros']:.0f} m seguidos"
            rit = f"{g['ritmo_100']:.1f}" if g.get("ritmo_100") else "-"
            desc = f"{g['descanso_s']:.0f} s" if g.get("descanso_s") else "-"
            sug = ETIQUETA_INTENSIDAD.get(g.get("intensidad_sugerida") or "", "sin historico")
            print(f"  {reps:<26}{rit:>11}{desc:>10}  {sug}")
            for a in g["avisos"]:
                print(f"      ! {a}")
        print("  (esto es una propuesta: en el portal se parte, se une, se marca material e intensidad)")
