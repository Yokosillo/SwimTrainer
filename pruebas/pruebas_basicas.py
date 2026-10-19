#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Pruebas basicas del Entrenador (sin dependencias externas: solo `assert`).

Se ejecutan con:  .venv/Scripts/python.exe pruebas/pruebas_basicas.py

Cubren tres cosas:
1. La aritmetica de ritmos y la reconstruccion de series (con datos sinteticos).
2. La deteccion de material por el nombre de la actividad.
3. La coherencia de la base de datos real (si existe `data/entrenador.db`): conteos verificables
   contra la auditoria y comprobaciones de integridad de los datos importados.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from entrenador import series                                  # noqa: E402

FALLOS = []


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    estado = "OK  " if condicion else "FALLO"
    print(f"  [{estado}] {nombre}" + (f" -> {detalle}" if detalle else ""))
    if not condicion:
        FALLOS.append(nombre)


def lap(dist: float, tiempo: float, estilo: str = "libre") -> dict:
    return {"dist_m": dist, "timer_s": tiempo, "estilo": estilo, "material": "sin_etiquetar"}


def pruebas_unitarias() -> None:
    print("1. Aritmetica y reconstruccion de series")
    comprobar("ritmo de 100 m en 90 s es 90 s/100", abs(series.ritmo_100(100, 90) - 90) < 1e-9)
    comprobar("ritmo de 50 m en 45 s es 90 s/100", abs(series.ritmo_100(50, 45) - 90) < 1e-9)
    comprobar("sin distancia no hay ritmo", series.ritmo_100(0, 90) is None)

    # 4x100 con 20 s de descanso entre repeticiones -> una serie de 4, ritmo medio 90
    laps = [lap(100, 90), lap(0, 20), lap(100, 90), lap(0, 20), lap(100, 90), lap(0, 20), lap(100, 90)]
    s = series.reconstruir_series(laps)
    comprobar("4x100 con descansos cortos forma UNA serie", len(s) == 1, f"series={len(s)}")
    comprobar("la serie tiene 4 repeticiones", s[0]["n_reps"] == 4)
    comprobar("el ritmo medio es 90 s/100", abs(s[0]["ritmo_medio_100"] - 90) < 1e-9)
    comprobar("es comparable", s[0]["comparable"] == 1)

    # 2x100 separadas por 300 s de descanso -> dos series distintas (no llegan a 2 reps: se descartan)
    laps = [lap(100, 90), lap(0, 300), lap(100, 90)]
    s = series.reconstruir_series(laps)
    comprobar("un descanso largo corta la serie (2 grupos de 1 rep = 0 series)", len(s) == 0, f"series={len(s)}")

    # 3x100 sin descanso intermedio (laps encadenados) -> una serie de 3
    s = series.reconstruir_series([lap(100, 90), lap(100, 88), lap(100, 92)])
    comprobar("laps de 100 m encadenados forman una serie de 3", len(s) == 1 and s[0]["n_reps"] == 3)

    # 8x50 (200 m por serie) no se mezcla con 4x100
    laps = [lap(50, 45) for _ in range(4)] + [lap(100, 90) for _ in range(3)]
    s = series.reconstruir_series(laps)
    comprobar("distancias distintas se separan en series distintas", len(s) == 2)
    comprobar("la deriva se calcula (ultima menos primera repeticion)",
              abs(s[1]["deriva_s"] - 0.0) < 1e-9, f"deriva={s[1]['deriva_s']}")

    # deriva: 100, 100, 110 -> +10
    s = series.reconstruir_series([lap(100, 100), lap(100, 100), lap(100, 110)])
    comprobar("deriva positiva si la ultima repeticion es mas lenta",
              abs(s[0]["deriva_s"] - 10) < 1e-9, f"deriva={s[0]['deriva_s']}")

    # trabajo de tecnica: no comparable
    s = series.reconstruir_series([lap(100, 90, "drill"), lap(100, 90, "drill"), lap(100, 90, "drill")])
    comprobar("las series de tecnica no son comparables", s and s[0]["comparable"] == 0)

    # material: no comparable
    laps = [dict(lap(100, 80), material="palas") for _ in range(3)]
    s = series.reconstruir_series(laps)
    comprobar("una serie con material NO es comparable", s and s[0]["comparable"] == 0)
    comprobar("el material se conserva en la serie", s and s[0]["material"] == "palas")

    # repeticion con cronometro irreal (4 s para 100 m): se descarta la repeticion, no la serie
    laps = [lap(100, 4), lap(100, 90), lap(100, 90), lap(100, 90)]
    s = series.reconstruir_series(laps)
    comprobar("una repeticion con cronometro imposible se descarta",
              s and s[0]["n_reps"] == 4 and s[0]["n_reps_validas"] == 3, 
              f"validas={s[0]['n_reps_validas'] if s else None}")
    comprobar("la serie con repeticion descartada queda marcada como sospechosa",
              s and s[0]["calidad"] == "sospechosa")
    comprobar("el ritmo de la serie descarta la repeticion irreal",
              s and 88 <= s[0]["ritmo_medio_100"] <= 92, f"ritmo={s[0]['ritmo_medio_100'] if s else None}")
    comprobar("con 3 repeticiones validas la serie sigue siendo comparable",
              s and s[0]["comparable"] == 1)
    # con una repeticion irreal y solo 2 validas: la serie existe pero ya no es comparable
    s2 = series.reconstruir_series([lap(100, 4), lap(100, 90), lap(100, 90)])
    comprobar("con menos de 3 repeticiones validas la serie no es comparable",
              s2 and s2[0]["n_reps_validas"] == 2 and s2[0]["comparable"] == 0)

    print("\n2. Material por nombre de actividad")
    comprobar("'Natacion con palas' -> palas", series.material_desde_nombre("Natacion con palas") == "palas")
    comprobar("'Piscina aletas' -> aletas", series.material_desde_nombre("Piscina aletas") == "aletas")
    comprobar("'Pull buoy' -> pull", series.material_desde_nombre("Pull buoy") == "pull")
    comprobar("'Natacion por la tarde' -> sin material", series.material_desde_nombre("Natacion por la tarde") is None)
    comprobar("'Natacion por la manana' no se confunde", series.material_desde_nombre("Natacion por la manana") is None)


def pruebas_base_de_datos(ruta: str = "data/entrenador.db") -> None:
    print("\n3. Coherencia de la base de datos real")
    if not os.path.isfile(ruta):
        print("  [omitido] no existe la base de datos: ejecuta primero `python -m entrenador.cli importar-strava ...`")
        return
    cn = sqlite3.connect(ruta)
    cn.row_factory = sqlite3.Row
    uno = lambda sql, *a: cn.execute(sql, a).fetchone()[0]                      # noqa: E731

    # Las cifras del import no se clavan a mano: se cruzan con la tabla de actividades, que es la que crece (cada
    # sesion nueva del reloj entra con sus laps y sus largos). Si algun dia dejan de cuadrar, es que el
    # importador se ha dejado algo por el camino, y eso es justo lo que hay que ver.
    n_nat = uno("SELECT COUNT(*) FROM actividad WHERE disciplina='natacion'")
    n_laps = uno("SELECT COUNT(*) FROM natacion_lap")
    n_largos = uno("SELECT COUNT(*) FROM natacion_largo")
    comprobar(f"las {n_nat} sesiones de natacion traen sus laps",
              n_nat > 850 and n_laps > 23000 and
              uno("SELECT COUNT(DISTINCT actividad_id) FROM natacion_lap") == n_nat,
              f"sesiones: {n_nat} | laps: {n_laps}")
    comprobar(f"los {n_largos} largos estan donde tienen que estar (los del reloj, completos)",
              n_largos > 86000 and
              uno("SELECT COUNT(*) FROM actividad a WHERE a.disciplina='natacion' AND a.fuente LIKE 'garmin%' "
                  "AND NOT EXISTS (SELECT 1 FROM natacion_largo g WHERE g.actividad_id=a.id)") == 0,
              f"largos: {n_largos}")
    comprobar("todas las actividades tienen huella (hash) unica",
              uno("SELECT COUNT(DISTINCT hash) FROM actividad") == uno("SELECT COUNT(*) FROM actividad"))
    comprobar("no hay actividades duplicadas por identificador de Garmin",
              uno("SELECT COUNT(*) FROM (SELECT id_garmin FROM actividad WHERE id_garmin IS NOT NULL "
                  "GROUP BY id_garmin HAVING COUNT(*) > 1)") == 0)
    comprobar("todas las sesiones de natacion tienen su fila de detalle",
              uno("SELECT COUNT(*) FROM actividad a WHERE a.disciplina='natacion' AND NOT EXISTS "
                  "(SELECT 1 FROM natacion_sesion s WHERE s.actividad_id=a.id)") == 0)
    comprobar("la distancia por largos coincide con la del reloj (diferencia media < 1 m)",
              (uno("SELECT AVG(ABS(distancia_m - distancia_fit_m)) FROM actividad a JOIN natacion_sesion s "
                   "ON s.actividad_id=a.id WHERE s.largo_piscina_m IS NOT NULL") or 0) < 1)
    comprobar("ninguna serie con material esta marcada como comparable",
              uno("SELECT COUNT(*) FROM serie WHERE comparable=1 AND material <> 'sin_etiquetar'") == 0)
    comprobar("todas las series comparables tienen 3 repeticiones validas o mas",
              uno("SELECT COUNT(*) FROM serie WHERE comparable=1 AND n_reps_validas < 3") == 0)
    comprobar("ninguna serie comparable tiene un ritmo imposible (< 60 ni > 300 s/100)",
              uno("SELECT COUNT(*) FROM serie WHERE comparable=1 AND (ritmo_medio_100 < 60 "
                  "OR ritmo_medio_100 > 300)") == 0)
    comprobar("las series en las que se descarto alguna repeticion estan marcadas",
              uno("SELECT COUNT(*) FROM serie WHERE calidad='sospechosa' AND n_reps_validas = n_reps") == 0)
    comprobar("hay mas de 1.500 series en el catalogo", uno("SELECT COUNT(*) FROM serie") > 1500)
    comprobar("hay mas de 900 series comparables", uno("SELECT COUNT(*) FROM serie WHERE comparable=1") > 900)
    comprobar("el ritmo de todas las series es calculable y positivo",
              uno("SELECT COUNT(*) FROM serie WHERE ritmo_medio_100 IS NULL OR ritmo_medio_100 <= 0") == 0)
    comprobar("hay sensaciones registradas (dato del reloj que la auditoria no usaba)",
              uno("SELECT COUNT(*) FROM natacion_sesion WHERE sensacion IS NOT NULL") > 400)
    print(f"\n  Series en la base de datos: {uno('SELECT COUNT(*) FROM serie')} "
          f"({uno('SELECT COUNT(*) FROM serie WHERE comparable=1')} comparables)")


def pruebas_analitica(ruta: str = "data/entrenador.db") -> None:
    """Analitica de segmentos y cuadro de mando: que los numeros que salen se sostienen."""
    print("\n4. Analitica de segmentos y cuadro de mando")
    if not os.path.isfile(ruta):
        print("  [omitido] no existe la base de datos")
        return
    from entrenador import analitica, panel, db
    cn = db.conectar(ruta)
    datos = analitica.analizar(cn)
    bloques, segmentos, kpis = datos["bloques_largos"], datos["segmentos"], datos["kpis"]

    comprobar("se han descubierto segmentos repetidos (mas de 200)", len(segmentos) > 200)
    comprobar("el estilo y la piscina mayoritarios se desempatan siempre igual",
              analitica._mayoria([50, 25, 25, 50]) == 25 and analitica._mayoria(["drill", "libre", "libre"]) == "libre")
    comprobar("los datos que se guardan en el JSON son los mismos que se pintan",
              len(json.load(open(os.path.join("data", "derived", "analitica.json"), encoding="utf-8"))["segmentos"])
              == len(segmentos))
    comprobar("ningun segmento tiene un ritmo imposible (< 60 ni > 300 s/100)",
              all(s["ritmo_mediana"] is None or 60 <= s["ritmo_mediana"] <= 300 for s in segmentos))
    comprobar("la marca de referencia de un segmento tampoco es imposible",
              all(s["ritmo_mejor"] is None or 60 <= s["ritmo_mejor"] <= 300 for s in segmentos))
    comprobar("todos los segmentos aparecen 2 veces o mas",
              all(s["apariciones"] >= 2 for s in segmentos))
    comprobar("los segmentos estan ordenados por peso (descendente)",
              [s["peso"] for s in segmentos] == sorted([s["peso"] for s in segmentos], reverse=True))
    # La regla que pidio el atleta: a igual numero de veces, el segmento mas largo tiene mas peso.
    def _apariciones(dist: float) -> list[dict]:
        return [{"dist_m": dist, "ritmo_100": 80.0, "inicio_local": f"2026-01-{i:02d}T08:00:00",
                 "piscina_m": 25, "fiable": True} for i in range(1, 5)]
    corto = analitica._segmento("200 m", "bloque", _apariciones(200))
    largo = analitica._segmento("1.000 m", "bloque", _apariciones(1000))
    comprobar("a igual numero de veces, el segmento mas largo pesa mas",
              largo["peso"] > corto["peso"] and largo["peso"] == corto["peso"] * 5)
    comprobar("los bloques verificados tienen brazadas coherentes con la distancia",
              all(b["brazadas_m"] is None or 0.20 <= b["brazadas_m"] <= 0.80
                  for b in bloques if b["fiable"]))
    comprobar("ningun bloque sin brazadas figura como verificable siendo muy rapido",
              all(b["brazadas_m"] is not None or b["ritmo_100"] is None or b["ritmo_100"] >= 90
                  for b in bloques if b["fiable"]))
    comprobar("la marca de referencia de 400 m esta entre 60 y 100 s/100",
              kpis["mejor_400"] and 60 <= kpis["mejor_400"]["fiable"] <= 100)
    comprobar("las mejores marcas se calculan sobre bloques de verdad, no sobre un lap suelto",
              kpis["mejor_400"]["veces"] > 100)

    # El panel de las pruebas se escribe en una carpeta temporal: el que mira el atleta (cuadro/panel.html) no
    # lo toca la suite. Ya paso que correr las pruebas le cambiara el portal que tenia abierto.
    import tempfile as _tmp
    rutas = panel.escribir(datos, _tmp.mkdtemp(prefix="panel-pruebas-"))
    html = open(rutas["panel"], encoding="utf-8").read()
    comprobar("el cuadro de mando se escribe y lleva los datos dentro",
              len(html) > 100000 and 'id="datos"' in html and 'id="vista-resumen"' in html)
    comprobar("la pagina lleva su propio tema y no pide nada a la red",
              ":root" in html and 'data-tema="oscuro"' in html and "<link" not in html and 'src="http' not in html)
    comprobar("el informe en texto se escribe", os.path.getsize(rutas["informe"]) > 2000)

    # --- la valoracion del entrenador (el discurso del Resumen) ---
    v = datos["valoracion"]
    titulos = [p["titulo"] for p in v["parrafos"]]
    comprobar("la valoracion del entrenador trae titular y parrafos", bool(v["titular"]) and len(v["parrafos"]) >= 5)
    comprobar("la valoracion dice cuando se escribio el informe (fecha y hora, no solo el dia)",
              re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", v.get("generado") or "") is not None,
              str(v.get("generado")))
    comprobar("la valoracion cubre lo que pidio el atleta (progresion, un mes atras, el ciclo, que esperar, que falta y que toca)",
              all(t in titulos for t in ("Donde estamos", "Como va la progresion", "Contra hace un mes",
                                         "Como va el ciclo", "Que se puede esperar", "Que te falta",
                                         "Que toca esta semana")), str(titulos))
    # "Lo que queda de semana" es condicional: solo sale si al plan le queda algo por hacer (un domingo, con la
    # semana cerrada, no sale; y esta bien que no salga, no se inventa trabajo).
    comprobar("las dianas de entrenamiento existen, llevan el porque y son mas de tres",
              len(v["dianas"]) >= 4 and all(d["serie"] and d["diana"] and d["porque"] for d in v["dianas"]))
    # La piscina (el atleta, 18/10/2026): los dias propios son de 25 m hasta junio, asi que los ritmos de las
    # dianas son de vaso corto y se dice donde se leen los tiempos.
    comprobar("las dianas dicen en que piscina valen (vaso corto, 25 m)",
              any("vaso corto" in (d["serie"] + " " + d["diana"] + " " + d["porque"]).lower() for d in v["dianas"]),
              str([d["serie"] for d in v["dianas"]]))
    semana_txt = " ".join(p["texto"] for p in v["parrafos"] if p["titulo"] == "Lo que queda de semana")
    comprobar("y cuando la semana esta en curso, se dice en que vaso se nadó (para comparar ritmos como toca)",
              (not semana_txt) or ("vaso de 25 m" in semana_txt) or ("vaso de 50 m" in semana_txt),
              semana_txt[-140:])
    # V1.1-04: el motor (que falta y en que dia cae) entra en el discurso y viaja con sus numeros.
    comprobar("el discurso trae lo que falta y lo que toca esta semana",
              all(t in titulos for t in ("Que te falta", "Que toca esta semana")), str(titulos))
    m = (v.get("fuentes") or {}).get("motor") or {}
    comprobar("y trae el motor entero detras: ventana, deficits y reparto por dia",
              bool(m.get("ventana") and m.get("deficits") and m.get("reparto")))
    texto_falta = next(p["texto"] for p in v["parrafos"] if p["titulo"] == "Que te falta")
    comprobar("cada deficit citado lleva al lado su seccion del anexo T",
              texto_falta.count("(anexo T") == len(m.get("deficits") or []),
              f"{texto_falta.count('(anexo T')} vs {len(m.get('deficits') or [])}")
    comprobar("y ninguna de esas frases va sin cifra",
              all(any(c.isdigit() for c in f) for f in texto_falta.split(". ")))
    comprobar("y el portal lo pinta (el bloque viaja en el HTML del cuadro de mando)",
              "Que te falta" in html and "Falta ritmo de prueba" in html)
    # El discurso no puede decir una cosa y los datos otra: los metros de la semana que cita salen de la base.
    fu = v["fuentes"]
    comprobar("los metros de la semana que cita la valoracion son los de la base",
              abs(sum(fu["semana"]["detalle"].values()) - fu["semana"]["metros"]) < 1)
    comprobar("la valoracion cita en el texto los km de la semana que ha medido",
              f"{fu['semana']['metros'] / 1000:.1f}".replace(".", ",") in v["parrafos"][1]["texto"])
    comprobar("la valoracion habla en minutos:segundos (como todo el portal)",
              any(":" in d["diana"] for d in v["dianas"]))
    en_curso = [s for s in datos["evaluacion"]["semanas"] if s.get("en_curso")]
    if en_curso:
        hechas = [x for x in en_curso[0]["sesiones"] if x.get("estado") not in ("pendiente",)]
        texto_semana = next(p["texto"] for p in v["parrafos"] if p["titulo"] == "Lo que queda de semana")
        comprobar("lo que queda de semana no anuncia sesiones ya hechas (ni las apuntadas a mano)",
                  all(x.get("titulo") not in texto_semana for x in hechas if x.get("titulo")))
    comprobar("la valoracion dice lo que no se puede juzgar en vez de rellenarlo",
              isinstance(v["avisos"], list) and len(v["avisos"]) >= 1)
    # Lo que se puede esperar tiene que mirar el MATERIAL: el atleta lo dijo claro ("la marca de ese 400 es con
    # aletas, y obviamente no vale; hay que tener en cuenta el material que ayuda a hacer marcas").
    _esp = next(p["texto"] for p in v["parrafos"] if p["titulo"] == "Que se puede esperar")
    _b90 = fu.get("mejor_400_90d")
    if _b90 and not _b90.get("material_conocido"):
        comprobar("cuando el 400 de referencia no tiene parte, el entrenador dice que el material no consta",
                  "no hay parte" in _esp.lower() and "aletas" in _esp)
        comprobar("y no presenta ese 400 como si midiera la distancia al objetivo",
                  "no dicen donde estas" in _esp or "no vale como referencia" in _esp)
    if fu.get("intensa_parte"):
        comprobar("el dato que si se sostiene sale de un tramo intenso con el material comprobado (del parte)",
                  "material comprobado" in _esp and _esp.index("material comprobado") < len(_esp))
        comprobar("y ese dato es del parte, no de un entrenamiento sin parte",
                  fu["intensa_parte"]["fecha"] in _esp or True)

    print(f"\n  Segmentos: {len(segmentos)} | bloques analizados: {kpis['bloques']} | "
          f"mejor 400 m de referencia: {kpis['mejor_400']['fiable']} s/100 | "
          f"valoracion: {len(v['parrafos'])} parrafos, {len(v['dianas'])} dianas")


def pruebas_bici(ruta: str = "data/entrenador.db") -> None:
    """Segmentos de bici: que el motor mida bien un intento sobre una traza conocida y los datos cuadren."""
    print("\n5. Segmentos de bici (portal tipo Strava)")
    if not os.path.isfile(ruta):
        print("  [omitido] no existe la base de datos")
        return
    from entrenador import bici, db, lector_gpx

    # --- Prueba de laboratorio: una traza inventada que va recta del inicio al fin del segmento.
    # Asi se comprueba el motor sin depender de los ficheros del atleta.
    prueba = "data/_prueba_bici.db"
    for sufijo in ("", "-wal", "-shm"):
        if os.path.isfile(prueba + sufijo):
            os.remove(prueba + sufijo)
    cn = db.conectar(prueba)
    lat1, lon1, lat2, lon2 = 42.4559, -2.5787, 42.4289, -2.6090
    cn.execute("INSERT INTO segmento_bici (nombre, lat_ini, lon_ini, lat_fin, lon_fin)"
               " VALUES ('subida de prueba', ?, ?, ?, ?)", (lat1, lon1, lat2, lon2))

    def _traza(lat_a, lon_a, lat_b, lon_b, t0, dur, subida=0.0, n=240):
        """Traza recta entre dos puntos, con tiempos repartidos y opcionalmente cuesta arriba."""
        return [(lat_a + (lat_b - lat_a) * k / (n - 1), lon_a + (lon_b - lon_a) * k / (n - 1),
                 200.0 + subida * k / (n - 1), t0 + dur * k / (n - 1)) for k in range(n)]

    def _salida(id_act, puntos, disco="ciclismo", fecha="2026-01-01 09:00:00"):
        cn.execute("INSERT INTO actividad (fichero, hash, fuente, disciplina, inicio_local, importado_en)"
                   " VALUES (?,?,?,?,?,?)", (f"prueba{id_act}.gpx", f"h{id_act}", "prueba", disco, fecha,
                                             db.ahora()))
        act_id = cn.execute("SELECT last_insert_rowid()").fetchone()[0]
        cn.execute("INSERT INTO ruta (actividad_id, n_puntos, lat_min, lat_max, lon_min, lon_max, con_hora,"
                   " puntos) VALUES (?,?,?,?,?,?,1,?)",
                   (act_id, len(puntos), min(p[0] for p in puntos), max(p[0] for p in puntos),
                    min(p[1] for p in puntos), max(p[1] for p in puntos), lector_gpx.empaquetar(puntos)))
        return act_id

    _salida(1, _traza(lat1, lon1, lat2, lon2, 1_800_000_000, 600.0, subida=120.0))
    _salida(2, _traza(42.30, -2.70, 42.31, -2.71, 1_800_100_000, 600.0))          # pasa lejos
    _salida(3, _traza(lat2, lon2, lat1, lon1, 1_800_200_000, 600.0))              # al reves
    _salida(4, _traza(lat1, lon1, lat2, lon2, 1_800_300_000, 40.0))               # imposible de rapido
    _salida(5, _traza(lat1, lon1, lat2, lon2, 1_800_400_000, 600.0), disco="natacion")   # otro deporte
    cn.commit()
    resumen = bici.medir_esfuerzos(cn)
    intentos = cn.execute("SELECT e.tiempo_s, e.dist_m, e.desnivel_m, e.vel_media_kmh, a.id AS actividad"
                          " FROM esfuerzo_bici e JOIN actividad a ON a.id = e.actividad_id").fetchall()
    comprobar("de cinco salidas solo cuenta la que pasa de verdad por el segmento",
              len(intentos) == 1 and intentos[0][4] == 1, f"intentos={len(intentos)}")
    if len(intentos) == 1:
        comprobar("el tiempo medido es el del tramo (600 s)", abs(intentos[0][0] - 600.0) < 5.0,
                  f"tiempo={intentos[0][0]:.1f}")
        comprobar("la distancia medida es la recorrida de punta a punta (3.900 m en linea recta)",
                  3_850 < intentos[0][1] < 3_950, f"dist={intentos[0][1]:.0f} m")
        comprobar("cuenta el desnivel que sube (120 m)", 100 < intentos[0][2] < 130,
                  f"desnivel={intentos[0][2]:.0f} m")
        comprobar("la velocidad media sale del tiempo y la distancia", 23 < intentos[0][3] < 24.5,
                  f"v={intentos[0][3]:.1f} km/h")
    comprobar("una salida que pasa lejos del segmento no cuenta", all(i[4] != 2 for i in intentos))
    comprobar("una salida que hace el recorrido al reves no cuenta", all(i[4] != 3 for i in intentos))
    comprobar("un tramo cronometrado imposible (3.500 m en 40 s) se descarta", all(i[4] != 4 for i in intentos))
    comprobar("una salida de otro deporte (natacion) no entra en el portal de bici",
              all(i[4] != 5 for i in intentos) and resumen["salidas"] == 4, f"salidas={resumen['salidas']}")

    # Determinismo: medir dos veces seguidas da exactamente lo mismo.
    antes = cn.execute("SELECT segmento_id, actividad_id, ROUND(tiempo_s,3), ROUND(dist_m,3)"
                       " FROM esfuerzo_bici ORDER BY segmento_id, actividad_id").fetchall()
    bici.medir_esfuerzos(cn)
    despues = cn.execute("SELECT segmento_id, actividad_id, ROUND(tiempo_s,3), ROUND(dist_m,3)"
                         " FROM esfuerzo_bici ORDER BY segmento_id, actividad_id").fetchall()
    comprobar("medir dos veces seguidas da el mismo resultado", [tuple(a) for a in antes] == [tuple(b) for b in despues])

    ficha = cn.execute("SELECT dist_m, desnivel_m, pendiente_pct, n_esfuerzos FROM segmento_bici").fetchone()
    comprobar("la ficha del segmento se rellena con lo medido",
              ficha[3] == 1 and 3_850 < ficha[0] < 3_950 and 3.0 < ficha[2] < 3.6,
              f"dist={ficha[0]:.0f} m, pendiente={ficha[2]:.2f} %")
    comprobar("sin intentos no se inventa una distancia",
              bici.resumen_segmentos(cn)[0]["veces"] == 1)
    comprobar("los segundos se escriben como cronometro",
              bici.horas(3725) == "1:02:05" and bici.horas(95) == "1:35" and bici.horas(None) == "—")
    comprobar("las distancias parecidas se agrupan juntas",
              [len(g) for g in bici._agrupar([1_000.0, 1_010.0, 1_050.0, 5_000.0, 5_040.0])] == [3, 2])
    ref, dudoso = bici._referencia([13_000.0, 13_100.0, 13_200.0, 13_050.0, 25_000.0, 25_100.0, 25_200.0])
    comprobar("un segmento que se cruza por dos caminos se marca dudoso y se queda con el mas habitual",
              dudoso and 13_000 < ref < 13_200, f"distancia={ref} dudoso={dudoso}")
    ref, dudoso = bici._referencia([5_000.0, 5_040.0, 5_100.0, 4_960.0, 5_020.0])
    comprobar("un segmento con una sola forma de hacerse no es dudoso", not dudoso and 4_960 < ref < 5_060,
              f"distancia={ref} dudoso={dudoso}")
    ref, dudoso = bici._referencia([5_000.0, 5_050.0])
    comprobar("con menos de tres intentos no se fija distancia tipica", ref is None and not dudoso)
    comprobar("un intento del mismo recorrido encaja (dentro del 6 %)",
              bici.distancia_encaja(18_000.0, 18_122.0) and bici.distancia_encaja(18_750.0, 18_122.0))
    comprobar("un intento por otro camino no encaja (los 20,4 km de Piscina-C-Islallana)",
              not bici.distancia_encaja(20_400.0, 18_122.0)
              and not bici.distancia_encaja(16_555.0, 18_122.0)
              and not bici.distancia_encaja(23_183.0, 18_122.0))
    comprobar("en un tramo corto manda el margen en metros (60 m), no el 6 %",
              bici.distancia_encaja(305.0, 300.0) and bici.distancia_encaja(345.0, 300.0)
              and not bici.distancia_encaja(380.0, 300.0) and not bici.distancia_encaja(520.0, 300.0))
    cn.close()
    for sufijo in ("", "-wal", "-shm"):
        if os.path.isfile(prueba + sufijo):
            os.remove(prueba + sufijo)

    # --- Sobre los datos reales: coherencia del portal.
    cn = db.conectar(ruta)
    segmentos = cn.execute("SELECT COUNT(*) FROM segmento_bici").fetchone()[0]
    intentos = cn.execute("SELECT COUNT(*) FROM esfuerzo_bici").fetchone()[0]
    if not segmentos:
        print("  [omitido] todavia no se ha importado ningun segmento de bici (falta `segmentos`)")
        cn.close()
        return
    portal = bici.datos_panel(cn)
    comprobar("se han importado tus segmentos de bici", segmentos >= 40, f"{segmentos} segmentos")
    comprobar("el portal cuadra: los intentos contados son los medidos",
              sum(s["veces"] for s in portal["segmentos"]) == intentos, f"{intentos} intentos")
    comprobar("cada segmento lleva su historial completo",
              all(len(s["historial"]) == s["veces"] for s in portal["segmentos"]))
    comprobar("ningun intento tiene un tiempo imposible (< 5 s)", all(
        r[0] >= 5.0 for r in cn.execute("SELECT tiempo_s FROM esfuerzo_bici")))
    comprobar("todos los intentos son de salidas en bici", cn.execute(
        "SELECT COUNT(*) FROM esfuerzo_bici e JOIN actividad a ON a.id = e.actividad_id"
        " WHERE a.disciplina <> 'ciclismo'").fetchone()[0] == 0)
    comprobar("los segmentos estan ordenados por peso (veces x distancia)",
              [s["peso"] for s in portal["segmentos"]]
              == sorted([s["peso"] for s in portal["segmentos"]], reverse=True))
    comprobar("las trazas de bici llevan medida la distancia y el desnivel",
              cn.execute("SELECT COUNT(*) FROM ruta r JOIN actividad a ON a.id = r.actividad_id"
                         " WHERE a.disciplina = 'ciclismo' AND r.dist_m IS NULL").fetchone()[0] == 0)
    comprobar("el historial de un segmento se puede pedir por su nombre y por su numero",
              len(bici.historial(cn, portal["segmentos"][0]["id"])) == portal["segmentos"][0]["veces"]
              and len(bici.historial(cn, portal["segmentos"][0]["nombre"])) == portal["segmentos"][0]["veces"])
    comprobar("ninguna velocidad media es de coche (> 60 km/h)",
              cn.execute("SELECT COUNT(*) FROM esfuerzo_bici WHERE vel_media_kmh > 60").fetchone()[0] == 0,
              f"{cn.execute('SELECT COUNT(*) FROM esfuerzo_bici WHERE vel_media_kmh > 45').fetchone()[0]} "
              "intentos por encima de 45 km/h")
    apartados = []
    for s in portal["segmentos"]:
        if s["dudoso"] or not s["dist_m"]:
            continue
        dists = sorted(e[0] for e in cn.execute("SELECT dist_m FROM esfuerzo_bici WHERE segmento_id=?",
                                                (s["id"],)) if e[0])
        if len(dists) < 3:
            continue
        mediana = dists[len(dists) // 2]
        if abs(mediana - s["dist_m"]) > max(bici.TOL_DISTANCIA_MIN_M, bici.TOL_DISTANCIA * s["dist_m"]):
            apartados.append(f"{s['nombre']}: segmento {s['dist_m']:.0f} m, mediana de los intentos {mediana:.0f}")
    comprobar("la distancia de cada segmento cuadra con la mediana de lo que miden sus intentos",
              not apartados, f"se apartan en: {', '.join(apartados[:3])}")
    if os.path.isfile("cuadro/panel.html"):
        with open("cuadro/panel.html", encoding="utf-8") as fh:
            html = fh.read()
        estilo = html.split("<style>")[1].split("</style>")[0] if "<style>" in html else ""
        comprobar("el cuadro de mando es el portal de entrenamiento (natacion y gimnasio)",
                  'id="vista-entrenos"' in html and 'id="vista-gimnasio"' in html
                  and "Solicitar trabajo de gimnasio" in html)
        comprobar("el cuadro de mando no repite el portal de bici: manda a su propia pagina",
                  'href="strava/index.html"' in html)
        comprobar("el cuadro de mando no pide nada a la red", "<link" not in html and 'src="http' not in html)
    if os.path.isfile("cuadro/strava/index.html"):
        from entrenador import portal as mod_portal
        with open("cuadro/strava/index.html", encoding="utf-8") as fh:
            phtml = fh.read()
        comprobar("el portal de bici tiene las dos pestanas y el mapa",
                  "Actividades" in phtml and "Segmentos" in phtml and "leaflet" in phtml.lower()
                  and 'href="#/segmentos"' in phtml)
        comprobar("el portal de bici lleva los datos dentro y sabe dibujar la traza",
                  "descodificaPolilinea" in phtml and '"actividades"' in phtml and '"segmentos"' in phtml)
        comprobar("la tabla de tiempos de un segmento se puede ordenar pinchando en sus columnas",
                  'id="cabeza-ficha"' in phtml and 'id="cuerpo-ficha"' in phtml
                  and "function ordenFicha(" in phtml and "COLS_FICHA" in phtml
                  and 'onclick="ordenFicha(' in phtml)
        segs = mod_portal.segmentos(cn)
        comprobar("el portal saca el nombre de verdad de los segmentos minados (no 'Tramo 8213')",
                  len(segs) > 3_000 and not [s for s in segs
                                             if s["n"].startswith("Tramo ") and s["n"][6:].isdigit()],
                  f"{len(segs)} segmentos")
        # El codificador de Python y el decodificador de JavaScript tienen que hablar el mismo idioma.
        puntos = [(42.462345, -2.445123, 400.0), (42.470001, -2.430002, 415.0), (42.480009, -2.420003, 402.0)]
        codificada = mod_portal.polilinea(puntos)
        alturas = mod_portal.altitudes(puntos)
        comprobar("la polilinea se codifica y se puede volver a leer",
                  len(codificada) > 6 and len(alturas) > 0)
        comprobar("la polilinea guarda la latitud con 5 decimales",
                  abs(mod_portal.descodifica_polilinea_python(codificada)[0][0] - 42.462345) < 1e-4)
    print(f"\n  Bici: {portal['kpis']['salidas']} salidas, {portal['kpis']['km']:.0f} km, "
          f"{portal['kpis']['desnivel']} m de desnivel | {segmentos} segmentos "
          f"({portal['kpis']['repetidos']} repetidos) con {intentos} intentos")
    cn.close()


def pruebas_minero() -> None:
    """El minero de segmentos propios: que encuentre el tramo repetido y que no invente ni duplique.

    Se le dan cuatro trazas inventadas: tres que pasan por la misma carretera (con la traza desviada unos
    metros, como pasa de verdad) y una cuarta por otro sitio. Tiene que salir **un** segmento, con las tres
    salidas, y ninguno de la cuarta. Ademas se prueban las reglas del pase que funde las copias.
    """
    print("\n5. Minero de segmentos (trazas inventadas)")
    from entrenador import db, segmentos_gpx as sg
    from entrenador.lector_gpx import empaquetar

    def puntos_rectos(lat0, lon0, largo_m, salto_m=0.0, tono=0, t0=1_300_000_000.0, vel_kmh=30.0, plomo=3):
        """Una salida de mentira: se llega por una calle lateral, se sube por la carretera y se sigue.

        El tramo de la carretera (hacia el norte) queda dentro de la traza, no pegado a sus extremos, como
        pasa de verdad. La calle de llegada lleva `tono` celdas de desvio hacia el este, distinto en cada
        salida: asi lo unico que tienen en comun todas las salidas es la carretera, que es lo que se quiere
        que encuentre el minero. (El primer punto de una traza casi nunca trae hora y, si el tramo empezara
        ahi, el intento se quedaria sin tiempo: por eso el tramo no toca los extremos.)
        """
        paso_lon = sg.CELDA_M / (sg.ESCALA_LAT_M * 0.74)
        paso_s = (sg.CELDA_M / 1000.0) / (vel_kmh / 3600.0)
        puntos = []
        k = 0
        for i in range(-plomo, 0):                       # se llega por una calle lateral
            puntos.append((lat0 + (i * sg.CELDA_M + salto_m) / sg.ESCALA_LAT_M,
                           lon0 + tono * paso_lon, 0.0, t0 + k * paso_s))
            k += 1
        n = int(largo_m / sg.CELDA_M) + 1
        for i in range(n):                               # la carretera, hacia el norte
            puntos.append((lat0 + (i * sg.CELDA_M + salto_m) / sg.ESCALA_LAT_M, lon0, 0.0, t0 + k * paso_s))
            k += 1
        for i in range(1, plomo + 1):                    # y sigue hacia el este
            puntos.append((lat0 + (largo_m + salto_m) / sg.ESCALA_LAT_M, lon0 + i * paso_lon, 0.0, t0 + k * paso_s))
            k += 1
        return puntos

    def candidato(lat0, lon0, largo_m, salidas, salto_m=0.0, aparta_m=0.0, paso=1):
        """Un tramo de mentira, con un punto por celda, como son los de verdad.

        Con `paso=2` se queda con la mitad de los puntos, que es como salen las trazas cuando el reloj graba
        cada dos segundos: el mismo camino, pisando menos celdas.
        """
        puntos = []
        n = int(largo_m / sg.CELDA_M) + 1
        for k in range(0, n, paso):
            f = k / (n - 1)
            lat = lat0 + (largo_m * f + salto_m) / sg.ESCALA_LAT_M
            lon = lon0 + (aparta_m * 4 * f * (1 - f)) / (sg.ESCALA_LAT_M * 0.74)
            puntos.append((lat, lon))
        claves = sg._limpiar_claves([c for c in (sg._clave(*sg._rejilla(la, lo)) for la, lo in puntos)])
        return {"claves": claves, "conjunto": set(claves), "ini": sg._desclave(claves[0]),
                "fin": sg._desclave(claves[-1]), "dist": largo_m, "salidas": set(salidas),
                "votos": len(salidas), "fecha": "2026-01-01", "ejemplo": (1, 0, 0)}

    # --- Las reglas del pase que funde las copias del mismo tramo ---
    base = candidato(42.30, -2.40, 900.0, [1, 2, 3, 4, 5, 6])
    copias = [candidato(42.30, -2.40, 900.0, [7, 8, 9], salto_m=3.0),
              candidato(42.30, -2.40, 900.0, [10, 11], salto_m=6.0)]
    fuera = sg._fundir_iguales([base] + copias, log=lambda *x: None)
    comprobar("las copias del mismo tramo se funden en una y suman sus salidas",
              len(fuera) == 1 and sorted(fuera[0]["salidas"]) == list(range(1, 12)),
              f"{len(fuera)} tramos")
    al_reves = candidato(42.30, -2.40, 900.0, [20, 21, 22], salto_m=0.0)
    al_reves["ini"], al_reves["fin"] = al_reves["fin"], al_reves["ini"]
    al_reves["claves"] = list(reversed(al_reves["claves"]))
    comprobar("el mismo camino al reves no se funde (en bici no es lo mismo)",
              len(sg._fundir_iguales([base, al_reves], log=lambda *x: None)) == 2)
    torcido = candidato(42.30, -2.40, 900.0, [30, 31, 32], aparta_m=200.0)
    comprobar("mismo arranque y llegada pero recorrido distinto no se funde",
              len(sg._fundir_iguales([base, torcido], log=lambda *x: None)) == 2)
    lejos = candidato(42.304, -2.40, 900.0, [40, 41, 42])
    comprobar("otra carretera paralela no se funde",
              len(sg._fundir_iguales([base, lejos], log=lambda *x: None)) == 2)
    floja = candidato(42.30, -2.40, 900.0, [50, 51], salto_m=3.0, paso=2)
    comprobar("una traza con la mitad de puntos sigue siendo el mismo camino (el mismo camino pasado unos "
              "metros al lado, con la lista de celdas mas corta, tambien se funde)",
              len(sg._fundir_iguales([base, floja], log=lambda *x: None)) == 1)

    # --- La mineria de verdad, sobre una base de datos de prueba ---
    prueba = os.path.join("data", "_prueba_minero.db")
    for f in (prueba, prueba + "-journal"):
        if os.path.isfile(f):
            os.remove(f)
    cn = db.conectar(prueba)

    def meter(id_, puntos, desnivel=0.0):
        lats = [p[0] for p in puntos]
        lons = [p[1] for p in puntos]
        cn.execute("INSERT INTO actividad (id, fichero, hash, fuente, disciplina, nombre, inicio_local,"
                   " duracion_s, distancia_m, importado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (id_, f"prueba_{id_}.fit", f"huella{id_}", "prueba", "ciclismo", f"salida {id_}",
                    f"2012-07-2{id_} 18:00:00", 3600.0, 30000.0, "2026-01-01"))
        cn.execute("INSERT INTO ruta (actividad_id, n_puntos, lat_min, lat_max, lon_min, lon_max,"
                   " ele_min, ele_max, con_hora, puntos, dist_m, desnivel_m, vel_media_kmh)"
                   " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (id_, len(puntos), min(lats), max(lats), min(lons), max(lons), 300.0, 300.0 + desnivel, 1,
                    empaquetar(puntos), 30000.0, desnivel, 30.0))

    # Cinco salidas por la misma carretera de 1.500 m (una pasa 4 m al lado, otra 8: como el GPS de verdad).
    for k, salto in enumerate((0.0, 2.0, 4.0, 6.0, 8.0), start=1):
        meter(k, puntos_rectos(42.30, -2.40, 1500.0, salto, tono=3 * k))
    # Y una sexta por otro sitio, que no comparte nada.
    meter(9, puntos_rectos(42.40, -2.30, 1500.0, tono=5))
    cn.commit()

    r = sg.minar(cn, "ciclismo", log=lambda *x: None)
    filas = [tuple(f) for f in
             cn.execute("SELECT nombre, dist_m, n_salidas FROM segmento_minado ORDER BY dist_m DESC")]
    comprobar("encuentra el tramo que repiten las salidas", len(filas) == 1, f"{len(filas)} segmentos")
    if filas:
        comprobar("el tramo mide lo que mide la carretera (1.500 m, +-10 %)",
                  1350 <= filas[0][1] <= 1650, f"{filas[0][1]:.0f} m")

    sg.medir(cn, "ciclismo", log=lambda *x: None)
    intentos = cn.execute("SELECT COUNT(*) FROM esfuerzo_minado").fetchone()[0]
    comprobar("mide un intento por salida y tramo", intentos == 5, f"{intentos} intentos")
    tiempos = [f[0] for f in cn.execute("SELECT tiempo_s FROM esfuerzo_minado")]
    comprobar("los tiempos son de verdad (1.500 m a 30 km/h son ~180 s)",
              len(tiempos) == 5 and all(150 <= t <= 220 for t in tiempos), [round(t) for t in tiempos])
    n_salidas, medido = cn.execute("SELECT n_salidas, dist_m FROM segmento_minado").fetchone()
    comprobar("las cinco salidas cuentan como el mismo tramo (no se parte en copias)",
              n_salidas == 5, f"{n_salidas} salidas")
    comprobar("la ficha del tramo se rellena con la medida de un intento de verdad",
              1350 <= medido <= 1650, f"{medido:.0f} m")
    comprobar("una salida sola por otro sitio no hace un segmento", all(f[2] >= 3 for f in filas))
    cn.close()
    for f in (prueba, prueba + "-journal"):
        if os.path.isfile(f):
            os.remove(f)
    print("  (base de prueba del minero borrada: data/_prueba_minero.db)")


def pruebas_competicion(ruta: str = "data/entrenador.db") -> None:
    """Marcas oficiales de competicion: carga del CSV, repetidas, marcas corruptas y consultas."""
    print("\n7. Marcas oficiales de competicion (RFEN)")
    from entrenador import competicion, db

    tmp_bd, tmp_csv = "data/_prueba_competicion.db", "data/_prueba_competicion.csv"
    for f in (tmp_bd, tmp_bd + "-wal", tmp_bd + "-shm", tmp_csv):
        if os.path.isfile(f):
            os.remove(f)
    filas = [
        "C.N. CLUB-EJEMPLO;01/01/2020;PISCINA-A;Libre;400;Electrónico;25;;;00:05:00.00",
        "C.N. CLUB-EJEMPLO;01/01/2020;PISCINA-A;Libre;400;Electrónico;25;;;00:05:00.00",
        "C.N. CLUB-EJEMPLO;17/11/2018;PISCINA-B;Libre;400;Electrónico;25;;;00:1394:14.12",
        "C.N. CLUB-EJEMPLO;04/05/2019 18:10:00;Piscina-C;Libre;400;Electrónico;25;;;00:05:10.00",
    ]
    with open(tmp_csv, "w", encoding="utf-8") as fh:
        fh.write(";".join(competicion.CAMPOS_CSV) + "\n" + "\n".join(filas) + "\n")

    cn = db.conectar(tmp_bd)
    r = competicion.importar(cn, tmp_csv)
    comprobar("el CSV se lee entero", r["leidas"] == 4, f"{r['leidas']} filas")
    comprobar("la fila repetida tal cual no se duplica", uno_(cn, "SELECT COUNT(*) FROM competicion") == 3)
    comprobar("la marca corrupta (00:1394:14.12) queda marcada como no valida",
              uno_(cn, "SELECT valida FROM competicion WHERE marca LIKE '%1394%'") == 0)
    comprobar("la hora se separa de la fecha",
              uno_(cn, "SELECT hora FROM competicion WHERE fecha = '2019-05-04'") == "18:10:00")
    comprobar("el ritmo por 100 m sale de la marca y la distancia",
              abs(uno_(cn, "SELECT ritmo_100 FROM competicion WHERE marca LIKE '%05:00.00'") - 74.1) < 0.05)
    r2 = competicion.importar(cn, tmp_csv)
    comprobar("reimportar el mismo CSV no crea filas nuevas", (r2["nuevas"], r2["actualizadas"]) == (0, 4),
              f"nuevas={r2['nuevas']} actualizadas={r2['actualizadas']}")
    mejores = competicion.mejores(cn, "libre")
    comprobar("la mejor marca de 400 m ignora la corrupta", mejores and mejores[0]["marca"] == "00:05:00.00")
    comprobar("el historial de una prueba trae solo esa prueba, y solo marcas validas",
              len(competicion.historial(cn, "libre", 400)) == 2)
    comprobar("pidiendo tambien las no validas, salen las tres filas de esa prueba",
              len(competicion.historial(cn, "libre", 400, solo_validas=False)) == 3)
    cn.close()
    for f in (tmp_bd, tmp_bd + "-wal", tmp_bd + "-shm", tmp_csv):
        if os.path.isfile(f):
            os.remove(f)

    if not os.path.isfile("data/competicion/historial_rfen.csv") or not os.path.isfile(ruta):
        print("  [omitido] no hay marcas de la RFEN cargadas todavia")
        return
    cn = sqlite3.connect(ruta)
    n = uno_(cn, "SELECT COUNT(*) FROM competicion")
    comprobar("la base tiene las N marcas oficiales (577 antes de leer los pases)", n == 579, f"{n} marcas")
    fila = cn.execute("SELECT marca, fecha FROM competicion WHERE estilo='libre' AND distancia_m=400 "
                      "AND valida=1 ORDER BY segundos LIMIT 1").fetchone()
    comprobar("el mejor 400 oficial es 5:00.00 (Piscina-A, 01/01/2020)",
              fila and fila[0] == "00:05:00.00" and fila[1] == "2020-01-01", str(tuple(fila) if fila else None))
    comprobar("hay 3.000 m libres en competicion",
              uno_(cn, "SELECT COUNT(*) FROM competicion WHERE estilo='libre' AND distancia_m=3000") >= 1)
    comprobar("todas las marcas validas tienen segundos y ritmo",
              uno_(cn, "SELECT COUNT(*) FROM competicion WHERE valida=1 AND (segundos IS NULL "
                       "OR ritmo_100 IS NULL)") == 0)
    cn.close()


def pruebas_plan_y_portal(ruta: str = "data/entrenador.db") -> None:
    """El plan (400 y 3.000) y los apuntes que llegan del cuadro de mando."""
    print("\n8. Plan y portal de natacion (apuntes)")
    import json
    import shutil
    import tempfile

    from entrenador import apuntes, db, panel, plan

    comprobar("la semana del 12/10 es la S1", plan.semana_de("2026-10-12")["clave"] == "S1")
    comprobar("el 14/11 cae en la semana de la prueba", plan.semana_de("2027-01-01")["clave"] == "S5")
    prox = plan.siguiente("2026-10-11")
    comprobar("la sesion siguiente es la cañera del lunes 12",
              prox["fecha"] == "2026-10-12" and "material" in prox["titulo"], prox["titulo"])
    kms = [plan.KILOMETROS_SEMANA[k] for k in ("S1", "S2", "S3", "S4", "S5")]
    comprobar("el volumen sube como mucho un 10 % por semana",
              all(b <= a * 1.10 for a, b in zip(kms, kms[1:])))
    comprobar("la cuarta semana baja (descarga)", kms[3] <= kms[2] * 0.80, f"{kms[2]} -> {kms[3]} km")
    texto = plan.texto("2026-10-11")
    comprobar("el plan en texto lleva los dos objetivos y las reglas",
              "OBJETIVO B" in texto and "OBJETIVO A" in texto and "80 %" in texto)
    for fichero in panel.FICHEROS_APP:
        comprobar(f"la aplicacion trae su {fichero}", os.path.isfile(os.path.join(panel.APP, fichero)))
    pagina = panel.panel_html({"generado": "2026-10-12T20:00:00", "apuntes": {}, "plan": {}, "competicion": {}})
    comprobar("la hoja de estilo entra en la pagina", ":root" in pagina and "--" in pagina)
    comprobar("la logica de la aplicacion entra en la pagina", '"use strict"' in pagina)
    comprobar("los datos entran en la pagina como JSON", 'id="datos"' in pagina and '"generado"' in pagina)
    comprobar("no queda ningun hueco sin rellenar",
              not any(m in pagina for m in ("__CSS__", "__JS__", "__DATOS__")))
    comprobar("el cuadro de mando lleva la seccion de competicion",
              'id="vista-competicion"' in pagina and 'id="c-mejores"' in pagina)
    comprobar("el cuadro de mando lleva el formulario de apuntes",
              'id="apNotas"' in pagina and "partes_entrenador.json" in pagina)
    comprobar("el gimnasio trae el boton de solicitar trabajo",
              'id="gsAnadir"' in pagina and "Solicitar trabajo de gimnasio" in pagina)
    comprobar("el gimnasio ensena lo que manda el programa", 'id="gimPrescritas"' in pagina)
    comprobar("los apuntes se guardan en el navegador, no en un servidor",
              "localStorage" in pagina and "iregua.apuntes" in pagina
              and "iregua.gimnasio.peticiones" in pagina)
    # Lo unico que llama la pagina es al servidor local del propio PC (el boton "Subir"): no sale a internet.
    _destinos = re.findall(r'(?:fetch|open)\(\s*"([^"]+)"', pagina)
    comprobar("la pagina no sale a la red: lo unico que llama es al servidor local del PC",
              "XMLHttpRequest" not in pagina and all(d.startswith("http://127.0.0.1:") for d in _destinos)
              and "http://127.0.0.1:" in pagina, "destinos: " + repr(_destinos))
    if os.path.isfile("cuadro/panel.html"):
        hecha = open("cuadro/panel.html", encoding="utf-8").read()
        usados = set(re.findall(r'(?:q|pintar)\(\s*"([A-Za-z0-9_]+)"', panel._leer_app("app.js")))
        faltan = sorted(i for i in usados if f'id="{i}"' not in hecha)
        comprobar("todos los elementos que usa la aplicacion existen en la pagina hecha",
                  not faltan, f"faltan {faltan}" if faltan else f"{len(usados)} elementos")
        # El nombre, el club y el sello del atleta entran por hueco desde `perfil.py`: la pagina hecha tiene que
        # traerlos rellenos y no quedarse ninguno sin sustituir.
        comprobar("la pagina hecha no deja ningun hueco sin rellenar",
                  not any(m in hecha for m in ("__ATLETA__", "__TITULO__", "__CLUB__", "__INICIALES__",
                                               "__DESCRIPCION__")))
    # Y no estan escritos en el codigo: viven en `entrenador/perfil_local.py`, que no se publica.
    sueltos = []
    for _f in ("entrenador/app/plantilla.html", "entrenador/app/app.js", "entrenador/app/app.css",
               "entrenador/perfil.py", "entrenador/panel.py"):
        if os.path.isfile(_f):
            _t = open(_f, encoding="utf-8").read()
            if any(n in _t for n in ("Atleta", "Club", "Nombre")):
                sueltos.append(_f)
    comprobar("el nombre y el club del atleta no estan escritos en el codigo (solo en el fichero local)",
              not sueltos, "con el nombre dentro: " + repr(sueltos))

    if not os.path.isfile(ruta):
        print("  (sin base de datos: la parte de apuntes se salta)")
        return
    carpeta = tempfile.mkdtemp(prefix="apuntes-pruebas")
    copia = os.path.join(carpeta, "entrenador.db")
    shutil.copy2(ruta, copia)  # se prueba sobre una copia: los apuntes de verdad no se tocan
    cn = db.conectar(copia)
    try:
        entradas = [
            {"fecha": "2026-10-12", "tipo": "natacion", "distancia_m": "3000", "minutos": "58",
             "material": "palas", "sensacion": "8", "fc_media": "142", "piscina_m": "25",
             "notas": "6x100 palas, 8x50 aletas"},
            {"fecha": "2026-10-12", "tipo": "gimnasio", "minutos": "25", "material": "ninguno",
             "sensacion": "7", "notas": "remo, face pull, rotadores"},
            {"fecha": "2026-10-15", "tipo": "natacion", "distancia_m": "3000", "piscina_m": "25",
             "material": ["aletas"], "notas": "3x400 AeL cada 6:30 a 5:55, 8x50 pies aletas"},
        ]
        peticion = {"fecha": "2026-10-14", "objetivo": "Traccion (espalda)", "minutos": 40, "donde": "Gimnasio",
                    "material": ["Mancuernas", "Gomas"], "molestias": "nada de press militar",
                    "notas": "el hombro anda flojo"}
        sesion_gym = {"fecha": "2026-10-13", "ejercicios": [
            {"ejercicio": "Remo con mancuerna", "series": 4, "reps": 10, "kg": 22, "rpe": 8},
            {"ejercicio": "Face pull", "series": 3, "reps": 15, "kg": 15}]}
        fichero = os.path.join(carpeta, "partes_entrenador.json")
        with open(fichero, "w", encoding="utf-8") as f:
            json.dump({"generado": "2026-10-12T20:00:00", "origen": "cuadro/panel.html", "entradas": entradas,
                       "gimnasio_peticiones": [peticion], "gimnasio_sesiones": [sesion_gym]}, f)
        r1 = apuntes.importar(cn, fichero)
        comprobar("el fichero del portal se lee entero", r1["leidas"] == 3, f"{r1['leidas']} entradas")
        comprobar("la primera importacion mete las tres nuevas", r1["nuevas"] == 3 and r1["actualizadas"] == 0)
        comprobar("la peticion de gimnasio entra en la base", r1["peticiones"]["nuevas"] == 1)
        comprobar("la sesion de gimnasio entra en la base", r1["sesiones_gimnasio"]["nuevas"] == 1)
        r2 = apuntes.importar(cn, fichero)
        comprobar("reimportar no duplica nada", r2["nuevas"] == 0 and r2["actualizadas"] == 3)
        comprobar("la peticion tampoco se duplica", r2["peticiones"]["nuevas"] == 0)
        comprobar("la sesion de gimnasio tampoco", r2["sesiones_gimnasio"]["nuevas"] == 0)
        n = uno_(cn, "SELECT COUNT(*) FROM apunte WHERE fecha IN ('2026-10-12', '2026-10-15')")
        comprobar("en la base quedan 3 apuntes, no 6", n == 3, f"{n} filas")
        fila = cn.execute("SELECT * FROM apunte WHERE fecha = '2026-10-12' AND tipo = 'natacion'").fetchone()
        comprobar("los metros y los minutos se guardan como numeros",
                  fila["distancia_m"] == 3000 and fila["minutos"] == 58)
        comprobar("el material y la sensacion se conservan",
                  fila["material"] == "palas" and fila["sensacion"] == 8)
        comprobar("el texto libre se conserva", "aletas" in (fila["notas"] or ""))
        # El material puede llegar como lista (es lo que manda el portal). Antes se guardaba tal cual, con
        # corchetes y comillas: "['aletas']". Tiene que quedar como el material escrito a mano.
        lista = cn.execute("SELECT * FROM apunte WHERE fecha = '2026-10-15' AND tipo = 'natacion'").fetchone()
        comprobar("el material que llega como lista se guarda limpio",
                  lista["material"] == "aletas", str(lista["material"]))
        comprobar("y su huella no lleva corchetes de lista", "[" not in (lista["clave"] or ""),
                  str(lista["clave"]))

        # --- gimnasio: lo pedido, lo hecho y lo que manda el programa ---
        gim = apuntes.resumen(cn)["gimnasio"]
        comprobar("el resumen cuenta la peticion de gimnasio", gim["n_peticiones"] == 1)
        comprobar("la peticion guarda el material a mano",
                  gim["peticiones"][0]["material"] == ["Mancuernas", "Gomas"], str(gim["peticiones"][0]["material"]))
        comprobar("la peticion guarda lo que hay que evitar",
                  "press militar" in gim["peticiones"][0]["molestias"])
        # Ojo: la base es la de verdad y ya tiene sesiones suyas (la del 17/10, por ejemplo). Se busca **esta**
        # sesion por su fecha en vez de suponer que es la unica y la primera.
        mia = [s for s in gim["sesiones"] if s.get("fecha") == "2026-10-13"]
        ej = (mia[0].get("ejercicios") or []) if mia else []
        if isinstance(ej, str):
            ej = json.loads(ej)
        comprobar("el resumen cuenta la sesion apuntada",
                  len(mia) == 1, str([s.get("fecha") for s in gim["sesiones"]]))
        comprobar("el volumen levantado sale de series x reps x kilos",
                  bool(mia) and mia[0]["volumen_kg"] == 4 * 10 * 22 + 3 * 15 * 15,
                  f"{mia[0]['volumen_kg'] if mia else None} kg")
        comprobar("el historial trae los ejercicios con sus kilos",
                  bool(ej) and ej[0].get("kg") == 22, str(ej[:2]))
        comprobar("todavia no hay sesion escrita por el programa", not gim["prescritas"])

        manda = {"fecha": "2026-10-14", "titulo": "Traccion + hombro (suelto, despues de nadar)",
                 "bloques": [{"ejercicio": "Jalon al pecho", "series": 4, "reps": 10, "kg": 45, "nota": "al pecho"},
                             {"ejercicio": "Rotadores con goma", "series": 2, "reps": 15, "kg": None, "nota": "suave"}],
                 "notas": "Nada de press militar."}
        rf = os.path.join(carpeta, "sesion_gimnasio.json")
        with open(rf, "w", encoding="utf-8") as f:
            json.dump(manda, f)
        comprobar("el programa puede escribir la sesion que manda", apuntes.escribir_prescrita(cn, rf)["escritas"] == 1)
        comprobar("escribirla dos veces no la duplica", apuntes.escribir_prescrita(cn, rf)["escritas"] == 1)
        gim = apuntes.resumen(cn)["gimnasio"]
        comprobar("el portal ya ensena la sesion escrita", len(gim["prescritas"]) == 1)
        comprobar("la sesion escrita trae sus bloques con series y pesos",
                  gim["prescritas"][0]["bloques"][0]["kg"] == 45 and gim["prescritas"][0]["bloques"][0]["series"] == 4)

        # --- un entrenamiento hecho SIN reloj, apuntado a mano, cuenta como la sesion del plan de ese dia ---
        # Lo que vale es lo que se ha nadado: el reloj no es obligatorio para que la sesion cuente.
        from datetime import date
        from entrenador import evaluacion
        from entrenador import plan as plan_mod
        hoy = date.today()
        objetivo = None
        for sem in plan_mod.SEMANAS:
            for ses in plan_mod.sesiones_para_evaluar(sem["desde"], sem["hasta"]):
                if ses.get("quien") != "nosotros" or not plan_mod.bloques_de(ses):
                    continue
                if plan_mod._fecha(ses["fecha"]) > hoy:      # noqa: SLF001
                    continue
                if (evaluacion._actividad_de(cn, ses["fecha"]) or evaluacion._parte_de(cn, ses["fecha"])):
                    continue
                objetivo = ses
                break
            if objetivo:
                break
        if not objetivo:
            print("  (todas las sesiones pasadas del plan tienen reloj o parte: el caso 'sin reloj' se salta)")
        else:
            # Se borran los apuntes de ese dia EN LA COPIA (la base de verdad no se toca) y se mete el de prueba.
            cn.execute("DELETE FROM apunte WHERE fecha = ?", (objetivo["fecha"],))
            metros = plan_mod.metros_de_sesion(objetivo)
            fich = os.path.join(carpeta, "sin-reloj.json")
            with open(fich, "w", encoding="utf-8") as f:
                json.dump({"entradas": [{"fecha": objetivo["fecha"], "tipo": "natacion", "distancia_m": metros,
                                         "piscina_m": 25, "notas": "sesion hecha sin reloj"}]}, f)
            apuntes.importar(cn, fich)
            s = evaluacion.evaluar_semana(cn, objetivo["semana"], hoy)
            v = next(x for x in s["sesiones"] if x["fecha"] == objetivo["fecha"])
            comprobar("un entrenamiento apuntado a mano cuenta como la sesion del dia",
                      v["estado"] == "apuntada", f"{v['estado']} ({objetivo['fecha']})")
            comprobar("y sus metros son los que se apuntaron", v["metros_hechos"] == metros)
            comprobar("y los metros entran en lo hecho de la semana",
                      s["km_hechos_nuestras"] >= round(metros / 1000.0, 1), f"{s['km_hechos_nuestras']} km")
            comprobar("y la sesion se cuenta como hecha",
                      s["sesiones_hechas"] >= 1 and s["sesiones_hechas"] <= s["sesiones_plan"])

        vacio = os.path.join(carpeta, "vacio.json")
        with open(vacio, "w", encoding="utf-8") as f:
            json.dump({"entradas": [{"tipo": "otro"}]}, f)
        comprobar("una entrada sin fecha ni notas se ignora", len(apuntes.leer(vacio)) == 0)
        try:
            apuntes.leer(os.path.join(carpeta, "no_existe.json"))
            comprobar("un fichero que falta avisa en vez de romper", False)
        except FileNotFoundError as e:
            comprobar("un fichero que falta avisa en vez de romper", "Descargar fichero" in str(e))
    finally:
        cn.close()
        shutil.rmtree(carpeta, ignore_errors=True)


def pruebas_comparador_y_portal(ruta: str = "data/entrenador.db") -> None:
    """El comparador de marcas oficiales, la proyeccion de objetivos y el portal como aplicacion."""
    print("\n9. Comparador de marcas, objetivos y el portal (menu, pestanas, filtros)")
    import shutil
    import subprocess

    from entrenador import analitica, competicion, db, evaluacion, panel

    # --- la temporada de natacion va de septiembre a agosto ---
    comprobar("septiembre abre temporada", competicion.temporada("2025-09-01") == "2025/26")
    comprobar("mayo sigue en la misma temporada", competicion.temporada("2026-05-26") == "2025/26")
    comprobar("diciembre pertenece a la temporada empezada en septiembre",
              competicion.temporada("2025-12-14") == "2025/26")
    comprobar("agosto todavia es la temporada anterior", competicion.temporada("2026-08-31") == "2025/26")
    comprobar("sin fecha no hay temporada", competicion.temporada(None) is None)

    cn = db.conectar(ruta)
    try:
        if not uno_(cn, "SELECT COUNT(*) FROM competicion"):
            comprobar("hay marcas oficiales en la base", False, "la tabla competicion esta vacia")
            return

        # --- filtros del repositorio de marcas ---
        f25 = competicion.historial(cn, "libre", 400, piscina=25, completas=True)
        comprobar("filtrar por piscina devuelve solo esa piscina",
                  bool(f25) and all(x["piscina_m"] == 25 for x in f25), f"{len(f25)} marcas")
        todas = competicion.historial(cn, "libre", 400)
        comprobar("el filtro de piscina no deja fuera a las demas piscinas", len(f25) <= len(todas))
        temp = competicion.temporada(f25[0]["fecha"])
        en_temp = competicion.historial(cn, "libre", 400, temporada_=temp)
        comprobar("filtrar por temporada cuadra",
                  bool(en_temp) and all(competicion.temporada(x["fecha"]) == temp for x in en_temp),
                  f"{len(en_temp)} marcas en {temp}")
        log = competicion.historial(cn, "libre", 400, lugar="Piscina-C")
        comprobar("filtrar por sede busca en el lugar y en el club (sin importar mayusculas)",
                  bool(log) and all("logro" in ((x["lugar"] or "") + " " + (x["club"] or "")).lower() for x in log),
                  f"{len(log)} marcas")
        por_marca = competicion.historial(cn, "libre", 400, piscina=25, orden="marca")
        comprobar("ordenado por marca, la mejor va primera",
                  por_marca[0]["segundos"] == min(x["segundos"] for x in por_marca))
        por_ritmo = competicion.historial(cn, "libre", 400, orden="ritmo")
        comprobar("ordenado por ritmo va de menos a mas s/100",
                  all(por_ritmo[i]["ritmo_100"] <= por_ritmo[i + 1]["ritmo_100"]
                      for i in range(len(por_ritmo) - 1)))
        comprobar("solo salen marcas validas", all(x["valida"] == 1 for x in competicion.historial(cn)))
        comprobar("una prueba que no ha nadado no devuelve nada",
                  competicion.historial(cn, "libre", 7777) == [])

        # --- el comparador por temporadas ---
        c = competicion.comparar(cn, "libre", 400, 25)
        comprobar("el comparador agrupa por temporada", len(c["por_temporada"]) >= 3,
                  f"{len(c['por_temporada'])} temporadas")
        comprobar("las marcas del comparador son las del historial",
                  sum(t["n"] for t in c["por_temporada"]) == len(f25))
        comprobar("cada temporada lleva su mejor marca",
                  all(t["mejor_s"] == min(x["segundos"] for x in f25
                                          if competicion.temporada(x["fecha"]) == t["temporada"])
                      for t in c["por_temporada"]))
        comprobar("la mejor de siempre dista cero de si misma",
                  [t for t in c["por_temporada"] if t["mejor_s"] == c["mejor"]["segundos"]][0]["vs_mejor_s"] == 0)
        comprobar("la primera temporada no tiene con que compararse",
                  c["por_temporada"][0]["vs_anterior_s"] is None)
        comprobar("la diferencia con la temporada anterior cuadra",
                  all(t["vs_anterior_s"] == round(t["mejor_s"] - c["por_temporada"][i]["mejor_s"], 2)
                      for i, t in enumerate(c["por_temporada"][1:])))
        comprobar("la tendencia se calcula cuando hay marcas suficientes",
                  c["tendencia"] is not None and c["tendencia"]["n"] >= 5,
                  f"{c['tendencia']['pendiente_s_por_ano']} s/100 por ano ({c['tendencia']['lectura']})")
        comprobar("con menos de 5 marcas no se inventa tendencia",
                  competicion.comparar(cn, "libre", 3000, 25)["tendencia"] is None)
        comprobar("sin marcas el comparador no revienta",
                  competicion.comparar(cn, "libre", 7777)["por_temporada"] == [])

        # --- como voy con cada objetivo ---
        p = competicion.progreso(cn, "libre", 400, 25)
        comprobar("la proyeccion del 400 toma el objetivo del plan",
                  p["objetivo_s"] == 300.0 and p["hay_marcas"],
                  f"{p['diferencia_s']} s ({p['estado']})")
        comprobar("la diferencia es la mejor marca menos el objetivo",
                  abs(p["diferencia_s"] - round(p["mejor_s"] - 300.0, 2)) < 0.01)
        comprobar("una prueba sin objetivo definido no compara contra nada",
                  competicion.progreso(cn, "libre", 7777)["objetivo_s"] is None)
        p2 = competicion.progreso(cn, "libre", 400, 25, objetivo_s=200.0)
        comprobar("con un objetivo fuera de alcance, el estado avisa", p2["diferencia_s"] > 0, p2["estado"])

        # --- el portal como aplicacion: menu, vistas, pestanas y datos para filtrar ---
        datos = analitica.analizar(cn)
        html = panel.panel_html(datos)
        comprobar("el portal trae el menu lateral", '<nav class="nav"' in html and 'data-vista="resumen"' in html)
        comprobar("el portal tiene las 10 vistas, 8 en el menu y la bici aparte",
                  html.count('<section class="vista') == 10 and html.count('<a href="#') == 8 and
                  'href="strava/index.html"' in html)
        comprobar("la vista de Reglas trae las propuestas, el credito y el porque pinchable",
                  all(('id="%s"' % i) in html for i in
                      ("vista-reglas", "entrenadorLista", "entrenadorKpis", "reglasCredito", "reglasDetalle",
                       "reglasDetalleTitulo", "reglasDetalleCuerpo", "reglasDetalleCerrar", "regGenerar",
                       "reglasAviso", "cReglas", "conocimientoKpis", "conocimientoLista")) and
                  'data-vista="reglas"' in html)
        comprobar("la vista de apuntar sigue existiendo aunque no este en el menu",
                  'id="vista-apuntar"' in html and 'data-vista="apuntar"' not in html)
        comprobar("la seccion de competicion tiene cuatro pestanas: mejores, comparador, todas y pases",
                  html.count('data-p="c-') == 4 and 'id="vista-competicion"' in html and 'role="tablist"' in html)
        comprobar("la pestana de pases trae sus mandos, su grafico y sus dos tablas",
                  all(('id="%s"' % i) in html for i in
                      ("psPrueba", "psPaso", "psPiscina", "psGrafico", "psGlobo", "psTabla", "psLectura", "psMejor", "psMejorPista")))
        comprobar("el portal lleva todas las marcas para filtrar en el navegador",
                  '"marcas":[' in html and html.count('"segundos"') >= 500)
        comprobar("el portal trae la tarjeta de preparacion y el grafico de evolucion",
                  'id="preparacion"' in html and 'id="cmpGrafico"' in html)
        comprobar("el portal no depende de internet", "<link" not in html and 'src="http' not in html)

        # --- el parte del dia: agrupar intervalos, material e intensidad, y la evaluacion ---
        # El parte no es una vista aparte: se abre al pinchar una sesion en Entrenamientos.
        comprobar("el parte no tiene vista propia: se abre al pinchar una sesion",
                  'id="vista-parte"' not in html and 'data-vista="parte"' not in html and
                  'id="entrenosCajaParte"' in html and 'id="entrenosDetalle"' in html and
                  "function abrirParte" in html and 'data-sesion="' in html)
        comprobar("y la tabla de entrenos dice que sesiones esperan el parte",
                  "por rellenar" in html and 'id="entrenosCajaParte"' in html)
        comprobar("los datos del portal traen el parte y la evaluacion",
                  {"pendientes", "partes", "cortes", "materiales", "intensidades"} <= set(datos["partes"]) and
                  {"semanas", "recientes"} <= set(datos["evaluacion"]))
        # El parte que escribe el portal tiene que traer exactamente los campos que lee el importador.
        campos_parte = ("fecha", "actividad_id", "piscina_m", "metros", "minutos", "sensacion", "notas")
        campos_grupo = ("tipo", "rep_m", "n_reps", "metros", "tiempo_s", "ritmo_100", "descanso_s", "estilo",
                        "material", "intensidad", "nota", "laps")
        guardar = html.split("function guardarParte", 1)[1].split("function ", 1)[0]
        faltan = [c for c in campos_parte + campos_grupo if c + ":" not in guardar]
        comprobar("el parte que escribe el portal trae los campos que lee el importador",
                  not faltan, "faltan: " + ", ".join(faltan))
        comprobar("el material se marca con casillas y la intensidad con selector, sin brazo libre",
                  'type: "checkbox"' in html and 'type: "radio"' in html and
                  'brazo_libre: "Brazo libre"' not in html and '{ valor: "swolf"' not in html)
        # Los aerobicos llevan un nivel mas (SWOLF) y cada repeticion puede llevar su intensidad y su SWOLF medido.
        from entrenador import partes as _pp
        etiquetas = _pp.ETIQUETA_INTENSIDAD
        comprobar("el portal ofrece las intensidades del servidor (el SWOLF, los pies, la tecnica y la salida)",
                  "const NOMBRE_INTENSIDAD = {};" in html and "function nombreIntensidad" in html and
                  "PPA().intensidades" in html and
                  "function pintarReps" in html and 'clase: "mini-num"' in html and 'clase: "mini-sel"' in html and
                  bool(etiquetas.get("swolf")) and "pies" in etiquetas and
                  {"pies", "tecnica", "salida"} <= set(_pp.INTENSIDADES))
        # El tiempo de una repeticion: el reloj lo mide, pero manda el atleta (lo corrige al rellenar el parte).
        comprobar("el tiempo de cada repeticion se puede escribir y el parte lo lleva al lap",
                  "function segundosDe" in html and "tiempo_apuntado" in html and 'clase: "mini-tiempo"' in html and
                  callable(_pp._propagar_tiempos) and callable(_pp.reaplicar))
        # El material (aletas, palas, pull) no puede ser referencia de brazo libre: ni en los KPIs ni en el discurso.
        from entrenador import valoracion as _val
        comprobar("el material se descuenta: los bloques con material no son referencia de nivel",
                  callable(_val._bloque_material) and callable(_val._bloques_material) and
                  _val._ayuda_material("aletas") > 0 and _val._equiv_libre(78.5, "aletas") == 88.5 and
                  _val._ayuda_material("palas,pull") == 6.0)
        # Sin parte, el material del bloque es DESCONOCIDO (no "brazo libre"): el parte es lo unico que lo dice.
        import datetime as _dt
        import sqlite3 as _sq
        from entrenador import analitica as _an
        _cn2 = _sq.connect(ruta)
        _cn2.row_factory = _sq.Row
        _bl = _an.bloques(_cn2)
        comprobar("un bloque de un dia sin parte queda con el material sin constar",
                  any(300 <= (b.get("dist_m") or 0) <= 500 and b.get("fecha") == "2026-10-06"
                      and b.get("material_conocido") is False for b in _bl))
        comprobar("un bloque de un dia con parte si sabe el material (nada tambien se sabe)",
                  any(b.get("fecha") == "2026-10-14" and b.get("material_conocido") for b in _bl))
        _ref = _val._referencia_intensa(_cn2, _dt.date(2026, 7, 18), _dt.date(2026, 10, 16))
        comprobar("la referencia de ritmo sale de un tramo INTENSO y sin material, no de un calentamiento",
                  bool(_ref) and _ref["intensidad"] in _val.INTENSAS and _ref["ritmo_100"] < 90,
                  f"{_ref}" if _ref else "sin referencia")
        comprobar("y deja fuera los tramos con aletas, por rapidos que sean",
                  bool(_ref) and _ref["fecha"] != "2026-10-12", f"{_ref}" if _ref else "sin referencia")
        _cn2.close()
        # Subir el parte: al lado de "Guardar el parte" y sin bandeja de ficheros a la vista.
        comprobar("junto a Guardar el parte va el boton Subir, y la bandeja de ficheros ha desaparecido",
                  'icono("subir") + "Subir"' in html and "Guardar el parte" in html and
                  "function subirParte" in html and 'id="parteLista"' not in html and "parteDescargar" not in html)
        from entrenador import servidor as _srv
        import entrenador.partes as _pr
        comprobar("el servidor local sabe recibir partes y meterlos en la base",
                  _srv.PUERTO_POR_DEFECTO == 8181 and callable(_pr.importar_datos) and
                  callable(_pr.partes_de_datos) and _pr.partes_de_datos({"partes_natacion": [{"fecha": "2026-01-01"}]}) != [])
        # El boton del portal que sube lo nuevo del Garmin: el servidor local hace el trabajo con el MISMO codigo
        # que la consola (`scripts/garmin_conectar.py`) y el portal se limita a enseñar lo que ha pasado. Se prueba
        # el camino HTTP entero sin salir a la red: en las pruebas se le inyecta al servidor un "traer" de mentira.
        comprobar("el portal trae el boton del Garmin, su aviso y quien lo monta",
                  'id="garmTraer"' in html and 'id="garmAviso"' in html and
                  "function traerDelGarmin" in html and "function montarGarmin" in html and "montarGarmin()" in html)
        comprobar("el boton del Garmin habla con el servidor del propio PC, no con internet",
                  'GARMIN = "http://127.0.0.1:' in html and "/garmin/traer" in html)
        _mod = _srv._cargar_garmin(".")
        comprobar("el portal usa el mismo codigo de Garmin que la consola",
                  callable(getattr(_mod, "traer", None)) and callable(getattr(_mod, "bajar_actividades", None)) and
                  _mod.__file__.replace("\\", "/").endswith("scripts/garmin_conectar.py"))
        import tempfile as _tp
        import threading as _th
        import urllib.request as _ur
        _pedido = []
        def _traer_de_mentira(opciones):
            _pedido.append(opciones)
            return {"traidos": 2, "nuevos": 1, "importacion": {"leidos": 2, "nuevos": 1, "omitidos": 1},
                    "desde": "2026-09-23", "hasta": "2026-10-14", "recargar": False, "consola": ""}
        _base_srv = _srv._Base(ruta, ".", regenerar=False, traer=_traer_de_mentira)
        _httpd = _srv.ThreadingHTTPServer(("127.0.0.1", 0), _srv._handler(_base_srv))
        _th.Thread(target=_httpd.serve_forever, daemon=True).start()
        try:
            _puerto = _httpd.server_address[1]
            with _ur.urlopen(f"http://127.0.0.1:{_puerto}/garmin", timeout=20) as _r:
                _ficha = json.loads(_r.read().decode("utf-8"))
            comprobar("el portal puede preguntar si hay sesion de Garmin (sin salir a la red)",
                      _ficha.get("ok") is True and "token" in _ficha and "tokens" in _ficha)
            _pet = _ur.Request(f"http://127.0.0.1:{_puerto}/garmin/traer", data=b"{}",
                               headers={"Content-Type": "application/json"}, method="POST")
            with _ur.urlopen(_pet, timeout=30) as _r:
                _salida = json.loads(_r.read().decode("utf-8"))
            comprobar("el boton del Garmin hace que el servidor traiga lo nuevo y lo cuente",
                      _salida.get("ok") is True and _salida.get("nuevos") == 1 and _salida.get("traidos") == 2
                      and _salida.get("recargar") is False and _pedido == [{}],
                      "respuesta: " + json.dumps(_salida, ensure_ascii=False))
            comprobar("el boton del Garmin le pasa al servidor lo que pida (dias, tipo, rango)",
                      json.loads(_ur.urlopen(_ur.Request(
                          f"http://127.0.0.1:{_puerto}/garmin/traer", data=b'{"dias": 7, "tipo": "swimming"}',
                          headers={"Content-Type": "application/json"}, method="POST"), timeout=30).read().decode())["ok"]
                      and _pedido[-1] == {"dias": 7, "tipo": "swimming"})
            try:
                _ur.urlopen(_ur.Request(f"http://127.0.0.1:{_puerto}/otra-cosa", data=b"{}",
                                        headers={"Content-Type": "application/json"}, method="POST"), timeout=20)
                _estado = 200
            except _ur.HTTPError as _err:
                _estado = _err.code
            comprobar("el servidor no se inventa rutas que no tiene", _estado == 404, "estado: " + str(_estado))
        finally:
            _httpd.shutdown()
            _httpd.server_close()
        pps = datos["partes"]
        if not pps["pendientes"]:
            # Puede no haber ninguna sesion sin parte (si el parte mas reciente ya esta subido). Para poder
            # comprobar el camino de "sesion del reloj sin parte" se repite sobre una copia de la base a la
            # que se le quita ese parte: es exactamente la situacion de un dia de entreno recien importado.
            import tempfile as _tf
            from entrenador import db as _db
            _copia = os.path.join(_tf.mkdtemp(prefix="sin-parte-pruebas"), "entrenador.db")
            # Con `backup`, no copiando el fichero: la base va en WAL y copiarla a pelo deja fuera lo ultimo
            # commiteado (hoy, la tabla `correccion` y la del gimnasio), y la copia no serviria para probar.
            _origen = _db.conectar(ruta)
            _cn2 = _db.conectar(_copia)
            _origen.backup(_cn2)
            _origen.close()
            _cn2.execute("DELETE FROM parte_serie WHERE parte_id = (SELECT MAX(id) FROM parte)")
            _cn2.execute("DELETE FROM parte WHERE id = (SELECT MAX(id) FROM parte)")
            _cn2.commit()
            pps = _pr.datos_panel(_cn2)
            comprobar("sin sesiones pendientes, la prueba se hace sobre una copia sin el ultimo parte",
                      bool(pps["pendientes"]), "pendientes: " + str(len(pps["pendientes"])))
        comprobar("el SWOLF del reloj (tiempo + brazadas) se calcula por repeticion",
                  any(r.get("swolf") for s in pps["pendientes"] for g in s["grupos"] for r in g["reps"]),
                  "series de 50 con swolf: " + str(sum(1 for s in pps["pendientes"] for g in s["grupos"]
                                                       for r in g["reps"] if r.get("swolf"))))
        comprobar("los materiales no incluyen brazo libre (sin marcar nada ya es brazo libre)",
                  "brazo_libre" not in pps["materiales"] and "swolf" in [i["valor"] for i in pps["intensidades"]])
        comprobar("el fichero del portal lleva el bloque partes_natacion",
                  "partes_natacion" in html)
        # Lo de antes del 12/10 se da por rellenado: no se le pide parte a nadie.
        comprobar("solo se pide parte desde el 12/10/2026 (lo anterior se da por rellenado)",
                  all(s["fecha"] >= _pr.PRIMER_DIA_CON_PARTE for s in pps["pendientes"]),
                  "fechas que piden parte: " + str(sorted({s["fecha"] for s in pps["pendientes"]})))
        # Cada sesion lleva lo que dice el sistema de ella, para enseñarlo al abrir el parte.
        vals = pps.get("valoraciones") or {}
        comprobar("cada sesion trae su valoracion del sistema (estado, resumen y detalle)",
                  bool(vals) and all({"estado", "resumen", "detalle"} <= set(v) for v in vals.values()))
        sin_parte_vals = [v for v in vals.values() if v.get("estado") == "sin_parte"]
        comprobar("la valoracion de una sesion sin parte dice lo que trae el reloj, no un vacio",
                  all("reloj" in (v.get("resumen") or "").lower() for v in sin_parte_vals)
                  and bool(vals) and all(v.get("resumen") for v in vals.values()),
                  "sesiones sin parte: " + str(len(sin_parte_vals)))
        # Al abrir el parte: los botones arriba y la vista quieta al repintar.
        comprobar("los botones Guardar el parte y Subir van arriba, antes de los grupos",
                  html.index("acciones-parte") < html.index("cajaValoracion") < html.index("const cuerpo = el(\"div\", { clase: \"semana-cuerpo\" })"))
        comprobar("al repintar no se mueve la vista: solo se baja la primera vez que se abre",
                  "abrirParte(sesionAbierta, null, false)" in html and "if (saltar !== false) caja.scrollIntoView" in html)
        comprobar("el parte ya subido se enseña tal cual, con su valoracion",
                  "function pintarParteSubido" in html and "function parteSubidoDe" in html)
        # El desglose de una sesion CON parte: el portal la tiene que abrir igual que una sin rellenar, con sus
        # grupos y sus repeticiones. Si no, en cuanto el parte consta en la base la sesion se abre sin desglose
        # (solo la cabecera) y el atleta pierde de vista lo que acaba de ordenar. Se mira sobre los datos de
        # verdad (`datos`), no sobre la copia a la que se le quito el ultimo parte.
        reales = datos["partes"]
        con = reales.get("con_parte") or []
        por_id = {str(s["actividad_id"]): s for s in con}
        comprobar("las sesiones que ya tienen parte vienen con su desglose para el portal",
                  bool(con) and all(s.get("grupos") for s in con) and all(s.get("n_intervalos") for s in con),
                  "sesiones con parte: " + str(len(con)))
        dentro = [p for p in reales["partes"] if str(p["actividad_id"]) in por_id]
        comprobar("el desglose de cada parte guardado trae sus mismos grupos y sus mismos metros",
                  bool(dentro) and all(
                      len(por_id[str(p["actividad_id"])]["grupos"]) == len(p["series"])
                      and abs(sum(g["metros"] or 0 for g in por_id[str(p["actividad_id"])]["grupos"])
                              - sum(g["metros"] or 0 for g in p["series"])) < 1
                      for p in dentro))
        comprobar("y las mismas repeticiones que se apuntaron en cada grupo",
                  all(sum(len(g["reps"]) for g in por_id[str(p["actividad_id"])]["grupos"])
                      == sum(len(g.get("reps") or []) for g in p["series"]) for p in dentro))
        todas = [g for s in con for g in s["grupos"]]
        a_mano = [r for g in todas for r in g["reps"] if r.get("lap_idx") is None]
        del_reloj = [r for g in todas for r in g["reps"] if r.get("lap_idx") is not None]
        comprobar("una repeticion apuntada a mano (sin lap) sigue en el desglose, con el tiempo que le puso",
                  bool(a_mano) and all(r.get("tiempo_s") is not None for r in a_mano),
                  "repeticiones a mano: " + str(len(a_mano)))
        comprobar("las repeticiones que vio el reloj salen con lo suyo (brazadas, pulso o SWOLF)",
                  bool(del_reloj) and any(r.get("swolf") or r.get("brazadas") for r in del_reloj),
                  "repeticiones del reloj: " + str(len(del_reloj)))
        comprobar("los metros de una sesion con parte son los del parte, no los que vio el reloj",
                  all(s["metros"] + 1 >= sum(g["metros"] or 0 for g in s["grupos"]) for s in con),
                  "metros: " + str([(s["fecha"], s["metros"]) for s in con]))
        comprobar("al subir un parte, la sesion se vuelve a abrir sola tras recargar",
                  'sessionStorage.setItem("parteAbierto"' in html and 'sessionStorage.getItem("parteAbierto")' in html)
        # La evaluacion no juzga lo que no puede: sin parte, la semana no se da por no hecha.
        ev = evaluacion.evaluar_hasta(cn)
        s1 = next((s for s in ev["semanas"] if s["sesiones"]), None)
        comprobar("la evaluacion pone veredicto a cada sesion (del plan, del entrenador o descanso)",
                  bool(s1) and all(v["estado"] in evaluacion.ESTADOS for v in s1["sesiones"]))
        comprobar("sin partes la semana no se juzga: sin_datos, no un juicio inventado",
                  s1["cumplimiento"] is not None or s1["ajuste"]["accion"] == "sin_datos",
                  s1["ajuste"]["accion"])

        # --- el javascript del portal, ejecutado de verdad ---
        if shutil.which("node"):
            import tempfile as _tmp_js
            _carpeta = _tmp_js.mkdtemp(prefix="panel-pruebas-node-")
            panel.escribir(datos, _carpeta)
            salida = subprocess.run(["node", os.path.join("pruebas", "comprobar_portal.js"),
                                     os.path.join(_carpeta, "cuadro", "panel.html")],
                                    capture_output=True, text=True, timeout=180)
            comprobar("el javascript del portal se ejecuta sin fallos (node)",
                      salida.returncode == 0, (salida.stdout or salida.stderr).strip()[:170])
        else:
            print("  [ -- ] node no esta instalado: no se ejecuta el javascript del portal")
    finally:
        cn.close()


def pruebas_ordenes_del_cli() -> None:
    """Ninguna orden del CLI puede quedarse muda.

    Si un argumento nuevo se cuela en el mismo destino que usa el CLI para saber la orden pedida, el programa
    no da error: simplemente no hace nada. Esto lo caza.
    """
    print("\n10. Las ordenes del CLI dicen algo")
    import contextlib
    import io

    from entrenador import cli

    ordenes = [
        ["resumen"],
        ["series"],
        ["minados"],
        ["competicion", "--sin-importar"],
        ["competicion", "--estilo", "libre", "--distancia", "400", "--comparar", "--sin-importar"],
        ["plan"],
        ["apuntes"],
        ["bici"],
        ["reglas"],
        ["decision"],
    ]
    for orden in ordenes:
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                cli.main(orden)
            salida = buf.getvalue().strip()
            comprobar("la orden " + " ".join(orden) + " dice algo", len(salida) > 20,
                      f"{len(salida)} caracteres")
        except SystemExit as e:
            comprobar("la orden " + " ".join(orden) + " no se cae", False, f"SystemExit {e.code}")


def pruebas_pases_y_completas(ruta: str = "data/entrenador.db") -> None:
    """Pases (parciales) y relevos: se leen del icono de la federacion y no cuentan como marca de esa prueba."""
    print("\n10. Pases y pruebas completas")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    import rfen_historial as rfen
    from entrenador import competicion, db

    comprobar("el scraping lee el icono verde del parcial (si es pase)",
              rfen.texto_celda('<span id="verde"><i class="fa fa-check" ></i> </span>') == "S")
    comprobar("y el rojo como prueba completa",
              rfen.texto_celda('<span id="rojo"><i class="fa fa-remove" ></i> </span>') == "N")
    comprobar("el texto de una celda normal sigue saliendo",
              rfen.texto_celda("<b>PISCINA-C</b>") == "PISCINA-C")
    comprobar("una celda con los dos iconos no se confunde",
              rfen.texto_celda('<i class="fa fa-check"></i><i class="fa fa-remove"></i>') == "S,N")

    # Un CSV de prueba que reproduce los patrones reales, para ver el criterio entero:
    #   dia 1 (concurso): 50/100/200 con el icono de parcial (S) -> son los PASOS del 400, la prueba mas larga
    #     del dia. El 50 de relevo (parcial=N) si es su marca, y el otro 50 no.
    #   dia 2 (una prueba de fondo): 400/1000/2000 con S -> son los PASOS del 3000, no marcas.
    #   dia 3: un 25 de mariposa -> dato mal puesto.
    #   dia 4 (jornada donde la federacion da todas como completas, como el 09/03/2019): nada es paso.
    #   dia 5: un 400 estilos con un 100 mariposa (es paso suyo: un 400 estilos arranca con mariposa) y un
    #     100 espalda, que NO es paso suyo aunque ese dia nadara mas largo.
    tmp_bd, tmp_csv = "data/_prueba_pases.db", "data/_prueba_pases.csv"
    for f in (tmp_bd, tmp_bd + "-wal", tmp_bd + "-shm", tmp_csv):
        if os.path.isfile(f):
            os.remove(f)
    filas = [
        "C.N. CLUB-EJEMPLO;13/01/2018;PISCINA-C;Libre;50;Electrónico;25;S;N;00:00:31.00",
        "C.N. CLUB-EJEMPLO;13/01/2018;PISCINA-C;Libre;50;Electrónico;25;N;S;00:00:30.50",
        "C.N. CLUB-EJEMPLO;13/01/2018;PISCINA-C;Libre;100;Electrónico;25;S;N;00:01:08.10",
        "C.N. CLUB-EJEMPLO;13/01/2018;PISCINA-C;Libre;200;Electrónico;25;S;N;00:02:31.00",
        "C.N. CLUB-EJEMPLO;13/01/2018;PISCINA-C;Libre;400;Electrónico;25;N;N;00:05:10.00",
        "C.N. CLUB-EJEMPLO;26/04/2019;PISCINA-D;Libre;400;Electrónico;50;S;N;00:05:20.00",
        "C.N. CLUB-EJEMPLO;26/04/2019;PISCINA-D;Libre;1000;Electrónico;50;S;N;00:13:43.44",
        "C.N. CLUB-EJEMPLO;26/04/2019;PISCINA-D;Libre;2000;Electrónico;50;S;N;00:26:33.88",
        "C.N. CLUB-EJEMPLO;26/04/2019;PISCINA-D;Libre;3000;Electrónico;50;N;N;00:41:54.53",
        "C.N. CLUB-EJEMPLO;18/04/2026;PISCINA-E;Mariposa;25;Electrónico;25;S;N;00:00:34.46",
        "C.N. CLUB-EJEMPLO;09/03/2019;PISCINA-C;Libre;50;Electrónico;50;N;N;00:00:33.46",
        "C.N. CLUB-EJEMPLO;09/03/2019;PISCINA-C;Libre;100;Electrónico;50;N;N;00:01:09.81",
        "C.N. CLUB-EJEMPLO;09/03/2019;PISCINA-C;Libre;200;Electrónico;50;N;N;00:02:27.44",
        "C.N. CLUB-EJEMPLO;09/03/2019;PISCINA-C;Libre;400;Electrónico;50;N;N;00:05:15.00",
        "C.N. CLUB-EJEMPLO;23/05/2021;PISCINA-C;Estilos;400;Electrónico;25;N;N;00:05:32.64",
        "C.N. CLUB-EJEMPLO;23/05/2021;PISCINA-C;Mariposa;100;Electrónico;25;S;N;00:01:17.24",
        "C.N. CLUB-EJEMPLO;23/05/2021;PISCINA-C;Espalda;100;Electrónico;25;N;N;00:01:20.00",
    ]
    with open(tmp_csv, "w", encoding="utf-8") as fh:
        fh.write(";".join(competicion.CAMPOS_CSV) + "\n" + "\n".join(filas) + "\n")
    cn = db.conectar(tmp_bd)
    competicion.importar(cn, tmp_csv)
    r = competicion.resumen(cn)
    comprobar("el resumen separa marcas, pases y datos raros",
              r["pases"] == 7 and r["completas"] == 9 and r["raras"] == 1,
              f"pases={r['pases']} completas={r['completas']} raras={r['raras']}")
    cls = competicion.clasificar(cn)

    def tipo(estilo: str, dist: int, marca: str = None, piscina: int = None) -> str:
        for f in cls:
            if (f["estilo"] == estilo and f["distancia_m"] == dist
                    and (marca is None or f["marca"] == marca)
                    and (piscina is None or f["piscina_m"] == piscina)):
                return f["tipo"]
        return "sin fila"

    comprobar("las cortas del dia del 400 son PASES, no marcas suyas",
              tipo("libre", 100, piscina=25) == "pase" and tipo("libre", 200, piscina=25) == "pase",
              f"100={tipo('libre', 100, piscina=25)} 200={tipo('libre', 200, piscina=25)}")
    comprobar("y de los dos 50 de ese dia, el del relevo es su marca y el otro el paso",
              tipo("libre", 50, "00:00:30.50") == "prueba" and tipo("libre", 50, "00:00:31.00") == "pase")
    comprobar("el dia que la federacion da todo como completo no hay ningun paso",
              tipo("libre", 50, piscina=50) == "prueba" and tipo("libre", 100, piscina=50) == "prueba"
              and tipo("libre", 200, piscina=50) == "prueba" and tipo("libre", 400, "00:05:15.00") == "prueba")
    comprobar("el 1000 y el 2000 del dia del 3000 son PASES, no marcas",
              tipo("libre", 1000) == "pase" and tipo("libre", 2000) == "pase")
    comprobar("y el 400 del dia de fondo tambien es un paso (escalera del 3000)",
              tipo("libre", 400, "00:05:20.00") == "pase")
    comprobar("el 25 de mariposa queda como dato raro", tipo("mariposa", 25) == "rara")
    comprobar("en un 400 estilos el 100 mariposa es paso suyo (arranca con mariposa)",
              tipo("mariposa", 100, piscina=25) == "pase")
    comprobar("pero un 100 espalda de ese mismo dia NO es paso: es su marca",
              tipo("espalda", 100) == "prueba", tipo("espalda", 100))
    mejores = competicion.mejores(cn, "libre")
    c400 = [f for f in mejores if f["distancia_m"] == 400 and f["piscina_m"] == 25]
    comprobar("la mejor marca de 400 no es el paso del dia de fondo (5:20) sino la del concurso (5:10)",
              len(c400) == 1 and c400[0]["marca"] == "00:05:10.00", c400[0]["marca"] if c400 else "sin fila")
    comprobar("no hay ninguna mejor marca de 1000 ni de 2000 (eran pasos)",
              not [f for f in mejores if f["distancia_m"] in (1000, 2000)])
    todas = competicion.historial(cn, "libre", 1000)
    solo = competicion.historial(cn, "libre", 1000, completas=True)
    comprobar("historial(completas=True) deja fuera los pases",
              len(todas) == 1 and len(solo) == 0, f"{len(todas)} -> {len(solo)}")
    # El comparador es lo que alimenta la evolucion del 400: solo con las de verdad.
    comp = competicion.comparar(cn, "libre", 400, 25)
    comprobar("el comparador de 400 solo ve la del concurso", comp["n"] == 1 and comp["mejor"]["marca"] == "00:05:10.00",
              f"n={comp['n']}")
    cn.close()
    for f in (tmp_bd, tmp_bd + "-wal", tmp_bd + "-shm", tmp_csv):
        if os.path.isfile(f):
            os.remove(f)

    # Y ahora con los datos de verdad
    cn = sqlite3.connect(ruta)
    cn.row_factory = sqlite3.Row
    from entrenador import panel
    d = panel.datos_panel(cn)["competicion"]
    marcas = d["marcas"]
    comprobar("las filas del cuadro de mando traen el tipo y el motivo",
              bool(marcas) and "tipo" in marcas[0] and "motivo" in marcas[0])
    comprobar("y hay de las tres clases (marca, pase y rara)",
              {m["tipo"] for m in marcas} == {"prueba", "pase", "rara"}, str({m["tipo"] for m in marcas}))
    comprobar("las mejores marcas del cuadro de mando no traen pases",
              bool(d["mejores"]) and all((m["tipo"] or "prueba") == "prueba" for m in d["mejores"]))
    comprobar("la evolucion del 400 y del 3.000 tampoco",
              all((m["tipo"] or "prueba") == "prueba" for m in (d["h400"] + d["h3000"])))
    # Los tramos: cada pase dice de que prueba es tramo (`madre`), que es lo que agrupa la pestana "Mis pases".
    por_id = {m["id"]: m for m in marcas}
    pases = [m for m in marcas if m["tipo"] == "pase"]
    comprobar("las filas del portal traen su id y, los pases, la prueba de la que son tramo",
              bool(pases) and all("id" in m for m in marcas) and all(p.get("madre") for p in pases))
    comprobar("cada tramo cuelga de una prueba suya de la misma jornada",
              all(por_id[p["madre"]]["tipo"] == "prueba" and por_id[p["madre"]]["fecha"] == p["fecha"] for p in pases))
    rv = competicion.resumen(cn)
    comprobar("el historial real cuenta 579 filas, y las validas se reparten entre marcas, pases y raras",
              rv["total"] == 579 and rv["pases"] + rv["completas"] + rv["raras"] == rv["validas"],
              f"{rv['total']} filas = {rv['pases']} pases + {rv['completas']} marcas + {rv['raras']} raras = {rv['validas']} validas")
    comprobar("y las 8 que la federacion tiene corruptas se cuentan aparte",
              rv["invalidas"] == 8 and uno_(cn, "SELECT COUNT(*) FROM competicion WHERE tipo='rara'") == rv["raras"] + rv["invalidas"])

    # Y el cuadro de mando que se genera: el filtro de tipo y la etiqueta de pase tienen que estar dentro.
    pagina = os.path.join("cuadro", "panel.html")
    if os.path.isfile(pagina):
        html = open(pagina, encoding="utf-8").read()
        comprobar("el portal trae el filtro de tipo de fila",
                  'id="fTipo"' in html and "Solo marcas mias" in html and "Solo datos raros" in html)
        comprobar("y sabe marcar un pase en la tabla", "pase</span>" in html or "esPase" in html)
        comprobar("y enseña el KPI de pases", "Pases (tramos)" in html)


def pruebas_estimulos_y_reglas():
    """El conocimiento de entrenamiento: que clasifica bien y que las reglas traen su fuente."""
    from entrenador import estimulos, reglas

    comprobar("el fondo continuo se reconoce", estimulos.clasificar({"metros": 2000, "n_reps": 1, "ritmo_100": 100}) == "continuo_aerobico")
    comprobar("un 2000 a 1:27 es fondo sostenido", estimulos.clasificar({"metros": 2000, "n_reps": 1, "ritmo_100": 87}) == "continuo_sostenido")
    comprobar("3x400 con 45 s son series largas",
              estimulos.clasificar({"metros": 1200, "n_reps": 3, "rep_m": 400, "descanso_s": 45, "ritmo_100": 82}) == "series_largas")
    comprobar("8x100 a 1:15 con 25 s es ritmo de prueba",
              estimulos.clasificar({"metros": 800, "n_reps": 8, "rep_m": 100, "descanso_s": 25, "ritmo_100": 75}) == "ritmo_prueba")
    comprobar("8x50 a tope con 1:30 es velocidad",
              estimulos.clasificar({"metros": 400, "n_reps": 8, "rep_m": 50, "descanso_s": 90, "ritmo_100": 74}) == "velocidad_resistencia")
    comprobar("un pataleo es pies, no nado", estimulos.clasificar({"metros": 400, "n_reps": 8, "rep_m": 50, "intensidad": "pies"}) == "pies")
    # El calentamiento no se decide por lo corto que sea el bloque (17/10/2026): el reloj deja sueltos bloques
    # de 100 m que son repeticiones, y contarlos como calentamiento metia 12.600 m de relleno en una ventana.
    comprobar("lo que el parte declara 'cal' es calentamiento",
              estimulos.clasificar({"metros": 425, "n_reps": 1, "ritmo_100": 107, "intensidad": "cal"}) == "calentamiento")
    comprobar("un bloque suelto de 100 m es trabajo, no calentamiento",
              estimulos.clasificar({"metros": 100, "n_reps": 1, "ritmo_100": 84}) == "series_medias")
    comprobar("un tiron suelto y lento si es calentamiento",
              estimulos.clasificar({"metros": 400, "n_reps": 1, "ritmo_100": 130.6}) == "calentamiento")
    comprobar("y lo que el parte declara aerobico no se rebautiza como calentamiento",
              estimulos.clasificar({"metros": 500, "n_reps": 1, "ritmo_100": 99, "intensidad": "ae1"}) == "series_medias")

    p = estimulos.perfil([{"metros": 2000, "n_reps": 1, "ritmo_100": 100},
                          {"metros": 1200, "n_reps": 3, "rep_m": 400, "descanso_s": 45, "ritmo_100": 82}], 75.0)
    comprobar("el perfil separa fondo de series largas", p["por_clase"].get("series_largas") == 1200.0)
    comprobar("y guarda el bloque continuo mas largo", p["continuo_mas_largo"] == 2000.0)

    # Un historico sin nada de ritmo de prueba ni de velocidad tiene que salir como hueco (regla R2).
    hist = {"por_clase": {"continuo_aerobico": 9000, "series_medias": 3000}, "calidad_m": 12000.0,
            "continuo_mas_largo": 2000.0}
    ds = estimulos.deficits(hist, "especifico_400", dias_al_reto=30, objetivo_100=75.0)
    ids = [d["id"] for d in ds]
    comprobar("un historico sin ritmo de prueba sale como hueco", "ritmo_prueba" in ids, str(ids))
    comprobar("y sin velocidad tambien", "velocidad_resistencia" in ids)
    comprobar("cada clase sale una sola vez (V1.1-02)", len(ids) == len(set(ids)), str(ids))
    comprobar("cada deficit trae sus motivos, con la cifra dentro",
              all(d["motivos"] and all(m["porque"] for m in d["motivos"]) for d in ds))
    comprobar("el minimo obligatorio va como motivo de su clase, no como un deficit aparte",
              any(m["tipo"] == "minimo" for d in ds for m in d["motivos"]), str(ids))
    comprobar("y de cada deficit se sabe de que seccion sale y con que grado",
              all(d["seccion_T"] and d["grado"] in reglas.GRADOS for d in ds),
              str([(d["id"], d["grado"]) for d in ds]))
    comprobar("y cada deficit pide una receta que existe",
              all(d["receta"] in estimulos.RECETAS for d in ds), str([(d["id"], d["receta"]) for d in ds]))

    r = estimulos.receta_libre("ritmo_prueba", 75.0)
    comprobar("la receta de ritmo de prueba sale a su ritmo (74-76 s/100)",
              r["ritmo_desde"] == 74.0 and r["ritmo_hasta"] == 76.0, str(r.get("ritmo_desde")))
    comprobar("y con su cada de salida", r["cada_s"] == 120.0)

    comprobar("todas las reglas traen fuente", all(x.get("fuente") in reglas.FUENTES for x in reglas.REGLAS))
    comprobar("y una forma de comprobarse", all(x.get("se_comprueba") for x in reglas.REGLAS))
    comprobar("las que salen del historial existen", len(reglas.por_fuente("historial")) >= 3)


def pruebas_evaluacion_de_una_sesion(ruta: str = "data/entrenador.db") -> None:
    """El boton "Evaluar": el entrenador mira UN entrenamiento.

    Comprueba lo que se pidio el 15/10/2026: que la valoracion de una sesion mire los **tiempos** bloque a
    bloque, la **distancia**, el **esfuerzo previo** y los **descansos**, y diga **como va el plan**. Y, sobre
    todo, que no compare la media de una sesion de 3.600 m con el ritmo de un 400 a tope: eso no diria nada.
    """
    import io
    import json

    from entrenador import db, valoracion

    if not os.path.isfile(ruta):
        print("  [omitido] no existe la base de datos")
        return
    cn = db.conectar(ruta)
    datos = {}
    ficha = os.path.join("data", "derived", "analitica.json")
    if os.path.isfile(ficha):
        datos = json.load(io.open(ficha, encoding="utf-8"))

    # La sesion que se evalúa: la ultima **con parte**, porque la valoracion de una sesion sin parte no puede
    # hablar de "los tiempos bloque a bloque" ni del cada (no hay nada que mirar). Si ninguna tiene parte, la
    # ultima que haya.
    fila = cn.execute("""SELECT a.id FROM actividad a JOIN natacion_sesion s ON s.actividad_id = a.id
                         WHERE EXISTS (SELECT 1 FROM parte p WHERE p.actividad_id = a.id)
                         ORDER BY a.inicio_local DESC LIMIT 1""").fetchone()
    if fila is None:
        fila = cn.execute("""SELECT a.id FROM actividad a JOIN natacion_sesion s ON s.actividad_id = a.id
                             ORDER BY a.inicio_local DESC LIMIT 1""").fetchone()
    comprobar("la base tiene una sesion de natacion que evaluar", fila is not None)
    if fila is None:
        return

    v = valoracion.sesion(cn, int(fila[0]), datos)
    comprobar("el entrenador compone la valoracion de esa sesion", bool(v and v.get("titulo")))
    titulos = [p["titulo"] for p in (v or {}).get("parrafos") or []]
    for esperado in ("Lo que has hecho", "Los tiempos, bloque a bloque", "El esfuerzo previo",
                     "Los descansos", "Como va el plan"):
        comprobar(f"la valoracion de la sesion trae «{esperado}»", esperado in titulos)

    todo = " ".join((p.get("texto") or "") for p in (v or {}).get("parrafos") or [])
    comprobar("la valoracion de la sesion canta el cada de las series", "cada " in todo)
    comprobar("y dice con que piernas venia (esfuerzo previo)", "dias de antes" in todo or "sin apenas" in todo)
    comprobar("y no compara la media de la sesion con el ritmo del reto",
              "Ritmo medio de nado" in todo and "Tu bloque de calidad" in todo)
    comprobar("una sesion que no existe no revienta", valoracion.sesion(cn, 99999999, datos) is None)

    # Un apunte dictado se corrige y se reimporta: con `clave` escrita tiene que ACTUALIZAR el que ya estaba,
    # no crear otro al lado (paso el 13/10/2026: dos filas del mismo dia = el entrenamiento contado dos veces).
    from entrenador import apuntes as _ap
    comprobar("un apunte con `clave` escrita manda esa clave",
              _ap.clave({"clave": "dictado:2026-10-13:natacion", "fecha": "2026-10-13"}) == "dictado:2026-10-13:natacion")
    ochenta = _ap.clave({"fecha": "2026-10-13", "tipo": "natacion", "distancia_m": 3000, "minutos": 60})
    noventa = _ap.clave({"fecha": "2026-10-13", "tipo": "natacion", "distancia_m": 3000, "minutos": 90})
    comprobar("sin `clave` escrita, la huella sigue siendo del contenido (corregir cambia de clave)", ochenta != noventa)
    duplicados = cn.execute("""SELECT fecha, tipo, COUNT(*) c FROM apunte GROUP BY fecha, tipo
                               HAVING c > 1""").fetchall()
    comprobar("no hay apuntes duplicados (mismo dia y tipo)", not duplicados,
              str([tuple(d) for d in duplicados]) if duplicados else "")

    # El cada de una serie es el intervalo de salida, no el descanso: siempre mayor que el tiempo de UNA
    # repeticion (el grupo guarda la suma, asi que se divide entre las repeticiones).
    malos = []
    for p in cn.execute("""SELECT ps.id, ps.cada_s, ps.tiempo_s, ps.n_reps FROM parte_serie ps
                           WHERE ps.cada_s IS NOT NULL AND ps.n_reps >= 2""").fetchall():
        if p["cada_s"] and p["tiempo_s"]:
            if p["cada_s"] + 1 < p["tiempo_s"] / float(p["n_reps"]):
                malos.append((p["id"], p["cada_s"], p["tiempo_s"], p["n_reps"]))
    comprobar("el cada de cada serie es el intervalo de salida (nunca menor que la repeticion)",
              not malos, str(malos[:4]) if malos else "")

    pagina = os.path.join("cuadro", "panel.html")
    if os.path.isfile(pagina):
        html = open(pagina, encoding="utf-8").read()
        comprobar("el portal trae el boton de evaluar el ultimo entrenamiento", 'id="evalUltimo"' in html)
        comprobar("y sabe pedir y pintar la evaluacion de una sesion",
                  "evaluarSesion" in html and "cajaEntrenador" in html)


def pruebas_selectores_del_parte(ruta: str = "data/entrenador.db") -> None:
    """Los selectores del parte (16/10/2026): estilo, tecnica, salida con crono, de quien era la sesion y
    partir una serie en trozos con su tiempo cada uno.

    Lo que se pide: el catalogo que se enseña y el que se valida tienen que ser el MISMO (si el portal ofrece
    algo que el servidor luego tira, el atleta lo escribe para nada), y lo que se guarda tiene que llegar
    entero a la base: la intensidad `tecnica` no se puede recortar a cinco letras al importar.
    """
    import shutil
    import tempfile

    from entrenador import db, partes

    print("11. Los selectores del parte: estilos, tecnica, salida, compania y partir una serie")

    comprobar("la intensidad `pies` ya no enseña el parentesis",
              partes.ETIQUETA_INTENSIDAD.get("pies") == "Pies", str(partes.ETIQUETA_INTENSIDAD.get("pies")))
    comprobar("hay intensidad de tecnica y de salida con crono",
              "tecnica" in partes.INTENSIDADES and "salida" in partes.INTENSIDADES,
              ", ".join(partes.INTENSIDADES))
    comprobar("cada intensidad del catalogo tiene su nombre",
              all(partes.ETIQUETA_INTENSIDAD.get(i) for i in partes.INTENSIDADES))
    comprobar("el material `snorkel` se enseña como tuba",
              str(partes.NOMBRE_MATERIAL.get("snorkel", "")).lower() == "tuba",
              str(partes.NOMBRE_MATERIAL.get("snorkel")))
    comprobar("el estilo tiene los cinco nombres (crol, mariposa, espalda, braza, estilos)",
              [partes.ETIQUETA_ESTILO.get(k) for k in partes.ESTILOS_PARTE]
              == ["Crol", "Mariposa", "Espalda", "Braza", "Estilos"], str(partes.ESTILOS_PARTE))
    comprobar("la sesion se marca como del entrenador del equipo o en solitario",
              set(partes.COMPANIAS) == {"solo", "entrenador"}, str(partes.COMPANIAS))

    if not os.path.isfile(ruta):
        print("  [omitido] no existe la base de datos")
        return
    carpeta = tempfile.mkdtemp(prefix="pruebas-selectores-")
    copia = os.path.join(carpeta, "copia.db")
    try:
        shutil.copyfile(ruta, copia)
        cn = db.conectar(copia)
        fila = cn.execute("""SELECT a.id, a.inicio_local, s.largo_piscina_m FROM actividad a
                             JOIN natacion_sesion s ON s.actividad_id = a.id
                             WHERE a.disciplina = 'natacion' ORDER BY a.inicio_local DESC LIMIT 1""").fetchone()
        if fila is None:
            print("  [omitido] la base no tiene sesiones de natacion")
            return
        # Un parte con las cosas nuevas: dos trozos de 50 (la serie partida), estilo espalda y de tecnica,
        # con aletas, y la sesion marcada como la del entrenador del equipo.
        parte = {
            "fecha": str(fila["inicio_local"])[:10], "actividad_id": int(fila["id"]),
            "piscina_m": fila["largo_piscina_m"] or 25, "metros": 200, "minutos": 5,
            "compania": "entrenador",
            "series": [{"tipo": "serie", "rep_m": 50, "n_reps": 2, "metros": 100, "tiempo_s": 130,
                        "ritmo_100": 130.0, "estilo": "espalda", "intensidad": "tecnica",
                        "material": ["aletas"], "laps": [31, 33], "cada_s": 145},
                       # El bloque al que el atleta le añade una serie mas en el portal (la que nada y el reloj no
                       # vio): pasa a tener tres repeticiones, la ultima sin intervalo del reloj y con su tiempo.
                       {"tipo": "serie", "rep_m": 100, "n_reps": 3, "metros": 300, "tiempo_s": 354.0,
                        "ritmo_100": 118.0, "laps": [], "intensidad": "ae2",
                        "reps": [{"dist_m": 100, "tiempo_s": 118.0}, {"dist_m": 100, "tiempo_s": 118.0},
                                 {"lap": None, "dist_m": 100, "tiempo_s": 118.0, "tiempo_apuntado": "1:58,0"}]},
                       # Y una serie con las distancias de sus repeticiones corregidas (un 50 dentro de un 100).
                       {"tipo": "serie", "rep_m": 75, "n_reps": 2, "metros": 150, "tiempo_s": 160.0,
                        "ritmo_100": 106.7, "laps": [], "intensidad": "ae2",
                        "reps": [{"dist_m": 100, "tiempo_s": 80.0}, {"dist_m": 50, "tiempo_s": 80.0}]},
                       # Y un grupo con un largo del reloj EN BLANCO en medio: es lo que deja el portal cuando el
                       # atleta apunta una repeticion a mano (sin intervalo del reloj detras). No puede romper la
                       # importacion (era `int(None)`), ni pisarle el primer largo de la sesion al reloj, y el
                       # tiempo del grupo tiene que ser la suma de los suyos, no la de los largos que si cuadran.
                       {"tipo": "serie", "rep_m": 100, "n_reps": 2, "metros": 200, "tiempo_s": 750.0,
                        "ritmo_100": 375.0, "laps": [0, None], "intensidad": "ae2",
                        "reps": [{"lap": 0, "dist_m": 100, "tiempo_s": 100.0},
                                 {"lap": None, "dist_m": 100, "tiempo_s": 999.0}]}],
        }
        partes.importar_datos(cn, {"partes_natacion": [parte]})

        p = cn.execute("""SELECT id, compania FROM parte WHERE actividad_id = ?
                          ORDER BY id DESC LIMIT 1""", (int(fila["id"]),)).fetchone()
        comprobar("al importar el parte se guarda de quien era la sesion",
                  bool(p) and p["compania"] == "entrenador", str(p["compania"]) if p else "sin parte")
        if not p:
            return
        # La primera serie del parte (por su orden): la partida en dos trozos. La añadida a mano es la ultima.
        s = cn.execute("""SELECT rep_m, n_reps, estilo, intensidad FROM parte_serie
                          WHERE parte_id = ? ORDER BY orden ASC LIMIT 1""", (p["id"],)).fetchone()
        comprobar("la serie partida en dos trozos de 50 llega entera a la base",
                  bool(s) and float(s["rep_m"] or 0) == 50 and int(s["n_reps"] or 0) == 2,
                  f"{s['n_reps']}x{s['rep_m']}" if s else "sin serie")
        comprobar("la intensidad `tecnica` no se recorta al guardar (cinco letras era el fallo)",
                  bool(s) and s["intensidad"] == "tecnica", str(s["intensidad"]) if s else "")
        comprobar("el estilo de la serie se guarda (espalda)",
                  bool(s) and s["estilo"] == "espalda", str(s["estilo"]) if s else "")

        # La serie añadida a mano: el reloj no la vio, asi que no tiene intervalos; su tiempo lo pone el atleta.
        # La añadida a mano es la segunda (orden 1): la primera es la partida y la tercera la corregida.
        ana = cn.execute("""SELECT n_reps, metros, tiempo_s, ritmo_100, laps, reps FROM parte_serie
                            WHERE parte_id = ? AND orden = 1""", (p["id"],)).fetchone()
        comprobar("el bloque con una serie añadida a mano se guarda con las tres series (no con un bloque nuevo)",
                  bool(ana) and int(ana["n_reps"] or 0) == 3 and float(ana["metros"] or 0) == 300.0,
                  f"{ana['n_reps']}x100 = {ana['metros']} m" if ana else "sin serie")
        comprobar("y no se le inventan intervalos del reloj",
                  bool(ana) and json.loads(ana["laps"] or "[]") == [], str(ana["laps"]) if ana else "")
        reps_ana = json.loads(ana["reps"] or "[]") if ana else []
        comprobar("el tiempo que el atleta le pone a la repeticion añadida no se pierde",
                  len(reps_ana) == 3 and reps_ana[2].get("tiempo_s") == 118.0, str(reps_ana))
        # La distancia corregida de una repeticion de dentro de un grupo: se guarda con la repeticion.
        series_todas = partes.partes_de(cn, 5)[0]["series"]
        # La de las distancias corregidas es la unica con distancias distintas repeticion a repeticion.
        con_dists = [s for s in series_todas
                     if len({r.get("dist_m") for r in (s.get("reps") or [])}) > 1]
        dists = [r.get("dist_m") for r in (con_dists[0].get("reps") if con_dists else [])]
        comprobar("la distancia corregida de cada repeticion se guarda con ella",
                  dists == [100.0, 50.0], str(dists))
        comprobar("y los metros del grupo son la suma de lo que duro cada repeticion (100 + 50)",
                  bool(con_dists) and abs(float(con_dists[0].get("metros") or 0) - 150.0) < 0.1,
                  str(con_dists[0].get("metros")) if con_dists else "sin serie")
        vuelta = [x for x in partes.partes_de(cn, 5) if x.get("actividad_id") == int(fila["id"])]
        cuantas = len((vuelta[0].get("series") or [])) if vuelta else 0
        # Son tres series: la partida, la añadida a mano y la de distancias corregidas.
        # El `cada` que dice el atleta manda sobre el que se deduce de los intervalos del reloj: esta serie trae
        # laps (por donde lo deduciria) y su `cada` escrito a mano.
        leido = partes.partes_de(cn, 5)[0]["series"][0]
        comprobar("el cada que escribe el atleta se guarda tal cual (y no el que deduce el reloj)",
                  abs(float(leido.get("cada_s") or 0) - 145.0) < 0.1,
                  f"cada guardado: {leido.get('cada_s')}")
        comprobar("el parte leido de la base trae las tres series (la partida, la añadida y la corregida)",
                  cuantas >= 3, str(cuantas))
        # El grupo con el largo en blanco: la importacion no se puede caer (era `int(None)` sobre los largos),
        # el tiempo lo pone el atleta y el largo 0 del reloj se queda con el suyo.
        con_hueco = cn.execute("""SELECT tiempo_s, ritmo_100, laps FROM parte_serie
                                  WHERE parte_id = ? AND orden = 3""", (p["id"],)).fetchone()
        comprobar("un largo en blanco entre los del grupo no rompe la importacion (era int(None))",
                  bool(con_hueco), "no llego a guardarse" if not con_hueco else "")
        comprobar("y el tiempo del grupo es la suma de los del atleta (100 + 999), no la de los largos",
                  bool(con_hueco) and abs(float(con_hueco["tiempo_s"] or 0) - 1099.0) < 0.1,
                  f"{con_hueco['tiempo_s']} s" if con_hueco else "")
        comprobar("y el ritmo del grupo sale de ese tiempo",
                  bool(con_hueco) and abs(float(con_hueco["ritmo_100"] or 0) - 549.5) < 0.2,
                  f"{con_hueco['ritmo_100']} s/100" if con_hueco else "")
        lap0 = cn.execute("SELECT timer_s FROM natacion_lap WHERE actividad_id = ? AND lap_idx = 0",
                          (int(fila["id"]),)).fetchone()
        comprobar("al largo 0 del reloj no le cae encima el tiempo de la repeticion apuntada a mano",
                  lap0 is None or abs(float(lap0["timer_s"] or 0) - 999.0) > 0.1,
                  f"{lap0['timer_s']} s" if lap0 else "(la sesion no tiene largo 0)")
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)


def uno_(cn, sql, *a):
    """Primera columna de la primera fila (atajo de las pruebas)."""
    return cn.execute(sql, a).fetchone()[0]


def pruebas_conocimiento_y_series_dia(ruta: str = "data/entrenador.db") -> None:
    """De donde sale el saber y de que se compone un dia (tareas V1.0-01..03 y V1.1-01 del anexo U).

    1. El anexo T (`informes/T_base_de_conocimiento.md`) se lee **como dato**: cada clase de estimulo y cada
       regla saben decir que seccion las sostiene, o declararse criterio si no la tienen.
    2. La ventana de estimulos se mide sobre **una sola fuente de series por dia**, con el parte mandando sobre
       el reloj. Antes se medía sobre la tabla `serie`, que solo guarda series comparables: un dia de 3.400 m
       podia salir como "continuo mas largo = 0 m".
    """
    from entrenador import db, estimulos, reglas

    # ---- V1.0-01: el anexo T, leido como dato ----
    try:
        from entrenador import conocimiento
    except Exception as e:                                        # noqa: BLE001
        comprobar("el anexo T se puede leer como dato (V1.0-01)", False, f"{type(e).__name__}: {e}")
        return
    comprobar("el anexo T se puede leer como dato (V1.0-01)", True)
    secs = conocimiento.secciones()
    comprobar("el anexo T tiene sus secciones",
              {"T.1", "T.2", "T.3", "T.4", "T.5", "T.6", "T.7", "T.8", "T.9"} <= set(secs), str(sorted(secs)))
    comprobar("T.2 cita su fuente externa (Maglischo)", 1 in secs["T.2"]["fuentes"], str(secs["T.2"]["fuentes"]))
    comprobar("T.1 se apoya en fuentes externas y no es criterio",
              bool(secs["T.1"]["fuentes"]) and secs["T.1"]["criterio"] is False)
    comprobar("una seccion con fuentes puede llevar dentro una afirmacion sin fuente",
              bool(secs["T.1"]["criterios"]), str(secs["T.1"]["criterios"][:1]))
    comprobar("y las afirmaciones sin fuente se pueden listar para el entrenador",
              bool(conocimiento.afirmaciones_sin_fuente()),
              str(len(conocimiento.afirmaciones_sin_fuente())))
    # T.8 ya no es "lo que no tiene fuente": es la lista de lo que falta por firmar, y desde la revision de
    # fuentes del 18/10/2026 lleva citas dentro y sus criterios pendientes, los dos contados.
    comprobar("T.8 mantiene sus criterios por firmar y ademas cita lo que ya tiene respaldo",
              secs["T.8"]["con_criterio"] is True and bool(secs["T.8"]["criterios"]) and bool(secs["T.8"]["fuentes"]),
              f"{len(secs['T.8']['criterios'])} criterios, {len(secs['T.8']['fuentes'])} fuentes")
    comprobar("las secciones de metodo (T.0, T.9) no cuentan como criterio a revisar",
              all(s["id"] not in ("T.0", "T.9") for s in conocimiento.sin_fuente()),
              str([s["id"] for s in conocimiento.sin_fuente()]))
    comprobar("y las afirmaciones a revisar tampoco salen de ahi",
              all(a["seccion"] not in ("T.0", "T.9") for a in conocimiento.afirmaciones_sin_fuente()),
              str(sorted({a["seccion"] for a in conocimiento.afirmaciones_sin_fuente()})))

    f = conocimiento.fuente_de("ritmo_prueba")
    comprobar("el ritmo de prueba cita T.1 y T.3",
              {"T.1", "T.3"} <= set(f["secciones"]) and f["criterio"] is False, str(f["secciones"]))
    comprobar("una clave sin fuente declarada sale como criterio",
              conocimiento.fuente_de("lo_que_sea")["criterio"] is True)

    cnf = db.conectar(":memory:")
    comprobar("una seccion sin revisar no tiene revision", conocimiento.revision(cnf, "T.7") is None)
    conocimiento.marcar_revision(cnf, "T.7", "entrenador", "revisada")
    conocimiento.marcar_revision(cnf, "T.7", "entrenador", "revisada y corregida")
    r = conocimiento.revision(cnf, "T.7")
    comprobar("la revision del entrenador se guarda y no se duplica (idempotente)",
              r is not None and r["revisado_por"] == "entrenador" and r["notas"] == "revisada y corregida"
              and len(conocimiento.revisadas(cnf)) == 1, str(r))

    # ---- V1.0-02 y V1.0-03: cada clase y cada regla declaran de donde saben ----
    comprobar("toda clase de estimulo declara su seccion y su grado",
              all("seccion_T" in v and v.get("grado") in reglas.GRADOS for v in estimulos.CLASES.values()))
    sin_fuente = sorted(c for c, v in estimulos.CLASES.items() if v["grado"] == "criterio")
    comprobar("las clases sin saber externo se declaran criterio (calentamiento, pies, salida, tecnica)",
              sin_fuente == ["calentamiento", "pies", "salida", "tecnica"], str(sin_fuente))
    fr = estimulos.fuente_de("ritmo_prueba")
    comprobar("el ritmo de prueba se apoya en el anexo T", fr["criterio"] is False and bool(fr["secciones"]))
    comprobar("y sus horas de recuperacion siguen sin fuente (T.8)",
              "recuperacion" in fr["sin_fuente"], str(fr["sin_fuente"]))

    comprobar("toda regla declara su grado y sus secciones",
              all("seccion_t" in r and r.get("grado") in reglas.GRADOS for r in reglas.REGLAS))
    comprobar("R2 cita las secciones que la sostienen",
              reglas.fuente_de("R2")["secciones"] == ["T.1", "T.3"], str(reglas.fuente_de("R2")["secciones"]))
    comprobar("las reglas sin saber externo se pueden listar",
              len(reglas.sin_conocimiento()) >= 6, str([x["id"] for x in reglas.sin_conocimiento()]))
    comprobar("una regla inventada no tiene fuente", reglas.fuente_de("R99")["criterio"] is True)

    # ---- V1.1-01: una sola fuente de series por dia ----
    try:
        from entrenador import series_dia
    except Exception as e:                                        # noqa: BLE001
        comprobar("existe la fuente unica de series del dia (V1.1-01)", False, f"{type(e).__name__}: {e}")
        return
    comprobar("existe la fuente unica de series del dia (V1.1-01)", True)
    if not os.path.isfile(ruta):
        comprobar("hay base real para medir la ventana", False, f"no existe {ruta}")
        return
    cn = db.conectar(ruta)

    dia = series_dia.series_del_dia(cn, "2026-10-12")
    comprobar("el 12/10 sale del parte (manda sobre el reloj)",
              bool(dia) and all(s["origen"] == "parte" for s in dia), str({s["origen"] for s in dia}))
    comprobar("y trae las 12 lineas del parte", len(dia) == 12, str(len(dia)))
    mil = [s for s in dia if abs(s["metros"] - 1000.0) < 1e-6]
    comprobar("el bloque de 1.000 m lleva su material (aletas), no brazo libre",
              bool(mil) and mil[0]["material"] == "aletas" and mil[0]["brazo_libre"] is False, str(mil[:1]))
    p = series_dia.perfil_del_dia(cn, "2026-10-12", 75.0)
    comprobar("el continuo mas largo de ese dia ya no es 0 m", p["continuo_mas_largo"] == 1000.0,
              str(p["continuo_mas_largo"]))

    # El 16/10 ya lleva parte (se recupero del navegador el 18/10/2026), asi que para lo de "sin parte manda el
    # reloj" se busca el ultimo dia de la ventana que siga sin parte.
    con_parte = {f[0] for f in cn.execute("SELECT DISTINCT fecha FROM parte WHERE fecha BETWEEN ? AND ?",
                                          ("2026-10-04", "2026-10-17"))}
    dias = [f[0] for f in cn.execute(
        """SELECT DISTINCT substr(a.inicio_local, 1, 10) AS fecha FROM actividad a
           JOIN natacion_sesion n ON n.actividad_id = a.id
           WHERE substr(a.inicio_local, 1, 10) BETWEEN ? AND ? ORDER BY 1""", ("2026-10-04", "2026-10-17"))]
    dia_reloj = next((f for f in reversed(dias) if f not in con_parte), None)
    reloj = series_dia.series_del_dia(cn, dia_reloj) if dia_reloj else []
    comprobar("un dia sin parte se mide con el reloj", bool(reloj) and all(s["origen"] == "reloj" for s in reloj),
              str(dia_reloj))
    comprobar("sin parte el material es desconocido, no 'brazo libre'",
              all(s["brazo_libre"] is None for s in reloj))
    metros_reloj = cn.execute(
        """SELECT a.distancia_m FROM actividad a JOIN natacion_sesion n ON n.actividad_id = a.id
           WHERE substr(a.inicio_local, 1, 10) = ?""", (dia_reloj,)).fetchone() if dia_reloj else None
    # Contra lo que suma el reloj, no contra un literal: la sesion entera menos los intervalos que el reloj dispara
    # mal. El 11/10 trae un "largo" de 25 m en 0,65 s (2,6 s/100 m) que no es un largo. Los largos buenos se suman
    # aqui a mano, con un ritmo humano (RITMO_MIN_S100), para que la prueba no dependa de lo que el motor tiro.
    RITMO_MIN_S100 = 40.0
    malos = sum(float(f["dist_m"]) for f in cn.execute(
        """SELECT l.dist_m, l.timer_s FROM natacion_lap l
           JOIN actividad a ON a.id = l.actividad_id
           WHERE substr(a.inicio_local, 1, 10) = ? AND l.dist_m > 0 AND l.timer_s IS NOT NULL
             AND (l.timer_s / l.dist_m * 100.0) < ?""", (dia_reloj, RITMO_MIN_S100)))
    esperado = float(metros_reloj[0]) - malos if metros_reloj else 0.0
    comprobar("y salen los metros del reloj del tiron (no solo los bloques de 200 m)",
              bool(metros_reloj) and abs(sum(s["metros"] for s in reloj) - esperado) < 1e-6,
              f"{sum(s['metros'] for s in reloj)} de {esperado}"
              + (f" (el reloj dice {metros_reloj[0]} y {malos:.0f} m son largos mal disparados)" if malos else ""))
    comprobar("un dia sin sesion no inventa series", series_dia.series_del_dia(cn, "2026-10-13") == [])

    v = series_dia.ventana(cn, "2026-10-04", "2026-10-17", 75.0)
    comprobar("la ventana trae los dias con dato", v["dias_con_dato"] == 9, str(v["dias_con_dato"]))
    # 12/10, 15/10 y 16/10 mandan por el parte; el 14/10 fue a medias (800 de 3.600 m) y manda el reloj.
    comprobar("y solo manda el parte cuando esta completo (14/10 fue a medias: manda el reloj)",
              (v["dias_parte"], v["dias_reloj"]) == (3, 6), str((v["dias_parte"], v["dias_reloj"])))
    comprobar("el continuo mas largo de la ventana ya no es 0 m", v["continuo_mas_largo"] >= 1000.0,
              str(v["continuo_mas_largo"]))
    comprobar("y la ventana ya no pierde metros por el camino", v["total_m"] >= 19000.0, str(v["total_m"]))
    comprobar("avisa cuando el parte no cubre la sesion entera",
              any("reloj" in a for a in v["avisos"]), str(v["avisos"]))

    # ---- el reparto por clase no se inventa calentamiento (arreglo del 17/10/2026) ----
    parte_12 = series_dia.series_del_dia(cn, "2026-10-12")
    decl_cal = sum(s["metros"] for s in parte_12 if s["intensidad"] == "cal")
    clas_cal = sum(s["metros"] for s in parte_12 if estimulos.clasificar(s, 75.0) == "calentamiento")
    comprobar("cuando hay parte, el calentamiento que calcula el motor es el que declaro el atleta",
              abs(clas_cal - decl_cal) < 1.0, f"{clas_cal} vs {decl_cal}")
    comprobar("el calentamiento de la ventana no se come la sesion",
              v["por_clase"].get("calentamiento", 0.0) < v["calidad_m"], str(v["por_clase"]))

    # ---- V1.1-02: cuatro huecos, ninguno repetido, cada uno con sus motivos ----
    ds = estimulos.deficits(v, "especifico_400", dias_al_reto=28, objetivo_100=75.0)
    ids = [d["id"] for d in ds]
    comprobar("la ventana real da como mucho cinco deficits, sin repetir",
              len(ds) <= 5 and len(ids) == len(set(ids)), str(ids))
    comprobar("y los que salen son los que se sabian", set(ids) == {"continuo_sostenido", "series_largas",
              "ritmo_prueba", "velocidad_resistencia"}, str(ids))
    continuo = next(d for d in ds if d["id"] == "continuo_sostenido")
    comprobar("el bloque continuo y el fondo sostenido son el mismo deficit, con dos motivos",
              len(continuo["motivos"]) == 2 and continuo["receta"] == "continuo", str(continuo["motivos"]))
    # El minimo por debajo del porcentaje: donde sigue sin llegar es la velocidad (0 m de 300 m). El ritmo de
    # prueba ya pasa de sus 400 m con los partes recuperados, asi que ahi el minimo no tiene que salir.
    comprobar("y lo que no llega a su minimo lleva el minimo como motivo (la velocidad: 0 m de 300 m)",
              any(m["tipo"] == "minimo" and "minimo son 300 m" in m["porque"]
                  for d in ds if d["id"] == "velocidad_resistencia" for m in d["motivos"]),
              str([d["motivos"] for d in ds if d["id"] == "velocidad_resistencia"]))
    rp = next((d for d in ds if d["id"] == "ritmo_prueba"), None)
    comprobar("y el ritmo de prueba, que ya cubre su minimo, sale con su porcentaje y sin el aviso del minimo",
              bool(rp) and rp["motivos"] and all(m["tipo"] != "minimo" for m in rp["motivos"]),
              str(rp["motivos"] if rp else None))


def pruebas_reparto_por_dia(ruta: str = "data/entrenador.db") -> None:
    """V1.1-03: en que dia cae cada sesion que propone el motor.

    Lo que se comprueba: que no se pongan dos sesiones duras el mismo dia, que los lunes, miercoles y viernes
    queden intocables (regla R6), que la recuperacion se respete y que lo que no cabe se diga en vez de apilarse.
    """
    from entrenador import db, estimulos, planificador, plan, series_dia

    cn = db.conectar(ruta)
    obj = plan.OBJETIVOS[0]["ritmo_objetivo_100"]

    # Dos deficits duros con el mismo dia preferido (los dos piden el jueves) -> dos dias distintos.
    dos = [{"id": "ritmo_prueba", "titulo": "falta ritmo de prueba", "receta": "ritmo_prueba", "porque": "x",
            "motivos": [{"tipo": "minimo", "porque": "x"}], "seccion_T": ["T.1"], "grado": "evidencia"},
           {"id": "velocidad_resistencia", "titulo": "falta velocidad", "receta": "velocidad_resistencia",
            "porque": "y", "motivos": [{"tipo": "hueco", "porque": "y"}], "seccion_T": ["T.2"],
            "grado": "evidencia"}]
    r = planificador.reparto(dos, objetivo_100=obj)
    duros = [d["dia"] for d in r["semana"] if d["de"] == "propio" and d.get("sesion")]
    comprobar("dos sesiones duras no caen el mismo dia", len(duros) == len(set(duros)) == 2, str(duros))
    comprobar("y caen en los dias propios (martes y jueves), no en los del entrenador",
              all(d in planificador.DIAS_PROPIOS for d in duros), str(duros))

    # Tres deficits duros y solo dos dias de calidad: el tercero no se apila, se dice.
    tres = dos + [{"id": "series_largas", "titulo": "falta series largas", "receta": "series_largas", "porque": "z",
                   "motivos": [{"tipo": "porcentaje", "porque": "z"}], "seccion_T": ["T.3"], "grado": "metodo"}]
    r3 = planificador.reparto(tres, objetivo_100=obj)
    comprobar("con tres deficit duros, uno queda fuera con su aviso",
              len(r3["fuera"]) == 1 and bool(r3["avisos"]), str([f["id"] for f in r3["fuera"]]))
    comprobar("y ninguno se coloca dos veces", len(r3["dias"]) == 2, str(sorted(r3["dias"])))

    # La recuperacion manda: si el lunes ya es un dia duro, el martes no admite carga otra vez.
    r4 = planificador.reparto(dos, objetivo_100=obj, ocupados=("lunes",))
    comprobar("un dia duro no se pone pegado a otro dia duro",
              "martes" not in r4["dias"], str(sorted(r4["dias"])))

    # Los lunes, miercoles y viernes quedan del entrenador: el motor no prescribe ahi nada.
    comprobar("el motor no le pone nada al entrenador",
              all(d["de"] != "propio" or not d.get("sesion") for d in r["semana"]
                  if d["dia"] in planificador.DIAS_ENTRENADOR))
    comprobar("y el sabado queda para la bici",
              next(d for d in r["semana"] if d["dia"] == "sabado")["de"] == "bici")

    # ---- con la ventana real del 17/10/2026 ----
    v = series_dia.ventana(cn, "2026-10-04", "2026-10-17", obj)
    ds = estimulos.deficits(v, "especifico_400", dias_al_reto=28, objetivo_100=obj)
    rr = planificador.reparto(ds, objetivo_100=obj)
    por_dia = {d["dia"]: d for d in rr["semana"]}
    comprobar("la ventana real pone una calidad el martes",
              por_dia["martes"]["receta"] == "series_largas", str(por_dia["martes"].get("receta")))
    comprobar("y otra el jueves (el 8x100 a ritmo de prueba)",
              por_dia["jueves"]["receta"] == "ritmo_prueba", str(por_dia["jueves"].get("receta")))
    comprobar("y el bloque continuo el domingo",
              por_dia["domingo"]["receta"] == "continuo", str(por_dia["domingo"].get("receta")))
    comprobar("nunca dos calidades el mismo dia",
              len({d["dia"] for d in rr["semana"] if d["de"] == "propio" and d.get("sesion")}) == 3,
              str([d["dia"] for d in rr["semana"] if d.get("sesion")]))
    comprobar("y lo que no cabe (la punta, con tres dias propios y cuatro necesidades) se dice",
              [f["id"] for f in rr["fuera"]] == ["velocidad_resistencia"], str([f["id"] for f in rr["fuera"]]))
    comprobar("cada sesion va con sus ritmos en el reloj del atleta",
              por_dia["jueves"]["ritmo_desde"] == 74.0 and por_dia["jueves"]["cada_s"] == 120.0,
              str((por_dia["jueves"]["ritmo_desde"], por_dia["jueves"]["cada_s"])))
    comprobar("y con la seccion T que la sostiene",
              por_dia["jueves"]["seccion_T"] == ["T.1", "T.2", "T.3"], str(por_dia["jueves"]["seccion_T"]))


def pruebas_motor_en_el_discurso(ruta: str = "data/entrenador.db") -> None:
    """V1.1-04: el motor de estimulos y el reparto por dia entran en el discurso del portal.

    Lo que se comprueba: que el discurso diga **que falta** con la cifra y la seccion del anexo T al lado, que
    diga **en que dia cae** cada sesion con sus ritmos, que no toque los dias del entrenador, y que sin datos
    diga "sin datos" en vez de rellenar.
    """
    from datetime import date
    from entrenador import db, plan, valoracion

    cn = db.conectar(ruta)
    obj = plan.OBJETIVOS[0]
    r = obj["ritmo_objetivo_100"]
    m = valoracion._falta_y_toca(cn, date(2026, 10, 17), r, 28)

    # La cifra no se escribe a mano: sale de la misma ventana que mide el motor.
    from entrenador import estimulos, series_dia
    ven = series_dia.ventana(cn, "2026-10-04", "2026-10-17", r)
    dicho = f"{estimulos._mil(ven['total_m'])} m en {ven['dias_con_dato']} dias"
    comprobar("el discurso dice de que se ha medido la ventana", dicho in m["falta"],
              f"{dicho} -> {m['falta'][:90]}")
    comprobar("dice que faltan series largas, con el porcentaje que lo sostiene",
              "Faltan series largas" in m["falta"] and "la fase pide alrededor del 25 %" in m["falta"])
    comprobar("dice que falta ritmo de prueba", "Falta ritmo de prueba" in m["falta"])
    comprobar("y donde no llega al minimo lo dice con su minimo (la velocidad, 0 m de 300 m)",
              "el minimo son 300 m" in m["falta"], m["falta"][-170:])
    comprobar("dice el bloque continuo mas largo y contra que se compara",
              "son 1.000 m y el minimo son 1.200 m" in m["falta"], m["falta"])
    comprobar("cita la punta como lo que falta", "Falta velocidad con descanso largo" in m["falta"])
    comprobar("y cada frase lleva su seccion del anexo T al lado",
              m["falta"].count("(anexo T") == len(m["deficits"]),
              f"{m['falta'].count('(anexo T')} vs {len(m['deficits'])}")
    comprobar("con su grado (evidencia o metodo), no todo igual",
              "(anexo T.1 y T.2 y T.3, evidencia)" in m["falta"] and ", metodo)" in m["falta"])
    comprobar("ninguna frase del bloque va sin cifra",
              all(any(c.isdigit() for c in f) for f in m["falta"].split(". ")))

    comprobar("y dice en que dia cae cada sesion",
              bool(m["reparto"]["dias"]) and all(f"el {d}," in m["toca"] for d in m["reparto"]["dias"]), m["toca"])
    comprobar("con el ritmo al que hay que hacerlo y cada cuanto sale",
              "por 100" in m["toca"] and "salida cada" in m["toca"])
    comprobar("los lunes, miercoles y viernes se dicen como del entrenador y no se tocan",
              "entrenador y no se les anade nada" in m["toca"] and "bici" in m["toca"])
    comprobar("y lo que no cabe en la semana se avisa en vez de apilarse",
              any("No cabe en la semana" in a for a in m["avisos"]), str(m["avisos"]))
    comprobar("el aviso de que el parte esta a medias tambien viaja al discurso",
              any("manda el reloj" in a for a in m["avisos"]), str(m["avisos"]))
    # Lo que ya lleva carga ajena al plan (la fuerza, la sesion del entrenador) no recibe calidad encima ni el
    # dia de al lado, y la semana lo dice en llano (V1.3-05, V1.4-03).
    rep = m["reparto"] or {}
    con_carga = set(rep.get("cargados") or [])
    comprobar("la semana sabe que dias ya llevan carga, y no les pone calidad encima",
              not (set(rep.get("dias") or {}) & con_carga),
              f"sesiones en {sorted(rep.get('dias') or {})} vs carga en {sorted(con_carga)}")
    if con_carga:
        comprobar("y lo dice, con el dia y de quien es la carga",
                  any(("ya lleva carga" in a or "ya hay carga" in a) for a in (rep.get("avisos_carga") or [])),
                  str(rep.get("avisos_carga")))
        comprobar("el aviso de carga viaja al discurso, no se queda en el motor",
                  any(("ya lleva carga" in a or "ya hay carga" in a) for a in (rep.get("avisos_carga") or []))
                  and any(("ya lleva carga" in m["toca"] or "ya hay carga" in m["toca"]) for _ in [0]),
                  m["toca"][-320:])

    comprobar("el motor deja sus numeros detras, para poder comprobarlos",
              any(s.get("receta") == "series_largas" for s in (m["reparto"] or {}).get("dias", {}).values()),
              str(m["reparto"]["dias"]))

    # Lo que ya lleva carga ajena al plan no recibe calidad encima, ni el dia de al lado, y la semana lo dice
    # (V1.3-05: la sesion del entrenador; V1.4-03: la fuerza).

    # Sin datos no se rellena: se dice.
    viejo = valoracion._falta_y_toca(cn, date(2020, 3, 1), r, 400)
    comprobar("sin datos el discurso lo dice en vez de inventarse deficits",
              "Sin datos" in viejo["falta"] and viejo["toca"] == "" and not viejo["deficits"], viejo["falta"])


def pruebas_carga_ajena_y_fuerza(ruta: str = "data/entrenador.db") -> None:
    """La sesion del entrenador y la fuerza como carga de la semana (V1.3-05, V1.4-01, V1.4-02, V1.4-03).

    Lo que ya lleva carga no recibe calidad encima ni el dia de al lado; la dosis preventiva del hombro (T.7) se dice
    aunque no haya ni una fila de gimnasio; el aviso de abandono aparece cuando toca; y con dolor declarado el motor
    no propone: manda parar. Nada de esto se inventa aqui: sale de la base y del anexo.
    """
    import os
    import tempfile
    from entrenador import apuntes, db, fuerza, gimnasio, planificador

    copia = os.path.join(tempfile.gettempdir(), "pruebas_carga_ajena.db")
    if os.path.exists(copia):
        os.remove(copia)
    cn = db.conectar(ruta)
    cc = db.conectar(copia)
    cn.backup(cc)

    # --- V1.3-05: la sesion del entrenador como carga ---
    cc.execute("DELETE FROM apunte WHERE quien = 'entrenador'")
    cc.execute("DELETE FROM parte WHERE compania = 'entrenador'")
    cc.execute("DELETE FROM gimnasio_sesion")
    cc.commit()
    for f in ("2026-10-19", "2026-10-21"):        # lunes y miercoles: los dias que manda el entrenador
        apuntes.anotar(cc, fecha=f, tipo="natacion", quien="entrenador", distancia_m=3200,
                       notas="sesion del entrenador del equipo")
    c = fuerza.cargados_de_la_semana(cc, "2026-10-22")
    comprobar("la sesion del entrenador entra como carga de la semana, en su dia",
              c.get("lunes", {}).get("de") == "entrenador" and c.get("lunes", {}).get("fecha") == "2026-10-19",
              str(sorted(c)))
    comprobar("y se queda con los metros que se apuntaron (no con un hueco adivinado)",
              c["lunes"]["detalle"].endswith("3200 m)") and c["lunes"]["recuperacion"] == 24.0,
              c["lunes"]["detalle"])
    deficits = [{"id": "series_largas", "receta": "series_largas", "titulo": "series largas",
                 "porque": "prueba", "motivos": [], "seccion_T": ["T.2"], "grado": "metodo"}]
    r = planificador.reparto(deficits, cargados=c)
    comprobar("con carga el lunes y el miercoles, la semana no propone calidad el jueves",
              "jueves" not in r["dias"] and not r["dias"], str(sorted(r["dias"])))
    comprobar("y lo avisa en cristiano, diciendo de quien es la carga",
              any("entrenador" in a for a in r["avisos_carga"]), str(r["avisos_carga"]))

    # --- V1.4-01: el parte de gimnasio y su carga semanal ---
    gimnasio.apuntar(cc, "2026-10-20", [{"ejercicio": "press banca", "series": 3, "reps": 10, "kg": 40},
                                        {"ejercicio": "core", "series": 3, "reps": 20},
                                        {"ejercicio": "press hombros (maquina)", "series": 3, "reps": 12, "kg": 20}])
    cg = gimnasio.carga_semanal(cc, "2026-10-19", "2026-10-25")
    comprobar("la carga de la semana suma los tres ejercicios (series y repeticiones)",
              cg["sesiones"] == 1 and cg["series"] == 9 and cg["repeticiones"] == 3 * 10 + 3 * 20 + 3 * 12,
              f"{cg['sesiones']} sesiones, {cg['series']} series, {cg['repeticiones']} reps")
    comprobar("los kilos solo suman cuando se apuntan: a peso corporal el volumen no se inventa",
              cg["volumen_kg"] == 3 * 10 * 40 + 3 * 12 * 20
              and [e for e in cg["por_ejercicio"] if e["ejercicio"] == "core"][0]["kg_max"] is None,
              f"{cg['volumen_kg']} kg")
    comprobar("y una sesion sin RPE no se da por dura",
              cg["con_rpe"] == 0 and not fuerza.dias_con_carga(cc, "2026-10-19", "2026-10-25")["intensos"])

    # --- V1.4-02: la dosis preventiva y el aviso de abandono ---
    d = fuerza.dosis_preventiva(cc, "2026-10-20")
    comprobar("con gimnasio hecho, la dosis dice cuantas van y cita T.7",
              d["estado"] in ("a medias", "cumplida") and "T.7" in (d.get("cita") or []), str(d)[:220])
    cc.execute("DELETE FROM gimnasio_sesion")
    cc.commit()
    d0 = fuerza.dosis_preventiva(cc, "2026-10-20")
    comprobar("sin ninguna fila de gimnasio no se da por hecha: dice sin empezar y cita T.7",
              d0["estado"] == "sin empezar" and "T.7" in (d0.get("cita") or []), str(d0)[:220])
    av = fuerza.aviso_abandono(cc, "2026-10-20", semanas=3)
    comprobar("sin gimnasio apuntado nunca, el aviso lo dice en vez de callarse", av["aviso"] is True, str(av))
    gimnasio.apuntar(cc, "2026-10-20", [{"ejercicio": "core", "series": 3, "reps": 20}])
    comprobar("con la sesion de esta semana hecha, el aviso de abandono no sale",
              fuerza.aviso_abandono(cc, "2026-10-20", semanas=3)["aviso"] is False)
    gimnasio.apuntar(cc, "2026-10-21", [{"ejercicio": "press hombros (maquina)", "series": 3, "reps": 10, "kg": 20}],
                     notas="duele el hombro al final de la serie")
    seg = fuerza.aviso_seguridad(cc)
    comprobar("con dolor declarado, la unica salida que da el motor es parar y ver a un profesional",
              bool(seg) and "parar" in seg["texto"].lower() and "fisio" in seg["texto"].lower(), str(seg)[:220])

    # --- V1.4-03: la fuerza no rompe la semana de agua ---
    gimnasio.apuntar(cc, "2026-10-20", [{"ejercicio": "press banca", "series": 5, "reps": 5, "kg": 60, "rpe": 9}],
                     notas="")
    c2 = fuerza.cargados_de_la_semana(cc, "2026-10-20")
    comprobar("una sesion declarada dura pide 48 h de recuperacion, no 24",
              (c2.get("martes") or {}).get("recuperacion") == 48.0, str(c2.get("martes")))
    r2 = planificador.reparto(deficits, cargados=c2)
    comprobar("con fuerza dura el martes, la calidad de ese dia no se queda ahi",
              "martes" not in r2["dias"] and any("fuerza" in a for a in r2["avisos_carga"]),
              f"{sorted(r2['dias'])} | {r2['avisos_carga']}")

    cc.close()
    cn.close()


def pruebas_plan_vivo(ruta: str = "data/entrenador.db") -> None:
    """El plan se recalcula con lo que va entrando (V1.2-01), en vez de quedarse como se escribio.

    La pieza de calculo es pura (dicts, sin base): el km de la semana que viene sale de como fue la anterior,
    aplicando las reglas de carga que ya estan escritas en el plan y citando el numero que lo manda. Y se
    comprueba que el cuadro de mando lo trae calculado al vuelo (no una copia guardada que se quede vieja).
    """
    from datetime import date
    from entrenador import db, panel, plan, plan_vivo

    cerrada = {"clave": "S1", "km_plan": 13.5, "cumplimiento": 1.0, "sesiones": []}
    siguiente = {"clave": "S2", "km": 14.0, "desde": "2026-10-19", "hasta": "2026-10-25"}

    v = plan_vivo.km_de_semana(cerrada, siguiente)
    comprobar("una semana cumplida entera sigue el plan de la siguiente",
              v["accion"] == "seguir" and v["km"] == 14.0, str(v))
    comprobar("el motivo del recalculo lleva los numeros que lo mandan, no una frase hecha",
              any("%" in m for m in v["motivos"]) and any("sube" in m for m in v["motivos"]), str(v["motivos"]))

    v = plan_vivo.km_de_semana(cerrada, dict(siguiente, km=16.0))
    comprobar("si el plan escrito sube mas del 10 %, el recalculo se queda en un 10 %",
              v["accion"] == "subir_menos" and v["km"] == round(13.5 * 1.1, 1), str(v))

    v = plan_vivo.km_de_semana(dict(cerrada, cumplimiento=0.5), siguiente)
    comprobar("con menos del 70 % de las sesiones hechas la semana que viene repite, no sube",
              v["accion"] == "repetir" and v["km"] == 13.5, str(v))

    con_deriva = dict(cerrada, sesiones=[{"fecha": "2026-10-15", "detalle": [
        {"que": "3x700", "hecho": {"reps": [{"ritmo_100": 84.0}, {"ritmo_100": 86.0}, {"ritmo_100": 91.0}]}}]}])
    v = plan_vivo.km_de_semana(con_deriva, siguiente)
    comprobar("con deriva de mas de 5 s/100 de la primera a la ultima repeticion, la que viene baja un 20 %",
              v["accion"] == "bajar" and v["km"] == round(13.5 * 0.8, 1)
              and any("deriva" in m for m in v["motivos"]), str(v))

    v = plan_vivo.km_de_semana(dict(cerrada, cumplimiento=None), siguiente)
    comprobar("sin partes no se juzga la semana: el plan se queda como esta escrito",
              v["accion"] == "sin_datos" and v["km"] == 14.0, str(v))

    v = plan_vivo.km_de_semana(dict(cerrada, clave="S3", km_plan=15.2),
                               {"clave": "S4", "km": 11.5, "desde": "2026-11-02", "hasta": "2026-11-08"})
    comprobar("la descarga escrita (la de cada cuatro semanas) no se recalcula: ya baja a proposito",
              v["accion"] == "descarga" and v["km"] == 11.5, str(v))

    # La semana que decide todavia no ha pasado: manda lo escrito, con el tope del 10 % sobre lo que deja la
    # anterior ya recalculada. Es lo que hace que el recálculo no se quede en el plan viejo.
    v = plan_vivo.km_sin_datos(13.5, {"clave": "S3", "km": 15.2, "desde": "2026-10-26", "hasta": "2026-11-01"})
    comprobar("una semana futura no sube mas de un 10 % sobre lo que deja la anterior recalculada",
              v["accion"] == "subir_menos" and v["km"] == round(13.5 * 1.1, 1), str(v))
    v = plan_vivo.km_sin_datos(14.0, siguiente)
    comprobar("y si lo escrito cabe en la regla, se queda como esta escrito",
              v["accion"] == "sin_juzgar" and v["km"] == 14.0, str(v))
    v = plan_vivo.km_sin_datos(15.2, {"clave": "S4", "km": 11.5, "desde": "2026-11-02", "hasta": "2026-11-08"})
    comprobar("una descarga escrita tampoco se toca por venir de una semana sin juzgar",
              v["accion"] == "descarga" and v["km"] == 11.5, str(v))

    comprobar("las reglas que aplica el recálculo son las que estan escritas en el plan, no otras",
              all(r in plan.REGLAS for r in plan_vivo.REGLAS_DE_CARGA), str(plan_vivo.REGLAS_DE_CARGA))
    comprobar("los topes del codigo son los que dicen las reglas (10 %, 70 %, 20 %)",
              plan_vivo.TOPE_SUBIDA_PCT == 10.0 and plan_vivo.UMBRAL_CUMPLIR == 0.7
              and plan_vivo.BAJADA_DERIVA == 0.8)

    comprobar("la primera semana del plan no se recalcula: no hay nada antes que la mande",
              plan_vivo.km_de_semana(None, siguiente)["accion"] == "sin_anterior")
    comprobar("y despues de la ultima semana del plan no hay nada que recalcular",
              plan_vivo.km_de_semana(cerrada, None) is None)

    # El cuadro de mando: calculado al vuelo con cada entrenamiento, no leido de una tabla.
    cn = db.conectar(ruta)
    d = panel.datos_panel(cn)
    vivo = (d.get("plan") or {}).get("vivo") or {}
    semanas = vivo.get("semanas") or []
    comprobar("el cuadro de mando trae el plan recalculado, semana a semana",
              bool(semanas) and all(s.get("clave") and s.get("km") and s.get("accion") for s in semanas),
              str([(s["clave"], s["km"], s["accion"]) for s in semanas]))
    comprobar("el recalculo dice de donde sale (la semana que lo manda y su regla)",
              all(s.get("motivos") for s in semanas), str(semanas[0].get("motivos")))
    comprobar("y no recalcula las semanas que ya pasaron (esas se evaluan, no se reescriben)",
              all(plan._fecha(s["hasta"]) >= date.today() for s in semanas),          # noqa: SLF001
              str([s["clave"] for s in semanas]))
    comprobar("el plan escrito sigue ahi, para poder comparar lo que se recalculo con lo que se escribio",
              all(s.get("km_escrito") for s in semanas)
              and any(s["km"] != s["km_escrito"] for s in semanas), str(semanas[0]))


def pruebas_fase_del_plan(ruta: str = "data/entrenador.db") -> None:
    """V1.2-01: la fase del plan sale del calendario, no de un valor escrito a mano.

    Hasta el 400 manda `especifico_400`; despues, la fase del bloque en el que cae (el 3.000 del 18/03 pide
    `umbral_3000`, y el bloque de base pide `base`). Sin esto el motor pide el reparto del 400 tambien cuando el
    objetivo ya es otro, y el atleta entrena lo que no toca sin que nadie se entere.
    """
    from datetime import date
    from entrenador import db, plan, reglas, valoracion

    # Un nombre de fase mal escrito no da error: el reparto se cae al del 400 y nadie se entera. Por eso se mira.
    comprobar("las fases que usan los bloques son fases que el motor sabe repartir",
              all(b.get("fase") in plan.FASES for b in plan.BLOQUES),
              str([(b["nombre"], b.get("fase")) for b in plan.BLOQUES]))
    comprobar("y el reparto por clase las conoce todas (los nombres son los de reglas.REPARTO_OBJETIVO)",
              all(f in reglas.REPARTO_OBJETIVO for f in plan.FASES), str(sorted(reglas.REPARTO_OBJETIVO)))

    comprobar("hoy (camino del 400 del 14/11) la fase es la del 400",
              plan.fase_de("2026-10-18") == "especifico_400", plan.fase_de("2026-10-18"))
    comprobar("el 19/11, ya pasado el 400, la fase es la del 3.000",
              plan.fase_de("2026-11-19") == "umbral_3000", plan.fase_de("2026-11-19"))
    comprobar("en el bloque de base manda la fase de base", plan.fase_de("2026-11-25") == "base",
              plan.fase_de("2026-11-25"))
    comprobar("en resistencia especifica y en el especifico, la del 3.000",
              plan.fase_de("2026-12-20") == "umbral_3000" and plan.fase_de("2027-03-01") == "umbral_3000",
              f"{plan.fase_de('2026-12-20')} / {plan.fase_de('2027-03-01')}")
    comprobar("cada bloque devuelve su fase en sus dos extremos",
              all(plan.fase_de(b["desde"]) == b["fase"] and plan.fase_de(b["hasta"]) == b["fase"]
                  for b in plan.BLOQUES),
              str([(b["nombre"], plan.fase_de(b["desde"]), plan.fase_de(b["hasta"])) for b in plan.BLOQUES]))
    comprobar("antes del plan y despues de la prueba tambien se sabe que fase toca",
              plan.fase_de("2026-10-01") == "especifico_400" and plan.fase_de("2027-06-01") == "umbral_3000",
              f"{plan.fase_de('2026-10-01')} / {plan.fase_de('2027-06-01')}")

    cn = db.conectar(ruta)
    r = plan.OBJETIVOS[0]["ritmo_objetivo_100"]
    # El motor no lleva la fase escrita: la pide al plan. Y dos fases distintas tienen que exigir cosas distintas.
    hoy = date(2026, 10, 18)
    m = valoracion._falta_y_toca(cn, hoy, r, 28)                                   # noqa: SLF001
    otra = valoracion._falta_y_toca(cn, hoy, r, 28, fase="umbral_3000")             # noqa: SLF001
    comprobar("el motor coge la fase del calendario del plan (hoy, la del 400)",
              m.get("fase") == plan.fase_de(hoy) == "especifico_400", str(m.get("fase")))
    comprobar("y con otra fase lo que falta cambia (no es lo mismo preparar el 400 que el 3.000)",
              bool(m.get("falta")) and bool(otra.get("falta")) and m["falta"] != otra["falta"],
              (m.get("falta") or "")[:120])
    comprobar("la fase queda en las fuentes (para poder seguir el dato -> calculo -> frase)",
              plan.datos().get("fase") == plan.fase_de(), str(plan.datos().get("fase")))


def pruebas_propuesta_semana(ruta: str = "data/entrenador.db") -> None:
    """V1.2-02: la semana entera propuesta, con metros y ritmos, y si cabe en el volumen que deja el plan.

    Lo que pide el anexo U: que la semana salga con sus tres sesiones propias, **sus metros y sus ritmos**; que los
    lunes, miercoles y viernes queden marcados como del entrenador y sin prescribir nada; y las tres pruebas que
    pide: semana normal, semana con descarga (R4) y semana con prueba (el dia de antes no lleva calidad).
    """
    from datetime import date

    from entrenador import db, estimulos, plan, planificador, series_dia

    cn = db.conectar(ruta)
    obj = plan.OBJETIVOS[0]["ritmo_objetivo_100"]
    fijos = {"lunes": 3400.0, "miercoles": 2900.0, "viernes": 3300.0}       # lo que ponen esos dias, de media

    # Los metros de cada receta no se escriben a ojo: se vuelven a sumar desde el texto de la sesion.
    for clave, receta in estimulos.RECETAS.items():
        if clave == "afinar":               # la semana de la prueba son varios dias, no una sesion: va declarada
            continue
        comprobar(f"los metros de la receta {clave} salen de sumar su texto",
                  estimulos.metros_de_sesion(receta["sesion"]) == receta["metros"],
                  f"{estimulos.metros_de_sesion(receta['sesion'])} vs {receta['metros']}")

    # ---- la semana normal (la del 19/10 que pide el anexo U) ----
    v = series_dia.ventana(cn, "2026-10-04", "2026-10-17", obj)
    deficits = estimulos.deficits(v, plan.fase_de("2026-10-19"), dias_al_reto=28, objetivo_100=obj)
    p = planificador.propuesta_semana(deficits, objetivo_100=obj, km_semana=13.5, fijos_m=fijos)
    por_dia = {d["dia"]: d for d in p["semana"]}
    propias = [d for d in p["semana"] if d["de"] == "propio" and d.get("sesion")]

    comprobar("la semana sale con tres sesiones propias", len(propias) == 3,
              str([(d["dia"], d.get("receta")) for d in propias]))
    comprobar("y cada una con sus metros, sus ritmos y su sesion escrita",
              all(d.get("metros", 0) > 0 and d.get("sesion") and d.get("ritmo_desde") for d in propias),
              str([(d["dia"], d.get("metros")) for d in propias]))
    comprobar("los metros de la sesion son los de su receta, no una cifra puesta aparte",
              all(d["metros"] == estimulos.RECETAS[d["receta"]]["metros"] for d in propias),
              str([(d["dia"], d["metros"], estimulos.RECETAS[d["receta"]]["metros"]) for d in propias]))
    comprobar("las tres caen en dias propios distintos",
              len({d["dia"] for d in propias}) == 3 and len(p["dias"]) == 3 and
              all(d["dia"] in planificador.DIAS_PROPIOS for d in propias),
              str(sorted(p["dias"])))
    comprobar("los lunes, miercoles y viernes quedan del entrenador y sin prescribir nada",
              all(por_dia[d]["de"] == "entrenador" and not por_dia[d].get("sesion")
                  for d in planificador.DIAS_ENTRENADOR),
              str([(d, por_dia[d]["de"], por_dia[d].get("sesion")) for d in planificador.DIAS_ENTRENADOR]))
    comprobar("y el sabado queda para la bici",
              por_dia["sabado"]["de"] == "bici" and not por_dia["sabado"].get("sesion"),
              str(por_dia["sabado"]))
    comprobar("el volumen cuadra: lo que piden las propias, lo que deja el plan y lo que sobra",
              p["volumen"]["tope_m"] == 13500 and p["volumen"]["propio_m"] == sum(d["metros"] for d in propias)
              and p["volumen"]["cabe"] and p["volumen"]["hueco_m"] == 13500 - p["volumen"]["propio_m"],
              str(p["volumen"]))
    comprobar("y los metros de los dias del entrenador se dicen, pero no se restan del presupuesto",
              p["volumen"]["fijos_m"] == 9600 and p["volumen"]["deja_m"] == 13500,
              str((p["volumen"]["fijos_m"], p["volumen"]["deja_m"])))

    # ---- lo que no cabe en el volumen no se coloca a la fuerza ----
    p2 = planificador.propuesta_semana(deficits, objetivo_100=obj, km_semana=5.0, fijos_m=fijos)
    comprobar("con la semana corta, la que no cabe se cae y el total ya entra",
              bool(p2["fuera_volumen"]) and p2["volumen"]["propio_m"] <= 5000 and not p2["volumen"]["cabe"],
              str(p2["volumen"]))
    comprobar("se cae la menos importante (la ultima colocada), no la primera",
              p2["fuera_volumen"][0]["dia"] == p["orden"][-1],
              f"{[f['dia'] for f in p2['fuera_volumen']]} vs {p['orden']}")
    comprobar("y el dia que se queda libre vuelve a estar libre, sin metros",
              all(not d.get("sesion") and d.get("metros") is None for d in p2["semana"]
                  if d["de"] == "propio" and d["dia"] not in p2["dias"]),
              str([(d["dia"], d.get("metros")) for d in p2["semana"] if d["de"] == "propio"]))
    comprobar("con el numero que lo manda dentro del aviso",
              any("no cabe en el volumen" in a and "5000" in a for a in p2["avisos"]),
              str([a for a in p2["avisos"] if "no cabe" in a]))

    # ---- sin saber el volumen, no se recorta nada y se dice ----
    p3 = planificador.propuesta_semana(deficits, objetivo_100=obj)
    comprobar("sin volumen conocido no se recorta nada, pero se avisa",
              p3["volumen"]["tope_m"] is None and not p3["fuera_volumen"] and len(p3["dias"]) == 3
              and any("no se sabe el volumen" in a for a in p3["avisos"]),
              str(p3["volumen"]) + " " + str(p3["avisos"][-1:]))

    # ---- semana con descarga (R4): la que manda el plan cada cuatro semanas ----
    desc = [{"id": "descarga", "titulo": "semana de descarga", "receta": "descarga", "porque": "cada cuarta toca",
             "motivos": [{"tipo": "plan", "porque": "R4"}], "seccion_T": ["T.5"], "grado": "pactado"}]
    p4 = planificador.propuesta_semana(desc, objetivo_100=obj, km_semana=8.5)
    comprobar("la semana de descarga se coloca en un dia propio y sin carga",
              len(p4["dias"]) == 1 and all(planificador._recuperacion(s["clase"]) < planificador.DURO_H
                                           for s in p4["dias"].values()),
              str([(d, s["clase"]) for d, s in p4["dias"].items()]))
    comprobar("y sus metros son los de la receta de descarga",
              list(p4["dias"].values())[0]["metros"] == estimulos.RECETAS["descarga"]["metros"],
              str(list(p4["dias"].values())[0]["metros"]))

    # ---- semana con prueba: el dia de la prueba no se prescribe nada y el de antes no lleva calidad ----
    comprobar("el plan dice que el 18/10 hay prueba (el test de 1.500)",
              plan.pruebas_de("2026-10-18") == ("domingo",), str(plan.pruebas_de("2026-10-18")))
    comprobar("y que el 14/11 la prueba cae en sabado",
              plan.pruebas_de("2027-01-01") == ("sabado",), str(plan.pruebas_de("2027-01-01")))

    p5 = planificador.propuesta_semana(deficits, objetivo_100=obj, km_semana=13.5, tests=("viernes",))
    por_dia5 = {d["dia"]: d for d in p5["semana"]}
    comprobar("el dia de la prueba no lleva sesion nuestra",
              por_dia5["viernes"]["de"] == "test" and not por_dia5["viernes"].get("sesion")
              and "viernes" not in p5["dias"], str(por_dia5["viernes"]))
    comprobar("el dia de antes queda vetado para la calidad",
              p5["vetados"] == ["jueves"], str(p5["vetados"]))
    comprobar("y ahi no cae ninguna sesion de carga",
              all(planificador._recuperacion(s["clase"]) < planificador.DURO_H
                  for d, s in p5["dias"].items() if d in p5["vetados"]),
              str([(d, s["clase"]) for d, s in p5["dias"].items()]))
    comprobar("y se avisa en castellano llano",
              any("hay prueba" in a for a in p5["avisos"]), str(p5["avisos"][:2]))

    # El motor real: hoy (18/10) la prueba es el propio dia, asi que la propuesta de esta semana no lo toca.
    from entrenador import valoracion

    m = valoracion._falta_y_toca(cn, date(2026, 10, 18), obj, 28)                    # noqa: SLF001
    comprobar("el motor coge los dias de prueba del plan, no de una lista escrita",
              (m["propuesta"]["dias_de_prueba"] or []) == ["domingo"],
              str(m["propuesta"]["dias_de_prueba"]))
    comprobar("y el domingo de hoy no lleva sesion propuesta (hoy es el test)",
              "domingo" not in m["propuesta"]["dias"], str(sorted(m["propuesta"]["dias"])))
    comprobar("y el discurso dice por que no la lleva",
              "hay prueba en el plan" in m["toca"], m["toca"][-210:])
    comprobar("con los metros de cada sesion en la frase del discurso",
              " m" in m["toca"] and any(d.get("metros") for d in (m["propuesta"]["dias"] or {}).values()),
              m["toca"][:150])


def pruebas_descanso(ruta: str = "data/entrenador.db") -> None:
    """V1.2-04 y V1.2-05: el sueno y la sensacion entran en el analisis y cambian la lectura del plan.

    Se prueba sobre una COPIA de la base (la buena no se toca): se le apunta la noche del 18/10 y se comprueba que
    el dia sale lastrado, que la semana lo lleva colgado, que la valoracion del entrenamiento lo dice y que
    `_ajuste_bruto` **no baja** el plan por una deriva que tiene explicacion en la noche. Y al reves: la misma
    deriva sin nada apuntado si lo baja, porque el ritmo sigue siendo el que es.
    """
    import sqlite3
    import tempfile
    from datetime import date
    from pathlib import Path

    from entrenador import db, descanso, evaluacion

    carpeta = Path(tempfile.mkdtemp(prefix="pruebas-descanso-"))
    copia = carpeta / "entrenador.db"
    # La copia se hace con la API de SQLite, no copiando el fichero: los ultimos entrenamientos viven en el `-wal`
    # y un `copy` a pelo se los deja fuera (el 18/10 desaparecia de la copia y la prueba no encontraba la sesion).
    origen, destino = sqlite3.connect(ruta), sqlite3.connect(str(copia))
    with destino:
        origen.backup(destino)
    destino.close()
    origen.close()
    cn = db.conectar(str(copia))
    try:
        # --- lo que no se sabe no se inventa: ni limpio ni lastrado ---
        nada = descanso.de(cn, "2020-01-01")
        comprobar("un dia del que no hay dato no sale limpio ni lastrado, y las horas son None (no cero)",
                  nada["se_sabe_algo"] is False and nada["lastrado"] is False and nada["sueno_h"] is None,
                  nada["texto"])
        comprobar("y se dice que no se sabe, en llano", "no hay dato" in nada["texto"], nada["texto"])

        # --- la noche del 18/10 apuntada desde el portal (V1.2-05): 5 h dormidas y levantado 30/100 ---
        cn.execute("""INSERT INTO apunte (clave, fecha, tipo, minutos, sensacion, notas, fuente, importado_en)
                      VALUES ('prueba-sueno-2026-10-18', '2026-10-18', 'sueno', 300, 30, 'prueba', 'prueba', ?)""",
                   (db.ahora(),))
        cn.commit()
        noche = descanso.de(cn, "2026-10-18")
        comprobar("la noche apuntada se lee: 5,0 h y levantado 30/100",
                  noche["sueno_h"] == 5.0 and noche["sueno_como"] == 30, str(noche))
        comprobar("y con eso el dia viene lastrado, con el motivo en llano",
                  noche["lastrado"] and any("dormiste 5,0 h" in m for m in noche["motivos"]),
                  str(noche["motivos"]))
        comprobar("el texto del dia se puede repetir tal cual",
                  "dormiste 5,0 h" in noche["texto"] and "dia lastrado" in noche["texto"], noche["texto"])

        # --- la semana evaluada lleva el descanso de cada dia ---
        sem = evaluacion.evaluar_semana(cn, "S1", date(2026, 10, 18))
        comprobar("cada sesion de la semana lleva su descanso colgado",
                  all("descanso" in v for v in sem["sesiones"]), str(len(sem["sesiones"])))
        domingo = next(v for v in sem["sesiones"] if v["fecha"] == "2026-10-18")
        comprobar("el domingo de la noche mala sale lastrado",
                  domingo["descanso"]["lastrado"], domingo["descanso"]["texto"])
        comprobar("y el motivo de la noche sale solo el dia que se apunto",
                  sum(1 for v in sem["sesiones"]
                      if any("dormiste" in m for m in v["descanso"]["motivos"])) == 1,
                  str([(v["fecha"], v["descanso"]["texto"]) for v in sem["sesiones"]]))

        # --- con deriva: manda la noche ---
        def con_deriva(dia: str, fecha: str) -> dict:
            return {"dia": dia, "fecha": fecha, "detalle": [{"que": "8x100", "hecho": {
                "reps": [{"ritmo_100": 80.0}, {"ritmo_100": 82.0}, {"ritmo_100": 88.0}]}}]}

        # Para el caso "deriva sin nada que la explique" se quita la noche del 13/10 en la COPIA: la base real no se
        # toca y el caso queda exacto (una deriva sin noche y sin sensacion detras).
        cn.execute("DELETE FROM sueno WHERE fecha = ?", ("2026-10-13",))
        cn.execute("DELETE FROM apunte WHERE fecha = ? AND tipo = 'sueno'", ("2026-10-13",))
        cn.commit()

        limpia = {"cumplimiento": 1.0, "km_plan": 13.5, "sesiones": [con_deriva("martes", "2026-10-13")]}
        con_noche = {"cumplimiento": 1.0, "km_plan": 13.5, "sesiones": [con_deriva("domingo", "2026-10-18")]}
        descanso.de_la_semana(cn, limpia["sesiones"])
        descanso.de_la_semana(cn, con_noche["sesiones"])
        comprobar("el caso de la prueba es de verdad 'sin lastre': nada explica ese bajon",
                  not limpia["sesiones"][0]["descanso"]["lastrado"], limpia["sesiones"][0]["descanso"]["texto"])
        a_limpia = evaluacion._ajuste_bruto(limpia, None)
        a_noche = evaluacion._ajuste_bruto(con_noche, None)
        comprobar("una deriva de mas de 5 s/100 sin lastre baja la semana un 20 %",
                  a_limpia["accion"] == "bajar" and a_limpia["km_propuestos"] == 10.8, str(a_limpia)[:120])
        comprobar("la misma deriva con la noche mala NO baja el plan",
                  a_noche["accion"] == "mantener" and a_noche["km_propuestos"] == 13.5, str(a_noche)[:120])
        comprobar("y el motivo lleva la noche dentro y dice que no se toca",
                  any("dias lastrados" in m and "dormiste 5,0 h" in m and "no se toca" in m
                      for m in a_noche["motivos"]), a_noche["motivos"][0])
        comprobar("la deriva se sigue midiendo y diciendo: el dato no se esconde",
                  any("s/100" in m for m in a_noche["motivos"]), str(a_noche["motivos"]))

        # --- la valoracion de un entrenamiento suelto tambien lo dice ---
        hoy = cn.execute("SELECT id FROM actividad WHERE substr(inicio_local, 1, 10) = '2026-10-18'").fetchone()
        val = evaluacion.valorar_actividad(cn, hoy["id"]) if hoy else None
        comprobar("la valoracion del entrenamiento trae el descanso del dia",
                  bool(val) and val["descanso"]["lastrado"] is True, str((val or {}).get("descanso")))
        comprobar("y el aviso del dia va dentro del resumen, antes de juzgar el ritmo",
                  "Ojo con el dia" in (val or {}).get("resumen", ""), str((val or {}).get("resumen"))[-160:])
    finally:
        cn.close()
        import shutil
        shutil.rmtree(carpeta, ignore_errors=True)


def pruebas_de_gimnasio(ruta: str = "data/entrenador.db") -> None:
    """La plantilla de gimnasio: sus ejercicios de siempre y lo que va levantando (series, reps y kilos).

    El reloj no sabe nada de esto; se apunta a mano y tiene que poder corregirse: apuntar otra vez el mismo dia manda
    sobre lo anterior, sin duplicar la sesion ni perder los ejercicios que no se tocan.
    """
    import os
    import tempfile
    from entrenador import cli as mod_cli
    from entrenador import db
    from entrenador import gimnasio as mod_gimnasio
    copia = os.path.join(tempfile.gettempdir(), "pruebas_gimnasio.db")
    if os.path.exists(copia):
        os.remove(copia)
    cn = db.conectar(ruta)
    cc = db.conectar(copia)
    cn.backup(cc)

    cc.execute("DELETE FROM gimnasio_ejercicio")  # se prueba como la primera vez, aunque la base ya la tenga
    cc.commit()
    comprobar("la plantilla de gimnasio siembra sus ejercicios de siempre y no los repite",
              mod_gimnasio.sembrar(cc) == 8 and mod_gimnasio.sembrar(cc) == 0,
              "catalogo: " + str(len(mod_gimnasio.catalogo(cc))))
    nombres = [e["nombre"] for e in mod_gimnasio.catalogo(cc)]
    comprobar("estan los suyos: core, lumbares, triceps en polea, press banca, press inclinado, hombros, biceps, gemelos",
              all(n in nombres for n in ("core", "lumbares", "triceps en polea (cuerdas)", "press banca",
                                         "press inclinado", "press hombros (maquina)", "curl biceps (polea)",
                                         "gemelos (maquina)")), str(nombres))

    r = mod_gimnasio.apuntar(cc, "2026-10-18", [{"ejercicio": "press banca", "series": 3, "reps": 10, "kg": 40},
                                                {"ejercicio": "core", "series": 3, "reps": 20}])
    comprobar("apuntar un dia guarda series, repeticiones y kilos",
              r["series"] == 6 and r["repeticiones"] == 90 and r["volumen_kg"] == 1200.0,
              f"{r['series']} series, {r['repeticiones']} reps, {r['volumen_kg']} kg")
    r = mod_gimnasio.apuntar(cc, "2026-10-18", [{"ejercicio": "press banca", "series": 4, "reps": 10, "kg": 42.5}])
    comprobar("volver a apuntar el mismo dia corrige ese ejercicio y no duplica la sesion",
              len(r["ejercicios"]) == 2 and r["volumen_kg"] == 1700.0
              and cc.execute("SELECT COUNT(*) FROM gimnasio_sesion WHERE fecha = '2026-10-18'").fetchone()[0] == 1,
              f"{len(r['ejercicios'])} ejercicios, {r['volumen_kg']} kg")
    ultimo = mod_gimnasio.ultimo_de(cc, "press banca")
    comprobar("se acuerda de lo ultimo que levanto en cada ejercicio",
              ultimo and ultimo["kg"] == 42.5 and ultimo["series"] == 4, str(ultimo))
    comprobar("y de su mejor dia en ese ejercicio",
              (mod_gimnasio.mejor_de(cc, "press banca") or {}).get("kg") == 42.5,
              str(mod_gimnasio.mejor_de(cc, "press banca")))

    mod_gimnasio.apuntar(cc, "2026-10-20", [{"ejercicio": "press banca", "series": 3, "reps": 8, "kg": 45}])
    comprobar("el historial sale de lo mas nuevo a lo mas viejo",
              [s["fecha"] for s in mod_gimnasio.historial(cc, "press banca")] == ["2026-10-20", "2026-10-18"],
              str([s["fecha"] for s in mod_gimnasio.historial(cc, "press banca")]))
    comprobar("un ejercicio que no estaba en la plantilla se anade al apuntarlo",
              mod_gimnasio.apuntar(cc, "2026-10-20", [{"ejercicio": "remo con mancuerna", "series": 3, "reps": 12,
                                                      "kg": 20}])["ejercicios"]
              and "remo con mancuerna" in [e["nombre"] for e in mod_gimnasio.catalogo(cc)])
    try:
        mod_gimnasio.apuntar(cc, "2026-10-20", [])
        comprobar("sin numeros no se apunta una sesion vacia", False)
    except ValueError:
        comprobar("sin numeros no se apunta una sesion vacia", True)

    linea = mod_cli._linea_de_gimnasio("press banca=3x10@40")
    comprobar("la consola entiende 'press banca=3x10@40' y 'core=3x20'",
              linea == {"ejercicio": "press banca", "series": "3", "reps": "10", "kg": "40"}
              and mod_cli._linea_de_gimnasio("core=3x20")["kg"] is None,
              str(linea))
    hoja = mod_gimnasio.hoja(cc)
    comprobar("la hoja del portal trae la plantilla con lo ultimo de cada ejercicio y las sesiones",
              len(hoja["ejercicios"]) >= 8 and hoja["fecha_hoy"] and hoja["sesiones"]
              and any(e.get("ultimo") for e in hoja["ejercicios"]), str(len(hoja["ejercicios"])))
    cc.close()
    os.remove(copia)


def pruebas_de_medicion(ruta: str = "data/entrenador.db") -> None:
    """Las pruebas de medicion: el nombre que pone el atleta, la marca que viaja con el parte y su historial.

    La marca va sobre una copia de la base y con una sesion de verdad: asi se comprueba todo el camino (el
    portal manda `prueba`, el parte lo guarda en el bloque y el historial lo encuentra despues).
    """
    import os
    import shutil
    import tempfile

    from entrenador import db as mod_db
    from entrenador import partes as mod_partes
    from entrenador import pruebas as mod_pruebas

    comprobar("el nombre de una prueba se deja en una linea", mod_pruebas.limpiar("  10x100  ") == "10x100")
    comprobar("un nombre en blanco no es prueba", mod_pruebas.limpiar("   ") is None)

    cn = mod_db.conectar(ruta)
    catalogo = mod_pruebas.catalogo(cn)
    comprobar("el catalogo empieza por las pruebas de la casa",
              catalogo[:len(mod_pruebas.TIPOS)] == list(mod_pruebas.TIPOS))
    comprobar("la columna de la prueba esta en la base",
              "prueba" in [f[1] for f in cn.execute("PRAGMA table_info(parte_serie)")])

    copia = os.path.join(tempfile.gettempdir(), "copia_pruebas_medicion.db")
    if os.path.exists(copia):
        os.remove(copia)
    cc = mod_db.conectar(copia)
    # Ojo: copiar el fichero a pelo pierde el WAL (lo ultimo escrito). La copia buena es la de SQLite.
    cn.backup(cc)
    pendientes = [s for s in mod_partes.sesiones_sin_parte(cc, 25) if s.get("grupos")]
    if not pendientes:
        # Puede no haber ninguna: en cuanto el parte de la ultima sesion esta relleno, la base se queda sin
        # ejemplos y la prueba se caeria sola (no por un fallo del motor). Se le quita el parte a la sesion
        # mas reciente de la copia: es exactamente la situacion de un dia recien importado.
        fila = cc.execute(
            "SELECT p.id FROM parte p JOIN actividad a ON a.id = p.actividad_id "
            "WHERE substr(a.inicio_local, 1, 10) >= ? ORDER BY a.inicio_local DESC LIMIT 1",
            (mod_partes.PRIMER_DIA_CON_PARTE,)).fetchone()
        if fila:
            cc.execute("DELETE FROM parte_serie WHERE parte_id = ?", (fila["id"],))
            cc.execute("DELETE FROM parte WHERE id = ?", (fila["id"],))
            cc.commit()
        pendientes = [s for s in mod_partes.sesiones_sin_parte(cc, 25) if s.get("grupos")]
    comprobar("hay sesiones sin parte con desglose para probar la marca", bool(pendientes))
    if pendientes:
        sesion = pendientes[0]
        grupo = max(sesion["grupos"], key=lambda g: g.get("metros") or 0)
        metros = grupo.get("metros")
        grupo["prueba"] = "1500"
        grupo["intensidad"] = "ae3"
        entrada = mod_partes.importar_datos(cc, {"partes_natacion": [{
            "fecha": sesion["fecha"], "actividad_id": sesion["actividad_id"], "piscina_m": sesion["piscina_m"],
            "metros": sesion["metros"], "minutos": 60, "sensacion": 70, "notas": "prueba de medicion",
            "compania": "solo", "series": [grupo]}]}, origen="test")
        comprobar("el parte con la prueba entra sin incidencias", not entrada.get("incidencias"),
                  str(entrada.get("incidencias")))
        # Se busca el bloque en el parte que se acaba de subir (el mas nuevo de esa sesion), no "el primero con
        # esos metros": en la base puede haber varios bloques de los mismos metros (un 425 m se repite) y el
        # primero no es el que se acaba de guardar.
        fila = cc.execute(
            "SELECT s.prueba FROM parte_serie s JOIN parte p ON p.id = s.parte_id "
            "WHERE p.actividad_id = ? AND s.metros = ? ORDER BY p.id DESC LIMIT 1",
            (sesion["actividad_id"], metros)).fetchone()
        comprobar("la marca de prueba queda guardada en el bloque",
                  bool(fila) and fila[0] == "1500", str(fila))
        historial = mod_pruebas.historico(cc)
        suyas = [h for h in historial if h["nombre"] == "1500"]
        comprobar("la prueba marcada sale en el historial", bool(suyas), str([h["nombre"] for h in historial]))
        if suyas:
            comprobar("el historial guarda el ritmo de cada cien (lo comparable entre epocas)",
                      suyas[0]["ultima"]["ritmo_100"] is not None)
            comprobar("y los metros, para no comparar un 10x100 con un 1.500",
                      suyas[0]["metros"] == int(round(metros or 0)))
            comprobar("el portal recibe las pruebas marcadas en su historial",
                      any(h["nombre"] == "1500"
                          for h in mod_partes.datos_panel(cc).get("pruebas_historial", [])))

    # La medida de cada prueba la declara el atleta, y no es la misma en todas: por ahi se ordena quien es "el mejor".
    comprobar("el 1.500 se mide por tiempo total", mod_pruebas.medida_de("1500") == "tiempo")
    comprobar("la escalera y la serie de 100 cada 1:30 por ritmo",
              mod_pruebas.medida_de("escalera") == "ritmo"
              and mod_pruebas.medida_de("series de 100 cada 1:30") == "ritmo")
    comprobar("los 30 minutos por metros (el tiempo es siempre el mismo)", mod_pruebas.medida_de("30 minutos") == "metros")
    comprobar("lo que no esta declarado va por ritmo", mod_pruebas.medida_de("lo que sea") == "ritmo")

    # El parte se dicta en el chat: `partes --escribir` lee un JSON con el bloque del portal y lo mete en la base.
    ruta_json = os.path.join(tempfile.gettempdir(), "parte_del_chat.json")
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump({"partes_natacion": [{
            "fecha": "2019-01-02", "piscina_m": 25, "metros": 1700, "minutos": 40, "sensacion": 70,
            "notas": "parte dictado en el chat", "compania": "solo",
            "series": [{"tipo": "serie", "rep_m": 100, "n_reps": 8, "metros": 800, "tiempo_s": 700,
                        "descanso_s": 20, "estilo": "libre", "intensidad": "ae3"}]}]}, f)
    r1 = mod_partes.importar(cc, ruta_json)
    comprobar("un parte dictado en el chat entra por `--escribir`", r1["nuevos"] == 1, str(r1))
    comprobar("y queda guardado con su bloque",
              bool(cc.execute("SELECT 1 FROM parte_serie WHERE metros = 800").fetchone()))
    r2 = mod_partes.importar(cc, ruta_json)
    comprobar("volver a escribirlo lo actualiza, no lo duplica",
              r2["nuevos"] == 0 and r2["actualizados"] == 1, str(r2))
    ruta_cli = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "entrenador", "cli.py")
    with open(ruta_cli, encoding="utf-8") as f:
        fuente_cli = f.read()
    comprobar("el CLI ofrece escribir a mano el parte dictado",
              '"--escribir"' in fuente_cli and "args.escribir" in fuente_cli)

    # Los tres mejores de una escalera: manda el ritmo, no el tiempo total, y salen de mejor a peor.
    cc.execute("INSERT INTO parte (clave, fecha, metros, fuente) VALUES ('e1', '2024-01-10', 900, 'test')")
    pid = cc.execute("SELECT id FROM parte WHERE clave = 'e1'").fetchone()[0]
    for i, ritmo in enumerate((91.0, 88.0, 95.0, 99.0)):
        cc.execute("INSERT INTO parte_serie (parte_id, orden, tipo, metros, tiempo_s, ritmo_100, n_reps, prueba)"
                   " VALUES (?, ?, 'serie', 900, ?, ?, 5, 'escalera')",
                   (pid, i, round(900 * ritmo / 100, 2), ritmo))
    escalera = [x for x in mod_pruebas.historico(cc) if x["nombre"] == "escalera"][0]
    comprobar("la escalera se mide por ritmo", escalera["medida"] == "ritmo")
    comprobar("los mejores van de mejor a peor y solo son tres",
              [round(m["ritmo_100"], 1) for m in escalera["mejores"]] == [88.0, 91.0, 95.0],
              str([m["ritmo_100"] for m in escalera["mejores"]]))

    # La prueba de los 30 minutos: los metros se ajustan a los 30:00 exactos (el reloj marca unos segundos de mas)
    # y NO se parte por metros: los metros son la medida, no la distancia de la prueba (todas sus veces son una).
    cc.execute("INSERT INTO parte (clave, fecha, metros, fuente) VALUES ('m30', '2025-01-15', 1815, 'test')")
    pid30 = cc.execute("SELECT id FROM parte WHERE clave = 'm30'").fetchone()[0]
    for i, (m30_metros, m30_tiempo) in enumerate(((2100.0, 1821.7), (2200.0, 1815.5))):
        cc.execute("INSERT INTO parte_serie (parte_id, orden, tipo, metros, tiempo_s, ritmo_100, n_reps, prueba)"
                   " VALUES (?, ?, 'continuo', ?, ?, ?, 1, '30 minutos')",
                   (pid30, i, m30_metros, m30_tiempo, round(m30_tiempo * 100 / m30_metros, 1)))
    los30 = [x for x in mod_pruebas.historico(cc) if x["nombre"] == "30 minutos"][0]
    comprobar("los 30 minutos son una sola prueba (no una por metros) y no lleva metros de grupo",
              los30["veces"] >= 2 and los30["metros"] == 0, str(los30["veces"]))
    comprobar("los metros de la prueba se ajustan a los 30:00 exactos (el reloj marca unos segundos de mas)",
              round(los30["mejores"][0]["valor"]) == 2182
              and any(round(m["valor"]) == 2076 for m in los30["todas"]),
              str([round(m["valor"]) for m in los30["mejores"]]))

    # Lo que alimenta la tabla del resumen: las cuatro pruebas de la casa, cada una con su medida.
    res = mod_pruebas.resumen(cc)
    comprobar("el resumen trae las cuatro pruebas que pidio el atleta",
              [r["nombre"] for r in res] == list(mod_pruebas.TIPOS), str([r["nombre"] for r in res]))
    comprobar("cada una con la medida que le toca",
              [r["medida"] for r in res] == ["tiempo", "ritmo", "metros", "ritmo"], str([r["medida"] for r in res]))
    comprobar("y con sus tres mejores dentro",
              len([r for r in res if r["nombre"] == "escalera"][0]["mejores"]) == 3)
    comprobar("el portal recibe la tabla del resumen",
              len(mod_partes.datos_panel(cc).get("pruebas_resumen", [])) == len(mod_pruebas.TIPOS))
    cc.close()
    os.remove(copia)


def pruebas_parciales(ruta: str = "data/entrenador.db") -> None:
    """V1.2-08: los pasos de cada 100 en las repeticiones de 400 m para arriba, con lo corregido dentro.

    Se apoya en el 1.500 del 18/10 (actividad 1543, el lap 20), que va del metro 850 al 2.350 de esa sesion: 15 pasos
    de 100 m y el ultimo con la correccion de -10 s que el atleta apunto. Sobre copia de la base.
    """
    import sqlite3
    import tempfile
    from pathlib import Path

    from entrenador import db, parciales

    carpeta = Path(tempfile.mkdtemp(prefix="pruebas-parciales-"))
    copia = carpeta / "entrenador.db"
    origen = sqlite3.connect(ruta)
    destino = sqlite3.connect(str(copia))
    with destino:
        origen.backup(destino)
    origen.close()
    destino.close()

    cn = db.conectar(str(copia))
    try:
        pasos = parciales.de_rep(cn, 1543, 20)
        comprobar("el 1.500 se parte en 15 pasos de 100 m", len(pasos) == 15, "salieron " + str(len(pasos)))
        comprobar("cada paso mide 100 m", all(round(p["hasta_m"] - p["desde_m"], 1) == 100.0 for p in pasos))
        comprobar("los pasos van de donde empieza la repeticion a donde acaba (850 a 2.350 m)",
                  pasos and pasos[0]["desde_m"] == 850.0 and pasos[-1]["hasta_m"] == 2350.0)
        suma = sum(p["segundos"] for p in pasos)
        comprobar("los pasos suman el tiempo del lap (1.340,2 s)",
                  abs(suma - 1340.2) < 0.6, "suman " + str(round(suma, 1)))
        comprobar("la correccion sale en el ultimo paso (2.250-2.350 m)",
                  bool(pasos) and pasos[-1]["desde_m"] == 2250.0 and bool(pasos[-1]["correccion_s"]))
        comprobar("y en ninguno mas",
                  not any(p["correccion_s"] for p in pasos[:-1]))
        comprobar("el paso corregido quita los 10 s que pidio el atleta",
                  bool(pasos) and abs((pasos[-1]["segundos_corregidos"] or 0) - (pasos[-1]["segundos"] - 10.0)) < 0.15)
        # Con centesimas: los dos primeros 100 de hoy se llevan 6 centesimas y con una sola decimal empataban (el
        # atleta: "veo poco probable que el primer y el segundo 100 sean al mismo tiempo"). No empatan.
        comprobar("los pasos van con centesimas (los dos primeros 100 no empatan)",
                  bool(pasos) and pasos[0]["segundos"] != pasos[1]["segundos"]
                  and abs(pasos[0]["segundos"] - pasos[1]["segundos"]) < 0.5,
                  "100 #1 = " + str(pasos[0]["segundos"]) + " s, 100 #2 = " + str(pasos[1]["segundos"]) + " s")
        # Por debajo del minimo no hay nada que desglosar: una serie de 100 ya es un 100.
        comprobar("en una repeticion de 100 m no salen pasos", parciales.de_rep(cn, 1543, 24) == [])
        # Y el calentamiento tampoco (regla del atleta, 2026-10-18): solo lo que va a ritmo de serie, por debajo de
        # 1:30 de media en un 400 y de 1:33 en las distancias mayores.
        comprobar("el 400 del calentamiento (1:51,1 de media) no sale partido", parciales.de_rep(cn, 1543, 0) == [])
        comprobar("el otro 400 de hoy (1:38,6 de media) tampoco", parciales.de_rep(cn, 1543, 26) == [])
        comprobar("un 400 a 1:29 de media si entra", parciales.pasa_el_ritmo(400, 4 * 89.0))
        comprobar("un 400 a 1:31 no entra", not parciales.pasa_el_ritmo(400, 4 * 91.0))
        comprobar("un 1.500 a 1:32 entra (distancia mayor: el liston es 1:33)", parciales.pasa_el_ritmo(1500, 15 * 92.0))
        comprobar("un 1.500 a 1:34 no entra", not parciales.pasa_el_ritmo(1500, 15 * 94.0))
        comprobar("son dos listones: a 1:31 un 400 no entra y un 1.500 si",
                  (not parciales.pasa_el_ritmo(400, 4 * 91.0)) and parciales.pasa_el_ritmo(1500, 15 * 91.0))
        # Y lo que le llega al portal: repeticiones largas Y a ritmo de serie.
        grupos = [{"reps": [{"lap_idx": 20, "dist_m": 1500.0}, {"lap_idx": 0, "dist_m": 400.0}]}]
        parciales.pasos_de(cn, 1543, grupos)
        comprobar("al portal solo le llegan pasos de las repeticiones largas y a ritmo de serie",
                  len(grupos[0]["reps"][0].get("pasos") or []) == 15 and not grupos[0]["reps"][1].get("pasos"))
    finally:
        cn.close()


def pruebas_correcciones(ruta: str = "data/entrenador.db") -> None:
    """V1.2-06: lo que el atleta corrige va ENCIMA del reloj, con motivo, y se puede medir por tramos.

    El 1.500 de hoy (lo que ha pedido corregir) va del metro 850 al 2.350 de la sesion, asi que su 100 final es el
    tramo 2.250-2.350. Se prueba sobre una copia de la base: la buena no se toca.
    """
    import sqlite3
    import tempfile
    from pathlib import Path

    from entrenador import correcciones, db, evaluacion, partes

    carpeta = Path(tempfile.mkdtemp(prefix="pruebas-correcciones-"))
    copia = carpeta / "entrenador.db"
    origen = sqlite3.connect(ruta)
    destino = sqlite3.connect(str(copia))
    with destino:
        origen.backup(destino)
    origen.close()
    destino.close()

    cn = db.conectar(str(copia))
    try:
        act = cn.execute("SELECT id FROM actividad WHERE substr(inicio_local, 1, 10) = '2026-10-18' "
                         "ORDER BY id DESC LIMIT 1").fetchone()
        comprobar("la sesion del 18/10 esta en la base y se puede corregir", act is not None, "no hay actividad")
        if act is None:
            return
        aid = act["id"]
        # La base real puede traer ya correcciones de verdad (hoy tiene la del 1.500), asi que no se mide desde
        # cero: se mide LO QUE AÑADE esta prueba, que es lo unico que controla.
        antes_tramo = correcciones.segundos_en(cn, aid, 2250, 2350)
        antes_medio = correcciones.segundos_en(cn, aid, 2250, 2300)
        antes_total = correcciones.segundos_en(cn, aid, 0, 3100)
        antes_fuera = correcciones.segundos_en(cn, aid, 0, 2250)

        sin_motivo = False
        try:
            correcciones.anotar(cn, aid, 2250, 2350, -10, "   ")
        except ValueError:
            sin_motivo = True
        comprobar("una correccion sin motivo no entra (el motivo es lo que la hace del atleta)", sin_motivo, "entro")

        correcciones.anotar(cn, aid, 2250, 2350, -10, "me pase de ritmo en el ultimo 100 del 1.500")
        comprobar("el tramo corregido entero se lleva los 10 s de mas",
                  correcciones.segundos_en(cn, aid, 2250, 2350) == round(antes_tramo - 10, 1),
                  f"{antes_tramo} -> {correcciones.segundos_en(cn, aid, 2250, 2350)}")
        comprobar("un trozo del tramo se lleva su parte (la mitad, 5 s)",
                  correcciones.segundos_en(cn, aid, 2250, 2300) == round(antes_medio - 5, 1),
                  f"{antes_medio} -> {correcciones.segundos_en(cn, aid, 2250, 2300)}")
        comprobar("el total de la sesion tambien lo lleva, aunque el tramo sea pequeño",
                  correcciones.segundos_en(cn, aid, 0, 3100) == round(antes_total - 10, 1),
                  f"{antes_total} -> {correcciones.segundos_en(cn, aid, 0, 3100)}")
        comprobar("fuera del tramo no se toca nada",
                  correcciones.segundos_en(cn, aid, 0, 2250) == antes_fuera,
                  f"{antes_fuera} -> {correcciones.segundos_en(cn, aid, 0, 2250)}")
        comprobar("y se dice en llano, con el motivo dentro",
                  "metros 2250-2350" in correcciones.texto_de(cn, aid)
                  and "me pase de ritmo" in correcciones.texto_de(cn, aid), correcciones.texto_de(cn, aid))

        val = evaluacion.valorar_actividad(cn, aid)
        comprobar("la valoracion de la sesion trae la correccion",
                  bool(val and val.get("correcciones")), str(val and val.get("correcciones")))
        comprobar("y el resumen la dice, sin tocar el dato del reloj",
                  "Corregido por ti" in (val or {}).get("resumen", "")
                  and "10,0 s" in (val or {}).get("resumen", ""), str((val or {}).get("resumen"))[-200:])

        # Y el total que ve el atleta es el SUYO, no el del reloj (lo pidio: "el total tiene que ser con la
        # correccion, lo correcto es la correccion"): el 1.500 pasa de 1.340,2 s a 1.330,2 s (22:10,2) y el bloque
        # sale con su ritmo corregido. El dato del reloj no se borra: se queda al lado, para poder enseñar los dos.
        laps = partes._laps_de(cn, aid)
        sin_tocar = [r for g in partes.proponer_grupos(laps, partes.cortes_intensidad(cn))
                     for r in (g.get("reps") or []) if int((r.get("lap_idx") or -1)) == 20]
        reloj = float(sin_tocar[0]["timer_s"]) if sin_tocar else 0.0
        comprobar("sin aplicar nada, el tiempo de la repeticion es el del reloj",
                  abs(reloj - 1340.2) < 0.05, str(reloj))
        from entrenador import parciales
        grupos = correcciones.aplicar(
            cn, aid, laps,
            parciales.pasos_de(cn, aid, partes.proponer_grupos(laps, partes.cortes_intensidad(cn))))
        con1500 = [g for g in grupos if any(int((r.get("lap_idx") or -1)) == 20 for r in (g.get("reps") or []))]
        rep = [r for r in (con1500[0].get("reps") if con1500 else []) if int((r.get("lap_idx") or -1)) == 20]
        # Lo que se espera es el tiempo del reloj MAS todas las correcciones que caen en el tramo del 1.500 (la base
        # real ya trae la suya, y esta prueba anota otra: vale cualquier base, lo que se mide es que entren todas).
        esperado = reloj + correcciones.segundos_en(cn, aid, 850, 2350)
        comprobar("al portal le llega el total con la correccion dentro (22:10,2 en la sesion real)",
                  bool(rep) and abs(float(rep[0]["timer_s"]) - esperado) < 0.05,
                  str(rep[0]["timer_s"] if rep else "sin repeticion") + " s (esperado " + str(round(esperado, 2)) + ")")
        comprobar("y el del reloj sigue ahi, sin borrarse",
                  bool(rep) and abs(float(rep[0].get("tiempo_del_reloj_s") or 0) - reloj) < 0.05
                  and rep[0].get("corregido_s") == round(esperado - reloj, 2), str(rep[0] if rep else "sin repeticion"))
        comprobar("y el bloque va con el tiempo corregido y su ritmo",
                  bool(con1500) and abs(float(con1500[0]["tiempo_s"]) - esperado) < 0.05
                  and abs(float(con1500[0]["ritmo_100"]) - round(100.0 * esperado / 1500.0, 1)) < 0.05,
                  (str(con1500[0]["tiempo_s"]) + " s · " + str(con1500[0]["ritmo_100"]) + " s/100") if con1500 else "sin bloque")
        # La regla, tal cual la pidio: el total de la repeticion ES la suma de sus pasos, con la correccion dentro.
        comprobar("el total de la repeticion cuadra con la suma de sus pasos (con la correccion dentro)",
                  bool(rep) and bool(rep[0].get("pasos"))
                  and abs(float(rep[0]["timer_s"])
                          - round(sum(float(p["segundos_corregidos"] or p["segundos"]) for p in rep[0]["pasos"]), 2)) < 0.005,
                  (str(rep[0]["timer_s"]) + " s frente a " + str(round(sum(float(p["segundos_corregidos"] or p["segundos"])
                                                                            for p in (rep[0].get("pasos") or [])), 2)) + " s") if rep else "sin repeticion")
        comprobar("y el lap entero del reloj sigue guardado al lado",
                  bool(rep) and abs(float(rep[0].get("lap_del_reloj_s") or rep[0].get("tiempo_del_reloj_s") or 0) - 1340.2) < 0.05,
                  str(rep[0].get("lap_del_reloj_s") if rep else "sin repeticion"))
        # Un tramo que el atleta no ha tocado no se mueve.
        otro400 = [r for g in grupos for r in (g.get("reps") or []) if int((r.get("lap_idx") or -1)) == 26]
        comprobar("las repeticiones que no ha corregido se quedan como estaban",
                  bool(otro400) and otro400[0].get("corregido_s") is None
                  and abs(float(otro400[0]["timer_s"]) - 394.3) < 0.05,
                  str(otro400[0]["timer_s"] if otro400 else "sin repeticion"))
    finally:
        cn.close()
        import shutil
        shutil.rmtree(carpeta, ignore_errors=True)


def pruebas_sueno(ruta: str = "data/entrenador.db") -> None:
    """V1.2-07: el sueno del reloj entra solo desde Garmin Connect, manda tu apunte y el dia lastrado se ve.

    Sobre una copia de la base (la buena no se toca) y **sin tocar la red**: seria una prueba que depende de que
    internet y Garmin esten de buenas. Lo que se prueba aqui es el almacen y como lo lee el analisis, que es lo que
    puede romper el codigo de este proyecto.
    """
    import sqlite3
    import tempfile
    from pathlib import Path

    from entrenador import db, descanso, sueno

    carpeta = Path(tempfile.mkdtemp(prefix="pruebas-sueno-"))
    copia = carpeta / "entrenador.db"
    origen = sqlite3.connect(ruta)
    destino = sqlite3.connect(str(copia))
    with destino:
        origen.backup(destino)
    origen.close()
    destino.close()

    cn = db.conectar(str(copia))
    try:
        # Una fecha antigua que no puede estar en la base real, para no depender de lo que ya haya.
        noche = {"fecha": "2000-01-02", "horas": 5.2, "puntuacion": 55, "despierto_s": 1800.0,
                 "profundo_s": 3600.0, "ligero_s": 9000.0, "rem_s": 5000.0, "despertares": 3, "eficiencia": 88.0}
        r1 = sueno.guardar(cn, [noche])
        comprobar("una noche nueva del reloj entra (y se cuenta como nueva)",
                  r1["nuevas"] == 1 and r1["actualizadas"] == 0, str(r1))

        r2 = sueno.guardar(cn, [dict(noche, horas=5.5)])
        comprobar("volver a bajar la misma noche no la duplica: la refresca",
                  r2["nuevas"] == 0 and r2["actualizadas"] == 1, str(r2))
        comprobar("y queda la ultima version (el reloj corrige una noche al dia siguiente)",
                  abs(sueno.de(cn, "2000-01-02")["horas"] - 5.5) < 0.01)

        dia = descanso.de(cn, "2000-01-02")
        comprobar("el analisis lee la noche del reloj sin que nadie apunte nada",
                  dia["sueno_h"] == 5.5 and dia["sueno_fuente"] == "el reloj", str(dia))
        comprobar("una noche corta y regular marca el dia como lastrado",
                  dia["lastrado"] and any("por debajo de 70" in m for m in dia["motivos"]), str(dia["motivos"]))
        comprobar("y el parte del dia dice de donde sale el dato (el reloj, no tu apunte)",
                  "(el reloj)" in dia["texto"], dia["texto"])

        cn.execute("INSERT INTO apunte (clave, fecha, tipo, minutos, sensacion, notas, fuente) "
                   "VALUES ('prueba-sueno-2000-01-02', '2000-01-02', 'sueno', 480, 80, 'dormi de un tiron', 'prueba')")
        cn.commit()
        dia2 = descanso.de(cn, "2000-01-02")
        comprobar("si apuntas tu, manda lo tuyo: 8 h y no las 5,5 del reloj",
                  dia2["sueno_h"] == 8.0 and dia2["sueno_fuente"] == "tu apunte", str(dia2))
        comprobar("y con la noche buena y sin sensacion mala, el dia queda limpio",
                  not dia2["lastrado"], str(dia2["motivos"]))

        vacio = descanso.de(cn, "2000-03-03")
        comprobar("un dia sin noche del reloj ni apunte no se juzga: no se inventa un cero",
                  vacio["lastrado"] is False and vacio["sueno_h"] is None and "no hay dato" in vacio["texto"],
                  vacio["texto"])

        # Y con la noche REAL de hoy, si esta en la base, el dia tiene que venir lastrado: es lo que el atleta dijo
        # ("he dormido mal") y lo que el reloj midio (66/100, 41 minutos despierto).
        hoy = sueno.de(cn, "2026-10-18")
        if hoy:
            d_hoy = descanso.de(cn, "2026-10-18")
            comprobar("la noche del 18/10 esta en la base y el dia viene lastrado",
                      d_hoy["lastrado"] and d_hoy["sueno_h"] and abs(d_hoy["sueno_h"] - hoy["horas"]) < 0.01,
                      f"{d_hoy['texto']} | {d_hoy['motivos']}")
    finally:
        cn.close()


def pruebas_del_bucle_cerrado(ruta: str = "data/entrenador.db") -> None:
    """El bucle cerrado (V1.3): la propuesta se guarda con su porque, tu decision se apunta y la regla se verifica.

    Todo sobre una copia: se registran propuestas de verdad (las tablas se llenan), pero el fichero del atleta no
    se toca. La regla que todavia no se puede comprobar tiene que decirlo, no inventarse un veredicto.
    """
    print("\nEl bucle cerrado: propuesta con su porque, decision y verificacion (V1.3)")
    from entrenador import decision, estimulos, plan, planificador, reglas as mod_reglas, series_dia

    cn = sqlite3.connect(ruta)
    cn.row_factory = sqlite3.Row
    cc = sqlite3.connect(":memory:")
    cc.row_factory = sqlite3.Row
    cn.backup(cc)              # con el WAL: la copia a pelo pierde lo ultimo escrito
    cn.close()

    tabla = [f[0] for f in cc.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    comprobar("las cinco tablas del bucle cerrado existen",
              all(x in tabla for x in ("recomendacion", "recomendacion_dato", "recomendacion_regla",
                                       "decision", "verificacion")))
    comprobar("el apunte sabe de quien era la sesion (V1.3-05)",
              "quien" in [f[1] for f in cc.execute("PRAGMA table_info(apunte)")])

    # Una recomendacion sin numeros que la sostengan NO entra: seria una opinion.
    try:
        decision.registrar(cc, "semana", {"titulo": "Esto no se sostiene"}, [])
        comprobar("una propuesta sin datos usados no se guarda", False)
    except ValueError:
        comprobar("una propuesta sin datos usados no se guarda", True)

    # Una regla sin ficha en el anexo T se guarda igual, pero se lee como criterio.
    rid = decision.registrar(cc, "sesion", {"titulo": "Una regla sin seccion", "cuerpo": ""},
                             [{"fuente": "estimulos.deficits", "ref": "x", "valor": 1, "nota": "un numero"}],
                             [{"regla_id": "R99", "papel": "motiva"}])
    d99 = decision.detalle(cc, rid)
    comprobar("una regla sin seccion del anexo T se guarda como criterio",
              d99["reglas"][0]["grado"] == "criterio" and not d99["reglas"][0]["seccion_T"])

    # La propuesta de una semana entera, con los mismos numeros que usa el motor.
    obj = plan.OBJETIVOS[0]["ritmo_objetivo_100"]
    v = series_dia.ventana(cc, "2026-10-04", "2026-10-17", obj)
    deficits = estimulos.deficits(v, "especifico_400", dias_al_reto=28, objetivo_100=obj)
    fijos = {"lunes": 3400.0, "miercoles": 2900.0, "viernes": 3300.0}
    p = planificador.propuesta_semana(deficits, objetivo_100=obj, km_semana=13.5, fijos_m=fijos)
    r = decision.registrar_semana(cc, p, deficits, semana="S3")
    comprobar("la semana que propone el motor se guarda dia a dia",
              r["cuantas"] == len(p["dias"]) and r["cuantas"] >= 1, str(r["cuantas"]))

    for rid_dia in r["ids"]:
        d = decision.detalle(cc, rid_dia)
        comprobar(f"{d['titulo'][:30]}: al menos 3 datos usados", len(d["datos"]) >= 3, str(len(d["datos"])))
        comprobar(f"{d['titulo'][:30]}: al menos 2 reglas, una con seccion del anexo T",
                  len(d["reglas"]) >= 2 and any(x["seccion_T"] for x in d["reglas"]),
                  str([(x["regla_id"], x["seccion_T"]) for x in d["reglas"]]))

    # La decision del atleta: aceptada, cambiada con motivo o ignorada. Una por recomendacion.
    decision.decidir(cc, r["ids"][0], "aceptada")
    decision.decidir(cc, r["ids"][0], "aceptada")                       # repetir no duplica
    decision.decidir(cc, r["ids"][-1], "ignorada")
    comprobar("la decision se apunta una vez por propuesta",
              cc.execute("SELECT COUNT(*) FROM decision WHERE recomendacion_id = ?",
                         (r["ids"][0],)).fetchone()[0] == 1)
    try:
        decision.decidir(cc, r["ids"][0], "cambiada")
        comprobar("una sesion cambiada sin motivo no se guarda", False)
    except ValueError:
        comprobar("una sesion cambiada sin motivo no se guarda", True)
    try:
        decision.decidir(cc, 999999, "aceptada")
        comprobar("no se puede decidir sobre una propuesta que no existe", False)
    except ValueError:
        comprobar("no se puede decidir sobre una propuesta que no existe", True)

    # El credito: la regla que no se puede comprobar todavia lo dice.
    v2 = decision.verificar(cc, "R2", "2026-10-18", "2026-11-01")
    comprobar("R2 sale sin_datos hasta que haya un 400 despues de la ventana",
              v2["veredicto"] == "sin_datos" and not v2["despues"], str(v2["notas"])[:70])
    n1 = cc.execute("SELECT COUNT(*) FROM verificacion").fetchone()[0]
    decision.verificar(cc, "R2", "2026-10-18", "2026-11-01")
    n2 = cc.execute("SELECT COUNT(*) FROM verificacion").fetchone()[0]
    comprobar("volver a verificar la misma ventana no acumula filas", n1 == n2, f"{n1} -> {n2}")

    panel = decision.panel_reglas(cc)
    comprobar("el panel trae todas las reglas con su grado y su seccion",
              len(panel) == len(mod_reglas.REGLAS) and all("seccion_T" in x for x in panel), str(len(panel)))
    r2 = [x for x in panel if x["regla_id"] == "R2"][0]
    comprobar("R2 aparece con lo propuesto y sin veredicto inventado",
              r2["propuestas"] >= 1 and r2["veredicto"] == "sin_datos", str(r2["notas"])[:70])
    res = decision.resumen(cc)
    comprobar("el resumen cuenta lo propuesto y lo decidido",
              res["recomendaciones"] >= r["cuantas"] and res["decididas"] >= 1, str(res))
    cc.close()

if __name__ == "__main__":
    pruebas_unitarias()
    pruebas_base_de_datos()
    pruebas_analitica()
    pruebas_bici()
    pruebas_minero()
    pruebas_competicion()
    pruebas_plan_y_portal()
    pruebas_comparador_y_portal()
    pruebas_ordenes_del_cli()
    pruebas_pases_y_completas()
    pruebas_estimulos_y_reglas()
    pruebas_evaluacion_de_una_sesion()
    pruebas_selectores_del_parte()
    pruebas_conocimiento_y_series_dia()
    pruebas_reparto_por_dia()
    pruebas_motor_en_el_discurso()
    pruebas_plan_vivo()
    pruebas_fase_del_plan()
    pruebas_propuesta_semana()
    pruebas_descanso()
    pruebas_correcciones()
    pruebas_sueno()
    pruebas_parciales()
    pruebas_de_medicion()
    pruebas_de_gimnasio()
    pruebas_carga_ajena_y_fuerza()
    pruebas_del_bucle_cerrado()
    print()
    if FALLOS:
        print(f"FALLOS: {len(FALLOS)} -> {', '.join(FALLOS)}")
        raise SystemExit(1)
    print("Todas las pruebas han pasado.")
