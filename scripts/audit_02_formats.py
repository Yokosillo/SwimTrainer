#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Auditoria 02: que contiene realmente cada formato.

1) Cruza tipo de actividad con formato de fichero disponible.
2) Abre ficheros FIT (fitdecode) de cada disciplina y lista los mensajes
   y campos realmente presentes, para saber que se puede reconstruir.
3) Comprueba el contenido de los GPX (campos y resolucion temporal).
Solo LEE. Escribe informes/audit_02_formats.json
"""
from __future__ import annotations

import csv
import gzip
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORT = os.path.join(ROOT, "data", "export_2026-10-11")
OUT = os.path.join(ROOT, "informes")
ACTS = os.path.join(EXPORT, "activities")
os.makedirs(OUT, exist_ok=True)

import fitdecode  # noqa: E402
import gpxpy      # noqa: E402


def load_csv():
    with open(os.path.join(EXPORT, "activities.csv"), encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    header = rows[0]
    idx = {}
    for i, h in enumerate(header):
        idx.setdefault(h, i)
    recs = [r for r in rows[1:] if r and r[0].strip()]
    return header, idx, recs


def main():
    header, idx, recs = load_csv()

    def col(r, name):
        i = idx.get(name)
        return r[i] if i is not None and i < len(r) else ""

    tipo_fmt = defaultdict(Counter)
    por_tipo_ejemplos = defaultdict(list)
    for r in recs:
        t = col(r, "Tipo de actividad").strip() or "(vacio)"
        base = os.path.basename(col(r, "Nombre del archivo").strip())
        ext = ".fit.gz" if base.endswith(".fit.gz") else ".gpx.gz" if base.endswith(".gpx.gz") else ".gpx" if base.endswith(".gpx") else base.rsplit(".", 1)[-1]
        tipo_fmt[t][ext] += 1
        if len(por_tipo_ejemplos[t]) < 4:
            por_tipo_ejemplos[t].append((base, col(r, "Nombre de la actividad"), col(r, "Fecha de la actividad")))

    print("--- Formato de fichero por tipo de actividad ---")
    for t, c in sorted(tipo_fmt.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"  {t:14s} {dict(c)}")

    # ---------- FIT: que mensajes/campos existen de verdad ----------
    def fit_profile(path, gz=True):
        msgs = Counter()
        campos = defaultdict(Counter)
        n_records = 0
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rb") as fh:
            try:
                with fitdecode.FitReader(fh) as fit:
                    for frame in fit:
                        if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                            continue
                        name = frame.name
                        msgs[name] += 1
                        if name == "record":
                            n_records += 1
                            if n_records > 3000:
                                continue
                        for f in frame.fields:
                            if f.value is not None:
                                campos[name][f.name] += 1
            except Exception as e:  # noqa: BLE001
                return {"error": f"{type(e).__name__}: {e}", "msgs": dict(msgs), "campos": {k: dict(v) for k, v in campos.items()}}
        return {"msgs": dict(msgs), "n_records": n_records,
                "campos": {k: dict(v) for k, v in campos.items()}}

    # elige ejemplos: la natacion mas reciente de cada formato, y 1 de cada otra disciplina
    picks = []
    def newest(t, fmt_suffix):
        best = None
        for r in recs:
            if col(r, "Tipo de actividad").strip() != t:
                continue
            b = os.path.basename(col(r, "Nombre del archivo").strip())
            if fmt_suffix and not b.endswith(fmt_suffix):
                continue
            if best is None or col(r, "ID de actividad") > best[0]:
                best = (col(r, "ID de actividad"), b)
        return best

    for t in tipo_fmt:
        for sfx in tipo_fmt[t]:
            p = newest(t, sfx)
            if p:
                picks.append((t, sfx, p[1]))

    out = {"tipo_formato": {k: dict(v) for k, v in tipo_fmt.items()}, "fit": {}, "gpx": {}}
    print("\n--- Perfil FIT de ficheros de muestra ---")
    for t, sfx, base in picks:
        if not base.endswith(".fit.gz"):
            continue
        path = os.path.join(ACTS, base)
        prof = fit_profile(path)
        out["fit"][f"{t}|{base}"] = prof
        if "error" in prof:
            print(f"  {t:12s} {base:28s} ERROR {prof['error']}")
            continue
        print(f"  {t:12s} {base:28s} records={prof.get('n_records',0):6d}  mensajes={sorted(prof['msgs'])}")
        for m in ("length", "lap", "session", "set", "event"):
            if m in prof["campos"]:
                print(f"      {m}: {sorted(prof['campos'][m])}")
    # ---------- GPX ----------
    print("\n--- Perfil GPX de ficheros de muestra ---")
    for t, sfx, base in picks:
        if not base.endswith((".gpx", ".gpx.gz")):
            continue
        path = os.path.join(ACTS, base)
        try:
            opener = gzip.open if base.endswith(".gz") else open
            with opener(path, "rb") as fh:
                g = gpxpy.parse(fh)
            pts = sum(len(seg.points) for trk in g.tracks for seg in trk.segments)
            exts = Counter()
            n_time = 0
            n_hr = 0
            n_pow = 0
            for trk in g.tracks:
                for seg in trk.segments:
                    for p in seg.points:
                        if p.time:
                            n_time += 1
                        for e in (p.extensions or []):
                            exts[e.tag.split("}")[-1]] += 1
                            if "hr" in e.tag:
                                n_hr += 1
                            if "power" in e.tag:
                                n_pow += 1
            info = {"points": pts, "con_tiempo": n_time, "extensiones": dict(exts), "n_hr": n_hr, "n_pow": n_pow,
                    "name": g.name, "time": str(g.time), "rutas": len(g.tracks)}
            out["gpx"][f"{t}|{base}"] = info
            print(f"  {t:12s} {base:22s} pts={pts:6d} con_tiempo={n_time:6d} ext={dict(exts)}")
        except Exception as e:  # noqa: BLE001
            print(f"  {t:12s} {base:22s} ERROR {type(e).__name__}: {e}")
            out["gpx"][f"{t}|{base}"] = {"error": str(e)}

    with open(os.path.join(OUT, "audit_02_formats.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("\nEscrito:", os.path.join(OUT, "audit_02_formats.json"))


if __name__ == "__main__":
    main()
