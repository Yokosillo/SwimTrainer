#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Apuntes de entrenamiento que llegan del cuadro de mando.

El reloj no registra los ejercicios de gimnasio, ni los pesos, ni como de duro fue una sesion: solo guarda la
duracion. Para eso esta el formulario "Apuntar mis entrenamientos" del cuadro de mando (`cuadro/panel.html`):
se rellena, se descarga `partes_entrenador.json` (carpeta de Descargas) y esto lo mete en la base.

Es idempotente: la `clave` de cada apunte es una huella de su contenido, asi que reimportar el mismo fichero no
duplica nada, y corregir un apunte (misma fecha, mismos numeros) actualiza el que ya estaba.

Uso:
    python -m entrenador.cli apuntes                      # lo que hay en la base
    python -m entrenador.cli apuntes --importar           # lee Descargas/partes_entrenador.json
    python -m entrenador.cli apuntes --importar --ruta X  # lee otro fichero
"""

from __future__ import annotations

import json
import os
import sqlite3

from . import db

NOMBRE_FICHERO = "partes_entrenador.json"
TIPOS = ("natacion", "gimnasio", "bici", "otro", "sueno")
MATERIALES = ("ninguno", "palas", "aletas", "pull", "tabla", "varios")


def ruta_por_defecto() -> str:
    """Donde deja el navegador el fichero: la carpeta de Descargas del usuario."""
    return os.path.join(os.path.expanduser("~"), "Downloads", NOMBRE_FICHERO)


def _texto(v) -> str:
    return "" if v is None else str(v).strip()


def _numero(v) -> float | None:
    """Convierte a numero sin inventar: si no es un numero (o esta vacio), devuelve None."""
    t = _texto(v).replace(",", ".")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def clave(a: dict) -> str:
    """Huella del apunte: si no cambia nada, no se duplica; si cambia, se actualiza.

    El material se lee con `_material()` (no con `_texto()`) para que una lista del portal y el texto ya
    escrito den la misma huella: asi el mismo apunte no entra dos veces segun como venga el material.

    Si el apunte trae **`clave` escrita** (los ficheros que se dictan y luego se corrigen: la del 13/10/2026
    es `dictado:2026-10-13:natacion`), manda esa. Motivo: la huella es de CONTENIDO, asi que corregir un
    apunte dictado (anadir los minutos, arreglar una nota) creaba una fila nueva al lado de la vieja y el
    mismo entrenamiento contaba dos veces. Con una clave fija, reimportar el fichero corregido **actualiza**
    el apunte que ya estaba.
    """
    puesta = _texto(a.get("clave"))
    if puesta:
        return puesta
    campos = ("fecha", "tipo", "distancia_m", "minutos", "material", "sensacion", "fc_media", "piscina_m", "notas")
    return "|".join(_material(a) if k == "material" else _texto(a.get(k)) for k in campos)


def leer_todo(ruta: str) -> dict:
    """Lee el JSON que descarga el cuadro de mando y devuelve sus tres bloques:

    - `entradas`: los apuntes sueltos (material, sensaciones, notas).
    - `gimnasio_peticiones`: lo que se ha pedido con "Solicitar trabajo de gimnasio".
    - `gimnasio_sesiones`: las sesiones de gimnasio que se han hecho y apuntado.

    Acepta tambien una lista suelta, para los ficheros de la primera version del portal.
    """
    if not os.path.isfile(ruta):
        raise FileNotFoundError(
            f"No encuentro {ruta}. En el cuadro de mando (cuadro/panel.html), seccion "
            f"\"Apuntar\" o \"Gimnasio\", pulsa \"Descargar fichero\" y se guarda ahi.")
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)
    if isinstance(datos, list):
        return {"entradas": datos, "gimnasio_peticiones": [], "gimnasio_sesiones": []}
    if not isinstance(datos, dict):
        raise ValueError("El fichero no tiene la forma esperada (falta la lista 'entradas').")
    salida = {}
    for clave_f, nombre in (("entradas", "entradas"), ("gimnasio_peticiones", "gimnasio_peticiones"),
                            ("gimnasio_sesiones", "gimnasio_sesiones")):
        valor = datos.get(clave_f) or []
        if not isinstance(valor, list):
            raise ValueError(f"El campo '{clave_f}' deberia ser una lista.")
        salida[nombre] = [x for x in valor if isinstance(x, dict)]
    return salida


def leer(ruta: str) -> list[dict]:
    """Solo los apuntes sueltos (se mantiene por comodidad)."""
    entradas = leer_todo(ruta)["entradas"]
    return [e for e in entradas if _texto(e.get("fecha")) or _texto(e.get("notas"))]


def _material(p: dict) -> str:
    """El material puede llegar como lista (del portal) o como texto ya escrito."""
    m = p.get("material")
    if isinstance(m, (list, tuple)):
        return ", ".join(t for t in (_texto(x) for x in m) if t and t.lower() != "nada de material")
    return _texto(m)


def clave_peticion(p: dict) -> str:
    campos = ("fecha", "objetivo", "minutos", "donde", "molestias", "notas")
    return "|".join([_texto(p.get(k)) for k in campos] + [_material(p)])


def clave_sesion(s: dict) -> str:
    return _texto(s.get("fecha")) + "|" + json.dumps(s.get("ejercicios") or [], ensure_ascii=False, sort_keys=True)


def _volumen(ejercicios: list) -> tuple[int, int, float]:
    """Series, repeticiones y kilos levantados (series x repeticiones x kilos)."""
    series = reps = 0
    volumen = 0.0
    for e in ejercicios:
        if not isinstance(e, dict):
            continue
        s = _numero(e.get("series")) or 0
        r = _numero(e.get("reps")) or 0
        kg = _numero(e.get("kg")) or 0
        series += int(s)
        reps += int(s * r)
        volumen += s * r * kg
    return series, reps, volumen


def anotar(cn: sqlite3.Connection, *, fecha: str, tipo: str = "natacion", quien: str = "atleta",
           distancia_m: float | None = None, minutos: float | None = None, material: str = "ninguno",
           sensacion: float | None = None, notas: str = "", piscina_m: float | None = None,
           fuente: str = "cli") -> dict:
    """Apunta una sesion que no trae el reloj: la del entrenador, con su fecha y sus metros (V1.3-05).

    La clave es fija (`quien|fecha|tipo`), asi que volver a apuntar el mismo dia **actualiza** la fila en vez de
    duplicarla. Devuelve la fila tal como ha quedado.
    """
    quien = (quien or "atleta").strip().lower() or "atleta"
    k = f"{quien}|{_texto(fecha)[:10]}|{_texto(tipo).lower() or 'otro'}"
    cn.execute(
        """INSERT INTO apunte (clave, fecha, tipo, distancia_m, minutos, material, sensacion, fc_media,
                               piscina_m, notas, quien, fuente, importado_en)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(clave) DO UPDATE SET
               fecha=excluded.fecha, tipo=excluded.tipo, distancia_m=excluded.distancia_m,
               minutos=excluded.minutos, material=excluded.material, sensacion=excluded.sensacion,
               piscina_m=excluded.piscina_m, notas=excluded.notas, quien=excluded.quien,
               fuente=excluded.fuente, importado_en=excluded.importado_en""",
        (k, _texto(fecha)[:10], _texto(tipo).lower() or "otro", distancia_m, minutos, material, sensacion,
         None, piscina_m, _texto(notas), quien, fuente, db.ahora()))
    cn.commit()
    fila = cn.execute("SELECT * FROM apunte WHERE clave = ?", (k,)).fetchone()
    return dict(fila) if fila else {}


def importar(cn: sqlite3.Connection, ruta: str) -> dict:
    """Mete en la base los apuntes, las peticiones de gimnasio y las sesiones de gimnasio (idempotente).

    Devuelve cuantos se leyeron y cuantos son nuevos o ya estaban. Lo mismo, por separado, en
    `peticiones` y `sesiones_gimnasio`.
    """
    todo = leer_todo(ruta)
    entradas = [e for e in todo["entradas"] if _texto(e.get("fecha")) or _texto(e.get("notas"))]
    nuevas = actualizadas = 0
    for a in entradas:
        k = clave(a)
        if cn.execute("SELECT 1 FROM apunte WHERE clave = ?", (k,)).fetchone():
            actualizadas += 1
        else:
            nuevas += 1
        tipo = _texto(a.get("tipo")).lower() or "otro"
        material = _material(a).lower() or "ninguno"
        cn.execute(
            """INSERT INTO apunte (clave, fecha, tipo, distancia_m, minutos, material, sensacion, fc_media,
                                   piscina_m, notas, fuente, importado_en)
               VALUES (?,?,?,?,?,?,?,?,?,?,'portal',?)
               ON CONFLICT(clave) DO UPDATE SET
                   fecha=excluded.fecha, tipo=excluded.tipo, distancia_m=excluded.distancia_m,
                   minutos=excluded.minutos, material=excluded.material, sensacion=excluded.sensacion,
                   fc_media=excluded.fc_media, piscina_m=excluded.piscina_m, notas=excluded.notas,
                   importado_en=excluded.importado_en""",
            (k, _texto(a.get("fecha")), tipo, _numero(a.get("distancia_m")), _numero(a.get("minutos")),
             material, _numero(a.get("sensacion")), _numero(a.get("fc_media")), _numero(a.get("piscina_m")),
             _texto(a.get("notas")), db.ahora()))

    pet_nuevas = pet_actualizadas = 0
    for p in todo["gimnasio_peticiones"]:
        if not (_texto(p.get("objetivo")) or _texto(p.get("notas"))):
            continue
        k = clave_peticion(p)
        if cn.execute("SELECT 1 FROM gimnasio_peticion WHERE clave = ?", (k,)).fetchone():
            pet_actualizadas += 1
        else:
            pet_nuevas += 1
        cn.execute(
            """INSERT INTO gimnasio_peticion (clave, fecha, pedida_en, objetivo, minutos, donde, material,
                                              molestias, notas, importado_en)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(clave) DO UPDATE SET
                   fecha=excluded.fecha, objetivo=excluded.objetivo, minutos=excluded.minutos,
                   donde=excluded.donde, material=excluded.material, molestias=excluded.molestias,
                   notas=excluded.notas, importado_en=excluded.importado_en""",
            (k, _texto(p.get("fecha"))[:10], _texto(p.get("pedida_en"))[:19], _texto(p.get("objetivo")),
             _numero(p.get("minutos")), _texto(p.get("donde")) or "Gimnasio", _material(p),
             _texto(p.get("molestias")), _texto(p.get("notas")), db.ahora()))

    ses_nuevas = ses_actualizadas = 0
    for s in todo["gimnasio_sesiones"]:
        ejercicios = [e for e in (s.get("ejercicios") or []) if isinstance(e, dict)]
        if not ejercicios:
            continue
        k = clave_sesion(s)
        series, reps, volumen = _volumen(ejercicios)
        if cn.execute("SELECT 1 FROM gimnasio_sesion WHERE clave = ?", (k,)).fetchone():
            ses_actualizadas += 1
        else:
            ses_nuevas += 1
        cn.execute(
            """INSERT INTO gimnasio_sesion (clave, fecha, ejercicios, series, repeticiones, volumen_kg, notas, importado_en)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(clave) DO UPDATE SET
                   fecha=excluded.fecha, ejercicios=excluded.ejercicios, series=excluded.series,
                   repeticiones=excluded.repeticiones, volumen_kg=excluded.volumen_kg,
                   notas=excluded.notas, importado_en=excluded.importado_en""",
            (k, _texto(s.get("fecha"))[:10], json.dumps(ejercicios, ensure_ascii=False), series, reps,
             round(volumen, 1), _texto(s.get("notas")), db.ahora()))

    leidos = len(entradas) + pet_nuevas + pet_actualizadas + ses_nuevas + ses_actualizadas
    cn.execute("INSERT INTO importacion (momento, fuente, ruta, leidos, nuevos, actualizados, omitidos, incidencias)"
               " VALUES (?,?,?,?,?,?,?,?)",
               (db.ahora(), "portal-natacion", ruta, leidos, nuevas + pet_nuevas + ses_nuevas,
                actualizadas + pet_actualizadas + ses_actualizadas, 0, 0))
    cn.commit()
    return {"leidas": len(entradas), "nuevas": nuevas, "actualizadas": actualizadas,
            "peticiones": {"leidas": pet_nuevas + pet_actualizadas, "nuevas": pet_nuevas, "actualizadas": pet_actualizadas},
            "sesiones_gimnasio": {"leidas": ses_nuevas + ses_actualizadas, "nuevas": ses_nuevas,
                                  "actualizadas": ses_actualizadas}}


def mostrar(cn: sqlite3.Connection, limite: int = 40) -> None:
    total = cn.execute("SELECT COUNT(*) FROM apunte").fetchone()[0]
    if not total:
        print("No hay apuntes en la base todavia.")
        print("Se rellenan en el cuadro de mando (cuadro/panel.html), pestanas \"Apuntar\" y \"Gimnasio\":")
        print("  pulsar \"Descargar fichero\" deja partes_entrenador.json en Descargas, y luego")
        print("  `python -m entrenador.cli apuntes --importar` lo mete aqui.")
        mostrar_gimnasio(cn)
        return
    filas = cn.execute("SELECT * FROM apunte ORDER BY fecha DESC, id DESC LIMIT ?", (limite,)).fetchall()
    print(f"Apuntes en la base: {total} (los {len(filas)} mas recientes)")
    print(f"  {'fecha':<12}{'tipo':<10}{'material':<9}{'metros':>8}{'min':>7}{'sens':>6}  notas")
    for f in filas:
        metros = f"{f['distancia_m']:.0f}" if f["distancia_m"] else ""
        minutos = f"{f['minutos']:.0f}" if f["minutos"] else ""
        sens = f"{f['sensacion']:.0f}" if f["sensacion"] else ""
        print(f"  {(f['fecha'] or '')[:10]:<12}{(f['tipo'] or ''):<10}{(f['material'] or ''):<9}"
              f"{metros:>8}{minutos:>7}{sens:>6}  {(f['notas'] or '')[:58]}")
    for tipo in TIPOS:
        n, mins = cn.execute("SELECT COUNT(*), SUM(minutos) FROM apunte WHERE tipo = ?", (tipo,)).fetchone()
        if n:
            print(f"  {tipo:<10} {n} apuntes" + (f", {mins:.0f} min en total" if mins else ""))
    mostrar_gimnasio(cn)


def pendientes(cn: sqlite3.Connection, limite: int = 12) -> list[dict]:
    """Lo que se ha pedido con "Solicitar trabajo de gimnasio" y todavia no tiene sesion escrita."""
    filas = cn.execute(
        """SELECT fecha, pedida_en, objetivo, minutos, donde, material, molestias, notas
           FROM gimnasio_peticion ORDER BY COALESCE(fecha, pedida_en) DESC, id DESC LIMIT ?""", (limite,)).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        d["material"] = [m.strip() for m in (d.get("material") or "").split(",") if m.strip()]
        salida.append(d)
    return salida


def prescritas(cn: sqlite3.Connection, limite: int = 5) -> list[dict]:
    """Las sesiones que manda el programa (las escribe el agente), con sus series y sus pesos."""
    filas = cn.execute(
        "SELECT fecha, titulo, bloques, notas FROM gimnasio_prescrita"
        " ORDER BY COALESCE(fecha, escrita_en) DESC, id DESC LIMIT ?", (limite,)).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        try:
            d["bloques"] = json.loads(d.get("bloques") or "[]")
        except ValueError:
            d["bloques"] = []
        salida.append(d)
    return salida


def sesiones_gimnasio(cn: sqlite3.Connection, limite: int = 12) -> list[dict]:
    """El historial de sesiones de gimnasio apuntadas en el portal."""
    filas = cn.execute(
        "SELECT fecha, ejercicios, series, repeticiones, volumen_kg FROM gimnasio_sesion"
        " ORDER BY fecha DESC, id DESC LIMIT ?", (limite,)).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        try:
            d["ejercicios"] = json.loads(d.get("ejercicios") or "[]")
        except ValueError:
            d["ejercicios"] = []
        salida.append(d)
    return salida


def escribir_prescrita(cn: sqlite3.Connection, fichero: str) -> dict:
    """Escribe una sesion de gimnasio que manda el programa (las escribe el agente, no el portal).

    El fichero lleva un objeto o una lista de objetos con: fecha, titulo, bloques
    (lista de {ejercicio, series, reps, kg, nota}) y notas.
    """
    with open(fichero, encoding="utf-8") as f:
        datos = json.load(f)
    sesiones = datos if isinstance(datos, list) else [datos]
    escritas = 0
    for s in sesiones:
        if not isinstance(s, dict) or not (s.get("bloques") or s.get("titulo")):
            continue
        bloques = json.dumps([b for b in (s.get("bloques") or []) if isinstance(b, dict)], ensure_ascii=False)
        k = _texto(s.get("fecha"))[:10] + "|" + _texto(s.get("titulo")) + "|" + bloques
        cn.execute(
            """INSERT INTO gimnasio_prescrita (clave, fecha, titulo, bloques, notas, escrita_en)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(clave) DO UPDATE SET
                   fecha=excluded.fecha, titulo=excluded.titulo, bloques=excluded.bloques,
                   notas=excluded.notas, escrita_en=excluded.escrita_en""",
            (k, _texto(s.get("fecha"))[:10], _texto(s.get("titulo")), bloques, _texto(s.get("notas")), db.ahora()))
        escritas += 1
    cn.commit()
    return {"escritas": escritas}


def _resumen_gimnasio(cn: sqlite3.Connection) -> dict:
    """Todo lo del gimnasio: lo pedido, lo hecho y lo que manda el programa."""
    n_pet = cn.execute("SELECT COUNT(*) FROM gimnasio_peticion").fetchone()[0]
    n_ses = cn.execute("SELECT COUNT(*) FROM gimnasio_sesion").fetchone()[0]
    vol = cn.execute("SELECT SUM(volumen_kg) FROM gimnasio_sesion").fetchone()[0] or 0
    minutos = cn.execute("SELECT SUM(minutos) FROM apunte WHERE tipo = 'gimnasio'").fetchone()[0] or 0
    return {
        "n_peticiones": n_pet, "peticiones": pendientes(cn),
        "n_sesiones": n_ses, "sesiones": sesiones_gimnasio(cn),
        "volumen_total_kg": round(vol, 1), "minutos_apuntados": minutos,
        "prescritas": prescritas(cn),
    }


def resumen(cn: sqlite3.Connection) -> dict:
    """Lo que el cuadro de mando ensena: los apuntes por tipo, los ultimos y todo el gimnasio."""
    gim = _resumen_gimnasio(cn)
    total = cn.execute("SELECT COUNT(*) FROM apunte").fetchone()[0]
    if not total:
        return {"total": 0, "por_tipo": [], "recientes": [], "gimnasio": gim}
    por_tipo = [dict(f) for f in cn.execute(
        "SELECT tipo, COUNT(*) n, SUM(minutos) minutos FROM apunte GROUP BY tipo ORDER BY n DESC")]
    recientes = [dict(f) for f in cn.execute(
        """SELECT fecha, tipo, distancia_m, minutos, material, sensacion, fc_media, piscina_m, notas
           FROM apunte ORDER BY fecha DESC, id DESC LIMIT 12""")]
    return {"total": total, "por_tipo": por_tipo, "recientes": recientes, "gimnasio": gim}


def mostrar_gimnasio(cn: sqlite3.Connection) -> None:
    """Lo que hay del gimnasio en la consola: lo pedido, lo hecho y lo que manda el programa."""
    r = _resumen_gimnasio(cn)
    print(f"\nGimnasio: {r['n_peticiones']} peticiones, {r['n_sesiones']} sesiones apuntadas "
          f"({r['volumen_total_kg']:.0f} kg levantados), {len(r['prescritas'])} sesiones escritas")
    if r["peticiones"]:
        print("\n  PEDIDO (Solicitar trabajo de gimnasio):")
        for p in r["peticiones"]:
            material = ", ".join(p["material"]) or "sin material"
            print(f"    {(p['fecha'] or '')[:10]:<11}{p['objetivo'] or 'sesion':<26}"
                  f"{str(int(p['minutos']) if p['minutos'] else '?'):>4} min  {p['donde'] or ''}")
            print(f"       material: {material}" + (f" | a evitar: {p['molestias']}" if p["molestias"] else ""))
            if p["notas"]:
                print(f"       notas: {p['notas'][:70]}")
    if r["sesiones"]:
        print("\n  HECHO (apuntado en el portal):")
        for s in r["sesiones"]:
            print(f"    {(s['fecha'] or '')[:10]:<11}{len(s['ejercicios'])} ejercicios, {s['series']} series, "
                  f"{s['volumen_kg']:.0f} kg")
    if r["prescritas"]:
        print("\n  ESCRITO POR EL PROGRAMA:")
        for s in r["prescritas"]:
            print(f"    {(s['fecha'] or '')[:10]:<11}{s['titulo'] or 'sesion'} ({len(s['bloques'])} ejercicios)")
    if not (r["peticiones"] or r["sesiones"] or r["prescritas"]):
        print("  Todavia sin nada. En el cuadro de mando (cuadro/panel.html), pestana \"Gimnasio\",")
        print("  el boton \"Solicitar trabajo de gimnasio\" deja la peticion en partes_entrenador.json.")
