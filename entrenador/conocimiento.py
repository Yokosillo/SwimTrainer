#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""El anexo T como dato: que se sabe de natacion, de que seccion sale y quien lo ha revisado.

Aqui no hay ningun modelo. El saber vive escrito a mano en `informes/T_base_de_conocimiento.md`, con su fuente
citada al lado, y este modulo solo lo lee y lo pone a disposicion del motor. Tres piezas:

  1. `secciones()` - las secciones del anexo (T.0 a T.9) con su texto, los numeros de fuente que citan y si se
     declaran criterio sin fuente.
  2. `fuente_de(clave)` - de donde sale lo que el motor dice de una clase de estimulo (`ritmo_prueba`), de una
     regla (`R2`) o de una clave de conocimiento (`taper`). Si no tiene seccion, devuelve `criterio=True`.
  3. `revision` / `marcar_revision` - quien ha revisado cada seccion y cuando. Una seccion firmada por el
     entrenador pesa mas que cualquier fuente: es el unico saber que no viene de un documento.

Regla que manda: si una afirmacion no tiene seccion en el anexo, este modulo **no la inventa**, la declara
criterio. Y eso se ve en el portal, para que nadie confunda "esta escrito" con "esta respaldado".

Uso:
    from . import conocimiento
    conocimiento.fuente_de("ritmo_prueba")
    # {'clave': 'ritmo_prueba', 'secciones': ['T.1', 'T.2', 'T.3'], 'fuentes': [1, 2, 3],
    #  'grado': 'evidencia', 'criterio': False, 'sin_fuente': ['recuperacion'], ...}
"""

from __future__ import annotations

import os
import re
import sqlite3

# El anexo vive en el proyecto. La ruta se puede cambiar (pruebas, otro idioma, otro documento) sin tocar codigo.
RUTA_ANEXO = os.path.join("informes", "T_base_de_conocimiento.md")

# Version del motor de conocimiento. Se lee del entorno en ESTE unico sitio: el resto del codigo pregunta
# por `motor_version()` y nunca por la variable. Hoy solo existe `v1` (el motor actual); `v2` se activara
# en F5. La bandera no cambia ningun comportamiento todavia (F0-04): deja preparada la vuelta atras.
MOTOR_POR_DEFECTO = "v1"
MOTORES = ("v1", "v2")


def motor_version() -> str:
    """La version del motor de conocimiento activa (`MOTOR_CONOCIMIENTO=v1|v2`).

    Un valor desconocido o vacio cae a `v1`: la bandera no puede dejar el sistema sin motor. Es el unico
    punto donde se lee la variable de entorno (INV-08 del plan).
    """
    valor = (os.environ.get("MOTOR_CONOCIMIENTO") or "").strip().lower()
    return valor if valor in MOTORES else MOTOR_POR_DEFECTO

# Claves de conocimiento que no son ni una clase ni una regla del motor: se citan por su nombre.
CLAVES: dict[str, str] = {
    "que_pide_cada_prueba": "T.1",
    "zonas_y_descansos": "T.2",
    "series_cortas_vs_largas": "T.3",
    "recuperacion_entre_sesiones": "T.4",
    "taper": "T.5",
    "banda_de_ritmo": "T.6",
    "fuerza_y_hombro": "T.7",
    "sin_fuente": "T.8",
    "como_se_mantiene": "T.9",
}

RE_SECCION = re.compile(r"^##\s+(T\.\d+)\b\s*(.*)$")
RE_FUENTE = re.compile(r"\[(\d+)\]")

# Secciones que no son saber de natacion sino como funciona el propio anexo. Sus frases marcadas no son
# afirmaciones que haya que respaldar ni revisar, asi que quedan fuera de las listas de trabajo.
META: tuple[str, ...] = ("T.0", "T.9")


def _camino(ruta: str | None = None) -> str:
    return ruta or RUTA_ANEXO


def secciones(ruta: str | None = None) -> dict[str, dict]:
    """Las secciones del anexo T, indexadas por id.

    Cada una sale como `{'id', 'titulo', 'texto', 'fuentes', 'criterio', 'criterios'}`: `fuentes` son los numeros
    entre corchetes que la seccion cita (`[1]`, `[2]`...). `criterio` es True solo si la seccion **entera** va sin
    fuente (todas sus afirmaciones son criterio); `criterios` lista las afirmaciones sueltas marcadas
    `[criterio]` dentro de una seccion que si tiene fuentes. El bloque de fuentes final se ignora.
    """
    camino = _camino(ruta)
    if not os.path.isfile(camino):
        return {}
    fuera: dict[str, dict] = {}
    actual: str | None = None
    with open(camino, encoding="utf-8") as f:
        for linea in f:
            linea = linea.rstrip("\n")
            m = RE_SECCION.match(linea)
            if m:
                actual = m.group(1)
                fuera[actual] = {"id": actual, "titulo": m.group(2).strip(), "texto": [],
                                 "fuentes": set(), "criterios": [], "con_criterio": False}
                continue
            if linea.startswith("## "):       # cualquier otro titulo cierra el anexo (el bloque de fuentes)
                actual = None
                continue
            if actual is None:
                continue
            fuera[actual]["texto"].append(linea)
            for n in RE_FUENTE.findall(linea):
                fuera[actual]["fuentes"].add(int(n))
            if "[criterio]" in linea:
                fuera[actual]["con_criterio"] = True
                fuera[actual]["criterios"].append(linea.strip())
    for s in fuera.values():
        s["texto"] = "\n".join(s["texto"]).strip()
        s["fuentes"] = sorted(s["fuentes"])
        # Criterio de verdad: afirmaciones marcadas y ninguna fuente en toda la seccion (asi T.8 sale criterio y
        # T.1, que cita cuatro fuentes y tiene una afirmacion marcada, no se tacha entera).
        s["criterio"] = bool(s["criterios"]) and not s["fuentes"]
    return fuera


def seccion(sid: str, ruta: str | None = None) -> dict | None:
    """Una seccion concreta del anexo, o None si no existe."""
    return secciones(ruta).get(sid)


def fuente_de(clave: str, ruta: str | None = None) -> dict:
    """De donde sale lo que el motor dice de `clave`.

    `clave` puede ser una clase de estimulo (`ritmo_prueba`), una regla (`R2`) o una clave de conocimiento
    (`taper`). Devuelve las secciones del anexo que la sostienen, los numeros de fuente que citan, el grado
    (`evidencia`, `metodo`, `pactado`, `historial`, `criterio`) y lo que dentro de esa clase o regla sigue sin
    fuente. Una clave desconocida sale como criterio: no se inventa respaldo.
    """
    from . import estimulos, reglas

    secs = secciones(ruta)
    secciones_clave: list[str] = []
    grado = "criterio"
    sin_fuente: list[str] = []
    origen = ""

    clase = estimulos.CLASES.get(clave)
    if clase:
        secciones_clave = list(clase.get("seccion_T") or [])
        grado = clase.get("grado") or "criterio"
        sin_fuente = list(clase.get("sin_fuente") or [])
        origen = "estimulos.CLASES"
    else:
        regla = next((r for r in reglas.REGLAS if r["id"] == clave), None)
        if regla:
            secciones_clave = list(regla.get("seccion_t") or [])
            grado = regla.get("grado") or "criterio"
            sin_fuente = list(regla.get("sin_fuente") or [])
            origen = f"reglas.REGLAS ({regla.get('fuente') or 'sin fuente declarada'})"
        elif clave in CLAVES:
            secciones_clave = [CLAVES[clave]]
            grado = "criterio" if (secs.get(CLAVES[clave]) or {}).get("criterio") else "evidencia"
            origen = "conocimiento.CLAVES"

    fuentes = sorted({n for s in secciones_clave for n in (secs.get(s, {}).get("fuentes") or [])})
    return {
        "clave": clave,
        "secciones": secciones_clave,
        "fuentes": fuentes,
        "grado": grado,
        "criterio": not secciones_clave,
        "sin_fuente": sin_fuente,
        "origen": origen,
        "frase": _frase(secciones_clave, grado, sin_fuente),
    }


def _frase(secciones_clave: list[str], grado: str, sin_fuente: list[str]) -> str:
    """Como se cuenta esto en el discurso, sin adornos."""
    if not secciones_clave:
        base = "sin fuente: criterio a revisar"
    elif grado == "evidencia":
        base = f"con evidencia: anexo {' y '.join(secciones_clave)}"
    elif grado == "metodo":
        base = f"por metodo de entrenamiento: anexo {' y '.join(secciones_clave)}"
    elif grado == "pactado":
        base = f"pactado con el atleta: anexo {' y '.join(secciones_clave)}"
    elif grado == "historial":
        base = f"por tus propios datos, con {' y '.join(secciones_clave)} al lado"
    else:
        base = "criterio"
    if sin_fuente:
        base += f" (sin fuente: {', '.join(sin_fuente)})"
    return base


def sin_fuente(ruta: str | None = None) -> list[dict]:
    """Las secciones de saber que se declaran criterio entero: la lista para que la firme el entrenador."""
    return [s for s in secciones(ruta).values() if s["criterio"] and s["id"] not in META]


def afirmaciones_sin_fuente(ruta: str | None = None) -> list[dict]:
    """Las afirmaciones sueltas que el anexo declara criterio, con la seccion a la que pertenecen.

    Es la lista de trabajo de verdad: una seccion puede tener cuatro fuentes y una frase sin respaldo dentro. Las
    secciones de metodo (T.0 y T.9) quedan fuera: no son afirmaciones sobre natacion.
    """
    fuera = []
    for s in secciones(ruta).values():
        if s["id"] in META:
            continue
        for linea in s["criterios"]:
            fuera.append({"seccion": s["id"], "afirmacion": _limpia(linea)})
    return fuera


def _limpia(linea: str) -> str:
    """La frase sin la marca de criterio ni las comillas de codigo que la acompanan en el anexo."""
    return linea.replace("`[criterio]`", "").replace("[criterio]", "").strip().strip("`").strip()


def revision(cn: sqlite3.Connection, sid: str) -> dict | None:
    """La revision de una seccion (quien y cuando), o None si nadie la ha revisado."""
    f = cn.execute("SELECT seccion, revisado_por, revisado_en, notas FROM conocimiento_revision "
                   "WHERE seccion = ?", (sid,)).fetchone()
    return dict(f) if f else None


def marcar_revision(cn: sqlite3.Connection, sid: str, quien: str, notas: str = "") -> None:
    """Marca una seccion como revisada por alguien.

    Idempotente: la misma seccion se actualiza, no se duplica (por eso la clave primaria es la seccion).
    """
    from . import db

    cn.execute(
        """INSERT INTO conocimiento_revision (seccion, revisado_por, revisado_en, notas)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(seccion) DO UPDATE SET
               revisado_por = excluded.revisado_por,
               revisado_en  = excluded.revisado_en,
               notas        = excluded.notas""",
        (sid, quien, db.ahora(), notas))
    cn.commit()


def revisadas(cn: sqlite3.Connection) -> list[str]:
    """Las secciones que ya tienen revision, por orden."""
    return [r[0] for r in cn.execute("SELECT seccion FROM conocimiento_revision ORDER BY seccion")]


def cuadro_revision(cn: sqlite3.Connection, ruta: str | None = None) -> dict:
    """La firma del anexo T: que secciones hay, con que respaldo y quien las ha revisado (V1.3-01).

    Es lo que enseña el portal. Sin firma no se pone "revisado": se pone sin revisar. Las secciones que van sin
    fuente se cuentan aparte, porque son criterio del entrenador y asi hay que decirlo.
    """
    try:
        firmas = {r["seccion"]: dict(r) for r in
                  cn.execute("SELECT seccion, revisado_por, revisado_en, notas FROM conocimiento_revision")}
    except sqlite3.OperationalError:      # base sin migrar todavia: el anexo se lee igual, sin firmas
        firmas = {}
    lista = []
    for sid, s in secciones(ruta).items():
        f = firmas.get(sid) or {}
        lista.append({
            "seccion": sid, "titulo": s.get("titulo"),
            "fuentes": list(s.get("fuentes") or []), "con_fuente": len(s.get("fuentes") or []),
            "criterio": bool(s.get("criterio")), "criterios": len(s.get("criterios") or []),
            "revisado_por": f.get("revisado_por"), "revisado_en": f.get("revisado_en"), "notas": f.get("notas"),
        })
    return {"anexo": RUTA_ANEXO, "total": len(lista),
            "revisadas": sum(1 for x in lista if x["revisado_por"]),
            "sin_fuente": sum(1 for x in lista if not x["con_fuente"]),
            "secciones": lista}
