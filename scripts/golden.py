#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Snapshots dorados ("golden") de lo que hoy dice el motor, para no romperlo sin darse cuenta.

Guarda y compara, sin dependencias externas, las cuatro salidas que resumen el comportamiento de la
version actual del conocimiento:

  1. `cli valoracion`                  (el discurso del entrenador),
  2. `cli plan --recalculado`          (la semana ajustada con lo que ha entrado),
  3. `cli reglas`                      (el credito de cada regla),
  4. `cli decision --lista`            (las propuestas guardadas y lo que se decidio),
  5. un resumen de los datos incrustados en `cuadro/panel.html` (solo lo imprescindible: KPIs,
     conteos, version del conocimiento y valoracion; se guarda tambien el hash del JSON completo
     para detectar cualquier cambio de datos).

Los snapshots llevan datos del atleta, asi que se guardan SIEMPRE en `data/derived/golden/`, que
esta ignorado por git. El script si puede ser publico; sus salidas no.

Uso:
    # antes de tocar el motor: guardar la referencia
    python scripts/golden.py --guardar

    # despues del cambio: comparar contra la referencia
    python scripts/golden.py --comparar

    # otra carpeta de snapshots (por ejemplo, para comparar v1 contra v2)
    python scripts/golden.py --guardar --dir data/derived/golden/v1
    python scripts/golden.py --comparar --dir data/derived/golden/v1

En Docker:
    docker compose exec -T entrenador python scripts/golden.py --guardar
    docker compose exec -T entrenador python scripts/golden.py --comparar

Codigo de salida de `--comparar`: 0 si todo coincide (texto **y** codigo de salida), 1 si algo cambia
o falta la referencia. Un comando que termina con codigo != 0 hace fallar la comparacion (R-09): un
error no puede guardarse como si fuera comportamiento.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_POR_DEFECTO = os.path.join("data", "derived", "golden")

# (nombre del snapshot, argumentos del CLI). El orden es el de la documentacion.
COMANDOS = (
    ("valoracion", ["valoracion"]),
    ("plan_recalculado", ["plan", "--recalculado"]),
    ("reglas", ["reglas"]),
    ("decision_lista", ["decision", "--lista"]),
)

# Claves que cambian en cada ejecucion y no dicen nada del conocimiento: se excluyen del hash.
VOLATILES = ("generado",)


def _normalizar_salida(texto: str) -> str:
    """Quita de las snapshots lo que cambia solo por el dia en que se ejecutan.

    `plan --recalculado` imprime la fecha de hoy; los textos de valoracion pueden decir "Quedan 26
    dias". Ninguna de las dos cosas es comportamiento del motor, asi que se comparan normalizadas.
    Las fechas de las sesiones y del plan se conservan: esas si son datos.
    """
    texto = re.sub(r"Plan recalculado el \d{4}-\d{2}-\d{2}", "Plan recalculado el <fecha>", texto)
    texto = re.sub(r"\b(Quedan|quedan)\s+\d+\s+d[ií]as\b", r"\1 <n> dias", texto)
    return texto


def _sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _limpiar_volatiles(dato):
    """Copia el dato sin las claves de fecha de generacion (no son conocimiento)."""
    if isinstance(dato, dict):
        return {k: _limpiar_volatiles(v) for k, v in dato.items() if k not in VOLATILES}
    if isinstance(dato, list):
        return [_limpiar_volatiles(x) for x in dato]
    return dato


def _json_canonico(dato) -> str:
    return json.dumps(dato, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def ejecutar(args: list[str]) -> tuple[str, int]:
    """Ejecuta `python -m entrenador.cli ...` y devuelve (salida, codigo).

    No se aborta si falla: el error se guarda como texto, que tambien sirve para comparar. Pero el
    codigo se devuelve para poder avisar en `--guardar`.
    """
    entorno = dict(os.environ)
    entorno.setdefault("PYTHONIOENCODING", "utf-8")
    r = subprocess.run([sys.executable, "-m", "entrenador.cli", *args],
                       cwd=RAIZ, env=entorno, capture_output=True, text=True, encoding="utf-8")
    return ((r.stdout or "") + (r.stderr or "")), r.returncode


def resumen_panel(ruta: str) -> dict:
    """Lo imprescindible de `cuadro/panel.html`: KPIs, conteos y version del conocimiento.

    El HTML lleva los datos del panel en un `<script id="datos" type="application/json">`. No se guarda
    entero (lleva todas las sesiones): se guarda el resumen y un hash del JSON sin las marcas de
    generacion, que basta para detectar que algo cambio.
    """
    if not os.path.isfile(ruta):
        return {"error": "no existe cuadro/panel.html"}
    with open(ruta, encoding="utf-8") as f:
        html = f.read()
    m = re.search(r'<script id="datos" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        return {"error": "no encuentro el bloque de datos en cuadro/panel.html"}
    datos = json.loads(m.group(1))
    limpio = _limpiar_volatiles(datos)
    entrenador = datos.get("entrenador") or {}
    valoracion = datos.get("valoracion") or {}
    plan = datos.get("plan") or {}
    return {
        "hash_datos": _sha256(_json_canonico(limpio)),
        "kpis": datos.get("kpis"),
        "conteos": {k: len(v) for k, v in datos.items() if isinstance(v, list)},
        "conocimiento": entrenador.get("conocimiento"),
        "reglas": entrenador.get("reglas"),
        "propuestas": entrenador.get("propuestas"),
        "plan": {"fase": plan.get("fase"),
                 "semanas": len(plan.get("semanas") or []),
                 "bloques": len(plan.get("bloques") or []),
                 "vivo": plan.get("vivo")},
        "valoracion": {"titular": valoracion.get("titular"),
                       "fuentes": valoracion.get("fuentes"),
                       "n_parrafos": len(valoracion.get("parrafos") or []),
                       "n_dianas": len(valoracion.get("dianas") or [])},
        "competicion": ((datos.get("competicion") or {}).get("resumen")),
    }


def _cabecera() -> dict:
    """Datos de la ejecucion: no se comparan, solo ayudan a leer el snapshot."""
    cab = {"fecha": datetime.now().astimezone().isoformat(timespec="seconds")}
    try:
        cab["git_head"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=RAIZ, capture_output=True,
                                         text=True).stdout.strip()
        cab["git_branch"] = subprocess.run(["git", "branch", "--show-current"], cwd=RAIZ,
                                           capture_output=True, text=True).stdout.strip()
    except OSError:
        pass
    cab["bd"] = os.environ.get("ENTRENADOR_BD", os.path.join("data", "entrenador.db"))
    return cab


def guardar(carpeta: str) -> int:
    os.makedirs(carpeta, exist_ok=True)
    manifiesto = {"cabecera": _cabecera(), "snapshots": {}}
    fallos = 0
    for nombre, args in COMANDOS:
        texto, codigo = ejecutar(args)
        texto = _normalizar_salida(texto)
        with open(os.path.join(carpeta, nombre + ".txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(texto)
        manifiesto["snapshots"][nombre] = {"comando": "python -m entrenador.cli " + " ".join(args),
                                           "codigo": codigo,
                                           "lineas": texto.count("\n") + (0 if texto.endswith("\n") else 1),
                                           "sha256": _sha256(texto)}
        if codigo != 0:
            fallos += 1
            print(f"  [!] {nombre}: el comando termino con codigo {codigo} (se guarda igual)")
    panel = resumen_panel(os.path.join(RAIZ, "cuadro", "panel.html"))
    with open(os.path.join(carpeta, "panel.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(panel, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    manifiesto["snapshots"]["panel"] = {"comando": "resumen de cuadro/panel.html",
                                        "codigo": 0,
                                        "sha256": _sha256(_json_canonico(panel))}
    with open(os.path.join(carpeta, "manifiesto.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    print(f"Guardados {len(COMANDOS) + 1} snapshots en {carpeta}")
    for nombre in [n for n, _ in COMANDOS] + ["panel"]:
        print(f"  {nombre:<18} sha256={manifiesto['snapshots'][nombre]['sha256'][:12]}")
    return 1 if fallos else 0


def _leer(ruta: str) -> str:
    with open(ruta, encoding="utf-8") as f:
        return f.read()


def snapshots_iguales(nombre: str, esperado: str, codigo_esperado: int,
                      actual: str, codigo_actual: int, limite: int = 40) -> bool:
    """Compara texto **y** codigo de salida (R-09). Devuelve True solo si coinciden y el codigo es 0.

    Un comando que falla (codigo != 0) no puede ser un golden valido aunque su texto coincida: se
    guardaria el error como si fuera comportamiento. Si el codigo esperado y el actual difieren, tambien
    falla.
    """
    if codigo_esperado != codigo_actual or codigo_actual != 0:
        print(f"  [~] {nombre}: CODIGO {codigo_esperado} -> {codigo_actual} (tiene que ser 0)")
        if esperado != actual:
            _imprimir_diff(nombre, esperado, actual, limite)
        return False
    if esperado == actual:
        print(f"  [=] {nombre}")
        return True
    print(f"  [~] {nombre}: CAMBIA")
    _imprimir_diff(nombre, esperado, actual, limite)
    return False


def _imprimir_diff(nombre: str, esperado: str, actual: str, limite: int = 40) -> None:
    diff = list(difflib.unified_diff(esperado.splitlines(), actual.splitlines(),
                                     fromfile="golden/" + nombre, tofile="actual/" + nombre, lineterm=""))
    for linea in diff[:limite]:
        print("      " + linea)
    if len(diff) > limite:
        print(f"      ... ({len(diff) - limite} lineas mas)")


def comparar(carpeta: str) -> int:
    if not os.path.isdir(carpeta):
        print(f"No hay snapshots en {carpeta}: ejecuta antes `python scripts/golden.py --guardar`.")
        return 1
    ruta_manifiesto = os.path.join(carpeta, "manifiesto.json")
    if not os.path.isfile(ruta_manifiesto):
        print(f"  [!] falta {ruta_manifiesto}: no se puede comprobar el codigo de salida (R-09)")
        return 1
    with open(ruta_manifiesto, encoding="utf-8") as f:
        manifiesto = json.load(f)
    snaps = manifiesto.get("snapshots") or {}
    cambios = 0
    for nombre, args in COMANDOS:
        ruta = os.path.join(carpeta, nombre + ".txt")
        if not os.path.isfile(ruta):
            print(f"  [!] {nombre}: falta el snapshot")
            cambios += 1
            continue
        codigo_esperado = int((snaps.get(nombre) or {}).get("codigo", 0))
        actual, codigo_actual = ejecutar(args)
        actual = _normalizar_salida(actual)
        if not snapshots_iguales(nombre, _leer(ruta), codigo_esperado, actual, codigo_actual):
            cambios += 1
    ruta_panel = os.path.join(carpeta, "panel.json")
    if not os.path.isfile(ruta_panel):
        print("  [!] panel: falta el snapshot")
        cambios += 1
    else:
        actual = resumen_panel(os.path.join(RAIZ, "cuadro", "panel.html"))
        texto_actual = json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        codigo_esperado = int((snaps.get("panel") or {}).get("codigo", 0))
        if not snapshots_iguales("panel", _leer(ruta_panel), codigo_esperado, texto_actual, 0):
            cambios += 1
    print()
    if cambios:
        print(f"CAMBIOS: {cambios} snapshot(s) no coinciden con {carpeta}.")
        return 1
    print(f"OK: los {len(COMANDOS) + 1} snapshots coinciden con {carpeta} (texto y codigo).")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Guarda o compara los snapshots dorados del motor.")
    grupo = p.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--guardar", action="store_true", help="escribe la referencia en --dir")
    grupo.add_argument("--comparar", action="store_true", help="compara con la referencia de --dir")
    p.add_argument("--dir", default=DIR_POR_DEFECTO, help=f"carpeta de snapshots (por defecto {DIR_POR_DEFECTO})")
    args = p.parse_args(argv)
    return guardar(args.dir) if args.guardar else comparar(args.dir)


if __name__ == "__main__":
    raise SystemExit(main())
