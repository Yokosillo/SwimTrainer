"""Que FORMA tiene una serie: regular, progresiva, aflojando, en V, cambiando.

Aparte de la intensidad (AeL, AeI, ae2, ae3...), una serie tiene una forma: puede ir cada repeticion mas
rapida (progresiva), aflojar, mantenerse o mezclar. Eso **no hay que declararlo**: se mide de los tiempos
que ya trae el reloj. Aqui vive esa medida.

Lo importante es que los datos del reloj **no son exactos**: se equivoca con algun largo y los tiempos
bailan uno o dos segundos. Por eso el margen no es un numero inventado: sale de lo que ha aprendido
`aprendizaje.py` de sus propios partes (`margen()`), y una repeticion con el cronometro mal disparado se
puede marcar como mala para que no cuente.
"""

from __future__ import annotations

import statistics as st

CONCEPTOS = ("progresivo", "aflojando", "regular", "en_v", "cambiando", "mixto")

NOMBRE = {
    "progresivo": "Progresiva (cada repeticion mas rapida)",
    "aflojando": "Aflojando (cada repeticion mas lenta)",
    "regular": "Regular (todas al mismo ritmo)",
    "en_v": "Cambio de ritmo (rapida en el medio)",
    "cambiando": "Cambiando (fuerte-suave alternando)",
    "mixto": "Sin forma clara",
}

# Mientras no haya partes de los que aprender (o sean muy pocos), este es el margen: una repeticion cuenta
# como distinta de la anterior si se aparta mas de esto. Es en segundos por 100 m.
MARGEN_POR_DEFECTO = 1.0
MIN_REPS = 3            # con dos repeticiones no se puede hablar de una forma


def _limpio(v) -> float | None:
    """Un ritmo usable: numero, positivo y de un nadador humano (entre 40 y 400 s/100)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if 40.0 <= x <= 400.0 else None


def pendiente(ritmos: list[float]) -> float | None:
    """Cuanto cambia el ritmo de una repeticion a la siguiente (s/100 por repeticion).

    Con la mediana de las pendientes entre todos los pares (Theil-Sen): asi una repeticion suelta con el
    cronometro mal disparado **no** manda sobre la forma del bloque. Negativo = cada vez mas rapida.
    """
    xs = list(range(len(ritmos)))
    pares = [(ritmos[j] - ritmos[i]) / (j - i) for i in xs for j in xs if j > i]
    return round(st.median(pares), 2) if pares else None


def _pasos(ritmos: list[float], margen: float) -> list[int]:
    """-1 si esta repeticion es mas rapida que la anterior, +1 si mas lenta, 0 si dentro del margen."""
    pasos = []
    for i in range(1, len(ritmos)):
        d = ritmos[i] - ritmos[i - 1]
        pasos.append(0 if abs(d) <= margen else (-1 if d < 0 else 1))
    return pasos


def medir(ritmos, margen: float | None = None, malos=()) -> dict:
    """La forma de una serie a partir de los ritmos de sus repeticiones, en orden.

    `malos` son los indices que no valen (cronometro mal disparado, largo mal contado): se apartan sin
    romper la forma ni la cuenta de repeticiones.
    """
    margen = float(margen if margen is not None else MARGEN_POR_DEFECTO)
    utiles = [(i, _limpio(r)) for i, r in enumerate(list(ritmos))]
    utiles = [(i, r) for i, r in utiles if r is not None and i not in set(malos)]
    if len(utiles) < MIN_REPS:
        return {"concepto": None, "motivo": f"hacen falta al menos {MIN_REPS} repeticiones para ver la forma",
                "n_usadas": len(utiles), "margen_s_100": margen}

    vals = [r for _, r in utiles]
    pasos = _pasos(vals, margen)
    signos = {p for p in pasos}
    subidas = [p for p in pasos if p == -1]
    bajadas = [p for p in pasos if p == 1]

    concepto = "mixto"
    if not signos - {0}:
        concepto = "regular"
    elif not bajadas and subidas:
        concepto = "progresivo"
    elif not subidas and bajadas:
        concepto = "aflojando"
    else:
        sin_ceros = [p for p in pasos if p]
        # Dos tramos (acelera y luego afloja, o al reves) o un zigzag (fuerte-suave alternando). Si hay mas
        # de dos tramos y no alterna, no hay forma clara: no se inventa una.
        tramos = 1 + sum(1 for i in range(1, len(sin_ceros)) if sin_ceros[i] != sin_ceros[i - 1])
        if tramos == 2:
            concepto = "en_v"
        elif all(sin_ceros[i] != sin_ceros[i - 1] for i in range(1, len(sin_ceros))):
            concepto = "cambiando"

    # La repeticion que se sale de la tendencia (para decirlo, no para esconderlo). Solo tiene sentido cuando
    # la forma es una linea (regular, progresiva, aflojando): en un zigzag o en dos tramos no hay tendencia
    # contra la que comparar y marcar "fuera" seria inventarse un fallo.
    if concepto in ("progresivo", "aflojando", "regular"):
        tendencia = pendiente(vals)
        linea = [vals[0] + tendencia * i for i in range(len(vals))] if tendencia is not None else list(vals)
        residuos = [round(v - l, 2) for v, l in zip(vals, linea)]
        fuera = sorted(utiles[i][0] for i, r in enumerate(residuos) if abs(r) > max(2 * margen, 2.0))
    else:
        tendencia, residuos, fuera = pendiente(vals), [], []

    return {
        "concepto": concepto,
        "n_usadas": len(vals),
        "margen_s_100": round(margen, 2),
        "pasos": pasos,
        "pendiente_s_100_por_rep": tendencia,
        "ganancia_s_100": round(vals[0] - vals[-1], 2) if len(vals) > 1 else None,
        "ritmos": [round(v, 1) for v in vals],
        "residuos_s_100": residuos,
        "reps_fuera_de_la_tendencia": fuera,
    }


def nombre(clave: str | None) -> str:
    """Como se dice en castellano llano (vacio si no hay forma medida)."""
    return NOMBRE.get(clave or "", "")


def forma(evidencia: dict | None) -> str:
    """Una linea para el portal o el discurso: 'Progresiva: 6,8 s/100 mas rapida de la primera a la ultima'."""
    if not evidencia or not evidencia.get("concepto"):
        return ""
    texto = nombre(evidencia["concepto"]).split(" (")[0]
    g = evidencia.get("ganancia_s_100")
    if g is not None and abs(g) > float(evidencia.get("margen_s_100") or 0):
        como = "mas rapida" if g > 0 else "mas lenta"
        texto += f": {abs(g):.1f} s/100 {como} de la primera a la ultima".replace(".", ",")
    return texto
