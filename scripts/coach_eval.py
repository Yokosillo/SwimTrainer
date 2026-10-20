#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Arnés de evaluación de la capa LLM (F8-06). NO hace llamadas de red.

Compara la explicación determinista (baseline) con una respuesta de proveedor falso, y cuenta:
- explicaciones válidas / fallback;
- citas válidas / citas rotas;
- cifras fuera de contexto;
- latencia medida local y coste estimado por tokens (sin tarifa real).
El protocolo con un proveedor real sería el mismo, cambiando `ProveedorFalso` por
`ProveedorOpenAICompatible` y registrando la latencia/coste del proveedor; no se ejecuta aquí.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from entrenador import coach_llm  # noqa: E402

REC = {
    "prioridad": 1, "problema": "falta ritmo de prueba",
    "estado": {"clase": "ritmo_prueba", "confianza": 0.7, "metros_actuales": 0,
               "metros_minimos": 400, "pct": 0, "grado": "historial", "seccion_T": ["T.1"]},
    "evidencia": ["AF-002"], "parametros": ["PA-101"], "contraindicaciones": [],
    "metrica_exito": {"tipo": "ritmo_100", "criterio": "mantener el ritmo", "medir_en": "2026-10-23"},
    "revisar_en": "2026-10-27", "explicacion": "Que veo: falta ritmo. Que propongo: 8x100.",
    "opciones": [{"id": "A", "recomendada": True, "sesion": "8x100 con 25-30 s", "dia": "jueves",
                  "metros": 1700, "ritmo": "1:16", "confianza": 0.7, "riesgo_etiqueta": "medio",
                  "coste_etiqueta": "medio", "score": 1.5}],
}
VALIDA = {"explicacion": "La prioridad es el ritmo de prueba.", "citas": ["AF-002"],
          "cifras": [], "avisos": [], "confianza": "media"}
INVALIDA = {"explicacion": "La mejora es 999 segundos.", "citas": ["AF-999"],
            "cifras": [{"valor": 999, "unidad": "s", "origen": "PA-101"}],
            "avisos": [], "confianza": "alta"}


def ejecutar(casos=None) -> dict:
    casos = casos or [("valida", VALIDA), ("invalida", INVALIDA)]
    filas = []
    for nombre, respuesta in casos:
        t0 = time.perf_counter()
        r = coach_llm.explicar(None, REC, proveedor=coach_llm.ProveedorFalso(
            json.dumps(respuesta, ensure_ascii=False)), activo=True)
        ms = round((time.perf_counter() - t0) * 1000, 2)
        filas.append({"caso": nombre, "fuente": r.get("fuente"),
                      "citas_validas": len([c for c in r.get("citas") or [] if c.startswith(("AF-", "FU-"))]),
                      "fallback": r.get("fuente") == "determinista",
                      "validacion": r.get("validacion") or [], "latencia_local_ms": ms,
                      "coste_estimado": "depende del proveedor; solo una llamada y max_tokens"})
    return {"protocolo": "baseline determinista vs LLM; medir utilidad/tiempo con el atleta, "
                         "citas validas, latencia y coste; no ejecutar en tests",
            "cases": filas}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Arnés F8 sin red (proveedor falso).")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    d = ejecutar()
    print(json.dumps(d, ensure_ascii=False, indent=2) if args.json else
          "\n".join(f"{x['caso']}: {x['fuente']} · citas={x['citas_validas']} · "
                    f"fallback={x['fallback']} · {x['latencia_local_ms']} ms" for x in d["cases"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
