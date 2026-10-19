#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Exporta las tareas del plan de conocimiento a un CSV para seguirlas.

La fuente de verdad es `PLAN_MEJORA_CONOCIMIENTO.md`. Este script solo lee las tablas de las fases
(`#### F0 ...`) y escribe `PLAN_TAREAS.csv` con una fila por tarea. Asi el tablero no se queda viejo
cuando se anade o cambia una tarea en el plan.

Uso:
    python scripts/exportar_plan_tareas.py
    python scripts/exportar_plan_tareas.py --plan PLAN_MEJORA_CONOCIMIENTO.md --salida PLAN_TAREAS.csv
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


RE_FASE = re.compile(r"^#### (F\d+) — (.+)$")
RE_TAREA = re.compile(r"^\| (F\d+-\d+) \|")


def tareas(plan: Path) -> list[dict]:
    fase = nombre = ""
    fuera: list[dict] = []
    for linea in plan.read_text(encoding="utf-8").splitlines():
        m = RE_FASE.match(linea)
        if m:
            fase, nombre = m.group(1), m.group(2).strip()
            continue
        if not RE_TAREA.match(linea):
            continue
        partes = [p.strip() for p in linea.strip().strip("|").split("|")]
        if len(partes) < 5:
            continue
        tid, entregable, depende, aceptacion, prueba = partes[:5]
        fuera.append({
            "id": tid,
            "fase": fase,
            "fase_nombre": nombre,
            "tarea": entregable,
            "depende_de": depende,
            "aceptacion": aceptacion,
            "prueba": prueba,
            "estado": "pendiente",
        })
    return fuera


def main() -> int:
    p = argparse.ArgumentParser(description="Exporta las tareas del plan de conocimiento a CSV.")
    p.add_argument("--plan", default="PLAN_MEJORA_CONOCIMIENTO.md")
    p.add_argument("--salida", default="PLAN_TAREAS.csv")
    args = p.parse_args()

    filas = tareas(Path(args.plan))
    if not filas:
        print("No he encontrado tareas: revisa el formato de las tablas del plan.")
        return 1
    # El estado es lo unico que no sale del plan: se conserva el que ya hubiera en el CSV para no perder
    # el seguimiento al regenerarlo.
    anteriores: dict[str, str] = {}
    salida_actual = Path(args.salida)
    if salida_actual.is_file():
        with salida_actual.open(newline="", encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                if fila.get("id") and fila.get("estado"):
                    anteriores[fila["id"]] = fila["estado"]
    for fila in filas:
        fila["estado"] = anteriores.get(fila["id"], "pendiente")
    with open(args.salida, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "fase", "fase_nombre", "tarea", "depende_de",
                                          "aceptacion", "prueba", "estado"], lineterminator="\n")
        w.writeheader()
        w.writerows(filas)
    print(f"{len(filas)} tareas exportadas a {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
