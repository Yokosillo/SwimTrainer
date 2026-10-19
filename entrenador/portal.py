#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Genera el portal de bici (tipo Strava) en un solo fichero HTML que se abre con doble clic.

Lo que hace:

- Reune lo que ya esta en la base de datos (las salidas con GPS y los segmentos, tanto los del export de
  Strava como los descubiertos en las propias trazas) y lo deja escrito dentro de `cuadro/strava/index.html`.
- El fichero lleva los datos dentro (no hay servidor ni ficheros sueltos), asi que funciona con doble clic.
- Las trazas van codificadas en el formato "polyline" de Google/Strava, que ocupa una cuarta parte que el
  JSON a pelo; la altura va como diferencias de metros.
- El mapa es Leaflet con las teselas de OpenStreetMap: gratis, sin clave y sin cuenta (Google Maps exige
  clave de API y tarjeta). Solo hace falta conexion para ver el mapa; los datos son locales.

Pantallas: Actividades (todas las salidas), ficha de una salida (mapa + sus segmentos), Segmentos (catalogo
completo) y ficha de un segmento (todos los tiempos del atleta).
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from . import db
from .bici import _buscar_intento, _prefijos
from .lector_gpx import desempaquetar

DESTINO = os.path.join("cuadro", "strava", "index.html")
PASO_TRAZA_M = 90.0        # para dibujar: un punto cada 90 m sobra (el motor usa la traza entera)
MAX_PUNTOS = 1200
PRECISION = 5              # decimales de la polilinea (como Google/Strava)
RADIO_RECORTE = 120.0      # metros a los que se pega el inicio o el fin de un segmento de Strava a la traza


# ------------------------------------------------------------------------------------ codificacion
def _varint(v: int) -> str:
    """Un entero con signo como texto del formato polyline (grupos de 5 bits + 63)."""
    v = ~(v << 1) if v < 0 else (v << 1)
    fuera = []
    while v >= 0x20:
        fuera.append(chr((0x20 | (v & 0x1F)) + 63))
        v >>= 5
    fuera.append(chr(v + 63))
    return "".join(fuera)


def polilinea(puntos: list[tuple]) -> str:
    """Traza a texto compacto (lat/lon con 5 decimales, cada punto respecto del anterior)."""
    escala = 10 ** PRECISION
    lat_prev = lon_prev = 0
    fuera = []
    for p in puntos:
        lat = int(round(p[0] * escala))
        lon = int(round(p[1] * escala))
        fuera.append(_varint(lat - lat_prev))
        fuera.append(_varint(lon - lon_prev))
        lat_prev, lon_prev = lat, lon
    return "".join(fuera)


def descodifica_polilinea_python(cadena: str, precision: int = PRECISION) -> list[tuple]:
    """Vuelve a leer lo que ha escrito `polilinea`. Esta para comprobar que codificador y descodificador
    (el de JavaScript del portal y este) dicen lo mismo; el portal usa el suyo, en JavaScript.
    """
    factor = float(10 ** precision)
    i = 0
    lat = lon = 0
    fuera = []
    while i < len(cadena):
        despla = 0
        res = 0
        while True:
            byte = ord(cadena[i]) - 63
            i += 1
            res |= (byte & 0x1F) << despla
            despla += 5
            if byte < 0x20:
                break
        lat += ~(res >> 1) if (res & 1) else (res >> 1)
        despla = 0
        res = 0
        while True:
            byte = ord(cadena[i]) - 63
            i += 1
            res |= (byte & 0x1F) << despla
            despla += 5
            if byte < 0x20:
                break
        lon += ~(res >> 1) if (res & 1) else (res >> 1)
        fuera.append((lat / factor, lon / factor))
    return fuera


def altitudes(puntos: list[tuple]) -> str:
    """Alturas (metros enteros) como diferencias, para dibujar el perfil."""
    prev = 0
    fuera = []
    for p in puntos:
        alt = int(round(p[2])) if len(p) > 2 and p[2] is not None else prev
        fuera.append(_varint(alt - prev))
        prev = alt
    return "".join(fuera)


def _adelgazar(puntos: list[tuple], paso_m: float = PASO_TRAZA_M, tope: int = MAX_PUNTOS) -> list[tuple]:
    """Quita puntos para dibujar: se queda uno cada `paso_m` metros (y el ultimo)."""
    if len(puntos) <= 2:
        return puntos
    fuera = [puntos[0]]
    acumulado = 0.0
    for a, b in zip(puntos, puntos[1:]):
        acumulado += abs(b[0] - a[0]) * 111320.0 + abs(b[1] - a[1]) * 83000.0
        if acumulado >= paso_m:
            fuera.append(b)
            acumulado = 0.0
    if fuera[-1] is not puntos[-1]:
        fuera.append(puntos[-1])
    if len(fuera) > tope:
        salto = len(fuera) / float(tope)
        fuera = [fuera[int(i * salto)] for i in range(tope)]
        fuera[-1] = puntos[-1]
    return fuera


# ------------------------------------------------------------------------------------ datos
def actividades(cn) -> list[dict]:
    """Todas las salidas con traza GPS, con su polilinea ya lista para el mapa."""
    filas = cn.execute(
        "SELECT a.id, a.inicio_local, a.nombre, a.disciplina, a.duracion_s, r.dist_m, r.desnivel_m, "
        "r.vel_media_kmh, r.puntos FROM ruta r JOIN actividad a ON a.id = r.actividad_id "
        "ORDER BY a.inicio_local DESC").fetchall()
    fuera = []
    for id_, fecha, nombre, disc, dur, dist, desn, vel, blob in filas:
        puntos = desempaquetar(blob)
        if len(puntos) < 2:
            continue
        ligeros = _adelgazar(puntos)
        fuera.append({
            "id": id_, "fecha": (fecha or "")[:16], "nombre": nombre or "", "tipo": disc or "",
            "km": round((dist or 0) / 1000.0, 2), "tiempo": int(round(dur)) if dur else None,
            "vel": round(vel, 1) if vel else None, "desnivel": round(desn or 0),
            "poly": polilinea(ligeros), "ele": altitudes(ligeros),
        })
    return fuera


def _polilinea_strava(cn, seg: dict) -> str | None:
    """Recorta de una salida la traza del trozo que corresponde a un segmento del export de Strava.

    El export solo trae el punto de inicio y el de fin, sin forma. Se busca la salida que mejor lo hizo y
    se saca de su traza el trozo de entre los dos puntos: asi el mapa dibuja la carretera, no una raya.
    """
    esfuerzo = cn.execute(
        "SELECT actividad_id FROM esfuerzo_bici WHERE segmento_id=? AND actividad_id IS NOT NULL "
        "ORDER BY tiempo_s LIMIT 1", (seg["id"],)).fetchone()
    if not esfuerzo:
        return None
    fila = cn.execute("SELECT puntos FROM ruta WHERE actividad_id=?", (esfuerzo[0],)).fetchone()
    if not fila or not fila[0]:
        return None
    puntos = desempaquetar(fila[0])
    pref = _prefijos(puntos)
    intento = _buscar_intento(puntos, pref, seg, dist_ref=seg.get("dist_m"))
    if not intento or "i" not in intento or intento["j"] <= intento["i"]:
        return None
    trozo = _adelgazar(puntos[intento["i"]:intento["j"] + 1])
    return polilinea(trozo) if len(trozo) >= 2 else None


def segmentos(cn) -> list[dict]:
    """Catalogo completo: los segmentos descubiertos en las trazas y los que vienen del export de Strava."""
    fuera = []
    for r in cn.execute(
            "SELECT id, nombre, dist_m, pendiente_pct, n_intentos, n_salidas, "
            "puntos, primera, ultima, oculto FROM segmento_minado ORDER BY n_intentos DESC, dist_m DESC"):
        id_, nombre, dist, pend, veces, salidas, blob, primera, ultima, oculto = r
        if oculto:
            continue
        puntos = desempaquetar(blob) if blob else []
        ligeros = _adelgazar(puntos) if puntos else []
        fuera.append({
            "k": f"m{id_}", "n": nombre or f"Tramo {id_}", "d": round(dist or 0),
            "p": round(pend, 1) if pend is not None else None, "v": veces or 0,
            "nsal": salidas or 0, "ori": "trazas", "f1": (primera or "")[:10],
            "f2": (ultima or "")[:10],
            "poly": polilinea(ligeros) if len(ligeros) >= 2 else "",
        })
    for r in cn.execute(
            "SELECT id, nombre, dist_m, pendiente_pct, n_esfuerzos, lat_ini, lon_ini, lat_fin, lon_fin, "
            "dudoso FROM segmento_bici WHERE COALESCE(n_esfuerzos,0) > 0 ORDER BY n_esfuerzos DESC"):
        id_, nombre, dist, pend, veces, la, lo, lf, of, dudoso = r
        seg = {"id": id_, "lat_ini": la, "lon_ini": lo, "lat_fin": lf, "lon_fin": of, "dist_m": dist}
        poly = _polilinea_strava(cn, seg)
        fuera.append({
            "k": f"s{id_}", "n": (nombre or f"Segmento {id_}") + (" *" if dudoso else ""),
            "d": round(dist or 0), "p": round(pend, 1) if pend is not None else None,
            "v": veces or 0, "nsal": None, "ori": "strava", "f1": "", "f2": "",
            "poly": poly or "", "la": la, "lo": lo, "lf": lf, "of": of,
        })
    return fuera


def intentos(cn) -> dict[str, list]:
    """Todos los tiempos de todos los segmentos, por segmento (lo que se ve al pinchar en uno)."""
    fuera: dict[str, list] = {}
    for r in cn.execute(
            "SELECT 'm' || segmento_id, fecha, tiempo_s, vel_media_kmh, dist_m, actividad_id "
            "FROM esfuerzo_minado ORDER BY fecha"):
        fuera.setdefault(r[0], []).append([(r[1] or "")[:10], round(r[2], 1) if r[2] else None,
                                           round(r[3], 1) if r[3] else None, round(r[4] or 0), r[5]])
    for r in cn.execute(
            "SELECT 's' || segmento_id, fecha, tiempo_s, vel_media_kmh, dist_m, actividad_id "
            "FROM esfuerzo_bici ORDER BY fecha"):
        fuera.setdefault(r[0], []).append([(r[1] or "")[:10], round(r[2], 1) if r[2] else None,
                                           round(r[3], 1) if r[3] else None, round(r[4] or 0), r[5]])
    return fuera


def datos(cn) -> dict:
    """Todo lo que necesita el portal, en un diccionario."""
    acts = actividades(cn)
    segs = segmentos(cn)
    ens = intentos(cn)
    segs = [s for s in segs if ens.get(s["k"])]
    for s in segs:
        tiempos = sorted(x[1] for x in ens[s["k"]] if x[1])
        s["mej"] = round(tiempos[0], 1) if tiempos else None
        s["med"] = round(tiempos[len(tiempos) // 2], 1) if tiempos else None
        s["v"] = len(tiempos)
        s["w"] = round(s["v"] * (s["d"] or 0) / 1000)   # peso = veces x km, el mismo criterio que en natacion
    return {
        "generado": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "actividades": acts,
        "segmentos": segs,
        "intentos": {s["k"]: ens[s["k"]] for s in segs},
    }


# ------------------------------------------------------------------------------------ pagina
PLANTILLA = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Portal de bici - Entrenador</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  :root {
    --fondo: #14161a; --panel: #1b1e24; --panel2: #22262e; --borde: #2e333d;
    --texto: #e8eaed; --suave: #9aa3af; --naranja: #fc5200; --azul: #4a9eff; --verde: #35c46a;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--fondo); color: var(--texto);
         font: 14px/1.45 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  header { background: var(--panel); border-bottom: 1px solid var(--borde); padding: 10px 18px;
           display: flex; align-items: baseline; gap: 18px; flex-wrap: wrap; position: sticky; top: 0; z-index: 500; }
  header h1 { font-size: 17px; margin: 0; letter-spacing: .2px; }
  header h1 span { color: var(--naranja); }
  nav { display: flex; gap: 6px; margin-left: auto; }
  nav a { color: var(--suave); text-decoration: none; padding: 5px 12px; border-radius: 18px; font-size: 13px; }
  nav a.on, nav a:hover { background: var(--panel2); color: var(--texto); }
  main { padding: 16px 18px 60px 18px; max-width: 1240px; }
  h2 { font-size: 20px; margin: 4px 0 2px 0; }
  .sub { color: var(--suave); font-size: 12.5px; margin-bottom: 12px; }
  .kpis { display: flex; gap: 10px; flex-wrap: wrap; margin: 12px 0; }
  .kpi { background: var(--panel); border: 1px solid var(--borde); border-radius: 10px; padding: 8px 13px; min-width: 104px; }
  .kpi b { display: block; font-size: 17px; font-weight: 600; }
  .kpi span { color: var(--suave); font-size: 11px; text-transform: uppercase; letter-spacing: .4px; }
  .card { background: var(--panel); border: 1px solid var(--borde); border-radius: 12px; padding: 12px 14px; margin: 12px 0; }
  .card h3 { margin: 0 0 8px 0; font-size: 13px; color: var(--suave); font-weight: 600;
             text-transform: uppercase; letter-spacing: .5px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--borde); white-space: nowrap; }
  th { color: var(--suave); font-size: 11.5px; text-transform: uppercase; letter-spacing: .4px; cursor: pointer;
       position: sticky; top: 0; background: var(--panel); }
  th.nosort { cursor: default; }
  td.num, th.num { text-align: right; }
  tbody tr:hover td { background: var(--panel2); }
  a.fila { color: var(--texto); text-decoration: none; }
  a.fila:hover { color: var(--naranja); }
  a.enlace { color: var(--azul); text-decoration: none; }
  .tabla-scroll { max-height: 62vh; overflow: auto; }
  .verde { color: var(--verde); font-weight: 600; }
  .naranja { color: var(--naranja); }
  .suave { color: var(--suave); }
  .filtros { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
  input, select { background: var(--panel); color: var(--texto); border: 1px solid var(--borde);
                  border-radius: 8px; padding: 6px 9px; font-size: 13px; }
  input { min-width: 210px; }
  #mapa { height: 460px; border-radius: 12px; border: 1px solid var(--borde); }
  .dos { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: start; }
  .migas { font-size: 12.5px; margin-bottom: 6px; }
  .migas a { color: var(--azul); text-decoration: none; }
  @media (max-width: 900px) { .dos { grid-template-columns: 1fr; } #mapa { height: 340px; } }
  .aviso { color: var(--suave); font-size: 12.5px; }
</style>
</head>
<body>
<header>
  <h1>Entrenador <span>|</span> Portal de bici</h1>
  <nav>
    <a href="#/actividades" id="nav-act">Actividades</a>
    <a href="#/segmentos" id="nav-seg">Segmentos</a>
  </nav>
</header>
<main id="vista"></main>
<div id="mapa" style="display:none"></div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const D = __DATOS__;
const DATOS_EN = "__FECHA__";

// ------------------------------------------------------------------ utilidades
function descodificaPolilinea(cadena, precision) {
  let i = 0, lat = 0, lon = 0, fuera = [];
  const factor = Math.pow(10, precision || 5);
  while (i < cadena.length) {
    let shift = 0, res = 0, byte;
    do { byte = cadena.charCodeAt(i++) - 63; res |= (byte & 0x1f) << shift; shift += 5; } while (byte >= 0x20);
    lat += (res & 1) ? ~(res >> 1) : (res >> 1);
    shift = 0; res = 0;
    do { byte = cadena.charCodeAt(i++) - 63; res |= (byte & 0x1f) << shift; shift += 5; } while (byte >= 0x20);
    lon += (res & 1) ? ~(res >> 1) : (res >> 1);
    fuera.push([lat / factor, lon / factor]);
  }
  return fuera;
}

function descodificaEnteros(cadena) {
  let i = 0, v = 0; const fuera = [];
  while (i < cadena.length) {
    let shift = 0, res = 0, byte;
    do { byte = cadena.charCodeAt(i++) - 63; res |= (byte & 0x1f) << shift; shift += 5; } while (byte >= 0x20);
    v += (res & 1) ? ~(res >> 1) : (res >> 1);
    fuera.push(v);
  }
  return fuera;
}

function hms(s) {
  if (s === null || s === undefined) return "-";
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  const dos = (n) => (n < 10 ? "0" : "") + n;
  return h > 0 ? h + ":" + dos(m) + ":" + dos(x) : m + ":" + dos(x);
}
function km(m) { return m === null || m === undefined ? "-" : (m / 1000).toFixed(2) + " km"; }
function num(v, d) { return v === null || v === undefined ? "-" : Number(v).toFixed(d === undefined ? 1 : d); }
function fecha(s) { return (s || "").slice(0, 10); }
function saleHTML(t) {
  return String(t === null || t === undefined ? "" : t).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
const AÑOS = (() => { const s = new Set(); D.actividades.forEach(a => s.add(fecha(a.fecha).slice(0, 4)));
                      return Array.from(s).filter(x => x).sort().reverse(); })();

const POR_ACTIVIDAD = {};   // id de salida -> claves de los segmentos que hizo
Object.keys(D.intentos).forEach(k => {
  D.intentos[k].forEach(x => {
    const id = x[4];
    if (!POR_ACTIVIDAD[id]) POR_ACTIVIDAD[id] = [];
    if (POR_ACTIVIDAD[id].indexOf(k) < 0) POR_ACTIVIDAD[id].push(k);
  });
});

// ------------------------------------------------------------------ mapa
let mapa = null, capa = null;
function pintaMapa(trazas, altura) {
  const cont = document.getElementById("mapa");
  cont.style.display = "block";
  cont.style.height = (altura || 460) + "px";
  if (mapa === null) {
    mapa = L.map("mapa", { scrollWheelZoom: true });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "&copy; OpenStreetMap"
    }).addTo(mapa);
  }
  if (capa) { mapa.removeLayer(capa); capa = null; }
  capa = L.layerGroup().addTo(mapa);
  const todo = [];
  trazas.forEach(t => {
    const p = descodificaPolilinea(t.puntos, 5);
    if (p.length < 2) return;
    todo.push(p);
    L.polyline(p, { color: t.color || "#4a9eff", weight: t.grosor || 4, opacity: t.alfa || 0.9 }).addTo(capa);
  });
  if (todo.length) {
    mapa.fitBounds(L.latLngBounds(todo.reduce((a, b) => a.concat(b), [])), { padding: [18, 18] });
  }
  setTimeout(() => mapa.invalidateSize(), 60);
}
function ocultaMapa() { document.getElementById("mapa").style.display = "none"; }

// ------------------------------------------------------------------ perfil
function perfilSVG(alturas, ancho, alto) {
  const n = alturas.length;
  if (n < 3) return '<div class="aviso">Sin datos de altura en esta salida.</div>';
  const min = Math.min.apply(null, alturas), max = Math.max.apply(null, alturas);
  const rango = Math.max(1, max - min);
  const puntos = alturas.map((a, i) => [i * ancho / (n - 1), alto - 6 - (a - min) * (alto - 14) / rango]);
  const linea = puntos.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const area = "0," + alto + " " + linea + " " + ancho + "," + alto;
  return '<svg viewBox="0 0 ' + ancho + " " + alto + '" width="100%" height="' + alto +
    '" preserveAspectRatio="none">' +
    '<polygon points="' + area + '" fill="rgba(74,158,255,.18)"/>' +
    '<polyline points="' + linea + '" fill="none" stroke="#4a9eff" stroke-width="1.6"/></svg>' +
    '<div class="aviso">Altura: de ' + Math.round(min) + " m a " + Math.round(max) + " m</div>";
}

function evolucionSVG(filas, ancho, alto) {
  if (filas.length < 2) return '<div class="aviso">Hacen falta al menos dos intentos para ver la evolucion.</div>';
  const tiempos = filas.map(f => f[1]);
  const min = Math.min.apply(null, tiempos), max = Math.max.apply(null, tiempos);
  const rango = Math.max(1, max - min);
  const puntos = tiempos.map((t, i) => [8 + i * (ancho - 16) / (filas.length - 1), 8 + (max - t) * (alto - 20) / rango]);
  const linea = puntos.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  let circulos = "";
  puntos.forEach((p, i) => {
    const esMejor = tiempos[i] === min;
    circulos += '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="' + (esMejor ? 4 : 2.4) +
      '" fill="' + (esMejor ? "#35c46a" : "#fc5200") + '"/>';
  });
  return '<svg viewBox="0 0 ' + ancho + " " + alto + '" width="100%" height="' + alto + '">' +
    '<polyline points="' + linea + '" fill="none" stroke="#6b7280" stroke-width="1.2"/>' + circulos + "</svg>" +
    '<div class="aviso">Verde = mejor tiempo. Izquierda = mas antiguo, derecha = mas reciente.</div>';
}

// ------------------------------------------------------------------ vistas
let estado = { orden: "fecha", direccion: -1, minimo: 1, texto: "", tipo: "", ano: "" };

function vistaActividades() {
  ocultaMapa();
  const tipos = Array.from(new Set(D.actividades.map(a => a.tipo))).sort();
  let html = '<h2>Todas mis actividades</h2>' +
    '<div class="sub">' + D.actividades.length + " salidas con traza GPS. Datos generados el " + DATOS_EN +
    '. Pincha en una para ver el mapa y sus segmentos.</div>' +
    '<div class="filtros">' +
    '<input id="busca" placeholder="Buscar por nombre..." value="' + saleHTML(estado.texto) + '">' +
    '<select id="fTipo"><option value="">Todos los deportes</option>' +
    tipos.map(t => '<option value="' + saleHTML(t) + '"' + (t === estado.tipo ? " selected" : "") + ">" +
      saleHTML(t) + "</option>").join("") + "</select>" +
    '<select id="fAno"><option value="">Todos los anos</option>' +
    AÑOS.map(a => '<option value="' + a + '"' + (a === estado.ano ? " selected" : "") + ">" + a + "</option>").join("") +
    "</select>" +
    '<button id="limpia" style="background:var(--panel);color:var(--texto);border:1px solid var(--borde);' +
    'border-radius:8px;padding:6px 12px;cursor:pointer">Quitar filtros</button></div>' +
    '<div class="card"><div class="tabla-scroll"><table id="tabla"><thead><tr>' +
    ["Fecha", "Nombre", "Tipo", "Km", "Tiempo", "Vel. media", "Desnivel"].map((t, i) =>
      '<th data-orden="' + ["fecha", "nombre", "tipo", "km", "tiempo", "vel", "desnivel"][i] +
      '"' + (["km", "tiempo", "vel", "desnivel"].indexOf(["fecha", "nombre", "tipo", "km", "tiempo", "vel", "desnivel"][i]) >= 0 ? ' class="num"' : "") +
      ">" + t + "</th>").join("") + "</tr></thead><tbody></tbody></table></div></div>";
  document.getElementById("vista").innerHTML = html;
  document.getElementById("busca").oninput = (e) => { estado.texto = e.target.value; rellenaActividades(); };
  document.getElementById("fTipo").onchange = (e) => { estado.tipo = e.target.value; rellenaActividades(); };
  document.getElementById("fAno").onchange = (e) => { estado.ano = e.target.value; rellenaActividades(); };
  document.getElementById("limpia").onclick = () => {
    estado.texto = ""; estado.tipo = ""; estado.ano = "";
    document.getElementById("busca").value = ""; document.getElementById("fTipo").value = "";
    document.getElementById("fAno").value = ""; rellenaActividades();
  };
  Array.from(document.querySelectorAll("#tabla th")).forEach(th => {
    th.onclick = () => {
      const o = th.getAttribute("data-orden");
      if (estado.orden === o) { estado.direccion = -estado.direccion; } else { estado.orden = o; estado.direccion = -1; }
      rellenaActividades();
    };
  });
  // Al entrar en Actividades se ordena por fecha, la mas reciente arriba (la lista de Segmentos ordena por
  // peso, y el estado es el mismo para las dos: hay que dejarlo puesto en cada vista).
  estado.orden = "fecha";
  estado.direccion = -1;
  rellenaActividades();
}

function actividadesFiltradas() {
  const texto = estado.texto.toLowerCase();
  let filas = D.actividades.filter(a =>
    (!estado.tipo || a.tipo === estado.tipo) &&
    (!estado.ano || fecha(a.fecha).slice(0, 4) === estado.ano) &&
    (!texto || (a.nombre || "").toLowerCase().indexOf(texto) >= 0));
  const o = estado.orden, d = estado.direccion;
  filas.sort((a, b) => {
    let x = a[o], y = b[o];
    if (o === "fecha") { x = a.fecha; y = b.fecha; }
    if (x === null || x === undefined) x = -Infinity;
    if (y === null || y === undefined) y = -Infinity;
    if (typeof x === "string") return d * x.localeCompare(y);
    return d * (x - y);
  });
  return filas;
}

function rellenaActividades() {
  const filas = actividadesFiltradas();
  const cuerpo = document.querySelector("#tabla tbody");
  if (!cuerpo) return;
  cuerpo.innerHTML = filas.map(a =>
    "<tr>" +
    '<td><a class="fila" href="#/actividad/' + a.id + '">' + fecha(a.fecha) + "</a></td>" +
    '<td><a class="fila" href="#/actividad/' + a.id + '">' + saleHTML(a.nombre) + "</a></td>" +
    '<td class="suave">' + saleHTML(a.tipo) + "</td>" +
    '<td class="num">' + num(a.km, 2) + "</td>" +
    '<td class="num">' + hms(a.tiempo) + "</td>" +
    '<td class="num">' + num(a.vel) + " km/h</td>" +
    '<td class="num">' + a.desnivel + " m</td></tr>").join("");
}

function migas(texto) { return '<div class="migas"><a href="#/actividades">Actividades</a> / ' + texto + "</div>"; }

function vistaActividad(id) {
  const a = D.actividades.filter(x => x.id === id)[0];
  if (!a) { document.getElementById("vista").innerHTML = '<h2>No encuentro esa salida</h2>'; ocultaMapa(); return; }
  const claves = (POR_ACTIVIDAD[id] || []).slice();
  const suyos = claves.map(k => {
    const seg = D.segmentos.filter(s => s.k === k)[0];
    const mio = (D.intentos[k] || []).filter(x => x[4] === id)[0];
    if (!seg || !mio) return null;
    const tiempos = (D.intentos[k] || []).map(x => x[1]).filter(x => x);
    tiempos.sort((p, q) => p - q);
    const puesto = tiempos.indexOf(mio[1]) + 1;
    return { seg: seg, mio: mio, puesto: puesto, total: tiempos.length };
  }).filter(x => x);
  suyos.sort((x, y) => y.mio[3] - x.mio[3]);

  let html = migas(saleHTML(a.nombre)) + "<h2>" + saleHTML(a.nombre) + "</h2>" +
    '<div class="sub">' + a.fecha + " &middot; " + saleHTML(a.tipo) + "</div>" +
    '<div class="kpis">' +
    '<div class="kpi"><b>' + num(a.km, 2) + " km</b><span>Distancia</span></div>" +
    '<div class="kpi"><b>' + hms(a.tiempo) + "</b><span>Tiempo</span></div>" +
    '<div class="kpi"><b>' + num(a.vel) + " km/h</b><span>Vel. media</span></div>" +
    '<div class="kpi"><b>' + a.desnivel + " m</b><span>Desnivel</span></div>" +
    '<div class="kpi"><b>' + suyos.length + "</b><span>Segmentos</span></div></div>";
  html += '<div id="hueco-mapa"></div>';
  html += '<div class="card"><h3>Altura</h3>' + perfilSVG(descodificaEnteros(a.ele), 900, 110) + "</div>";
  html += '<div class="card"><h3>Segmentos de esta salida</h3><div class="tabla-scroll"><table><thead><tr>' +
    '<th class="nosort">Segmento</th><th class="nosort num">Tiempo</th><th class="nosort num">Vel.</th>' +
    '<th class="nosort num">Dist.</th><th class="nosort num">Puesto</th></tr></thead><tbody>' +
    (suyos.length ? suyos.map(x =>
      '<tr><td><a class="fila" href="#/segmento/' + x.seg.k + '">' + saleHTML(x.seg.n) + "</a>" +
      (x.seg.ori === "strava" ? ' <span class="suave">(Strava)</span>' : "") + "</td>" +
      '<td class="num">' + hms(x.mio[1]) + "</td>" +
      '<td class="num">' + num(x.mio[2]) + " km/h</td>" +
      '<td class="num">' + km(x.mio[3]) + "</td>" +
      '<td class="num' + (x.puesto === 1 ? " verde" : "") + '">' + x.puesto + " de " + x.total + "</td></tr>").join("")
      : '<tr><td colspan="5" class="suave">Esta salida no pisa ningun segmento del catalogo.</td></tr>') +
    "</tbody></table></div></div>";
  document.getElementById("vista").innerHTML = html;
  pintaMapa([{ puntos: a.poly, color: "#4a9eff", grosor: 4 }]
    .concat(suyos.map(x => ({ puntos: x.seg.poly || a.poly, color: "#fc5200", grosor: 4, alfa: 0.95 }))
      .filter(x => x.puntos && x.puntos.length > 4)));
}

function vistaSegmentos() {
  ocultaMapa();
  let html = '<h2>Segmentos</h2>' +
    '<div class="sub">' + D.segmentos.length + " tramos con tiempos medidos. Los de las trazas se han " +
    'descubierto de tus propios GPX; los de Strava vienen del export y se conservan para no perder los nombres. ' +
    'Los marcados con * son de recorrido dudoso (los mismos pueblos por caminos distintos). ' +
    'Pincha en una cabecera para ordenar: <b>por tiempo</b>, en Mejor o Mediana; <b>por fecha</b>, en Ultima ' +
    'vez; tambien por distancia, pendiente, veces o peso (otra vez en la misma, al reves).</div>' +
    '<div class="filtros">' +
    '<input id="busca2" placeholder="Buscar segmento..." value="' + saleHTML(estado.texto) + '">' +
    '<select id="fMin"><option value="1">Al menos 1 vez</option><option value="3">3 veces o mas</option>' +
    '<option value="10">10 veces o mas</option><option value="50">50 veces o mas</option></select>' +
    '<select id="fOri"><option value="">Todas las fuentes</option><option value="trazas">Solo de mis trazas</option>' +
    '<option value="strava">Solo de Strava</option></select></div>' +
    '<div class="card"><div class="tabla-scroll"><table id="tabla2"><thead><tr>' +
    '<th data-orden="n">Segmento</th><th data-orden="d" class="num">Distancia</th>' +
    '<th data-orden="p" class="num">Pendiente</th><th data-orden="v" class="num">Veces</th>' +
    '<th data-orden="w" class="num">Peso</th>' +
    '<th data-orden="mej" class="num">Mejor</th><th data-orden="med" class="num">Mediana</th>' +
    '<th data-orden="f2">Ultima vez</th></tr></thead><tbody></tbody></table></div></div>';
  document.getElementById("vista").innerHTML = html;
  const ordenar = (o) => { estado.orden = o; rellenaSegmentos(); };
  document.getElementById("busca2").oninput = (e) => { estado.texto = e.target.value; rellenaSegmentos(); };
  document.getElementById("fMin").onchange = (e) => { estado.minimo = Number(e.target.value); rellenaSegmentos(); };
  document.getElementById("fOri").onchange = (e) => { estado.tipo = e.target.value; rellenaSegmentos(); };
  // Por defecto se ordena por peso (veces x km), que es el criterio del proyecto: asi salen primero las
  // carreteras largas que se repiten, no las callejuelas cortas del pueblo por el que se pasa siempre.
  estado.orden = "w";
  estado.direccion = -1;
  Array.from(document.querySelectorAll("#tabla2 th")).forEach(th => {
    th.onclick = () => {
      const o = th.getAttribute("data-orden");
      if (estado.orden === o) { estado.direccion = -estado.direccion; } else { estado.orden = o; estado.direccion = -1; }
      ordenar(o);
    };
  });
  rellenaSegmentos();
}

function segmentosFiltrados() {
  const texto = estado.texto.toLowerCase();
  let filas = D.segmentos.filter(s => s.v >= estado.minimo &&
    (!estado.tipo || s.ori === estado.tipo) &&
    (!texto || s.n.toLowerCase().indexOf(texto) >= 0));
  const o = estado.orden, d = estado.direccion;
  filas.sort((a, b) => {
    let x = a[o], y = b[o];
    if (x === null || x === undefined) x = -Infinity;
    if (y === null || y === undefined) y = -Infinity;
    if (typeof x === "string") return d * x.localeCompare(y);
    return d * (x - y);
  });
  return filas;
}

function rellenaSegmentos() {
  const filas = segmentosFiltrados();
  const cuerpo = document.querySelector("#tabla2 tbody");
  if (!cuerpo) return;
  cuerpo.innerHTML = filas.slice(0, 400).map(s =>
    "<tr>" +
    '<td><a class="fila" href="#/segmento/' + s.k + '">' + saleHTML(s.n) + "</a>" +
    (s.ori === "strava" ? ' <span class="suave">(Strava)</span>' : "") + "</td>" +
    '<td class="num">' + km(s.d) + "</td>" +
    '<td class="num">' + (s.p === null || s.p === undefined ? "-" : num(s.p) + " %") + "</td>" +
    '<td class="num">' + s.v + "</td>" +
    '<td class="num suave">' + (s.w || 0) + "</td>" +
    '<td class="num' + (s.v > 1 ? "" : " suave") + '">' + (s.mej ? hms(s.mej) : "-") + "</td>" +
    '<td class="num suave">' + (s.med ? hms(s.med) : "-") + "</td>" +
    '<td class="suave">' + (s.f2 || s.f1 || "") + "</td></tr>").join("") +
    (filas.length > 400 ? '<tr><td colspan="8" class="suave">Se ven los 400 primeros de ' + filas.length +
      ". Afina con los filtros.</td></tr>" : "");
}

// --- La tabla de tiempos de un segmento se puede ordenar pinchando en sus cabeceras -------------------------
// Estado de la tabla abierta: el segmento, sus intentos y por que columna esta ordenada.
let ficha = null;
let COLS_FICHA = [
  { k: "fecha", t: "Fecha", num: false }, { k: "tiempo", t: "Tiempo", num: true },
  { k: "vel", t: "Vel. media", num: true }, { k: "dist", t: "Distancia", num: true },
  { k: "puesto", t: "Puesto", num: true }, { k: "salida", t: "Salida", num: false },
];

function ordenFicha(col) {
  if (!ficha) return;
  if (ficha.orden === col) { ficha.dir = -ficha.dir; }
  else { ficha.orden = col; ficha.dir = (col === "fecha") ? -1 : 1; }   // la fecha, la mas reciente arriba
  fichaPinta();
}

// El valor por el que se ordena cada fila en cada columna (el tiempo manda sobre la velocidad, que se deduce
// de el; y la salida se ordena por su nombre, para que salgan juntas las del mismo sitio).
function valorFicha(f, col) {
  if (col === "fecha") return String(f.x[0] || "");
  if (col === "tiempo") return (f.x[1] === null || f.x[1] === undefined) ? Infinity : f.x[1];
  if (col === "vel") return (f.vel === null || f.vel === undefined) ? Infinity : f.vel;
  if (col === "dist") return (f.x[3] === null || f.x[3] === undefined) ? Infinity : f.x[3];
  if (col === "puesto") return f.posicion;
  const a = D.actividades.filter(y => y.id === f.x[4])[0];
  return a ? a.nombre : "";
}

function fichaPinta() {
  if (!ficha) return;
  const mejor = ficha.mejor, total = ficha.total;
  const flecha = (c) => (ficha.orden === c ? (ficha.dir > 0 ? " &#9650;" : " &#9660;") : "");
  document.getElementById("cabeza-ficha").innerHTML = "<tr>" + COLS_FICHA.map(c =>
    '<th class="' + (c.num ? "num" : "") + '" onclick="ordenFicha(\'' + c.k + '\')">' + c.t +
    flecha(c.k) + "</th>").join("") + "</tr>";
  const filas = ficha.filas.slice();
  filas.sort((a, b) => {
    const va = valorFicha(a, ficha.orden), vb = valorFicha(b, ficha.orden);
    if (typeof va === "string" || typeof vb === "string") {
      return String(va).localeCompare(String(vb)) * ficha.dir;
    }
    return (va - vb) * ficha.dir;
  });
  document.getElementById("cuerpo-ficha").innerHTML = filas.map(f => {
    const a = D.actividades.filter(y => y.id === f.x[4])[0];
    return "<tr>" +
      "<td>" + fecha(f.x[0]) + "</td>" +
      '<td class="num' + (f.x[1] === mejor ? " verde" : "") + '">' + hms(f.x[1]) + "</td>" +
      '<td class="num">' + num(f.vel) + " km/h</td>" +
      '<td class="num">' + km(f.x[3]) + "</td>" +
      '<td class="num">' + (f.x[1] === mejor ? '<span class="verde">1 de ' + total + "</span>"
                                             : f.posicion + " de " + total) + "</td>" +
      '<td>' + (a ? '<a class="enlace" href="#/actividad/' + a.id + '">' + saleHTML(a.nombre) + "</a>"
                   : '<span class="suave">salida ' + f.x[4] + "</span>") + "</td></tr>";
  }).join("");
}

function vistaSegmento(clave) {
  const s = D.segmentos.filter(x => x.k === clave)[0];
  if (!s) { document.getElementById("vista").innerHTML = '<h2>No encuentro ese segmento</h2>'; ocultaMapa(); return; }
  const tiempos = (D.intentos[clave] || []).slice().sort((a, b) => (a[1] || 0) - (b[1] || 0));
  const soloTiempos = tiempos.map(x => x[1]).filter(x => x);
  const mejor = soloTiempos.length ? Math.min.apply(null, soloTiempos) : null;
  const mediana = soloTiempos.length ? soloTiempos[Math.floor(soloTiempos.length / 2)] : null;
  const porAno = {};
  tiempos.forEach(x => {
    const a = (x[0] || "").slice(0, 4);
    if (!a || !x[1]) return;
    if (!porAno[a] || x[1] < porAno[a]) porAno[a] = x[1];
  });
  const cronologico = tiempos.slice().sort((a, b) => (a[0] || "").localeCompare(b[0] || ""));
  const filas = tiempos.map(x => ({ x: x, posicion: soloTiempos.indexOf(x[1]) + 1,
                                    vel: x[2] || (x[1] ? 3.6 * x[3] / x[1] : null) }));
  ficha = { s: s, filas: filas, mejor: mejor, total: tiempos.length, orden: "fecha", dir: -1 };

  let html = '<div class="migas"><a href="#/segmentos">Segmentos</a> / ' + saleHTML(s.n) + "</div>" +
    "<h2>" + saleHTML(s.n) + "</h2>" +
    '<div class="sub">' + (s.ori === "strava" ? "Segmento del export de Strava" : "Descubierto en tus trazas GPS") +
    (s.v > 1 ? " &middot; lo has hecho " + s.v + " veces" : "") + "</div>" +
    '<div class="kpis">' +
    '<div class="kpi"><b>' + km(s.d) + "</b><span>Distancia</span></div>" +
    '<div class="kpi"><b>' + (s.p === null || s.p === undefined ? "-" : num(s.p) + " %") + "</b><span>Pendiente</span></div>" +
    '<div class="kpi"><b class="verde">' + hms(mejor) + "</b><span>Tu mejor tiempo</span></div>" +
    '<div class="kpi"><b>' + hms(mediana) + "</b><span>Mediana</span></div>" +
    '<div class="kpi"><b>' + tiempos.length + "</b><span>Intentos</span></div></div>";
  html += '<div id="hueco-mapa"></div>';
  html += '<div class="dos"><div class="card"><h3>Evolucion de tus tiempos</h3>' +
    evolucionSVG(cronologico.filter(x => x[1]), 560, 150) + "</div>" +
    '<div class="card"><h3>Tu mejor tiempo de cada ano</h3><table><thead><tr><th class="nosort">Ano</th>' +
    '<th class="nosort num">Tiempo</th><th class="nosort num">Vel. media</th></tr></thead><tbody>' +
    Object.keys(porAno).sort().reverse().map(a =>
      "<tr><td>" + a + '</td><td class="num' + (porAno[a] === mejor ? " verde" : "") + '">' + hms(porAno[a]) +
      '</td><td class="num">' + num(3.6 * s.d / porAno[a]) + " km/h</td></tr>").join("") + "</tbody></table></div></div>";
  html += '<div class="card"><h3>Todos mis tiempos (' + tiempos.length + ")</h3>" +
    '<div class="sub">Pincha en una columna para ordenar por ella: tiempo, fecha, velocidad, distancia o ' +
    "puesto (otra vez en la misma columna, al reves).</div>" +
    '<div class="tabla-scroll"><table><thead id="cabeza-ficha"></thead><tbody id="cuerpo-ficha"></tbody>' +
    "</table></div></div>";
  document.getElementById("vista").innerHTML = html;
  fichaPinta();
  const trazas = [{ puntos: s.poly, color: "#fc5200", grosor: 5 }];
  if (!s.poly && s.la) {
    trazas.length = 0;
    pintaMapa([{ puntos: polilineaSimple([[s.la, s.lo], [s.lf, s.of]]), color: "#fc5200", grosor: 4 }]);
  } else {
    pintaMapa(trazas);
  }
}

function polilineaSimple(puntos) {
  let lat = 0, lon = 0, fuera = "";
  puntos.forEach(p => {
    const la = Math.round(p[0] * 1e5), lo = Math.round(p[1] * 1e5);
    fuera += varint(la - lat) + varint(lo - lon); lat = la; lon = lo;
  });
  return fuera;
}
function varint(v) {
  v = v < 0 ? ~(v << 1) : (v << 1);
  let fuera = "";
  while (v >= 0x20) { fuera += String.fromCharCode((0x20 | (v & 0x1f)) + 63); v >>= 5; }
  return fuera + String.fromCharCode(v + 63);
}

// ------------------------------------------------------------------ navegacion
function pinta() {
  const ruta = (location.hash || "#/actividades").replace(/^#\/?/, "");
  const trozos = ruta.split("/");
  const nav = document.getElementById("nav-" + (trozos[0] === "segmento" || trozos[0] === "segmentos" ? "seg" : "act"));
  Array.from(document.querySelectorAll("nav a")).forEach(a => a.className = "");
  if (nav) nav.className = "on";
  window.scrollTo(0, 0);
  if (trozos[0] === "actividad") return vistaActividad(Number(trozos[1]));
  if (trozos[0] === "segmento") return vistaSegmento(trozos[1]);
  if (trozos[0] === "segmentos") return vistaSegmentos();
  return vistaActividades();
}

window.addEventListener("hashchange", pinta);
document.addEventListener("DOMContentLoaded", () => {
  if (!location.hash) location.hash = "#/actividades";
  pinta();
});
</script>
</body>
</html>
"""


def html(datos_portal: dict) -> str:
    """La pagina entera, con los datos dentro."""
    salida = PLANTILLA.replace("__FECHA__", datos_portal["generado"])
    return salida.replace("__DATOS__", json.dumps(datos_portal, ensure_ascii=False, separators=(",", ":")))


def escribir(cn, destino: str = DESTINO) -> dict:
    """Escribe el portal en `destino` (por defecto `cuadro/strava/index.html`) y devuelve lo que ha salido."""
    datos_portal = datos(cn)
    texto = html(datos_portal)
    carpeta = os.path.dirname(destino)
    if carpeta and not os.path.isdir(carpeta):
        os.makedirs(carpeta, exist_ok=True)
    with open(destino, "w", encoding="utf-8") as fh:
        fh.write(texto)
    return {"destino": destino, "actividades": len(datos_portal["actividades"]),
            "segmentos": len(datos_portal["segmentos"]),
            "intentos": sum(len(v) for v in datos_portal["intentos"].values()),
            "mb": round(os.path.getsize(destino) / 1048576.0, 2)}
