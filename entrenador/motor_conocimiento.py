#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Adaptador entre el conocimiento TOML y las estructuras de v1 (F3-05).

El motor v1 sigue leyendo `estimulos.CLASES`, `reglas.REGLAS`, etc. Cuando
`MOTOR_CONOCIMIENTO` vale `v2`, esos modulos sustituyen sus tablas por las que salen de aqui
(publico + local). Con `dual`, se calculan las dos y se compara; se ejecuta v1 y se deja un
informe en `data/derived/conocimiento/dual_<modulo>.json`.

F9 activa `MOTOR_CONOCIMIENTO=v2` por defecto; con `v1` (rollback) nada de esto se ejecuta y las
constantes historicas siguen mandando.
"""

from __future__ import annotations

import json
import os
import warnings

from . import conocimiento_toml


def cargar() -> conocimiento_toml.Conocimiento:
    c = conocimiento_toml.cargar()
    if not c.local:
        warnings.warn("MOTOR_CONOCIMIENTO v2/dual sin conocimiento/local: se usa solo el conocimiento publico",
                      RuntimeWarning, stacklevel=2)
    return c


def _num(valor):
    return valor


def _entero_si_puede(valor):
    if isinstance(valor, float) and valor.is_integer():
        return int(valor)
    return valor


def clases(c: conocimiento_toml.Conocimiento) -> dict[str, dict]:
    """`estimulos.CLASES` a partir de los estimulos TOML, en el orden de `orden`."""
    fuera: dict[str, dict] = {}
    for e in sorted(c.estimulos, key=lambda x: x.orden):
        if not e.clave:
            continue
        fuera[e.clave] = {
            "nombre": e.nombre, "entrena": e.entrena, "no_entrena": e.no_entrena,
            "recuperacion": _entero_si_puede(e.recuperacion_h),
            "papel400": e.papel_400, "papel3000": e.papel_3000, "senal": e.senal,
            "seccion_T": list(e.seccion_T), "grado": e.grado, "sin_fuente": list(e.sin_fuente),
        }
    return fuera


def conocimiento(c: conocimiento_toml.Conocimiento) -> dict[str, dict]:
    return {clave: {"seccion_T": list(v["seccion_T"]), "grado": v["grado"],
                    "sin_fuente": list(v["sin_fuente"])}
            for clave, v in clases(c).items()}


def material(c: conocimiento_toml.Conocimiento) -> dict[str, dict]:
    return {m.clave: {"nombre": m.nombre, "que_hace": m.que_hace,
                      "ayuda_s100": m.ayuda_s100, "ojo": m.ojo}
            for m in sorted(c.materiales, key=lambda x: x.orden) if m.clave}


def recetas(c: conocimiento_toml.Conocimiento) -> dict[str, dict]:
    fuera: dict[str, dict] = {}
    for r in sorted(c.recetas, key=lambda x: x.orden):
        if not r.clave:
            continue
        rel = tuple(_entero_si_puede(x) for x in r.rel_ritmo)
        fuera[r.clave] = {
            "nombre": r.nombre, "sesion": r.sesion, "metros": _entero_si_puede(r.metros),
            "reps": r.reps, "dist_m": _entero_si_puede(r.dist_m), "rel_ritmo": rel,
            "descanso_s": None if r.descanso_s in (0, 0.0) else _entero_si_puede(r.descanso_s),
            "salida": _entero_si_puede(r.salida_s) if r.salida_s else None,
            "desde": r.desde_dia, "porque": r.porque,
        }
    return fuera


def receta_de_clase(c: conocimiento_toml.Conocimiento) -> dict[str, str]:
    return dict(c.receta_de_clase)


def reglas(c: conocimiento_toml.Conocimiento) -> list[dict]:
    fuera: list[dict] = []
    for r in sorted(c.reglas, key=lambda x: x.orden):
        fuera.append({
            "id": r.legacy_id or r.id, "enunciado": r.enunciado,
            "fuente": r.fuente, "se_comprueba": r.se_comprueba,
            "grado": r.grado, "seccion_t": list(r.seccion_t), "sin_fuente": list(r.sin_fuente),
        })
    return fuera


def reparto(c: conocimiento_toml.Conocimiento) -> dict[str, dict[str, float]]:
    return {fase: {k: _entero_si_puede(v) for k, v in valores.items()}
            for fase, valores in (c.reparto_objetivo or {}).items()}


def minimos(c: conocimiento_toml.Conocimiento) -> dict[str, float]:
    return {k: float(v) for k, v in (c.minimos_obligatorios or {}).items()}


def calendario(c: conocimiento_toml.Conocimiento) -> dict:
    cal = c.calendario
    return {
        "dias": tuple(cal.dias or ()),
        "dias_entrenador": tuple(cal.dias_entrenador or ()),
        "dias_propios": tuple(cal.dias_propios or ()),
        "dia_bici": cal.dia_bici,
        "dias_calidad": tuple(cal.dias_calidad or ()),
        "dias_largos": tuple(cal.dias_largos or ()),
        "duro_h": cal.duro_h,
    }


def datos(c: conocimiento_toml.Conocimiento) -> dict:
    return {
        "clases": clases(c), "conocimiento": conocimiento(c), "material": material(c),
        "recetas": recetas(c), "receta_de_clase": receta_de_clase(c),
        "reglas": reglas(c), "reparto": reparto(c), "minimos": minimos(c),
        "calendario": calendario(c),
    }


def _diferencias(esperado, actual, camino: str = "", salida: list | None = None,
                 limite: int = 200) -> list[dict]:
    salida = [] if salida is None else salida
    if len(salida) >= limite:
        return salida
    if type(esperado) is not type(actual) and not (isinstance(esperado, (int, float))
                                                   and isinstance(actual, (int, float))):
        salida.append({"camino": camino or ".", "esperado": repr(esperado), "actual": repr(actual)})
        return salida
    if isinstance(esperado, dict) and isinstance(actual, dict):
        for clave in sorted(set(esperado) | set(actual)):
            if clave not in esperado:
                salida.append({"camino": f"{camino}.{clave}", "esperado": "<falta>", "actual": repr(actual[clave])})
            elif clave not in actual:
                salida.append({"camino": f"{camino}.{clave}", "esperado": repr(esperado[clave]), "actual": "<falta>"})
            else:
                _diferencias(esperado[clave], actual[clave], f"{camino}.{clave}", salida, limite)
    elif isinstance(esperado, (list, tuple)) and isinstance(actual, (list, tuple)):
        if len(esperado) != len(actual):
            salida.append({"camino": camino or ".", "esperado": f"{len(esperado)} elementos",
                           "actual": f"{len(actual)} elementos"})
        for i, (a, b) in enumerate(zip(esperado, actual)):
            _diferencias(a, b, f"{camino}[{i}]", salida, limite)
    elif esperado != actual:
        salida.append({"camino": camino or ".", "esperado": repr(esperado), "actual": repr(actual)})
    return salida


def registrar_dual(modulo: str, v1: dict, v2: dict) -> list[dict]:
    """Compara v1 y v2 y deja el informe; devuelve la lista de diferencias."""
    diferencias = _diferencias(v1, v2)
    destino = os.path.join("data", "derived", "conocimiento", f"dual_{modulo}.json")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"modulo": modulo, "n": len(diferencias), "diferencias": diferencias},
                  f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    return diferencias
