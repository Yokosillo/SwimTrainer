"""Prueba suelta: la forma de una serie y lo que el sistema aprende de sus partes.

Se ejecuta con:  .venv/Scripts/python.exe pruebas/comprobar_forma.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from entrenador import aprendizaje, concepto, db, partes, series   # noqa: E402

fallos = []


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    print(("  [OK  ] " if condicion else "  [FALLO] ") + nombre + (f"  -> {detalle}" if detalle else ""))
    if not condicion:
        fallos.append(nombre)


def main() -> int:
    print("\n1. La forma de una serie, medida de sus ritmos")
    casos = [
        ("progresivo", [95, 93, 91, 89], "una serie que va a mas"),
        ("progresivo", [95, 93.5, 92, 89.4], "progresiva con el reloj bailando"),
        ("aflojando", [88, 90, 92, 94], "cada una mas lenta"),
        ("regular", [90, 90.4, 89.7, 90.2], "todas iguales"),
        ("cambiando", [88, 96, 88, 96], "fuerte-suave alternando"),
        ("en_v", [95, 90, 95, 100], "rapida en el medio"),
    ]
    for esperado, ritmos, nombre in casos:
        e = concepto.medir(ritmos)
        comprobar(f"{nombre} ({ritmos})", e["concepto"] == esperado, str(e["concepto"]))
    e = concepto.medir([90, 90.2])
    comprobar("con dos repeticiones no se inventa una forma", e["concepto"] is None, str(e.get("motivo")))
    e = concepto.medir([95, 60, 91, 89], malos=(1,))
    comprobar("un largo con el cronometro mal disparado no cuenta para la forma",
              e["concepto"] == "progresivo" and e["ritmos"] == [95.0, 91.0, 89.0], str(e["ritmos"]))
    e = concepto.medir([95, 93, 91, 89], margen=3.0)
    comprobar("con un margen mas ancho (el que ha aprendido) lo que baja poco es regular",
              e["concepto"] == "regular", str(e["concepto"]))
    comprobar("la forma se cuenta en una linea",
              concepto.forma(concepto.medir([95, 93, 91, 89])) == "Progresiva: 6,0 s/100 mas rapida de la primera a la ultima",
              concepto.forma(concepto.medir([95, 93, 91, 89])))

    print("\n2. Lo que aprende de sus propios partes")
    cn = db.conectar()
    d = aprendizaje.aprender(cn)
    comprobar("mide con sus partes (no esta vacio)", d["partes"] > 0 and d["bloques"] > 0, f"{d['partes']} partes")
    comprobar("el margen de los tiempos sale de sus bloques", d["margen_s_100"] > 0
              and d["ruido"]["basado_en"] > 0, str(d["ruido"]))
    comprobar("aprende cuanto descanso sigue siendo la misma serie",
              d["agrupacion"]["descanso_mismo_bloque_s"] <= series.DESCANSO_MAX_S
              and d["agrupacion"]["basado_en"] > 0, str(d["agrupacion"]))
    comprobar("los conceptos se cuentan con la intensidad a la que los usa",
              isinstance(d["conceptos"]["cuenta"], dict) and d["conceptos"]["n_bloques_medidos"] >= 8,
              str(d["conceptos"]["cuenta"]))
    comprobar("y queda guardado para la proxima pasada",
              aprendizaje.leer().get("margen_s_100") == d["margen_s_100"], aprendizaje.RUTA)

    print("\n3. Agrupa con lo aprendido")
    comprobar("el tope de descanso del importe es el suyo (no el fijo de 180 s)",
              abs(series.descanso_max_serie() - aprendizaje.descanso_mismo_bloque()) < 0.01,
              f"{series.descanso_max_serie()} s")
    comprobar("y el del parte, el mismo",
              abs(partes.descanso_max_grupo() - aprendizaje.descanso_mismo_bloque()) < 0.01,
              f"{partes.descanso_max_grupo()} s")
    # Dos series iguales de 4x50 progresivas, con un descanso largo en medio: dos series, las dos progresivas.
    laps = []
    for i in range(4):
        laps.append({"dist_m": 50.0, "timer_s": 60.0 - i})
    laps.append({"dist_m": 0.0, "timer_s": 600.0})
    for i in range(4):
        laps.append({"dist_m": 50.0, "timer_s": 58.0 - i})
    ss = series.reconstruir_series(laps)
    comprobar("un descanso largo parte las series", len(ss) == 2, str(len(ss)))
    comprobar("y cada una lleva su forma medida",
              [s["concepto"] for s in ss] == ["progresivo", "progresivo"], str([s["concepto"] for s in ss]))
    del_e = ss[0]["concepto_evidencia"]
    comprobar("con lo que mejora la repeticion (quien firma el bloque progresivo)",
              del_e["ganancia_s_100"] > 0 and del_e["reps_fuera_de_la_tendencia"] == [], str(del_e))

    print("\n4. Lo que sale en el portal")
    p = partes.partes_de(cn, limite=6)
    medidas = [s for g in p for s in g["series"] if s.get("concepto")]
    comprobar("los partes ya subidos enseñan la forma al leerlos (no se guarda: sale de los tiempos)",
              len(medidas) >= 1, f"{len(medidas)} bloques")
    ppa = partes.datos_panel(cn)
    comprobar("el portal recibe los nombres de las formas",
              len(ppa.get("conceptos") or []) == len(concepto.CONCEPTOS), str(len(ppa.get("conceptos") or [])))
    comprobar("y lo que ha aprendido, con su fecha",
              bool((ppa.get("aprendizaje") or {}).get("generado"))
              and ppa["aprendizaje"]["margen_s_100"] > 0, str(ppa.get("aprendizaje")))
    cn.close()

    print("\n" + (f"{len(fallos)} fallos: " + ", ".join(fallos) if fallos else "Todo bien."))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
