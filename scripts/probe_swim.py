#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Volcado detallado de UNA sesion de natacion (para entender la estructura).

Uso: .venv/Scripts/python.exe scripts/probe_swim.py <fichero.fit.gz>
"""
from __future__ import annotations

import gzip
import os
import sys

import fitdecode

path = sys.argv[1]
opener = gzip.open if path.endswith(".gz") else open
laps = []
lengths = []
with opener(path, "rb") as fh:
    with fitdecode.FitReader(fh) as fit:
        for fr in fit:
            if fr.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            if fr.name == "lap":
                laps.append({
                    "idx": fr.get_value("message_index"),
                    "start": fr.get_value("start_time"),
                    "dist": fr.get_value("total_distance"),
                    "timer": fr.get_value("total_timer_time"),
                    "elapsed": fr.get_value("total_elapsed_time"),
                    "n_len": fr.get_value("num_lengths"),
                    "n_act": fr.get_value("num_active_lengths"),
                    "first_len": fr.get_value("first_length_index"),
                    "stroke": str(getattr(fr.get_value("swim_stroke"), "value", fr.get_value("swim_stroke"))),
                    "hr_avg": fr.get_value("avg_heart_rate"),
                    "hr_max": fr.get_value("max_heart_rate"),
                    "trigger": str(getattr(fr.get_value("lap_trigger"), "value", fr.get_value("lap_trigger"))),
                    "strokes": fr.get_value("total_strokes"),
                    "swolf": fr.get_value("avg_stroke_distance"),
                })
            elif fr.name == "length":
                lengths.append({
                    "idx": fr.get_value("message_index"),
                    "type": str(getattr(fr.get_value("length_type"), "value", fr.get_value("length_type"))),
                    "stroke": str(getattr(fr.get_value("swim_stroke"), "value", fr.get_value("swim_stroke"))),
                    "timer": fr.get_value("total_timer_time"),
                    "elapsed": fr.get_value("total_elapsed_time"),
                    "strokes": fr.get_value("total_strokes"),
                    "cad": fr.get_value("avg_swimming_cadence"),
                    "speed": fr.get_value("avg_speed"),
                    "start": fr.get_value("start_time"),
                })

print(f"FICHERO: {path}")
print(f"laps={len(laps)} lengths={len(lengths)}")
print("\n--- LAPS ---")
print(f"{'i':>3} {'inicio':>8} {'dist':>7} {'timer':>7} {'elaps':>7} {'nlen':>5} {'nact':>5} {'1stlen':>6} {'estilo':>12} {'FC':>5} {'FCmax':>5} {'trig':>8} {'braz':>5}")
for l in laps:
    ini = l["start"].strftime("%H:%M:%S") if l["start"] else "?"
    print(f"{l['idx']:>3} {ini:>8} {str(l['dist']):>7} {str(l['timer']):>7} {str(l['elapsed']):>7} {str(l['n_len']):>5} {str(l['n_act']):>5} {str(l['first_len']):>6} {l['stroke']:>12} {str(l['hr_avg']):>5} {str(l['hr_max']):>5} {l['trigger']:>8} {str(l['strokes']):>5}")

print("\n--- LENGTHS (largos) ---")
print(f"{'i':>4} {'tipo':>7} {'estilo':>12} {'timer':>7} {'elaps':>7} {'braz':>5} {'cad':>5}")
for x in lengths:
    print(f"{x['idx']:>4} {x['type']:>7} {x['stroke']:>12} {str(x['timer']):>7} {str(x['elapsed']):>7} {str(x['strokes']):>5} {str(x['cad']):>5}")
