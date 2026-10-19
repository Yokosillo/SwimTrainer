#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Las reglas del entrenador, cada una con **de donde sale** y **como se comprueba**.

Esto es lo que separa un motor de reglas de un modelo de lenguaje: cada regla entra con su fuente (el historial
propio, los anexos F y L, el entrenador personal o el criterio del asistente) y con la forma de medir si acierta.
Si una regla no tiene fuente, no entra. Si con el tiempo no mejora nada, se revisa y se cambia aqui, no se tapa
con prosa.

Fuentes que existen hoy:
  * `anexo_F`  - la planificacion pactada (80/20, 70/30, 65/25/10, regla del 10 %, descarga cada 4.ª semana).
  * `anexo_L`  - el plan de los objetivos (400 y 3.000).
  * `historial` - ingenieria inversa de sus 186 semanas con datos (`scripts/ingenieria_inversa.py`,
                 informe `informes/M_ingenieria_inversa.md`, 15/10/2026).
  * `entrenador_personal` - lo que manda los lunes, miercoles y viernes. **Pendiente de registrar**: hoy no
                 hay ni una linea suya en la base, y son tres de los seis dias.

Uso:
    from . import reglas
    reglas.REGLAS                       # todas, con su fuente
    reglas.reparto_objetivo("especifico_400")   # el reparto de clases que pide la fase
"""

from __future__ import annotations

FUENTES: dict[str, dict] = {
    "anexo_F": {"que": "Propuesta de planificacion (anexos F del 11/10/2026)",
                "fiabilidad": "alta: esta pactada con el atleta"},
    "anexo_L": {"que": "Plan del 400 y del 3.000 (anexo L del 11/10/2026)",
                "fiabilidad": "alta: esta pactada con el atleta"},
    "historial": {"que": "Ingenieria inversa de sus 186 semanas con datos (15/10/2026)",
                  "fiabilidad": ("media: sus propios datos, pero correlacion no es causa. Manda cuando "
                                 "coincide con el anexo F")},
    "entrenador_personal": {"que": "Lo que manda su entrenador los lunes, miercoles y viernes",
                            "fiabilidad": "alta cuando exista; hoy NO hay datos"},
    "asistente": {"que": "Criterio del asistente",
                  "fiabilidad": "baja: solo se admite si no contradice a las anteriores y se marca como tal"},
}

# ---------------------------------------------------------------------------
# Las reglas
# ---------------------------------------------------------------------------
#
# Cada regla: `id`, `enunciado` (lo que se aplica), `fuente`, y `se_comprueba` (como se mide si acierta). Las
# reglas numeradas R1.. salen del historial: son las que dan a la valoracion algo que decir que el atleta no
# pueda leer ya en sus tiempos.

# DEPRECATED (F3): la fuente nueva es conocimiento/local/reglas.toml (o la publica de ejemplo).
REGLAS: list[dict] = [
    {
        "id": "R1",
        "enunciado": ("Lo que distingue sus buenas semanas no es descansar menos ni hacer mas series largas: es "
                      "**menos metros faciles y mas series medias**. Comparando semanas del mismo tamano "
                      "(5-11 km), las buenas metieron 47,4 % de su calidad en series de 100-200 m y solo 14,2 % "
                      "en fondo facil; las malas, 43,0 % y 21,9 %. El fondo sostenido tambien pesa algo mas "
                      "(4,8 % contra 1,9 %)."),
        "fuente": "historial",
        "se_comprueba": ("subir la cuota de series medias y bajar el fondo facil debe bajar el ritmo mediano de "
                         "la calidad; si a las 3 semanas no baja, la regla no vale para el"),
    },
    {
        "id": "R1b",
        "enunciado": ("Sus bloques continuos son cortos: la mediana del bloque mas largo de la semana es ~725 m, "
                      "y **no** distingue las buenas de las malas (750 m en las peores). Es decir: el bloque "
                      "largo continuo (2.000-2.500 m) es un estimulo que practicamente **no aparece** en su "
                      "historial, y es justo lo que piden el 400 (tercer 100) y el 3.000 entero."),
        "fuente": "historial",
        "se_comprueba": "el domingo de bloque continuo largo debe notarse en el ritmo sostenido de la semana",
    },
    {
        "id": "R2",
        "enunciado": ("**Nunca ha entrenado ritmo de prueba con pausa corta ni velocidad maxima**: en 186 semanas "
                      "de historial, el trabajo a ritmo de 400 con menos de 30 s de descanso es el 0,2 % y la "
                      "velocidad con descanso largo es el 0,0 %. Es el hueco estructural de toda su carrera "
                      "registrada y el principal sospechoso de que su 400 se quede en 5:00-5:11."),
        "fuente": "historial",
        "se_comprueba": ("introducir 8x100 a ritmo de prueba con 25-30 s y 8x50 a tope; el 400 objetivo y el "
                         "ritmo de sus series de 100 deben acusarlo"),
    },
    {
        "id": "R3",
        "enunciado": ("El descanso no es su palanca: las semanas buenas tienen la misma densidad de nado que las "
                      "malas (0,51 las dos). Recortar descansos por sistema no es lo que le ha hecho mejorar "
                      "nunca. Lo que cambia el ritmo es **cuanto** trabajo sostenido mete, no cuantas pausas "
                      "quita."),
        "fuente": "historial",
        "se_comprueba": ("no proponer descansos mas cortos como receta principal; si se recortan, que sea dentro "
                         "de la receta de ritmo de prueba, no como norma general"),
    },
    {
        "id": "R4",
        "enunciado": ("Sus series largas (200-400) estan igual de presentes en las buenas y en las malas semanas "
                      "(33,5 % contra 33,2 %): no son el problema. El problema esta en el fondo facil que sobra, "
                      "en el bloque largo continuo que no aparece y en la punta que no entrena."),
        "fuente": "historial",
        "se_comprueba": "no recetar mas series largas 'por si acaso'; ya las hace",
    },
    {
        "id": "R5",
        "enunciado": ("El volumen semanal no sube mas de un 10 %, y cada cuarta semana baja un 25-30 %. Si una "
                      "semana no se completa el 80 % de lo previsto, la siguiente repite volumen en vez de subir."),
        "fuente": "anexo_F",
        "se_comprueba": "historial de km semanales antes y despues de cada subida",
    },
    {
        "id": "R6",
        "enunciado": ("Los lunes, miercoles y viernes son del entrenador: no se les anade nada. Las sesiones "
                      "propias caen en **martes, jueves y domingo**."),
        "fuente": "anexo_L",
        "se_comprueba": "las sesiones que propone el motor tienen que caer en esos tres dias",
    },
    {
        "id": "R7",
        "enunciado": ("Una prueba de 400 m no pide taper largo: ultimo dia duro 4-5 dias antes, y el jueves de la "
                      "semana de la prueba solo sensaciones (1.200-1.500 m con 4x50 a ritmo de prueba)."),
        "fuente": "anexo_L",
        "se_comprueba": "como sale el 400 objetivo y como se siente en el ultimo dia duro",
    },
    {
        "id": "R8",
        "enunciado": ("El material (aletas, palas, pull) sube el ritmo sin que el atleta nade mejor: sus ritmos "
                      "con material **no cuentan** como referencia a brazo libre. Ya paso: un 400 citado como de "
                      "brazo libre que en realidad era con aletas."),
        "fuente": "anexo_F",
        "se_comprueba": "la valoracion descuenta el material declarado (~10 s/100 aletas, ~6 palas, ~4 pull)",
    },
]

# ---------------------------------------------------------------------------
# De donde sabe cada regla lo que dice (tarea V1.0-03 del anexo U)
# ---------------------------------------------------------------------------
#
# Cada regla declara su **grado** de respaldo, las secciones del anexo T que la sostienen y lo que dentro de ella
# sigue sin fuente:
#   * `evidencia` - estudio revisado, con cita literal en el anexo T (poca cosa: el 200/400 y el lactato).
#   * `metodo`    - manual o escuela con nombre: vale para "como se hace" (zonas, descansos, material).
#   * `pactado`   - lo acordado con el atleta (anexos F y L): manda, pero no es saber de fuera.
#   * `historial` - sale de sus propios datos: calibra, no demuestra. Fiabilidad media.
#   * `criterio`  - criterio sin fuente. Se puede usar, pero se dice.
#
# Que una regla sea `historial` no la hace floja: significa que su respaldo son 186 semanas de datos del atleta,
# no un paper de nadadores de elite. Lo que no se puede es contarlo como si fuera evidencia.

GRADOS: tuple[str, ...] = ("evidencia", "metodo", "pactado", "historial", "criterio")

# DEPRECATED (F3): la metadata de cada regla va en el TOML; se conserva para v1/dual.
CONOCIMIENTO: dict[str, dict] = {
    "R1": {"grado": "historial", "seccion_t": [], "sin_fuente": []},
    "R1b": {"grado": "historial", "seccion_t": ["T.2"], "sin_fuente": []},
    "R2": {"grado": "historial", "seccion_t": ["T.1", "T.3"], "sin_fuente": ["recuperacion"]},
    "R3": {"grado": "historial", "seccion_t": [], "sin_fuente": []},
    "R4": {"grado": "historial", "seccion_t": [], "sin_fuente": []},
    "R5": {"grado": "pactado", "seccion_t": [], "sin_fuente": ["descarga_cada_cuarta_semana"]},
    "R6": {"grado": "pactado", "seccion_t": [], "sin_fuente": []},
    "R7": {"grado": "pactado", "seccion_t": ["T.5"], "sin_fuente": ["ultimo_dia_duro"]},
    "R8": {"grado": "metodo", "seccion_t": ["T.2"], "sin_fuente": ["descuentos_por_material"]},
}

for _regla in REGLAS:
    # Una regla nueva sin ficha de conocimiento no se cuela como respaldada: sale como criterio a revisar.
    _regla.update(CONOCIMIENTO.get(_regla["id"], {"grado": "criterio", "seccion_t": [], "sin_fuente": ["todo"]}))

# ---------------------------------------------------------------------------
# El reparto de clases que pide cada fase (revisado con lo que dicen los datos)
# ---------------------------------------------------------------------------
#
# El anexo F da porcentajes por intensidad (80/20, 70/30, 65/25/10). Aqui se traducen a clases de `estimulos` y,
# para la fase del 400, se sube el peso del continuo sostenido por R1 (es lo que separa sus buenas semanas).
# La punta y el ritmo de prueba entran como minimo obligatorio por R2: no son porcentaje, son "algo o nada".

# DEPRECATED (F3): la fuente nueva es [reparto_objetivo] en conocimiento/local/reglas.toml.
REPARTO_OBJETIVO: dict[str, dict[str, float]] = {
    "base": {"continuo_aerobico": 55, "continuo_sostenido": 20, "series_largas": 15, "series_medias": 10},
    "especifico_400": {"continuo_sostenido": 20, "series_largas": 25, "series_medias": 35,
                       "ritmo_prueba": 10, "velocidad_resistencia": 10},
    "umbral_3000": {"continuo_sostenido": 25, "series_largas": 30, "series_medias": 35, "ritmo_prueba": 10},
}

# Clases que no valen con un porcentaje: o hay algo en la ventana o hay un hueco (regla R2).
# DEPRECATED (F3): la fuente nueva es [minimos_obligatorios] en conocimiento/local/reglas.toml.
MINIMOS_OBLIGATORIOS: dict[str, float] = {
    "ritmo_prueba": 400.0,          # metros en la ventana de 14 dias
    "velocidad_resistencia": 300.0,
}


def reparto_objetivo(fase: str = "especifico_400") -> dict[str, float]:
    return REPARTO_OBJETIVO.get(fase) or REPARTO_OBJETIVO.get("especifico_400") or {}


def cita(regla_id: str) -> str:
    """El texto de una regla con su fuente, para poder decirlo en el discurso sin inventarse nada."""
    for r in REGLAS:
        if r["id"] == regla_id:
            return r["enunciado"]
    return ""


def por_fuente(fuente: str) -> list[dict]:
    return [r for r in REGLAS if r["fuente"] == fuente]


# --------------------------------------------------------------------------- de donde sabe cada regla


def fuente_de(regla_id: str) -> dict:
    """De donde sabe una regla lo que dice, con el detalle de `conocimiento.fuente_de` (anexo T)."""
    from . import conocimiento

    return conocimiento.fuente_de(regla_id)


def sin_conocimiento() -> list[dict]:
    """Las reglas que **no** se apoyan en saber de fuera (anexo T): salen de sus datos o de lo pactado.

    No es una lista de reglas malas: es la lista de las que no pueden citar un documento, y por eso se comprueban
    contra el historial y se revisan con el entrenador.
    """
    return [r for r in REGLAS if r.get("grado") not in ("evidencia", "metodo")]



# --------------------------------------------------------------------------- adaptador F3
def _aplicar_motor_conocimiento() -> None:
    from . import motor_conocimiento
    from .conocimiento import motor_version

    modo = motor_version()
    if modo not in ("v2", "dual"):
        return
    datos = motor_conocimiento.datos(motor_conocimiento.cargar())
    nuevo = {"reglas": datos["reglas"], "reparto": datos["reparto"], "minimos": datos["minimos"]}
    if modo == "v2":
        global REGLAS, REPARTO_OBJETIVO, MINIMOS_OBLIGATORIOS
        REGLAS = nuevo["reglas"]
        REPARTO_OBJETIVO = nuevo["reparto"]
        MINIMOS_OBLIGATORIOS = nuevo["minimos"]
    else:
        motor_conocimiento.registrar_dual("reglas", {
            "reglas": REGLAS, "reparto": REPARTO_OBJETIVO, "minimos": MINIMOS_OBLIGATORIOS,
        }, nuevo)


_aplicar_motor_conocimiento()
