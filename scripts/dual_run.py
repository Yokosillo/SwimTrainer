#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Dual-run v1/v2 de F9: ejecuta una ventana de días y resume métricas sin tocar la base.

No escribe recomendaciones ni decisiones: solo llama a `motor.dual()`, que calcula v1 y v2 en
paralelo y deja un JSON por día. El resumen contiene conteos y clases, no textos de sesiones ni
datos personales; aun así se guarda en `data/derived/` (ignorado por git).

Uso:
    python scripts/dual_run.py --fin 2026-10-19 --dias 14
    python scripts/dual_run.py --inicio 2026-10-06 --fin 2026-10-19
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from entrenador import conocimiento_toml, db, motor


def _fechas(inicio: str | None, fin: str | None, dias: int) -> list[str]:
    fin_d = date.fromisoformat(fin) if fin else date.today()
    if inicio:
        inicio_d = date.fromisoformat(inicio)
    else:
        inicio_d = fin_d - timedelta(days=max(1, dias) - 1)
    if inicio_d > fin_d:
        raise SystemExit("--inicio no puede ser posterior a --fin")
    total = (fin_d - inicio_d).days + 1
    return [(inicio_d + timedelta(days=i)).isoformat() for i in range(total)]


def _opciones(r: dict) -> list[dict]:
    return [o for o in (r.get("opciones") or []) if isinstance(o, dict)]


def _tiene_alternativa(r: dict) -> bool:
    ops = _opciones(r)
    return (len(ops) >= 2 and sum(1 for o in ops if o.get("recomendada")) == 1
            and any(not o.get("recomendada") and not o.get("descartada") for o in ops))


def _metrica_ok(r: dict) -> bool:
    m = r.get("metrica_exito")
    return isinstance(m, dict) and all(str(m.get(k) or "").strip() for k in ("tipo", "criterio", "medir_en"))


def _citas_ok(r: dict, af: set[str], fu: set[str]) -> bool:
    ev = r.get("evidencia")
    if not isinstance(ev, list) or not ev:
        return False
    return all(isinstance(x, str) and (x in af or x in fu or x.startswith(("T.", "R"))) for x in ev)


def _parametros_ok(r: dict, params: dict) -> bool:
    for pid in r.get("parametros") or []:
        p = params.get(str(pid))
        if p is None or not str(p.procedencia or "").strip():
            return False
    return True


def _seguridad_ok(r: dict) -> bool:
    clase = str((r.get("estado") or {}).get("clase") or "")
    problema = str(r.get("problema") or "").lower()
    if clase not in ("dolor_lesion", "lesion", "dolor") and "dolor" not in problema:
        return True
    return all(float(o.get("metros") or 0) == 0 and not o.get("dia") for o in _opciones(r))


def _gobernanza(cn) -> dict:
    c = conocimiento_toml.cargar()
    criterios = ([a for a in c.afirmaciones if a.procedencia == "criterio_firmado"]
                 + [p for p in c.parametros if p.procedencia == "criterio_firmado"])
    firmados = sum(1 for x in criterios if str(getattr(x, "firmado_por", "") or "").strip())
    try:
        verificadas = cn.execute(
            "SELECT COUNT(DISTINCT regla_id) FROM verificacion WHERE regla_id IS NOT NULL "
            "AND veredicto IS NOT NULL AND veredicto <> ''").fetchone()[0]
    except Exception:
        verificadas = 0
    return {"criterios": len(criterios), "criterios_firmados": firmados,
            "reglas": len(c.reglas), "reglas_con_verificacion": int(verificadas or 0),
            "version_conocimiento": c.version}


def resumir(cn, fechas: list[str], carpeta: str) -> dict:
    c = conocimiento_toml.cargar()
    af = {a.id for a in c.afirmaciones}
    fu = {f.id for f in c.fuentes}
    params = {p.id: p for p in c.parametros}

    dias = []
    total_v2 = 0
    total_v1 = 0
    total_opciones = 0
    faltas = {"alternativa": 0, "metrica": 0, "citas": 0, "parametros": 0,
              "estado": 0, "seguridad": 0, "opciones": 0}
    clas = {"mejora": 0, "equivalente": 0, "regresion": 0, "error": 0}
    clases_v1: set[str] = set()
    clases_v2: set[str] = set()

    for fecha in fechas:
        d = motor.dual(cn, fecha, carpeta=os.path.join(carpeta, "dual"))
        v1 = d.get("v1") or {}
        v2 = d.get("v2") or {}
        v1r = v1.get("recomendaciones") or []
        v2r = v2.get("recomendaciones") or []
        total_v1 += len(v1r)
        total_v2 += len(v2r)
        for r in v2r:
            total_opciones += len(_opciones(r))
            if not _tiene_alternativa(r):
                faltas["alternativa"] += 1
            if not _metrica_ok(r):
                faltas["metrica"] += 1
            if not _citas_ok(r, af, fu):
                faltas["citas"] += 1
            if not _parametros_ok(r, params):
                faltas["parametros"] += 1
            if not str(r.get("estado_id") or "").strip() or not isinstance(r.get("estado"), dict):
                faltas["estado"] += 1
            if not _seguridad_ok(r):
                faltas["seguridad"] += 1
            if len(_opciones(r)) < 2:
                faltas["opciones"] += 1
            clases_v2.add(str((r.get("estado") or {}).get("clase") or ""))
        for r in v1r:
            clases_v1.add(str(r.get("clase") or ""))
        cl = d.get("clasificacion") or {}
        for k in clas:
            clas[k] += len(cl.get(k) or [])
        dias.append({
            "fecha": fecha,
            "v1_sesiones": len(v1r),
            "v2_prioridades": len(v2r),
            "v2_opciones": sum(len(_opciones(r)) for r in v2r),
            "mejora": list(cl.get("mejora") or []),
            "equivalente": list(cl.get("equivalente") or []),
            "regresion": list(cl.get("regresion") or []),
            "error": list(cl.get("error") or []),
        })

    n = total_v2
    return {
        "tipo": "dual_run_f9",
        "inicio": fechas[0],
        "fin": fechas[-1],
        "dias": len(fechas),
        "v1_sesiones": total_v1,
        "v2_prioridades": total_v2,
        "v2_opciones": total_opciones,
        "clases_v1": sorted(x for x in clases_v1 if x),
        "clases_v2": sorted(x for x in clases_v2 if x),
        "clasificacion": clas,
        "faltas": faltas,
        "metricas": {
            "alternativa_100": n > 0 and faltas["alternativa"] == 0,
            "metrica_exito_100": n > 0 and faltas["metrica"] == 0,
            "citas_100": n > 0 and faltas["citas"] == 0,
            "parametros_con_procedencia_100": n > 0 and faltas["parametros"] == 0,
            "estado_id_100": n > 0 and faltas["estado"] == 0,
            "seguridad_dolor_100": n > 0 and faltas["seguridad"] == 0,
            "opciones_2_100": n > 0 and faltas["opciones"] == 0,
            "sin_regresiones": clas["regresion"] == 0,
            "sin_errores": clas["error"] == 0,
        },
        "gobernanza": _gobernanza(cn),
        "por_dia": dias,
    }


def _markdown(r: dict) -> str:
    m = r["metricas"]
    g = r["gobernanza"]
    lineas = [
        f"# Dual-run v1/v2 · {r['inicio']} a {r['fin']} ({r['dias']} días)",
        "",
        f"- v1: {r['v1_sesiones']} sesiones; v2: {r['v2_prioridades']} prioridades y "
        f"{r['v2_opciones']} opciones.",
        f"- Clasificación: mejora {r['clasificacion']['mejora']}, equivalente "
        f"{r['clasificacion']['equivalente']}, regresión {r['clasificacion']['regresion']}, "
        f"error {r['clasificacion']['error']}.",
        f"- Clases v1: {', '.join(r['clases_v1']) or '—'}.",
        f"- Clases v2: {', '.join(r['clases_v2']) or '—'}.",
        "",
        "## Métricas",
        "",
        "| Métrica | Resultado |",
        "|---|---|",
    ]
    for k, v in m.items():
        lineas.append(f"| `{k}` | {'OK' if v else 'FALLO'} |")
    lineas += [
        "",
        "## Gobernanza (no es un gate técnico)",
        "",
        f"- Criterios firmados: {g['criterios_firmados']}/{g['criterios']}.",
        f"- Reglas con verificación: {g['reglas_con_verificacion']}/{g['reglas']}.",
        f"- Versión de conocimiento: `{g['version_conocimiento']}`.",
        "",
    ]
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Dual-run v1/v2 y resumen de métricas (F9).")
    p.add_argument("--bd", default=db.RUTA_POR_DEFECTO)
    p.add_argument("--inicio")
    p.add_argument("--fin")
    p.add_argument("--dias", type=int, default=14)
    p.add_argument("--salida", default=os.path.join("data", "derived", "f9"))
    args = p.parse_args(argv)

    fechas = _fechas(args.inicio, args.fin, args.dias)
    cn = db.conectar(args.bd)
    try:
        r = resumir(cn, fechas, args.salida)
    finally:
        cn.close()
    os.makedirs(args.salida, exist_ok=True)
    base = f"dual_run_{r['inicio']}_{r['fin']}"
    with open(os.path.join(args.salida, base + ".json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(r, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    with open(os.path.join(args.salida, base + ".md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_markdown(r))
    print(f"Dual-run {r['inicio']}..{r['fin']}: {r['dias']} días, "
          f"v1 {r['v1_sesiones']} sesiones, v2 {r['v2_prioridades']} prioridades, "
          f"regresiones {r['clasificacion']['regresion']}, errores {r['clasificacion']['error']}")
    print(f"Informe: {os.path.join(args.salida, base + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
