"use strict";
/* ============================================================================
   Panel de entrenamiento: el comportamiento del portal
   Logica de la aplicacion local (cuadro/panel.html).

   Todo se calcula AQUI, en el navegador, con los datos que van incrustados en
   el propio fichero (#datos). No hay API ni se pide nada a la red, salvo el
   boton "Subir" del parte: manda el parte al servidor local del propio PC
   (`entrenador.cli servir`, 127.0.0.1) para que lo meta en la base sin bajar
   ficheros. Lo que se apunta a mano y no se sube (entrenamientos sueltos,
   peticiones y sesiones de gimnasio) queda en el almacen del navegador hasta
   que se descarga el fichero y se importa con `python -m entrenador.cli apuntes
   --importar`.
   ========================================================================= */

/* ---------- 0. Datos y utilidades ---------------------------------------- */

const DATOS = JSON.parse(document.getElementById("datos").textContent);
const PLAN = DATOS.plan || {};
const COMP = DATOS.competicion || {};
const APU = DATOS.apuntes || {};

const q = (id) => document.getElementById(id);
const $$ = (sel, raiz) => Array.prototype.slice.call((raiz || document).querySelectorAll(sel));

/* Donde vive la pequena API del servidor (subir el parte, gimnasio, evaluar...).
   - Si la pagina se sirve por HTTP, manda el mismo sitio que la pagina: asi funciona igual en
     `http://127.0.0.1:8181/` que detras de Caddy en `https://dalmacia/entrenador/`.
   - Si se abre como fichero (file://), el servidor del PC sigue estando en 127.0.0.1:8181. */
const API_BASE = (typeof location === "undefined" || !location.pathname
                  || location.protocol === "file:")
  ? "http://127.0.0.1:8181/"
  : location.pathname.replace(/[^/]*$/, "");
const urlApi = (ruta) => API_BASE + ruta;

function el(tag, attrs, hijos) {
  const n = document.createElement(tag);
  if (attrs) Object.keys(attrs).forEach((k) => {
    if (k === "clase") n.className = attrs[k];
    else if (k === "html") n.innerHTML = attrs[k];
    else if (k === "texto") n.textContent = attrs[k];
    else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), attrs[k]);
    else if (attrs[k] !== null && attrs[k] !== undefined) n.setAttribute(k, attrs[k]);
  });
  (hijos || []).forEach((h) => { if (h !== null && h !== undefined && h !== false) n.appendChild(typeof h === "string" ? document.createTextNode(h) : h); });
  return n;
}
const pintar = (id, contenido) => { const c = q(id); if (c) c.innerHTML = contenido; };
const esc = (s) => String(s === null || s === undefined ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const icono = (n, clase) => '<svg class="ico ' + (clase || "") + '" aria-hidden="true"><use href="#i-' + n + '"/></svg>';

const entero = (v) => (v === null || v === undefined || v === "" || isNaN(v) ? "—" : Math.round(Number(v)).toLocaleString("es-ES"));
const miles = (v, d) => (v === null || v === undefined || isNaN(v) ? "—" : Number(v).toLocaleString("es-ES", { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 }));
/* Decimales con coma, como se escribe en castellano. */
const dec = (v, d) => (v === null || v === undefined || isNaN(v) ? "—" : Number(v).toFixed(d === undefined ? 1 : d).replace(".", ","));
/* La sensacion del reloj viene en la escala de Garmin (0, 25, 50, 75, 100). En las tablas se lee de 0 a 5. */
const de0a5 = (v) => (v === null || v === undefined || v === "" || isNaN(v) ? "—"
  : (Math.round(Number(v) / 2) / 10).toFixed(1).replace(/\.0$/, "").replace(".", ","));
const sgn = (v, d) => (v === null || v === undefined || isNaN(v) ? "—" : (Number(v) > 0 ? "+" : "") + dec(v, d));

/* Marca y ritmo: "4:12,00" y "1:20,0" (el ritmo, por 100 m). */
function crono(seg) {
  if (seg === null || seg === undefined || isNaN(seg)) return "—";
  const s = Number(seg);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const rest = (r < 10 ? "0" : "") + r.toFixed(2).replace(".", ",");
  if (h) return h + ":" + (m < 10 ? "0" : "") + m + ":" + rest;
  return m + ":" + rest;
}
const cronoVerbal = (seg) => {
  if (seg === null || seg === undefined || isNaN(seg)) return "—";
  const m = Math.floor(Number(seg) / 60), r = Number(seg) % 60;
  return m + ":" + (r < 10 ? "0" : "") + r.toFixed(0);
};
/* Ritmo por 100 m, en minutos y segundos: 74,1 s/100 -> "1:14,1". */
const ritmo100 = (s) => {
  if (s === null || s === undefined || isNaN(s)) return "—";
  const n = Math.round(Number(s) * 10) / 10;
  const min = Math.floor(n / 60), seg = Math.round((n - min * 60) * 10) / 10;
  return min + ":" + (seg < 10 ? "0" : "") + dec(seg, 1);
};
const km = (m) => dec(Number(m) / 1000, 1) + " km";
/* La fecha y la hora en que se escribio un informe: '18/10/2026 a las 19:42'. */
const fechaHora = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso).replace("T", " ").slice(0, 16);
  const dos = (n) => String(n).padStart(2, "0");
  return dos(d.getDate()) + "/" + dos(d.getMonth() + 1) + "/" + d.getFullYear()
    + " a las " + dos(d.getHours()) + ":" + dos(d.getMinutes());
};

const fechaCorta = (iso) => {
  if (!iso) return "—";
  const p = String(iso).slice(0, 10).split("-");
  return p.length === 3 ? p[2] + "/" + p[1] + "/" + p[0] : String(iso);
};
const mesCorto = (clave) => {
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const p = String(clave).split("-");
  return p.length >= 2 ? MESES[Number(p[1]) - 1] + " " + p[0].slice(2) : clave;
};
const hoyISO = () => new Date().toISOString().slice(0, 10);
function diasHasta(iso) {
  if (!iso) return null;
  const a = new Date(hoyISO() + "T00:00:00"), b = new Date(String(iso).slice(0, 10) + "T00:00:00");
  return Math.round((b - a) / 86400000);
}
/* La temporada de natacion va de septiembre a agosto: 2026-05-26 es la 2025/26. */
function temporadaDe(iso) {
  if (!iso) return "—";
  const p = String(iso).slice(0, 10).split("-"), a = Number(p[0]), m = Number(p[1]);
  return m >= 9 ? a + "/" + String(a + 1).slice(2) : (a - 1) + "/" + String(a).slice(2);
}
const TEMPORADAS = Array.from(new Set((COMP.marcas || []).map((m) => temporadaDe(m.fecha)))).sort();
const ESTILOS = Array.from(new Set((COMP.marcas || []).map((m) => m.estilo))).sort();

/* ---------- 1. Lo que se apunta a mano (almacen del navegador) ------------ */

const CLAVES = {
  apuntes: "entrenador.apuntes.v2",
  peticiones: "entrenador.gimnasio.peticiones.v1",
  sesiones: "entrenador.gimnasio.sesiones.v1",
  partes: "entrenador.partes.v1",
  tema: "entrenador.tema.v1",
  vista: "entrenador.vista.v1",
};
/* Prefijo historico del panel: solo se usa para migrar una vez las claves viejas. */
const PREFIJO_ANTIGUO = "iregua";
const CLAVES_ANTIGUAS = {
  apuntes: PREFIJO_ANTIGUO + ".apuntes.v2",
  peticiones: PREFIJO_ANTIGUO + ".gimnasio.peticiones.v1",
  sesiones: PREFIJO_ANTIGUO + ".gimnasio.sesiones.v1",
  partes: PREFIJO_ANTIGUO + ".partes.v1",
  tema: PREFIJO_ANTIGUO + ".tema.v1",
  vista: PREFIJO_ANTIGUO + ".vista.v1",
};
const almacen = {
  leer(k, def) { try { const v = JSON.parse(localStorage.getItem(k)); return v === null || v === undefined ? def : v; } catch (e) { return def; } },
  guardar(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* modo privado */ } },
};
/* Migracion idempotente: si la clave vieja existe y la nueva no, se copia; despues se borra la vieja. */
function migrarClavesAntiguas() {
  try {
    Object.keys(CLAVES).forEach((k) => {
      const vieja = CLAVES_ANTIGUAS[k];
      if (!vieja) return;
      const valor = localStorage.getItem(vieja);
      if (valor === null) return;
      if (localStorage.getItem(CLAVES[k]) === null) localStorage.setItem(CLAVES[k], valor);
      localStorage.removeItem(vieja);
    });
  } catch (e) { /* modo privado o almacen lleno: no se migra nada */ }
}
migrarClavesAntiguas();
const leerApuntes = () => almacen.leer(CLAVES.apuntes, []);
const leerPeticiones = () => almacen.leer(CLAVES.peticiones, []);
const leerSesiones = () => almacen.leer(CLAVES.sesiones, []);
const leerPartes = () => almacen.leer(CLAVES.partes, []);

function ficheroApuntes() {
  return JSON.stringify({
    generado: new Date().toISOString(),
    origen: "cuadro/panel.html",
    entradas: leerApuntes(),
    gimnasio_peticiones: leerPeticiones(),
    gimnasio_sesiones: leerSesiones(),
    // El parte de cada sesion de piscina: los grupos con su material y su intensidad.
    partes_natacion: leerPartes(),
  }, null, 2);
}

/* ---------- 2. Tablas ---------------------------------------------------- */

/* columnas: [{t: "fecha", n: "Fecha", num: false, clase: ""}]; filas: [ [celda, ...] ]
   Si una columna trae `t` (su clave) y la opcion `orden` es {campo, dir}, su cabecera se puede pinchar para
   ordenar por ella (y sale una flecha en la que manda). El clic lo recoge quien pinte la tabla. */
function tablaHTML(columnas, filas, opciones) {
  const op = opciones || {};
  const th = columnas.map((c) => '<th class="' + (c.num ? "num " : "") + (c.clase || "") + '">' + esc(c.n) + "</th>").join("");
  const cuerpo = filas.map((f) => {
    const clases = (f.clase ? ' class="' + f.clase + '"' : "") + (f.attrs ? " " + f.attrs : "") + (f.pega ? ' data-pega="1"' : "");
    const celdas = (f.celdas || f).map((v, i) => '<td class="' + (columnas[i] && columnas[i].num ? "num" : "") + '">' + v + "</td>").join("");
    return "<tr" + clases + ">" + celdas + "</tr>";
  }).join("");
  const pie = op.pie ? "<tfoot><tr>" + op.pie.map((v, i) => '<td class="' + (columnas[i] && columnas[i].num ? "num" : "") + '">' + v + "</td>").join("") + "</tr></tfoot>" : "";
  const caption = op.titulo ? "<caption>" + esc(op.titulo) + "</caption>" : "";
  if (!filas.length) return '<div class="vacio"><strong>Sin datos</strong>' + esc(op.vacio || "No hay nada que ensenar aqui todavia.") + "</div>";
  return '<table class="tabla' + (op.compacta ? " tabla-compacta" : "") + '">' + caption + "<thead><tr>" + th + "</tr></thead><tbody>" + cuerpo + "</tbody>" + pie + "</table>";
}

/* ---------- 2b. Ordenar cualquier tabla pinchando en su cabecera -------------- */

/* Toda tabla de tiempos del portal se ordena pinchando en el titulo de una columna (la fecha, la marca, el
   ritmo...). El valor de cada celda se lee de su propio texto: fechas (d/m/a o a-m-d), tiempos y ritmos
   (m:ss.cc o m:ss,c, u h:mm:ss.cc), numeros (con coma o punto, aunque lleven unidad: "2.500 m") y texto. Un
   hueco o un guion va siempre al final, se ordene como se ordene. Las filas marcadas con `pega` viajan pegadas
   a la de arriba, para que un tramo no se separe de su marca. */

const RE_FECHA_R = /^(\d{4})-(\d{1,2})-(\d{1,2})$/;
const RE_FECHA = /^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})$/;
const RE_TIEMPO = /^(\d{1,3}):(\d{1,2}):(\d{2})(?:[.,](\d{1,2}))?$/;
const RE_MIN_SEG = /^(\d{1,3}):(\d{2})(?:[.,](\d{1,2}))?$/;
const RE_NUMERO = /^-?\d+(?:[.,]\d+)?(?![\d])/;

/* Lo que vale una celda para ordenar: {t: 0 fecha | 1 tiempo | 2 numero | 3 texto, v: valor}, o null si esta vacia. */
function valorCelda(td) {
  if (!td) return null;
  const propuesto = td.getAttribute ? td.getAttribute("data-v") : null;
  const bruto = String(propuesto === null || propuesto === "" ? (td.textContent || "") : propuesto).trim();
  if (!bruto || bruto === "—" || bruto === "-" || bruto === "·") return null;
  let m;
  if ((m = RE_FECHA_R.exec(bruto))) return { t: 0, v: Number(m[1]) * 10000 + Number(m[2]) * 100 + Number(m[3]) };
  if ((m = RE_FECHA.exec(bruto))) {
    const a = Number(m[3]) < 100 ? 2000 + Number(m[3]) : Number(m[3]);
    return { t: 0, v: a * 10000 + Number(m[2]) * 100 + Number(m[1]) };
  }
  if ((m = RE_TIEMPO.exec(bruto))) {
    return { t: 1, v: Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) + (m[4] ? Number("0." + m[4]) : 0) };
  }
  if ((m = RE_MIN_SEG.exec(bruto))) return { t: 1, v: Number(m[1]) * 60 + Number(m[2]) + (m[3] ? Number("0." + m[3]) : 0) };
  const suelto = RE_NUMERO.exec(bruto);
  if (suelto) return { t: 2, v: Number(suelto[0].replace(",", ".")) };
  return { t: 3, v: bruto.toLowerCase() };
}

function compararFilas(a, b, i, dir) {
  const x = valorCelda((a.cells || [])[i]), y = valorCelda((b.cells || [])[i]);
  if (!x && !y) return 0;
  if (!x) return 1;                        /* los huecos, al final siempre */
  if (!y) return -1;
  const r = x.t !== y.t ? x.t - y.t : (typeof x.v === "number" ? x.v - y.v : String(x.v).localeCompare(String(y.v)));
  return r * dir;
}

function cabecerasDe(tabla) {
  const h = tabla.tHead && tabla.tHead.rows && tabla.tHead.rows.length ? tabla.tHead.rows[tabla.tHead.rows.length - 1] : null;
  return h ? Array.prototype.slice.call(h.cells || []) : [];
}

/* Las filas se agrupan: una fila con `data-pega` va con la de arriba y no se ordena por su cuenta. */
function gruposDeFilas(tbody) {
  const grupos = [];
  Array.prototype.slice.call((tbody && tbody.rows) || []).forEach((f) => {
    const pega = !!(f.getAttribute && f.getAttribute("data-pega") !== null);
    if (pega && grupos.length) grupos[grupos.length - 1].push(f); else grupos.push([f]);
  });
  return grupos;
}

function tipoDeColumna(grupos, i) {
  let mejor = 5;
  grupos.forEach((g) => {
    const v = valorCelda((g[0].cells || [])[i]);
    if (v && v.t < mejor) mejor = v.t;
  });
  return mejor === 5 ? 3 : mejor;
}

/* Deja la tabla ordenada por la columna `i`. Si ya lo estaba, no toca nada (asi no se reordena en bucle). */
function ordenarTabla(tabla, i, dir) {
  const tbody = tabla.tBodies && tabla.tBodies[0];
  if (!tbody || !tbody.rows || tbody.rows.length < 2) return false;
  const grupos = gruposDeFilas(tbody);
  if (grupos.length < 2) return false;
  for (let k = 1; k < grupos.length; k++) {
    if (compararFilas(grupos[k - 1][0], grupos[k][0], i, dir) > 0) {
      grupos.sort((A, B) => compararFilas(A[0], B[0], i, dir));
      grupos.forEach((g) => g.forEach((f) => tbody.appendChild(f)));
      return true;
    }
  }
  return false;
}

function marcarCabecera(tabla, i, dir) {
  cabecerasDe(tabla).forEach((th, k) => {
    if (!th.getAttribute) return;
    if (th.getAttribute("data-base") === null) th.setAttribute("data-base", th.textContent || "");
    const pinta = k === i ? String(dir) : "";
    if (th.getAttribute("data-pinta") === pinta) return;
    th.textContent = (th.getAttribute("data-base") || "") + (k === i ? (dir < 0 ? " ▾" : " ▴") : "");
    th.setAttribute("data-pinta", pinta);
  });
}

/* El orden de cada tabla se recuerda por el id de su cajon, para volver a ponerlo cuando la tabla se repinta. */
const ORDENES = new Map();

function cajonDeTabla(tabla) {
  let n = tabla;
  while (n && n.getAttribute) {
    if (n.id) return n.id;
    if (String(n.tagName || "").toLowerCase() === "body") return null;
    n = n.parentNode;
  }
  return null;
}

function ordenarAlPinchar(th) {
  const tabla = th && th.closest ? th.closest("table") : null;
  if (!tabla) return;
  const i = cabecerasDe(tabla).indexOf(th);
  const tbody = tabla.tBodies && tabla.tBodies[0];
  if (i < 0 || !tbody || !tbody.rows || tbody.rows.length < 2) return;
  const cajon = cajonDeTabla(tabla);
  const antes = (cajon && ORDENES.get(cajon)) || null;
  /* Al pinchar una columna nueva: la fecha empieza por lo mas reciente y el resto por lo mas bajo (la mejor
     marca, el ritmo mas rapido). Al volver a pinchar la misma, se da la vuelta. */
  const dir = antes && antes.col === i ? -antes.dir : (tipoDeColumna(gruposDeFilas(tbody), i) === 0 ? -1 : 1);
  if (cajon) ORDENES.set(cajon, { col: i, dir: dir });
  ordenarTabla(tabla, i, dir);
  marcarCabecera(tabla, i, dir);
}

function montarOrdenTablas() {
  document.addEventListener("click", (ev) => {
    const th = ev.target && ev.target.closest ? ev.target.closest("th") : null;
    if (th) ordenarAlPinchar(th);
  });
  /* Cuando una tabla se repinta se pierde el orden: se vuelve a poner el que tuviera. */
  if (typeof MutationObserver !== "undefined" && document.body) {
    new MutationObserver(() => {
      if (!ORDENES.size) return;
      document.querySelectorAll("table").forEach((tb) => {
        const o = ORDENES.get(cajonDeTabla(tb));
        if (!o) return;
        ordenarTabla(tb, o.col, o.dir);
        marcarCabecera(tb, o.col, o.dir);
      });
    }).observe(document.body, { childList: true, subtree: true });
  }
}

/* ---------- 2c. Pinchar una fila para abrir esa sesion ---------------------- */

/* Las filas que llevan `data-sesion` (la lista de sesiones) se pinchan, o se activan con Enter, y abren esa
   sesion con su parte. Va delegado en `document`, como el orden: asi vale en CUALQUIER tabla del portal
   (resumen y entrenamientos), aguanta los repintados y no va apilando un oyente cada vez que se pinta una
   vista. Antes solo lo hacia la tabla de entrenamientos. */
function montarFilasPinchables() {
  /* Una fila pinchable o lleva al parte de esa sesion (`data-sesion`) o al sitio donde esta apuntado el
     entrenamiento (`data-apunte`, uno hecho sin reloj): las dos cosas se pinchan igual. Y los cuadros del
     calendario llevan el mismo atributo, asi que se pinchan con el mismo oyente. */
  const abrir = (nodo) => {
    if (nodo.dataset.sesion) abrirParte(nodo.dataset.sesion, nodo.dataset.fecha, true);
    else if (nodo.dataset.apunte) irA("apuntar");
  };
  const filaDe = (ev) => (ev.target && ev.target.closest
    ? ev.target.closest("tr[data-sesion], tr[data-apunte], .cal-celda[data-sesion], .cal-celda[data-apunte]") : null);
  document.addEventListener("click", (ev) => {
    const tr = filaDe(ev);
    if (tr) abrir(tr);
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const tr = filaDe(ev);
    if (!tr) return;
    ev.preventDefault();
    abrir(tr);
  });
}

function kpi(etiqueta, valor, pie, clase) {
  return '<div class="kpi ' + (clase || "") + '"><span class="k-etiqueta">' + esc(etiqueta) + '</span><span class="k-valor">' + valor + '</span><span class="k-pie">' + (pie || "") + "</span></div>";
}

/* ---------- 3. Graficos ------------------------------------------------- */

function graficoLinea(caja, puntos, opciones) {
  const op = opciones || {};
  const W = 720, H = op.alto || 250, m = { ar: 46, ab: 34, izq: 8, der: 8 };
  const valores = puntos.map((p) => p.y).concat(op.meta ? [op.meta] : []);
  if (!valores.length) { caja.innerHTML = '<div class="vacio">Sin datos suficientes.</div>'; return; }
  let min = Math.min.apply(null, valores), max = Math.max.apply(null, valores);
  const marjen = Math.max((max - min) * 0.16, 0.4);
  min -= marjen; max += marjen;
  const ancho = W - m.izq - m.der, alto = H - m.ar - m.ab;
  const px = (i) => m.izq + (puntos.length === 1 ? ancho / 2 : (i * ancho) / (puntos.length - 1));
  const py = (v) => m.ar + alto - ((v - min) / (max - min)) * alto;

  let rejilla = "", ejes = "";
  const nLineas = 4;
  for (let i = 0; i <= nLineas; i++) {
    const v = min + ((max - min) * i) / nLineas, y = py(v);
    rejilla += '<line class="rejilla-linea" x1="' + m.izq + '" y1="' + y.toFixed(1) + '" x2="' + (W - m.der) + '" y2="' + y.toFixed(1) + '"/>';
    ejes += '<text class="eje-texto" x="' + (W - m.der) + '" y="' + (y - 4).toFixed(1) + '" text-anchor="end">' + crono(v) + "</text>";
  }
  const camino = puntos.map((p, i) => (i ? "L" : "M") + px(i).toFixed(1) + " " + py(p.y).toFixed(1)).join(" ");
  const area = camino + " L" + px(puntos.length - 1).toFixed(1) + " " + (m.ar + alto) + " L" + px(0).toFixed(1) + " " + (m.ar + alto) + " Z";
  const metaLinea = op.meta ? '<line class="meta-linea" x1="' + m.izq + '" y1="' + py(op.meta).toFixed(1) + '" x2="' + (W - m.der) + '" y2="' + py(op.meta).toFixed(1) + '"/>'
    + '<text class="eje-texto" x="' + m.izq + '" y="' + (py(op.meta) - 5).toFixed(1) + '" fill="var(--meta)">objetivo ' + crono(op.meta) + "</text>" : "";
  const etiquetas = puntos.map((p, i) => (i % Math.ceil(puntos.length / 8) === 0 || i === puntos.length - 1
    ? '<text class="eje-texto" x="' + px(i).toFixed(1) + '" y="' + (H - 12) + '" text-anchor="middle">' + esc(p.x) + "</text>" : "")).join("");
  const circulos = puntos.map((p, i) => '<circle class="punto" cx="' + px(i).toFixed(1) + '" cy="' + py(p.y).toFixed(1) + '" r="4" data-i="' + i + '"/>').join("");

  caja.insertAdjacentHTML("beforeend", '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' + esc(op.titulo || "Evolucion") + '">'
    + rejilla + metaLinea + '<path class="area" d="' + area + '"/><path class="serie" d="' + camino + '"/>' + circulos + ejes + etiquetas + "</svg>");

  const globo = op.globo;
  caja.querySelectorAll(".punto").forEach((c) => {
    c.addEventListener("mouseenter", (ev) => {
      const i = Number(c.dataset.i), r = c.getBoundingClientRect(), cr = caja.getBoundingClientRect();
      if (!globo) return;
      globo.textContent = puntos[i].globo || (puntos[i].x + ": " + crono(puntos[i].y));
      globo.style.left = (r.left - cr.left + r.width / 2) + "px";
      globo.style.top = (r.top - cr.top) + "px";
      globo.classList.add("visible");
    });
    c.addEventListener("mouseleave", () => { if (globo) globo.classList.remove("visible"); });
  });
}

function barrasHTML(datos, opciones) {
  const op = opciones || {};
  if (!datos.length) return '<div class="vacio">Sin datos.</div>';
  const max = Math.max.apply(null, datos.map((d) => d.v)) || 1;
  return '<div class="barras">' + datos.map((d) => {
    const h = Math.max((d.v / max) * 100, 1.5);
    return '<div class="b"><em>' + esc(d.titulo || (entero(d.v) + (op.unidad || ""))) + '</em><i style="height:' + h.toFixed(1) + '%"></i><span>' + esc(d.x) + "</span></div>";
  }).join("") + "</div>";
}

/* ---------- 4. Navegacion, pestanas y tema ------------------------------ */

const VISTAS = {
  resumen: { titulo: "Resumen", migas: "Panel", sub: "Todo lo que hay en la base: piscina, competicion, gimnasio y bici.", icono: "resumen" },
  competicion: { titulo: "Competicion", migas: "Panel · Federacion", sub: "Las marcas oficiales de la RFEN: filtros, comparativa por temporadas y evolucion.", icono: "copa" },
  plan: { titulo: "Plan", migas: "Panel · Planificacion", sub: "Los dos objetivos, las semanas en curso y las reglas de carga. Los dias de entrenador no se tocan.", icono: "plan" },
  entrenos: { titulo: "Entrenamientos", migas: "Panel · Piscina", sub: "Las sesiones que vienen del reloj, los tramos que repito y las piezas de fondo. Pincha una sesion de piscina y se abre su parte.", icono: "entrenos" },
  gimnasio: { titulo: "Gimnasio", migas: "Panel · Gimnasio", sub: "Pedir trabajo de gimnasio, registrar lo que hago y ver el historial.", icono: "gym" },
  apuntar: { titulo: "Apuntar", migas: "Panel · Registro", sub: "Lo que el reloj no registra: material, sensaciones y notas. Se descarga y se importa.", icono: "apuntar" },
  volumen: { titulo: "Volumen", migas: "Panel · Analisis", sub: "Metros nadados mes a mes y resumen por ano.", icono: "volumen" },
  bici: { titulo: "Bicicleta", migas: "Panel · Bici", sub: "Resumen de las salidas y los tramos; el detalle esta en el portal de bici.", icono: "bici" },
  pruebas: { titulo: "Pruebas", migas: "Panel · Analisis", sub: "Los bloques que marcas como prueba (tu 1.500, un 400, la serie de 100, tu escalera) y como van con los anos.", icono: "volumen" },
  reglas: { titulo: "Reglas", migas: "Panel · Entrenador", sub: "Lo que te propone, de donde sale cada numero, que decides tu y si la regla acierta. Aqui se cierra el bucle.", icono: "plan" },
};

function mostrarVista(nombre, silencioso) {
  if (!VISTAS[nombre]) nombre = "resumen";
  $$(".vista").forEach((s) => s.classList.toggle("activa", s.id === "vista-" + nombre));
  $$(".nav a[data-vista]").forEach((a) => {
    if (a.dataset.vista === nombre) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  const v = VISTAS[nombre];
  pintar("migas", esc(v.migas));
  pintar("tituloVista", esc(v.titulo));
  pintar("subVista", esc(v.sub));
  document.title = v.titulo + " · " + ((DATOS && DATOS.titulo_pagina) || "Entrenamiento");
  almacen.guardar(CLAVES.vista, nombre);
  if (!silencioso) { window.scrollTo({ top: 0, behavior: "smooth" }); }
}

function montarPestanas() {
  $$("[role=tab]").forEach((b) => {
    b.addEventListener("click", () => {
      const grupo = b.closest(".pestanas");
      $$("[role=tab]", grupo).forEach((o) => o.setAttribute("aria-selected", String(o === b)));
      $$(".panel-pestana", q("vista-" + grupo.dataset.vista || document)).forEach(() => {});
      const panel = b.dataset.p;
      const vista = b.closest("section.vista");
      $$(".panel-pestana", vista).forEach((p) => p.classList.toggle("activa", p.id === panel));
    });
  });
}

function montarTema() {
  const guardado = almacen.leer(CLAVES.tema, "oscuro");
  const aplicar = (t) => {
    document.documentElement.setAttribute("data-tema", t);
    pintar("btTemaTxt", t === "claro" ? "Modo oscuro" : "Modo claro");
    q("btTema").querySelector("use").setAttribute("href", t === "claro" ? "#i-luna" : "#i-sol");
    almacen.guardar(CLAVES.tema, t);
  };
  aplicar(guardado);
  q("btTema").addEventListener("click", () => aplicar(document.documentElement.getAttribute("data-tema") === "claro" ? "oscuro" : "claro"));
  q("btImprimir").addEventListener("click", () => window.print());
}

/* ---------- 5. Resumen --------------------------------------------------- */

function pintarCabeceraDatos() {
  const k = DATOS.kpis || {};
  pintar("selloDatos", "Datos locales · actualizado " + fechaCorta(String(DATOS.generado || "").slice(0, 10))
    + " · " + entero(k.sesiones) + " sesiones de piscina desde " + fechaCorta(k.primera));
  const ob = PLAN.objetivo_b, oa = PLAN.objetivo_a;
  const fichas = [["b", ob], ["a", oa]].filter((x) => x[1]).map((x) => {
    const o = x[1], d = diasHasta(o.fecha);
    return '<button class="cuenta ' + x[0] + '" type="button" data-vista="plan">'
      + "<b>" + esc(o.nombre) + "</b>"
      + '<span class="dias">' + (d === null ? "—" : (d >= 0 ? d : "hecho")) + (d !== null && d >= 0 ? " d" : "") + "</span>"
      + "<small>" + esc(o.que) + "</small></button>";
  }).join("");
  pintar("cuentaAtras", fichas);
  $$("#cuentaAtras .cuenta").forEach((b) => b.addEventListener("click", () => irA("plan")));
  pintar("cResumen", entero(k["60dias"]) + " en 60 d");
  pintar("cCompeticion", entero((COMP.resumen || {}).validas));
  pintar("cPlan", ((PLAN.semanas || []).length || "") + " sem");
  pintar("cEntrenos", entero(k.sesiones));
}

function pintarKpis() {
  const k = DATOS.kpis || {};
  // Lo que llevamos nadado en los ultimos 7 dias, con lo que llevabamos en los 7 de antes: es el dato que el
  // atleta mira de verdad (el total de siempre no dice si esta entrenando ahora). Sale del resumen del entrenador.
  const v = DATOS.valoracion || {}, fu = v.fuentes || {};
  const sem = fu.semana || null, prev = fu.semana_previa || null;
  const dif7 = sem && prev ? sem.metros - prev.metros : null;
  pintar("kpis", [
    sem ? kpi("Nadado en los ultimos 7 dias", entero(sem.metros) + " m",
              sem.dias + (sem.dias === 1 ? " dia en el agua" : " dias en el agua")
              + (dif7 === null ? "" : " · " + (dif7 >= 0 ? "+" : "\u2212") + entero(Math.abs(dif7))
                 + " m que los 7 anteriores"),
              dif7 === null ? "" : (dif7 >= 0 ? "ok" : "no")) : "",
    kpi("Metros nadados", entero(k.metros_totales), "en " + entero(k.sesiones) + " sesiones"),
    kpi("Ultima sesion", fechaCorta(k.ultima), "hace " + (diasHasta(k.ultima) === null ? "—" : -diasHasta(k.ultima) + " dias")),
  ]);
}

function pintarPreparacion() {
  const objs = [PLAN.objetivo_b, PLAN.objetivo_a].filter(Boolean);
  pintar("preparacion", objs.map((o) => {
    const piscina = o.prueba && o.prueba.piscina_m ? String(o.prueba.piscina_m) : "";
    const marcas = (COMP.marcas || []).filter((m) => m.estilo === o.prueba.estilo && m.distancia_m === o.prueba.distancia_m
      && esMarca(m) && (!piscina || String(m.piscina_m) === piscina)).slice().sort((a, b) => (a.fecha < b.fecha ? 1 : -1));
    const mejores = marcas.slice().sort((a, b) => a.segundos - b.segundos);
    const mejor = mejores[0];
    const ultimas = marcas.slice(0, 3);
    const base = ultimas.length ? ultimas.reduce((s, m) => s + m.segundos, 0) / ultimas.length : null;
    const objetivo = o.marca_objetivo_s;
    const dias = diasHasta(o.fecha);
    const dif = base === null ? null : base - objetivo;
    const clase = dif === null ? "" : (dif <= 0 ? "ok" : (dif <= 12 ? "up" : "no"));
    const pct = base === null || !mejor ? 0 : Math.min(100, Math.max(0, ((mejor.segundos - base) / Math.max(mejor.segundos - objetivo, 1)) * 100));
    const piscinaTxt = piscina ? "piscina de " + piscina + " m" : "todas las piscinas";
    return '<article class="objetivo">'
      + '<div class="o-cabeza"><div class="o-titulo"><b>' + esc(o.nombre) + '</b><span class="o-fecha">'
      + esc(fechaCorta(o.fecha)) + (dias !== null && dias >= 0 ? " · quedan " + dias + " dias" : "") + "</span></div>"
      + '<div class="o-que">' + esc(o.que) + "</div></div>"
      + '<div class="o-cuerpo">'
      + '<div class="o-linea"><span>Marca objetivo</span><b>' + crono(objetivo) + "</b></div>"
      + '<div class="o-linea"><span>Tu mejor oficial (' + esc(piscinaTxt) + ")</span><b>" + (mejor ? crono(mejor.segundos) + " · " + fechaCorta(mejor.fecha) : "—") + "</b></div>"
      + '<div class="o-linea"><span>Ultimas ' + ultimas.length + " marcas oficiales</span><b>" + (base === null ? "—" : crono(base)) + "</b></div>"
      + '<div class="barra ' + clase + '"><i style="width:' + pct.toFixed(0) + '%"></i></div>'
      + '<div class="barra-cifras"><span>objetivo ' + crono(objetivo) + "</span><span>mejor " + (mejor ? crono(mejor.segundos) : "—") + "</span></div>"
      + '<div class="proyeccion ' + clase + '"><span class="p-cifra">' + (dif === null ? "—" : sgn(dif, 1) + " s") + "</span>"
      + '<span class="p-txt">' + (dif === null ? "No hay marcas de esta prueba para proyectar."
        : (dif <= 0 ? "Con las ultimas marcas estarias <b>dentro</b> del objetivo."
          : "Con las ultimas marcas <b>faltan " + dec(dif, 1) + " s</b> para el objetivo (" + ritmo100(base / (o.prueba.distancia_m / 100)) + " de ritmo)."))
      + "</span></div>"
      + '<p class="ayuda" style="margin:0">Referencia, no pronostico: es lo que sale de las ultimas marcas oficiales de '
      + esc(piscinaTxt) + ", y en " + esc(o.rango) + " esta lo razonable." + "</p>"
      + "</div></article>";
  }).join(""));
}

/* ---------- 2b. El calendario de piscina: el mes de verdad ---------------- */

/* El mes que se esta mirando ("2026-10"). Empieza en el mes de hoy y se mueve con los botones. */
let CAL_MES = null;
const DIAS_SEMANA = ["L", "M", "X", "J", "V", "S", "D"];
const MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
  "agosto", "septiembre", "octubre", "noviembre", "diciembre"];

const calISO = (anio, mes, dia) => anio + "-" + String(mes).padStart(2, "0") + "-" + String(dia).padStart(2, "0");
function calFechaHoy() {
  const h = new Date();
  return calISO(h.getFullYear(), h.getMonth() + 1, h.getDate());
}

function pintarCalendario(mesPedido) {
  const cal = DATOS.calendario || [];
  const caja = q("calendario");
  if (!caja || !cal.length) return;
  if (mesPedido) CAL_MES = String(mesPedido).slice(0, 7);   /* se puede pedir un mes concreto (pruebas) */
  const indice = {};
  cal.forEach((d) => { indice[d.fecha] = d; });
  const hoy = calFechaHoy();
  const primera = DATOS.kpis && DATOS.kpis.primera ? String(DATOS.kpis.primera).slice(0, 10) : cal[0].fecha;
  if (!CAL_MES) CAL_MES = hoy.slice(0, 7);
  if (CAL_MES < primera.slice(0, 7)) CAL_MES = primera.slice(0, 7);
  if (CAL_MES > hoy.slice(0, 7)) CAL_MES = hoy.slice(0, 7);
  const anio = Number(CAL_MES.slice(0, 4));
  const mes = Number(CAL_MES.slice(5, 7));
  pintar("calMes", MESES_LARGOS[mes - 1] + " " + anio);

  /* Cabecera de dias de la semana. La semana empieza en lunes, que es como entrena. */
  pintar("calCabecera", DIAS_SEMANA.map((d) => "<span>" + d + "</span>").join(""));

  const desplazamiento = (new Date(anio, mes - 1, 1).getDay() + 6) % 7;
  const diasDelMes = new Date(anio, mes, 0).getDate();
  let maxMes = 1, nadados = 0, metrosMes = 0, pasados = 0;
  const conAgua = [];
  cal.forEach((d) => {
    if (d.fecha.slice(0, 7) !== CAL_MES) return;
    if (d.fecha <= hoy) pasados += 1;
    if (d.metros > 0) {
      nadados += 1; metrosMes += d.metros; conAgua.push(d.metros);
      maxMes = Math.max(maxMes, d.metros);
    }
  });

  const celdas = [];
  for (let i = 0; i < desplazamiento; i += 1) celdas.push('<div class="cal-celda fuera"></div>');
  for (let dia = 1; dia <= diasDelMes; dia += 1) {
    const fecha = calISO(anio, mes, dia);
    const d = indice[fecha] || { metros: 0, sesiones: 0 };
    const futuro = fecha > hoy;
    let clase = "cal-celda", fondo = "", texto = "";
    if (d.metros > 0) {
      clase += " nadado";
      const p = Math.min(1, d.metros / maxMes);
      fondo = ' style="background:color-mix(in srgb, var(--acento) ' + Math.round(10 + 60 * p) + '%, var(--sup-2))"';
      texto = entero(d.metros);
    } else if (futuro) {
      clase += " futuro";
    } else if (fecha < primera) {
      clase += " sin-datos";
    } else {
      clase += " seco";                       /* ese dia no hubo piscina: se marca aparte, como pidio el atleta */
    }
    if (d.apunte) clase += " apunte";
    if (fecha === hoy) clase += " hoy";
    let pinchar = "", papel = "";
    if (d.actividad_id !== null && d.actividad_id !== undefined) {
      pinchar = ' data-sesion="' + d.actividad_id + '" data-fecha="' + fecha + '"';
      papel = ' role="button" tabindex="0"';
    } else if (d.apunte_id !== null && d.apunte_id !== undefined) {
      pinchar = ' data-apunte="' + d.apunte_id + '" data-fecha="' + fecha + '"';
      papel = ' role="button" tabindex="0"';
    }
    const asunto = d.metros > 0
      ? entero(d.metros) + " m" + (d.sesiones > 1 ? " en " + d.sesiones + " sesiones" : "")
        + (d.apunte ? " (apuntado a mano)" : "")
      : (futuro ? "por venir" : (fecha < primera ? "sin datos" : "no nade"));
    celdas.push('<div class="' + clase + '"' + fondo + pinchar + papel + ' title="' + fechaCorta(fecha)
      + ": " + asunto + '"><span class="cal-num">' + dia + '</span><span class="cal-m">' + texto + "</span></div>");
  }
  while (celdas.length % 7 !== 0) celdas.push('<div class="cal-celda fuera"></div>');
  caja.innerHTML = celdas.join("");

  /* La leyenda distingue las tres cosas que se ven: nadado, no nadado, y por venir/sin datos. */
  pintar("calLeyenda", '<span class="cal-ej nadado"></span>nadado (mas color, mas metros)'
    + '<span class="cal-ej seco"></span>no nade'
    + '<span class="cal-ej hueso"></span>por venir o sin datos');
  const orden = conAgua.slice().sort((a, b) => a - b);
  const mediana = orden.length
    ? (orden.length % 2 ? orden[(orden.length - 1) / 2] : (orden[orden.length / 2 - 1] + orden[orden.length / 2]) / 2)
    : 0;
  pintar("calPista", "en " + MESES_LARGOS[mes - 1] + ": " + nadados + " dias en el agua de " + pasados + " pasados"
    + " · " + km(metrosMes) + (mediana ? " · mediana " + entero(mediana) + " m" : "")
    + " · cada cuadro es un dia");
}

function montarCalendario() {
  const mover = (delta) => {
    if (!CAL_MES) CAL_MES = calFechaHoy().slice(0, 7);
    const anio = Number(CAL_MES.slice(0, 4));
    const mes = Number(CAL_MES.slice(5, 7));
    const d = new Date(anio, mes - 1 + delta, 1);
    CAL_MES = calISO(d.getFullYear(), d.getMonth() + 1, 1).slice(0, 7);
    pintarCalendario();
  };
  const ant = q("calAnt"), sig = q("calSig"), hoy = q("calHoy");
  if (ant) ant.addEventListener("click", () => mover(-1));
  if (sig) sig.addEventListener("click", () => mover(1));
  if (hoy) hoy.addEventListener("click", () => { CAL_MES = calFechaHoy().slice(0, 7); pintarCalendario(); });
  pintarCalendario();
}

/* ---------- pruebas de medicion ---------------------------------------- */

/* El bloque que el atleta destaca para compararse consigo mismo con los anos: su 1.500, un 400, la serie de 100,
   la escalera que hace a menudo. La elige el, aqui, en la cabecera del bloque; viaja con el parte hasta la base
   y el motor solo la guarda. Despues se compara con las de su clase: mismo nombre y mismos metros. */
function selectorPrueba(g) {
  const lista = (PPA() && PPA().pruebas) || [];
  const sel = el("select", { clase: "mini-sel", title: "Marcar este bloque como prueba de medicion" });
  sel.appendChild(el("option", { value: "", texto: "prueba" }));
  const nombres = lista.slice();
  if (g.prueba && nombres.indexOf(g.prueba) < 0) nombres.push(g.prueba);
  nombres.forEach((n) => {
    const o = el("option", { value: n, texto: n });
    if (g.prueba === n) o.selected = true;
    sel.appendChild(o);
  });
  sel.addEventListener("change", () => {
    g.prueba = sel.value || null;
    sel.title = g.prueba ? "Este bloque es una prueba de medicion: " + g.prueba
      : "Marcar este bloque como prueba de medicion";
  });
  return sel;
}

/* Una prueba con su historial: lo de siempre arriba (la ultima, la mejor y el ano a ano) y debajo todas, que es
   lo que responde a "como voy respecto a otras epocas". */
function tarjetaPrueba(p) {
  const filas = (p.todas || []).slice().reverse().map((e) => [
    esc(e.fecha || ""),
    entero(e.metros) + " m",
    (e.n_reps && e.n_reps > 1)
      ? "<span class='gris'>" + entero(e.n_reps) + "x" + entero(e.rep_m || (e.metros / e.n_reps)) + "</span>"
      : "seguido",
    e.tiempo_s ? crono(e.tiempo_s) : "\u2014",
    e.ritmo_100 ? ritmo100(e.ritmo_100) : "\u2014",
    e.actividad_id ? "<span class='gris mini-txt'>sesion " + esc(e.actividad_id) + "</span>" : "",
  ]);
  const porAno = (p.por_ano || []).map((a) => [esc(a.ano), entero(a.veces), ritmo100(a.mejor_ritmo), ritmo100(a.media_ritmo)]);
  const delta = (p.delta_ultima_s === null || p.delta_ultima_s === undefined) ? ""
    : " <b>" + (p.delta_ultima_s <= 0 ? "mejor" : "peor") + " " + dec(Math.abs(p.delta_ultima_s), 1)
      + " s/100 que la anterior</b>";
  return "<div class='tarjeta'>"
    + "<header><h3>" + esc(p.nombre) + (p.metros ? " \u00b7 " + entero(p.metros) + " m" : "") + "</h3>"
    + "<span class='pista'>" + p.veces + (p.veces === 1 ? " vez" : " veces") + "</span></header>"
    + "<div class='tarjeta-cuerpo'><p class='ayuda'>"
    + (p.mejor ? "Tu mejor " + esc(p.etiqueta_medida || "") + ": " + valorDeMedida(p.mejor, p.medida)
        + " el " + esc(p.mejor.fecha || "") + ". " : "")
    + (p.ultima ? "La ultima: " + (p.ultima.ritmo_100 ? ritmo100(p.ultima.ritmo_100) : "\u2014")
        + " el " + esc(p.ultima.fecha || "") + "." : "")
    + delta + "</p>"
    + tablaHTML([{ n: "Fecha" }, { n: "Metros" }, { n: "Forma" }, { n: "Tiempo", num: true },
                 { n: "Ritmo /100", num: true }, { n: "" }], filas,
                { compacta: true, vacio: "Sin pruebas todavia." })
    + (porAno.length > 1
      ? "<div class='etiqueta-mini'>Por ano</div>"
        + tablaHTML([{ n: "Ano" }, { n: "Veces", num: true }, { n: "Mejor", num: true }, { n: "Media", num: true }],
                    porAno, { compacta: true })
      : "")
    + "</div></div>";
}

/* Los tres mejores de cada prueba, en la pagina resumen: el atleta lo pidio asi, con su tiempo y su fecha, y cada
   prueba con lo que manda en ella (el 1.500 por tiempo total, la escalera y la serie de 100 cada 1:30 por ritmo,
   los 30 minutos por metros). Es lo que contesta de un vistazo "como voy respecto a otras epocas". */
function valorDeMedida(m, medida) {
  if (!m || m.valor === null || m.valor === undefined || m.valor === "") return "\u2014";
  if (medida === "tiempo") return crono(m.valor);
  if (medida === "metros") return entero(m.valor) + " m";
  return ritmo100(m.valor);
}

function pintarResumenPruebas() {
  const lista = (PPA() && PPA().pruebas_resumen) || [];
  if (!lista.length) return;
  const filas = lista.map((p) => {
    const celdas = [0, 1, 2].map((i) => {
      const m = (p.mejores || [])[i];
      if (!m) return '<span class="gris">\u2014</span>';
      return "<b>" + valorDeMedida(m, p.medida) + "</b> <span class='gris mini-txt'>" + esc(m.fecha || "") + "</span>";
    });
    return ["<b>" + esc(p.nombre) + "</b> <span class='gris mini-txt'>" + esc(p.etiqueta_medida || "") + "</span>"].concat(celdas);
  });
  pintar("resPruebas", tablaHTML([{ n: "Prueba" }, { n: "1\u00ba" }, { n: "2\u00ba" }, { n: "3\u00ba" }], filas,
    { compacta: true, vacio: "Todavia sin marcar." }));
}

function pintarPruebas() {
  const lista = (PPA() && PPA().pruebas_historial) || [];
  if (!lista.length) {
    pintar("pruebasCaja", "<div class='tarjeta'><header><h3>Pruebas de medicion</h3>"
      + "<span class='pista'>para compararte contigo mismo</span></header><div class='tarjeta-cuerpo'>"
      + "<p class='ayuda'>Todavia no hay ninguna prueba marcada. Abre un entrenamiento y, en la cabecera de un"
      + " bloque, elige lo que es (tu 1.500, un 400, la serie de 100, tu escalera); despues guarda el parte y subelo."
      + " Aqui aparecera con su historial, para comparar como vas con los anos.</p></div></div>");
    return;
  }
  pintar("pruebasCaja", lista.map(tarjetaPrueba).join(""));
}

function pintarVolumen() {
  const v = DATOS.volumen || {}, k = DATOS.kpis || {};
  const anos = (v.por_ano || []).map((a) => ({ x: a.clave, v: a.metros, titulo: entero(a.metros) + " m · " + a.sesiones + " sesiones" }));
  pintar("volumenAnual", barrasHTML(anos, { unidad: " m" }));
  const meses = (v.por_mes || []).slice(-12).map((m) => ({ x: mesCorto(m.clave), v: m.metros, titulo: entero(m.metros) + " m · " + m.sesiones + " sesiones" }));
  pintar("volumenMensual", barrasHTML(meses, { unidad: " m" }));

  pintarCalendario();

  pintar("volTabla", tablaHTML(
    [{ n: "Ano" }, { n: "Sesiones", num: true }, { n: "Metros", num: true }, { n: "Horas", num: true }, { n: "Media por sesion", num: true }],
    (v.por_ano || []).slice().reverse().map((a) => [
      "<span class='ahora'>" + esc(a.clave) + "</span>", entero(a.sesiones), entero(a.metros), dec(a.horas, 1), entero(a.metros / Math.max(a.sesiones, 1)) + " m",
    ]), { compacta: true }));

  pintar("recientes", tablaHTML(
    [{ n: "Fecha" }, { n: "Sesion" }, { n: "Metros", num: true }, { n: "Tiempo", num: true }, { n: "Ritmo", num: true }, { n: "Piscina", num: true }, { n: "Pulso", num: true }, { n: "Sensacion /5", num: true }],
    (DATOS.sesiones_recientes || []).map((s) => {
      const id = s.actividad_id === null || s.actividad_id === undefined ? null : String(s.actividad_id);
      /* Un entrenamiento apuntado a mano (sin reloj) tambien se pincha: lleva a "Apuntar mis entrenamientos". */
      const ap = !id && s.apunte_id !== null && s.apunte_id !== undefined ? String(s.apunte_id) : null;
      return {
        clase: id || ap ? "pinchable" : "",
        attrs: id ? ' data-sesion="' + esc(id) + '" data-fecha="' + esc(s.fecha) + '" tabindex="0"'
               : (ap ? ' data-apunte="' + esc(ap) + '" data-fecha="' + esc(s.fecha) + '" tabindex="0"' : ""),
        celdas: [
          "<span class='ahora'>" + esc(fechaCorta(s.fecha)) + "</span> <span class='gris mini-txt'>" + esc(s.hora) + "</span>",
          esc(s.nombre || "—"), entero(s.dist_m), cronoVerbal(s.min ? s.min * 60 : null), ritmo100(s.ritmo_100),
          (s.piscina_m ? entero(s.piscina_m) + " m" : "—"), entero(s.fc_media), de0a5(s.sensacion),
        ],
      };
    }), { compacta: true, vacio: "No hay sesiones recientes." }));
}

/* ---------- 6. Competicion ---------------------------------------------- */

/* Que fila es marca suya y que fila es tramo de otra prueba lo decide el proyecto mirando la JORNADA entera
   (entrenador/competicion.clasificar_sesion: la jornada = fecha + hora + sede, y el estilo de la prueba mas
   larga manda) y llega ya masticado en `m.tipo`:
     - "prueba": es su marca (una prueba individual, o el tramo de un relevo nadado a tope).
     - "pase":   es un tramo de la prueba mas larga de esa misma jornada (el 1000 de un 3000, el 400 de la escalera del dia).
     - "rara":   dato mal puesto de origen (25 m, ritmos imposibles): no se enseña como marca. */
function esPase(m) { return (m.tipo || "prueba") === "pase"; }
function esMarca(m) { return (m.tipo || "prueba") === "prueba"; }
function esRara(m) { return m.tipo === "rara"; }

function pintarCompeticion() {
  const c = COMP.resumen || {}, obj = COMP.objetivo_s100;
  pintar("compKpis", [
    kpi("Marcas oficiales", entero(c.validas), c.total - c.validas + " descartadas en origen", "a"),
    kpi("Pruebas completas", entero(c.completas), "las que cuentan como marca"),
    kpi("Pases (tramos)", entero(c.pases), "de otra prueba" + (c.raras ? " · " + entero(c.raras) + " raras" : "")),
    kpi("Competiciones", entero(c.competiciones), "de " + fechaCorta(c.desde) + " a " + fechaCorta(c.hasta)),
    kpi("Objetivo del 400", ritmo100(obj), "bajar de 5:00 en 25 m"),
  ]);
  pintar("compResumen", entero(c.validas) + " marcas validas de " + entero(c.total) + " · "
    + entero(c.completas) + " pruebas completas y " + entero(c.pases) + " pases (tramos dentro de otra prueba)");

  /* --- pestana 1: mejores marcas --- */
  const h400 = COMP.h400 || [];
  pintar("h400Pista", h400.length + " pruebas completas (los pases quedan fuera)");
  const mejor400 = h400.slice().sort((a, b) => a.segundos - b.segundos)[0];
  pintar("objetivo400", mejor400
    ? '<div class="fila entre"><span>Mejor oficial: <b class="num">' + crono(mejor400.segundos) + "</b> (" + esc(mejor400.lugar) + ", " + fechaCorta(mejor400.fecha) + ", " + mejor400.piscina_m + " m)</span>"
      + '<span class="etiqueta ' + (mejor400.ritmo_100 <= obj ? "ok" : "up") + '">' + ritmo100(mejor400.ritmo_100) + " · objetivo " + ritmo100(obj) + "</span></div>"
    : "");
  pintar("h400Tabla", tablaHTML(
    [{ n: "Fecha" }, { n: "Sede" }, { n: "Piscina", num: true }, { n: "Marca", num: true }, { n: "Ritmo /100", num: true }, { n: "Con el objetivo", num: true }],
    h400.slice().sort((a, b) => (a.fecha < b.fecha ? 1 : -1)).map((m) => {
      const dif = m.segundos - 300;
      const clase = dif <= 0 ? "ok" : (dif <= 6 ? "up" : "no");
      return {
        clase: (m.segundos <= 300.5 ? "destaca" : ""),
        celdas: ["<span class='ahora'>" + esc(fechaCorta(m.fecha)) + "</span>", esc(m.lugar), entero(m.piscina_m),
          "<span class='tiempo'>" + crono(m.segundos) + "</span>", ritmo100(m.ritmo_100),
          '<span class="etiqueta ' + clase + '">' + sgn(dif, 1) + " s</span>"],
      };
    }), { compacta: true }));

  const h3000 = COMP.h3000 || [];
  pintar("h3000Tabla", tablaHTML(
    [{ n: "Fecha" }, { n: "Sede" }, { n: "Piscina", num: true }, { n: "Marca", num: true }, { n: "Ritmo /100", num: true }],
    h3000.map((m) => ["<span class='ahora'>" + esc(fechaCorta(m.fecha)) + "</span>", esc(m.lugar), entero(m.piscina_m),
      "<span class='tiempo'>" + crono(m.segundos) + "</span>", ritmo100(m.ritmo_100)]), { compacta: true }));

  const selPiscina = q("fMejoresPiscina");
  const pintarMejores = () => {
    const fil = selPiscina.value;
    const mm = (COMP.mejores || []).filter((m) => !fil || String(m.piscina_m) === fil);
    pintar("mejoresTabla", tablaHTML(
      [{ n: "Prueba" }, { n: "Piscina", num: true }, { n: "Marca", num: true }, { n: "Ritmo", num: true }, { n: "Fecha" }, { n: "Sede" }],
      mm.map((m) => [esc(m.estilo + " " + m.distancia_m), entero(m.piscina_m), "<span class='tiempo'>" + crono(m.segundos) + "</span>",
        ritmo100(m.ritmo_100), "<span class='ahora'>" + esc(fechaCorta(m.fecha)) + "</span>", esc(m.lugar)]),
      { compacta: true }));
    pintar("mejoresPista", mm.length + " pruebas · solo completas");
  };
  selPiscina.addEventListener("change", pintarMejores);
  pintarMejores();

  /* --- pestana 2: comparador por temporadas --- */
  /* Solo las pruebas que el atleta tiene de verdad: las filas de pases (un 1000 dentro de un 3000, por
     ejemplo) traen distancias que no son suyas y no pintan nada en el selector. */
  const pruebas = Array.from(new Set((COMP.marcas || []).filter(esMarca).map((m) => m.estilo + "|" + m.distancia_m)))
    .map((p) => { const [e, d] = p.split("|"); return { valor: p, etiqueta: e + " " + d }; });
  q("cmpPrueba").innerHTML = pruebas.map((p) => '<option value="' + esc(p.valor) + '">' + esc(p.etiqueta) + "</option>").join("");
  q("cmpPrueba").value = "libre|400";
  q("cmpDesde").innerHTML = '<option value="">Todas las temporadas</option>' + TEMPORADAS.map((t) => '<option value="' + t + '">' + t + "</option>").join("");
  q("cmpDesde").value = TEMPORADAS.length > 7 ? TEMPORADAS[TEMPORADAS.length - 7] : "";

  const comparar = () => {
    const [estilo, dist] = q("cmpPrueba").value.split("|");
    const piscina = q("cmpPiscina").value;
    const dePrueba = (COMP.marcas || []).filter((m) => m.estilo === estilo && String(m.distancia_m) === dist);
    const pases = dePrueba.filter(esPase).length;
    const todas = dePrueba.filter(esMarca);
    const piscinas = Array.from(new Set(todas.map((m) => m.piscina_m)));
    const recargaSelect = q("cmpPiscina").dataset.prueba !== q("cmpPrueba").value;
    if (recargaSelect) {
      const conteo = {};
      todas.forEach((m) => { conteo[m.piscina_m] = (conteo[m.piscina_m] || 0) + 1; });
      const conMas = String(Object.keys(conteo).sort((a, b) => conteo[b] - conteo[a])[0] || "");
      q("cmpPiscina").innerHTML = piscinas.map((p) => '<option value="' + p + '">' + p + " m (" + conteo[p] + " marcas)</option>").join("")
        + '<option value="">25 y 50 m juntas</option>';
      q("cmpPiscina").value = conMas;
      q("cmpPiscina").dataset.prueba = q("cmpPrueba").value;
    }
    const mezcla = !q("cmpPiscina").value && piscinas.length > 1;
    const marcas = todas.filter((m) => !q("cmpPiscina").value || String(m.piscina_m) === q("cmpPiscina").value);

    const porTemp = {};
    marcas.forEach((m) => { const t = temporadaDe(m.fecha); (porTemp[t] = porTemp[t] || []).push(m); });
    const desde = q("cmpDesde").value;
    const temporadas = Object.keys(porTemp).sort().filter((t) => !desde || t >= desde);
    const filas = temporadas.map((t) => {
      const g = porTemp[t], mejor = g.slice().sort((a, b) => a.segundos - b.segundos)[0];
      return { temporada: t, n: g.length, mejor: mejor, segundos: mejor.segundos, ritmo: mejor.ritmo_100 };
    });
    const media = {};
    temporadas.forEach((t) => { const g = porTemp[t]; media[t] = g.reduce((s, m) => s + m.segundos, 0) / g.length; });

    const mejorGlobal = filas.slice().sort((a, b) => a.segundos - b.segundos)[0];
    const objetivo = (PLAN.objetivo_b && PLAN.objetivo_b.prueba.estilo === estilo && String(PLAN.objetivo_b.prueba.distancia_m) === dist)
      ? PLAN.objetivo_b.marca_objetivo_s : null;

    pintar("cmpTabla", tablaHTML(
      [{ n: "Temporada" }, { n: "Marcas", num: true }, { n: "Mejor marca", num: true }, { n: "Ritmo /100", num: true }, { n: "Media", num: true }, { n: "Con la anterior", num: true }, { n: "Con la mejor" , num: true}],
      filas.map((f, i) => {
        const ant = i ? filas[i - 1].segundos : null;
        const difAnt = ant === null ? null : f.segundos - ant;
        const difMejor = f.segundos - (mejorGlobal ? mejorGlobal.segundos : f.segundos);
        const etAnt = difAnt === null ? "<span class='gris'>primera</span>"
          : '<span class="etiqueta ' + (difAnt <= 0 ? "ok" : "no") + '">' + sgn(difAnt, 2) + " s</span>";
        const etMej = difMejor === 0 ? '<span class="etiqueta a">la mejor</span>'
          : '<span class="etiqueta">' + sgn(difMejor, 2) + " s</span>";
        return {
          clase: (objetivo !== null && f.segundos <= objetivo ? "destaca" : ""),
          celdas: ["<span class='ahora'>" + esc(f.temporada) + "</span>", entero(f.n),
            "<span class='tiempo'>" + crono(f.segundos) + "</span>", ritmo100(f.ritmo),
            "<span class='gris'>" + crono(media[f.temporada]) + "</span>", etAnt, etMej],
        };
      }), { compacta: true, vacio: "No hay marcas de esa prueba con esos filtros." }));

    pintar("cmpMejores", tablaHTML(
      [{ n: "Temporada" }, { n: "Mejor marca", num: true }, { n: "Fecha" }, { n: "Sede" }],
      filas.slice().reverse().map((f) => ["<span class='ahora'>" + esc(f.temporada) + "</span>",
        "<span class='tiempo'>" + crono(f.segundos) + "</span>", esc(fechaCorta(f.mejor.fecha)), esc(f.mejor.lugar)]), { compacta: true }));
    pintar("cmpPista", filas.length + " temporadas · " + (q("cmpPiscina").value ? q("cmpPiscina").value + " m" : "25 y 50 juntas"));

    /* tendencia: recta de minimos cuadrados sobre la mejor marca de cada temporada */
    let lectura = "Con menos de cinco temporadas no se calcula la tendencia: no se inventa una recta con dos puntos.";
    let clase = "";
    if (filas.length >= 5) {
      const xs = filas.map((f) => Number(f.temporada.slice(0, 4))), ys = filas.map((f) => f.segundos);
      const n = xs.length, sx = xs.reduce((a, b) => a + b, 0), sy = ys.reduce((a, b) => a + b, 0);
      const sxy = xs.reduce((a, x, i) => a + x * ys[i], 0), sxx = xs.reduce((a, x) => a + x * x, 0);
      const pend = (n * sxy - sx * sy) / (n * sxx - sx * sx);
      const porCien = (pend / (sy / n)) * 100;
      clase = Math.abs(porCien) < 0.3 ? "" : (porCien < 0 ? "ok" : "no");
      lectura = "Pendiente de <b>" + sgn(porCien, 2) + " % por temporada</b> (" + sgn(pend, 2) + " s en la marca). "
        + (Math.abs(porCien) < 0.3 ? "Practicamente plano: estas donde estabas." : (porCien < 0 ? "Vas a mejor." : "Vas perdiendo ritmo."))
        + " Sale de " + n + " temporadas con " + marcas.length + " marcas; con tan pocos puntos es una orientacion, no una prediccion.";
    }
    pintar("cmpLectura", lectura + (mezcla ? "<br><br><span class='ambar'>Ojo: estas juntando piscina de 25 y de 50 m, que no son la misma prueba.</span>" : "")
      + (pases ? "<br><br><span class='gris'>Fuera quedan " + pases + " pases (tramos dentro de otra prueba): no son marcas de esta distancia.</span>" : ""));

    const caja = q("cmpGrafico");
    $$("svg", caja).forEach((s) => s.remove());
    graficoLinea(caja, filas.map((f) => ({
      x: f.temporada.slice(2), y: f.segundos, globo: f.temporada + " · " + crono(f.segundos) + " (" + ritmo100(f.ritmo) + ")",
    })), { meta: objetivo, globo: q("cmpGlobo"), titulo: "Evolucion por temporadas", alto: 240 });
  };
  q("cmpPrueba").addEventListener("change", comparar);
  q("cmpPiscina").addEventListener("change", comparar);
  q("cmpDesde").addEventListener("change", comparar);
  comparar();

  /* --- pestana 3: todas las marcas --- */
  const rellenar = (sel, valores, etiquetaTodas, etiquetar) => {
    sel.innerHTML = '<option value="">' + etiquetaTodas + "</option>" + valores.map((v) => '<option value="' + esc(v) + '">' + esc(etiquetar ? etiquetar(v) : v) + "</option>").join("");
  };
  rellenar(q("fEstilo"), ESTILOS, "Todos los estilos");
  /* Distancias donde tiene alguna marca propia: el 1.000 y el 2.000 no salen, porque en su historial solo
     aparecen como tramos de un 3.000 (son pases, no pruebas que haya nadado). */
  rellenar(q("fDistancia"), Array.from(new Set((COMP.marcas || []).filter(esMarca).map((m) => m.distancia_m))).sort((a, b) => a - b), "Todas las distancias", (v) => v + " m");
  rellenar(q("fPiscina"), Array.from(new Set((COMP.marcas || []).map((m) => m.piscina_m))).sort((a, b) => a - b), "Todas las piscinas", (v) => v + " m");
  rellenar(q("fTemporada"), TEMPORADAS, "Todas las temporadas");

  /* Las pruebas que ese dia tuvieron tramos se pueden desplegar para verlos debajo, pegados a su marca. El
     orden de la tabla lo pone el titular de la columna (montarOrdenTablas), como en todas las del portal. */
  const abiertas = new Set();
  const TODAS = COMP.marcas || [];
  const pasesDe = (id) => TODAS.filter((p) => esPase(p) && p.madre === id);

  const etiquetaTipo = (m) => (esPase(m)
    ? " <span class='etiqueta up' title='" + esc(m.motivo || "") + "'>pase</span>"
    : (esRara(m) ? " <span class='etiqueta down' title='" + esc(m.motivo || "") + "'>rara</span>" : ""));
  const botonPases = (id, n, abierta) => '<button type="button" class="bt-pases" data-pases="' + id + '" title="'
    + (abierta ? "Ocultar los tramos de esta prueba" : "Ver los tramos de esta prueba") + '">'
    + (abierta ? "▾" : "▸") + " " + n + " pase" + (n === 1 ? "" : "s") + "</button>";

  const filtrar = () => {
    const e = q("fEstilo").value, d = q("fDistancia").value, p = q("fPiscina").value;
    const t = q("fTemporada").value, lug = q("fLugar").value.trim().toLowerCase();
    const tp = q("fTipo").value;
    let mm = TODAS.filter((m) => (!e || m.estilo === e) && (!d || String(m.distancia_m) === d)
      && (!p || String(m.piscina_m) === p) && (!t || temporadaDe(m.fecha) === t)
      && (!lug || (m.lugar || "").toLowerCase().indexOf(lug) >= 0));
    if (tp === "completas") mm = mm.filter(esMarca);
    else if (tp === "pases") mm = mm.filter(esPase);
    else if (tp === "raras") mm = mm.filter(esRara);
    pintar("fCuenta", mm.length + " de " + TODAS.length + " filas del historial"
      + (tp === "completas" ? " · solo marcas suyas" : (tp === "pases" ? " · solo tramos" : (tp === "raras" ? " · solo datos raros" : ""))));
    pintar("fAviso", (p === "" && new Set(mm.map((m) => m.piscina_m)).size > 1)
      ? "Estas mezclando piscinas de 25 y 50 m: no son la misma prueba." : "");
    return mm.slice().sort((a, b) => (a.fecha < b.fecha ? 1 : -1));
  };

  const pintarTabla = () => {
    const mm = filtrar();
    const filas = [];
    mm.slice(0, 400).forEach((m) => {
      const pases = esMarca(m) ? pasesDe(m.id) : [];
      const abierta = pases.length > 0 && abiertas.has(m.id);
      filas.push({
        clase: "fila-marca",
        celdas: ["<span class='ahora'>" + esc(fechaCorta(m.fecha)) + "</span>", esc(m.lugar),
          esc(m.estilo + " " + m.distancia_m) + etiquetaTipo(m)
            + (pases.length ? " " + botonPases(m.id, pases.length, abierta) : ""),
          entero(m.piscina_m), "<span class='tiempo'>" + crono(m.segundos) + "</span>",
          ritmo100(m.ritmo_100), "<span class='gris'>" + esc(temporadaDe(m.fecha)) + "</span>"],
      });
      if (abierta) {
        pases.slice().sort((a, b) => a.distancia_m - b.distancia_m).forEach((p) => filas.push({
          clase: "fila-pase", pega: true, attrs: 'title="' + esc(p.motivo || "") + '"',
          celdas: ["<span class='ahora'>" + esc(fechaCorta(p.fecha)) + "</span>", esc(p.lugar),
            "<span class='pase-rotulo'>↳ tramo de " + p.distancia_m + " m</span>", entero(p.piscina_m),
            "<span class='tiempo tenue'>" + crono(p.segundos) + "</span>",
            "<span class='gris'>" + ritmo100(p.ritmo_100) + "</span>",
            "<span class='gris'>" + esc(temporadaDe(p.fecha)) + "</span>"],
        }));
      }
    });
    pintar("fTabla", tablaHTML(
      [{ n: "Fecha" }, { n: "Sede" }, { n: "Prueba" }, { n: "Piscina", num: true }, { n: "Marca", num: true },
        { n: "Ritmo /100", num: true }, { n: "Temporada" }],
      filas, { compacta: true, vacio: "Ninguna marca con esos filtros." }));
  };

  ["fEstilo", "fDistancia", "fPiscina", "fTemporada", "fTipo"].forEach((id) => q(id).addEventListener("change", pintarTabla));
  q("fLugar").addEventListener("input", pintarTabla);
  q("fTabla").addEventListener("click", (ev) => {
    const boton = ev.target && ev.target.closest ? ev.target.closest("[data-pases]") : null;
    if (!boton) return;
    const id = Number(boton.getAttribute("data-pases"));
    if (abiertas.has(id)) abiertas.delete(id); else abiertas.add(id);
    pintarTabla();
  });
  q("fLimpiar").addEventListener("click", () => {
    ["fEstilo", "fDistancia", "fPiscina", "fTemporada", "fLugar"].forEach((id) => { q(id).value = ""; });
    q("fTipo").value = "completas";
    abiertas.clear();
    pintarTabla();
  });
  pintarTabla();
}

/* ---------- 6b. Mis pases ----------------------------------------------- */

/* Los tramos de la misma prueba, competicion a competicion: el primer 100 de cada 400, el 200 de cada 3.000...
   Cada fila de pase trae `madre` (el id de la prueba de la que es tramo), que calcula el proyecto
   (entrenador/competicion.clasificar_sesion): aqui solo se agrupa, se compara y se enseña. */
function pintarPases() {
  const marcas = COMP.marcas || [];
  const porId = {};
  marcas.forEach((m) => { porId[m.id] = m; });

  const grupos = {};   // "libre|400" -> {estilo, distancia_m, dias: [{madre, pases}]}
  marcas.forEach((p) => {
    if (!esPase(p)) return;
    const madre = porId[p.madre];
    if (!madre) return;
    const k = madre.estilo + "|" + madre.distancia_m;
    const g = grupos[k] || (grupos[k] = { estilo: madre.estilo, distancia_m: madre.distancia_m, dias: [] });
    let dia = g.dias.filter((d) => d.madre.id === madre.id)[0];
    if (!dia) { dia = { madre: madre, pases: [] }; g.dias.push(dia); }
    dia.pases.push(p);
  });
  const claves = Object.keys(grupos).sort((a, b) => grupos[b].dias.length - grupos[a].dias.length
    || grupos[b].distancia_m - grupos[a].distancia_m);

  if (!claves.length) {
    q("psPrueba").innerHTML = ""; q("psPaso").innerHTML = ""; q("psPiscina").innerHTML = "";
    pintar("psPista", ""); pintar("psTabla", ""); pintar("psMejor", ""); pintar("psMejorPista", "");
    pintar("psLectura", "Todavia no hay tramos apuntados en el historial.");
    return;
  }
  q("psPrueba").innerHTML = claves.map((k) => '<option value="' + esc(k) + '">'
    + esc(grupos[k].estilo + " " + grupos[k].distancia_m + " m") + " · " + grupos[k].dias.length + " competiciones</option>").join("");

  const pintarGrupo = () => {
    const g = grupos[q("psPrueba").value] || grupos[claves[0]];
    const distancias = Array.from(new Set(g.dias.reduce((a, d) => a.concat(d.pases.map((p) => p.distancia_m)), [])))
      .sort((a, b) => a - b);
    const piscinas = Array.from(new Set(g.dias.map((d) => d.madre.piscina_m))).sort((a, b) => a - b);

    const pasoPrevio = q("psPaso").value, piscinaPrevia = q("psPiscina").value;
    q("psPaso").innerHTML = distancias.map((d) => '<option value="' + d + '">' + d + " m</option>").join("");
    if (distancias.map(String).indexOf(pasoPrevio) >= 0) q("psPaso").value = pasoPrevio;
    q("psPiscina").innerHTML = '<option value="">25 y 50 m</option>'
      + piscinas.map((p) => '<option value="' + p + '">' + p + " m</option>").join("");
    if (piscinas.map(String).indexOf(piscinaPrevia) >= 0) q("psPiscina").value = piscinaPrevia;
    const tramo = Number(q("psPaso").value) || distancias[0];
    const pisc = q("psPiscina").value;

    let dias = g.dias.slice().sort((a, b) => (a.madre.fecha < b.madre.fecha ? 1 : -1));
    if (pisc) dias = dias.filter((d) => String(d.madre.piscina_m) === pisc);
    const tramos = g.dias.reduce((a, d) => a + d.pases.length, 0);
    const mezcla = !pisc && piscinas.length > 1;
    pintar("psPista", g.estilo + " " + g.distancia_m + " m · " + dias.length + " competiciones · " + tramos + " tramos"
      + (mezcla ? " · 25 y 50 m juntas" : ""));

    /* la tabla: una fila por competicion, una columna por tramo. Asi se comparan los tramos entre si. */
    const columnas = [{ n: "Fecha" }, { n: "Sede" }, { n: "Piscina", num: true }, { n: "Marca", num: true },
      { n: "Ritmo /100", num: true }];
    distancias.forEach((d) => columnas.push({ n: "Tramo " + d + " m", num: true }));
    pintar("psTabla", tablaHTML(columnas, dias.map((d) => ({
      celdas: ["<span class='ahora'>" + esc(fechaCorta(d.madre.fecha)) + "</span>", esc(d.madre.lugar),
        entero(d.madre.piscina_m), "<span class='tiempo'>" + crono(d.madre.segundos) + "</span>",
        ritmo100(d.madre.ritmo_100)].concat(distancias.map((dist) => {
          const p = d.pases.filter((x) => x.distancia_m === dist)[0];
          return p ? "<span class='tiempo tenue'>" + crono(p.segundos) + "</span> <span class='gris mini-txt'>"
            + ritmo100(p.ritmo_100) + " · " + sgn(p.ritmo_100 - d.madre.ritmo_100, 1) + "</span>"
            : "<span class='gris'>—</span>";
        })),
    })), { compacta: true, vacio: "No hay tramos de esa prueba con esa piscina." }));

    /* el grafico: el tramo elegido, competicion a competicion */
    const puntos = dias.slice().reverse().map((d) => {
      const p = d.pases.filter((x) => x.distancia_m === tramo)[0];
      return p ? { x: fechaCorta(d.madre.fecha).slice(0, 5), y: p.ritmo_100,
        globo: fechaCorta(d.madre.fecha) + " · " + (d.madre.lugar || "") + " · tramo " + tramo + " m " + crono(p.segundos)
          + " (" + ritmo100(p.ritmo_100) + ")" } : null;
    }).filter(Boolean);
    const caja = q("psGrafico");
    $$("svg", caja).forEach((s) => s.remove());
    if (puntos.length) {
      graficoLinea(caja, puntos, { globo: q("psGlobo"),
        titulo: "Tramo de " + tramo + " m del " + g.estilo + " " + g.distancia_m + " m", alto: 240 });
    }

    /* la lectura: cuanto cuesta cada tramo frente al ritmo de la prueba entera */
    const trozos = distancias.map((dist) => {
      const pp = [];
      dias.forEach((d) => { const p = d.pases.filter((x) => x.distancia_m === dist)[0]; if (p) pp.push({ p: p, m: d.madre }); });
      if (!pp.length) return null;
      return { dist: dist, n: pp.length,
        media: pp.reduce((a, x) => a + x.p.ritmo_100, 0) / pp.length,
        dif: pp.reduce((a, x) => a + x.p.ritmo_100, 0) / pp.length - pp.reduce((a, x) => a + x.m.ritmo_100, 0) / pp.length,
        mejor: pp.slice().sort((a, b) => a.p.ritmo_100 - b.p.ritmo_100)[0] };
    }).filter(Boolean);
    pintar("psLectura", trozos.length
      ? (trozos.map((x) => "El tramo de <b>" + x.dist + " m</b> te sale a <b>" + ritmo100(x.media) + "</b> de media"
        + " (" + sgn(x.dif, 1) + " s/100 frente al ritmo de la prueba, en " + x.n + " competiciones)"
        + ", y el mejor fue el " + fechaCorta(x.mejor.p.fecha) + " a " + ritmo100(x.mejor.p.ritmo_100) + ".").join("<br>")
        + "<br><br>Un tramo mas rapido que el ritmo de la prueba es lo normal: se sale a por la marca y luego se paga."
        + (mezcla ? "<br><br><span class='ambar'>Ojo: estas juntando piscina de 25 y de 50 m, que no son la misma prueba.</span>" : ""))
      : "Con esa piscina no queda ningun tramo que comparar.");

    /* el desglose de su mejor dia: la prueba y cada tramo, con lo que se aparta del ritmo final */
    const mejor = dias.slice().sort((a, b) => a.madre.segundos - b.madre.segundos)[0];
    if (!mejor) { pintar("psMejor", ""); pintar("psMejorPista", ""); return; }
    pintar("psMejorPista", fechaCorta(mejor.madre.fecha) + " · " + (mejor.madre.lugar || ""));
    const filas = [{ celdas: ["<b>Prueba entera</b>", "<span class='tiempo'>" + crono(mejor.madre.segundos) + "</span>",
      ritmo100(mejor.madre.ritmo_100), "<span class='gris'>—</span>"] }];
    mejor.pases.slice().sort((a, b) => a.distancia_m - b.distancia_m).forEach((p) => filas.push({
      celdas: ["Tramo de " + p.distancia_m + " m", "<span class='tiempo tenue'>" + crono(p.segundos) + "</span>",
        ritmo100(p.ritmo_100), "<span class='etiqueta'>" + sgn(p.ritmo_100 - mejor.madre.ritmo_100, 1) + " s/100</span>"],
    }));
    pintar("psMejor", tablaHTML([{ n: "Parcial" }, { n: "Tiempo", num: true }, { n: "Ritmo /100", num: true },
      { n: "Con la prueba", num: true }], filas, { compacta: true }));
  };

  q("psPrueba").addEventListener("change", pintarGrupo);
  q("psPaso").addEventListener("change", pintarGrupo);
  q("psPiscina").addEventListener("change", pintarGrupo);
  pintarGrupo();
}

/* ---------- 7. Plan ----------------------------------------------------- */

function pintarPlan() {
  pintar("objetivosPlan", [PLAN.objetivo_b, PLAN.objetivo_a].filter(Boolean).map((o) => {
    const d = diasHasta(o.fecha);
    return '<article class="objetivo"><div class="o-cabeza"><div class="o-titulo"><b>' + esc(o.nombre) + '</b>'
      + '<span class="o-fecha">' + esc(fechaCorta(o.fecha)) + (d !== null ? " · " + d + " dias" : "") + "</span></div>"
      + '<div class="o-que">' + esc(o.que) + '</div></div><div class="o-cuerpo">'
      + "<dl class='datos'><div><dt>Marca objetivo</dt><dd>" + crono(o.marca_objetivo_s) + "</dd></div>"
      + "<div><dt>Ritmo objetivo</dt><dd>" + ritmo100(o.ritmo_objetivo_100) + "</dd></div>"
      + "<div><dt>Prueba</dt><dd>" + esc(o.prueba.estilo) + " " + o.prueba.distancia_m + " m · " + o.prueba.piscina_m + " m</dd></div>"
      + "<div><dt>Rango razonable</dt><dd>" + esc(o.rango) + "</dd></div></dl>"
      + '<p class="ayuda" style="margin:0">' + esc(o.nota) + "</p></div></article>";
  }).join(""));

  pintar("planEntrenador", '<div class="tarjeta-cuerpo"><strong>Con el entrenador</strong><p class="destacado" style="margin:4px 0 0">'
    + esc(PLAN.entrenador) + "</p></div>");

  // El plan recalculado va aparte y manda sobre el escrito: se rehace con cada entrenamiento que entra.
  const vivo = {};
  ((PLAN.vivo || {}).semanas || []).forEach((v) => { vivo[v.clave] = v; });
  pintar("planSemanas", (PLAN.semanas || []).map((s) => {
    const d = diasHasta(s.desde), enCurso = d !== null && d <= 0 && diasHasta(s.hasta) >= 0;
    const v = vivo[s.clave] || null, kmTxt = dec(v && v.km != null ? v.km : s.km, 1), kmEscrito = dec(s.km, 1);
    const cambio = kmTxt !== kmEscrito;
    return '<article class="semana"><header><div><b>Semana ' + esc(s.clave) + "</b> <span class='gris mini-txt'>"
      + fechaCorta(s.desde) + " - " + fechaCorta(s.hasta) + "</span></div>"
      + '<div class="chips"><span class="chip a">' + kmTxt + " km</span>"
      + (cambio ? '<span class="chip">escrito: ' + kmEscrito + " km</span>" : "")
      + (enCurso ? '<span class="chip ok">esta semana</span>' : "") + "</div></header>"
      + "<div class='s-foco' style='padding:8px 13px 0'>" + esc(s.foco) + "</div>"
      + (v && v.motivos && v.motivos.length && (cambio || enCurso)
        ? "<div class='plan-motivo gris mini-txt' style='padding:6px 13px 0'>Recalculado con lo que ha pasado: "
          + esc(v.motivos.join(" ")) + "</div>" : "")
      + tablaHTML([{ n: "Dia" }, { n: "Quien" }, { n: "Sesion" }, { n: "Detalle" }],
        s.sesiones.map((x) => ["<span class='sesion-dia'><i class='dot " + esc(x.tipo) + "'></i>" + esc(x.dia) + "</span>",
          (x.quien === "entrenador" ? '<span class="etiqueta v">entrenador</span>' : '<span class="etiqueta a">por mi cuenta</span>'),
          esc(x.titulo), "<span class='gris'>" + esc(x.detalle) + "</span>"]), { compacta: true })
      + "</article>";
  }).join(""));

  pintar("planBloques", tablaHTML([{ n: "Bloque" }, { n: "Desde" }, { n: "Hasta" }, { n: "Volumen" }, { n: "Que" }],
    (PLAN.bloques || []).map((b) => ["<b>" + esc(b.nombre) + "</b>", "<span class='ahora'>" + esc(fechaCorta(b.desde)) + "</span>",
      "<span class='ahora'>" + esc(fechaCorta(b.hasta)) + "</span>", esc(b.km), "<span class='gris'>" + esc(b.que) + "</span>"]), { compacta: true }));
  pintar("planReglas", (PLAN.reglas || []).map((r) => "<li>" + esc(r) + "</li>").join(""));
  pintar("planDecisiones", (PLAN.decisiones || []).map((r) => "<li>" + esc(r) + "</li>").join(""));
}

/* ---------- 8. Entrenamientos ------------------------------------------- */

function pintarEntrenos() {
  const sesiones = (DATOS.sesiones_recientes || []).slice();
  const pintarSesiones = () => {
    const t = q("entrenosBuscar").value.trim().toLowerCase();
    let s = sesiones.filter((x) => !t || [x.nombre, x.fecha, x.dist_m, x.sensacion, x.piscina_m].join(" ").toLowerCase().indexOf(t) >= 0);
    /* El orden lo pone el titular de la columna (montarOrdenTablas); al pintar, por fecha. */
    s = s.slice().sort((a, b) => (a.fecha < b.fecha ? 1 : -1));
    /* Un parte recien guardado esta en el navegador y no en la base hasta que se sube: la sesion tiene que
       salir ya como hecha (con su aviso de que falta subirla), no como si no se hubiera rellenado. */
    const deBase = (PPA().partes || []).map((p) => String(p.actividad_id));
    const deAqui = leerPartes().map((p) => String(p.actividad_id));
    const esperan = (PPA().pendientes || []).map((p) => String(p.actividad_id))
      .filter((id) => deAqui.indexOf(id) < 0);
    pintar("entrenosCuenta", s.length + " de " + sesiones.length + " sesiones");
    pintar("entrenosTabla", tablaHTML(
      [{ n: "Fecha" }, { n: "Sesion" }, { n: "Metros", num: true }, { n: "Tiempo", num: true }, { n: "Ritmo /100", num: true },
       { n: "Piscina", num: true }, { n: "Pulso", num: true }, { n: "Sensacion /5", num: true }, { n: "Parte" }],
      s.map((x) => {
        const id = x.actividad_id === null || x.actividad_id === undefined ? null : String(x.actividad_id);
        /* Un entrenamiento apuntado a mano (sin reloj) no tiene parte, pero tambien se pincha: lleva a
           "Apuntar mis entrenamientos", que es donde esta apuntado. */
        const ap = !id && x.apunte_id !== null && x.apunte_id !== undefined ? String(x.apunte_id) : null;
        return {
          clase: id || ap ? "pinchable" : "",
          attrs: id ? ' data-sesion="' + esc(id) + '" data-fecha="' + esc(x.fecha) + '" tabindex="0"'
                 : (ap ? ' data-apunte="' + esc(ap) + '" data-fecha="' + esc(x.fecha) + '" tabindex="0"' : ""),
          celdas: ["<span class='ahora'>" + esc(fechaCorta(x.fecha)) + "</span>", esc(x.nombre || "—"), entero(x.dist_m),
            cronoVerbal(x.min ? x.min * 60 : null), ritmo100(x.ritmo_100), entero(x.piscina_m),
            entero(x.fc_media),
            de0a5(x.sensacion),
            (id && esperan.indexOf(id) >= 0 ? chip("por rellenar", "a")
              : (id && deBase.indexOf(id) >= 0 ? chip("hecho", "ok")
                : (id && deAqui.indexOf(id) >= 0 ? chip("hecho · sin subir", "ok")
                  : (ap ? chip("sin reloj", "a") : "—"))))],
        };
      }), { compacta: true }));
  };
  /* Se pinta mas de una vez (al guardar un parte la lista tiene que reflejarlo), asi que la escucha se pone
     una sola vez. */
  if (!q("entrenosBuscar")._escucha) {
    q("entrenosBuscar").addEventListener("input", pintarSesiones);
    q("entrenosBuscar")._escucha = true;
  }
  pintarSesiones();

  /* Las filas de esta tabla se pinchan con el oyente global (montarFilasPinchables), no con uno propio. */

  /* Si se acaba de subir un parte, la pagina se recarga: se vuelve a abrir esa misma sesion. */
  let volver = null;
  try { volver = sessionStorage.getItem("parteAbierto"); sessionStorage.removeItem("parteAbierto"); } catch (e) {}
  if (volver) {
    const fila = document.querySelector('[data-sesion="' + volver + '"]');
    abrirParte(volver, fila ? fila.dataset.fecha : null, true);
  }

  const seg = DATOS.segmentos || [];
  const pintarSeg = () => {
    const t = q("segmentosBuscar").value.trim().toLowerCase();
    const s = seg.filter((x) => !t || x.nombre.toLowerCase().indexOf(t) >= 0);
    pintar("segmentosCuenta", s.length + " de " + seg.length);
    pintar("segmentosTabla", tablaHTML(
      [{ n: "Tramo" }, { n: "Veces", num: true }, { n: "Distancia", num: true }, { n: "Mediana", num: true }, { n: "Mejor", num: true }, { n: "Ultima vez" }],
      s.slice(0, 120).map((x) => [esc(x.nombre), entero(x.apariciones), entero(x.dist_m) + " m",
        "<span class='gris'>" + ritmo100(x.ritmo_mediana) + "</span>", "<span class='tiempo'>" + ritmo100(x.ritmo_mejor) + "</span>",
        "<span class='ahora'>" + esc(fechaCorta(x.ultima_vez)) + "</span>"]), { compacta: true }));
  };
  q("segmentosBuscar").addEventListener("input", pintarSeg);
  pintarSeg();

  pintar("bloquesLargos", tablaHTML([{ n: "Fecha" }, { n: "Metros", num: true }, { n: "Tiempo", num: true }, { n: "Ritmo /100", num: true }],
    (DATOS.bloques_largos || []).map((b) => ["<span class='ahora'>" + esc(fechaCorta(b.fecha)) + "</span>", entero(b.dist_m),
      cronoVerbal(b.tiempo_s), ritmo100(b.ritmo_100)]), { compacta: true }));
}

/* ---------- 9. Gimnasio ------------------------------------------------- */

/* La plantilla de series y kilos: los ejercicios que hace siempre, con lo ultimo de cada uno. Los numeros se
   guardan en la base (la vista de Gimnasio los manda al servidor), no en el navegador: asi no hay que exportar
   nada y el historial queda junto al resto de su entrenamiento. */
const GIMNASIO = urlApi("gimnasio");
let GIM = null;

function numerosDe(d) {
  const trozos = [];
  if (d.series && d.reps) trozos.push(d.series + "x" + d.reps);
  else if (d.series) trozos.push(d.series + " series");
  else if (d.reps) trozos.push(d.reps + " reps");
  if (d.kg) trozos.push(entero(d.kg) + " kg");
  return trozos.length ? trozos.join(" a ") : "\u2014";
}

function pintarPlantillaGimnasio() {
  const caja = document.getElementById("gimPlantilla");
  if (!caja) return;
  if (!GIM && typeof fetch === "function") {
    caja.innerHTML = '<div class="vacio">Cargando tus ejercicios...</div>';
    fetch(GIMNASIO).then(function (r) { return r.json(); }).then(function (d) {
      if (!d || !d.ok) {
        caja.innerHTML = '<div class="vacio"><strong>No se pudo leer</strong>'
          + esc((d && d.error) || "el servidor no ha contestado.") + "</div>";
        return;
      }
      GIM = d;
      const fecha = document.getElementById("gimFecha");
      if (fecha && !fecha.value) fecha.value = d.fecha_hoy || "";
      pintarPlantillaGimnasio();
    }).catch(function () {
      caja.innerHTML = '<div class="vacio"><strong>Sin servidor</strong>Enciende el servidor del entrenador'
        + ' (127.0.0.1:8181) y vuelve a esta pagina.</div>';
    });
    return;
  }
  if (!GIM) return;
  /* En filas, como una hoja del gimnasio: un ejercicio por linea, y al final la linea para anadir los que falten. */
  const filas = GIM.ejercicios.map(function (e) {
    const u = e.ultimo || {}, m = e.mejor || {};
    return "<tr class='gim-fila' data-ejercicio='" + esc(e.nombre) + "'>"
      + "<td><strong>" + esc(e.nombre) + "</strong>"
      + "<div class='pista'>" + (u.fecha
          ? "la ultima vez (" + esc(u.fecha) + "): " + numerosDe(u)
          : "sin apuntar todavia")
      + (m.kg ? " \u00b7 mejor: " + numerosDe(m) : "") + "</div></td>"
      + "<td><input type='number' min='0' class='gim-series gim-num' value='" + (u.series || "") + "'></td>"
      + "<td><input type='number' min='0' class='gim-reps gim-num' value='" + (u.reps || "") + "'></td>"
      + "<td><input type='number' min='0' step='0.5' class='gim-kg gim-num' value='" + (u.kg || "") + "'></td>"
      + "</tr>";
  }).join("");
  caja.innerHTML = "<table class='tabla gim-tabla'><thead><tr><th>Ejercicio</th><th>Series</th><th>Reps</th>"
    + "<th>Kilos</th></tr></thead><tbody>" + filas
    + "<tr class='gim-nueva'><td><select id='gimNuevoSel' class='gim-select'></select>"
    + " <input type='text' id='gimNuevoNombre' class='gim-nombre' placeholder='u otro'></td>"
    + "<td colspan='3'><button class='boton mini' id='gimAnadir' type='button'>Anadir</button></td></tr>"
    + "</tbody></table>";

  /* El selector trae los que faltan: los del gimnasio del portal que todavia no son habituales. */
  const sel = document.getElementById("gimNuevoSel");
  if (sel) {
    const ya = GIM.ejercicios.map(function (e) { return e.nombre.toLowerCase(); });
    const faltan = EJERCICIOS_HABITUALES.filter(function (n) { return ya.indexOf(n.toLowerCase()) < 0; });
    sel.innerHTML = "<option value=''>Los que faltan...</option>"
      + faltan.map(function (n) { return "<option value='" + esc(n) + "'>" + esc(n) + "</option>"; }).join("");
  }
  const botonAnadir = document.getElementById("gimAnadir");
  if (botonAnadir) botonAnadir.addEventListener("click", anadirEjercicioGimnasio);

  const hist = document.getElementById("gimHistorico");
  if (!hist) return;
  if (!GIM.sesiones || !GIM.sesiones.length) {
    hist.innerHTML = '<div class="vacio">Todavia no hay ninguna sesion de gimnasio apuntada.</div>';
    return;
  }
  hist.innerHTML = "<table class='tabla'><thead><tr><th>Dia</th><th>Lo que hiciste</th><th>Volumen</th></tr></thead><tbody>"
    + GIM.sesiones.map(function (s) {
        return "<tr><td>" + esc(s.fecha) + "</td><td>" + s.ejercicios.map(function (d) {
          return esc(d.ejercicio) + " " + numerosDe(d);
        }).join(" \u00b7 ") + "</td><td>"
          + (s.volumen_kg ? entero(s.volumen_kg) + " kg" : "\u2014") + "</td></tr>";
      }).join("")
    + "</tbody></table>";
}

/* Anadir un ejercicio que no esta en la plantilla: se pinta como una fila mas y, en cuanto se guarda el dia, entra
   en los habituales (lo mete en el catalogo `gimnasio.apuntar`, sin preguntar nada). */
function anadirEjercicioGimnasio() {
  const caja = document.getElementById("gimPlantilla");
  const sel = document.getElementById("gimNuevoSel");
  const nombre = document.getElementById("gimNuevoNombre");
  if (!caja) return;
  const cual = ((sel && sel.value) || (nombre && nombre.value) || "").trim();
  if (!cual) return;
  const repetido = caja.querySelector(".gim-fila[data-ejercicio='" + cual.replace(/'/g, "\\'") + "']");
  if (repetido) {
    const primero = repetido.querySelector(".gim-series");
    if (primero) primero.focus();
    return;
  }
  const tr = document.createElement("tr");
  tr.className = "gim-fila";
  tr.setAttribute("data-ejercicio", cual);
  tr.innerHTML = "<td><strong>" + esc(cual) + "</strong><div class='pista'>nuevo: en cuanto lo guardes,"
    + " queda como habitual</div></td>"
    + "<td><input type='number' min='0' class='gim-series gim-num'></td>"
    + "<td><input type='number' min='0' class='gim-reps gim-num'></td>"
    + "<td><input type='number' min='0' step='0.5' class='gim-kg gim-num'></td>";
  const nueva = caja.querySelector(".gim-nueva");
  caja.querySelector("tbody").insertBefore(tr, nueva);
  if (nombre) nombre.value = "";
  if (sel) sel.value = "";
  const primero = tr.querySelector(".gim-series");
  if (primero) primero.focus();
}

function guardarGimnasio() {
  const caja = document.getElementById("gimPlantilla");
  const aviso = document.getElementById("gimAviso");
  if (!caja) return;
  const fecha = (document.getElementById("gimFecha") || {}).value || "";
  const filas = [];
  caja.querySelectorAll(".gim-fila[data-ejercicio]").forEach(function (f) {
    const s = f.querySelector(".gim-series").value, r = f.querySelector(".gim-reps").value,
          k = f.querySelector(".gim-kg").value;
    if (!s && !r && !k) return;
    filas.push({ ejercicio: f.getAttribute("data-ejercicio"), series: s || null, reps: r || null, kg: k || null });
  });
  if (!filas.length) {
    if (aviso) aviso.textContent = "No hay nada marcado: pon al menos las series o los kilos.";
    return;
  }
  if (aviso) aviso.textContent = "Guardando...";
  fetch(GIMNASIO, { method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ fecha: fecha, ejercicios: filas }) })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d || !d.ok) {
        if (aviso) aviso.textContent = "No se pudo guardar: " + ((d && d.error) || "sin respuesta");
        return;
      }
      GIM = d.hoja || null;
      pintarPlantillaGimnasio();
      if (aviso) {
        aviso.textContent = "Guardado: " + d.ejercicios.length + " ejercicio(s), " + d.repeticiones + " repeticiones"
          + (d.volumen_kg ? ", " + entero(d.volumen_kg) + " kg" : "") + ".";
      }
    })
    .catch(function () { if (aviso) aviso.textContent = "No se pudo guardar: el servidor no responde."; });
}

document.addEventListener("DOMContentLoaded", function () {
  const b = document.getElementById("gimGuardar");
  if (b) b.addEventListener("click", guardarGimnasio);
});


const MATERIAL_GYM = ["Mancuernas", "Barra y discos", "Maquinas", "Gomas", "Banco", "Mancuernas rusas", "Barra de dominadas", "Nada de material"];
const EJERCICIOS_HABITUALES = ["Press banca", "Press inclinado con mancuernas", "Aperturas", "Fondos", "Curl de biceps",
  "Curl martillo", "Extension de triceps", "Remo con barra", "Remo con mancuerna", "Jalon al pecho", "Dominadas",
  "Face pull", "Rotadores con goma", "Plancha", "Plancha lateral", "Elevacion de piernas", "Sentadilla", "Peso muerto",
  "Zancadas", "Gemelos", "Hip thrust"];


/* La fuerza que sostiene el hombro (V1.4-01, V1.4-02, V1.4-03): la dosis del anexo T.7 con su estado, el aviso de
   abandono, el aviso de seguridad si hay dolor declarado y la carga de la semana. Viene calculado en DATOS.fuerza;
   aqui solo se pinta, y si falta se dice que falta en vez de dejar el hueco en blanco. */
function pintarFuerza() {
  const cajaD = q("fueDosis"), cajaC = q("fueCarga"), cajaS = q("fueSeguro");
  if (!cajaD || !cajaC || !cajaS) return;
  const f = DATOS.fuerza;
  if (!f) {
    cajaD.innerHTML = '<div class="vacio"><strong>Sin datos de fuerza</strong>El motor no ha podido calcular la dosis preventiva del hombro.</div>';
    cajaC.innerHTML = "";
    cajaS.innerHTML = "";
    return;
  }
  const d = f.dosis || {}, e = f.estado || "sin empezar";
  const clase = e === "cumplida" ? "etiqueta ok" : (e === "a medias" ? "etiqueta up" : "etiqueta no");
  const citas = (f.cita || []).map((n) => '<span class="chip">Anexo ' + esc(n) + "</span>").join(" ");
  cajaD.innerHTML = '<div class="item"><i class="i-marca"></i><div class="i-txt"><strong>Dosis preventiva: '
    + esc(e) + "</strong><span>" + entero(d.sesiones_semana) + " sesiones por semana \u00b7 "
    + entero(d.ejercicios) + " ejercicios \u00b7 " + entero(d.reps_min) + " repeticiones o mas \u00b7 "
    + entero(d.semanas) + " semanas"
    + (f.hechas != null ? " \u00b7 esta semana, " + entero(f.hechas) + " apuntada(s)" : "")
    + (f.faltan_de_la_plantilla ? " \u00b7 te faltan " + entero(f.faltan_de_la_plantilla) + " de la plantilla" : "")
    + "</span>" + (citas ? '<div class="chips" style="margin-top:6px">' + citas + "</div>" : "")
    + '<span class="gris mini-txt">' + esc(f.fuente || "") + (f.grado ? " \u00b7 " + esc(f.grado) : "") + "</span>"
    + '</div><span class="' + clase + '">' + esc(e) + "</span></div>";

  const s = (f.semana || {});
  const dias = Object.keys(s.por_dia || {});
  cajaC.innerHTML = '<div class="item"><i class="i-marca"></i><div class="i-txt"><strong>La carga de la fuerza esta semana</strong>'
    + "<span>" + entero(s.sesiones) + " sesion(es) \u00b7 " + entero(s.series) + " series \u00b7 "
    + entero(s.repeticiones) + " repeticiones \u00b7 " + entero(s.volumen_kg) + " kg levantados"
    + (s.con_rpe ? "" : " \u00b7 sin RPE apuntado: no se puede decir si fue dura") + "</span>"
    + (dias.length ? '<span class="gris mini-txt">Dias con gimnasio: ' + esc(dias.join(", "))
        + " (" + esc(s.desde) + " a " + esc(s.hasta) + ")</span>" : "")
    + '<span class="gris mini-txt">' + esc(f.nota || "") + "</span></div>"
    + '<span class="etiqueta">' + entero(s.sesiones) + " sesion(es)</span></div>";

  const a = f.abandono || {}, seg = f.seguridad;
  const trozos = [];
  if (seg) {
    trozos.push('<div class="item"><i class="i-marca"></i><div class="i-txt"><strong>'
      + esc(seg.titulo || "Aviso de seguridad") + "</strong><span>" + esc(seg.texto || "") + "</span></div>"
      + '<span class="etiqueta no">parar</span></div>');
  }
  if (a.aviso) {
    trozos.push('<div class="item"><i class="i-marca"></i><div class="i-txt"><strong>'
      + esc(a.titulo || "La fuerza esta parada") + "</strong><span>" + esc(a.texto || "") + "</span>"
      + (a.cita && a.cita.length ? '<span class="gris mini-txt">Anexo ' + esc(a.cita.join(", ")) + "</span>" : "")
      + '</div><span class="etiqueta up">aviso</span></div>');
  }
  cajaS.innerHTML = trozos.join("") || ('<div class="vacio"><strong>Sin avisos de fuerza</strong>'
    + "La dosis va al dia y no hay dolor declarado.</div>");
}

function pintarGimnasio() {
  pintarPlantillaGimnasio();
  pintarFuerza();
  const g = DATOS.gimnasio || {}, gp = (APU.gimnasio || {});
  const peticionesGuardadas = leerPeticiones().length;
  const sesionesGuardadas = leerSesiones().length;
  pintar("gimKpis", [
    kpi("Peticiones pendientes", entero(peticionesGuardadas + (gp.n_peticiones || 0)), "para escribir la sesion", peticionesGuardadas ? "up" : ""),
    kpi("Sesiones apuntadas", entero(sesionesGuardadas + (gp.n_sesiones || 0)), "con ejercicios y kilos", "a"),
    kpi("Volumen levantado", entero((gp.volumen_total_kg || 0)) + " kg", "series x reps x kilos"),
    kpi("Del reloj", entero(g.n), (g.ultima ? "ultima " + fechaCorta(g.ultima) : "sin datos")),
    kpi("Media del reloj", entero(g.minutos_media) + " min", "por sesion"),
  ]);
  pintar("cGimnasio", (peticionesGuardadas + (gp.n_peticiones || 0)) || "");

  /* materiales */
  pintar("gsMaterial", MATERIAL_GYM.map((m) => '<label><input type="checkbox" value="' + esc(m) + '"' + (["Mancuernas", "Maquinas", "Gomas"].indexOf(m) >= 0 ? " checked" : "") + ">" + esc(m) + "</label>").join(""));
  const c = q("gsCuando"); if (!c.value) c.value = hoyISO();
  const af = q("apFecha"); if (!af.value) af.value = hoyISO();

  /* --- peticiones --- */
  const pintarPeticiones = () => {
    const lista = leerPeticiones().concat((gp.peticiones || []).map((p) => Object.assign({}, p, { deBase: true })));
    pintar("gsCuentaDe", lista.length + (lista.length === 1 ? " peticion" : " peticiones"));
    const caja = q("gsLista");
    caja.innerHTML = "";
    if (!lista.length) {
      caja.innerHTML = '<div class="vacio"><strong>Sin peticiones</strong>Escribe arriba lo que quieres trabajar y pulsa "Solicitar trabajo de gimnasio".</div>';
      return;
    }
    lista.slice().reverse().forEach((p, i) => {
      const fecha = p.fecha || p.cuando || "";
      caja.appendChild(el("div", { clase: "item", "data-tipo": "gimnasio_peticion" }, [
        el("i", { clase: "i-marca" }),
        el("div", { clase: "i-txt", html: "<strong>" + esc(p.objetivo || "Sesion") + " · " + esc(p.minutos || "?") + " min · " + esc(p.donde || "Gimnasio")
          + "</strong><span>" + (fecha ? "para el " + esc(fechaCorta(fecha)) : "sin fecha") + (p.deBase ? " · ya en la base" : " · sin subir")
          + "</span>" + ((p.material || []).length ? '<div class="chips" style="margin-top:5px">' + p.material.map((m) => '<span class="chip">' + esc(m) + "</span>").join("") + "</div>" : "")
          + (p.molestias ? "<p>A evitar: " + esc(p.molestias) + "</p>" : "") + (p.notas ? "<p>" + esc(p.notas) + "</p>" : "") }),
        p.deBase ? el("span", { clase: "etiqueta ok", texto: "importada" })
          : el("button", { clase: "boton mini peligro", type: "button", html: icono("papelera"), title: "Quitar", onclick: () => {
              const l = leerPeticiones(); l.splice(l.length - 1 - i, 1); almacen.guardar(CLAVES.peticiones, l); pintarPeticiones();
            } }),
      ]));
    });
  };
  pintarPeticiones();

  q("gsEjemplo").addEventListener("click", () => {
    q("gsObjetivo").value = "Traccion (espalda)";
    q("gsMinutos").value = "40";
    q("gsNotas").value = "Sesion corta despues de nadar. El hombro anda flojo.";
  });
  q("gsAnadir").addEventListener("click", () => {
    const material = $$("#gsMaterial input:checked").map((i) => i.value);
    const p = {
      fecha: q("gsCuando").value || hoyISO(), objetivo: q("gsObjetivo").value, minutos: Number(q("gsMinutos").value) || null,
      donde: q("gsDonde").value, material: material, molestias: q("gsMolestias").value.trim(), notas: q("gsNotas").value.trim(),
    };
    const l = leerPeticiones(); l.push(p); almacen.guardar(CLAVES.peticiones, l);
    q("gsNotas").value = "";
    pintar("gsAviso", "Peticion guardada. Pulsa \"Descargar fichero\" y el agente la escribe.");
    setTimeout(() => pintar("gsAviso", ""), 4000);
    pintarPeticiones();
  });

  /* --- historial de la base --- */

  pintar("gimPrescritas", (gp.prescritas || []).length
    ? (gp.prescritas || []).map((s) => '<article class="semana" style="margin-bottom:10px"><header><div><b>' + esc(s.titulo || "Sesion")
      + '</b> <span class="gris mini-txt">' + esc(fechaCorta(s.fecha)) + "</span></div></header>"
      + tablaHTML([{ n: "Ejercicio" }, { n: "Series x reps", num: true }, { n: "Peso", num: true }, { n: "Nota" }],
        (s.bloques || []).map((b) => [esc(b.ejercicio), entero(b.series) + " x " + entero(b.reps),
          (b.kg ? dec(b.kg, 1) + " kg" : "—"), "<span class='gris'>" + esc(b.nota || "") + "</span>"]), { compacta: true })
      + (s.notas ? '<p class="ayuda" style="padding:8px 13px 0">' + esc(s.notas) + "</p>" : "") + "</article>").join("")
    : '<div class="vacio"><strong>Nada mandado todavia</strong>Cuando pidas una sesion, aqui aparece escrita con sus series y sus pesos.</div>');

  pintar("gimReloj", tablaHTML([{ n: "Fecha" }, { n: "Nombre" }, { n: "Duracion", num: true }],
    (g.sesiones || []).slice().reverse().map((s) => ["<span class='ahora'>" + esc(fechaCorta(s.fecha)) + "</span> <span class='gris mini-txt'>" + esc(s.hora) + "</span>",
      esc(s.nombre), cronoVerbal(s.duracion_s)]), { compacta: true }));
}

/* ---------- 10. Apuntar ------------------------------------------------- */

function pintarApuntar() {
  const pintarLista = () => {
    const l = leerApuntes();
    pintar("apCuenta", l.length + (l.length === 1 ? " apunte" : " apuntes") + " · gimnasio: " + leerPeticiones().length + " peticiones, " + leerSesiones().length + " sesiones");
    const caja = q("apLista");
    caja.innerHTML = "";
    if (!l.length) { caja.innerHTML = '<div class="vacio"><strong>Nada apuntado</strong>Lo que anadas aqui se queda en este navegador hasta que descargues el fichero.</div>'; return; }
    l.slice().reverse().forEach((a, i) => {
      const partes = [a.tipo, a.distancia_m ? entero(a.distancia_m) + " m" : "", a.minutos ? entero(a.minutos) + " min" : "",
        a.material || "", a.sensacion !== "" && a.sensacion !== null && a.sensacion !== undefined ? "sensacion " + a.sensacion : ""].filter(Boolean);
      caja.appendChild(el("div", { clase: "item", "data-tipo": a.tipo }, [
        el("i", { clase: "i-marca" }),
        el("div", { clase: "i-txt", html: "<strong>" + esc(fechaCorta(a.fecha)) + " · " + esc(partes.join(" · ")) + "</strong>"
          + (a.notas ? "<p>" + esc(a.notas) + "</p>" : "") }),
        el("button", { clase: "boton mini peligro", type: "button", html: icono("papelera"), onclick: () => {
          const m = leerApuntes(); m.splice(m.length - 1 - i, 1); almacen.guardar(CLAVES.apuntes, m); pintarLista();
        } }),
      ]));
    });
  };
  pintarLista();

  q("apAnadir").addEventListener("click", () => {
    const esSueno = q("apTipo").value === "sueno";
    const horas = parseFloat(q("apSueno").value || "0");
    const a = {
      fecha: q("apFecha").value || hoyISO(), tipo: q("apTipo").value,
      // La noche se apunta en horas y se guarda en minutos, que es como se guarda todo lo que dura (V1.2-05).
      distancia_m: esSueno ? "" : q("apDistancia").value,
      minutos: esSueno ? (horas ? String(Math.round(horas * 60)) : "") : q("apMinutos").value,
      material: esSueno ? "" : q("apMaterial").value, sensacion: q("apSensacion").value,
      fc_media: esSueno ? "" : q("apFc").value, piscina_m: esSueno ? "" : q("apPiscina").value,
      notas: q("apNotas").value.trim(),
    };
    if (!a.notas && !a.distancia_m && !a.minutos) { pintar("apAviso", "Pon al menos los metros, los minutos o una nota."); setTimeout(() => pintar("apAviso", ""), 4000); return; }
    const l = leerApuntes(); l.push(a); almacen.guardar(CLAVES.apuntes, l);
    ["apDistancia", "apMinutos", "apNotas", "apSensacion", "apFc", "apSueno"].forEach((id) => { q(id).value = ""; });
    pintar("apAviso", "Anadido a la lista."); setTimeout(() => pintar("apAviso", ""), 4000);
    pintarLista();
  });
  const descargar = () => {
    const blob = new Blob([ficheroApuntes()], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "partes_entrenador.json";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  };
  q("apDescargar").addEventListener("click", descargar);
  q("apCopiar").addEventListener("click", () => {
    const texto = ficheroApuntes();
    (navigator.clipboard ? navigator.clipboard.writeText(texto) : Promise.reject()).then(
      () => { pintar("apAviso", "Copiado al portapapeles."); setTimeout(() => pintar("apAviso", ""), 4000); },
      () => { pintar("apBase", '<div class="campo mt"><label>Copialo a mano</label><textarea rows="10" id="apTexto"></textarea></div>'); q("apTexto").value = texto; q("apTexto").select(); });
  });

  const imp = APU.recientes || [];
  pintar("apImportados", tablaHTML([{ n: "Fecha" }, { n: "Tipo" }, { n: "Metros", num: true }, { n: "Minutos", num: true }, { n: "Material" }, { n: "Sensacion", num: true }, { n: "Notas" }],
    imp.map((a) => ["<span class='ahora'>" + esc(fechaCorta(a.fecha)) + "</span>", esc(a.tipo), entero(a.distancia_m), entero(a.minutos),
      esc(a.material || "—"), (a.sensacion === null ? "—" : entero(a.sensacion)), "<span class='gris'>" + esc(a.notas || "") + "</span>"]),
    { compacta: true, vacio: "Todavia no se ha importado ningun apunte." }));
}

/* ---------- 10b. Parte del dia ----------------------------------------- */

/* El parte es lo que el reloj no sabe: agrupar los intervalos en series de un mismo bloque y poner material e
   intensidad. Se propone solo a partir del reloj y el atleta corrige: partir, juntar o quitar grupos, marcar
   el material con casillas y elegir la intensidad. Al guardarlo, entra en la lista de "partes sin subir" con
   todo lo demas (apuntes y gimnasio) y se baja en el mismo fichero. */

const PPA = () => DATOS.partes || {};
const EVA = () => DATOS.evaluacion || {};

const NOMBRE_MATERIAL = { pull: "Pull", aletas: "Aletas", palas: "Palas", tabla: "Tabla", snorkel: "Tuba" };
/* Los nombres de las intensidades los manda el servidor (`PPA().intensidades`, el mismo catalogo que valida lo
   que se guarda), asi que aqui no se copia la lista: cuando el entrenador anade una (por ejemplo `pies`) el
   portal la enseña sin tocar el JS. */
const NOMBRE_INTENSIDAD = {};
function nombreIntensidad(v) {
  if (!Object.keys(NOMBRE_INTENSIDAD).length) {
    (PPA().intensidades || []).forEach((i) => { NOMBRE_INTENSIDAD[i.valor] = i.nombre; });
  }
  return NOMBRE_INTENSIDAD[v] || v;
}

let seqGrupo = 0;

function etiquetaGrupo(g) {
  /* Un bloque juntado a mano no tiene UNA distancia de repeticion (el reloj las vio sueltas): se enseña por sus
     metros totales y el detalle queda dentro, grupo a grupo. Antes salia "4x\u2014", que no dice nada. */
  const metro = g.rep_m || distanciaComunDeReps(g);
  const n = g.n_reps || (g.laps || []).length || (g.reps || []).length;
  if (g.tipo === "continuo" || !metro || n < 2) return entero(g.metros) + " m";
  return n + "x" + entero(metro) + (g.estilo && g.estilo !== "libre" ? " " + esc(g.estilo) : "");
}

const chip = (t, clase) => '<span class="chip ' + (clase || "") + '">' + esc(t) + "</span>";

/* --- un grupo: cabecera, material con casillas e intensidad con selector --- */

function cuadraIntensidad(g) {
  if (!g.intensidad) return "Sin marcar: elige el nivel al que has ido.";
  if (g.intensidad === "pies") return "Pies: pataleo. Cuenta los metros, pero su ritmo no se compara con "
    + "el del plan (el reloj lo mide igual, pero no es ritmo de nado).";
  if (!g.intensidad_sugerida) return "Marcada por ti (el programa no tiene con que compararla).";
  if (g.intensidad === g.intensidad_sugerida) return "Cuadra con el ritmo medido.";
  return "Ojo: el programa diria " + nombreIntensidad(g.intensidad_sugerida)
    + (g.motivo_intensidad ? " (" + g.motivo_intensidad + ")" : "") + ". El selector manda, es tu sensacion.";
}

function opcionesMaterial(g) {
  const caja = el("div", { clase: "opciones" });
  (PPA().materiales || []).forEach((m) => {
    const id = "mat" + (++seqGrupo);
    const inp = el("input", { type: "checkbox", id: id });
    inp.dataset.m = m;
    if ((g.material || []).indexOf(m) >= 0) inp.checked = true;
    inp.addEventListener("change", () => {
      if (inp.checked) { if (g.material.indexOf(m) < 0) g.material.push(m); }
      else g.material = (g.material || []).filter((x) => x !== m);
      cuadrarReps(g);
    });
    caja.appendChild(el("label", { for: id }, [inp, document.createTextNode(NOMBRE_MATERIAL[m] || m)]));
  });
  caja.appendChild(el("span", { clase: "ayuda", texto: "Sin marcar nada = brazo libre." }));
  return caja;
}

function opcionesIntensidad(g) {
  const nombre = "int" + (++seqGrupo);
  const caja = el("div", { clase: "opciones" });
  const aviso = el("p", { clase: "ayuda" });
  (PPA().intensidades || []).forEach((i) => {
    const id = nombre + i.valor;
    const inp = el("input", { type: "radio", name: nombre, id: id, value: i.valor });
    if (g.intensidad === i.valor) inp.checked = true;
    inp.addEventListener("change", () => { g.intensidad = i.valor; aviso.textContent = cuadraIntensidad(g); cuadrarReps(g); });
    caja.appendChild(el("label", { for: id }, [inp, document.createTextNode(i.nombre)]));
  });
  aviso.textContent = cuadraIntensidad(g);
  aviso.style.marginTop = "7px";
  const cont = el("div");
  cont.appendChild(caja);
  cont.appendChild(aviso);
  return cont;
}

/* --- el estilo del grupo: crol, mariposa, espalda, braza o estilos (combinado) --- */

/* Los nombres los manda el servidor (`PPA().estilos`), el mismo catalogo que valida lo que se guarda. */
const NOMBRE_ESTILO = {};
function nombreEstilo(v) {
  if (!Object.keys(NOMBRE_ESTILO).length) {
    (PPA().estilos || []).forEach((i) => { NOMBRE_ESTILO[i.valor] = i.nombre; });
  }
  return NOMBRE_ESTILO[v] || v;
}

function opcionesEstilo(g) {
  const base = "est" + (++seqGrupo);
  const caja = el("div", { clase: "opciones" });
  const aviso = el("p", { clase: "ayuda" });
  const repinta = () => {
    aviso.textContent = g.estilo
      ? "Marca " + nombreEstilo(g.estilo) + ". El estilo importa: una serie de espalda o de braza no se "
        + "compara con crol (ni con el ritmo del plan, que es a crol)."
      : "Sin marcar: se da por crol (brazo libre).";
  };
  (PPA().estilos || []).forEach((i) => {
    const id = base + i.valor;
    const inp = el("input", { type: "radio", name: base, id: id, value: i.valor });
    if (g.estilo === i.valor) inp.checked = true;
    inp.addEventListener("change", () => { g.estilo = i.valor; repinta(); });
    caja.appendChild(el("label", { for: id }, [inp, document.createTextNode(i.nombre)]));
  });
  repinta();
  aviso.style.marginTop = "7px";
  const cont = el("div");
  cont.appendChild(caja);
  cont.appendChild(aviso);
  return cont;
}

/* --- el tiempo del grupo, cuando no hay tabla de repeticiones que lo recoja ----------------------- */

/* Un grupo de una sola repeticion (o de las piezas de una serie partida a mano) no tiene tabla de
   repeticiones, asi que su tiempo se escribe aqui. Vale tambien para corregirle el tiempo al reloj. */
/* El estilo del bloque, para la cabecera (el paleteo no tiene estilo que marcar: son piernas). */
function estiloNota(g) {
  return (g.estilo && g.intensidad !== "pies") ? ' <span class="gris">\u00b7 ' + esc(g.estilo) + "</span>" : "";
}

/* La forma del bloque (regular, progresiva, aflojando, cambiando...): **no la marca nadie**, sale de los tiempos
   que ya trae el reloj, con el margen que el sistema ha aprendido de sus propios partes (los tiempos bailan uno
   o dos segundos y el reloj se equivoca con algun largo). Se enseña en la cabecera, al lado del estilo, con lo
   que gano de la primera repeticion a la ultima. */
const NOMBRE_CONCEPTO = {};
function nombreConcepto(v) {
  if (!Object.keys(NOMBRE_CONCEPTO).length) {
    (PPA().conceptos || []).forEach((i) => { NOMBRE_CONCEPTO[i.valor] = i.nombre; });
  }
  return NOMBRE_CONCEPTO[v] || v;
}
function formaNota(g) {
  if (!g.concepto) return "";
  const ev = g.concepto_evidencia || {};
  const nombre = String(nombreConcepto(g.concepto)).split(" (")[0];
  const gana = ev.ganancia_s_100;
  const salto = (typeof gana === "number" && Math.abs(gana) > (ev.margen_s_100 || 0))
    ? ": " + dec(Math.abs(gana), 1) + " s/100 " + (gana > 0 ? "mas rapida" : "mas lenta")
      + " de la primera a la ultima"
    : "";
  const fuera = (ev.reps_fuera_de_la_tendencia || []).length;
  const aviso = fuera ? " " + (fuera === 1 ? "Una repeticion se sale" : fuera + " repeticiones se salen")
      + " de la linea (puede ser el reloj)." : "";
  return ' <span class="chip" title="' + esc("Se mide de los tiempos de sus repeticiones, no lo marca nadie."
    + " El sistema ya ha aprendido de tus partes cuanto bailan los tiempos." + aviso)
    + '">' + esc(nombre + salto) + "</span>";
}

/* El tiempo del bloque: el que marca el reloj, o el que escribe el atleta si no es el suyo. Manda el suyo, y con
   el se va el del lap cuando el bloque es de una sola repeticion (si no, el lap no lo cogeria). */
function ponerTiempoGrupo(g, valor) {
  const s = segundosDe(valor);
  g.tiempo_apuntado = s === null ? null : String(valor).trim();
  if (s === null) return false;
  g.tiempo_s = s;
  g.ritmo_100 = ritmoDe(g.metros, s);
  const reps = g.reps || [];
  if (reps.length === 1) {
    reps[0].tiempo_apuntado = String(valor).trim();
    reps[0].tiempo_s = s;
    reps[0].ritmo_100 = g.ritmo_100;
  }
  return true;
}

/* La cabecera de un bloque de una sola serie: la distancia (editable), el tiempo (editable) y el ritmo de cada
   cien (que sale de los dos y no se toca), todo en la misma linea. Es lo que el atleta pidio para no tener que
   bajar a la fila del tiempo del grupo. */
function cabeceraDeUnaSerie(g, estilo) {
  const caja = el("span", { clase: "fila", style: "gap:6px;align-items:baseline" });
  const inM = el("input", { clase: "mini-num", type: "text",
    value: String(Math.round(Number(g.metros) || Number(g.rep_m) || 0)) });
  const inT = el("input", { clase: "mini-tiempo", type: "text",
    value: (g.tiempo_apuntado !== undefined && g.tiempo_apuntado !== null) ? String(g.tiempo_apuntado) : crono(g.tiempo_s) });
  [inM, inT].forEach((x) => x.setAttribute("inputmode", "numeric"));
  inM.title = "Los metros del bloque. El reloj los saca del largo de la piscina y de las vueltas que ha visto: si se le escapo una, manda el tuyo.";
  inT.title = "El tiempo del bloque (5:55, 5,55 o 355). El reloj lo marca, pero el que vale es el tuyo.";
  const ritmo = el("span", { clase: "gris mini-txt" });
  const pinta = () => {
    ritmo.innerHTML = g.ritmo_100 ? ritmo100(g.ritmo_100) : "\u2014";
  };
  inM.addEventListener("input", () => {
    if (cambiarDistancia(g, inM.value, 1)) { pinta(); }
  });
  inT.addEventListener("input", () => { if (ponerTiempoGrupo(g, inT.value)) pinta(); });
  [inM, inT].forEach((x) => x.addEventListener("change", () => repintarDetalle()));
  pinta();
  caja.appendChild(inM);
  caja.appendChild(el("span", { clase: "gris mini-txt", texto: " m \u00b7 " }));
  caja.appendChild(inT);
  caja.appendChild(ritmo);
  caja.appendChild(el("span", { html: estilo + (g.descanso_s ? ' <span class="gris">\u00b7 descanso ' + dec(g.descanso_s, 0) + " s</span>" : "") }));
  return caja;
}

/* --- partir una serie en trozos iguales: de un 100 seguido, 2x50, con su tiempo cada uno --------- */

/* Los trozos que tienen sentido para un grupo: mitades, tercios y cuartos, siempre en multiplos de 25 m.
   Se cae la opcion que deje el grupo como ya esta (partir un 2x50 en 2 trozos de 50 no es partir nada). */
function trozosPosibles(g) {
  const metros = Math.round(+g.metros || 0);
  const rep = Math.round(+g.rep_m || 0);
  const reps = g.n_reps || (g.laps || []).length || 1;
  const trozo = (n) => Math.round(metros / n);
  return [2, 3, 4]
    .filter((n) => trozo(n) >= 25 && trozo(n) % 25 === 0 && Math.abs(trozo(n) * n - metros) < 1)
    .filter((n) => !(trozo(n) === rep && n === reps))
    .map((n) => ({ n: n, rep_m: trozo(n) }));
}

/* Reparte el grupo en `n` trozos iguales. Los intervalos del reloj se reparten en orden: el trozo que no
   tiene intervalo propio nace con el tiempo repartido a partes iguales y hay que escribirle el suyo. */
function partirEn(s, i, n) {
  const g = s.grupos[i];
  const metros = Math.round(+g.metros || 0);
  const trozo = Math.round(metros / n);
  if (n < 2 || trozo < 25 || Math.abs(trozo * n - metros) >= 1) {
    avisoParte("De ese grupo no salen " + n + " trozos de 25 m o mas.", s.actividad_id);
    return;
  }
  const laps = (g.laps || []).slice();
  const porLap = {};
  (g.reps || []).forEach((r) => {
    if (r.lap_idx !== undefined && r.lap_idx !== null) porLap[String(r.lap_idx)] = r;
  });
  const piezas = [];
  for (let k = 0; k < n; k += 1) {
    const desde = Math.floor((k * laps.length) / n);
    const hasta = Math.floor(((k + 1) * laps.length) / n);
    const suyos = laps.slice(desde, hasta);
    const del_reloj = suyos.map((l) => porLap[String(l)]).filter((x) => x)[0];
    const suyo = del_reloj && del_reloj.timer_s ? del_reloj.timer_s : null;
    const tiempo = suyo || (g.tiempo_s ? g.tiempo_s / n : null);
    const estimado = !suyo;
    piezas.push({
      tipo: "serie", rep_m: trozo, n_reps: 1, metros: trozo,
      tiempo_s: tiempo, ritmo_100: tiempo ? ritmoDe(trozo, tiempo) : null,
      descanso_s: g.descanso_s, cada_s: g.cada_s, estilo: g.estilo, brazadas_m: null,
      laps: suyos, intensidad_sugerida: g.intensidad_sugerida, motivo_intensidad: null,
      avisos: estimado ? ["Tiempo repartido a partes iguales: escribelo el tuyo."] : [],
      material: (g.material || []).slice(), intensidad: g.intensidad || "",
      reps: [{ dist_m: trozo, lap_idx: suyos.length ? suyos[0] : null, timer_s: tiempo,
               ritmo_100: tiempo ? ritmoDe(trozo, tiempo) : null, estimado: estimado }],
    });
  }
  s.grupos.splice(i, 1, ...piezas);
  repintarDetalle();
}

/* El control de partir, con los trozos que tienen sentido para ese grupo (2x50, 4x25...). */
function controlPartir(s, i, g) {
  const trozos = trozosPosibles(g);
  if (!trozos.length) return null;
  const sel = el("select", { clase: "mini-sel" });
  sel.appendChild(el("option", { value: "", texto: "Partir en..." }));
  trozos.forEach((t) => sel.appendChild(el("option", { value: String(t.n), texto: t.n + "x" + entero(t.rep_m) + " m" })));
  const btn = el("button", { clase: "boton mini suave", type: "button", texto: "Partir",
    onclick: () => {
      if (!sel.value) { avisoParte("Elige primero en cuantos trozos.", s.actividad_id); return; }
      partirEn(s, i, Number(sel.value));
    } });
  return el("span", { clase: "fila", style: "gap:6px;align-items:center" }, [sel, btn]);
}

/* --- repeticiones: cada una puede llevar su intensidad y su SWOLF medido --- */

const SWOLF_MIN = (PPA().swolf || {}).min || 15;
const SWOLF_MAX = (PPA().swolf || {}).max || 150;

function usaSwolf(g) {
  return g.intensidad === "swolf" || (g.reps || []).some((r) => r.intensidad === "swolf");
}

/* "5:55", "5,55" o "355" -> segundos (null si no se entiende). Es como el atleta le corrige el tiempo al
   reloj: el parte manda, igual que con el material. */
function segundosDe(texto) {
  const t = String(texto == null ? "" : texto).trim().replace(",", ".");
  if (!t) return null;
  const p = t.split(":");
  let s;
  if (p.length === 1) s = Number(p[0]);
  else if (p.length === 2) s = 60 * Number(p[0]) + Number(p[1]);
  else return null;
  return Number.isFinite(s) && s > 0 ? Math.round(s * 10) / 10 : null;
}

const ritmoDe = (metros, segundos) => (metros && segundos)
  ? Math.round(100 * segundos / metros * 10) / 10 : null;

/* Cuantas repeticiones llevan tiempo corregido y cuanto suma el grupo con ellos. */
function avisoTiempo(g) {
  const reps = g.reps || [];
  const corregidas = reps.filter((r) => r.tiempo_apuntado !== undefined && r.tiempo_apuntado !== null);
  if (!corregidas.length) return "";
  const total = reps.reduce((s, r) => s + (Number(r.tiempo_s) || Number(r.timer_s) || 0), 0);
  return "Tiempos corregidos por ti en " + corregidas.length + " de " + reps.length + " repeticiones (el grupo "
    + "suma " + crono(total) + "). Al guardar el parte, el ritmo del grupo se rehace con tus tiempos.";
}

function pintaAvisoTiempo(g, p) {
  const t = avisoTiempo(g);
  p.textContent = t;
  p.style.display = t ? "" : "none";
}

/* Un bloque de series dice cuantas son (`n_reps`). Si el parte se quedo corto y declara mas series de las que
   trae (pasa al corregir a mano el numero de series), se crean las que faltan vacias para poder rellenarlas: al
   atleta le "desaparecian las series" y no tenia donde escribir su tiempo. Las que se anaden van sin lap (el
   reloj no las vio) y con la distancia de las otras. */
function cuadrarRepsConSeries(g) {
  const n = Number(g.n_reps) || 0;
  if (n < 2 || !Array.isArray(g.reps)) return 0;
  const modelo = g.reps[g.reps.length - 1] || {};
  const dist = Number(g.rep_m) || Number(modelo.dist_m) || 0;
  let puestas = 0;
  while (g.reps.length < n) {
    g.reps.push({ dist_m: dist, timer_s: null, tiempo_s: null, ritmo_100: null, lap_idx: null, brazadas: null,
      intensidad: "", swolf_apuntado: null, material_apuntado: modelo.material_apuntado || null });
    puestas++;
  }
  return puestas;
}

function pintarReps(g) {
  const cont = g._contReps;
  if (!cont) return;
  cuadrarRepsConSeries(g);
  cont.innerHTML = "";
  const reps = g.reps || [];
  if (reps.length < 2) return;
  cont.appendChild(el("div", { clase: "etiqueta-mini", texto: "Cada repeticion (solo hay que tocar la que cambie)" }));
  const conSwolf = usaSwolf(g);
  const tabla = el("table", { clase: "tabla-reps" + (conSwolf ? " con-swolf" : "") });
  tabla.innerHTML = "<thead><tr><th>#</th><th>m</th><th>Tiempo</th><th>Ritmo</th><th>Brazadas</th>"
    + "<th>Intensidad</th><th>SWOLF medido</th></tr></thead>";
  const tb = el("tbody");
  reps.forEach((r, j) => {
    const tr = el("tr", { clase: r.revisar ? "revisar" : "" });
    tr.appendChild(el("td", { html: '<span class="gris">' + (j + 1) + "</span>" }));
    /* La distancia de cada repeticion se puede corregir: el reloj la saca del largo de la piscina y de las
       vueltas que ve, y con una vuelta de mas o de menos el numero que vale es el del atleta. */
    const inpM = el("input", { clase: "mini-num", type: "text", value: String(Math.round(Number(r.dist_m) || 0)) });
    inpM.setAttribute("inputmode", "numeric");
    inpM.title = "Los metros de esta repeticion (25, 50, 100, 200...)";
    inpM.addEventListener("input", () => { if (cambiarDistanciaRep(g, j, inpM.value)) tdRitmo.innerHTML = r.ritmo_100 ? ritmo100(r.ritmo_100) : '<span class="gris">—</span>'; });
    inpM.addEventListener("change", () => pintarReps(g));
    tr.appendChild(el("td", {}, [inpM]));
    /* El tiempo del reloj se puede corregir: cuando el crono mide mal (o el atleta cronometra de pared a
       pared), lo que vale es el suyo. Se escribe 5:55, 5,55 o 355, y el ritmo de la fila se rehace al momento;
       el tiempo y el ritmo del grupo los rehace el servidor al guardar el parte. */
    const inpT = el("input", { clase: "mini-tiempo", type: "text" });
    inpT.setAttribute("inputmode", "numeric");
    inpT.value = (r.tiempo_apuntado !== undefined && r.tiempo_apuntado !== null)
      ? String(r.tiempo_apuntado) : (r.timer_s === null || r.timer_s === undefined ? "" : crono(r.timer_s));
    if (inpT.value === "") inpT.placeholder = "—";
    inpT.title = "Lo que midio el reloj; si no es tu tiempo, escribelo (5:55, 5,55 o 355)";
    const tdRitmo = el("td", { html: r.ritmo_100 ? ritmo100(r.ritmo_100) : '<span class="gris">—</span>' });
    inpT.addEventListener("input", () => {
      const s = segundosDe(inpT.value);
      r.tiempo_apuntado = s === null ? null : inpT.value.trim();
      r.tiempo_s = s === null ? r.timer_s : s;
      r.ritmo_100 = s === null ? null : ritmoDe(r.dist_m, s);
      tdRitmo.innerHTML = r.ritmo_100 ? ritmo100(r.ritmo_100) : '<span class="gris">—</span>';
      const av = cont.querySelector(".aviso-tiempo");
      if (av) pintaAvisoTiempo(g, av);
    });
    inpT.addEventListener("change", () => pintarReps(g));
    tr.appendChild(el("td", {}, [inpT]));
    tr.appendChild(tdRitmo);
    tr.appendChild(el("td", { texto: r.brazadas ? entero(r.brazadas) : "—" }));
    const sel = el("select", { clase: "mini-sel" });
    sel.appendChild(el("option", { value: "", texto: "= que el grupo" }));
    (PPA().intensidades || []).forEach((i) => sel.appendChild(el("option", { value: i.valor, texto: i.nombre })));
    sel.value = r.intensidad || "";
    sel.addEventListener("change", () => { r.intensidad = sel.value; pintarReps(g); });
    tr.appendChild(el("td", {}, [sel]));
    const inp = el("input", { type: "number", clase: "mini-num", min: SWOLF_MIN, max: SWOLF_MAX, step: 1 });
    if (r.swolf_apuntado !== undefined && r.swolf_apuntado !== null) inp.value = r.swolf_apuntado;
    inp.placeholder = r.swolf ? String(Math.round(r.swolf)) : "—";
    inp.addEventListener("input", () => { r.swolf_apuntado = inp.value === "" ? null : Number(inp.value); });
    tr.appendChild(el("td", {}, [inp]));
    tb.appendChild(tr);
  });
  tabla.appendChild(tb);
  const env = el("div", { clase: "tabla-envoltura" });
  env.appendChild(tabla);
  cont.appendChild(env);
  cont.appendChild(el("p", { clase: "ayuda", texto: conSwolf
    ? "En gris esta el SWOLF que calcula el reloj (tiempo + brazadas); si has medido otro, escribelo y manda el tuyo."
    : "Puedes apuntar el SWOLF que midas en cualquier repeticion." }));
  const avT = el("p", { clase: "ayuda aviso-tiempo" });
  pintaAvisoTiempo(g, avT);
  cont.appendChild(avT);
}

function cuadrarReps(g) {
  if (g._contReps && esBloqueDeSeries(g)) pintarReps(g);
}

/* --- corregir la propuesta: juntar, partir, quitar --- */

function juntarGrupo(s, i) {
  const a = s.grupos[i - 1], b = s.grupos[i];
  const metros = (a.metros || 0) + (b.metros || 0), tiempo = (a.tiempo_s || 0) + (b.tiempo_s || 0);
  const unido = {
    tipo: "bloque", rep_m: null, n_reps: (a.n_reps || 0) + (b.n_reps || 0), metros: metros,
    tiempo_s: tiempo, ritmo_100: metros && tiempo ? Math.round((100 * tiempo) / metros * 10) / 10 : null,
    descanso_s: null, estilo: a.estilo === b.estilo ? a.estilo : null, brazadas_m: null,
    laps: (a.laps || []).concat(b.laps || []), reps: (a.reps || []).concat(b.reps || []),
    avisos: ["Grupo juntado a mano: comprueba que de verdad es un solo bloque."],
    intensidad_sugerida: a.intensidad_sugerida, motivo_intensidad: null,
    material: (a.material || []).slice(), intensidad: a.intensidad || "",
  };
  s.grupos.splice(i - 1, 2, unido);
  repintarDetalle();
}

function partirGrupo(s, i) {
  const g = s.grupos[i];
  const piezas = (g.reps || []).map((r) => ({
    tipo: "serie", rep_m: r.dist_m, n_reps: 1, metros: r.dist_m, tiempo_s: r.timer_s,
    ritmo_100: r.ritmo_100, descanso_s: null, estilo: r.estilo || g.estilo, brazadas_m: null,
    laps: [r.lap_idx], reps: [r], intensidad_sugerida: g.intensidad_sugerida, motivo_intensidad: null,
    avisos: r.revisar ? ["Intervalo con el cronometro mal disparado: el ritmo no es fiable."] : [],
    material: (g.material || []).slice(), intensidad: g.intensidad || "",
  }));
  if (piezas.length < 2) { avisoParte("Ese grupo ya es un solo intervalo: no hay nada que partir."); return; }
  s.grupos.splice(i, 1, ...piezas);
  repintarDetalle();
}

/* Rehace la distancia de un intervalo: manda la distancia de cada repeticion (25, 50, 100...) y los metros del
   grupo salen de multiplicar por las repeticiones. Se puede corregir porque el reloj la saca del largo de la
   piscina y de las vueltas que ha visto: si se le escapo una vuelta (o no se le dio al boton) el numero que
   vale es el del atleta. Devuelve `false` si la distancia no es utilizable. */
function cambiarDistancia(g, rep_m, n_reps) {
  const m = Math.round(Number(rep_m));
  const n = Math.max(1, Math.round(Number(n_reps)) || 1);
  if (!(m > 0)) return false;
  g.rep_m = m; g.n_reps = n; g.metros = m * n; g.dist_apuntada = true;
  const reps = g.reps || [];
  /* Las repeticiones del reloj se quedan con la distancia nueva solo cuando cuadran en numero: si no, son las
     vueltas que el reloj vio y no se tocan. */
  if (reps.length === n || (reps.length === 1 && n === 1)) {
    reps.forEach((r) => {
      r.dist_m = m;
      r.ritmo_100 = r.tiempo_s ? ritmoDe(m, r.tiempo_s) : null;
    });
  }
  g.ritmo_100 = g.tiempo_s ? ritmoDe(g.metros, g.tiempo_s) : null;
  return true;
}

/* Lo que duro el bloque entero, con los descansos de dentro: del inicio de la primera repeticion al final de la
   ultima. Lo pide el atleta en la cabecera del bloque (el tiempo a secas es solo lo nadado, y se queda corto).
   Si el servidor lo trae, manda el suyo; si el grupo se ha partido o juntado a mano en el portal, se compone con
   los tiempos de las repeticiones mas lo que se descansa entre ellas. */
function totalConDescansos(g) {
  if ((Number(g.total_s) || 0) > 0) return g.total_s;
  const reps = g.reps || [];
  if (reps.length < 2) return g.tiempo_s || null;
  const nadado = reps.reduce((t, r) => t + (Number(r.timer_s) || 0), 0) || g.tiempo_s || 0;
  const entre = Number(g.descanso_s) || 0;
  return nadado ? Math.round((nadado + entre * (reps.length - 1)) * 10) / 10 : null;
}

/* La mediana de una lista: la mitad dejan por debajo. No la estropea un valor suelto raro (un descanso largo
   entre dos series), que es justo lo que pasa en la piscina. */
function mediana(xs) {
  const v = (xs || []).filter((x) => isFinite(x)).slice().sort((a, b) => a - b);
  if (!v.length) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

/* El cada se canta en la piscina en numeros redondos ("4x100 cada 1:50", "3x400 cada 6:30") y la salida nunca es
   exacta al segundo: se redondea a los 5 s mas cercanos (lo pide el atleta). */
function redondearCada(s) {
  return s === null || s === undefined ? null : Math.round(Number(s) / 5) * 5;
}

/* El "cada" de un bloque: el **tiempo de la serie mas el descanso que va detras**, del inicio de una repeticion al
   de la siguiente. Manda lo que escriba el atleta; si no, sale de las repeticiones (cada una trae su descanso) y
   del del grupo; y siempre redondeado. Un bloque continuo (una sola repeticion) no tiene cada. */
function cadaDeducido(g) {
  const suyo = g.cada_apuntado ? segundosDe(g.cada_apuntado) : null;
  if (suyo) return suyo;                                  /* el suyo, tal cual lo canto: no se le toca */
  const reps = g.reps || [];
  /* Si el cada lo puso el programa (no el atleta), se rehace siempre de las repeticiones: si luego corrige un
     tiempo o parte el bloque, el cada que se ve es el de verdad. */
  if (reps.length >= 2 && (g.cada_deducido || !((Number(g.cada_s) || 0) > 0))) {
    const entreGrupo = Number(g.descanso_s) || 0;
    const salidas = [];
    for (let i = 0; i < reps.length - 1; i++) {
      const t = Number(reps[i].timer_s) || Number(reps[i].tiempo_s) || 0;
      if (!t) continue;
      const d = Number(reps[i].descanso_s);
      salidas.push(t + (isFinite(d) && d >= 0 ? d : entreGrupo));
    }
    const m = mediana(salidas);
    if (m) return redondearCada(m);
  }
  const cada = Number(g.cada_s) || 0;
  return cada > 0 ? redondearCada(cada) : null;
}

/* Un bloque de series de verdad: dos o mas repeticiones que se repiten cada cierto tiempo. En un bloque
   continuo (una sola serie seguida) no hay "cada" que valga. */
function esBloqueDeSeries(g) {
  return (Number(g.n_reps) || 0) >= 2 || (g.reps || []).length >= 2;
}

/* La distancia que comparten las repeticiones de un grupo, o `null` si no todas son iguales. */
function distanciaComunDeReps(g) {
  const ds = (g.reps || []).map((r) => Math.round(Number(r.dist_m) || 0)).filter((x) => x > 0);
  if (!ds.length) return null;
  return ds.every((x) => x === ds[0]) ? ds[0] : null;
}

/* La distancia de UNA repeticion de dentro de un grupo: lo que vio el reloj puede no ser lo que se nado (una
   vuelta contada de mas o de menos, o una repeticion hecha a otra distancia, como un 50 dentro de un 100).
   Los metros del grupo pasan a ser la suma de sus repeticiones. */
function cambiarDistanciaRep(g, j, valor) {
  const reps = g.reps || [];
  const r = reps[j];
  if (!r) return false;
  const m = Math.round(Number(valor));
  if (!(m > 0)) return false;
  r.dist_m = m;
  r.ritmo_100 = r.tiempo_s ? ritmoDe(m, r.tiempo_s) : null;
  const suma = reps.reduce((t, x) => t + (Number(x.dist_m) || 0), 0);
  if (suma > 0) g.metros = suma;
  g.rep_m = distanciaComunDeReps(g);
  g.ritmo_100 = g.tiempo_s ? ritmoDe(g.metros, g.tiempo_s) : g.ritmo_100;
  return true;
}

/* El "cada" de una serie (la salida: "8x100 cada 2:00"). El reloj no lo registra, asi que lo dice el atleta, y
   cuando lo dice manda lo suyo. Si lo deja vacio, se enseña el que se deduce de los intervalos del reloj. */
function cambiarCada(g, texto) {
  const t = String(texto === undefined || texto === null ? "" : texto).trim();
  /* En blanco: se vuelve al cada que se deduce de los intervalos (el de las repeticiones, no el que hubiera). */
  if (t === "") {
    g.cada_apuntado = null;
    g.cada_deducido = true;
    g.cada_s = null;
    g.cada_s = cadaDeducido(g);
    return true;
  }
  const s = segundosDe(t);
  if (s === null) return false;
  g.cada_apuntado = t;
  g.cada_deducido = false;
  g.cada_s = s;
  return true;
}

function filaCadaGrupo(g) {
  /* El cada va **relleno**, no en una etiqueta al lado (lo pidio el atleta: "rellenalo no lo anuncies en una
     etiqueta"): si no lo ha escrito el, se pone el que se deduce de los intervalos -el tiempo de la repeticion
     mas el descanso que va detras, ya redondeado- y se guarda con el bloque. */
  if (!g.cada_apuntado && (Number(g.cada_s) || 0) <= 0) {
    const est = cadaDeducido(g);
    if (est) { g.cada_s = est; g.cada_deducido = true; }
  }
  const cont = el("div", { clase: "fila", style: "gap:7px;align-items:center;margin-top:7px" });
  cont.appendChild(el("span", { clase: "etiqueta-mini", texto: "Cada (salida cada…)" }));
  const inp = el("input", { clase: "mini-tiempo", type: "text" });
  inp.setAttribute("inputmode", "numeric");
  inp.value = g.cada_apuntado ? String(g.cada_apuntado)
    : ((Number(g.cada_s) || 0) > 0 ? cronoVerbal(g.cada_s) : "");
  inp.title = "Cada cuanto sales en esta serie (2:00, 2,00 o 120). Viene puesto con lo que se deduce de los "
    + "intervalos (el tiempo de la repeticion mas su descanso); si lo escribes tu, vale el tuyo.";
  inp.addEventListener("input", () => { if (cambiarCada(g, inp.value)) inp.classList.remove("mal"); else inp.classList.add("mal"); });
  inp.addEventListener("change", () => repintarDetalle());
  cont.appendChild(inp);
  return cont;
}

/* Los pasos de cada 100 de una repeticion larga (de 400 m para arriba): el tiempo total no dice si saliste fuerte y
   pagaste al final; los pasos si. Solo salen en las repeticiones que el motor ha desglosado (`rep.pasos`, que viene
   de `entrenador/parciales.py`), y si hay una correccion del atleta dentro de un paso, ese paso sale con su tiempo
   corregido al lado del del reloj: el del reloj no se borra, se enseña lo que vale. */
function tablaPasos(rep) {
  const caja = el("div", { clase: "pasos" });
  const metros = Number(rep.dist_m) || 0;
  caja.appendChild(el("div", { clase: "etiqueta-mini",
    texto: "Pasos de cada 100" + (metros ? " \u00b7 " + entero(metros) + " m seguidos" : "") }));
  /* El paso es de 100 m, asi que su tiempo y su ritmo por 100 son el mismo numero: repetirlo no dice nada. La
     tercera columna enseña lo que llevas acumulado, que es lo que el atleta pidio para ver como se va cayendo la
     serie (y el ultimo valor del acumulado tiene que dar justo el total del bloque). */
  let acumulado = 0;
  const filas = (rep.pasos || []).map((p) => {
    const suyo = (p.segundos_corregidos !== undefined && p.segundos_corregidos !== null)
      ? Number(p.segundos_corregidos) : (Number(p.segundos) || 0);
    acumulado = Math.round((acumulado + suyo) * 100) / 100;
    return [
      "<span class='ahora'>" + entero(p.n) + "</span>",
      (p.correccion_s
        ? "<span class='gris'>" + crono(p.segundos) + "</span> <b>" + crono(suyo) + "</b>"
        : crono(suyo)),
      crono(acumulado),
      (p.brazadas ? entero(p.brazadas) : "<span class='gris'>\u2014</span>"),
    ];
  });
  caja.appendChild(el("div", { html: tablaHTML(
    [{ n: "Paso" }, { n: "Tiempo", num: true }, { n: "Acumulado", num: true }, { n: "Brazadas", num: true }],
    filas, { compacta: true }) }));
  return caja;
}

function pasosDeGrupo(g) {
  return (g.reps || []).filter((r) => (r.pasos || []).length).map(tablaPasos);
}

function pintarGrupo(s, i) {
  const g = s.grupos[i];
  if (!Array.isArray(g.material)) g.material = [];
  if (g.intensidad === undefined || g.intensidad === null) g.intensidad = g.intensidad_sugerida || "";
  const quitar = g.no_cuenta === true;

  const caja = el("div", { clase: "grupo" + (quitar ? " gris" : "") + ((g.avisos || []).length ? " revisar" : "") });
  const cabecera = el("div", { clase: "grupo-cab" });
  /* La cabecera: un bloque de una sola serie lleva sus casillas (distancia, tiempo y el ritmo, que sale solo) y
     un bloque de series lleva su nombre (NxM o los metros) y el total; en los dos casos, el cada y el estilo. */
  if (!quitar && !esBloqueDeSeries(g)) {
    /* Bloque de una sola serie: la cabecera se corrige entera aqui, en la misma linea y en el lado izquierdo —
       la distancia (en metros), el tiempo, y el ritmo de cada cien, que sale solo de los dos y no se toca. Con
       esto sobran la casilla de la derecha ("100 m x 2") y la fila del tiempo del grupo de mas abajo. */
    cabecera.appendChild(cabeceraDeUnaSerie(g, estiloNota(g) + formaNota(g)));
  } else {
    cabecera.appendChild(el("span", { html:
      "<b>" + etiquetaGrupo(g) + "</b> " + (g.ritmo_100 ? '<span class="gris">' + ritmo100(g.ritmo_100) + "</span>" : "")
      // El "cada" (intervalo de salida) es como el atleta canta la serie ("8x100 cada 2:00"): dice mas que el
      // descanso suelto, que cambia de una repeticion a otra.
      + (cadaDeducido(g) ? ' <span class="gris">\u00b7 cada ' + cronoVerbal(cadaDeducido(g)) + "</span>"
                 : (g.descanso_s ? ' <span class="gris">\u00b7 descanso ' + dec(g.descanso_s, 0) + " s</span>" : ""))
      + estiloNota(g) + formaNota(g) + "</span>" }));
    if (quitar) {
      cabecera.appendChild(el("span", { clase: "gris mini-txt",
                                       texto: entero(g.metros) + " m · " + cronoVerbal(g.tiempo_s) }));
    } else {
      /* Un bloque con series dentro ES la suma de lo de dentro: aqui no se toca nada (los metros y los tiempos son
         los de sus repeticiones). Se enseña el total: los metros y lo que duro, descansos incluidos. La distancia
         se corrige repeticion a repeticion, en su tabla de abajo. */
      cabecera.appendChild(el("span", { clase: "gris mini-txt",
        texto: entero(g.metros) + " m \u00b7 " + cronoVerbal(totalConDescansos(g)) + " con descansos" }));
    }
  }
  caja.appendChild(cabecera);
  /* Y su marca de prueba de medicion: el bloque que el atleta destaca para compararlo consigo mismo con los anos.
     Va en la cabecera, con lo demas del bloque. */
  if (!quitar) cabecera.appendChild(selectorPrueba(g));

  (g.avisos || []).forEach((a) => caja.appendChild(el("p", { clase: "ayuda", texto: "Aviso: " + a })));

  g._contReps = el("div", { clase: "reps-caja" });
  if (esBloqueDeSeries(g)) caja.appendChild(g._contReps);

  if (!quitar) {
    if (esBloqueDeSeries(g)) caja.appendChild(filaCadaGrupo(g));   /* el "cada" solo tiene sentido en bloques */
    /* El pataleo no tiene estilo que marcar: son piernas. */
    if (g.intensidad !== "pies") {
      caja.appendChild(el("div", { clase: "etiqueta-mini", texto: "Estilo" }));
      caja.appendChild(opcionesEstilo(g));
    }
    caja.appendChild(el("div", { clase: "etiqueta-mini", texto: "Material (lo que llevabas puesto)" }));
    caja.appendChild(opcionesMaterial(g));
    caja.appendChild(el("div", { clase: "etiqueta-mini", texto: "Intensidad" }));
    caja.appendChild(opcionesIntensidad(g));
    pintarReps(g);
    pasosDeGrupo(g).forEach((t) => caja.appendChild(t));
    /* Una repeticion sola no tiene tabla de repeticiones: su tiempo se escribe aqui. */
  } else {
    caja.appendChild(el("p", { clase: "ayuda", texto: "Descartado: no cuenta en el parte (por ejemplo, una vuelta suelta)." }));
  }

  caja.appendChild(el("div", { clase: "fila mt", style: "gap:7px" }, [
    i > 0 ? el("button", { clase: "boton mini suave", type: "button", texto: "Juntar con el de arriba", onclick: () => juntarGrupo(s, i) }) : null,
    el("button", { clase: "boton mini suave", type: "button", texto: "Partir en bloques",
      title: "Cada intervalo del reloj pasa a ser un bloque suyo (para lo que el cronometro partio de mas).",
      onclick: () => partirGrupo(s, i) }),
    controlPartir(s, i, g),
    el("button", { clase: "boton mini suave", type: "button", texto: "Añadir serie", title: "Para lo que nadó y el reloj no registró (no le dio tiempo a darle al botón): añade una serie más DENTRO de este bloque, copia de la última y con el tiempo a mano.",
      onclick: () => anadirSerie(s, i) }),
    el("button", { clase: "boton mini " + (quitar ? "" : "peligro"), type: "button", texto: quitar ? "Volver a poner" : "Quitar",
      onclick: () => { g.no_cuenta = !quitar; repintarDetalle(); } }),
  ]));
  return caja;
}

/* Añade **una serie mas dentro del bloque** en el que esta el boton (el atleta: "cuando añado una serie me esta
   añadiendo un bloque entero, no solo una serie; tiene que añadir una serie dentro del bloque donde esta"). Sirve
   para lo que se nada y el reloj no registra (no le dio tiempo a darle al boton): la repeticion nueva nace copia
   de la ultima -mismos metros, material, intensidad y tiempo, para corregirlo- y SIN intervalo del reloj, asi que
   su tiempo es el que escriba el atleta. Un bloque continuo (una sola serie) pasa a ser un bloque de series: dos
   repeticiones, su cada y su total. */
function anadirSerie(s, i) {
  const g = s.grupos[i];
  if (!g) return;
  const reps = (g.reps || []).slice();
  const ultima = reps.length ? reps[reps.length - 1] : null;
  const metros = Math.round(Number((ultima && ultima.dist_m) || g.rep_m || g.metros) || 0);
  const segundos = Number((ultima && (ultima.timer_s || ultima.tiempo_s)) || g.tiempo_s) || 0;
  if (!metros && !segundos) return;          /* sin metros ni tiempo no hay nada que copiar */
  g.reps = reps.concat([{
    dist_m: metros || null, timer_s: segundos || null, tiempo_s: segundos || null,
    ritmo_100: metros && segundos ? ritmoDe(metros, segundos) : null,
    lap_idx: null, brazadas: null, swolf_apuntado: ultima ? ultima.swolf_apuntado : null,
    material_apuntado: ultima ? ultima.material_apuntado : null,
    intensidad: (ultima && ultima.intensidad) || g.intensidad || "",
    /* Su tiempo es el que escriba el atleta: no hay reloj que lo respalde. */
    tiempo_apuntado: segundos ? crono(segundos) : null,
  }]);
  g.n_reps = g.reps.length;
  g.metros = g.reps.reduce((t, r) => t + (Number(r.dist_m) || 0), 0) || g.metros;
  g.tiempo_s = g.reps.reduce((t, r) => t + (Number(r.tiempo_s) || Number(r.timer_s) || 0), 0) || g.tiempo_s;
  g.rep_m = distanciaComunDeReps(g);
  g.ritmo_100 = g.metros && g.tiempo_s ? ritmoDe(g.metros, g.tiempo_s) : g.ritmo_100;
  g.total_s = null;                          /* el total del bloque lo rehace el front con la repeticion nueva */
  if (g.tipo === "continuo") g.tipo = "serie";   /* una serie sola mas otra ya no es continuo */
  g.avisos = ["Serie añadida a mano: el reloj no la vio. El tiempo esta puesto igual que el de la ultima "
              + "repeticion: corrigelo si no fue asi."];
  repintarDetalle();
}

/* --- una sesion entera --- */

/* Si esa sesion ya tiene un parte guardado (aun sin subir), se repone lo apuntado sobre la propuesta del reloj:
   asi se corrige sin volver a marcar material, intensidad y SWOLF desde cero. */
/* Lo que hay guardado en el navegador es de cuando se guardo. Si el tiempo guardado es exactamente el que marcaba
   el reloj, no es una correccion del atleta (nadie escribe su tiempo con las centesimas del reloj): asi que no se
   repone por encima del motor, que si puede traer una correccion suya apuntada en la base. Si el atleta escribio
   un tiempo distinto del reloj, ese manda y se repone como siempre. */
const esElTiempoDelReloj = (suyo, reloj) => Number(reloj) > 0 && Math.abs(Number(suyo) - Number(reloj)) < 0.05;

function reponerApuntado(s) {
  if (s._repuesto) return;
  const g0 = leerPartes().filter((p) => String(p.actividad_id) === String(s.actividad_id))[0];
  if (!g0) { s._repuesto = true; return; }
  /* De quien era la sesion: tambien se repone. */
  if (g0.compania) s.compania = g0.compania;
  (s.grupos || []).forEach((g, i) => {
    const primer = String((g.laps || [])[0]);
    const ap = (g0.series || []).filter((x) => primer && String((x.laps || [])[0]) === primer)[0]
      || (g0.series || [])[i];
    if (!ap) return;
    g.material = (ap.material || []).filter((m) => m && m !== "brazo_libre");
    if (ap.intensidad) g.intensidad = ap.intensidad;
    if (ap.estilo) g.estilo = ap.estilo;
    if (ap.nota) g.nota = ap.nota;
    /* Y la prueba de medicion que marco: tambien es suya. */
    if (ap.prueba) g.prueba = ap.prueba;
    /* El tiempo que el atleta corrigio tambien vuelve: si no, al reabrir se ve el del reloj y parece que la
       correccion no se guardo. */
    if (ap.tiempo_s !== undefined && ap.tiempo_s !== null
        && !esElTiempoDelReloj(ap.tiempo_s, (g.reps || [])[0]
             && ((g.reps || [])[0].lap_del_reloj_s || (g.reps || [])[0].tiempo_del_reloj_s))) {
      g.tiempo_s = +ap.tiempo_s;
      g.tiempo_apuntado = crono(g.tiempo_s);
      g.ritmo_100 = g.metros ? ritmoDe(g.metros, g.tiempo_s) : g.ritmo_100;
    }
    if (ap.cada_s !== undefined && ap.cada_s !== null) {
      g.cada_s = +ap.cada_s;
      /* Si lo escribio el, vuelve como suyo y tal cual lo escribio; si lo puso el programa, vuelve deducido. */
      g.cada_apuntado = ap.cada_apuntado || null;
      g.cada_deducido = ap.cada_apuntado ? false : (ap.cada_deducido !== false);
    }
    (g.reps || []).forEach((r) => {
      const suya = (ap.reps || []).filter((x) => String(x.lap) === String(r.lap_idx))[0];
      if (!suya) return;
      if (suya.dist_m) {
        r.dist_m = +suya.dist_m;
        r.ritmo_100 = r.tiempo_s ? ritmoDe(r.dist_m, r.tiempo_s) : r.ritmo_100;
      }
      if (suya.tiempo_s !== undefined && suya.tiempo_s !== null
          && !esElTiempoDelReloj(suya.tiempo_s, r.lap_del_reloj_s || r.tiempo_del_reloj_s)) {
        r.tiempo_s = +suya.tiempo_s;
        r.tiempo_apuntado = crono(r.tiempo_s);
        r.ritmo_100 = r.dist_m ? ritmoDe(r.dist_m, r.tiempo_s) : r.ritmo_100;
      }
      if (suya.intensidad) r.intensidad = suya.intensidad;
      if (suya.swolf !== undefined && suya.swolf !== null) r.swolf_apuntado = suya.swolf;
      if (suya.material) r.material_apuntado = suya.material;
    });
  });
  /* Y si el parte guardado reagrupa (una serie partida a mano, dos grupos juntados) manda su lista. */
  rehacerSegunParte(s, g0);
}

/* Rehace los grupos del reloj con los del parte guardado, cuando el atleta los cambio a mano (partir una serie
   en 2x50, juntar dos, quitar uno). Solo se hace si unos y otros cubren **los mismos intervalos del reloj**:
   si no, es otro parte y no se toca nada. Los numeros (metros y tiempos) siguen saliendo del reloj; del parte
   guardado se toman la forma (cuantos trozos y de que metros) y lo que el atleta escribio. */
function rehacerSegunParte(s, g0) {
  const guardados = (g0.series || []).filter((x) => x && x.no_cuenta !== true);
  const mios = (s.grupos || []).filter((g) => g && g.no_cuenta !== true);
  if (!guardados.length || !mios.length) return false;
  const clave = (laps) => laps.map(String).sort().join(",");
  const intervalos = (gs) => clave([].concat.apply([], gs.map((g) => g.laps || [])));
  const suyos = intervalos(guardados), del_reloj = intervalos(mios);
  if (!suyos || suyos !== del_reloj) return false;
  const porLap = {};
  mios.forEach((g) => (g.reps || []).forEach((r) => {
    if (r.lap_idx !== undefined && r.lap_idx !== null) porLap[String(r.lap_idx)] = r;
  }));
  s.grupos = guardados.map((x) => {
    const laps = (x.laps || []);
    /* Lo que el atleta corrigio repeticion a repeticion (distancia, tiempo, intensidad, SWOLF y material) viaja
       en el parte guardado, asi que se aplica encima de lo que midio el reloj: si no, al reabrir se perderia. */
    const suyos = {};
    (x.reps || []).forEach((r) => {
      if (r && r.lap !== undefined && r.lap !== null) suyos[String(r.lap)] = r;
    });
    const reps = laps.map((l) => {
      const r = porLap[String(l)];
      if (!r) return null;
      const suyo = suyos[String(l)];
      const rep = Object.assign({}, r);
      if (!suyo) return rep;
      if (suyo.dist_m) rep.dist_m = +suyo.dist_m;
      if (suyo.tiempo_s !== undefined && suyo.tiempo_s !== null
          && !esElTiempoDelReloj(suyo.tiempo_s, rep.lap_del_reloj_s || rep.tiempo_del_reloj_s)) {
        rep.tiempo_s = +suyo.tiempo_s;
        rep.tiempo_apuntado = crono(rep.tiempo_s);
      }
      if (rep.dist_m && rep.tiempo_s) rep.ritmo_100 = ritmoDe(rep.dist_m, rep.tiempo_s);
      if (suyo.intensidad) rep.intensidad = suyo.intensidad;
      if (suyo.swolf !== undefined && suyo.swolf !== null) rep.swolf_apuntado = suyo.swolf;
      if (suyo.material) rep.material_apuntado = suyo.material;
      return rep;
    }).filter((r) => r);
    /* Las repeticiones que el atleta añadio a mano (el reloj no las vio) no tienen intervalo del reloj: se
       devuelven tal cuales al final del bloque, con su tiempo. Si no, al reabrir el parte se perderia lo que
       escribio y el bloque diria una serie de mas con la fila en blanco. */
    (x.reps || []).forEach((r) => {
      if (!r || (r.lap !== undefined && r.lap !== null)) return;
      const seg = (r.tiempo_s !== undefined && r.tiempo_s !== null) ? +r.tiempo_s : null;
      reps.push({
        dist_m: r.dist_m ? +r.dist_m : null, timer_s: seg, tiempo_s: seg,
        ritmo_100: r.dist_m && seg ? ritmoDe(+r.dist_m, seg) : null,
        lap_idx: null, brazadas: null, swolf_apuntado: r.swolf || null,
        material_apuntado: r.material || null, intensidad: r.intensidad || "",
        tiempo_apuntado: r.tiempo_apuntado || (seg ? crono(seg) : null),
      });
    });
    /* Los metros del grupo son los que se guardaron (repeticiones x distancia): si el atleta corrigio la
       distancia, el reloj no manda sobre eso. Las repeticiones del reloj solo se usan si no hay distancia. */
    const metros = (x.rep_m && x.n_reps) ? (+x.rep_m * +x.n_reps)
      : (reps.length ? reps.reduce((t, r) => t + (r.dist_m || 0), 0) : (+x.metros || 0));
    /* El tiempo guardado en el parte manda: es el que el atleta vio y corrigio. Solo si no lo hay se suma lo
       que midio el reloj. Y si lo guardado es exactamente el tiempo del reloj, no es una correccion suya (nadie
       escribe las centesimas del reloj): manda la suma de lo que hay ahora, que ya trae la correccion de la base. */
    const segundos = reps.length ? reps.reduce((t, r) => t + (r.timer_s || 0), 0) : null;
    const guardado = (x.tiempo_s !== undefined && x.tiempo_s !== null) ? +x.tiempo_s : null;
    const delReloj = (reps[0] && Number(reps[0].lap_del_reloj_s || reps[0].tiempo_del_reloj_s || 0)) || 0;
    const tiempo = (guardado !== null && !esElTiempoDelReloj(guardado, delReloj)) ? guardado : (segundos || guardado);
    return {
      tipo: x.tipo || "serie", rep_m: x.rep_m, n_reps: x.n_reps || reps.length || 1, metros: metros,
      tiempo_s: tiempo,
      ritmo_100: metros && tiempo ? Math.round((100 * tiempo) / metros * 10) / 10 : (x.ritmo_100 || null),
      descanso_s: x.descanso_s, cada_s: x.cada_s, cada_apuntado: x.cada_apuntado || null,
      cada_deducido: x.cada_apuntado ? false : (x.cada_deducido !== false), estilo: x.estilo || null, brazadas_m: null,
      laps: laps.slice(), reps: reps, avisos: [], intensidad_sugerida: x.intensidad_sugerida,
      motivo_intensidad: null, material: (x.material || []).filter((m) => m && m !== "brazo_libre"),
      intensidad: x.intensidad || "", nota: x.nota || "",
      /* La prueba de medicion que el atleta marco en el bloque: vuelve al reabrir el parte. */
      prueba: x.prueba || null,
    };
  });
  return true;
}

/* --- lo que dice el sistema de esta sesion --------------------------------------- */

/* Lo trae el cuadro de mando (`partes.valoraciones`), por actividad y tambien por fecha. */
function valoracionDe(s) {
  const ev = (PPA() && PPA().valoraciones) || {};
  return ev[String(s.actividad_id)] || (s.fecha ? ev[s.fecha] : null) || null;
}

const TONO_VALOR = { cumplida: "ok", a_medias: "a", cambiada: "a", hecha: "ok", propia: "", cumplido: "ok",
                     corto: "a", floja: "malo", pasado: "malo", sin_parte: "a", sin_intervalos: "" };

function cajaValoracion(v) {
  const caja = el("div", { clase: "valoracion" });
  caja.appendChild(el("div", { clase: "fila entre" }, [
    el("strong", { texto: "Como lo ve el sistema" }),
    el("span", { clase: "chips", html: chip(v.etiqueta || v.estado || "", TONO_VALOR[v.estado] || "")
      + (v.plan ? chip("plan " + entero(v.plan) + " m") : "") + (v.hecho ? chip("hecho " + entero(v.hecho) + " m") : "") }),
  ]));
  if (v.titulo) caja.appendChild(el("p", { clase: "mini-txt", html: "<b>" + esc(v.titulo) + "</b>" }));
  if (v.resumen) caja.appendChild(el("p", { clase: "mini-txt valor-texto", texto: v.resumen }));
  (v.detalle || []).forEach((d) => {
    caja.appendChild(el("div", { clase: "linea-valor" }, [
      el("span", { clase: "punto " + (TONO_VALOR[d.estado] || "") }),
      el("span", { html: "<b>" + esc(d.que || "") + "</b>" + (d.nota ? " <span class='gris'>" + esc(d.nota) + "</span>" : "") }),
    ]));
  });
  return caja;
}

/* El parte que ya esta en la base: se enseña tal como quedo, con la valoracion arriba. */
function parteSubidoDe(actividad_id, fecha) {
  const lista = PPA().partes || [];
  const porId = lista.filter((p) => p.actividad_id !== null && p.actividad_id !== undefined
    && String(p.actividad_id) === String(actividad_id))[0];
  if (porId) return porId;
  return (fecha ? lista.filter((p) => p.fecha === fecha)[0] : null) || null;
}

function pintarParteSubido(p) {
  const art = el("article", { clase: "semana" });
  const nota = p.notas || p.nota || "";
  art.appendChild(el("header", {}, [
    el("div", { html: "<b>" + esc(fechaCorta(p.fecha)) + "</b> <span class='gris mini-txt'>parte subido a la base"
      + (nota ? " · " + esc(nota) : "") + "</span>" }),
    el("div", { clase: "chips", html: chip(entero(p.metros) + " m") + chip((p.series || []).length + " grupos") }),
  ]));
  const val = valoracionDe(p);
  if (val) art.appendChild(cajaValoracion(val));
  const cuerpo = el("div", { clase: "semana-cuerpo" });
  (p.series || []).forEach((g) => {
    /* Las repeticiones del reloj, no solo las correcciones del atleta: un bloque juntado a mano no guarda
       repeticiones propias (su JSON va vacio) y sin esto se quedaba sin SWOLF y sin distancia por repeticion. */
    const susReps = (g.reps && g.reps.length) ? g.reps : (g.reps_reloj || []);
    const swolfs = susReps.map((r) => r.swolf || r.swolf_apuntado).filter((x) => x);
    const chips = (g.material || []).map((m) => chip(NOMBRE_MATERIAL[m] || m)).join("")
      + (g.intensidad ? chip(nombreIntensidad(g.intensidad)) : "")
      + (swolfs.length ? chip("SWOLF " + swolfs.join(", ")) : "");
    cuerpo.appendChild(el("div", { clase: "grupo" }, [
      el("div", { clase: "grupo-cab", html: "<span><b>" + etiquetaGrupo(g) + "</b> "
        + (g.ritmo_100 ? '<span class="gris">' + ritmo100(g.ritmo_100) + "</span>" : "") + "</span>"
        + '<span class="gris mini-txt">' + entero(g.metros) + " m \u00b7 " + cronoVerbal(totalConDescansos(g))
        + "</span>" }),
      el("div", { clase: "chips mt", html: chips || chip("brazo libre") }),
      (g.nota ? el("p", { clase: "ayuda", texto: g.nota }) : null),
    ]));
  });
  art.appendChild(cuerpo);
  return art;
}

/* --- de quien era la sesion: la del entrenador del equipo o la de uno mismo ----------------------- */

/* Los lunes, miercoles y viernes entrena con el entrenador del equipo y hace lo que le mandan: esas sesiones
   no se programan ni se corrigen, se apuntan. Saber de quien es cada sesion separa "lo que me han mandado" de
   "lo que me he hecho yo" al analizar. */
const NOMBRE_COMPANIA = {};
function nombreCompania(v) {
  if (!Object.keys(NOMBRE_COMPANIA).length) {
    (PPA().companias || []).forEach((i) => { NOMBRE_COMPANIA[i.valor] = i.nombre; });
  }
  return NOMBRE_COMPANIA[v] || v;
}

function cajaCompania(s) {
  const base = "comp" + s.actividad_id;
  const caja = el("div", { clase: "fila", style: "gap:11px;align-items:center;margin:0 0 10px" });
  caja.appendChild(el("span", { clase: "etiqueta-mini", texto: "Esta sesion fue" }));
  (PPA().companias || []).forEach((c) => {
    const id = base + c.valor;
    const inp = el("input", { type: "radio", name: base, id: id, value: c.valor });
    if (s.compania === c.valor) inp.checked = true;
    /* Se guarda al elegirlo (sin aviso): es una marca de la sesion, no un dato que haya que subir a mano. */
    inp.addEventListener("change", () => { s.compania = c.valor; guardarParte(s, true); });
    caja.appendChild(el("label", { for: id }, [inp, document.createTextNode(c.nombre)]));
  });
  if (!s.compania) caja.appendChild(el("span", { clase: "gris mini-txt", texto: "· sin marcar" }));
  return caja;
}

function pintarSesion(s) {
  s.grupos = s.grupos || [];
  reponerApuntado(s);
  const art = el("article", { clase: "semana", style: "margin-bottom:14px" });
  art.appendChild(el("header", {}, [
    el("div", { html: "<b>" + esc(fechaCorta(s.fecha)) + "</b> <span class='gris mini-txt'>" + esc(s.hora)
      + (s.nombre ? " · " + esc(s.nombre) : "") + "</span>" }),
    el("div", { clase: "chips", html: chip(entero(s.metros) + " m") + chip("piscina " + entero(s.piscina_m) + " m")
      + chip(s.n_intervalos + " intervalos") + (s.compania ? chip(nombreCompania(s.compania)) : "")
      + (s.sensacion !== null && s.sensacion !== undefined ? chip("sensacion " + de0a5(s.sensacion) + " /5") : "")
      + (s.rpe ? chip("RPE " + entero(s.rpe)) : "") + (s.fc_media ? chip("pulso " + entero(s.fc_media)) : "") }),
  ]));

  /* Los botones van arriba del todo: lo primero que se ve al abrir la sesion. */
  const cajaEval = cajaEntrenador(s.actividad_id);
  art.appendChild(el("div", { clase: "acciones-parte" }, [
    el("button", { clase: "boton principal", type: "button", html: icono("mas") + "Guardar el parte", onclick: () => guardarParte(s) }),
    el("button", { clase: "boton", type: "button", html: icono("subir") + "Subir", onclick: () => subirParte(s) }),
    el("button", { clase: "boton", type: "button", id: "evalSesion" + s.actividad_id,
                   html: icono("parte") + "Que lo evalue el entrenador",
                   onclick: (ev) => evaluarSesion(s.actividad_id, cajaEval, ev.currentTarget) }),
    el("span", { clase: "ayuda", "data-aviso": s.actividad_id }),
  ]));
  art.appendChild(cajaEval);

  const val = valoracionDe(s);
  if (val) art.appendChild(cajaValoracion(val));

  const cuerpo = el("div", { clase: "semana-cuerpo" });
  cuerpo.appendChild(cajaCompania(s));
  if (!s.grupos.length) cuerpo.appendChild(el("div", { clase: "vacio", html: "<strong>Sin intervalos</strong>El reloj no trae intervalos con metros en esta sesion." }));
  s.grupos.forEach((g, i) => cuerpo.appendChild(pintarGrupo(s, i)));

  const utiles = s.grupos.filter((g) => g.no_cuenta !== true);
  /* Ojo: el material que no se marca NO es un hueco que falte. No marcar material es que ese grupo se nado
     sin objetos (brazo libre), que es lo que el atleta hace la mayoria de las veces. Lo unico que hay que
     decir de un grupo es su intensidad. */
  const sinIntensidad = utiles.filter((g) => !g.intensidad).length;
  const pie = el("div", { clase: "fila entre mt" }, [
    el("span", { clase: "ayuda", texto: utiles.length + " grupos · " + (sinIntensidad ? sinIntensidad + " sin decir la intensidad" : "todos con su intensidad"),
                 title: "Si un grupo no lleva material marcado es que se nado sin objetos: eso no hay que marcarlo." }),
  ]);
  cuerpo.appendChild(pie);
  art.appendChild(cuerpo);
  return art;
}

function avisoParte(texto, actividad_id) {
  const caja = $$('[data-aviso="' + (actividad_id === undefined ? "" : actividad_id) + '"]')[0];
  if (!caja) return;
  if (caja._timer) clearTimeout(caja._timer);
  caja.textContent = texto;
  if (texto) caja._timer = setTimeout(() => { caja.textContent = ""; caja._timer = null; }, 6000);
}

function guardarParte(s, sin_aviso, sin_repintar) {
  const utiles = (s.grupos || []).filter((g) => g.no_cuenta !== true);
  if (!utiles.length) { avisoParte("No hay ningun grupo que guardar.", s.actividad_id); return; }
  /* Lo que falta de verdad es la intensidad: el material sin marcar es nadar sin objetos. */
  const sinIntensidad = utiles.filter((g) => !g.intensidad).length;
  const minutos = Math.round(utiles.reduce((t, g) => t + (g.tiempo_s || 0), 0) / 60);
  const parte = {
    fecha: s.fecha, actividad_id: s.actividad_id, piscina_m: s.piscina_m, metros: Math.round(utiles.reduce((t, g) => t + (g.metros || 0), 0)),
    minutos: minutos, sensacion: s.sensacion, notas: s.notas || "", compania: s.compania || null,
    series: utiles.map((g) => ({
      tipo: g.tipo, rep_m: g.rep_m, n_reps: g.n_reps, metros: g.metros, tiempo_s: g.tiempo_s,
      /* El cada solo viaja si lo escribio el atleta (el que deduce el servidor de las horas del reloj es mejor y
         se guarda en la base); `cada_apuntado` lo marca como suyo para volver a enseñarlo como suyo al reabrir. */
      ritmo_100: g.ritmo_100, descanso_s: g.descanso_s, cada_s: g.cada_apuntado ? g.cada_s : null,
      cada_apuntado: g.cada_apuntado || null, estilo: g.estilo,
      material: g.material.slice(), intensidad: g.intensidad, nota: g.nota || "", laps: g.laps || [],
      /* La prueba de medicion que el atleta marco en este bloque, si la hay: viaja con el y se guarda en la base. */
      prueba: g.prueba || null,
      /* Lo que cambia de una repeticion a otra: intensidad suelta y el SWOLF que ha medido. */
      reps: (g.reps || []).map((r) => {
        const fila = { lap: r.lap_idx };
        /* La distancia corregida de una repeticion viaja con ella: el reloj no la puede reponer. */
        if (r.dist_m) fila.dist_m = Math.round(Number(r.dist_m));
        if (r.intensidad) fila.intensidad = r.intensidad;
        if (r.swolf_apuntado !== undefined && r.swolf_apuntado !== null && r.swolf_apuntado !== "") fila.swolf = Number(r.swolf_apuntado);
        if (r.material_apuntado) fila.material = r.material_apuntado;
        /* El tiempo que el atleta le corrige a esa repeticion: se manda en segundos para que llegue al lap. */
        if (r.tiempo_apuntado && r.tiempo_s) fila.tiempo_s = r.tiempo_s;
        return fila;
      }).filter((f) => f.intensidad || f.swolf || f.material || f.tiempo_s),
    })),
  };
  const lista = leerPartes().filter((p) => String(p.actividad_id) !== String(s.actividad_id));
  lista.push(parte);
  almacen.guardar(CLAVES.partes, lista);
  /* Ojo: repintar el detalle vuelve a guardar (el detalle se guarda solo), asi que quien llame desde ahi tiene
     que pedir que no se repinte, o se llaman en bucle hasta reventar. */
  if (!sin_repintar) repintarDetalle();
  pintarEntrenos();          /* la lista de entrenamientos tiene que decir ya que este parte esta hecho */
  if (!sin_aviso) avisoParte(sinIntensidad ? "Guardado (quedan " + sinIntensidad + " grupos sin decir la intensidad)." : "Guardado.", s.actividad_id);
}

/* --- subir a la base --------------------------------------------------- */

/* El portal es un fichero suelto y no puede escribir en la base por su cuenta: se lo manda al servidor local
   (orden `servir`, que se levanta con servir-entrenador.bat). Si no esta, se dice en una linea y ya esta. */
const SUBIDA = urlApi("partes");

function subirParte(s) {
  guardarParte(s, true);
  const parte = leerPartes().filter((p) => String(p.actividad_id) === String(s.actividad_id))[0];
  if (!parte) { avisoParte("No encuentro el parte de esta sesion: dale antes a Guardar el parte.", s.actividad_id); return; }
  avisoParte("Subiendo el parte a la base...", s.actividad_id);
  fetch(SUBIDA, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ partes_natacion: [parte] }),
  })
    .then((r) => r.text().then((t) => ({ ok: r.ok, estado: r.status, t })))
    .then(({ ok, estado, t }) => {
      let d = {};
      try { d = JSON.parse(t) || {}; } catch (e) { d = {}; }
      if (!ok || d.ok === false) {
        avisoParte("El servidor ha respondido con un problema (" + estado + "): "
          + (d.error || String(t || "").slice(0, 140) || "sin detalle"), s.actividad_id);
        return;
      }
      /* Ya esta en la base: fuera de la lista del navegador, para no subirlo dos veces. */
      const l = leerPartes().filter((p) => String(p.actividad_id) !== String(s.actividad_id));
      almacen.guardar(CLAVES.partes, l);
      avisoParte("Subido a la base. " + entero(parte.metros) + " m en " + (parte.series || []).length
        + " grupos." + (d.recargar ? " Actualizando el cuadro..." : ""), s.actividad_id);
      /* El servidor rehace el cuadro con el parte ya dentro: al recargar, la sesion vuelve a abrirse sola
         (con su parte y la valoracion) y aparece en "Partes que ya constan". */
      if (d.recargar) setTimeout(() => location.reload(), 1200);
      else repintarDetalle();
    })
    .catch(() => {
      avisoParte("No hay ningun servidor al otro lado. Doble clic en servir-entrenador.bat (deja su ventana "
        + "abierta) y vuelve a darle a Subir: lo que has marcado no se pierde.", s.actividad_id);
    });
}

/* La bandeja de \"partes sin subir\" ya no se pinta: el boton Subir manda el parte a la base. Solo queda el
   contador de sesiones que esperan el parte, en el menu. */
function pintarPartesLista() {
  pintar("cEntrenos", (PPA().pendientes || []).length || "");
}

/* --- lo que ya consta y con que se compara --- */

function pintarCortes(cortes) {
  if (!cortes.length) {
    pintar("parteCortes", '<div class="vacio"><strong>Sin historico</strong>Todavia no hay suficientes intervalos medidos para marcar cortes.</div>');
    return;
  }
  pintar("parteCortes", tablaHTML([{ n: "Tipo de bloque" }, { n: "Distancia", num: true }, { n: "Veces", num: true }, { n: "Rapido", num: true }, { n: "Mediana", num: true }, { n: "Lento", num: true }],
    cortes.map((c) => [esc(c.tipo === "continuo" ? "seguido" : "serie"), entero(c.dist_m) + " m", entero(c.n),
      ritmo100(c.p25), ritmo100(c.p50), ritmo100(c.p75)]), { compacta: true })
    + '<p class="ayuda mt">Con esto se propone la intensidad de cada grupo: por debajo del rapido es AeIntenso, entre rapido y mediana AeMedio, entre mediana y lento AeLigero y por encima del lento, calentamiento o recuperar. Tu historico, en brazo libre.</p>');
}

function pintarPartesImportados(partes) {
  pintar("parteImportados", tablaHTML([{ n: "Fecha" }, { n: "Metros", num: true }, { n: "Grupos", num: true }, { n: "Con material", num: true }, { n: "Grupos del parte" }],
    partes.map((p) => ["<span class='ahora'>" + esc(fechaCorta(p.fecha)) + "</span>", entero(p.metros), (p.series || []).length,
      (p.series || []).filter((s) => (s.material || []).length).length,
      "<span class='gris'>" + esc((p.series || []).map((s) => (s.tipo === "continuo" || !s.rep_m ? entero(s.metros) + "m" : s.n_reps + "x" + entero(s.rep_m))
        + " " + ((s.material || []).map((m) => NOMBRE_MATERIAL[m] || m).join("+") || "brazo libre")).join(" · ")) + "</span>"]),
    { compacta: true, vacio: "Todavia no se ha importado ningun parte." }));
}

/* --- como va el plan (la evaluacion) --- */

const CLASE_ESTADO = { cumplida: "cumplida", a_medias: "a_medias", floja: "floja", cambiada: "cambiada", sin_parte: "sin_parte", pendiente: "pendiente", no_hecha: "floja", descanso: "descanso" };
const NOMBRE_ESTADO = { cumplida: "Cumplida", a_medias: "A medias", floja: "Floja", cambiada: "Cambiada", sin_parte: "Sin parte", pendiente: "Pendiente", no_hecha: "No hecha", descanso: "Descanso / entrenador" };

function pintarEvaluacion() {
  const ev = EVA();
  pintar("evalPista", ev.cortes || "");
  const caja = q("evalSemanas");
  if (!caja) return;
  caja.innerHTML = "";
  const semanas = ev.semanas || [];
  if (!semanas.length) { caja.innerHTML = '<div class="vacio"><strong>Sin semanas evaluables</strong>El plan empieza el 12/10/2026.</div>'; return; }
  semanas.forEach((s) => {
    const c = s.cumplimiento;
    const km = (s.km_plan ? s.km_plan + " km de plan" : "") + (s.km_hecho ? " · " + dec(s.km_hecho, 1) + " km hechos" : "");
    const art = el("article", { clase: "semana", style: "margin-bottom:14px" });
    art.appendChild(el("header", {}, [
      el("div", { html: "<b>" + esc(s.clave) + "</b> <span class='gris mini-txt'>" + esc(fechaCorta(s.desde)) + " a " + esc(fechaCorta(s.hasta)) + " · " + esc(s.foco || "") + "</span>" }),
      el("div", { clase: "chips", html: chip(km) + chip(s.sesiones_hechas + " de " + s.sesiones_plan + " sesiones nuestras")
        + (c === null || c === undefined ? "" : chip(Math.round(c * 100) + "% de cumplimiento", c >= 0.9 ? "ok" : (c >= 0.6 ? "a" : ""))) }),
    ]));
    const cuerpo = el("div", { clase: "semana-cuerpo" });
    cuerpo.appendChild(el("div", { html: tablaHTML([{ n: "Dia" }, { n: "Que tocaba" }, { n: "Como fue" }, { n: "Metros", num: true }],
      (s.sesiones || []).map((v) => {
        const detalles = (v.resumen || "").split("\n").filter(Boolean).map((x) => esc(x)).join("<br>");
        return ["<span class='ahora'>" + esc(fechaCorta(v.fecha)) + "</span>", esc(v.titulo || ""),
          "<span class='estado " + (CLASE_ESTADO[v.estado] || "") + "'>" + esc(NOMBRE_ESTADO[v.estado] || v.estado) + "</span>"
          + (detalles ? "<div class='ayuda' style='margin-top:5px'>" + detalles + "</div>" : ""),
          entero(v.metros_hechos)];
      }), { compacta: true }) }));
    const a = s.ajuste || {};
    const kmp = a.km_propuestos ? " → " + a.km_propuestos + " km" : "";
    cuerpo.appendChild(el("div", { clase: "aviso-ajuste", html:
      "<b>Ajuste que sale del parte: " + esc(String(a.accion || "").replace(/_/g, " ")) + kmp + "</b>"
      + (a.motivos || []).map((m) => "<div class='ayuda'>· " + esc(m) + "</div>").join("") }));
    art.appendChild(cuerpo);
    caja.appendChild(art);
  });
  caja.appendChild(el("p", { clase: "ayuda mt", texto: "El ajuste se propone, no se aplica: los dias del entrenador no se tocan y la semana se cambia a mano cuando tu lo digas." }));
}

/* --- arranque de la vista --- */

/* --- el parte sale dentro de la sesion que se pincha en Entrenamientos --- */

let sesionAbierta = null; /* actividad_id del parte que esta abierto */
let repintandoDetalle = false; /* se esta repintando el detalle ahora mismo? entonces no vuelvas a entrar */

function sesionDe(actividad_id) {
  /* La sesion con desglose: la que falta por rellenar (la propuesta del reloj) o, si ya tiene parte, esa
     misma sesion con lo que el atleta guardo. Antes solo valian las que faltaban, asi que en cuanto el parte
     constaba en la base la sesion se abria sin el desglose: solo salia la cabecera del parte. */
  const id = String(actividad_id);
  const listas = (PPA().pendientes || []).concat(PPA().con_parte || []);
  return listas.filter((s) => String(s.actividad_id) === id)[0] || null;
}

function abrirParte(actividad_id, fecha, saltar) {
  const caja = q("entrenosCajaParte"), cont = q("entrenosDetalle");
  if (!caja || !cont) return;
  const id = String(actividad_id);
  const s = sesionDe(id);
  sesionAbierta = id;
  try { sessionStorage.setItem("parteAbierto", id); } catch (e) {}
  caja.hidden = false;
  pintar("entrenosPartePista", s ? fechaCorta(s.fecha) + " · " + entero(s.metros) + " m · " + (s.n_intervalos || 0) + " intervalos" : (fecha ? fechaCorta(fecha) : ""));
  cont.innerHTML = "";
  if (s) {
    cont.appendChild(pintarSesion(s));
  } else {
    const ya = parteSubidoDe(id, fecha);
    if (ya) {
      cont.appendChild(pintarParteSubido(ya));
    } else {
      cont.innerHTML = '<div class="vacio"><strong>Sin intervalos que agrupar</strong>El reloj no trae intervalos con metros en esta sesion.</div>';
    }
  }
  /* Solo se baja la vista la primera vez que se abre. Al repintar (guardar, juntar, quitar) no se mueve nada. */
  if (saltar !== false) caja.scrollIntoView({ block: "start" });
}

/* Donde esta mirando el atleta: lo desplazado de la ventana y de todo lo que tenga scroll (el detalle de una
   sesion vive dentro de un contenedor con scroll). Repintar el detalle cambia el DOM entero y el navegador deja
   la vista arriba, asi que el atleta se pierde cuando parte o junta un bloque ("cada vez que pulso partir con
   intervalos o juntar se me va el scroll y no se donde estoy"): se apunta antes y se devuelve despues. */
function apuntarElSitio() {
  const sitios = [];
  Array.prototype.forEach.call(document.querySelectorAll("*"), (n) => { if (n.scrollTop) sitios.push([n, n.scrollTop]); });
  return { sitios: sitios, ventana: window.pageYOffset || 0 };
}

function devolverElSitio(sitio) {
  (sitio.sitios || []).forEach(([n, t]) => { n.scrollTop = t; });
  if (sitio.ventana) window.scrollTo(0, sitio.ventana);
}

/* Repinta el parte abierto sin perder lo que se lleva apuntado (junta, parte, quita o guarda). */
function repintarDetalle() {
  if (repintandoDetalle) return;   /* la red de seguridad contra llamarse en bucle */
  repintandoDetalle = true;
  const sitio = apuntarElSitio();
  try {
    /* Lo que se cambia en el detalle de una sesion se guarda solo, sin tener que darle a "Guardar el parte":
       asi no se pierde un tiempo corregido por cerrar la ventana. El boton sigue siendo el que deja el parte
       listo (y el que avisa de lo que falta); "Subir" es el que lo manda a la base. */
    if (sesionAbierta !== null) {
      const s = sesionDe(sesionAbierta);
      if (s) guardarParte(s, true, true);   /* sin repintar: lo hace esta misma funcion al final */
    }
    if (sesionAbierta !== null) abrirParte(sesionAbierta, null, false);
    pintarPartesLista();
  } finally {
    devolverElSitio(sitio);
    repintandoDetalle = false;
  }
}

/* Lo que el sistema ha aprendido de sus propios partes: cuanto bailan los tiempos y hasta cuanto descanso
   sigue siendo la misma serie. Con eso agrupa las repeticiones y mide la forma de cada bloque, asi que cuanto
   mas sube, mejor agrupa. Se enseña aqui para que se vea de donde salen los numeros. */
function pintarAprendizaje() {
  const a = PPA().aprendizaje || {};
  if (!a.generado) {
    pintar("parteAprendizaje", '<div class="vacio"><strong>Todavia no ha medido nada</strong>Sube algun '
      + 'entrenamiento con su parte y el sistema empezara a aprender de tus tiempos.</div>');
    return;
  }
  pintar("aprendizajePista", "medido el " + esc(fechaCorta(String(a.generado).slice(0, 10)))
    + " con " + entero(a.bloques) + " bloques de " + entero(a.partes) + " partes");
  const filas = [
    ["Cuanto bailan los tiempos", dec(a.margen_s_100, 1) + " s/100",
      "Una repeticion cuenta como mas rapida o mas lenta que la anterior solo si se aparta mas de esto. "
      + "Sale de la mediana de lo que se apartan sus repeticiones de la linea del bloque"
      + (a.basado_en_bloques ? " (" + a.basado_en_bloques + " bloques medidos)" : "") + "."],
    ["Descanso de la misma serie", cronoVerbal(a.descanso_mismo_bloque_s),
      "Mientras el descanso entre dos intervalos no pase de aqui, van al mismo bloque. Es el descanso mas "
      + "largo que has usado dentro de una serie, mas un margen; nunca por encima de 3:00."],
    ["Repeticiones por serie", a.reps_por_serie ? dec(a.reps_por_serie, 0) : "sin datos",
      "Tu mediana: lo que suele durar una serie tuya."],
    ["Formas que ya ha visto", Object.keys(a.conceptos || {}).length
      ? Object.keys(a.conceptos).map((k) => esc(nombreConcepto(k).split(" (")[0]) + " (" + a.conceptos[k] + ")").join(", ")
      : "ninguna todavia",
      "La forma de cada bloque (regular, progresiva, aflojando...) se mide de los tiempos, no se marca."],
  ];
  pintar("parteAprendizaje", tablaHTML([{ n: "Lo que mide" }, { n: "Cuanto" }, { n: "De donde sale" }],
    filas.map(([a1, b1, c1]) => [esc(a1), "<span class='ahora'>" + esc(b1) + "</span>", "<span class='ayuda'>" + c1 + "</span>"]),
    { compacta: true })
    + '<p class="ayuda mt">Se vuelve a medir en cada pasada (importar un entrenamiento o subir un parte), '
    + 'asi que el margen y el descanso se ajustan solos segun lo que hagas.</p>');
}

/* Lo que no vive dentro de una sesion: la bandeja de partes sin subir, los cortes y como va el plan. */
function pintarParteYPlan() {
  pintarPartesLista();
  pintarCortes((PPA().cortes) || []);
  pintarAprendizaje();
  pintarPartesImportados(PPA().partes || []);
  pintarEvaluacion();
}


function pintarBici() {
  const b = DATOS.bici || {}, k = b.kpis || {};
  pintar("biciKpis", [
    kpi("Salidas", entero(k.salidas), "desde " + fechaCorta(k.primera), "a"),
    kpi("Kilometros", entero(k.km), "en total"),
    kpi("Desnivel", entero(k.desnivel) + " m", "acumulado"),
    kpi("Tramos del export", entero(k.segmentos), entero(k.intentos) + " intentos medidos"),
  ]);
  pintar("biciSegmentos", tablaHTML([{ n: "Tramo" }, { n: "Veces", num: true }, { n: "Km", num: true }, { n: "Mejor", num: true }, { n: "Mediana", num: true }],
    (b.segmentos || []).slice().sort((x, y) => y.veces - x.veces).map((s) => [esc(s.nombre), entero(s.veces), dec(s.dist_m / 1000, 1),
      cronoVerbal(s.mejor_s), "<span class='gris'>" + cronoVerbal(s.mediana_s) + "</span>"]), { compacta: true }));
  pintar("biciSalidas", tablaHTML([{ n: "Fecha" }, { n: "Salida" }, { n: "Km", num: true }, { n: "Tiempo", num: true }, { n: "Km/h", num: true }],
    (b.salidas || []).map((s) => ["<span class='ahora'>" + esc(fechaCorta(s.fecha)) + "</span>", esc(s.nombre), dec(s.dist / 1000, 1),
      cronoVerbal(s.dur), dec(s.vel, 1)]), { compacta: true }));
}

/* ---------- 12. Arranque ----------------------------------------------- */

function irA(nombre) {
  if (location.hash.slice(1) === nombre) mostrarVista(nombre, true); else location.hash = nombre;
  mostrarVista(nombre, true);
}

/* La valoracion del entrenador (el discurso del Resumen). No se escribe aqui: la compone Python con los datos
   reales en cada pasada de `analizar` (`entrenador/valoracion.py`) y esta funcion pinta lo que le llega. */
function pintarValoracion() {
  const v = DATOS.valoracion || {};
  if (!v.titular) {
    pintar("resumenEntrenador", "");
    return;
  }
  const parrafos = (v.parrafos || []).map((p) =>
    "<p class='ent-parrafo'><b>" + esc(p.titulo) + ".</b> " + esc(p.texto) + "</p>").join("");
  const dianas = (v.dianas || []).length
    ? "<h3 class='ent-cabeza'>Con que tiempos entrenar para el reto</h3>"
      + tablaHTML(["Serie", "Diana", "Por que"],
        (v.dianas || []).map((d) => [esc(d.serie), "<b>" + esc(d.diana) + "</b>", esc(d.porque)]), {})
    : "";
  const avisos = (v.avisos || []).length
    ? "<p class='ent-avisos mini-txt'>" + (v.avisos || []).map(esc).join(" ") + "</p>" : "";
  pintar("resumenEntrenador",
    "<header><h3>El entrenador dice</h3><span class='pista'>" + esc(fechaCorta(v.fecha))
    + (v.generado ? " \u00b7 escrito el " + esc(fechaHora(v.generado)) : "") + "</span></header>"
    + "<div class='tarjeta-cuerpo'>"
    + "<p class='ent-titular'>" + esc(v.titular) + "</p>" + parrafos + dianas + avisos + "</div>");
}

/* La foto del estado del atleta (F4). La calcula Python (`entrenador/estado.py`) y llega en
   DATOS.estado: cada metrica con n, dispersion, confianza, fuente y limitaciones. */
function pintarEstado() {
  const e = DATOS.estado || {};
  const caja = q("estadoAtleta");
  if (!caja) return;
  if (!e.secciones || !e.secciones.length) {
    caja.innerHTML = "<header><h3>Estado del atleta</h3><span class='pista'>sin foto</span></header>"
      + "<div class='tarjeta-cuerpo'><div class='vacio'><strong>Sin estado calculado</strong>"
      + esc(e.error || "No hay metricas disponibles para esta fecha.") + "</div></div>";
    return;
  }
  const valorDe = (m) => {
    if (m.estado === "sin_datos" || m.valor === null || m.valor === undefined) return "sin datos";
    const v = String(m.valor) + (m.unidad ? " " + m.unidad : "");
    return esc(v) + (m.dispersion !== null && m.dispersion !== undefined
      ? " <span class='gris mini-txt'>± " + esc(String(m.dispersion)) + "</span>" : "");
  };
  let h = "<header><h3>Estado del atleta</h3><span class='pista'>" + esc(fechaCorta(e.fecha))
    + " · " + esc(e.estado_id || "sin id") + " · " + esc(e.version_conocimiento || "sin version")
    + "</span></header><div class='tarjeta-cuerpo'>"
    + "<p class='ayuda'>Foto reproducible de lo que se sabe en esa fecha. Cada numero lleva sus observaciones "
    + "(n), su dispersion, su confianza y lo que no se puede concluir. Si no hay datos, se dice: no se rellena.</p>";
  (e.secciones || []).forEach((s) => {
    h += "<div class='etiqueta-mini'>" + esc(s.titulo) + "</div>";
    h += tablaHTML([{ n: "Metrica" }, { n: "Valor" }, { n: "n", num: true },
                    { n: "Confianza" }, { n: "Fuente y limite" }],
      (s.metricas || []).map((m) => [
        esc(m.etiqueta),
        valorDe(m),
        esc(String(m.n === undefined ? 0 : m.n)),
        chip(m.confianza || "baja", m.confianza === "alta" ? "ok" : (m.confianza === "media" ? "a" : "")),
        "<span class='gris mini-txt'>" + esc((m.fuente || []).join(", "))
          + ((m.limitaciones || []).length ? " · " + esc((m.limitaciones || []).join(" · ")) : "") + "</span>",
      ]), { compacta: true });
    (s.notas || []).forEach((n) => { h += "<p class='mini-txt'>" + esc(n) + "</p>"; });
  });
  if ((e.avisos || []).length) {
    h += "<div class='aviso mt'><strong>Avisos</strong><ul>"
      + e.avisos.map((a) => "<li>" + esc(a) + "</li>").join("") + "</ul></div>";
  }
  h += "</div>";
  caja.innerHTML = h;
}

/* F6: el bucle cerrado, en una tarjeta pequena. No calcula: pinta lo que trae DATOS.resultados. */
function pintarResultados() {
  const r = DATOS.resultados || {};
  const caja = q("resultadosBucle");
  if (!caja) return;
  if (!r.recomendaciones) {
    caja.innerHTML = "<header><h3>Resultados</h3><span class='pista'>sin propuestas</span></header>"
      + "<div class='tarjeta-cuerpo'><div class='vacio'><strong>Sin bucle de resultados</strong>"
      + esc(r.error || "Todavia no hay recomendaciones guardadas.") + "</div></div>";
    return;
  }
  const e = r.enlaces || {};
  const filas = (r.ultimos || []).slice(0, 5).map((x) => [
    esc(String(x.id)), esc(x.titulo || ""),
    esc((x.enlace || {}).estado || "sin_enlace"),
    esc((x.decision || {}).tomada || "sin decidir"),
    esc((x.verificacion || {}).veredicto || "sin evaluar"),
  ]);
  let h = "<header><h3>Resultados</h3><span class='pista'>"
    + entero(r.recomendaciones) + " propuestas · " + entero(r.evaluadas) + " evaluadas</span></header>"
    + "<div class='tarjeta-cuerpo'>"
    + "<div class='chips' style='margin-bottom:10px'>"
    + chip("enlazadas " + entero(e.enlazado || 0), "ok")
    + chip("sin enlace " + entero(e.sin_enlace || 0), "") + chip("ambiguas " + entero(e.ambiguo || 0), "")
    + chip("a favor " + entero(r.a_favor || 0), "ok") + chip("en contra " + entero(r.en_contra || 0), "no")
    + chip("sin datos " + entero(r.sin_datos || 0), "") + chip("no concluyente " + entero(r.no_concluyente || 0), "")
    + "</div>"
    + tablaHTML([{ n: "#" }, { n: "Que se propuso" }, { n: "Enlace" }, { n: "Que se hizo" }, { n: "Que paso" }],
                filas, { compacta: true })
    + "<p class='mini-txt'>No se declara causalidad: si hay confounders o faltan datos, el veredicto es "
    + "no concluyente o sin datos. Las reglas no cambian solas.</p></div>";
  caja.innerHTML = h;
}

/* El boton del Garmin: el portal le pide al servidor local que baje de Garmin Connect lo que falte. El servidor
   usa el mismo codigo que `python scripts/garmin_conectar.py traer`. Por aqui no pasa ninguna credencial: la
   sesion (token OAuth) ya esta en el disco del PC, la dejo el atleta con conectar-garmin.bat. */
const GARMIN = urlApi("garmin/traer");

function avisoGarmin(texto) {
  const caja = document.getElementById("garmAviso");
  if (!caja) return;
  caja.hidden = !texto;
  caja.textContent = texto || "";
}

function montarGarmin() {
  const boton = document.getElementById("garmTraer");
  if (boton) boton.addEventListener("click", traerDelGarmin);
  /* El boton de evaluar: "mira el ultimo entrenamiento y dime como va el plan". La caja se crea al vuelo la
     primera vez que se pincha, para no dejar huecos vacios en la pantalla. */
  const ev = document.getElementById("evalUltimo");
  if (ev) ev.addEventListener("click", () => {
    const hueco = document.getElementById("evalUltimoCaja");
    if (!hueco) return;
    if (!hueco.querySelector(".entrenador")) hueco.appendChild(cajaEntrenador("ultimo"));
    evaluarSesion(null, hueco.querySelector(".entrenador"), ev);
  });
}

function traerDelGarmin() {
  const boton = document.getElementById("garmTraer");
  if (boton && boton.disabled) return;
  if (boton) boton.disabled = true;
  avisoGarmin("Mirando en Garmin Connect... puede tardar un poco (una sesion nueva son unos segundos).");
  fetch(GARMIN, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
    .then((r) => r.text().then((t) => ({ ok: r.ok, estado: r.status, t })))
    .then(({ ok, estado, t }) => {
      let d = {};
      try { d = JSON.parse(t) || {}; } catch (e) { d = {}; }
      const detalle = String(d.error || "").toLowerCase();
      if (!ok || d.ok === false) {
        avisoGarmin("El servidor ha respondido con un problema (" + estado + "): "
          + (d.error || String(t || "").slice(0, 180) || "sin detalle")
          + (detalle.indexOf("sesion") >= 0 || detalle.indexOf("login") >= 0 || detalle.indexOf("token") >= 0
              ? "  -> doble clic en conectar-garmin.bat para renovar la sesion de Garmin." : ""));
        if (boton) boton.disabled = false;
        return;
      }
      const imp = d.importacion || {};
      let txt = d.nuevos
        ? "Ya esta en la base: " + d.nuevos + " sesion(es) nueva(s) (del " + d.desde + " al " + d.hasta
          + ", " + (imp.leidos || 0) + " ficheros leidos"
          + (imp.omitidos ? ", " + imp.omitidos + " ya estaban" : "") + ")."
        : "No hay nada nuevo en el Garmin (del " + d.desde + " al " + d.hasta + "): "
          + entero(d.traidos) + " actividad(es) miradas y todas estaban ya en la base.";
      if (d.recargar) txt += " Actualizando el cuadro...";
      avisoGarmin(txt);
      /* El servidor rehace el cuadro con lo que ha entrado: al recargar sale ya todo al dia. */
      if (d.recargar) setTimeout(() => location.reload(), 1200);
      else if (boton) boton.disabled = false;
    })
    .catch(() => {
      avisoGarmin("No hay ningun servidor al otro lado. Doble clic en servir-entrenador.bat (y deja su ventana "
        + "abierta) y vuelve a darle al boton: lo que ya tengas en la base no se toca.");
      if (boton) boton.disabled = false;
    });
}

/* ---------- El entrenador mira UN entrenamiento (el boton "Evaluar") --------
   Manda la sesion al servidor local (127.0.0.1), que compone el discurso con lo que ya hay en la base: los
   tiempos bloque a bloque (con el material descontado), la distancia, el esfuerzo que traia encima y los
   descansos; y dice como va el plan. Nada sale del PC y no toca Garmin. */
const EVALUAR = urlApi("evaluar");

function cajaEntrenador(actividad_id) {
  const caja = el("div", { clase: "valoracion entrenador", hidden: true });
  caja.appendChild(el("div", { clase: "fila entre" }, [
    el("strong", { texto: "El entrenador dice" }),
    el("span", { clase: "chips", html: chip(actividad_id ? "sesion " + entero(actividad_id) : "la ultima sesion") }),
  ]));
  caja.appendChild(el("p", { clase: "ayuda", texto: "Mirando esta sesion...", "data-estado": "cargando" }));
  const cuerpo = el("div", { clase: "cuerpo-entrenador" });
  caja.appendChild(cuerpo);
  return caja;
}

function pintarEntrenador(caja, ev) {
  const cuerpo = caja.querySelector(".cuerpo-entrenador");
  const aviso = caja.querySelector("[data-estado]");
  if (aviso) aviso.hidden = true;
  caja.hidden = false;
  cuerpo.innerHTML = "";
  if (!ev) { cuerpo.appendChild(el("p", { clase: "ayuda", texto: "No he podido componer la valoracion de esa sesion." })); return; }
  cuerpo.appendChild(el("p", { clase: "mini-txt", html: "<b>" + esc(fechaCorta(ev.fecha)) + "</b> <span class='gris'>"
    + esc(ev.titulo || "") + " · " + esc(ev.cabecera || "") + "</span>" }));
  (ev.parrafos || []).forEach((p) => {
    cuerpo.appendChild(el("div", { clase: "etiqueta-mini", texto: p.titulo }));
    cuerpo.appendChild(el("p", { clase: "mini-txt valor-texto", texto: p.texto }));
  });
  /* Cuando se escribio: el texto es de este momento, no del dia de la sesion. */
  if (ev.generado) cuerpo.appendChild(el("p", { clase: "pista", texto: "Escrito el " + fechaHora(ev.generado) }));
}

function evaluarSesion(actividad_id, caja, boton) {
  if (boton && boton.disabled) return;
  if (boton) boton.disabled = true;
  const cuerpo = caja.querySelector(".cuerpo-entrenador");
  const aviso = caja.querySelector("[data-estado]");
  caja.hidden = false;
  if (aviso) { aviso.hidden = false; aviso.textContent = "Mirando esta sesion..."; }
  if (cuerpo) cuerpo.innerHTML = "";
  const cuerpo_peticion = JSON.stringify(actividad_id ? { actividad_id: actividad_id } : {});
  fetch(EVALUAR, { method: "POST", headers: { "Content-Type": "application/json" }, body: cuerpo_peticion })
    .then((r) => r.text().then((t) => ({ ok: r.ok, estado: r.status, t })))
    .then(({ ok, estado, t }) => {
      let d = {};
      try { d = JSON.parse(t) || {}; } catch (e) { d = {}; }
      if (!ok || d.ok === false) {
        if (aviso) { aviso.hidden = false; aviso.textContent = "El servidor ha respondido con un problema (" + estado + "): " + (d.error || "sin detalle"); }
        if (boton) boton.disabled = false;
        return;
      }
      if (d.aviso) { if (aviso) { aviso.hidden = false; aviso.textContent = d.aviso; } }
      pintarEntrenador(caja, d.evaluacion);
      if (boton) boton.disabled = false;
    })
    .catch(() => {
      if (aviso) aviso.hidden = false;
      if (aviso) aviso.textContent = "No hay ningun servidor al otro lado. Doble clic en servir-entrenador.bat "
        + "(y deja su ventana abierta) y vuelve a darle al boton.";
      if (boton) boton.disabled = false;
    });
}

/* ---------- 12. Reglas: el bucle cerrado (V1.3) ------------------------- */

const RUTA_DECISION = urlApi("decision");
const RUTA_PROPONER = urlApi("plan/generar");

function avisoReglas(texto) {
  pintar("reglasAviso", texto);
  if (texto) setTimeout(() => pintar("reglasAviso", ""), 6000);
}

function pintarReglas() {
  const ent = DATOS.entrenador || {}, res = ent.resumen || {}, reglas = ent.reglas || [], props = ent.propuestas || [];
  pintar("cReglas", (res.sin_decidir || 0) || "");
  pintar("entrenadorKpis", [
    kpi("Propuestas guardadas", entero(res.recomendaciones), "cada una con sus datos y sus reglas"),
    kpi("Sin decidir", entero(res.sin_decidir), "aceptar, cambiar o ignorar"),
    kpi("Reglas con medida", entero((res.reglas || 0) - (res.reglas_sin_datos || 0)), "las demas van sin datos"),
    kpi("Para revisar", (res.para_revisar || []).length ? (res.para_revisar || []).join(" ") : "ninguna", "tres ventanas en contra"),
  ]);

  /* las propuestas guardadas, con lo que las sostiene */
  const caja = q("entrenadorLista");
  if (!props.length) {
    caja.innerHTML = '<div class="vacio"><strong>Todavia no hay ninguna propuesta guardada</strong>'
      + 'Pulsa "Guardar la propuesta de esta semana" y aqui aparece cada dia con los numeros que lo sostienen,'
      + ' la regla que lo pide y lo que decides tu.</div>';
  } else {
    caja.innerHTML = props.map((p) => {
      const estado = p.decision ? p.decision.tomada : "sin decidir";
      const clase = estado === "aceptada" ? "etiqueta ok" : (estado === "sin decidir" ? "etiqueta" : "etiqueta ojo");
      const chips = (p.reglas || []).map((x) => '<button type="button" class="chip pinza" data-regla="' + esc(x.regla_id) + '">'
        + esc(x.regla_id) + " · " + esc((x.seccion_T || []).length ? x.seccion_T.join(", ") : "criterio") + "</button>").join("");
      return '<article class="semana" data-rec="' + esc(String(p.id)) + '">'
        + '<header><div><b>' + esc(p.titulo) + '</b> <span class="gris mini-txt">' + esc(fechaCorta(p.fecha))
        + (p.semana ? " · " + esc(p.semana) : "") + '</span></div><span class="' + clase + '">' + esc(estado) + "</span></header>"
        + (p.cuerpo ? '<p class="ayuda">' + esc(p.cuerpo) + "</p>" : "")
        + tablaHTML([{ n: "De donde sale" }, { n: "Dato" }, { n: "Valor", num: true }, { n: "Para que" }],
          (p.datos || []).map((x) => ["<span class='gris mini-txt'>" + esc(x.fuente) + "</span>",
            "<span class='ahora'>" + esc(x.ref) + "</span>", esc(String(x.valor)), "<span class='gris'>" + esc(x.nota || "") + "</span>"]),
          { compacta: true })
        + (chips ? '<div class="chips mt">' + chips + "</div>" : "")
        + '<div class="fila-campos mt">'
        + '<button class="boton mini" type="button" data-hacer="aceptada">Aceptar</button>'
        + '<button class="boton mini" type="button" data-hacer="cambiada">Cambiar</button>'
        + '<input class="campo-motivo" type="text" placeholder="por que lo cambias (en tus palabras)">'
        + '<button class="boton mini suave" type="button" data-hacer="ignorada">Ignorar</button>'
        + "</div>"
        + (p.decision && p.decision.motivo ? '<p class="pista">Lo cambiaste porque: ' + esc(p.decision.motivo) + "</p>" : "")
        + "</article>";
    }).join("");
  }

  /* la firma del anexo T (V1.3-01): sin firma se dice sin revisar */
  const cono = ent.conocimiento || {};
  pintar("conocimientoKpis", [
    kpi("Secciones del anexo", entero(cono.total), "lo que el motor sabe"),
    kpi("Firmadas", entero(cono.revisadas), "por entrenador o atleta"),
    kpi("Criterios sin firma", entero(cono.sin_fuente), "criterio del entrenador"),
  ]);
  const listaCono = q("conocimientoLista");
  if (listaCono) {
    listaCono.innerHTML = (cono.secciones || []).map((x) => {
      const estado = x.estado_revision || (x.revisado_por ? "revisada_por_asistente" : "sin_revisar");
      const firma = estado === "firmada"
        ? ("Firmada por " + esc(x.revisado_por) + " el " + esc(fechaCorta(x.revisado_en)))
        : (estado === "revisada_por_asistente"
          ? ("Revisada por " + esc(x.revisado_por) + " (asistente), pendiente de firma")
          : "Sin revisar");
      const marca = estado === "firmada" ? ["etiqueta ok", "firmada"]
        : (estado === "revisada_por_asistente" ? ["etiqueta ojo", "asistente"] : ["etiqueta", "sin revisar"]);
      const respaldo = x.con_fuente ? ("Fuentes " + (x.fuentes || []).map((n) => "[" + n + "]").join(" "))
        : (x.criterio ? "Criterio (sin cita literal)" : "Sección de método");
      return '<div class="item"><i class="i-marca"></i><div class="i-txt"><strong>' + esc(x.seccion) + " · "
        + esc(x.titulo || "") + "</strong><span>" + respaldo + (x.criterios ? " · " + entero(x.criterios)
        + " afirmacion(es) marcadas" : "") + '</span><span class="gris mini-txt">' + firma
        + (x.notas ? " · " + esc(x.notas) : "") + "</span></div>"
        + '<span class="' + marca[0] + '">' + marca[1] + "</span></div>";
    }).join("") || '<div class="vacio"><strong>No encuentro el anexo</strong>El motor no puede leer informes/T_base_de_conocimiento.md.</div>';
  }

  /* el credito de cada regla */
  q("reglasCredito").innerHTML = reglas.length ? reglas.map((r) => {
    const d = r.decisiones || {};
    const secciones = (r.seccion_T || []).length ? r.seccion_T.join(", ") : "criterio";
    const marca = r.veredicto === "a_favor" ? "etiqueta ok" : (r.veredicto === "en_contra" ? "etiqueta ojo" : "etiqueta");
    return '<div class="item item-pinza" data-regla="' + esc(r.regla_id) + '">'
      + '<i class="i-marca"></i><div class="i-txt"><strong>' + esc(r.enunciado) + "</strong>"
      + "<span>" + esc(r.regla_id) + " · anexo T " + esc(secciones) + " · " + esc(r.grado) + " · propuestas "
      + entero(r.propuestas) + " · aceptadas " + entero(d.aceptada || 0) + ", cambiadas " + entero(d.cambiada || 0)
      + ", ignoradas " + entero(d.ignorada || 0) + ", sin decidir " + entero(d.sin_registrar || 0) + "</span>"
      + '<span class="gris mini-txt">' + esc(String(r.veredicto)) + (r.notas ? " · " + esc(r.notas) : "") + "</span>"
      + (r.revisar ? '<span class="gris mini-txt">Marcada para revisar: tres ventanas en contra.</span>' : "")
      + "</div><span class='" + marca + "'>" + esc(String(r.veredicto)).replace("_", " ") + "</span></div>";
  }).join("") : '<div class="vacio"><strong>Sin reglas</strong>No hay ninguna regla declarada en el motor.</div>';
}

function abrirFichaRegla(rid) {
  const ent = DATOS.entrenador || {};
  const f = (ent.reglas || []).filter((x) => x.regla_id === rid)[0];
  if (!f) return;
  const usos = (ent.propuestas || []).filter((p) => (p.reglas || []).some((x) => x.regla_id === rid));
  const secciones = (f.seccion_T || []).length ? f.seccion_T.join(", ") : "criterio del entrenador (sin seccion del anexo T)";
  let h = "<p class='mini-txt'><b>" + esc(f.enunciado) + "</b></p>";
  h += "<p class='pista'>" + esc(f.regla_id) + " · " + esc(f.grado) + " · anexo T: " + esc(secciones)
    + " · fuente declarada: " + esc(f.fuente || "—") + "</p>";
  if (f.porque) h += "<p class='mini-txt valor-texto'>Como se comprueba: " + esc(f.porque) + "</p>";
  h += "<p class='pista'>Se ha propuesto " + entero(f.propuestas) + " vez/veces. Veredicto: <b>"
    + esc(String(f.veredicto)) + "</b>" + (f.notas ? " · " + esc(f.notas) : "") + "</p>";
  if (!usos.length) {
    h += '<div class="vacio"><strong>Todavia no la ha usado ninguna propuesta</strong>'
      + "Cuando el motor proponga algo con esta regla, aqui aparecen los numeros que la pusieron en juego.</div>";
  } else {
    usos.forEach((p) => {
      h += "<div class='etiqueta-mini'>#" + esc(String(p.id)) + " · " + esc(p.titulo) + "</div>";
      h += tablaHTML([{ n: "De donde sale" }, { n: "Dato" }, { n: "Valor", num: true }],
        (p.datos || []).map((x) => ["<span class='gris mini-txt'>" + esc(x.fuente) + "</span>",
          "<span class='ahora'>" + esc(x.ref) + "</span>", esc(String(x.valor))]), { compacta: true });
    });
  }
  pintar("reglasDetalleTitulo", esc(f.regla_id));
  pintar("reglasDetalleCuerpo", h);
  q("reglasDetalle").classList.remove("oculto");
}

function mandarDecision(rid, tomada, motivo) {
  if (typeof fetch !== "function") { avisoReglas("Este navegador no puede hablar con el servidor."); return; }
  avisoReglas("Apuntando...");
  fetch(RUTA_DECISION, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ recomendacion_id: rid, tomada: tomada, motivo: motivo || "" }) })
    .then((r) => r.text().then((t) => ({ ok: r.ok, estado: r.status, t })))
    .then(({ ok, estado, t }) => {
      let d = {};
      try { d = JSON.parse(t) || {}; } catch (e) { d = {}; }
      if (!ok || d.ok === false) { avisoReglas("No se pudo apuntar (" + estado + "): " + (d.error || "sin detalle")); return; }
      if (d.entrenador) DATOS.entrenador = d.entrenador;
      pintarReglas();
      avisoReglas("Apuntado: " + tomada + ".");
    })
    .catch(() => avisoReglas("No hay ningun servidor al otro lado. Doble clic en servir-entrenador.bat y vuelve a probar."));
}

function mandarProponerSemana() {
  if (typeof fetch !== "function") { avisoReglas("Este navegador no puede hablar con el servidor."); return; }
  avisoReglas("Guardando la propuesta de esta semana...");
  fetch(RUTA_PROPONER, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
    .then((r) => r.text().then((t) => ({ ok: r.ok, estado: r.status, t })))
    .then(({ ok, estado, t }) => {
      let d = {};
      try { d = JSON.parse(t) || {}; } catch (e) { d = {}; }
      if (!ok || d.ok === false) { avisoReglas("No se pudo guardar (" + estado + "): " + (d.error || "sin detalle")); return; }
      if (d.entrenador) DATOS.entrenador = d.entrenador;
      pintarReglas();
      avisoReglas(d.cuantas ? ("Guardada: " + d.cuantas + " dia(s) de " + (d.semana || "la semana") + ".") : (d.falta || "No habia nada que proponer."));
    })
    .catch(() => avisoReglas("No hay ningun servidor al otro lado. Doble clic en servir-entrenador.bat y vuelve a probar."));
}

function montarReglas() {
  const b = q("regGenerar");
  if (b) b.addEventListener("click", mandarProponerSemana);
  const c = q("reglasDetalleCerrar");
  if (c) c.addEventListener("click", () => q("reglasDetalle").classList.add("oculto"));
  const lista = q("entrenadorLista");
  if (lista) lista.addEventListener("click", (ev) => {
    const boton = ev.target.closest("[data-hacer]");
    if (boton) {
      const caja = boton.closest("[data-rec]");
      const rid = Number(caja.dataset.rec);
      const tomada = boton.dataset.hacer;
      const campo = caja.querySelector(".campo-motivo");
      const motivo = campo ? campo.value.trim() : "";
      if (tomada === "cambiada" && !motivo) { avisoReglas("Para cambiar una sesion hace falta el motivo: escribelo al lado."); if (campo) campo.focus(); return; }
      mandarDecision(rid, tomada, motivo);
      return;
    }
    const chip = ev.target.closest("[data-regla]");
    if (chip) abrirFichaRegla(chip.dataset.regla);
  });
  const credito = q("reglasCredito");
  if (credito) credito.addEventListener("click", (ev) => {
    const item = ev.target.closest("[data-regla]");
    if (item) abrirFichaRegla(item.dataset.regla);
  });
}

function arrancar() {
  montarTema();
  pintarCabeceraDatos();
  pintarKpis();
  pintarValoracion();
  pintarEstado();
  pintarResultados();
  pintarPreparacion();
  pintarVolumen();
  pintarResumenPruebas();
  pintarPruebas();
  montarCalendario();
  pintarCompeticion();
  pintarPases();
  pintarPlan();
  pintarEntrenos();
  montarGarmin();
  pintarGimnasio();
  pintarApuntar();
  pintarParteYPlan();
  pintarBici();
  pintarReglas();
  montarReglas();
  montarPestanas();
  montarOrdenTablas();
  montarFilasPinchables();
  $$(".nav a[data-vista]").forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); irA(a.dataset.vista); }));
  window.addEventListener("hashchange", () => mostrarVista(location.hash.slice(1) || "resumen", true));
  mostrarVista(location.hash.slice(1) || almacen.leer(CLAVES.vista, "resumen"), true);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", arrancar); else arrancar();
