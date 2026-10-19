#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""El anexo T como dato: que se sabe de natacion, de que seccion sale y quien lo ha revisado.

Aqui no hay ningun modelo. El saber vive escrito a mano en `informes/T_base_de_conocimiento.md`, con su fuente
citada al lado, y este modulo solo lo lee y lo pone a disposicion del motor. Tres piezas:

  1. `secciones()` - las secciones del anexo (T.0 a T.10) con su texto, los numeros de fuente que citan y si se
     declaran criterio sin fuente.
  2. `fuente_de(clave)` - de donde sale lo que el motor dice de una clase de estimulo (`ritmo_prueba`), de una
     regla (`R2`) o de una clave de conocimiento (`taper`). Si no tiene seccion, o la seccion se declara
     criterio, devuelve `criterio=True`.
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
from datetime import datetime

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
# Una linea del bloque `## Sources`: `[n] URL — Titulo`. La URL es el primer token (no lleva espacios);
# entre la URL y el titulo puede haber un parentetico con el DOI, asi que el separador se busca despues.
RE_SOURCE = re.compile(r"^\[(\d+)\]\s+(\S+)\s*(.*)$")
RE_TITULO_FUENTES = re.compile(r"^##\s+Sources\b", re.IGNORECASE)

# Secciones que no son saber de natacion sino como funciona el propio anexo. Sus frases marcadas no son
# afirmaciones que haya que respaldar ni revisar, asi que quedan fuera de las listas de trabajo.
# `T.10` es el cierre del anexo (que lee el motor y que no): tampoco es una afirmacion sobre natacion.
META: tuple[str, ...] = ("T.0", "T.9", "T.10")

# Solo estas personas firman. `asistente` puede revisar (y se ve que lo hizo) pero NO cuenta como firma:
# el sistema no se autofirma (INV-03 y D-05 del plan). La comparacion no distingue mayusculas.
FIRMANTES: tuple[str, ...] = ("entrenador", "atleta")


def _camino(ruta: str | None = None) -> str:
    return ruta or RUTA_ANEXO


def _leer_secciones(ruta: str | None = None) -> tuple[dict[str, dict], list[dict]]:
    """Lee el anexo una vez y devuelve (secciones, duplicados). No sobrescribe nada.

    Si un ID de seccion aparece dos veces, **se queda la primera** y el duplicado se anota en la lista
    que devuelve `duplicados()`. Antes el diccionario se sobrescribia en silencio y la segunda `T.9`
    (el cierre) se comia a "Como se mantiene esto" (defecto D-01).
    """
    camino = _camino(ruta)
    if not os.path.isfile(camino):
        return {}, []
    fuera: dict[str, dict] = {}
    duplicados: list[dict] = []
    actual: str | None = None
    with open(camino, encoding="utf-8") as f:
        for numero, linea in enumerate(f, start=1):
            linea = linea.rstrip("\n")
            m = RE_SECCION.match(linea)
            if m:
                sid = m.group(1)
                if sid in fuera:
                    duplicados.append({"id": sid, "titulo": m.group(2).strip(), "linea": numero})
                    actual = None          # el contenido del duplicado no se mezcla con el de la primera
                    continue
                actual = sid
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
    return fuera, duplicados


def secciones(ruta: str | None = None) -> dict[str, dict]:
    """Las secciones del anexo T, indexadas por id (la primera si hubiera un duplicado).

    Cada una sale como `{'id', 'titulo', 'texto', 'fuentes', 'criterio', 'criterios'}`: `fuentes` son los numeros
    entre corchetes que la seccion cita (`[1]`, `[2]`...). `criterio` es True solo si la seccion **entera** va sin
    fuente (todas sus afirmaciones son criterio); `criterios` lista las afirmaciones sueltas marcadas
    `[criterio]` dentro de una seccion que si tiene fuentes. El bloque de fuentes final se ignora.
    """
    return _leer_secciones(ruta)[0]


def duplicados(ruta: str | None = None) -> list[dict]:
    """Los IDs de seccion que aparecen mas de una vez, con la linea del duplicado.

    Es la comprobacion de D-01: un anexo sano devuelve `[]`. El validador lo trata como error.
    """
    return _leer_secciones(ruta)[1]


def seccion(sid: str, ruta: str | None = None) -> dict | None:
    """Una seccion concreta del anexo, o None si no existe."""
    return secciones(ruta).get(sid)


def fuente_de(clave: str, ruta: str | None = None) -> dict:
    """De donde sale lo que el motor dice de `clave`.

    `clave` puede ser una clase de estimulo (`ritmo_prueba`), una regla (`R2`) o una clave de conocimiento
    (`taper`). Devuelve las secciones del anexo que la sostienen, los numeros de fuente que citan, el grado
    (`evidencia`, `metodo`, `pactado`, `historial`, `criterio`) y lo que dentro de esa clase o regla sigue sin
    fuente. `criterio=True` significa que no hay saber externo detras (clave desconocida o seccion declarada
    criterio). Una clave desconocida sale como criterio: no se inventa respaldo.
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
        # `criterio` = no hay saber externo detras: o la clave no tiene seccion, o la seccion se declara
        # criterio (como T.9). Antes solo miraba lo primero y `como_se_mantiene` salia `False` aunque su
        # grado fuera `criterio`.
        "criterio": not secciones_clave or grado == "criterio",
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


def _leer_fuentes(ruta: str | None = None) -> tuple[dict[int, dict], list[dict]]:
    """Lee el bloque `## Sources` y devuelve (fuentes, duplicadas).

    `fuentes` se queda con la primera definicion de cada numero; `duplicadas` anota las repeticiones
    con su linea para que el validador las denuncie como error (R-04). El bloque termina en el
    siguiente titulo `## ` (el cierre T.10, por ejemplo).
    """
    camino = _camino(ruta)
    if not os.path.isfile(camino):
        return {}, []
    fuera: dict[int, dict] = {}
    duplicadas: list[dict] = []
    dentro = False
    actual: int | None = None
    with open(camino, encoding="utf-8") as f:
        for numero, linea in enumerate(f, start=1):
            linea = linea.rstrip("\n")
            if RE_TITULO_FUENTES.match(linea):
                dentro = True
                actual = None
                continue
            if not dentro:
                continue
            if linea.startswith("## "):       # el siguiente titulo cierra el bloque de fuentes
                break
            m = RE_SOURCE.match(linea.strip())
            if m:
                n = int(m.group(1))
                if n in fuera:                # duplicado: se queda la primera y se denuncia
                    duplicadas.append({"n": n, "linea": numero})
                    actual = None
                    continue
                resto = m.group(3) or ""
                # El titulo va detras del separador `—` (puede haber un `(doi ...)` antes).
                partes = re.split(r"\s*[—-]\s+", resto, maxsplit=1)
                titulo = partes[1] if len(partes) > 1 else resto
                titulo = re.sub(r"\s+", " ", titulo.replace("\\n", " ")).strip()
                fuera[n] = {"n": n, "url": m.group(2), "titulo": titulo, "citas": []}
                actual = n
                continue
            if actual is not None and linea.strip().startswith(">"):
                cita = linea.strip()[1:].strip()
                if len(cita) >= 2 and cita.startswith('"') and cita.endswith('"'):
                    cita = cita[1:-1]
                if cita:
                    fuera[actual]["citas"].append(cita)
    return fuera, duplicadas


def fuentes(ruta: str | None = None) -> dict[int, dict]:
    """El bloque `## Sources` del anexo, indexado por numero (primera definicion si hay duplicados).

    Cada fuente sale como `{'n', 'url', 'titulo', 'citas'}`. `citas` son las lineas `>` que van debajo
    (la cita literal, sin el `>` ni las comillas de fuera). No se confunde con
    `secciones(...)['fuentes']`, que son los numeros que **cita** cada seccion. Esto es el catalogo
    de lo que hay definido.
    """
    return _leer_fuentes(ruta)[0]


def fuentes_duplicadas(ruta: str | None = None) -> list[dict]:
    """Los numeros de fuente definidos mas de una vez en `## Sources`, con su linea (R-04)."""
    return _leer_fuentes(ruta)[1]


def sin_fuente(ruta: str | None = None, cn: sqlite3.Connection | None = None) -> list[dict]:
    """Las secciones que traen afirmaciones sin fuente (criterio) y que hay que firmar.

    Una seccion puede citar cuatro fuentes y tener dentro frases marcadas `[criterio]`. Se devuelven
    las secciones que tienen alguna (con su cuenta en `criterios`). Las secciones de metodo (T.0, T.9
    y T.10) quedan fuera: no son saber de natacion.

    Si se pasa `cn`, cada seccion lleva `estado_revision` (`firmada`, `revisada_por_asistente` o
    `sin_revisar`) y `firmada` (solo entrenador/atleta cuentan). Asi una revision del asistente no se
    disfraza de firma (R-03).
    """
    firmas = _firmas(cn) if cn is not None else {}
    fuera = []
    for s in secciones(ruta).values():
        if s["id"] in META or not s["criterios"]:
            continue
        fila = dict(s)
        if cn is not None:
            estado = estado_revision(firmas.get(s["id"]))
            fila["estado_revision"] = estado
            fila["firmada"] = estado == "firmada"
            fila["revisado_por"] = (firmas.get(s["id"]) or {}).get("revisado_por")
        fuera.append(fila)
    return fuera


# Una frase acaba en . ! o ? (puede llevar citas [n] pegadas) y sigue con mayuscula o signo de apertura.
# Partir por ahi evita arrastrar la frase anterior (que puede tener fuente) a un criterio.
_RE_FIN_FRASE = re.compile(r"(?<=[.!?])(?:\[\d+\])*\s+(?=[A-ZÁÉÍÓÚÑÜ¿¡])")


def _frases(texto: str) -> list[str]:
    return [x.strip() for x in _RE_FIN_FRASE.split(texto) if x.strip()]


def _clausulas_de_prosa(lineas: list[str]) -> list[str]:
    """Las frases con `[criterio]` de un bloque de prosa, partiendo por frases y por marca."""
    bloques: list[str] = []
    actual: list[str] = []
    for linea in lineas:
        if not linea.strip():
            if actual:
                bloques.append(" ".join(actual))
                actual = []
            continue
        actual.append(linea.strip())
    if actual:
        bloques.append(" ".join(actual))
    fuera: list[str] = []
    for parrafo in bloques:
        for frase in _frases(parrafo):
            if "[criterio]" not in frase:
                continue
            if frase.count("[criterio]") == 1:
                fuera.append(frase)
                continue
            partes = frase.split("[criterio]")
            for i in range(len(partes) - 1):
                trozo = partes[i]
                if i > 0:
                    # Quitar la coletilla de la marca anterior: desde el final de su frase.
                    trozo = re.split(r"(?<=[.!?])\s+", trozo, maxsplit=1)[-1]
                fuera.append(trozo)
    return fuera


def _criterios_de_seccion(s: dict) -> list[str]:
    """Las clausulas exactas con `[criterio]` de una seccion, en orden y sin solaparse.

    - En las tablas de T.8 se usa la primera columna (la afirmacion), no la fila entera.
    - En prosa se parte por frases (`.`/`!`/`?`) y se queda solo la frase que lleva el marcador.
    - Si una frase lleva dos marcas, se divide por marca: son dos criterios distintos.
    - Se deduplica por texto limpio.
    """
    fuera: list[str] = []
    prosa: list[str] = []
    for linea in s["texto"].splitlines():
        if linea.strip().startswith("|"):
            fuera.extend(_clausulas_de_prosa(prosa))
            prosa = []
            if "[criterio]" in linea:
                celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
                if celdas and celdas[0]:
                    fuera.append(celdas[0])
            continue
        prosa.append(linea)
    fuera.extend(_clausulas_de_prosa(prosa))
    limpio: list[str] = []
    vistos: set[str] = set()
    for x in fuera:
        x = _limpia(x).strip(" .;:")
        if x and x not in vistos:
            vistos.add(x)
            limpio.append(x)
    return limpio


def criterios(ruta: str | None = None, cn: sqlite3.Connection | None = None) -> list[dict]:
    """Las afirmaciones marcadas `[criterio]` que esperan firma, con su seccion y su estado.

    Es la lista de trabajo de verdad: una seccion puede tener cuatro fuentes y una frase sin respaldo
    dentro. Las secciones de metodo (T.0, T.9 y T.10) quedan fuera: no son afirmaciones sobre natacion.

    Cada marca `[criterio]` es un criterio: el anexo tiene 21 lineas marcadas, pero T.5 lleva dos
    marcas en la misma linea, asi que salen **22 clausulas** distintas. Antes se contaban lineas y
    salian 21; el plan usa ese numero historico, pero la lista no son 21 afirmaciones distintas (R-06).

    Si se pasa `cn`, cada fila lleva `estado` (`firmada`, `revisada_por_asistente` o `pendiente`) y
    `revisado_por`. Solo entrenador/atleta firman (R-03).
    """
    firmas = _firmas(cn) if cn is not None else {}
    fuera = []
    for s in secciones(ruta).values():
        if s["id"] in META:
            continue
        for afirmacion in _criterios_de_seccion(s):
            fila = {"seccion": s["id"], "afirmacion": afirmacion}
            if cn is not None:
                estado = estado_revision(firmas.get(s["id"]))
                fila["estado"] = "pendiente" if estado == "sin_revisar" else estado
                fila["revisado_por"] = (firmas.get(s["id"]) or {}).get("revisado_por")
            fuera.append(fila)
    return fuera


def criterios_markdown(filas: list[dict], fecha: str | None = None) -> str:
    """La lista de criterios como Markdown reproducible (R-10), con su estado y una nota de conteo."""
    fecha = fecha or datetime.now().astimezone().isoformat(timespec="seconds")
    lineas = [
        "# Criterios sin fuente pendientes de firma",
        "",
        f"- **Generado:** {fecha}",
        "- **Documento:** `informes/T_base_de_conocimiento.md` (anexo T)",
        "- **Como se genera:** `python -m entrenador.cli conocimiento --criterios --formato md`",
        f"- **Conteo:** {len(filas)} clausulas. El anexo tiene 21 lineas con marca `[criterio]`; T.5 "
        "lleva dos marcas en una linea, asi que salen 22 clausulas distintas (no son 21 afirmaciones).",
        "- **Firma:** solo cuentan `entrenador` y `atleta`. Una seccion revisada por `asistente` se "
        "muestra como revisada por asistente y **sigue pendiente de firma**.",
        "- **Que hacer:** leer cada frase y, o se convierte en cita (con su `[n]`), o se firma como "
        "criterio del entrenador, o se corrige/tira. Sin firma no puede motivar una recomendacion.",
        "",
        "| # | Seccion | Estado | Afirmacion |",
        "|---|---|---|---|",
    ]
    for i, x in enumerate(filas, 1):
        texto = str(x.get("afirmacion") or "").replace("|", "\\|").replace("\n", " ")
        lineas.append(f"| {i} | {x.get('seccion', '')} | {x.get('estado', 'pendiente')} | {texto} |")
    lineas.append("")
    return "\n".join(lineas)


def afirmaciones_sin_fuente(ruta: str | None = None) -> list[dict]:
    """Compatibilidad: el mismo listado que `criterios()` (nombre historico del modulo)."""
    return criterios(ruta)


def _resultado_validacion(camino: str, secs: dict, defs: dict, usadas: dict,
                          errores: list[dict], avisos: list[dict]) -> dict:
    return {
        "anexo": camino,
        "secciones": len(secs),
        "fuentes": len(defs),
        "citas_usadas": len(usadas),
        "errores": errores,
        "avisos": avisos,
        "ok": not errores,
    }


def validar(ruta: str | None = None) -> dict:
    """Valida el anexo: IDs de seccion, citas y fuentes del bloque `## Sources`.

    Devuelve `{'anexo', 'secciones', 'fuentes', 'citas_usadas', 'errores', 'avisos', 'ok'}`.
    Falla cerrado (R-02): si el anexo no existe, esta vacio o no tiene secciones `T.#`, devuelve
    `ok=False` con `anexo_ausente` / `anexo_vacio`. Un error invalida el documento (cita rota, ID de
    seccion duplicado o fuente duplicada); un aviso no (fuente definida y no citada, o fuente sin
    cita literal). El CLI devuelve 0 solo si `ok` y no hay errores.
    """
    camino = _camino(ruta)
    errores: list[dict] = []
    avisos: list[dict] = []

    if not os.path.isfile(camino):
        errores.append({"tipo": "anexo_ausente", "detalle": f"no existe {camino}"})
        return _resultado_validacion(camino, {}, {}, {}, errores, avisos)
    try:
        with open(camino, encoding="utf-8") as f:
            texto = f.read()
    except (OSError, UnicodeDecodeError) as exc:   # permisos, es un directorio, no es UTF-8...
        errores.append({"tipo": "anexo_ilegible", "detalle": f"{camino}: {exc}"})
        return _resultado_validacion(camino, {}, {}, {}, errores, avisos)
    if not texto.strip():
        errores.append({"tipo": "anexo_vacio", "detalle": f"{camino} esta vacio"})
        return _resultado_validacion(camino, {}, {}, {}, errores, avisos)

    secs = secciones(ruta)
    if not secs:
        errores.append({"tipo": "anexo_vacio", "detalle": f"{camino} no tiene secciones T.#"})
        return _resultado_validacion(camino, {}, {}, {}, errores, avisos)
    defs = fuentes(ruta)

    for d in duplicados(ruta):
        errores.append({"tipo": "seccion_duplicada",
                        "detalle": f"{d['id']} aparece otra vez en la linea {d['linea']}",
                        "id": d["id"]})
    for d in fuentes_duplicadas(ruta):
        errores.append({"tipo": "fuente_duplicada",
                        "detalle": f"[{d['n']}] esta definida otra vez en la linea {d['linea']}",
                        "fuente": d["n"]})

    usadas: dict[int, list[str]] = {}
    for sid, s in secs.items():
        for n in s["fuentes"]:
            usadas.setdefault(n, []).append(sid)

    for n in sorted(usadas):
        if n not in defs:
            errores.append({"tipo": "cita_rota",
                            "detalle": f"[{n}] se cita en {', '.join(usadas[n])} y no esta en Sources",
                            "fuente": n})
    for n in sorted(defs):
        if n not in usadas:
            avisos.append({"tipo": "fuente_huerfana",
                           "detalle": f"[{n}] esta en Sources y no se cita en ninguna seccion",
                           "fuente": n})
        if not defs[n]["citas"]:
            avisos.append({"tipo": "fuente_sin_cita",
                           "detalle": f"[{n}] no trae cita literal (linea \"> ...\")",
                           "fuente": n})

    return _resultado_validacion(camino, secs, defs, usadas, errores, avisos)


def _limpia(linea: str) -> str:
    """La frase sin la marca de criterio ni las comillas de codigo que la acompanan en el anexo."""
    frase = linea.replace("`[criterio]`", "").replace("[criterio]", "")
    frase = re.sub(r"[ \t]+([.,;:])", r"\1", frase)      # "proyecto ." -> "proyecto."
    frase = re.sub(r"[ \t]{2,}", " ", frase)
    return frase.strip().strip("`").strip()


def _firmas(cn: sqlite3.Connection) -> dict[str, dict]:
    """Las filas de `conocimiento_revision` por seccion (vacio si la tabla no existe todavia)."""
    try:
        return {r["seccion"]: dict(r) for r in
                cn.execute("SELECT seccion, revisado_por, revisado_en, notas FROM conocimiento_revision")}
    except sqlite3.OperationalError:
        return {}


def estado_revision(fila: dict | None) -> str:
    """`firmada` (entrenador/atleta), `revisada_por_asistente` o `sin_revisar` (R-03).

    Una revision del asistente no es una firma: el sistema no se autofirma (INV-03, D-05).
    """
    if not fila or not (fila.get("revisado_por") or "").strip():
        return "sin_revisar"
    if (fila.get("revisado_por") or "").strip().lower() in FIRMANTES:
        return "firmada"
    return "revisada_por_asistente"


def revision(cn: sqlite3.Connection, sid: str) -> dict | None:
    """La revision de una seccion (quien y cuando), o None si nadie la ha revisado."""
    f = cn.execute("SELECT seccion, revisado_por, revisado_en, notas FROM conocimiento_revision "
                   "WHERE seccion = ?", (sid,)).fetchone()
    return dict(f) if f else None


def marcar_revision(cn: sqlite3.Connection, sid: str, quien: str, notas: str = "") -> None:
    """Marca una seccion como revisada por alguien.

    Idempotente: la misma seccion se actualiza, no se duplica (por eso la clave primaria es la seccion).
    Si `quien` no es entrenador/atleta se guarda como revision del asistente y **no** cuenta como firma.
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
    """Las secciones **firmadas** por entrenador/atleta, por orden (R-03)."""
    return sorted(r[0] for r in cn.execute(
        "SELECT seccion, revisado_por FROM conocimiento_revision ORDER BY seccion")
        if (r[1] or "").strip().lower() in FIRMANTES)


def revisadas_por_asistente(cn: sqlite3.Connection) -> list[str]:
    """Las secciones revisadas por alguien que no firma (normalmente `asistente`), por orden."""
    return sorted(r[0] for r in cn.execute(
        "SELECT seccion, revisado_por FROM conocimiento_revision ORDER BY seccion")
        if (r[1] or "").strip() and (r[1] or "").strip().lower() not in FIRMANTES)


def cuadro_revision(cn: sqlite3.Connection, ruta: str | None = None) -> dict:
    """La firma del anexo T: que secciones hay, con que respaldo y quien las ha revisado (V1.3-01).

    Es lo que ensena el portal. Solo entrenador/atleta firman; una revision del asistente se muestra
    como tal y sigue pendiente de firma (R-03). Las secciones que van sin fuente se cuentan aparte,
    porque son criterio del entrenador y asi hay que decirlo.
    """
    firmas = _firmas(cn)
    lista = []
    for sid, s in secciones(ruta).items():
        f = firmas.get(sid) or {}
        estado = estado_revision(f)
        lista.append({
            "seccion": sid, "titulo": s.get("titulo"),
            "fuentes": list(s.get("fuentes") or []), "con_fuente": len(s.get("fuentes") or []),
            "criterio": bool(s.get("criterio")), "criterios": len(s.get("criterios") or []),
            "revisado_por": f.get("revisado_por"), "revisado_en": f.get("revisado_en"), "notas": f.get("notas"),
            "estado_revision": estado, "firmada": estado == "firmada",
        })
    crits = criterios(ruta)
    return {"anexo": RUTA_ANEXO, "total": len(lista),
            # Solo cuentan como revisadas las firmadas por entrenador/atleta.
            "revisadas": sum(1 for x in lista if x["firmada"]),
            "revisadas_por_asistente": sum(1 for x in lista
                                            if x["estado_revision"] == "revisada_por_asistente"),
            # Criterios sin firma, no secciones sin fuente: una seccion con fuentes puede tener dentro
            # frases `[criterio]`. Antes esto contaba secciones y el portal podia decir "todo con fuente".
            "sin_fuente": len(crits),
            "criterios_pendientes": len(crits),
            "secciones": lista}
