#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Genera el cuadro de mando (pagina HTML autocontenida) y el informe de segmentos.

Entrada: el paquete de analitica de `analitica.analizar()`.
Salidas (dentro del proyecto, nunca en la raiz de D:):

- `cuadro/panel.html`: cuadro de mando para abrir en el navegador o ver dentro de Hermes.
- `informes/H_analitica_segmentos.md`: el mismo contenido en texto, para leer o imprimir.

La aplicacion (diseno, esqueleto y logica) vive en `entrenador/app/`:

- `app.css`: hoja de estilo con las variables de tema y los componentes.
- `plantilla.html`: esqueleto con los huecos `__CSS__`, `__DATOS__` y `__JS__`.
- `app.js`: toda la logica (navegacion, filtros, comparador, graficos y gimnasio), en el navegador.

Aqui solo se montan los tres en un solo fichero, sin servidor, sin red y sin pedir nada a nadie.
"""

from __future__ import annotations

import html

from . import perfil

import json
import os
from datetime import datetime

ANCHO_PX = 1080


def _cuando(iso: str) -> str:
    """'2026-10-18T19:42:33+02:00' -> '18/10/2026 a las 19:42'. Vacio si no hay sello."""
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y a las %H:%M")
    except (TypeError, ValueError):
        return str(iso)


def datos_panel(cn) -> dict:
    """Lo que el cuadro de mando necesita y no sale de la analitica de entrenamiento:

    - `competicion`: las marcas oficiales de la RFEN que ya estan en la base (tabla `competicion`).
    - `plan`: las semanas hasta el 400 objetivo y los bloques hasta el 3.000 objetivo.

    Se importa dentro de la funcion para no obligar a tener marcas cargadas cuando solo se mira el entrenamiento.
    """
    from . import apuntes, competicion, plan, plan_vivo

    # El plan va con su version recalculada: la escrita es la referencia, y `vivo` es la que se rehace con cada
    # entrenamiento que entra (con lo que ha pasado de verdad en la semana anterior).
    salida = {"plan": dict(plan.datos(), vivo=plan_vivo.datos(cn)), "competicion": None,
              "apuntes": apuntes.resumen(cn), "estado": None, "resultados": None}
    try:
        from . import resultados as _resultados
        salida["resultados"] = _resultados.resumen(cn)
    except Exception as exc:
        salida["resultados"] = {"error": f"no se pudo calcular el bucle de resultados: {exc}"}
    try:
        from . import estado as _estado
        salida["estado"] = _estado.calcular(cn).a_dict()
    except Exception as exc:
        # El panel no puede quedarse en blanco porque el estado falle: se dice y se sigue.
        salida["estado"] = {"estado_id": "", "fecha": "", "secciones": [],
                            "error": f"no se pudo calcular el estado: {exc}"}
    r = competicion.resumen(cn)
    if not r.get("total"):
        return salida

    # Todas las filas del historial con su `tipo`, su `motivo` y su `madre` (la prueba de la que son tramo, si
    # son un pase). Se recalculan al vuelo con competicion.clasificar() en vez de leerse de la base: asi el
    # portal enseña siempre lo que dice el criterio de verdad (ver competicion.clasificar_sesion), sin
    # depender de que la tabla este sincronizada.
    todas = []
    for f in competicion.clasificar(cn):
        if not f["valida"]:
            continue
        f = dict(f)
        f["ritmo_100"] = None if f["ritmo_100"] is None else round(f["ritmo_100"], 1)
        todas.append(f)

    # Solo marcas suyas para "mejores" y para la evolucion del 400 y el 3.000: un 1000 o un 2000 de un dia de
    # 3.000 es un paso, no una marca; un 50 o un 200 de relevo si es marca suya.
    def limpia(f: dict) -> dict:
        g = dict(f)
        g.pop("madre", None)
        return g

    suyas = sorted([f for f in todas if f["tipo"] == "prueba"],
                   key=lambda f: (f["estilo"], f["distancia_m"], f["piscina_m"], f["segundos"]))
    mejores, vistas = [], set()
    for f in suyas:
        clave = (f["estilo"], f["distancia_m"], f["piscina_m"])
        if clave not in vistas:
            vistas.add(clave)
            mejores.append(limpia(f))

    def historial(dist: int) -> list:
        # Solo marcas suyas del 400 (o del 3.000): un 400 que fue tramo de un 1.500 no es una marca de 400.
        filas = [x for x in todas if x["estilo"] == "libre" and x["distancia_m"] == dist and x["tipo"] == "prueba"]
        return [limpia(f) for f in sorted(filas, key=lambda f: f["fecha"] or "", reverse=True)]

    salida["competicion"] = {
        "resumen": r,
        "mejores": mejores,
        "h400": historial(400),
        "h3000": historial(3000),
        "objetivo_s100": 75.0,   # bajar de 5:00 en 400 = 75,0 s/100
        # Todas las marcas validas, pases incluidos: el portal filtra, ordena y agrupa en el navegador, sin
        # preguntar a nadie. Cada fila lleva su `tipo` (prueba | pase | rara), el `motivo` y su `madre`.
        "marcas": todas,
    }
    return salida


def _fmt(v, sufijo: str = "", vacio: str = "-") -> str:
    return f"{v}{sufijo}" if v not in (None, "") else vacio


def _minutos(seg: float | None) -> str:
    if not seg:
        return "-"
    return f"{int(seg) // 60}:{int(seg) % 60:02d}"


def _crono(seg: float | None) -> str:
    """Segundos a cronometro (h:mm:ss), que es como se leen los tiempos de bici."""
    if not seg:
        return "-"
    seg = int(round(seg))
    h, resto = divmod(seg, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# --------------------------------------------------------------------------------------------- informe md


def valoracion_markdown(v: dict) -> list[str]:
    """La valoracion del entrenador en markdown, para el anexo escrito (el mismo texto que el Resumen).

    No se escribe aqui: llega compuesta de `entrenador/valoracion.py` con los datos reales de la base.
    """
    if not v or not v.get("titular"):
        return []
    lineas = ["## El entrenador dice: como vamos", "", f"*{v['titular']}*", ""]
    if v.get("generado"):
        lineas += [f"*Escrito el {_cuando(v['generado'])}.*", ""]
    for p in v.get("parrafos") or []:
        lineas += [f"**{p['titulo']}.** {p['texto']}", ""]
    if v.get("dianas"):
        lineas += ["### Con que tiempos entrenar para el reto", "", "| Serie | Diana | Por que |", "|---|---|---|"]
        for d in v["dianas"]:
            lineas.append(f"| {d['serie']} | **{d['diana']}** | {d['porque']} |")
        lineas.append("")
    for a in v.get("avisos") or []:
        lineas.append(f"- {a}")
    return lineas


def informe_segmentos(d: dict) -> str:
    k = d["kpis"]
    segmentos = d["segmentos"]
    lineas = [
        "# Anexo H - Segmentos mas habituales (descubiertos por el programa)",
        "",
        f"Generado el {_cuando(d['generado'])} a partir de {k['sesiones']} sesiones de natacion "
        f"({k['primera']} a {k['ultima']}, {k['metros_totales'] / 1000:.0f} km).",
        "",
        "El proyecto tiene **dos partes**:",
        "",
        "1. **Entrenamiento**: natacion (esta primera parte del informe) y gimnasio.",
        "2. **Portal de bici** (tipo Strava): comparar resultados y descubrir los segmentos que se repiten.",
        "",
        "El programa agrupa todo el historico en dos familias y **ordena por peso** (veces x longitud), para",
        "que los segmentos largos pesen mas que los cortos aunque se repitan menos: ",
        "",
        "- **Bloque continuo**: metros nadados del tiron (sin descanso).",
        "- **Serie**: repeticiones con descanso (10x100 m, 5x200 m...).",
        "",
        f"Se han descubierto **{k['segmentos']} segmentos** repetidos (un segmento tiene que aparecer 2 veces o",
        "mas para contar). Los ritmos son de brazo libre y **sin etiquetar material**: el reloj no lo registra.",
        "",
    ] + valoracion_markdown(d.get("valoracion") or {}) + [
        "",
        "## Los 20 segmentos de mas peso",
        "",
        "| Segmento | Tipo | Veces | Distancia | Ritmo mediana | Mejor | Ultima vez | Tendencia |",
        "|---|---|---:|---:|---:|---:|---|---:|",
    ]
    for s in segmentos[:20]:
        tend = f"{s['tendencia_s']:+.1f} s/100" if s["tendencia_s"] is not None else "-"
        lineas.append(
            f"| {s['nombre']} | {s['tipo']} | {s['apariciones']} | {s['dist_m']:.0f} m | "
            f"{_fmt(s['ritmo_mediana'])} s/100 | {_fmt(s['ritmo_mejor'])} | {s['ultima_vez']} | {tend} |"
        )

    lineas += ["", "## Los 15 segmentos mas largos", "",
               "| Segmento | Veces | Distancia total | Ritmo mediana | Mejor |",
               "|---|---:|---:|---:|---:|"]
    for s in sorted(segmentos, key=lambda x: -x["dist_m"])[:15]:
        lineas.append(f"| {s['nombre']} | {s['apariciones']} | {s['dist_m']:.0f} m | "
                      f"{_fmt(s['ritmo_mediana'])} s/100 | {_fmt(s['ritmo_mejor'])} |")

    lineas += ["", "## Mejores marcas por distancia (bloques continuos de brazo libre)", "",
               "Solo bloques verificados (brazadas coherentes con la distancia). La columna *marca de referencia* es",
               "la mediana de las 3 mejores veces, para que un lap mal cronometrado no fije un objetivo.", "",
               "| Distancia | Estilo | Piscina | Veces | Mediana | Marca de referencia | Mejor registrada | Ultima vez |",
               "|---:|---|---|---:|---:|---:|---:|---|"]
    for r in d["ritmos_por_distancia"]:
        piscina = f"{r['piscina_m']:g} m" if r["piscina_m"] else "aguas abiertas"
        estilo = "tecnica" if r["estilo"] == "drill" else (r["estilo"] or "libre/sin dato")
        lineas.append(f"| {r['dist_m']} m | {estilo} | {piscina} | {r['veces']} | {r['mediana']} s/100 | "
                      f"{r['mejor']} s/100 | {r['absoluto']} s/100 | {r['ultima_vez']} |")

    lineas += ["", "## Los 15 bloques mas largos de todo el historico", "",
               "| Fecha | Distancia | Tiempo | Ritmo | Piscina | Verificado | Sesion completa |",
               "|---|---:|---|---:|---|---|---|"]
    for b in d["bloques_largos"][:15]:
        piscina = f"{b['piscina_m']:g} m" if b["piscina_m"] else "aguas abiertas"
        lineas.append(f"| {b['fecha']} | {b['dist_m']:.0f} m | {_minutos(b['tiempo_s'])} | "
                      f"{_fmt(round(b['ritmo_100'], 1) if b['ritmo_100'] else None)} s/100 | {piscina} | "
                      f"{'si' if b['fiable'] else 'no'} | {'si' if b['domina_sesion'] else 'no'} |")

    lineas += ["", "## Volumen por ano", "", "| Ano | Sesiones | Metros | Horas |", "|---|---:|---:|---:|"]
    for a in d["volumen"]["por_ano"]:
        lineas.append(f"| {a['clave']} | {a['sesiones']} | {a['metros']:,} | {a['horas']} |".replace(",", "."))

    bici = d.get("bici") or {}
    if bici.get("segmentos"):
        bk = bici["kpis"]
        lineas += [
            "## Parte 2 - Portal de bici (tipo Strava): comparar resultados y segmentos repetidos", "",
            f"{bk['salidas']} salidas en bici ({bk['con_traza']} con traza GPS), {bk['km']:,.0f} km en total y "
            f"{bk['desnivel']:,} m de desnivel acumulado, del {bk['primera']} al {bk['ultima']}. "
            f"{bk['segmentos']} segmentos con intentos medidos ({bk['repetidos']} repetidos) y "
            f"{bk['intentos']} intentos en total.",
            "",
            "Los tiempos se miden sobre las trazas del propio atleta (punta a punta del segmento: inicio y fin "
            "que trae el fichero de segmentos del export), no se copian de ninguna web. La distancia y el "
            "desnivel son la mediana de lo medido en sus intentos, con umbral de 3 m para no contar el temblor "
            "del GPS.",
            "",
            "| Segmento | Veces | Distancia | Desnivel | Pendiente | Mejor | Mediana | Vel. media | Tendencia | Ultima vez |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for s in bici["segmentos"][:30]:
            tend = f"{s['tendencia_pct']:+.1f} %" if s["tendencia_pct"] is not None else "-"
            dist = f"{s['dist_m'] / 1000:.2f} km" if s["dist_m"] else "-"
            desn = f"{s['desnivel_m']:.0f} m" if s["desnivel_m"] is not None else "-"
            pend = f"{s['pendiente_pct']:.1f} %" if s["pendiente_pct"] is not None else "-"
            vel = f"{s['mejor_vel_kmh']:.1f} km/h" if s["mejor_vel_kmh"] else "-"
            lineas.append(f"| {s['nombre']}{' *' if s.get('dudoso') else ''} | {s['veces']} | {dist} | {desn} | "
                          f"{pend} | {_crono(s['mejor_s'])} | {_crono(s['mediana_s'])} | {vel} | {tend} | "
                          f"{s['ultima']} |")
        lineas += ["", "(*) Segmento **dudoso**: las trazas del atleta cruzan esa pareja de puntos por caminos de",
                   "distinta longitud (por ejemplo 13 km y 25 km), asi que se mide el camino mas habitual y los "
                   "intentos del otro camino no cuentan. Se avisa en vez de esconderlo.", ""]
        lineas += ["", "## Bici: mis ultimas salidas", "",
                   "| Fecha | Nombre | Distancia | Duracion | Vel. media | Desnivel | Segmentos |",
                   "|---|---|---:|---|---:|---:|---:|"]
        for s in bici.get("salidas", [])[:20]:
            dist = f"{s['dist'] / 1000:.1f} km" if s["dist"] else "-"
            vel = f"{s['vel']:.1f} km/h" if s["vel"] else "-"
            desn = f"{s['desnivel']:.0f} m" if s["desnivel"] is not None else "-"
            lineas.append(f"| {s['fecha']} | {s['nombre'] or '-'} | {dist} | {_minutos(s['dur'])} | {vel} | "
                          f"{desn} | {s['segmentos']} |")
        lineas += [""]

    gim = d.get("gimnasio") or {}
    if gim.get("n"):
        lineas += [
            "## Parte 1 - Entrenamiento: gimnasio", "",
            f"{gim['n']} sesiones en el reloj, de {gim['minutos_media']} min de media, la ultima el "
            f"{gim['ultima']}.", "",
            "| Anio | Sesiones | Minutos |", "|---|---:|---:|",
        ]
        lineas += [f"| {a['anio']} | {a['sesiones']} | {a['minutos']:,} |".replace(",", ".")
                   for a in gim["por_anio"]]
        lineas += ["", gim["nota"], "",
                   "| Ultimas sesiones | Dia | Duracion |", "|---|---|---:|"]
        lineas += [f"| {s['nombre'] or '-'} | {s['fecha']} {s['hora']} | {_minutos(s['duracion_s'])} |"
                   for s in gim["sesiones"][:10]]
        lineas += [""]

    lineas += ["", "## Nota sobre el material", "", d["nota_material"], "",
               "Cuando una sesion lleve la palabra en el nombre (palas, aletas, pull, tabla), el programa la",
               "marca sola al importarla y la saca de las comparaciones de brazo libre.", ""]
    return "\n".join(lineas)


# --------------------------------------------------------------------------------------------- pagina html


# --------------------------------------------------------------------------------------------- pagina html

# La aplicacion vive en `entrenador/app/`: el diseno (CSS), el esqueleto (HTML) y la logica (JS) estan en
# ficheros propios para poder tocarlos sin bucear en este modulo. Aqui solo se montan en un unico fichero
# autocontenido, que se abre con doble clic y no pide nada a la red.
APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")
FICHEROS_APP = ("app.css", "plantilla.html", "app.js")


def _leer_app(nombre: str) -> str:
    with open(os.path.join(APP, nombre), encoding="utf-8") as fh:
        return fh.read()


def panel_html(d: dict) -> str:
    """Devuelve la pagina del cuadro de mando con los datos incrustados (no necesita red ni servidor)."""
    for marca in ("__CSS__", "__DATOS__", "__JS__", "__TITULO__", "__DESCRIPCION__", "__INICIALES__",
                  "__ATLETA__", "__CLUB__"):
        if marca not in _leer_app("plantilla.html"):
            raise ValueError(f"la plantilla de la aplicacion no tiene el hueco {marca}")
    datos = json.dumps(dict(d, titulo_pagina=perfil.titulo()), ensure_ascii=False, separators=(",", ":"))
    plantilla = _leer_app("plantilla.html")
    plantilla = plantilla.replace("__CSS__", _leer_app("app.css"))
    plantilla = plantilla.replace("__DATOS__", datos)
    plantilla = plantilla.replace("__JS__", _leer_app("app.js"))
    # Los datos del atleta van por hueco: el nombre no esta escrito en el codigo, y sin `perfil_local.py` el panel
    # se pinta sin nombre (que es lo que se publica).
    plantilla = plantilla.replace("__TITULO__", html.escape(perfil.titulo()))
    plantilla = plantilla.replace("__DESCRIPCION__", html.escape(perfil.descripcion()))
    plantilla = plantilla.replace("__INICIALES__", html.escape(perfil.INICIALES))
    plantilla = plantilla.replace("__ATLETA__", html.escape(perfil.CORTO))
    plantilla = plantilla.replace("__CLUB__", html.escape(perfil.CLUB))
    return plantilla


def escribir(d: dict, carpeta: str = ".") -> dict:
    """Escribe el cuadro de mando y el informe en markdown. Devuelve las rutas."""
    ruta_html = os.path.join(carpeta, "cuadro", "panel.html")
    ruta_md = os.path.join(carpeta, "informes", "H_analitica_segmentos.md")
    os.makedirs(os.path.dirname(ruta_html), exist_ok=True)
    os.makedirs(os.path.dirname(ruta_md), exist_ok=True)
    with open(ruta_html, "w", encoding="utf-8") as fh:
        fh.write(panel_html(d))
    with open(ruta_md, "w", encoding="utf-8") as fh:
        fh.write(informe_segmentos(d))
    return {"panel": ruta_html, "informe": ruta_md}
