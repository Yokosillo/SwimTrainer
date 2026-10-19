"""La valoracion del entrenador: el discurso cualitativo que sale en el Resumen del portal.

Se compone aqui, en cada pasada de `analizar`, con los numeros que ya estan en la base (volumen, bloques
medidos, partes y la evaluacion contra el plan): **nada se escribe a mano ni se rellena a ojo**. Si un dato no
se puede sostener (no hay test, no hay parte, no hay ningun bloque de esa distancia), se dice que falta en vez
de inventarlo, y la valoracion cambia sola cuando cambian los datos.

El guion es el de un entrenador de verdad: donde estamos, como va la progresion (los ultimos dias y semanas, y
contra hace un mes), que queda en la semana, como va el ciclo, que se puede esperar, y con que tiempos hay que
entrenar para el reto.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta

from . import fuerza, partes, plan
from .partes import ETIQUETA_INTENSIDAD

# Ventanas de comparacion. La primera es "esta semana"; la segunda, "hace un mes" en dos tramos de 30 dias.
DIAS_SEMANA = 7
DIAS_MES = 30

# Cuanto se mira atras para saber lo que traen los dias del entrenador (6 semanas). Se usa la mediana y no la
# media: un dia de travesia larga no puede decidir el volumen de la semana propia (V1.2-02).
DIAS_FIJOS = 42


def _mmss(segundos: float | None) -> str:
    """Un tiempo en minutos:segundos, como se lee un crono (5:11, 13:05)."""
    if not segundos:
        return "—"
    s = int(round(segundos))
    return f"{s // 60}:{s % 60:02d}"


def _ritmo(s100: float | None) -> str:
    """Un ritmo por 100 en minutos:segundos con decimal (1:14,1), como en el resto del portal."""
    if not s100:
        return "—"
    total = round(float(s100) * 10) / 10.0
    minutos = int(total // 60)
    return f"{minutos}:{total - minutos * 60:04.1f}".replace(".", ",")


def _km(metros: float) -> str:
    return f"{metros / 1000:.1f} km".replace(".", ",")


def _millar(metros: float) -> str:
    """Los metros con el punto de millar de aqui: 3.600 m."""
    return f"{int(round(float(metros or 0))):,}".replace(",", ".")


def _fecha_corta(iso: str) -> str:
    """26/05, con el ano cuando no es el de este ano (una marca de 2022 no se lee igual que la del martes)."""
    d = plan._fecha(iso)  # noqa: SLF001
    if d.year != date.today().year:
        return f"{d.day:02d}/{d.month:02d}/{d.year}"
    return f"{d.day}/{d.month}"


def _agua(cn: sqlite3.Connection, desde: date, hasta: date) -> dict:
    """Los dias en el agua y los metros de un tramo: lo del reloj y lo apuntado a mano (sin reloj).

    Cuenta dias (no sesiones): dos entrenos el mismo dia son un dia en el agua.
    """
    dias: dict[str, float] = {}
    for fila in cn.execute(
        """SELECT substr(a.inicio_local, 1, 10) AS f, a.distancia_m AS m FROM actividad a
           JOIN natacion_sesion s ON s.actividad_id = a.id
           WHERE substr(a.inicio_local, 1, 10) BETWEEN ? AND ?""",
        (desde.isoformat(), hasta.isoformat()),
    ):
        dias[fila["f"]] = dias.get(fila["f"], 0.0) + float(fila["m"] or 0)
    for fila in cn.execute(
        """SELECT fecha, distancia_m FROM apunte
           WHERE lower(tipo) = 'natacion' AND fecha BETWEEN ? AND ?""",
        (desde.isoformat(), hasta.isoformat()),
    ):
        if fila["fecha"]:
            dias[fila["fecha"]] = dias.get(fila["fecha"], 0.0) + float(fila["distancia_m"] or 0)
    return {"dias": len(dias), "metros": round(sum(dias.values())), "detalle": dias}


def _mediana(valores: list[float]) -> float:
    """La mediana de una lista (el valor de en medio); con dos, la media de los dos. Vacia, 0."""
    if not valores:
        return 0.0
    v = sorted(valores)
    medio = len(v) // 2
    return float(v[medio]) if len(v) % 2 else (v[medio - 1] + v[medio]) / 2.0


def _fijos_m(cn: sqlite3.Connection, hoy: date, dias: int = DIAS_FIJOS) -> dict[str, float]:
    """Lo que ya traen los dias que no son nuestros: la mediana de lo que el atleta nada de verdad esos dias.

    Los lunes, miercoles y viernes los manda el entrenador y no se les anade nada (regla R6): aqui no se decide
    nada, solo se mide cuanto volumen ponen, para saber cuanto le queda a la semana propia (V1.2-02). Lo que manda
    es lo que el atleta hace (reloj o apunte), no lo que deberia hacer.
    """
    from . import planificador

    detalle = _agua(cn, hoy - timedelta(days=dias), hoy)["detalle"]
    por_dia: dict[str, list[float]] = {}
    for fecha, metros in (detalle or {}).items():
        if not metros:
            continue
        wd = planificador.DIAS[date.fromisoformat(fecha).weekday()]
        if wd not in planificador.DIAS_ENTRENADOR:
            continue                    # los dias propios se proponen aqui; solo se mide lo que ya esta pactado
        por_dia.setdefault(wd, []).append(float(metros))
    return {d: _mediana(v) for d, v in por_dia.items()}


def _km_de_la_semana(cn: sqlite3.Connection, hoy: date) -> float | None:
    """Los km que el plan deja a la semana de hoy, ya recalculados con lo que ha pasado (V1.2-02).

    Si la semana es una de las escritas (S1..S5) manda el plan vivo, que aplica la regla del 10 % sobre lo que
    dejo la anterior. Si ya es de los bloques siguientes, el km del bloque (el de abajo, que es lo menos que
    promete el plan). Si no se sabe, None: la propuesta no se recorta y lo dice.
    """
    from . import plan_vivo

    for s in plan_vivo.datos(cn, hoy).get("semanas") or []:
        if s.get("en_curso") and s.get("km"):
            return float(s["km"])
    for b in plan.BLOQUES:
        if plan._fecha(b["desde"]) <= hoy <= plan._fecha(b["hasta"]):        # noqa: SLF001
            m = re.search(r"(\d+(?:[.,]\d+)?)", str(b.get("km") or ""))       # "12-14" -> 12; "-" -> nada
            return float(m.group(1).replace(",", ".")) if m else None
    return None


def _bloque(bloques: list[dict], dist: float, desde: date, hasta: date,
            estilo: str = "libre", piscina: float = 25.0, libre: bool = True) -> dict | None:
    """El bloque continuo mas rapido de esa distancia (y de fiar) dentro de un tramo.

    Es la medida mas honesta de "como esta el ritmo": un 400 seguido del reloj, no una impresion. Por defecto
    solo mira bloques **a brazo libre**: uno con aletas o palas no dice como esta el atleta, dice como ayuda
    el material (para esos esta `libre=False`, y el discurso los cita aparte, con la ayuda descontada).
    """
    dentro = [b for b in bloques
              if b.get("fiable") and b.get("ritmo_100")
              and (b.get("estilo") or "") == estilo
              and float(b.get("piscina_m") or 0) == piscina
              and (b.get("brazo_libre", True) or not libre)
              and desde.isoformat() <= (b.get("fecha") or "") <= hasta.isoformat()
              and dist * 0.75 <= (b.get("dist_m") or 0) <= dist * 1.25]
    # Esta funcion devuelve el bloque mas rapido, tenga parte o no: quien lo cite tiene que mirar
    # `material_conocido` y decir si el material consta. Filtrar aqui por "con parte" dejaba de referencia un
    # calentamiento de 425 m a 1:46,9 solo porque ese dia habia parte: peor que decir la verdad del otro.
    return min(dentro, key=lambda b: b["ritmo_100"]) if dentro else None


def _bloques_material(bloques: list[dict], desde: date, hasta: date, metros_min: float = 200.0,
                      estilo: str = "libre", piscina: float = 25.0, tope: int = 5) -> list[dict]:
    """Los bloques con material de un tramo, del mas reciente al mas viejo (para nombrarlos, no para comparar)."""
    dentro = [b for b in bloques
              if b.get("fiable") and b.get("ritmo_100") and not b.get("brazo_libre", True)
              and (b.get("estilo") or "") == estilo
              and float(b.get("piscina_m") or 0) == piscina
              and desde.isoformat() <= (b.get("fecha") or "") <= hasta.isoformat()
              and (b.get("dist_m") or 0) >= metros_min]
    return sorted(dentro, key=lambda b: (b.get("fecha") or ""), reverse=True)[:tope]


def _bloque_material(bloques: list[dict], dist: float, desde: date, hasta: date,
                     estilo: str = "libre", piscina: float = 25.0) -> dict | None:
    """El bloque mas rapido de esa distancia entre los que **llevaban material** (aletas, palas, pull).

    Estos no son referencia de nivel: son lo que hay que nombrar y descontar antes de comparar nada.
    """
    dentro = [b for b in bloques
              if b.get("fiable") and b.get("ritmo_100") and not b.get("brazo_libre", True)
              and (b.get("estilo") or "") == estilo
              and float(b.get("piscina_m") or 0) == piscina
              and desde.isoformat() <= (b.get("fecha") or "") <= hasta.isoformat()
              and dist * 0.75 <= (b.get("dist_m") or 0) <= dist * 1.25]
    return min(dentro, key=lambda b: b["ritmo_100"]) if dentro else None


# Cuanto ayuda cada material, en segundos por cada 100 m. No hay dos nadadores iguales y el historico propio casi
# no tiene bloques con material etiquetado (el material se apunta desde el parte del 12/10/2026), asi que esto se
# declara como lo que es: una estimacion de entrenador. Sirve para una cosa concreta y honesta: **no comparar un
# 1.000 con aletas con un 400 a brazo libre como si fueran lo mismo**. El dia que haya bloques propios con y sin
# material a distancias parecidas, se mide en vez de estimarse.
AYUDA_MATERIAL = {"aletas": 10.0, "palas": 6.0, "pull": 4.0, "tabla": 0.0, "snorkel": 0.0, "churro": 0.0}


def _ayuda_material(material: str | None) -> float:
    """Segundos por 100 que regala ese material (el que mas ayude, no la suma: palas y pull van juntos)."""
    if not material:
        return 0.0
    return max((AYUDA_MATERIAL.get(m.strip().lower(), 0.0) for m in str(material).split(",") if m.strip()),
               default=0.0)


def _equiv_libre(ritmo: float | None, material: str | None) -> float | None:
    """El ritmo que le tocaria a brazo libre (estimado: el material ayuda, no significa que nade mejor)."""
    if ritmo is None:
        return None
    return round(float(ritmo) + _ayuda_material(material), 1)


def _bloque_de(hoy: date) -> dict | None:
    """El bloque del plan (de los que van hasta el 3.000) en el que cae una fecha."""
    for b in plan.BLOQUES:
        if plan._fecha(b["desde"]) <= hoy <= plan._fecha(b["hasta"]):  # noqa: SLF001
            return b
    return None


def _semana_del_plan(clave: str | None) -> dict | None:
    for s in plan.SEMANAS:
        if s["clave"] == clave:
            return s
    return None


# La piscina de los dias propios: el atleta la confirmo el 18/10/2026 y vale hasta junio. Los ritmos por 100 de
# las dianas son de vaso corto (25 m). Se dice donde se leen los tiempos, no en una nota aparte: un ritmo de vaso
# corto no se puede comparar con uno de vaso de 50 m (sale mas lento).
PISCINA = "25 m (vaso corto)"


def _dianas(ritmo_objetivo: float, rango: str, que: str) -> list[dict]:
    """Con que tiempos hay que entrenar para el reto.

    El criterio del entrenador es conocido y explicito: en entrenamiento **no se nada al ritmo exacto de la
    prueba** (el dia de la prueba el crono, la salida y la serie empujan). Los bloques de calidad van a 1-2
    s/100 por encima del objetivo, la velocidad del 50 a ritmo de prueba o algo por debajo, y el dia de la
    prueba se busca el rango objetivo del plan.
    """
    r = float(ritmo_objetivo)
    return [
        {"serie": "50 m a tope (velocidad)",
         "diana": f"{_ritmo((r - 0.5) / 2)} - {_ritmo(r / 2)}",
         "porque": "la salida del 400 se defiende con la velocidad del 50: hay que hacerlo a ritmo de prueba "
                   "y con margen, no a tope ahogando"},
        {"serie": "8x100 con salida cada 2:00",
         "diana": f"{_ritmo(r + 1)} - {_ritmo(r + 2)} por 100",
         "porque": "es el bloque que mas se parece al 400: si la ultima repeticion no se cae de la primera, "
                   "el ritmo esta puesto; si se cae mas de 5 s/100, todavia no"},
        {"serie": "4x400 con 45 s",
         "diana": f"{_mmss(4 * (r + 1))} - {_mmss(4 * (r + 2))} cada 400",
         "porque": "a 1-2 s/100 del objetivo: es la diana realista de entrenamiento, no el crono de la prueba"},
        {"serie": "400 seguido (control)",
         "diana": f"{_mmss(4 * r)} - {_mmss(4 * (r + 1))}",
         "porque": "el control mas honesto que hay: a 0-1 s/100 del objetivo, unas semanas antes de la prueba"},
        {"serie": "El dia de la prueba (14/11)",
         "diana": f"{rango.replace(' - ', ' a ')}",
         "porque": f"el plan busca {que}: el crono sale solo con la salida y la serie, si el ritmo esta metido"},
        {"serie": "La piscina de estos tiempos",
         "diana": PISCINA + ", en los dias propios y hasta junio",
         "porque": "los ritmos por 100 de las dianas son de vaso corto: en un vaso de 50 m el mismo esfuerzo sale mas lento"},
    ]


def _tiene_cifra(texto: str) -> bool:
    """Si una frase lleva un numero. En este discurso ninguna frase va sin cifra (regla del anexo U)."""
    return any(c.isdigit() for c in texto or "")


def _racha_en_agua(agua: dict, hoy: date) -> int:
    """Dias seguidos en el agua terminando hoy (o ayer, si hoy todavia no ha nadado)."""
    detalle = agua.get("detalle") or {}
    d = hoy if hoy.isoformat() in detalle else hoy - timedelta(days=1)
    n = 0
    while d.isoformat() in detalle:
        n += 1
        d -= timedelta(days=1)
    return n


def _falta_y_toca(cn: sqlite3.Connection, hoy: date, ritmo_objetivo: float, dias_al_reto: int,
                  fase: str | None = None) -> dict:
    """Lo que falta y lo que toca, con las cifras del motor y la seccion del anexo T que lo sostiene.

    La fase no se escribe a mano: sale del calendario del plan (`plan.fase_de`), asi que cuando cambie el bloque
    cambia lo que se le exige (V1.2-01: `especifico_400` hasta el 400, `base` en el bloque de base, `umbral_3000`
    camino del 3.000 del 18/03/2027).

    Es la tarea V1.1-04: hasta ahora `estimulos` (que falta) y `planificador` (en que dia cae) existian y estaban
    probados, pero no los llamaba nadie fuera de las pruebas: el portal decia como estaba el atleta y no decia
    **que habia que hacer**. Aqui se juntan los tres pasos: ventana de series -> deficits -> reparto por dia.

    Cada frase lleva su numero y su fuente: si el motor no tiene datos, se dice "sin datos" y no se rellena.
    """
    from . import estimulos, plan, planificador, series_dia

    fase = fase or plan.fase_de(hoy)      # V1.2-01: la fase la manda el calendario del plan, no quien llama

    desde = (hoy - timedelta(days=estimulos.VENTANA_DIAS - 1)).isoformat()
    agua = _agua(cn, hoy - timedelta(days=estimulos.VENTANA_DIAS - 1), hoy)
    v = series_dia.ventana(cn, desde, hoy.isoformat(), ritmo_objetivo)
    if not v.get("dias_con_dato"):
        return {"falta": "Sin datos en los ultimos 14 dias: no hay series que medir, asi que no se puede decir "
                         "que falta ni que toca.", "toca": "", "avisos": [], "deficits": [], "reparto": None,
                "fase": fase, "ventana": v}

    deficits = estimulos.deficits(v, fase, dias_al_reto=dias_al_reto, objetivo_100=ritmo_objetivo,
                                  dias_al_agua=float(_racha_en_agua(agua, hoy)))
    # La semana entera: en que dia cae cada sesion, cuantos metros pone cada una y si cabe en el volumen que el
    # plan deja para la semana (V1.2-02). El volumen sale del plan recalculado, no se escribe aqui.
    # Lo que ya lleva carga esa semana sin ser del plan (la fuerza y lo que manda el entrenador): el reparto no
    # pone calidad encima ni el dia de al lado, y lo dice (V1.3-05, V1.4-03).
    propuesta = planificador.propuesta_semana(deficits, objetivo_100=ritmo_objetivo,
                                              tests=plan.pruebas_de(hoy),
                                              km_semana=_km_de_la_semana(cn, hoy), fijos_m=_fijos_m(cn, hoy),
                                              cargados=fuerza.cargados_de_la_semana(cn, hoy.isoformat()))
    reparto = propuesta

    # --- que falta: un deficit por clase, cada uno con la cifra que lo sostiene y su seccion ---
    frases: list[str] = []
    for d in deficits:
        titulo = (d.get("titulo") or d.get("id") or "").strip()
        trozos = []
        tiene_min = any((m.get("tipo") == "minimo") for m in d.get("motivos") or [])
        for m in d.get("motivos") or []:
            t = (m.get("porque") or "").strip()
            if m.get("tipo") == "hueco" and tiene_min and not (d.get("metros_actuales") or 0):
                # Ya se ha dicho, con el minimo al lado, que no hay metros de esto. Repetirlo otra vez solo alarga.
                continue
            if not _tiene_cifra(t):
                # Un motivo sin cifra no entra en el discurso: se le pone delante la cifra de la clase.
                t = f"en la ventana de {estimulos.VENTANA_DIAS} dias hay {_millar(d.get('metros_actuales'))} m de " \
                    f"este trabajo y {t}"
            trozos.append(t)
        # Tras los dos puntos va en minuscula (es como se escribe en castellano); los motivos siguientes, en frase
        # aparte, empiezan en mayuscula.
        trozos = [trozos[0]] + [(t[0].upper() + t[1:]) for t in trozos[1:]] if trozos else trozos
        sello = (f"(anexo {' y '.join(d['seccion_T'])}" if d.get("seccion_T") else "(criterio, sin fuente")
        sello += f", {d.get('grado') or 'criterio'})"
        # Con titulo delante y cada motivo en su frase: sin el titulo esto se leia como una parrafada corrida
        # donde no se sabia de que se estaba hablando.
        cuerpo = ". ".join(t.strip().rstrip(".") for t in trozos if t.strip())
        frase = f"{titulo[0].upper() + titulo[1:]}: {cuerpo} {sello}" if cuerpo else f"{titulo} {sello}"
        frases.append(frase)
    falta = ""
    if frases:
        falta = (f"Midiendo los ultimos {estimulos.VENTANA_DIAS} dias ({_resumen_ventana(v)}): "
                 + ". ".join(f for f in frases if f) + ".")
    else:
        falta = (f"Midiendo los ultimos {estimulos.VENTANA_DIAS} dias ({_resumen_ventana(v)}): no falta nada "
                 f"de lo que pide la fase; el reparto por clase esta donde tiene que estar.")

    # --- que toca: en que dia cae cada sesion, con sus ritmos y su cada ---
    partes_sesion: list[str] = []
    for dia in ("martes", "jueves", "domingo"):
        s = (reparto.get("dias") or {}).get(dia)
        si = s and s.get("sesion")
        if not si:
            continue
        # Cuando la sesion viene en trozos (calentamiento | serie principal | sueltos), el ritmo y el cada son de
        # la serie principal: decir "a 1:19-1:23" a secas haria pensar que el calentamiento va a ese ritmo.
        quien = "la serie principal" if "|" in str(si) else "la sesion"
        cuando = ""
        if s.get("ritmo_desde") and s.get("ritmo_hasta"):
            cuando = f", con {quien} a {_ritmo(s['ritmo_desde'])}-{_ritmo(s['ritmo_hasta'])} por 100"
        cada = f", salida cada {_mmss(s['cada_s'])}" if s.get("cada_s") else ""
        metros = f", {_millar(s['metros'])} m" if s.get("metros") else ""
        partes_sesion.append(f"el {dia}, {si}{cuando}{cada}{metros}")
    toca = ""
    if partes_sesion:
        cola = ""
        vol = propuesta.get("volumen") or {}
        if vol.get("tope_m"):
            propio = int(vol.get("propio_m") or 0)
            cola = (f" Las sesiones propias suman {_millar(propio)} m y el plan deja {_millar(vol['tope_m'])} m para "
                    f"ellas: ")
            cola += "caben sin pasarse." if vol.get("cabe") else "no caben todas (el detalle, en los avisos)."
            hueco = vol.get("hueco_m")
            if vol.get("cabe") and hueco and hueco >= 500:
                cola += f" Quedan {_millar(hueco)} m de volumen facil, que se pueden nadar sueltos."
            if vol.get("fijos_m"):
                cola += (f" Aparte van los dias del entrenador: estos ultimos dias le han puesto unos "
                         f"{_millar(vol['fijos_m'])} m a la semana, que no entran en la cuenta del plan.")
            if propuesta.get("dias_de_prueba"):
                cola += (f" El {' y el '.join(propuesta['dias_de_prueba'])} hay prueba en el plan: ese dia no se "
                         f"prescribe nada, y el de antes no lleva trabajo de calidad.")
            # Los dias que ya llevan carga (la fuerza, la sesion del entrenador): por que no se les pone calidad
            # encima ni al de al lado (V1.3-05, V1.4-03).
            for a in propuesta.get("avisos_carga") or []:
                cola += " " + a[:1].upper() + a[1:] + "."

        toca = ("Esta semana: " + "; ".join(partes_sesion) + "." + cola + " Los lunes, miercoles y viernes son del "
                "entrenador y no se les anade nada, y el sabado es bici (anexo L, regla R6).")
    avisos: list[str] = []
    for f in reparto.get("fuera") or []:
        tit = (f.get("titulo") or f.get("id") or "").strip()
        porque = (f.get("porque") or "").strip()
        avisos.append(f"No cabe en la semana: {tit[0].lower() + tit[1:]}. "
                      f"{porque[0].upper() + porque[1:] if porque else ''}.")
    for a in (v.get("avisos") or []):
        avisos.append(a[0].upper() + a[1:] + "." if not a.endswith(".") else a)
    return {"falta": falta, "toca": toca, "avisos": avisos, "deficits": deficits, "reparto": reparto,
            "propuesta": propuesta, "fase": fase, "ventana": v}


def _resumen_ventana(v: dict) -> str:
    """El tamaño de lo medido, para poder juzgar la frase: metros, dias y de donde salen los metros."""
    de = {"parte": "del parte", "reloj": "del reloj", "mixto": "parte y reloj"}.get(v.get("origen") or "", "")
    return (f"{_millar(v.get('total_m') or 0)} m en {v.get('dias_con_dato') or 0} dias, medidos {de}, "
            f"{_millar(v.get('calidad_m') or 0)} m de trabajo de calidad")


def discurso(cn: sqlite3.Connection, bloques: list[dict], datos: dict,
             hoy: date | None = None) -> dict:
    """La valoracion entera: titular, parrafos con datos reales, dianas de entrenamiento y avisos."""
    hoy = hoy or date.today()
    obj = plan.OBJETIVO_B
    obj_a = plan.OBJETIVO_A
    r = float(obj["ritmo_objetivo_100"])
    dias_b = (plan._fecha(obj["fecha"]) - hoy).days      # noqa: SLF001
    dias_a = (plan._fecha(obj_a["fecha"]) - hoy).days    # noqa: SLF001

    # --- tramos de volumen: la semana, la anterior, el mes y el mes de antes ---
    # La ventana llega hasta hoy mismo: si ya hay una sesion hecha (del reloj o apuntada a mano), es del atleta y
    # tiene que contar. No se inventa nada por adelantado: solo cuenta lo que ya esta en la base.
    ultimo = hoy
    semana = _agua(cn, ultimo - timedelta(days=DIAS_SEMANA - 1), ultimo)
    semana_previa = _agua(cn, ultimo - timedelta(days=2 * DIAS_SEMANA - 1), ultimo - timedelta(days=DIAS_SEMANA))
    mes = _agua(cn, ultimo - timedelta(days=DIAS_MES - 1), ultimo)
    mes_previo = _agua(cn, ultimo - timedelta(days=2 * DIAS_MES - 1), ultimo - timedelta(days=DIAS_MES))

    # --- como esta el 400: el mejor bloque seguido de fiar en los ultimos 30 dias y en los 30 de antes ---
    b400_mes = _bloque(bloques, 400, ultimo - timedelta(days=DIAS_MES - 1), ultimo)
    b400_previo = _bloque(bloques, 400, ultimo - timedelta(days=2 * DIAS_MES - 1),
                          ultimo - timedelta(days=DIAS_MES))
    b400_90 = _bloque(bloques, 400, ultimo - timedelta(days=90), ultimo)
    # El dato mas limpio para hablar del ritmo del 400: un tramo intenso con material comprobado del parte.
    ref_intensa = _referencia_intensa(cn, ultimo - timedelta(days=90), ultimo)
    b1000 = _bloque(bloques, 1000, ultimo - timedelta(days=90), ultimo)
    kpis = datos.get("kpis") or {}
    # La mediana de sus tres mejores 1.000 a brazo libre: contra eso se mide lo que nade ahora.
    ref1000 = (kpis.get("mejor_1000") or {}).get("fiable")
    historico_400 = kpis.get("mejor_400") or {}

    # --- la semana del plan que esta en curso y lo que le queda por hacer ---
    semanas = (datos.get("evaluacion") or {}).get("semanas") or []
    en_curso = next((s for s in semanas if s.get("en_curso")), None)
    plan_semana = _semana_del_plan(en_curso["clave"]) if en_curso else None
    por_hacer = []
    if plan_semana:
        # Lo que queda es lo que el plan pedia y todavia no esta hecho. Manda el veredicto: una sesion ya hecha
        # (aunque sea de hoy y aunque se hiciera sin reloj, apuntada a mano) no se anuncia como pendiente.
        estados = {v["fecha"]: v.get("estado") for v in (en_curso or {}).get("sesiones") or []}
        for s in plan_semana["sesiones"]:
            if s["quien"] != "nosotros" or plan._fecha(s["fecha"]) < hoy:   # noqa: SLF001
                continue
            if estados.get(s["fecha"]) not in (None, "pendiente"):
                continue
            por_hacer.append(s)

    # --- el ciclo: el bloque de fondo en el que estamos y el ajuste que propone el plan ---
    ciclo = _bloque_de(hoy)
    ajuste = (en_curso or {}).get("ajuste") or {}

    parrafos: list[dict] = []
    avisos: list[str] = []

    # 1. Donde estamos.
    refs = "; ".join(f"{x['que']} ({x['fecha']})" for x in obj.get("referencias") or [])
    parrafos.append({
        "titulo": "Donde estamos",
        "texto": (f"Quedan {dias_b} dias para el 400 libre del 14/11 (y {dias_a} para los 3.000 del 18/03). "
                  f"El 400 se gana a {_ritmo(r)} por 100, o sea {_mmss(obj['marca_objetivo_s'])} en el crono. "
                  f"Tus referencias: {refs}. No es un objetivo nuevo: es volver a tu nivel."),
    })

    # 2. La progresion de los ultimos dias y semanas.
    arranque = (f"En los ultimos {DIAS_SEMANA} dias has estado en el agua {semana['dias']} "
                f"{'dia' if semana['dias'] == 1 else 'dias'} y has nadado {_km(semana['metros'])}; "
                f"en los {DIAS_SEMANA} de antes, {semana_previa['dias']} y {_km(semana_previa['metros'])}.")
    if b1000:
        # El 1.000 mas rapido con reloj de estos meses no tiene por que ser su nivel: si esta por detras de sus
        # tres mejores de siempre, ese dia salio flojo y no se puede vender como un logro.
        arranque += (f" El 1.000 con reloj mas rapido de estos meses: el del {_fecha_corta(b1000['fecha'])} en "
                     f"{_mmss(b1000['tiempo_s'])} ({_ritmo(b1000['ritmo_100'])} por 100). ")
        if ref1000 and b1000["ritmo_100"] <= float(ref1000) + 0.5:
            arranque += "Para ti eso ya es un buen bloque: es de los mejores 1.000 que has nadado nunca."
        elif ref1000:
            arranque += (f" Ojo con la lectura: tus mejores 1.000 estan en {_ritmo(ref1000)} de mediana, asi que "
                         "ese dia salio por detras de tu nivel. El plan no lo va a tomar como referencia.")
    sin_reloj = [v for v in (datos.get("evaluacion") or {}).get("recientes", [])
                 if v.get("estado") == "apuntada"]
    if sin_reloj:
        ultima = max(sin_reloj, key=lambda v: v["fecha"])
        arranque += (f" Y sin reloj tambien se cuenta: la sesion del {_fecha_corta(ultima['fecha'])} "
                     f"({round(ultima.get('metros_hechos') or 0)} m) esta apuntada a mano y vale como la del dia.")
    # Los tiempos con material se nombran siempre que aparezcan: un 1.000 con aletas no es una marca de brazo
    # libre, y el discurso no puede citarlo como si lo fuera (es lo que el atleta pidio que se tuviera en cuenta).
    b1000_mat = _bloque_material(bloques, 1000, ultimo - timedelta(days=DIAS_MES - 1), ultimo)
    if b1000_mat:
        eq1000 = _equiv_libre(b1000_mat["ritmo_100"], b1000_mat["material"])
        arranque += (f" Y un aviso con los tiempos: el 1.000 del {_fecha_corta(b1000_mat['fecha'])} salio en "
                     f"{_mmss(b1000_mat['tiempo_s'])} ({_ritmo(b1000_mat['ritmo_100'])} por 100), pero **con "
                     f"{b1000_mat['material']}**. A brazo libre eso serian unos {_ritmo(eq1000)} por 100 "
                     "(estimacion de la ayuda del material), asi que no lo cuento como tu mejor 1.000 a brazo "
                     "libre: la referencia de verdad es la mediana de tus tres mejores"
                     + (f", {_ritmo(ref1000)}." if ref1000 else "."))
    parrafos.append({"titulo": "Como va la progresion", "texto": arranque})

    # 3. Contra hace un mes.
    comparativa = (f"Ultimos {DIAS_MES} dias: {mes['dias']} dias en el agua y {_km(mes['metros'])}. "
                   f"Los {DIAS_MES} anteriores: {mes_previo['dias']} dias y {_km(mes_previo['metros'])}.")
    if b400_mes and b400_previo:
        mejora = b400_previo["ritmo_100"] - b400_mes["ritmo_100"]
        comparativa += (f" El mejor 400 seguido: {_fecha_corta(b400_mes['fecha'])} a "
                        f"{_ritmo(b400_mes['ritmo_100'])} ({_mmss(b400_mes['tiempo_s'])}), "
                        f"frente al {_fecha_corta(b400_previo['fecha'])} a {_ritmo(b400_previo['ritmo_100'])}.")
        comparativa += (f" Has bajado {mejora:.1f} s/100 en un mes." if mejora > 0
                        else f" Vas {abs(mejora):.1f} s/100 mas lento que hace un mes.")
    elif b400_mes:
        comparativa += (f" El mejor 400 seguido de este mes: {_fecha_corta(b400_mes['fecha'])} a "
                        f"{_ritmo(b400_mes['ritmo_100'])} ({_mmss(b400_mes['tiempo_s'])}). "
                        "En el mes anterior no hay ningun 400 seguido medido, asi que la comparacion del "
                        "ritmo queda para el mes que viene.")
    else:
        comparativa += (" En los ultimos 30 dias no hay ningun 400 seguido de fiar: los 400 de la semana "
                        "pasada fueron con material, y con material el ritmo no se compara.")
    parrafos.append({"titulo": "Contra hace un mes", "texto": comparativa})

    # 3-bis. Con que se hizo cada bloque: el material se nombra y se descuenta, no se cuela como brazo libre.
    con_material = _bloques_material(bloques, ultimo - timedelta(days=DIAS_MES - 1), ultimo)
    if con_material:
        piezas = []
        for b in con_material:
            eq = _equiv_libre(b["ritmo_100"], b["material"])
            piezas.append(f"{round(b['dist_m'])} m del {_fecha_corta(b['fecha'])} con {b['material']} "
                          f"({_ritmo(b['ritmo_100'])} por 100; a brazo libre, ~{_ritmo(eq)})")
        material_txt = ("Los tiempos con material no se comparan con los de brazo libre, asi que van aparte y con "
                        "la ayuda descontada: " + "; ".join(piezas) + ". La ayuda que se descuenta es una "
                        "estimacion (aletas ~10 s/100, palas ~6, pull ~4), pero el sentido es el correcto: lo "
                        "que llevas puesto no es lo que nadas. En las dianas y en el plan solo entran los tiempos "
                        "a brazo libre.")
        parrafos.append({"titulo": "Con que se hizo cada bloque", "texto": material_txt})

    # 4. Lo que queda en la semana.
    if en_curso and plan_semana:
        restante = (f"{en_curso['clave']} ({_fecha_corta(en_curso['desde'])} a "
                    f"{_fecha_corta(en_curso['hasta'])}): {plan_semana['foco'].lower()}. "
                    f"Llevas {_km(en_curso['km_hechos_nuestras'] * 1000)} de los "
                    f"{str(en_curso['km_plan']).replace('.', ',')} km del plan"
                    f" ({en_curso['sesiones_hechas']} de {en_curso['sesiones_plan']} sesiones hechas). "
                    "Lunes, miercoles y viernes no entran en estas cuentas: esas sesiones son del entrenador "
                    "y se hacen como el diga.")
        if por_hacer:
            trozos = []
            for s in por_hacer:
                detalle = (s.get("detalle") or "").strip()
                if len(detalle) > 150:
                    detalle = detalle[:147].rstrip() + "..."
                trozos.append(f"{s['dia']}: {s['titulo']} ({detalle})")
            restante += " Queda " + " | ".join(trozos) + "."
        else:
            restante += " No queda nada por hacer de esta semana: la has cerrado entera."
        # La piscina de la semana (el atleta, 18/10/2026): los bloques propios son de 25 m. Si alguno salio en vaso
        # de 50 m, sus ritmos por 100 no son comparables y se dice, en vez de mezclarlos con los de vaso corto.
        delasemana = [b for b in bloques if en_curso["desde"] <= (b.get("fecha") or "") <= en_curso["hasta"]]
        vasos = sorted({float(b["piscina_m"]) for b in delasemana if b.get("piscina_m")})
        otros = [v for v in vasos if float(v) != 25.0]
        if otros:
            restante += (f" Ojo: en la semana hay bloques en vaso de {', '.join(f'{int(v)} m' for v in otros)} y los "
                          "ritmos por 100 de un vaso de 50 m salen mas lentos: no se comparan con los de 25 m.")
        else:
            restante += " Los dias propios son de vaso de 25 m: los ritmos por 100 valen tal cual."

        parrafos.append({"titulo": "Lo que queda de semana", "texto": restante})
    else:
        avisos.append("La semana del plan que toca no se puede leer: el portal no sabe que queda por hacer.")

    # 5. Como va el ciclo.
    ciclo_texto = ""
    if ciclo:
        ciclo_texto = (f"En la parte larga del plan estas en el bloque '{ciclo['nombre']}' "
                       f"({_fecha_corta(ciclo['desde'])} a {_fecha_corta(ciclo['hasta'])}, {ciclo['km']} km por "
                       f"semana): {ciclo['que'].lower()} ")
    else:
        ciclo_texto = ("De momento estas en la recta del 400: las cinco semanas del plan (S1 a S5, del 12/10 al "
                       "15/11) son el camino hasta la prueba, y el ciclo largo del 3.000 arranca despues. ")
    bloques_txt = ", ".join(f"{b['nombre'].lower()} ({b['km']} km)" for b in plan.BLOQUES if b["km"] != "-")
    km_sem = ", ".join(f"{k} {str(v).replace('.', ',')} km" for k, v in plan.KILOMETROS_SEMANA.items())
    ciclo_texto += (f"Ese ciclo del 3.000 (del {_fecha_corta(plan.BLOQUES[0]['desde'])} al "
                    f"{_fecha_corta(plan.BLOQUES[-1]['hasta'])}) va asi, en este orden: {bloques_txt}. "
                    f"Y el camino del 400 sube de a poco ({km_sem}), con una descarga cada cuatro semanas y la "
                    "semana de la prueba mas floja: no hay taper largo ni otro compromiso detras.")
    if ajuste:
        motivos = "; ".join(ajuste.get("motivos") or [])
        ciclo_texto += (f" Para la semana que viene el plan propone {ajuste.get('accion')} "
                        f"({str(ajuste.get('km_propuestos')).replace('.', ',')} km). Por que: {motivos}.")
        if ajuste.get("provisional"):
            ciclo_texto += " Todavia es provisional: se cierra cuando acabe la semana."
    parrafos.append({"titulo": "Como va el ciclo", "texto": ciclo_texto})

    # 6. Que te falta: el motor de estimulos, con sus cifras y su seccion del anexo T (tarea V1.1-04).
    motor = _falta_y_toca(cn, hoy, r, dias_b)
    if motor.get("falta"):
        parrafos.append({"titulo": "Que te falta", "texto": motor["falta"]})
    # 7. Que toca esta semana: el reparto por dia (una sesion dura por dia propio, martes y jueves de calidad).
    if motor.get("toca"):
        parrafos.append({"titulo": "Que toca esta semana", "texto": motor["toca"]})
    avisos.extend(motor.get("avisos") or [])

    # 8. Que se puede esperar (sin prometer lo que los datos no dicen).
    esperar = ""
    if b400_90:
        falta = b400_90["ritmo_100"] - r
        esperar = (f"Tu mejor 400 seguido de los ultimos 90 dias: {_fecha_corta(b400_90['fecha'])} en "
                   f"{_mmss(b400_90['tiempo_s'])} ({_ritmo(b400_90['ritmo_100'])} por 100). ")
        if b400_90.get("material_conocido"):
            esperar += "Ese dia hay parte, asi que consta que fue a brazo libre. "
        else:
            # Sin parte no consta el material que llevaba: un 400 con aletas no es una marca y no se puede
            # presentar como si lo fuera. Se dice tal cual, con lo que valdria a brazo libre.
            con_aletas = _equiv_libre(b400_90["ritmo_100"], "aletas")
            esperar += (f"Pero de ese dia NO hay parte, asi que no consta con que se hizo: si llevabas aletas, "
                        f"a brazo libre serian unos {_ritmo(con_aletas)} por 100 (las aletas regalan unos "
                        f"{AYUDA_MATERIAL['aletas']:.0f} s/100), y entonces ese 400 no vale como referencia. ")
        esperar += (f"El objetivo son {_ritmo(r)} ({_mmss(300)}): estas a "
                    f"{f'{falta:.1f}'.replace('.', ',')} s/100. ")
        if b400_90.get("material_conocido"):
            esperar += ("Eso no es un mundo en un 400: son unas decimas por largo. " if falta <= 4
                        else "Hay trabajo por delante, pero es el trabajo que el plan ya tiene puesto. ")
        else:
            # Sin saber el material, esa distancia al objetivo no mide nada: el numero bueno es el del parte.
            esperar += ("Mientras el material no conste, esos s/100 no dicen donde estas. ")
    # El dato que si se sostiene: un tramo INTENSO con material comprobado, del parte. Ni calentamientos ni
    # material que ayude: el parte dice las dos cosas, asi que la referencia no hay que suponerla.
    if ref_intensa:
        falta_ref = ref_intensa["ritmo_100"] - r
        como = (f"{int(ref_intensa['n_reps'])}x{int(ref_intensa['rep_m'])}"
                if (ref_intensa.get("n_reps") or 1) > 1 and ref_intensa.get("rep_m")
                else f"{int(ref_intensa['metros'])} m seguidos")
        etiqueta = ETIQUETA_INTENSIDAD.get(ref_intensa.get("intensidad") or "", "")
        esperar += (f"El dato que si se sostiene es del parte del {_fecha_corta(ref_intensa['fecha'])}: "
                    f"{como} de {etiqueta} a {_ritmo(ref_intensa['ritmo_100'])} de media, con el material "
                    f"comprobado (a brazo libre), a "
                    f"{f'{falta_ref:.1f}'.replace('.', ',')} s/100 del ritmo del 400. ")
    if historico_400.get("fiable"):
        esperar += (f"Para tener perspectiva: tu mejor 400 de entrenamiento es "
                    f"{_ritmo(historico_400['fiable'])} ({_fecha_corta(historico_400['fecha'])}), de antes de "
                    "que hubiera partes: tampoco consta el material con que se hizo. ")
    esperar += ("Lo que se puede esperar del plan es el ritmo, no un crono prometido: los dos tests que vienen "
                "(el 1.500 del dom 18 y el 8x100 con salida cada 2:00 del mar 20) diran donde estas de verdad. "
                "Si el 8x100 se sostiene y el 400 seguido baja de 5:10, el 5:00 esta al alcance; si no, el plan "
                "tiene margen para repetir bloque, no para inventarse una marca.")
    parrafos.append({"titulo": "Que se puede esperar", "texto": esperar})

    # 9. Lo que no se puede juzgar todavia (honestidad: se dice, no se rellena).
    partes = datos.get("partes") or {}
    resumen_partes = partes.get("resumen") or {}
    if not resumen_partes.get("partes"):
        avisos.append("No hay ningun parte subido: sin parte no se puede ver el material ni la intensidad real "
                      "de los bloques (el reloj no los registra).")
    else:
        avisos.append(f"Hay {resumen_partes['partes']} parte(s) en la base (el ultimo, "
                      f"{_fecha_corta(str(resumen_partes['ultimo']))}): el material y la intensidad de las "
                      "sesiones que no lo tengan no se pueden juzgar.")
    sin_parte = [v for v in (datos.get("evaluacion") or {}).get("recientes", [])
                 if v.get("estado") == "sin_parte"]
    if sin_parte:
        avisos.append(f"{len(sin_parte)} sesion(es) del plan de los ultimos dias estan sin parte: en esas se "
                      "ve lo que trae el reloj, pero no se puede decir si el bloque salio como pedia el plan.")
    apuntadas = [v for v in (datos.get("evaluacion") or {}).get("recientes", [])
                 if v.get("estado") == "apuntada"]
    if apuntadas:
        avisos.append(f"{len(apuntadas)} sesion(es) hechas sin reloj y apuntadas a mano: cuentan como hechas, "
                      "pero sin laps no se puede medir el ritmo bloque a bloque.")

    return {
        "fecha": hoy.isoformat(),
        # Cuando se ha escrito este discurso (el dia que lo lee no es el mismo que el de los datos). Se sella aqui,
        # con la hora del PC, para que el que lo lea sepa si esta mirando el informe de esta tarde o el de la semana
        # pasada: el resto del texto no cambia y pareceria de hoy.
        "generado": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "titular": (f"Quedan {dias_b} dias para el 400 del 14/11. El objetivo es {_mmss(300)} "
                    f"({_ritmo(r)} por 100) y tu mejor 400 de los ultimos 90 dias esta en "
                    f"{_ritmo(b400_90['ritmo_100']) if b400_90 else 'sin medir'}"
                    f"{'' if (b400_90 or {}).get('material_conocido') else ' (sin parte: el material de ese dia no consta)'}."),
        "parrafos": parrafos,
        "dianas": _dianas(r, obj["rango"], obj["que"]),
        "avisos": avisos,
        # Los numeros que sostienen el discurso, para poder comprobarlos (y para las pruebas).
        "fuentes": {
            "dias_para_el_400": dias_b,
            "dias_para_el_3000": dias_a,
            "ritmo_objetivo_100": r,
            "semana": semana, "semana_previa": semana_previa,
            "mes": mes, "mes_previo": mes_previo,
            "mejor_400_mes": b400_mes, "mejor_400_mes_previo": b400_previo, "mejor_400_90d": b400_90,
            "intensa_parte": ref_intensa,
            "mejor_1000_90d": b1000,
            "ciclo": ciclo,
            # El motor (V1.1-04): la ventana de series, los deficits y el reparto por dia, tal cual salieron.
            "motor": {
                "fase": motor.get("fase"),
                "ventana": {k: (motor.get("ventana") or {}).get(k) for k in (
                    "desde", "hasta", "dias_con_dato", "dias_parte", "dias_reloj", "origen", "total_m",
                    "calidad_m", "por_clase", "continuo_mas_largo_m")},
                "deficits": motor.get("deficits"),
                "reparto": motor.get("reparto"),
                # La semana entera propuesta (V1.2-02): los siete dias con sus metros y lo que cabe en el volumen.
                "propuesta": motor.get("propuesta"),
            },
        },
    }


def texto(datos: dict) -> str:
    """El discurso en texto plano (para la consola y para leerlo de un tiron)."""
    v = datos or {}
    lineas = [v.get("titular", ""), ""]
    for p in v.get("parrafos") or []:
        lineas.append(f"{p['titulo'].upper()}")
        lineas.append(p["texto"])
        lineas.append("")
    if v.get("dianas"):
        lineas.append("TIEMPOS DE ENTRENAMIENTO PARA EL RETO")
        for d in v["dianas"]:
            lineas.append(f"- {d['serie']}: {d['diana']} ({d['porque']})")
        lineas.append("")
    for a in v.get("avisos") or []:
        lineas.append(f"({a})")
    return "\n".join(lineas).strip()


# ---------------------------------------------------------------------------
# La valoracion de UN entrenamiento (el boton "que lo evalue el entrenador")
# ---------------------------------------------------------------------------
# El discurso de arriba mira el conjunto (la progresion, el ciclo). Esto mira **una sesion** y lo que de verdad
# decide si ha ido bien: los tiempos bloque a bloque (descontando el material), la distancia, el **esfuerzo
# previo** (lo que ya llevaba nadado, en los dias de antes y dentro de la propia sesion) y los **descansos**
# (el `cada` de cada serie). Todo sale de los datos: ni una cifra a mano.

def _nado_de(cn: sqlite3.Connection, actividad_id: int) -> dict:
    """El ritmo de nado de una sesion, sin contar los descansos (el del reloj los incluye y engana)."""
    filas = cn.execute(
        """SELECT dist_m, timer_s FROM natacion_lap
           WHERE actividad_id = ? AND dist_m > 0""", (actividad_id,)).fetchall()
    metros = sum(float(f["dist_m"] or 0) for f in filas)
    segundos = sum(float(f["timer_s"] or 0) for f in filas)
    return {"metros": round(metros), "segundos": round(segundos),
            "ritmo_100": (100.0 * segundos / metros) if metros else None}


# Las intensidades del parte que cuentan como apretar: son las unicas que sirven de referencia de ritmo cuando
# el material esta comprobado (el parte lo dice). Un calentamiento rapido no es una referencia de nada.
INTENSAS = ("ae3", "swolf")


def _referencia_intensa(cn: sqlite3.Connection, desde: date, hasta: date) -> dict | None:
    """El mejor tramo INTENSO con material comprobado de los partes de un tramo de fechas.

    Es el dato honesto: el parte dice la intensidad y el material, asi que no hay que suponer nada. Fuera quedan
    los calentamientos y todo lo que llevaba aletas, palas o pull (eso ayuda, no mide al atleta).
    """
    mejor = None
    for fila in cn.execute("SELECT fecha FROM parte WHERE fecha >= ? AND fecha <= ? ORDER BY fecha DESC",
                           (desde.isoformat(), hasta.isoformat())):
        for s in _series_del_parte(cn, fila["fecha"]):
            if (s.get("intensidad") or "") not in INTENSAS or (s.get("material") or "").strip():
                continue
            metros = float(s.get("metros") or 0)
            segundos = float(s.get("tiempo_s") or 0)
            if metros < 50 or segundos <= 0:
                continue
            ritmo = 100.0 * segundos / metros
            if not (60.0 <= ritmo <= 150.0):
                continue
            if mejor is None or ritmo < mejor["ritmo_100"]:
                mejor = {"fecha": fila["fecha"], "metros": round(metros), "tiempo_s": round(segundos, 1),
                         "ritmo_100": round(ritmo, 1), "intensidad": s.get("intensidad"),
                         "n_reps": s.get("n_reps"), "rep_m": s.get("rep_m"), "cada_s": s.get("cada_s")}
    return mejor


def _series_del_parte(cn: sqlite3.Connection, fecha: str) -> list[dict]:
    """Los grupos del parte de ese dia tal como quedaron: con su `cada`, su descanso y su material."""
    fila = cn.execute("SELECT id FROM parte WHERE fecha = ? ORDER BY id DESC", (fecha,)).fetchone()
    if not fila:
        return []
    return [dict(s) for s in cn.execute(
        "SELECT * FROM parte_serie WHERE parte_id = ? ORDER BY orden", (fila["id"],))]


def _esfuerzo_previo(cn: sqlite3.Connection, fecha: str, dias: int = 3) -> dict:
    """Lo nadado en los `dias` dias de antes (sin contar el dia de la sesion): metros, dias y ritmo medio."""
    d = plan._fecha(fecha)  # noqa: SLF001
    desde = (d - timedelta(days=dias)).isoformat()
    hasta = (d - timedelta(days=1)).isoformat()
    agua = _agua(cn, plan._fecha(desde), plan._fecha(hasta))  # noqa: SLF001
    segundos, metros = 0, 0
    for f in cn.execute(
        """SELECT l.dist_m AS dist, l.timer_s AS t FROM natacion_lap l
           JOIN actividad a ON a.id = l.actividad_id
           WHERE substr(a.inicio_local, 1, 10) BETWEEN ? AND ? AND l.dist_m > 0""", (desde, hasta)):
        metros += float(f["dist"] or 0)
        segundos += float(f["t"] or 0)
    return {"dias": dias, "dias_en_agua": agua["dias"], "metros": round(metros),
            "ritmo_100": (100.0 * segundos / metros) if metros else None,
            "metros_agua": agua["metros"]}


def sesion(cn: sqlite3.Connection, actividad_id: int, datos: dict | None = None) -> dict | None:
    """La valoracion del entrenador para UN entrenamiento concreto.

    Responde a lo que el atleta pregunta al terminar: como ha ido **esta** sesion y como va el plan. Mira los
    tiempos (y el material que los ayuda), la distancia, el esfuerzo que ya traia encima y los descansos, que
    son los cuatro datos que separan un entrenamiento bueno de uno que solo llena metros.
    """
    act = cn.execute(
        """SELECT a.id, a.inicio_local, a.distancia_m, a.duracion_s, a.nombre,
                  s.largo_piscina_m, s.fc_media, s.sensacion
           FROM actividad a LEFT JOIN natacion_sesion s ON s.actividad_id = a.id
           WHERE a.id = ?""", (actividad_id,)).fetchone()
    if not act:
        return None
    fecha = (act["inicio_local"] or "")[:10]
    datos = datos or {}
    plan_obj = plan.OBJETIVO_B                      # el reto que manda ahora: el 400
    objetivo = float(plan_obj["ritmo_objetivo_100"])
    marca_obj = float(plan_obj["marca_objetivo_s"])

    # Los bloques de esta sesion, del historico ya calculado (lleva material y brazo libre).
    de_hoy = [b for b in (datos.get("bloques") or []) if b.get("actividad_id") == actividad_id]
    if not de_hoy:
        from . import analitica
        de_hoy = [b for b in analitica.bloques(cn) if b.get("actividad_id") == actividad_id]
    series = _series_del_parte(cn, fecha)
    nado = _nado_de(cn, actividad_id)

    minutos = (float(act["duracion_s"]) / 60.0) if act["duracion_s"] else None
    titulo = ((plan.sesion_de(fecha) or {}).get("titulo") or act["nombre"] or "Entrenamiento")
    piscina = act["largo_piscina_m"]

    parrafos: list[dict] = []

    # 1. Que se ha hecho, en numeros (y el material, que el reloj no sabe).
    con_material = [b for b in de_hoy if not b.get("brazo_libre", True)]
    cab = (f"{_millar(nado['metros'] or act['distancia_m'] or 0)} m")
    if minutos:
        cab += f" en {minutos:.0f} min"
    if piscina:
        cab += f" (piscina de {piscina:.0f} m)"
    que = [cab]
    if nado["ritmo_100"]:
        que.append(f"Ritmo medio de nado {_ritmo(nado['ritmo_100'])}/100, con los descansos aparte "
                   f"(el calentamiento y la tecnica entran en esa media)")
    if act["fc_media"]:
        que.append(f"FC media {act['fc_media']:.0f}")
    if act["sensacion"] is not None:
        que.append(f"Sensacion {act['sensacion']:.0f}/100")
    texto_1 = ". ".join(que) + "."
    if con_material:
        ayudas = ", ".join(sorted({b["material"] for b in con_material}))
        texto_1 += (f" De esos metros, {_millar(sum(b['dist_m'] for b in con_material))} m fueron con "
                    f"{ayudas}: cuentan como trabajo, pero no como ritmo de brazo libre.")
    parrafos.append({"titulo": "Lo que has hecho", "texto": texto_1})

    # 2. Los tiempos: los grupos del parte, que es como el atleta ve su entrenamiento (200 AeMedio, 2x100
    # AeIntenso...), con el material descontado y el orden real de la sesion. Comparar el ritmo medio de una
    # sesion de 3.600 m con el de un 400 a tope no diria nada: se comparan los bloques de calidad.
    lineas, antes = [], 0.0
    for s in series:
        ritmo = s.get("ritmo_100")
        if not ritmo:
            continue
        etiqueta = (f"{s['n_reps']}x{round(s['rep_m'] or 0)} m" if (s.get("n_reps") or 0) >= 2
                    else f"{round(s.get('metros') or 0)} m")
        if s.get("intensidad"):
            etiqueta += f" {partes.ETIQUETA_INTENSIDAD.get(s['intensidad'], s['intensidad'])}"
        trozo = f"{etiqueta}: {_ritmo(ritmo)}/100"
        if s.get("material"):
            trozo += (f" (con {s['material']}; a brazo libre serian "
                      f"{_ritmo(_equiv_libre(ritmo, s['material']))})")
        if s.get("cada_s"):
            trozo += f", cada {_mmss(s['cada_s'])}"
        trozo += f", tras {_millar(antes)} m de sesion" if antes else ", en frio"
        lineas.append(trozo)
        antes += float(s.get("metros") or 0)
    if lineas:
        parrafos.append({"titulo": "Los tiempos, bloque a bloque", "texto": ". ".join(lineas) + "."})

    # 3. El esfuerzo previo: con que piernas venia.
    previo = _esfuerzo_previo(cn, fecha, dias=3)
    semana = _esfuerzo_previo(cn, fecha, dias=7)
    t3 = (f"En los 3 dias de antes: {_millar(previo['metros'])} m en {previo['dias_en_agua']} dias"
          + (f", a {_ritmo(previo['ritmo_100'])}/100 de media" if previo["ritmo_100"] else "") + ".")
    t7 = (f" En la semana previa llevabas {_millar(semana['metros'])} m en {semana['dias_en_agua']} dias"
          + (f" ({_ritmo(semana['ritmo_100'])}/100)." if semana["ritmo_100"] else "."))
    remate = (" Con esa carga encima, lo de hoy dice mas de tu fondo que de tu punta de velocidad."
              if previo["metros"] >= 5000 else
              " Sin apenas carga acumulada, lo de hoy se lee casi en fresco: es tu nivel del dia.")
    parrafos.append({"titulo": "El esfuerzo previo", "texto": t3 + t7 + remate})

    # 4. Los descansos: el `cada` de cada serie y que se puede hacer con el.
    de_series = [s for s in series if s.get("cada_s") and (s.get("n_reps") or 0) >= 2]
    if de_series:
        trozos = []
        for s in de_series:
            que_serie = f"{s['n_reps']}x{round(s['rep_m'] or 0)} m"
            if s.get("intensidad"):
                que_serie += f" ({partes.ETIQUETA_INTENSIDAD.get(s['intensidad'], s['intensidad'])})"
            trozos.append(f"{que_serie}: cada {_mmss(s['cada_s'])}"
                          + (f", con {_mmss(s['descanso_s'])} de descanso" if s.get("descanso_s") else ""))
        texto_4 = "; ".join(trozos) + "."
        cortos = [s for s in de_series if (s.get("descanso_s") or 0) <= 45]
        largos = [s for s in de_series if (s.get("descanso_s") or 0) > 60]
        if cortos:
            texto_4 += (" Con esos descansos cortos las series se parecen a la prueba: asi se entrena el 400, "
                        "con el pulso arriba.")
        if largos:
            texto_4 += (" Los descansos largos son para series de calidad a tope (cada repeticion en fresco): "
                        "si la idea era aguantar ritmo, habia margen para recortarlos.")
        parrafos.append({"titulo": "Los descansos", "texto": texto_4})

    # 5. Como va el plan: lo de esta sesion contra lo que pedia, y la semana en curso.
    sesion_plan = plan.sesion_de(fecha)
    pedia = plan.metros_de_sesion(sesion_plan) if sesion_plan else None
    propia = bool(sesion_plan and sesion_plan.get("quien") == "nosotros")
    texto_5 = ""
    if propia and pedia:
        texto_5 = (f"La sesion de hoy pedia {round(pedia)} m y has nadado {round(nado['metros'])} m "
                   f"({100.0 * nado['metros'] / pedia:.0f} %).")
    else:
        texto_5 = (f"Esta no es de las mias del plan ({titulo}): cuenta como entrenamiento tuyo, "
                   f"{_millar(nado['metros'])} m.")
    clave = (plan.semana_de(fecha) or {}).get("clave")
    if clave:
        hechos = _agua(cn, plan._fecha((plan.semana_de(fecha) or {}).get("desde", fecha)),  # noqa: SLF001
                       plan._fecha((plan.semana_de(fecha) or {}).get("hasta", fecha)))      # noqa: SLF001
        previstos = plan.KILOMETROS_SEMANA.get(clave)
        if previstos:
            km = hechos["metros"] / 1000.0
            texto_5 += (f" En la semana {clave} llevas {km:.1f} km de los {previstos:.1f} km previstos"
                        f" ({100.0 * km / previstos:.0f} %), en {hechos['dias']} dias en el agua.")
    prox = plan.siguiente(_sumar_dia(fecha))
    if prox:
        texto_5 += (f" Lo siguiente: {_fecha_corta(prox['fecha'])}, "
                    f"{prox.get('titulo') or prox.get('que') or 'sesion del plan'}"
                    + (f" ({round(plan.metros_de_sesion(prox))} m)." if plan.metros_de_sesion(prox) else "."))
    parrafos.append({"titulo": "Como va el plan", "texto": texto_5})

    # 6. El cierre: el bloque de calidad del dia contra el ritmo del reto. Se compara el bloque que aprieta
    # (una serie, o un bloque largo), no la media de la sesion: la media de 3.600 m con calentamiento dentro no
    # dice para nada lo que puede salir un 400.
    global_ = datos.get("valoracion") or {}
    mejor400 = (datos.get("kpis") or {}).get("mejor_400") or {}
    calidad = []
    for s in series:
        if not s.get("ritmo_100") or (s.get("metros") or 0) < 100:
            continue
        if not ((s.get("n_reps") or 1) >= 2 or (s.get("metros") or 0) >= 200):
            continue
        # A igualdad de distancias, manda el ritmo **a brazo libre**: si no, un bloque con aletas ganaria por
        # el material y saldria como el mejor del dia sin serlo.
        calidad.append((_equiv_libre(float(s["ritmo_100"]), s.get("material")), s))
    cierre = ""
    if calidad:
        ritmo, s = min(calidad, key=lambda x: x[0])
        nombre = (f"{s['n_reps']}x{round(s['rep_m'] or 0)} m" if (s.get("n_reps") or 0) >= 2
                  else f"{round(s.get('metros') or 0)} m")
        if s.get("intensidad"):
            nombre += f" {partes.ETIQUETA_INTENSIDAD.get(s['intensidad'], s['intensidad'])}"
        falta = ritmo - objetivo
        cierre = (f"Tu bloque de calidad de hoy ({nombre}) salio a {_ritmo(ritmo)}/100"
                  + (" a brazo libre estimado" if s.get("material") else "")
                  + ". El ritmo del reto es " + _ritmo(objetivo) + "/100: "
                  + (f"hoy has nadado {abs(falta):.1f} s/100 por encima, asi que el 400 saldria en "
                     f"{_mmss(ritmo * 4)}."
                     if falta > 0 else
                     f"hoy has nadado {abs(falta):.1f} s/100 por debajo del ritmo del reto: a ese ritmo el "
                     f"400 saldria en {_mmss(ritmo * 4)}."))
    if mejor400.get("fiable"):
        cierre += (f" Tu mejor 400 seguido de los ultimos 90 dias esta en {_ritmo(mejor400['fiable'])}/100 "
                   f"({_mmss(mejor400['fiable'] * 4)}).")
    if global_.get("titular"):
        cierre += " " + global_["titular"]
    if cierre:
        parrafos.append({"titulo": "Que dice para el reto", "texto": cierre.strip()})

    return {"actividad_id": actividad_id, "fecha": fecha, "titulo": titulo, "cabecera": cab,
            # Cuando se ha escrito esta valoracion (la sesion es de su dia; el texto, de ahora mismo).
            "generado": datetime.now().astimezone().replace(microsecond=0).isoformat(),
            "minutos": round(minutos) if minutos else None, "metros": round(nado["metros"]),
            "ritmo_100": round(nado["ritmo_100"], 1) if nado["ritmo_100"] else None,
            "objetivo_ritmo": objetivo, "marca_objetivo_s": marca_obj,
            "parrafos": parrafos}


def _sumar_dia(fecha: str):
    return plan._fecha(fecha) + timedelta(days=1) if fecha else date.today()   # noqa: SLF001


def _titulo_bloque(b: dict, series: list[dict]) -> str:
    """Como llamar a un bloque en el discurso: la serie del parte si la hay (2x100 AeIntenso), si no sus metros."""
    for s in series:
        if abs(float(s.get("metros") or 0) - float(b.get("dist_m") or 0)) <= 25 and (
                (s.get("n_reps") or 1) >= 2 or abs(float(b.get("dist_m") or 0) - float(s.get("metros") or 0)) < 25):
            trozo = f"{s['n_reps']}x{round(s['rep_m'] or 0)} m" if (s.get("n_reps") or 0) >= 2 else f"{round(b['dist_m'])} m"
            if s.get("intensidad"):
                trozo += f" {partes.ETIQUETA_INTENSIDAD.get(s['intensidad'], s['intensidad'])}"
            return trozo
    return f"{round(b['dist_m'])} m seguidos"
