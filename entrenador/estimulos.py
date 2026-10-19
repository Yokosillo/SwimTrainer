#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""El conocimiento de entrenamiento, como datos: que estimulo da cada tipo de serie y que toca despues.

Esto NO es un modelo de lenguaje ni un modelo entrenado con datos: es el criterio escrito a mano, en una forma
que el programa puede **calcular**. Tres piezas:

  1. `CLASES` - la tabla de estimulos. Cada clase dice que sistema entrena, que NO entrena, cuanto cuesta
     recuperarla, su papel en el 400 y en el 3.000, y como se reconoce en un parte. Sale de los anexos F
     (planificacion) y L (los objetivos 400 y 3.000): no se inventa nada nuevo.
  2. `clasificar` / `perfil` - mirar lo que el atleta ha hecho y decir **de que** esta hecho (metros por clase,
     bloque continuo mas largo). Sin esto no se puede juzgar una sesion ni ver que falta.
  3. `deficits` / `recetas` - comparar lo hecho con lo que pide la fase del plan y sacar **que toca ahora**, con
     numeros concretos (reps, distancia, ritmo, descanso).

Regla que manda sobre todas: las bandas de ritmo son las del atleta (se inyectan desde `plan`), no formulas
genericas. Si una conclusion no tiene datos detras, este modulo debe callarse, no rellenar el hueco con prosa.

Uso:
    from . import estimulos
    p = estimulos.perfil(series_del_parte)          # de que esta hecha la sesion
    d = estimulos.deficits(hist, fase="S3", dias_al_reto=22)   # que falta
    estimulos.recetas(d[0])                          # que sesion montar
"""

from __future__ import annotations

import re
from typing import Iterable

from . import reglas

# ---------------------------------------------------------------------------
# 1. La tabla de estimulos
# ---------------------------------------------------------------------------
#
# Cada clase:
#   nombre       como se llama en el discurso (el atleta no dice "VO2max", dice "series")
#   entrena      lo que de verdad mejora
#   no_entrena   lo que la gente cree que mejora y no mejora
#   recuperacion lo que cuesta recuperarla, en horas (manda para no encadenar dos dias duros)
#   papel400     para que sirve en un 400 libre
#   papel3000    para que sirve en un 3.000
#   senal        como se nota que falta este estimulo en el historico reciente
#
# Las clases de carga son las cinco que de verdad cambian algo; el material y la tecnica van aparte porque
# modifican el ritmo sin cambiar el sistema que se entrena (por eso el material nunca cuenta como brazo libre).

CLASES: dict[str, dict] = {
    "continuo_aerobico": {
        "nombre": "Fondo continuo suave",
        "entrena": ("capacidad aerobica, economia de brazada y la base que sostiene todo lo demas; "
                    "tambien la cabeza de aguantar sin parar"),
        "no_entrena": "nada de ritmo alto: no mejora la punta ni el ritmo de prueba",
        "recuperacion": 12,
        "papel400": "es lo que hace que el tercer 100 no se te caiga; sin fondo, un 400 se paga al final",
        "papel3000": "es literalmente la prueba: aguantar ritmo sin parar",
        "senal": "sesiones de mas de 2.000 m seguidos hace mas de 15 dias",
    },
    "continuo_sostenido": {
        "nombre": "Fondo continuo sostenido",
        "entrena": ("durabilidad a ritmo medio-alto: sostener 1:24-1:30 sin parar; es el paso intermedio entre "
                    "el fondo facil y las series"),
        "no_entrena": "velocidad ni potencia",
        "recuperacion": 24,
        "papel400": "te ensena a nadar los 400 sin cortarte, a ritmo constante",
        "papel3000": "el motor de los primeros 2.000 m de la prueba",
        "senal": "ningun bloque continuo de mas de 1.200 m en las ultimas 2 semanas",
    },
    "series_largas": {
        "nombre": "Series largas (200-400 por repeticion)",
        "entrena": ("capacidad aerobica especifica: sostener ritmo de umbral con pausas cortas, que es la "
                    "manera mas directa de bajar el ritmo de 400 y de 1.000"),
        "no_entrena": "la punta de velocidad; no es una sesion para tocar techo de pulso",
        "recuperacion": 36,
        "papel400": "el pan del 400: reps de 200-400 a 1:20-1:26 con 30-45 s entrenan el ritmo de prueba",
        "papel3000": "el pan del 3.000: 3x1.000, 6x400, 2x1.500",
        "senal": "menos de 800 m por semana en repeticiones de 200 m o mas",
    },
    "series_medias": {
        "nombre": "Series medias (100-200 por repeticion)",
        "entrena": ("potencia aerobica y umbral: nadar a ritmo alto con pausas cortas; sube el techo de lo que "
                    "puedes sostener"),
        "no_entrena": "el aguante largo ni la velocidad maxima",
        "recuperacion": 30,
        "papel400": "6x200 a 1:19-1:21 con 40 s es el mejor entrenamiento para un 400",
        "papel3000": "10x200 a ritmo objetivo menos 2-4 s",
        "senal": "menos de 600 m por semana en repeticiones de 100-200 m",
    },
    "ritmo_prueba": {
        "nombre": "Ritmo de prueba con pausa corta",
        "entrena": ("tolerancia al lactato y confianza en el ritmo: nadar a TU ritmo de prueba con pausas de "
                    "20-30 s, que es como se nada un 400 (el pulso no se cae entre series)"),
        "no_entrena": "la base aerobica; sin fondo este trabajo se sostiene dos semanas y luego se estanca",
        "recuperacion": 36,
        "papel400": "el estimulo rey: 8x100 a 1:15 con 25-30 s, o 3 bloques de 4x100",
        "papel3000": "entra mas tarde, cuando el ritmo objetivo ya es comodo",
        "senal": "en 10 dias, nada a ritmo de prueba con descanso de 30 s o menos",
    },
    "velocidad_resistencia": {
        "nombre": "Velocidad con descanso largo",
        "entrena": ("mantener tecnica y potencia a velocidad alta con el cuerpo fresco: la reserva para el "
                    "ultimo 100 y para la salida"),
        "no_entrena": "el aguante; con 90 s de descanso no se entrena el pulso alto sostenido",
        "recuperacion": 24,
        "papel400": "8x50 a tope con 1:30 te da el cambio de ritmo del final",
        "papel3000": "velocidad de reserva: hacer que el ritmo de prueba parezca lento",
        "senal": "ningun bloque de 25-50 m rapido en las ultimas 2 semanas",
    },
    "pies": {
        "nombre": "Pataleo (pies)",
        "entrena": ("fuerza y propulsion de piernas: el viraje y el ultimo tramo de cada largo; en aguas "
                    "abiertas, el equilibrio"),
        "no_entrena": "el ritmo de brazo libre: un pataleo no se compara con una serie de nado completo",
        "recuperacion": 12,
        "papel400": "piernas para no perder el viraje cuando llegas justo",
        "papel3000": "menos peso que en el 400, pero ayuda a no arrastrar las piernas",
        "senal": "no hacer pies en 3 semanas",
    },
    "salida": {
        "nombre": "Salida con crono",
        "entrena": ("reaccion y los primeros metros: la salida, la entrada al agua y el primer ciclo; es "
                    "velocidad pura, sin aguante"),
        "no_entrena": "el fondo: la salida se decide en 7-10 s, no da pulso alto sostenido",
        "recuperacion": 24,
        "papel400": "una salida limpia y un primer 25 a tope son decimas que no cuestan entrenamiento",
        "papel3000": "sirve para el primer largo y para no perder el ritmo despues de cada viraje",
        "senal": "si hace mas de 3 semanas que no sales con crono",
    },
    "tecnica": {
        "nombre": "Tecnica",
        "entrena": "economia: hacer lo mismo gastando menos; es lo que sostiene los ultimos 100",
        "no_entrena": "nada de carga",
        "recuperacion": 0,
        "papel400": "cada brazada de mas en los ultimos 100 se paga en segundos",
        "papel3000": "la economia es medio 3.000",
        "senal": "nada; siempre suma",
    },
    "calentamiento": {
        "nombre": "Calentamiento y enfriamiento",
        "entrena": "poner el cuerpo a punto; no cuenta como carga",
        "no_entrena": "nada",
        "recuperacion": 0,
        "papel400": "obligatorio antes de cualquier serie rapida",
        "papel3000": "obligatorio",
        "senal": "",
    },
}

# De donde sabe cada clase de estimulo lo que dice: la seccion del anexo T que la sostiene, el grado de ese
# respaldo y lo que dentro de la clase sigue siendo criterio sin fuente (y por tanto lo tiene que firmar el
# entrenador). Se engancha a CLASES al cargar el modulo, para que cada clase pueda decir su procedencia (tareas
# V1.0-02 y V1.0-03 del anexo U) sin duplicar la tabla de arriba.
CONOCIMIENTO: dict[str, dict] = {
    "continuo_aerobico": {"seccion_T": ["T.2"], "grado": "metodo", "sin_fuente": ["recuperacion"]},
    "continuo_sostenido": {"seccion_T": ["T.2"], "grado": "metodo", "sin_fuente": ["recuperacion"]},
    "series_largas": {"seccion_T": ["T.2", "T.3"], "grado": "metodo", "sin_fuente": ["recuperacion"]},
    "series_medias": {"seccion_T": ["T.2"], "grado": "metodo", "sin_fuente": ["recuperacion"]},
    "ritmo_prueba": {"seccion_T": ["T.1", "T.2", "T.3"], "grado": "evidencia", "sin_fuente": ["recuperacion"]},
    "velocidad_resistencia": {"seccion_T": ["T.2", "T.3"], "grado": "evidencia", "sin_fuente": ["recuperacion"]},
    # Estas cuatro no estan en ninguna zona del anexo T: son criterio, y se declaran como tal.
    "calentamiento": {"seccion_T": [], "grado": "criterio", "sin_fuente": ["todo"]},
    "tecnica": {"seccion_T": [], "grado": "criterio", "sin_fuente": ["todo"]},
    "pies": {"seccion_T": [], "grado": "criterio", "sin_fuente": ["todo"]},
    "salida": {"seccion_T": [], "grado": "criterio", "sin_fuente": ["todo"]},
}

for _clase, _saber in CONOCIMIENTO.items():
    if _clase in CLASES:
        CLASES[_clase].update(_saber)

# Como ayuda el material. No cambia el sistema que se entrena, cambia el ritmo que se ve: por eso estos metros
# NUNCA cuentan como brazo libre (regla del anexo F, riesgo confirmado).
MATERIAL: dict[str, dict] = {
    "aletas": {"nombre": "aletas", "que_hace": "sube la velocidad y mejora la posicion; sirve para nadar rapido sin gastar",
               "ayuda_s100": 10.0, "ojo": "sus ritmos son los mas optimistas: no valen como referencia"},
    "palas": {"nombre": "palas", "que_hace": "fuerza de traccion: mas agua por brazada",
              "ayuda_s100": 6.0, "ojo": "cargan el hombro; no abuses con el hombro tocado"},
    "pull": {"nombre": "pull", "que_hace": "aisla la brazada y quita las piernas de la ecuacion",
             "ayuda_s100": 4.0, "ojo": "su ritmo no es el de nado completo"},
}

# ---------------------------------------------------------------------------
# 2. De que esta hecha una sesion
# ---------------------------------------------------------------------------


def _num(x, por_defecto=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return por_defecto


# Cuanto mas lento que su ritmo de prueba tiene que ir un bloque suelto para contarlo como calentamiento, en
# segundos por 100 m. Es criterio (T.8, "bandas de ritmo") y esta puesto donde se puede revisar: sale de sus
# propios partes del 12/10/2026, donde lo que el declara `cal` va a 107-167 s/100 y lo que declara AeLigero a
# 88,6. Con 25 (100 s/100 para el 400) no se toca su trabajo aerobico facil ni su AeLigero, y los bloques que
# el reloj deja sueltos y lentos (101-160 s/100) se cuentan como lo que son: calentamiento o suelta.
LENTO_SOBRE_OBJETIVO = 25.0


def clasificar(s: dict, objetivo_100: float | None = None) -> str:
    """De que clase es un grupo del parte (o un bloque del reloj).

    Mira tres cosas, por este orden: si es continuo o series, cuanto mide la repeticion y cuanto descansa. El
    ritmo solo desempata, y relativo al objetivo del atleta: no hay bandas absolutas que valgan para todos.

    Dos reglas que se aprendieron midiendo (arreglo del 17/10/2026):
      - Si el parte declara `cal`, es calentamiento aunque sea un tiron largo: lo declaro el atleta.
      - Un bloque suelto y corto del reloj (100-250 m) **no** es calentamiento por ser corto: es una repeticion,
        y el descanso que la separa de la siguiente el reloj no lo declara. Antes esto metia 12.600 m de
        "calentamiento" en una ventana de 28.925 m. Solo cuenta como calentamiento si ademas va lento (mas de
        20 s/100 por encima de su ritmo de prueba); sin ritmo no hay dato para afirmarlo.
    """
    metros = _num(s.get("metros"))
    n = int(_num(s.get("n_reps"), 1) or 1)
    rep = _num(s.get("rep_m")) or (metros / n if n else 0)
    desc = _num(s.get("descanso_s"), 0.0)
    intensidad = (s.get("intensidad") or "").strip().lower()
    ritmo = s.get("ritmo_100")
    ritmo = _num(ritmo) if ritmo else None
    obj = _num(objetivo_100, 75.0)

    if intensidad == "cal":
        return "calentamiento"
    if intensidad == "pies":
        return "pies"
    if intensidad == "salida":
        return "salida"
    if intensidad == "tecnica":
        return "tecnica"
    if metros <= 0:
        return "calentamiento"
    if n <= 1 and metros >= 600:
        return "continuo_sostenido" if (ritmo and ritmo <= obj + 15) else "continuo_aerobico"
    # Ojo: un bloque NO es continuo por sumar muchos metros (3x400 son 1.200 m y son series, no un continuo).
    # Por eso la rama de continuo exige una sola repeticion.
    if n >= 2:
        if rep <= 60:
            return "velocidad_resistencia" if desc >= 60 else "series_medias"
        if rep <= 200:
            if desc <= 30 and ritmo is not None and ritmo <= obj + 4:
                return "ritmo_prueba"
            return "series_medias"
        return "series_largas"
    # Suelto y corto (menos de 600 m sin series): es una repeticion o un tiron corto. Si el reloj no declara
    # intensidad y va lento, es calentamiento; si no, cuenta como serie media (es carga, no relleno).
    if not intensidad and desc == 0 and ritmo is not None and ritmo > obj + LENTO_SOBRE_OBJETIVO:
        return "calentamiento"
    return "series_medias"


def perfil(series: Iterable[dict], objetivo_100: float | None = None) -> dict:
    """De que esta hecha la sesion: metros por clase, y el bloque continuo mas largo.

    Se devuelve tambien `calidad_m` (metros que no son calentamiento ni tecnica) porque es el numero que importa
    para juzgar si una sesion entrena o solo llena metros.
    """
    por_clase: dict[str, float] = {}
    continuo_mas_largo = 0.0
    calidad_m = 0.0
    total = 0.0
    for s in series:
        metros = _num(s.get("metros"))
        if metros <= 0:
            continue
        c = clasificar(s, objetivo_100)
        por_clase[c] = por_clase.get(c, 0.0) + metros
        total += metros
        if c in ("continuo_aerobico", "continuo_sostenido"):
            continuo_mas_largo = max(continuo_mas_largo, metros)
        if c not in ("calentamiento", "tecnica"):
            calidad_m += metros
    # La clase que mas metros pone, sin contar las que no son carga.
    carga = {k: v for k, v in por_clase.items() if k not in ("calentamiento", "tecnica")}
    dominante = max(carga, key=carga.get) if carga else None
    return {"por_clase": por_clase, "dominante": dominante, "continuo_mas_largo": continuo_mas_largo,
            "calidad_m": calidad_m, "total_m": total}


# ---------------------------------------------------------------------------
# 3. Que falta y que toca
# ---------------------------------------------------------------------------
#
# Los deficits se miran sobre una ventana de 10-14 dias (no sobre un solo dia): una sesion suelta dice lo que
# has hecho hoy, la ventana dice de que estas hecho. Cada deficit: id, titulo, porque, y que mirar.

VENTANA_DIAS = 14
# Dias seguidos en el agua a partir de los cuales ya no es su semana normal (que tiene seis) y toca descargar.
DIAS_SIN_PARAR = 7.0
# El bloque continuo mas largo que se le pide a la ventana, en metros (regla R2 y aviso del propio motor).
MIN_CONTINUO_M = 1200.0
# El reparto objetivo por fase vive en `reglas` (REPARTO_OBJETIVO), que es donde lleva su fuente: el anexo F mas
# lo que dicen sus propios datos (regla R1). Aqui solo se guarda la ventana con la que se mide.


def _mil(metros: float) -> str:
    """Los metros con el punto de millar que se usa aqui: 1.000 m."""
    return f"{int(round(float(metros or 0))):,}".replace(",", ".")


def _titulo_de(clase: str) -> str:
    """El titulo del deficit, con el verbo en su numero: «falta ritmo de prueba», «faltan series largas»."""
    nombre = (CLASES.get(clase) or {}).get("nombre", clase).lower()
    nucleo = nombre.split("(")[0].strip()          # el nucleo sin el parentetico: «series largas»
    return f"{'faltan' if nucleo.endswith('s') else 'falta'} {nombre}"

# De clase de estimulo a receta. El fondo continuo tiene dos clases (facil y sostenido) y una sola receta: la
# sesion larga sin parar los cubre a los dos. Sin este mapa, un deficit de fondo sostenido pedia una receta que
# no existe (`RECETAS["continuo_sostenido"]`) y el discurso se quedaba sin sesion que proponer.
RECETA_DE_CLASE: dict[str, str] = {"continuo_aerobico": "continuo", "continuo_sostenido": "continuo"}


def deficits(hist: dict, fase: str = "especifico_400", dias_al_reto: int | None = None,
             objetivo_100: float | None = None, dias_al_agua: float = 0.0) -> list[dict]:
    """Que le falta al historico reciente, por orden de importancia.

    `hist` = perfil() de los ultimos ~14 dias (o el que salga de `perfil_de_ventana`).

    Devuelve **una entrada por clase de estimulo** (tarea V1.1-02). Antes salia una entrada por motivo, asi que el
    mismo hueco aparecia tres veces ("no hay ritmo de prueba", "no llegas al minimo de ritmo de prueba", "no hay
    ninguna repeticion corta y rapida") y el discurso parecia tener siete problemas donde hay cuatro. Cada entrada
    trae: `id` (la clase que falta), `titulo`, `porque` (el motivo principal, con sus numeros), `motivos` (todos
    los motivos), `receta` (la clave de `RECETAS` que lo arregla), `metros_actuales`, `metros_minimos`, `seccion_T`
    y `grado` (de donde sabe el motor que eso falta).
    """
    por = hist.get("por_clase") or {}
    calidad = _num(hist.get("calidad_m")) or 1.0
    grupos: dict[str, dict] = {}

    def pct(clase: str) -> float:
        return 100.0 * _num(por.get(clase)) / calidad

    def agrupa(clase: str, titulo: str, porque: str, receta: str | None = None, minimo: float | None = None,
               tipo: str = "porcentaje") -> None:
        """Suma un motivo a la clase que le corresponde: es lo que evita contar el mismo hueco tres veces."""
        g = grupos.get(clase)
        if g is None:
            g = grupos[clase] = {"id": clase, "titulo": titulo,
                                 "receta": receta or RECETA_DE_CLASE.get(clase, clase), "motivos": [],
                                 "metros_actuales": _num(por.get(clase)), "metros_minimos": None,
                                 "pct": round(pct(clase), 1)}
        g["motivos"].append({"tipo": tipo, "porque": porque})
        if minimo is not None:
            g["metros_minimos"] = max(g["metros_minimos"] or 0.0, float(minimo))

    quiere = reglas.reparto_objetivo(fase)
    for clase, minimo in quiere.items():
        if pct(clase) < minimo * 0.6:            # muy por debajo de lo que la fase pide
            agrupa(clase, _titulo_de(clase),
                   (f"en los ultimos {VENTANA_DIAS} dias, {pct(clase):.0f} % de tu trabajo de calidad fue "
                    f"de este tipo; la fase pide alrededor del {minimo:.0f} %"))

    # Minimos que no valen con un porcentaje (regla R2 del historial): o hay algo de esto o hay un hueco. En 186
    # semanas de historial, el ritmo de prueba con pausa corta es el 0,2 % y la velocidad el 0,0 %.
    for clase, metros_min in reglas.MINIMOS_OBLIGATORIOS.items():
        if _num(por.get(clase)) < metros_min:
            agrupa(clase, _titulo_de(clase),
                   (f"en la ventana hay {_mil(_num(por.get(clase)))} m de este trabajo y el minimo son "
                    f"{_mil(metros_min)} m; es el estimulo que menos aparece en todo tu historial"),
                   minimo=metros_min, tipo="minimo")

    # Ninguna repeticion rapida (25-50 m): la punta se pierde en tres semanas sin tocarla.
    if not por.get("velocidad_resistencia"):
        agrupa("velocidad_resistencia", "falta velocidad con descanso largo",
               "no hay ninguna repeticion corta y rapida en la ventana: es lo que te da el cambio del final",
               tipo="hueco")

    # Aguantar sin parar: si el bloque continuo mas largo es corto, el 400 se cae en el tercer 100. Va a la misma
    # clase que el fondo sostenido, con su propio motivo: es el mismo hueco visto desde otro sitio (el porcentaje
    # dice cuanto hay, el bloque dice cuanto aguanta de una tirada).
    continuo = _num(hist.get("continuo_mas_largo"))
    if continuo < MIN_CONTINUO_M:
        agrupa("continuo_sostenido", "falta fondo continuo sostenido",
               (f"tu bloque continuo mas largo de la ventana son {_mil(continuo)} m y el minimo son "
                f"{_mil(MIN_CONTINUO_M)} m: el 400 y el 3.000 se deciden en la cabeza de seguir sin parar"),
               receta="continuo", minimo=MIN_CONTINUO_M, tipo="bloque_continuo")

    # Cerca de la prueba manda otra cosa: afinar, no cargar. Solo se queda la punta, que no cuesta recuperar.
    especiales: list[dict] = []
    if dias_al_reto is not None and dias_al_reto <= 10:
        grupos = {k: v for k, v in grupos.items() if k == "velocidad_resistencia"}
        especiales.append({
            "id": "afinar", "titulo": "semana de afinado", "receta": "afinar", "metros_actuales": 0.0,
            "metros_minimos": None, "pct": 0.0, "motivos": [{"tipo": "regla",
                "porque": (f"quedan {dias_al_reto} dias: no se mete carga nueva, se baja volumen y se mantiene "
                           f"algo a ritmo de prueba")}]})

    # Sin un solo dia fuera del agua: primero se recupera. El umbral no puede ser cinco: la semana normal del
    # atleta tiene seis dias en el agua (lunes, miercoles y viernes con el entrenador; martes, jueves y domingo
    # propios; el sabado es bici), asi que a cinco saltaba todas las semanas y la descarga se comia el hueco de
    # la calidad. Siete dias seguidos ya no es su semana normal: es no haber parado.
    if dias_al_agua >= DIAS_SIN_PARAR:
        especiales.insert(0, {
            "id": "descarga", "titulo": "demasiados dias seguidos en el agua", "receta": "descarga",
            "metros_actuales": 0.0, "metros_minimos": None, "pct": 0.0, "motivos": [{"tipo": "regla",
                "porque": (f"llevas {dias_al_agua:.0f} dias seguidos sin un dia fuera del agua (tu semana normal "
                           f"son seis) y la adaptacion se hace descansando")}]})

    from . import conocimiento
    fuera: list[dict] = []
    for d in especiales + list(grupos.values()):
        f = conocimiento.fuente_de(d["id"])
        d["seccion_T"] = list(f.get("secciones") or [])
        d["grado"] = f.get("grado") or "criterio"
        d["porque"] = d["motivos"][0]["porque"]
        fuera.append(d)
    return fuera


# ---------------------------------------------------------------------------
# 4. Las recetas: la sesion, con numeros
# ---------------------------------------------------------------------------
#
# Cada receta es una plantilla: los ritmos se dan RELATIVOS al ritmo de prueba del atleta (`objetivo_100`), asi
# valen igual si el dia de la prueba sale a 1:15 o a 1:18. `desde` dice donde encaja en la semana: los lunes,
# miercoles y viernes son del entrenador personal y no se tocan (regla del plan).

RECETAS: dict[str, dict] = {
    "series_largas": {
        "nombre": "series largas a ritmo de umbral",
        # `metros` = lo que suma la sesion entera (calentamiento, serie y sueltos). No se escribe a mano a ojo: la
        # prueba `pruebas_metros_de_las_recetas` los vuelve a sumar desde el texto y compara (V1.2-02).
        "sesion": "500 suave + 4x50 progresivos | 3x400 con 45 s | 300 suaves",
        "metros": 2200,
        "reps": 3, "dist_m": 400, "rel_ritmo": (4, 8), "descanso_s": 45, "salida": None, "desde": "martes",
        "porque": ("es la manera mas directa de bajar el ritmo del 400: sostener 400 m seguidos con pausas cortas "
                   "ensena al cuerpo a nadar rapido cansado"),
    },
    "series_medias": {
        "nombre": "series medias a ritmo alto",
        "sesion": "400 suave + 200 tecnica | 6x200 con 40 s | 200 suaves",
        "metros": 2000,
        "reps": 6, "dist_m": 200, "rel_ritmo": (4, 6), "descanso_s": 40, "salida": None, "desde": "jueves",
        "porque": "sube el techo: mas metros a ritmo alto con pausa corta que en el 400 mismo",
    },
    "ritmo_prueba": {
        "nombre": "ritmo de prueba con pausa corta",
        "sesion": "500 suave + 4x50 progresivos | 8x100 con 25-30 s, salida cada 2:00 | 200 suaves",
        "metros": 1700,
        "reps": 8, "dist_m": 100, "rel_ritmo": (-1, 1), "descanso_s": 28, "salida": 120, "desde": "jueves",
        "porque": ("es el ritmo que vas a nadar el dia de la prueba, con el pulso arriba todo el rato: la pausa "
                   "corta es lo que hace que el cuerpo aprenda a aguantarlo"),
    },
    "velocidad_resistencia": {
        "nombre": "punta de velocidad",
        "sesion": "600 suave + 300 tecnica | 8x50 a tope con 1:30 de descanso | 300 suaves",
        "metros": 1600,
        "reps": 8, "dist_m": 50, "rel_ritmo": (-2, 0), "descanso_s": 90, "salida": None, "desde": "jueves",
        "porque": "la reserva de velocidad es lo que te deja cambiar de ritmo en los ultimos 100; se entrena fresco",
    },
    "continuo": {
        "nombre": "bloque largo continuo",
        "sesion": "400 suave + 200 tecnica | 2.500 continuos a 1:26-1:30 | 200 suaves",
        "metros": 3300,
        "reps": 1, "dist_m": 2500, "rel_ritmo": (11, 15), "descanso_s": None, "salida": None, "desde": "domingo",
        "porque": ("el domingo es para aguantar sin parar: es lo que sostiene el tercer 100 del 400 y el 3.000 "
                   "entero"),
    },
    "afinar": {
        "nombre": "afinado de la semana de la prueba",
        "sesion": ("martes: 6x200 a ritmo de prueba con 45 s (el ultimo dia duro) | jueves: 1.200-1.500 con 4x50 a "
                   "ritmo de prueba | sabado: la prueba"),
        # La semana de la prueba no es una sesion, son varios dias, asi que sus metros se declaran a mano: son los
        # del dia fuerte (martes, 6x200 con su calentamiento). Las demas recetas se comprueban sumando su texto.
        "metros": 1700,
        "reps": 4, "dist_m": 50, "rel_ritmo": (-1, 1), "descanso_s": 40, "salida": None, "desde": "martes",
        "porque": ("un 400 es una prueba de cuatro minutos: no pide taper largo. Ultimo dia duro 4-5 dias antes y "
                   "el jueves solo sensaciones"),
    },
    "descarga": {
        "nombre": "descarga",
        "sesion": "2.000-2.500 suaves, con 6x50 progresivos al final",
        "metros": 2300,
        "reps": 1, "dist_m": 2200, "rel_ritmo": (18, 25), "descanso_s": None, "salida": None, "desde": "cualquier dia",
        "porque": "el volumen de la semana no se sube si no se ha descansado la anterior; se baja un 25-30 %",
    },
}


def metros_de_sesion(texto: str) -> int:
    """Los metros que suman las series de una sesion escrita: "500 suave + 4x50 | 3x400 con 45 s | 300 suaves".

    Cuenta las series ("3x400") y los bloques rectos ("500 suave"), y lo que no son metros no lo cuenta: los
    descansos ("con 45 s"), el pulso y las salidas ("salida cada 2:00") no son metros. En un tramo con rango
    ("1.200-1.500") cuenta el de abajo, que es lo menos que se puede nadar.

    Existe para que los metros de cada receta (V1.2-02, para saber si la semana cabe en su volumen) no se escriban
    a mano: la prueba los vuelve a sumar con esto y compara.
    """
    total = 0.0
    for trozo in re.split(r"[|+]", texto or ""):
        t = trozo.strip()
        if not t:
            continue
        # Un bloque recto al principio del tramo ("500 suave", "2.000-2.500 suaves"): el de abajo si es un rango.
        m = re.match(r"^(\d{1,3}(?:\.\d{3})*)\s*(?:-\s*(\d{1,3}(?:\.\d{3})*))?\s+\D", t + " x")
        if m:
            total += float(m.group(1).replace(".", ""))
        for serie in re.finditer(r"(\d+)\s*[xX]\s*(\d{1,3}(?:\.\d{3})*)", t):
            total += int(serie.group(1)) * float(serie.group(2).replace(".", ""))
    return int(round(total))


def receta_libre(clave: str, objetivo_100: float = 75.0, material: list[str] | None = None) -> dict:
    """La receta con los ritmos ya puestos en el reloj del atleta (s/100), no en relativo.

    Devuelve tambien el `cada` de la serie (salida de una repeticion a la siguiente), que es como se canta en la
    piscina y como el atleta la ejecuta: es mas util que el descanso suelto.
    """
    r = RECETAS.get(clave)
    if not r:
        return {}
    bajo, alto = r["rel_ritmo"]
    desde = objetivo_100 + bajo
    hasta = objetivo_100 + alto
    cada = None
    if r.get("salida"):
        cada = float(r["salida"])
    elif r.get("descanso_s") and r.get("dist_m"):
        # cada = lo que tardas la repeticion + el descanso (con una estimacion honesta del ritmo medio)
        medio = (desde + hasta) / 2.0
        cada = medio * (r["dist_m"] / 100.0) + float(r["descanso_s"])
    return {**r, "ritmo_desde": round(desde, 1), "ritmo_hasta": round(hasta, 1),
            "cada_s": round(cada, 1) if cada else None, "material": list(material or [])}


def perfil_de_ventana(series_por_fecha: dict, desde: str, hasta: str, objetivo_100: float | None = None) -> dict:
    """El perfil juntando varios dias: `series_por_fecha` = {fecha: [series...]}.

    Es la ventana que usa `deficits`: una sesion dice lo de hoy, la ventana dice de que estas hecho.
    """
    juntas: list[dict] = []
    for fecha, series in (series_por_fecha or {}).items():
        if desde <= str(fecha) <= hasta:
            juntas.extend(series or [])
    return perfil(juntas, objetivo_100)


# --------------------------------------------------------------------------- de donde sabe cada clase


def fuente_de(clase: str) -> dict:
    """De donde sabe una clase de estimulo lo que dice (anexo T), con el detalle de `conocimiento.fuente_de`."""
    from . import conocimiento

    return conocimiento.fuente_de(clase)


def clases_sin_fuente() -> list[str]:
    """Las clases que hoy son criterio sin fuente externa: la lista para que la revise el entrenador."""
    return sorted(c for c, v in CLASES.items() if v.get("grado") == "criterio")
