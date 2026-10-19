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


def fuentes(ruta: str | None = None) -> dict[int, dict]:
    """El bloque `## Sources` del anexo, indexado por numero.

    Cada fuente sale como `{'n', 'url', 'titulo', 'citas'}`. `citas` son las lineas `>` que van debajo
    (la cita literal, sin el `>` ni las comillas de fuera). Si un numero se define dos veces, se queda
    la primera y el duplicado no se mezcla: la validacion lo denuncia.

    No se confunde con `secciones(...)['fuentes']`, que son los numeros que **cita** cada seccion. Esto
    es el catalogo de lo que hay definido.
    """
    camino = _camino(ruta)
    if not os.path.isfile(camino):
        return {}
    fuera: dict[int, dict] = {}
    dentro = False
    actual: int | None = None
    with open(camino, encoding="utf-8") as f:
        for linea in f:
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
                if n in fuera:                # duplicado: se queda la primera definicion
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
    return fuera


def sin_fuente(ruta: str | None = None) -> list[dict]:
    """Las secciones que traen afirmaciones sin fuente (criterio) y que hay que firmar.

    Ya no es solo la seccion entera sin fuentes: una seccion puede citar cuatro fuentes y tener dentro
    frases marcadas `[criterio]`. Se devuelven las secciones que tienen alguna (con su cuenta en
    `criterios`). Las secciones de metodo (T.0, T.9 y T.10) quedan fuera: no son saber de natacion.
    """
    return [s for s in secciones(ruta).values() if s["criterios"] and s["id"] not in META]


def criterios(ruta: str | None = None) -> list[dict]:
    """Las afirmaciones marcadas `[criterio]` que esperan firma, con la seccion a la que pertenecen.

    Es la lista de trabajo de verdad: una seccion puede tener cuatro fuentes y una frase sin respaldo
    dentro. Las secciones de metodo (T.0, T.9 y T.10) quedan fuera: no son afirmaciones sobre natacion.

    El anexo va partido en lineas de 120 columnas, asi que la frase se reconstruye con la linea
    anterior si el marcador cayo al principio de la siguiente (`_contexto`). Se cuenta **una por linea
    marcada**, que es el criterio que fijo el plan (21): la linea de T.5 con dos marcas es un solo
    criterio porque la segunda marca es una coletilla de la misma frase.
    """
    fuera = []
    for s in secciones(ruta).values():
        if s["id"] in META:
            continue
        lineas = s["texto"].splitlines()
        for i, linea in enumerate(lineas):
            if "[criterio]" not in linea:
                continue
            fuera.append({"seccion": s["id"], "afirmacion": _limpia(_afirmacion_de(lineas, i))})
    return fuera


_FIN_DE_FRASE = (".", ":", ";", "!", "?", "|")


def _afirmacion_de(lineas: list[str], i: int) -> str:
    """La frase que lleva el `[criterio]` de la linea `i`, con su contexto si venia partida.

    En las tablas de T.8 el criterio vive en una fila: se usa la primera columna (la afirmacion), no
    la fila entera con el estado y la justificacion.
    """
    linea = lineas[i].strip()
    if linea.startswith("|"):
        celdas = [c.strip() for c in linea.strip("|").split("|")]
        if celdas and celdas[0]:
            return celdas[0]
    partes = [linea]
    j = i - 1
    while j >= 0:
        previa = lineas[j].strip()
        if not previa or previa.startswith("#") or previa.startswith("|"):
            break
        if "[criterio]" in previa:
            # La frase empieza despues del ultimo marcador de la linea anterior; no se duplica.
            cola = previa.rsplit("[criterio]", 1)[1].lstrip("`").lstrip()
            cola = re.sub(r"^[.:;]\s*", "", cola)
            if cola:
                partes.insert(0, cola)
            break
        partes.insert(0, previa)
        if previa.endswith(_FIN_DE_FRASE):
            break
        j -= 1
    # Si el marcador cae a mitad de la frase, la frase sigue en las lineas de abajo: se completa
    # hasta el punto (o hasta el siguiente marcador, que ya es otro criterio).
    cola_actual = linea.rsplit("[criterio]", 1)[1].strip().lstrip("`").strip()
    if cola_actual and not cola_actual.endswith(_FIN_DE_FRASE):
        k = i + 1
        while k < len(lineas):
            siguiente = lineas[k].strip()
            if not siguiente or siguiente.startswith("#") or siguiente.startswith("|"):
                break
            if "[criterio]" in siguiente:
                antes = siguiente.split("[criterio]", 1)[0].strip()
                if antes:
                    partes.append(antes)
                break
            partes.append(siguiente)
            if siguiente.endswith(_FIN_DE_FRASE):
                break
            k += 1
    return " ".join(p.strip() for p in partes)


def afirmaciones_sin_fuente(ruta: str | None = None) -> list[dict]:
    """Compatibilidad: el mismo listado que `criterios()` (nombre historico del modulo)."""
    return criterios(ruta)


def validar(ruta: str | None = None) -> dict:
    """Valida el anexo: IDs de seccion, citas y fuentes del bloque `## Sources`.

    Devuelve `{'anexo', 'secciones', 'fuentes', 'citas_usadas', 'errores', 'avisos', 'ok'}`.
    Un error invalida el documento (cita rota o seccion duplicada); un aviso no (fuente definida y no
    citada, o fuente sin cita literal). El CLI devuelve 0 solo si `ok` y no hay errores.
    """
    secs = secciones(ruta)
    defs = fuentes(ruta)
    errores: list[dict] = []
    avisos: list[dict] = []

    for d in duplicados(ruta):
        errores.append({"tipo": "seccion_duplicada",
                        "detalle": f"{d['id']} aparece otra vez en la linea {d['linea']}",
                        "id": d["id"]})

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

    return {
        "anexo": _camino(ruta),
        "secciones": len(secs),
        "fuentes": len(defs),
        "citas_usadas": len(usadas),
        "errores": errores,
        "avisos": avisos,
        "ok": not errores,
    }


def _limpia(linea: str) -> str:
    """La frase sin la marca de criterio ni las comillas de codigo que la acompanan en el anexo."""
    frase = linea.replace("`[criterio]`", "").replace("[criterio]", "")
    frase = re.sub(r"[ \t]+([.,;:])", r"\1", frase)      # "proyecto ." -> "proyecto."
    frase = re.sub(r"[ \t]{2,}", " ", frase)
    return frase.strip().strip("`").strip()


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
    crits = criterios(ruta)
    return {"anexo": RUTA_ANEXO, "total": len(lista),
            "revisadas": sum(1 for x in lista if x["revisado_por"]),
            # Criterios sin firma, no secciones sin fuente: una seccion con fuentes puede tener dentro
            # frases `[criterio]`. Antes esto contaba secciones y el portal podia decir "todo con fuente".
            "sin_fuente": len(crits),
            "criterios_pendientes": len(crits),
            "secciones": lista}
