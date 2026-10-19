/* Comprueba el cuadro de mando como si fuera un navegador, sin navegador:
   - saca el JavaScript del fichero y comprueba que no tiene errores de sintaxis,
   - lo ejecuta dentro de un DOM simulado y comprueba que no revienta,
   - comprueba que todos los ids que el JS busca existen en el HTML,
   - comprueba que las vistas del menu cuadran con las secciones de la pagina,
   - y comprueba que las tarjetas se han pintado de verdad (no se queda en blanco).

   Uso: node pruebas/comprobar_portal.js cuadro/panel.html                        */

const fs = require("fs");
const vm = require("vm");

const ruta = process.argv[2] || "cuadro/panel.html";
const html = fs.readFileSync(ruta, "utf8");
const fallos = [];

/* ---------- 1. separar el JavaScript y los datos incrustados ---------- */
const bloques = (html.match(/<script[^>]*>[\s\S]*?<\/script>/g) || [])
  .map((b) => b.replace(/^<script[^>]*>/, "").replace(/<\/script>$/, ""));
const js = bloques.find((b) => b.indexOf('"use strict"') >= 0);
const datos = bloques.find((b) => b.trim().charAt(0) === "{");

if (!js) fallos.push("no encuentro el JavaScript de la aplicacion dentro del HTML");
if (!datos) fallos.push("no encuentro los datos incrustados (script id=datos)");
if (fallos.length) { console.log(fallos.join("\n")); process.exit(1); }

/* ---------- 2. los datos incrustados se tienen que poder leer ---------- */
try {
  const d = JSON.parse(datos);
  const falta = ["kpis", "plan", "competicion", "volumen", "calendario", "sesiones_recientes", "bici"].filter((k) => !(k in d));
  if (falta.length) fallos.push("a los datos les falta: " + falta.join(", "));
  console.log("datos: " + Object.keys(d).join(", "));
  console.log("marcas: " + ((d.competicion && d.competicion.marcas) || []).length
    + " | sesiones recientes: " + (d.sesiones_recientes || []).length
    + " | semanas de plan: " + ((d.plan && d.plan.semanas) || []).length
    + " | segmentos: " + (d.segmentos || []).length);
} catch (e) {
  fallos.push("los datos incrustados no son JSON valido: " + e.message);
}

/* ---------- 3. DOM simulado ---------- */
const pintados = {};
const eventos = [];

function elemento(nombre) {
  const el = {
    tagName: nombre || "div", dataset: {}, style: {}, hijos: [], _html: "", _texto: "",
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener(tipo) { eventos.push([nombre, tipo]); },
    removeEventListener() {},
    setAttribute(k, v) { el[k] = v; },
    getAttribute(k) { return el[k] === undefined ? null : el[k]; },
    removeAttribute(k) { delete el[k]; },
    appendChild(h) { el.hijos.push(h); return h; },
    insertBefore(h) { el.hijos.push(h); return h; },
    removeChild() {}, remove() {},
    insertAdjacentHTML(donde, texto) { el._html += texto; },
    querySelector() { return elemento("hijo"); },
    querySelectorAll() { return []; },
    closest() { return elemento("padre"); },
    getBoundingClientRect() { return { left: 0, top: 0, width: 10, height: 10 }; },
    focus() {}, select() {}, click() {}, blur() {},
    value: "", checked: false, disabled: false, title: "", href: "", download: "", rows: 0,
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html; },
    set(v) { el._html = String(v); if (nombre) pintados[nombre] = el._html; },
  });
  Object.defineProperty(el, "textContent", {
    get() { return el._texto; },
    set(v) { el._texto = String(v); },
  });
  return el;
}

/* El texto de un arbol de elementos del DOM simulado: el portal pinta anidando (appendChild), no con
   innerHTML, asi que para leer lo que ha quedado en pantalla hay que recorrer los hijos. */
function textoDe(el, hondo) {
  if (!el || typeof el !== "object" || (hondo || 0) > 12) return "";
  let t = (el._html || "") + " " + (el._texto || "");
  (el.hijos || []).forEach((h) => { t += " " + textoDe(h, (hondo || 0) + 1); });
  return t;
}

const ids_html = new Set(Array.from(html.matchAll(/id="([^"]+)"/g)).map((x) => x[1]));
const cajones = {};
ids_html.forEach((id) => { cajones[id] = elemento(id); });
/* los datos van incrustados en el HTML: hay que darselos al cajon, como haria el navegador */
if (cajones.datos) cajones.datos.textContent = datos;

const documento = {
  readyState: "complete",
  title: "",
  documentElement: elemento("html"),
  body: elemento("body"),
  getElementById(id) { return cajones[id] || (cajones[id] = elemento(id)); },
  querySelector(sel) { return elemento(sel); },
  querySelectorAll() { return []; },
  createElement(tag) { return elemento(tag); },
  createTextNode(t) { return { texto: t }; },
  addEventListener(t) { eventos.push(["document", t]); },
};
const almacen = {
  _d: {},
  getItem(k) { return this._d[k] === undefined ? null : this._d[k]; },
  setItem(k, v) { this._d[k] = String(v); },
  removeItem(k) { delete this._d[k]; },
};

const sandbox = {
  document: documento,
  window: { addEventListener() {}, scrollTo() {}, location: { hash: "" } },
  location: { hash: "" },
  localStorage: almacen,
  navigator: {},
  Blob: function () {}, URL: { createObjectURL: () => "blob:x", revokeObjectURL() {} },
  console, setTimeout: () => 0, clearTimeout() {},
  Date, Math, JSON, Set, Map, Array, Object, Number, String, Boolean, isNaN, parseInt, parseFloat, RegExp, Error,
};
vm.createContext(sandbox);

/* ---------- 4. sintaxis y ejecucion ---------- */
try {
  new vm.Script(js, { filename: "app.js" });
} catch (e) {
  fallos.push("el JavaScript del cuadro de mando tiene un error de sintaxis: " + e.message);
}
if (!fallos.length) {
  try {
    vm.runInContext(js, sandbox, { timeout: 30000, filename: "app.js" });
  } catch (e) {
    fallos.push("el JavaScript revienta al arrancar: " + e.message + " | " + (e.stack || "").split("\n")[1]);
  }
}

/* ---------- 5. ids que el JS necesita ---------- */
const ids_js = new Set(Array.from(js.matchAll(/(?:getElementById|pintar|q)\("([A-Za-z0-9_]+)"/g)).map((x) => x[1]));
/* Los de la fila de anadir del gimnasio: se pintan al vuelo con la tabla, no estan en el HTML fijo. */
const IDS_AL_VUELO = new Set(["gimNuevoSel", "gimNuevoNombre", "gimAnadir"]);
const faltan = Array.from(ids_js).filter((i) => !ids_html.has(i) && !IDS_AL_VUELO.has(i));
if (faltan.length) fallos.push("ids que el JS busca y no estan en el HTML: " + faltan.join(", "));

/* ---------- 6. menu y vistas ---------- */
const secciones = Array.from(html.matchAll(/<section[^>]*class="[^"]*vista[^"]*"[^>]*id="([^"]+)"/g)).map((x) => x[1]);
const enlaces = Array.from(html.matchAll(/data-vista="([A-Za-z0-9_]+)"/g)).map((x) => x[1]);
const menu_mal = enlaces.filter((v) => secciones.indexOf("vista-" + v) < 0);
if (menu_mal.length) fallos.push("el menu apunta a vistas que no existen: " + menu_mal.join(", "));
if (secciones.length < 8) fallos.push("esperaba al menos 8 vistas y hay " + secciones.length);

/* ---------- 7. que se haya pintado de verdad ---------- */
const esperados = ["kpis", "preparacion", "volumenAnual", "volumenMensual", "calendario", "calMes", "calCabecera",
  "calLeyenda", "calPista", "compKpis", "h400Tabla", "fueDosis", "fueCarga", "fueSeguro",
  "mejoresTabla", "cmpTabla", "fTabla", "objetivosPlan", "planSemanas", "entrenosTabla", "segmentosTabla",
  "gimKpis", "gsLista", "apImportados", "biciKpis", "biciSegmentos", "cuentaAtras", "selloDatos",
  "psPista", "psTabla", "psLectura", "psMejor", "psMejorPista"];
const vacios = esperados.filter((id) => {
  const pintado = pintados[id];
  return pintado === undefined || String(pintado).trim() === "";
});
if (vacios.length) fallos.push("se han quedado sin pintar: " + vacios.join(", "));

/* el calendario de piscina: un mes de verdad, con los dias que no se nado marcados aparte */
if (!fallos.length) {
  const cab = pintados.calCabecera || "";
  if (!/<span>L<\/span>/.test(cab) || !/<span>D<\/span>/.test(cab)) {
    fallos.push("el calendario no trae los dias de la semana (L..D)");
  }
  if (!/^[a-z]+ \d{4}$/.test(String(pintados.calMes || []).trim() === "" ? "" : String(pintados.calMes).trim())) {
    /* el mes se pinta como "octubre 2026" */
    fallos.push("el calendario no dice el mes que enseña: " + pintados.calMes);
  }
  if (typeof sandbox.pintarCalendario !== "function") {
    fallos.push("el calendario no se puede pintar (falta pintarCalendario)");
  } else {
    sandbox.pintarCalendario("2026-09");
    const htmlCal = String(pintados.calendario || "");
    const celdas = (htmlCal.match(/class="cal-celda/g) || []).length;
    if (celdas === 0 || celdas % 7 !== 0) fallos.push("el calendario no forma semanas completas (" + celdas + " cuadros)");
    if (celdas > 42) fallos.push("el calendario de un mes no puede tener mas de 42 cuadros");
    if (!/cal-num">1</.test(htmlCal)) fallos.push("el calendario no empieza en el dia 1");
    if (!/cal-num">30</.test(htmlCal)) fallos.push("el calendario no llega al ultimo dia del mes");
    const nadados = (htmlCal.match(/cal-celda nadado/g) || []).length;
    const secos = (htmlCal.match(/cal-celda seco/g) || []).length;
    if (!nadados) fallos.push("el calendario no marca ningun dia nadado");
    if (!secos) fallos.push("el calendario no marca los dias que no se nado");
    if (!/title="\d\d\/\d\d\/\d\d\d\d: \d/.test(htmlCal)) fallos.push("los cuadros del calendario no dicen los metros");
    if (!/data-sesion="/.test(htmlCal)) fallos.push("los dias del calendario no llevan a su sesion");
    if (!/cal-ej nadado/.test(String(pintados.calLeyenda || ""))) fallos.push("el calendario no explica su leyenda");
  }
}

/* ---------- 9. los selectores nuevos del parte y partir una serie ---------- */
if (!fallos.length) {
  /* El editor de un parte se pinta al abrir una sesion, y aqui no se abre: se comprueba que el portal lo
     sabe construir y que los catalogos (estilos, companias, intensidades) le llegan del servidor. */
  const faltan_js = ["opcionesEstilo", "cajaCompania", "controlPartir", "cabeceraDeUnaSerie", "ponerTiempoGrupo", "rehacerSegunParte"]
    .filter((f) => js.indexOf("function " + f) < 0);
  if (faltan_js.length) fallos.push("al portal le falta: " + faltan_js.join(", "));
  if (js.indexOf("PPA().estilos") < 0) fallos.push("el portal no coge los estilos del servidor");
  if (js.indexOf("PPA().companias") < 0) fallos.push("el portal no coge las companias del servidor");
  if (js.indexOf("Tuba") < 0) fallos.push("el material snorkel no se enseña como tuba");
  ["Estilo", "Esta sesion fue", "Partir en..."].forEach((t) => {
    if (js.indexOf(t) < 0) fallos.push('el editor del parte no tiene el selector "' + t + '"');
  });
  ["tecnica", "salida"].forEach((v) => {
    if (datos.indexOf('"valor":"' + v + '"') < 0 && datos.indexOf('"valor": "' + v + '"') < 0) {
      fallos.push("la intensidad " + v + " no llega al portal");
    }
  });
  if (datos.indexOf("Pies (pataleo") >= 0) fallos.push("la intensidad pies sigue enseñando el parentesis");

  /* los nombres de estilo y de compania salen del catalogo del servidor */
  const estilos = ["libre", "mariposa", "espalda", "braza", "estilos"];
  if (typeof sandbox.nombreEstilo === "function") {
    estilos.forEach((v) => {
      const n = sandbox.nombreEstilo(v);
      if (!n || n === v) fallos.push("el estilo " + v + " no tiene nombre en el portal");
    });
  } else {
    fallos.push("el portal no sabe nombrar los estilos");
  }
  if (typeof sandbox.nombreCompania !== "function" || !sandbox.nombreCompania("entrenador")) {
    fallos.push("el portal no sabe nombrar la compania de la sesion");
  }

  /* partir un 100 seguido en 2x50 (y 4x25), con un tiempo para cada trozo */
  if (typeof sandbox.trozosPosibles !== "function" || typeof sandbox.partirEn !== "function") {
    fallos.push("el portal no sabe partir una serie en trozos");
  } else {
    const t = sandbox.trozosPosibles({ tipo: "continuo", metros: 100, laps: [0, 1] });
    const como = t.map((x) => x.n + "x" + x.rep_m).join(",");
    if (como !== "2x50,4x25") fallos.push("de un 100 seguido no salen 2x50 y 4x25: " + (como || "nada"));
    const ya = sandbox.trozosPosibles({ tipo: "serie", metros: 100, rep_m: 50, n_reps: 2, laps: [0, 1] });
    if (ya.some((x) => x.n === 2)) fallos.push("se ofrece partir un 2x50 en 2x50, que no es partir nada");
    const falsa = {
      actividad_id: 1,
      grupos: [{ tipo: "continuo", metros: 100, tiempo_s: 130, laps: [4, 5],
                 reps: [{ lap_idx: 4, dist_m: 50, timer_s: 64 }, { lap_idx: 5, dist_m: 50, timer_s: 66 }] }],
    };
    const guarda = sandbox.repintarDetalle;
    sandbox.repintarDetalle = () => {};
    try {
      sandbox.partirEn(falsa, 0, 2);
    } finally {
      sandbox.repintarDetalle = guarda;
    }
    if (falsa.grupos.length !== 2) {
      fallos.push("partir un 100 en 2x50 no deja dos trozos (quedan " + falsa.grupos.length + ")");
    } else {
      const trozos = falsa.grupos.map((g) => Math.round(g.metros) + "/" + Math.round(g.tiempo_s));
      if (trozos.join(" ") !== "50/64 50/66") fallos.push("los trozos del 2x50 no se llevan su tiempo: " + trozos.join(" "));
      if (falsa.grupos.some((g) => !(g.tiempo_s > 0))) fallos.push("hay un trozo del 2x50 sin tiempo");
      if (falsa.grupos.some((g) => !(g.ritmo_100 > 0))) fallos.push("a los trozos del 2x50 les falta el ritmo");
    }
    console.log("partir una serie: " + (como || "no") + " | trozos con su tiempo: "
      + (falsa.grupos.length === 2 ? "si" : "no"));
  }

  /* añadir una serie: va DENTRO del bloque donde esta el boton, no un bloque nuevo (el atleta: "cuando añado una
     serie me esta añadiendo un bloque entero, no solo una serie") */
  if (typeof sandbox.anadirSerie !== "function") {
    fallos.push("el portal no sabe añadir una serie al parte");
  } else {
    const conSeries = {
      actividad_id: 2,
      grupos: [{ tipo: "serie", rep_m: 100, n_reps: 2, metros: 200, tiempo_s: 152, ritmo_100: 76,
                 intensidad: "ae3", material: ["pull"], estilo: "libre", laps: [7, 8],
                 reps: [{ lap_idx: 7, dist_m: 100, timer_s: 76, tiempo_s: 76, intensidad: "ae3" },
                        { lap_idx: 8, dist_m: 100, timer_s: 76, tiempo_s: 76, intensidad: "ae3" }] }],
    };
    const guarda2 = sandbox.repintarDetalle;
    sandbox.repintarDetalle = () => {};
    try {
      sandbox.anadirSerie(conSeries, 0);
    } finally {
      sandbox.repintarDetalle = guarda2;
    }
    const gs = conSeries.grupos[0];
    if (conSeries.grupos.length !== 1) {
      fallos.push("añadir una serie mete un bloque nuevo en vez de una serie dentro del bloque");
    } else {
      const nueva = (gs.reps || [])[2];
      if ((gs.reps || []).length !== 3) fallos.push("añadir una serie no deja la repeticion nueva dentro del bloque");
      if (!nueva || nueva.dist_m !== 100 || Number(nueva.timer_s) !== 76) {
        fallos.push("la serie añadida no nace igual que la ultima del bloque");
      }
      if (nueva && nueva.lap_idx !== null) fallos.push("la serie añadida apunta al reloj: el reloj no la vio");
      if (nueva && nueva.intensidad !== "ae3") fallos.push("a la serie añadida no se le lleva la intensidad del bloque");
      if (nueva && !nueva.tiempo_apuntado) fallos.push("al tiempo de la serie añadida no se le marca que es apuntado a mano");
      if (gs.n_reps !== 3) fallos.push("el bloque no cuenta la serie añadida: n_reps = " + gs.n_reps);
      if (gs.metros !== 300 || gs.tiempo_s !== 228) {
        fallos.push("los metros y el tiempo del bloque no suman la serie añadida: " + gs.metros + " m, " + gs.tiempo_s + " s");
      }
      if ((gs.laps || []).length !== 2) fallos.push("la serie añadida no puede traer intervalo del reloj");
      if (!(gs.avisos || []).length) fallos.push("no se avisa de que esa serie la puso el atleta a mano");
    }
    /* Un bloque continuo (una sola serie) pasa a bloque de series al añadirle otra. */
    const continuo = {
      actividad_id: 2,
      grupos: [{ tipo: "continuo", rep_m: 450, n_reps: 1, metros: 450, tiempo_s: 453, laps: [3],
                 reps: [{ lap_idx: 3, dist_m: 450, timer_s: 453, tiempo_s: 453 }] }],
    };
    sandbox.repintarDetalle = () => {};
    try {
      sandbox.anadirSerie(continuo, 0);
    } finally {
      sandbox.repintarDetalle = guarda2;
    }
    const gc = continuo.grupos[0];
    if (gc.tipo !== "serie" || (gc.reps || []).length !== 2 || gc.metros !== 900) {
      fallos.push("añadir una serie a un bloque continuo no lo convierte en bloque de series: " + gc.tipo
        + ", " + (gc.reps || []).length + " reps, " + gc.metros + " m");
    }
    console.log("añadir una serie: " + (conSeries.grupos[0].n_reps === 3 && continuo.grupos[0].tipo === "serie"
      ? "si, dentro del bloque" : "no"));
  }

  /* al reabrir, la repeticion que el atleta añadio a mano (sin intervalo del reloj) no se puede perder */
  if (typeof sandbox.rehacerSegunParte !== "function") {
    fallos.push("el portal no sabe rehacer el parte guardado");
  } else {
    const s2 = {
      actividad_id: 3,
      grupos: [{ tipo: "serie", rep_m: 100, n_reps: 2, metros: 200, tiempo_s: 152, laps: [7, 8],
                 reps: [{ lap_idx: 7, dist_m: 100, timer_s: 76 }, { lap_idx: 8, dist_m: 100, timer_s: 76 }] }],
    };
    const g0 = {
      series: [{ tipo: "serie", rep_m: 100, n_reps: 3, metros: 300, tiempo_s: 228, laps: [7, 8],
                 reps: [{ lap: 7, dist_m: 100, tiempo_s: 76 }, { lap: 8, dist_m: 100, tiempo_s: 76 },
                        { lap: null, dist_m: 100, tiempo_s: 76, tiempo_apuntado: "1:16,0" }] }],
    };
    const vale = sandbox.rehacerSegunParte(s2, g0);
    const re = ((s2.grupos || [])[0] || {}).reps || [];
    if (!vale) fallos.push("rehacer el parte guardado no se aplica aunque los intervalos del reloj cuadren");
    else if (re.length !== 3) {
      fallos.push("al reabrir se pierde la repeticion añadida a mano: " + re.length + " repeticiones de 3");
    } else if (re[2].lap_idx !== null || Number(re[2].tiempo_s) !== 76 || !re[2].tiempo_apuntado) {
      fallos.push("la repeticion añadida vuelve mal al reabrir: " + JSON.stringify(re[2]));
    }
    console.log("reabrir con una serie añadida a mano: " + re.length + " repeticiones");
  }

  /* corregir la distancia de un intervalo (el reloj la saca del largo de la piscina y de las vueltas) */
  if (typeof sandbox.cambiarDistancia !== "function" || typeof sandbox.cambiarDistanciaRep !== "function") {
    fallos.push("el portal no deja corregir la distancia del intervalo (ni la de cada repeticion)");
  } else {
    const g2 = {
      rep_m: 100, n_reps: 2, metros: 200, tiempo_s: 152, ritmo_100: 76, laps: [1, 2],
      reps: [{ lap_idx: 1, dist_m: 100, timer_s: 76, tiempo_s: 76 },
             { lap_idx: 2, dist_m: 100, timer_s: 76, tiempo_s: 76 }],
    };
    const antes = g2.ritmo_100;
    if (!sandbox.cambiarDistancia(g2, 125, 2)) fallos.push("cambiar la distancia no se deja hacer");
    if (g2.rep_m !== 125 || g2.n_reps !== 2 || g2.metros !== 250) {
      fallos.push("cambiar la distancia no rehace los metros del grupo: " + g2.rep_m + "x" + g2.n_reps + " = " + g2.metros);
    }
    if ((g2.reps || []).some((r) => r.dist_m !== 125)) fallos.push("cambiar la distancia no se le lleva a las repeticiones");
    if (!(g2.ritmo_100 > 0) || Math.round(g2.ritmo_100) !== 61 || g2.ritmo_100 === antes) {
      fallos.push("cambiar la distancia no rehace el ritmo del grupo: " + g2.ritmo_100);
    }
    const igual = JSON.stringify(g2);
    if (sandbox.cambiarDistancia(g2, 0, 2) || JSON.stringify(g2) !== igual) {
      fallos.push("cambiar la distancia a 0 no tiene que romper el grupo");
    }
    console.log("corregir la distancia: " + g2.metros + " m a " + (g2.ritmo_100 / 60).toFixed(3).slice(0, 4) + "/100");

    /* La distancia de UNA repeticion de dentro del grupo: un 50 dentro de un 100, una vuelta contada de mas... */
    const g6 = {
      rep_m: 100, n_reps: 2, metros: 200, tiempo_s: 160, ritmo_100: 80, laps: [41, 43],
      reps: [{ lap_idx: 41, dist_m: 100, timer_s: 80, tiempo_s: 80, ritmo_100: 80 },
             { lap_idx: 43, dist_m: 100, timer_s: 80, tiempo_s: 80, ritmo_100: 80 }],
    };
    if (!sandbox.cambiarDistanciaRep(g6, 1, 50)) fallos.push("no se puede cambiar la distancia de una repeticion");
    if (g6.reps[1].dist_m !== 50) fallos.push("la distancia de la repeticion no se queda");
    if (g6.metros !== 150) fallos.push("los metros del grupo no pasan a ser la suma de sus repeticiones (" + g6.metros + ")");
    if (g6.rep_m !== null) fallos.push("con repeticiones de distinta distancia el grupo no puede decir una sola (" + g6.rep_m + ")");
    if (Math.round(g6.reps[1].ritmo_100) !== 160 || !(g6.ritmo_100 > 0)) {
      fallos.push("cambiar la distancia de una repeticion no rehace su ritmo (" + g6.reps[1].ritmo_100 + ")");
    }
    if (sandbox.distanciaComunDeReps(g6) !== null) fallos.push("dos repeticiones distintas no tienen distancia comun");
    sandbox.cambiarDistancia(g6, 75, 2);
    if (sandbox.distanciaComunDeReps(g6) !== 75) fallos.push("corregir el grupo entero no unifica sus repeticiones");
    if (sandbox.cambiarDistanciaRep(g6, 5, 100)) fallos.push("una repeticion que no existe no se puede corregir");
    console.log("la distancia de una repeticion: 2x100 -> 100 + 50 = " + g6.metros + " m (grupo unificado despues)");

    /* Al reabrir la sesion, la distancia corregida manda sobre lo que conto el reloj (si no, se perderia). */
    if (typeof sandbox.rehacerSegunParte === "function") {
      const abierta = { actividad_id: 3, grupos: [{ tipo: "continuo", metros: 50, tiempo_s: 60, laps: [9],
                                                    reps: [{ lap_idx: 9, dist_m: 50, timer_s: 60 }] }] };
      const guardado = { series: [{ tipo: "continuo", rep_m: 100, n_reps: 1, metros: 100, tiempo_s: 120,
                                    ritmo_100: 120, laps: [9],
                                    reps: [{ lap: 9, dist_m: 150, tiempo_s: 90, intensidad: "ae3" }] }] };
      sandbox.rehacerSegunParte(abierta, guardado);
      const g3 = (abierta.grupos || [])[0] || {};
      const r3 = (g3.reps || [])[0] || {};
      if (g3.metros !== 100) fallos.push("al reabrir, la distancia corregida se pierde (queda en " + g3.metros + " m)");
      if (r3.dist_m !== 150) fallos.push("al reabrir, la distancia de la repeticion no vuelve (" + r3.dist_m + ")");
      if (r3.tiempo_s !== 90) fallos.push("al reabrir, el tiempo de la repeticion no vuelve al rehacer (" + r3.tiempo_s + ")");
      if (r3.intensidad !== "ae3") fallos.push("al reabrir y rehacer, la intensidad de la repeticion no vuelve");
    } else {
      fallos.push("el portal no sabe rehacer la sesion con lo guardado");
    }
  }

  /* el "cada" de una serie: el reloj no lo registra, lo dice el atleta */
  if (typeof sandbox.cambiarCada !== "function" || typeof sandbox.filaCadaGrupo !== "function") {
    fallos.push("el portal no deja escribir el cada de una serie");
  } else {
    const g4 = { rep_m: 100, n_reps: 8, metros: 800, tiempo_s: 600, cada_s: 130 };
    if (!sandbox.cambiarCada(g4, "2:10") || g4.cada_s !== 130 || g4.cada_apuntado !== "2:10") {
      fallos.push("escribir el cada no se queda con lo que dice el atleta: " + g4.cada_s);
    }
    if (sandbox.cambiarCada(g4, "hola")) fallos.push("un cada que no es un tiempo no puede valer");
    if (!sandbox.cambiarCada(g4, "") || g4.cada_s !== null || g4.cada_apuntado !== null) {
      fallos.push("el cada tiene que poder dejarse en blanco (y entonces vuelve el que se deduce de las repeticiones)");
    }
    console.log("el cada de una serie: se escribe, se corrige y se deja en blanco");
  }

  /* al reabrir, los tiempos que el atleta corrigio tienen que volver (el del grupo y el de cada repeticion) */
  if (typeof sandbox.reponerApuntado !== "function") {
    fallos.push("el portal no sabe reponer el parte guardado");
  } else {
    const vista = { actividad_id: 4242, grupos: [
      { tipo: "continuo", metros: 200, tiempo_s: 171, laps: [11],
        reps: [{ lap_idx: 11, dist_m: 200, timer_s: 171, tiempo_s: 171 }] },
    ] };
    almacen.setItem("iregua.partes.v1", JSON.stringify([{
      actividad_id: 4242, compania: "solo",
      series: [{ tipo: "continuo", metros: 200, tiempo_s: 165, cada_s: 190, laps: [11], material: [],
                 intensidad: "ae2", reps: [{ lap: 11, tiempo_s: 168 }] }],
    }]));
    sandbox.reponerApuntado(vista);
    const g5 = (vista.grupos || [])[0] || {};
    const r5 = (g5.reps || [])[0] || {};
    if (g5.tiempo_s !== 165) fallos.push("al reabrir, el tiempo del grupo vuelve al del reloj (" + g5.tiempo_s + ")");
    if (g5.cada_s !== 190) fallos.push("al reabrir, el cada guardado no vuelve (" + g5.cada_s + ")");
    if (r5.tiempo_s !== 168) fallos.push("al reabrir, el tiempo corregido de la repeticion no vuelve (" + r5.tiempo_s + ")");
    almacen.removeItem("iregua.partes.v1");
    console.log("al reabrir: el tiempo del grupo, el de la repeticion y el cada vuelven los tres");
  }

  /* lo que se toca en el detalle se guarda solo: no se pierde un tiempo por no darle a Guardar */
  if (!/function repintarDetalle\(\)[\s\S]{0,700}?guardarParte\(s, true(?:, true)?\)/.test(js)) {
    fallos.push("repintarDetalle no guarda el parte: lo que se corrige en el detalle se pierde si no se le da a Guardar");
  }
  /* Y que no se llame en bucle: guardarParte repinta el detalle y el detalle se guarda solo. */
  if (!/if \(repintandoDetalle\) return;/.test(js)) {
    fallos.push("falta la red contra el bucle guardar/repintar (repintarDetalle -> guardarParte -> repintarDetalle)");
  } else {
    console.log("el detalle se guarda solo (sin darle a Guardar el parte)");
  }
}

/* ---------- 10. el material que no se marca no es un hueco -------------------------------- */
if (!fallos.length) {
  /* No marcar material es nadar sin objetos: no es algo que falte. Lo que falta es la intensidad. */
  if (/!g\.material\.length\s*(?:\|\||&&)\s*!g\.intensidad/.test(js)) {
    fallos.push("el portal sigue contando el material que no se marca como si faltara algo (lo que falta es la intensidad)");
  }
  const cuantos = (js.match(/!g\.intensidad\)\.length/g) || []).length;
  if (cuantos < 2) fallos.push("falta el recuento de las intensidades que faltan (el pie de la sesion y el aviso al guardar): " + cuantos);
  if (js.indexOf("sin decir la intensidad") < 0) fallos.push("el aviso al guardar no habla de la intensidad que falta");

  /* El parte recien guardado vive en el navegador hasta que se sube: la lista tiene que decir ya que esta
     hecho ("he guardado el parte y no aparece como rellenado"). */
  const d = JSON.parse(datos);
  const recientes = (d.sesiones_recientes || []).filter((x) => x.actividad_id !== null && x.actividad_id !== undefined);
  const enBase = ((d.partes || {}).partes || []).map((p) => String(p.actividad_id));
  const pend = ((d.partes || {}).pendientes || []).map((p) => String(p.actividad_id));
  /* Una sesion que NO tenga parte en la base: solo asi se puede ver el parte del navegador como "sin subir" (con
     el parte ya en la base manda la base, y eso se comprueba justo debajo). */
  const elegida = recientes.filter((x) => enBase.indexOf(String(x.actividad_id)) < 0)[0];
  if (!elegida) {
    fallos.push("no hay ninguna sesion reciente sin parte en la base para comprobar la lista de entrenamientos");
  } else {
    const id = String(elegida.actividad_id);
    almacen.setItem("iregua.partes.v1", JSON.stringify([{ actividad_id: elegida.actividad_id, fecha: elegida.fecha, series: [] }]));
    sandbox.pintarEntrenos();
    const tabla = String(pintados.entrenosTabla || "");
    if (tabla.indexOf("hecho · sin subir") < 0) fallos.push("un parte guardado y sin subir no aparece como hecho en la lista de entrenamientos");
    /* La fila de esa sesion: desde su data-sesion hasta el de la siguiente (si no, el "por rellenar" de otra
       sesion de mas abajo contaria como si fuera el suyo). */
    const resto = tabla.split('data-sesion="' + id + '"')[1] || "";
    const fila = resto.split('data-sesion="')[0];
    if (pend.indexOf(id) >= 0 && fila.indexOf("por rellenar") >= 0) {
      fallos.push("la sesion " + id + " tiene el parte guardado y sigue diciendo \"por rellenar\"");
    }
    if (fila.indexOf("hecho") < 0) fallos.push("la fila de la sesion " + id + " no dice que el parte esta hecho");
    console.log("parte guardado sin subir: la lista dice \"" + (/(hecho · sin subir)/.test(tabla) ? "hecho · sin subir" : "nada") + "\"");
    almacen.removeItem("iregua.partes.v1");
    sandbox.pintarEntrenos();
  }

  /* Y al reves, que es lo que se ve cuando un parte se sube y el navegador se queda con su copia: si la sesion ya
     tiene el parte en la base, la lista dice "hecho" a secas, no "sin subir". */
  const yaEnBase = recientes.filter((x) => enBase.indexOf(String(x.actividad_id)) >= 0)[0];
  if (yaEnBase) {
    const idBase = String(yaEnBase.actividad_id);
    almacen.setItem("iregua.partes.v1", JSON.stringify([{ actividad_id: yaEnBase.actividad_id, fecha: yaEnBase.fecha, series: [] }]));
    sandbox.pintarEntrenos();
    const filaBase = String(pintados.entrenosTabla || "").split('data-sesion="' + idBase + '"')[1] || "";
    if (filaBase.indexOf("hecho") < 0) fallos.push("la sesion " + idBase + ", con el parte ya en la base, no sale como hecha");
    if (filaBase.indexOf("sin subir") >= 0) fallos.push("una sesion con el parte ya en la base sigue diciendo \"sin subir\"");
    console.log("parte ya en la base: la lista dice \"" + (filaBase.indexOf("hecho") >= 0 ? "hecho" : "nada") + "\"");
    almacen.removeItem("iregua.partes.v1");
    sandbox.pintarEntrenos();
  }

  /* Y al pincharla, la sesion con el parte ya en la base tiene que abrirse con su desglose: los grupos y,
     dentro de cada grupo, cada repeticion. Es lo que el atleta acaba de ordenar; si no, en cuanto el parte
     consta en la base la sesion se abre sin desglose y solo le queda la cabecera. */
  if (yaEnBase) {
    sandbox.abrirParte(String(yaEnBase.actividad_id), yaEnBase.fecha, false);
    const visto = textoDe(cajones.entrenosDetalle) + " " + String(pintados.entrenosDetalle || "");
    if (visto.indexOf("Cada repeticion") < 0) {
      fallos.push("una sesion con el parte ya en la base se abre sin sus repeticiones (sin el desglose)");
    } else if (visto.indexOf("Sin intervalos que agrupar") >= 0) {
      fallos.push("una sesion con el parte ya en la base dice que no hay intervalos que agrupar");
    } else {
      console.log("una sesion con el parte ya en la base se abre con su desglose (grupos y repeticiones)");
    }
  }

  /* El plan se recalcula con lo que ha entrado: la vista del plan tiene que enseñar el km que sale de lo que ha
     pasado (no el escrito a pelo) y decir de donde sale. */
  sandbox.pintarPlan();
  const planTxt = String(pintados.planSemanas || "");
  const vivoSemanas = (((d.plan || {}).vivo || {}).semanas) || [];
  const kmTxt = (x) => Number(x).toFixed(1).replace(".", ",");
  if (!vivoSemanas.length) {
    fallos.push("el portal no trae el plan recalculado");
  } else {
    const cambian = vivoSemanas.filter((v) => kmTxt(v.km) !== kmTxt(v.km_escrito));
    if (!cambian.length) fallos.push("el plan recalculado no cambia ninguna semana del plan escrito");
    const s = cambian[0] || vivoSemanas[0];
    if (planTxt.indexOf(kmTxt(s.km) + " km") < 0) {
      fallos.push("la semana " + s.clave + " del plan no enseña el km recalculado (" + kmTxt(s.km) + ")");
    }
    if (cambian.length && planTxt.indexOf("escrito: " + kmTxt(s.km_escrito) + " km") < 0) {
      fallos.push("la semana " + s.clave + " no deja ver el km escrito para poder comparar");
    }
    if (planTxt.indexOf("Recalculado con lo que ha pasado") < 0) {
      fallos.push("el plan no dice de donde sale el recalculo");
    } else {
      console.log("plan recalculado: " + vivoSemanas.length + " semanas, la " + s.clave + " sale con "
        + kmTxt(s.km) + " km (escrito " + kmTxt(s.km_escrito) + ") y con su motivo");
    }
  }
}

if (!/Tramo \d+ m/.test(pintados.psTabla || "")) fallos.push("la tabla de tramos no compara ningun tramo");
if (!/Tramo de \d+ m/.test(pintados.psMejor || "")) fallos.push("el desglose del mejor dia no trae ningun tramo");
/* y las cabeceras de las tablas tienen que estar puestas para poder pinchar en ellas */
if (!/<th[^>]*>Fecha<\/th>/.test(pintados.fTabla || "")) fallos.push("el historial no trae la cabecera de fecha");
if (!/<th[^>]*>Marca<\/th>/.test(pintados.fTabla || "")) fallos.push("el historial no trae la cabecera de marca");
if (!/data-pases="\d+"/.test(pintados.fTabla || "")) fallos.push("el historial no trae el boton para ver los tramos");
/* los ritmos van en minutos y segundos ("1:14,1"), no en segundos por 100 */
if (!/\d:\d\d,\d</.test(pintados.fTabla || "")) fallos.push("el historial no enseña los ritmos en minutos y segundos");
if (/ s\/100</.test(pintados.fTabla || "")) fallos.push("el historial sigue enseñando los ritmos en segundos por 100");

/* el ordenador de tablas: como se lee el valor de una celda y el orden que sale de el */
const celdaPrueba = (t) => { const c = elemento("td"); c.textContent = t; return c; };
const compararPrueba = (a, b, dir) => sandbox.compararFilas({ cells: [celdaPrueba(a)] }, { cells: [celdaPrueba(b)] }, 0, dir);
if (!fallos.length) {
  const leer = sandbox.valorCelda;
  if (typeof leer !== "function" || typeof sandbox.compararFilas !== "function") {
    fallos.push("el ordenador de tablas no esta disponible");
  } else {
    const f = leer(celdaPrueba("04/05/2019"));
    if (!f || f.t !== 0 || f.v !== 20190504) fallos.push("no se lee bien una fecha para ordenar");
    const t = leer(celdaPrueba("1:05:00.00"));
    if (!t || t.t !== 1 || Math.abs(t.v - 3896.4) > 0.0001) fallos.push("no se lee bien un tiempo para ordenar");
    const r = leer(celdaPrueba("74,1 s/100"));
    if (!r || r.t !== 2 || Math.abs(r.v - 74.1) > 0.0001) fallos.push("no se lee bien un ritmo con unidad");
    const m = leer(celdaPrueba("1:14,1"));
    if (!m || m.t !== 1 || Math.abs(m.v - 74.1) > 0.0001) fallos.push("no se lee bien un ritmo en minutos y segundos");
    if (leer(celdaPrueba("—")) !== null) fallos.push("un guion tiene que contar como hueco");
    if (compararPrueba("1:12.00", "1:04.00", 1) <= 0) fallos.push("los tiempos no se ordenan de mejor a peor");
    if (compararPrueba("1:12.00", "1:04.00", -1) >= 0) fallos.push("los tiempos no se pueden invertir");
    if (compararPrueba("04/05/2019", "12/05/2021", -1) <= 0) fallos.push("las fechas no se ordenan de lo mas reciente hacia atras");
    if (compararPrueba("1:04.00", "—", 1) >= 0) fallos.push("los huecos no se van al final");
  }
}

/* y que ordene de verdad: una tabla de mentira tiene que quedar ordenada, y un tramo viajar con su marca */
if (!fallos.length && typeof sandbox.ordenarTabla !== "function") fallos.push("el ordenador de tablas no esta montado");
if (!fallos.length) {
  const filaPrueba = (a, b, pega) => {
    const f = elemento("tr");
    f.cells = [celdaPrueba(a), celdaPrueba(b)];
    if (pega) f.setAttribute("data-pega", "1");
    return f;
  };
  const marcas = ["12/05/2021", "04/05/2019", "01/06/2019", "23/03/2024"].map((f) => filaPrueba(f, "1:00.00"));
  const tramo = filaPrueba("23/03/2024", "1:20.00", true);
  const cuerpo = elemento("tbody");
  cuerpo.rows = [marcas[0], marcas[1], marcas[2], marcas[3], tramo];
  cuerpo.appendChild = (f) => { cuerpo.rows = cuerpo.rows.filter((x) => x !== f).concat([f]); return f; };
  const tabla = elemento("table");
  tabla.tBodies = [cuerpo];
  tabla.tHead = { rows: [{ cells: [celdaPrueba("Fecha"), celdaPrueba("Marca")] }] };
  if (!sandbox.ordenarTabla(tabla, 0, -1)) fallos.push("no ha ordenado una tabla desordenada");
  const quedan = cuerpo.rows.map((f) => f.cells[0].textContent).join("|");
  if (quedan !== "23/03/2024|23/03/2024|12/05/2021|01/06/2019|04/05/2019")
    fallos.push("la tabla no queda ordenada por fecha (y el tramo con su marca): " + quedan);
  if (sandbox.ordenarTabla(tabla, 0, -1)) fallos.push("vuelve a ordenar una tabla que ya estaba ordenada");
}

/* Los pozos donde se mira: la lista de sesiones del resumen y la de entrenamientos. Las dos tienen que traer
   filas pinchables (data-sesion) y el oyente que las abre tiene que ser global, no de una tabla suelta. */
const tablasDeSesiones = ["recientes", "entrenosTabla"];
const pinchables = tablasDeSesiones.filter((c) => /data-sesion="/.test(pintados[c] || ""));
tablasDeSesiones.forEach((c) => {
  if (!pintados[c]) fallos.push("no se ha pintado la tabla de sesiones '" + c + "'");
  else if (!/data-sesion="/.test(pintados[c])) fallos.push("la tabla de sesiones '" + c + "' no tiene filas pinchables (data-sesion)");
  else if (!/tabindex="0"/.test(pintados[c])) fallos.push("las filas de '" + c + "' no se pueden activar con el teclado");
});
if (typeof sandbox.montarFilasPinchables !== "function") fallos.push("no esta montado montarFilasPinchables");
else {
  const antes = eventos.filter((x) => x[0] === "document").length;
  sandbox.montarFilasPinchables();
  const despues = eventos.filter((x) => x[0] === "document").length;
  if (despues - antes < 2) fallos.push("montarFilasPinchables no engancha el clic y el Enter en document");
}

/* Un entrenamiento apuntado a mano (sin reloj) tambien es una sesion: tiene que verse en las listas y
   pincharse (lleva a "Apuntar mis entrenamientos", que es donde esta apuntado). */
tablasDeSesiones.forEach((c) => {
  const html = pintados[c] || "";
  if (/sin reloj/.test(html) && !/data-apunte="/.test(html)) {
    fallos.push("hay un entrenamiento sin reloj en '" + c + "' que no se puede pinchar (data-apunte)");
  }
});
const conApuntado = tablasDeSesiones.filter((c) => /data-apunte="/.test(pintados[c] || ""));
const conSinReloj = tablasDeSesiones.filter((c) => /sin reloj/.test(pintados[c] || ""));

/* La valoracion del entrenador: el discurso del Resumen tiene que salir pintado, con parrafos y con las dianas
   de entrenamiento (los tiempos con los que hay que entrenar para el reto). */
const val = pintados.resumenEntrenador || "";
if (!/El entrenador dice/.test(val)) fallos.push("el Resumen no trae la valoracion del entrenador");
if (!/ent-parrafo/.test(val)) fallos.push("la valoracion del entrenador no trae parrafos");
if (!/Con que tiempos entrenar para el reto/.test(val)) fallos.push("la valoracion no trae las dianas de entrenamiento");
/* El boton del Garmin (Entrenamientos): el portal le pide al servidor del propio PC que traiga del reloj lo que
   todavia no esta en la base. Aqui no entra ninguna credencial: la sesion vive en el disco del PC. */
if (!/id="garmTraer"/.test(html)) fallos.push("Entrenamientos no trae el boton de traer lo nuevo del Garmin");
if (!/id="garmAviso"/.test(html)) fallos.push("el boton del Garmin no tiene donde avisar de lo que ha pasado");
if (typeof sandbox.traerDelGarmin !== "function") fallos.push("el JS del portal no sabe traer del Garmin");
if (typeof sandbox.montarGarmin !== "function") fallos.push("el JS del portal no monta el boton del Garmin");
/* El boton de evaluar: "mira el ultimo entrenamiento y dime como va el plan". El portal manda la sesion al
   servidor local y pinta lo que devuelve (tiempos, distancia, esfuerzo previo, descansos). */
if (!/id="evalUltimo"/.test(html)) fallos.push("Entrenamientos no trae el boton de evaluar el ultimo entrenamiento");
if (!/id="evalUltimoCaja"/.test(html)) fallos.push("el boton de evaluar no tiene donde escribir la valoracion");
/* ---------- 11. la cabecera del bloque: sus metros y lo que duro, con los descansos ---------------- */
if (!fallos.length) {
  /* El atleta: "la cabecera del bloque tambien sale mal, 4x- ... deberia ser 400 metros y la suma total de tiempo
     con sus descansos" y "el bloque cuando tiene series dentro no se puede modificar porque es la suma de lo de
     dentro". O sea: la etiqueta nunca sale con un guion donde iria la distancia (un bloque de series dice NxM si
     todas son iguales, y sus metros totales si no), y el tiempo es el del bloque entero, descansos incluidos. */
  if (/function etiquetaGrupo\([\s\S]{0,400}?seguidos/.test(js)) {
    fallos.push("la etiqueta del bloque sigue diciendo \"seguidos\"");
  }
  const rep = () => ({ dist_m: 100, timer_s: 85 });
  const iguales = { tipo: "bloque", rep_m: null, n_reps: 4, metros: 400, tiempo_s: 340, descanso_s: 20,
                    reps: [rep(), rep(), rep(), rep()] };
  const distintas = { tipo: "bloque", rep_m: null, n_reps: 3, metros: 300, tiempo_s: 240, descanso_s: 15,
                      reps: [{ dist_m: 100, timer_s: 80 }, { dist_m: 50, timer_s: 40 }, { dist_m: 150, timer_s: 120 }] };
  if (typeof sandbox.etiquetaGrupo !== "function" || typeof sandbox.totalConDescansos !== "function"
      || typeof sandbox.cadaDeducido !== "function") {
    fallos.push("el JS no sabe decir la etiqueta, el total y el cada de un bloque");
  } else {
    if (sandbox.etiquetaGrupo(iguales) !== "4x100") {
      fallos.push("la etiqueta de un bloque de series iguales deberia decir 4x100: " + sandbox.etiquetaGrupo(iguales));
    }
    if (sandbox.etiquetaGrupo(distintas) !== "300 m") {
      fallos.push("un bloque con distancias distintas deberia decir sus metros (300 m): " + sandbox.etiquetaGrupo(distintas));
    }
    if (sandbox.etiquetaGrupo({ tipo: "continuo", metros: 450, reps: [{ dist_m: 450, timer_s: 454 }] }) !== "450 m") {
      fallos.push("un bloque continuo deberia decir sus metros (450 m)");
    }
    const total = sandbox.totalConDescansos(iguales);
    if (Math.abs(total - 400) > 0.6) fallos.push("el total del bloque no suma sus descansos (400 s): " + total);
    const cada = sandbox.cadaDeducido(iguales);
    if (Math.abs(cada - 105) > 0.6) fallos.push("el cada estimado de un bloque partido o juntado a mano no sale (1:45): " + cada);
    console.log("cabecera del bloque: " + sandbox.etiquetaGrupo(iguales) + " · " + total + " s con descansos · cada "
      + cada + " s (" + sandbox.etiquetaGrupo(distintas) + " si las distancias no son iguales)");
  }
  /* Y el servidor manda el total calculado con los descansos de verdad de esa sesion. Los bloques con series y
     descansos salen en las propuestas de las sesiones que estan sin parte; si no queda ninguna (este fin de
     semana tiene parte todo lo que se ha nadado), no hay nada que comprobar y se dice, en vez de inventar un
     fallo por el estado de la base. */
  const d = JSON.parse(datos);
  const bloques = [].concat(
    (((d.partes || {}).pendientes) || []).map((p) => p.grupos || []),
    (((d.partes || {}).partes) || []).map((p) => p.series || []));
  const gs = [].concat.apply([], bloques);
  const conReps = gs.filter((g) => (g.reps || []).length >= 2 && g.descanso_s && g.total_s);
  if (!conReps.length) {
    console.log("total de un bloque con series: sin datos (ninguna sesion reciente queda sin parte)");
  } else if (!(conReps[0].total_s > conReps[0].tiempo_s)) {
    fallos.push("el total del bloque no cuenta lo descansado: " + conReps[0].tiempo_s + " s -> " + conReps[0].total_s + " s");
  } else {
    console.log("total de un bloque con series: " + Math.round(conReps[0].tiempo_s) + " s nadados -> "
      + conReps[0].total_s + " s con los descansos");
  }
}

if (typeof sandbox.evaluarSesion !== "function") fallos.push("el JS del portal no sabe pedir la evaluacion de una sesion");
if (typeof sandbox.cajaEntrenador !== "function") fallos.push("el JS del portal no sabe pintar la caja del entrenador");
/* El "cada" de cada serie: en la cabecera del grupo se canta el intervalo de salida ("cada 2:55"), no el
   descanso suelto. Es como se dice en la piscina. */
if (!/cada /.test(html)) fallos.push("las cabeceras de grupo no cantan el cada de la serie");
if (!/g\.cada_s/.test(html)) fallos.push("el portal no mira el cada de la serie");

/* Los pasos de cada 100 (V1.2-08): una repeticion larga y a ritmo de serie se abre con su desglose. Aqui se pinta
   de verdad la sesion, que es donde el fallo canta: si el portal mete el HTML de la tabla donde va un nodo, salta
   una excepcion y el script se queda a medias (con el menu lateral sin enganchar). */
const dp = JSON.parse(datos);
const conPasos = ((((dp.partes || {}).pendientes) || []).concat((((dp.partes || {}).partes) || [])))
  .filter((p) => (((p.grupos || []).concat(p.series || [])).some((g) => (g.reps || []).some((r) => (r.pasos || []).length))))[0];
if (!conPasos) {
  console.log("pasos de cada 100: sin datos (ninguna sesion reciente trae repeticiones largas a ritmo de serie)");
} else {
  try {
    sandbox.abrirParte(String(conPasos.actividad_id), conPasos.fecha, false);
    const vistoPasos = textoDe(cajones.entrenosDetalle) + " " + String(pintados.entrenosDetalle || "");
    if (vistoPasos.indexOf("Pasos de cada 100") < 0) {
      fallos.push("una repeticion larga no enseña sus pasos de cada 100");
    } else {
      console.log("pasos de cada 100: la repeticion larga sale partida, en su tabla");
      /* Y lo que se ve arriba: el total tiene que ser LA SUMA DE LOS PASOS, con la correccion dentro, y no el tiempo
         del reloj (el atleta: "el total debe ser la suma de los pasos y que se aplique mi corrección"). Se mira el
         texto ya pintado de la tarjeta, no los datos: es la unica forma de saber lo que ve el atleta. */
      const comoEnLaPagina = (s) => {
        const m = Math.floor(s / 60), r = s % 60;
        return m + ":" + (r < 10 ? "0" : "") + r.toFixed(2).replace(".", ",");
      };
      const conRep = ((conPasos.grupos || []).concat(conPasos.series || []))
        .map((g) => (g.reps || []).find((r) => (r.pasos || []).length)).filter(Boolean)[0];
      const suma = conRep ? conRep.pasos.reduce((s, p) => s + (Number(p.segundos_corregidos) || Number(p.segundos) || 0), 0) : 0;
      const delReloj = conRep ? Number(conRep.lap_del_reloj_s || conRep.tiempo_del_reloj_s || 0) : 0;
      const esta = (seg) => seg > 0
        && (vistoPasos.indexOf(comoEnLaPagina(seg)) >= 0 || vistoPasos.indexOf(comoEnLaPagina(seg).replace(/,[0-9]+$/, "")) >= 0);
      const relojes = (vistoPasos.match(/\b\d{1,3}:\d{2}(,\d{2})?\b/g) || []).filter((v, i, a) => a.indexOf(v) === i);
      console.log("el total del bloque: sesion " + conPasos.actividad_id + " (" + conPasos.fecha + "), lap "
        + (conRep && conRep.lap_idx) + " de " + (conRep && conRep.dist_m) + " m | pasos suman "
        + (suma ? comoEnLaPagina(suma) : "—") + " | reloj " + (delReloj ? comoEnLaPagina(delReloj) : "—")
        + " | relojes en la tarjeta: " + (relojes.join(", ") || "ninguno"));
      if (!conRep) {
        console.log("el total del bloque: sin repeticiones con pasos que comprobar");
      } else {
        /* La cabecera del bloque (una sola repeticion) se pinta con `g.tiempo_s`, y ese campo se comprueba en los
           datos: tiene que ser la suma de sus pasos, con la correccion dentro, y no el lap del reloj. Lo que pinte
           cada cajon se deja dicho, para poder mirarlo. */
        const sumaReps = ((conPasos.grupos || []).concat(conPasos.series || []))
          .map((g) => ({ g: g, rep: (g.reps || []).find((r) => (r.pasos || []).length) })).filter((x) => x.rep)[0];
        const relojGrande = sumaReps && Number(sumaReps.rep.lap_del_reloj_s || sumaReps.rep.tiempo_del_reloj_s || 0) > 900;
        if (relojGrande && Math.abs(Number(sumaReps.g.tiempo_s) - suma) > 0.005) {
          fallos.push("el bloque del 1.500 lleva un tiempo que no es la suma de sus pasos: " + sumaReps.g.tiempo_s
            + " s frente a " + suma + " s");
        } else if (relojGrande && Math.abs(Number(sumaReps.g.tiempo_s) - Number(sumaReps.rep.lap_del_reloj_s || 0)) < 0.005) {
          fallos.push("el bloque del 1.500 lleva el tiempo del reloj (" + sumaReps.g.tiempo_s + " s) en vez de la suma de sus pasos");
        }
        if (relojes.filter((t) => /^22:2/.test(t)).length) {
          console.log("ojo: en la tarjeta se ve un tiempo 22:2x (el del reloj del 1.500)");
        }
        /* Y el acumulado de la tabla tiene que terminar justo en la suma de los pasos: es el total que lee. */
        if (vistoPasos.indexOf("Acumulado") < 0) {
          fallos.push("la tabla de pasos no lleva la columna del acumulado");
        } else if (!esta(suma)) {
          fallos.push("el acumulado de la tabla no termina en la suma de los pasos (" + comoEnLaPagina(suma) + ")"
            + " · relojes que pinta: " + (relojes.join(", ") || "ninguno"));
        }
      }
    }
  } catch (e) {
    fallos.push("pintar una sesion con pasos de cada 100 revienta: " + e.message);
  }
}

/* El resumen tiene que traer los tres mejores de cada prueba: el atleta los pidio ahi, con tiempo y fecha. */
{
  const html = String(pintados.resPruebas || "");
  if (!html) {
    fallos.push("el resumen no pinta la tabla de los mejores de cada prueba");
  } else {
    const faltan = ["1500", "escalera", "30 minutos", "series de 100 cada 1:30"].filter((n) => html.indexOf(n) < 0);
    if (faltan.length) fallos.push("al resumen le faltan pruebas: " + faltan.join(", "));
  }
}

const nParrafos = (val.match(/ent-parrafo/g) || []).length;
const nDianas = (val.match(/<tr>/g) || []).length;

console.log("vistas: " + secciones.length + " | enlaces del menu: " + enlaces.length + " | ids que usa el JS: " + ids_js.size);
/* Si en algun cajon del portal aparece el tiempo del reloj del 1.500, hay que saber donde: el atleta lo ve. */
const cajonesConElReloj = Object.keys(pintados).filter((k) => String(pintados[k]).indexOf("22:2") >= 0);
console.log("cajones que enseñan un tiempo 22:2x (el del reloj es 22:20): " + (cajonesConElReloj.join(", ") || "ninguno"));
/* ---------- el parte guardado en el navegador no puede reponer el tiempo del reloj ---------- */
/* El caso que traia de cabeza al atleta: el parte guardado en el navegador llevaba el tiempo del reloj del 1.500
   (1.340,19 s, o sea 22:20) y al reabrir la sesion tapaba la correccion de la base (1.330,17 s = 22:10,17). El
   numero del reloj no es una correccion suya, asi que no se repone. Si de verdad escribio un tiempo, ese si vuelve. */
try {
  const pendiente = ((dp.partes || {}).pendientes || []).filter((p) => String(p.actividad_id) === "1543")[0]
    || ((dp.partes || {}).pendientes || [])[0];
  const bloque = pendiente && (pendiente.grupos || []).filter((g) => Math.round(Number(g.metros)) === 1500)[0];
  if (!bloque || typeof sandbox.reponerApuntado !== "function") {
    console.log("parte guardado: no hay bloque de 1.500 que probar");
  } else {
    const copia = () => JSON.parse(JSON.stringify(bloque));
    const guardando = (tiempo) => almacen.setItem("iregua.partes.v1", JSON.stringify(
      [{ actividad_id: pendiente.actividad_id, series: [{ laps: bloque.laps || [], tiempo_s: tiempo }] }]));

    guardando(bloque.reps[0].lap_del_reloj_s);            /* tal como estaba guardado: el tiempo del reloj */
    const conElDelReloj = { actividad_id: pendiente.actividad_id, grupos: [copia()] };
    sandbox.reponerApuntado(conElDelReloj);
    const trasReponer = Number(conElDelReloj.grupos[0].tiempo_s);

    guardando(1310.5);                                     /* un tiempo escrito de verdad por el atleta */
    const conElSuyo = { actividad_id: pendiente.actividad_id, grupos: [copia()] };
    sandbox.reponerApuntado(conElSuyo);
    const trasEscribir = Number(conElSuyo.grupos[0].tiempo_s);

    if (Math.abs(trasReponer - Number(bloque.reps[0].lap_del_reloj_s)) < 0.05) {
      fallos.push("el parte guardado en el navegador vuelve a poner el tiempo del reloj ("
        + bloque.reps[0].lap_del_reloj_s + " s) por encima de la corrección");
    } else if (Math.abs(trasEscribir - 1310.5) > 0.05) {
      fallos.push("un tiempo escrito de verdad por el atleta no se repone al reabrir: " + trasEscribir);
    } else {
      console.log("parte guardado: el tiempo del reloj (" + bloque.reps[0].lap_del_reloj_s
        + " s) no tapa la corrección (" + trasReponer + " s), y el que escribe él (" + trasEscribir + " s) vuelve");
    }
    almacen.removeItem("iregua.partes.v1");
  }
} catch (e) {
  fallos.push("no se pudo probar el parte guardado en el navegador: " + e.message);
}

console.log("cajones pintados: " + Object.keys(pintados).length);
console.log("sesiones pinchables: " + pinchables.join(", ") + " | oyente global: " + (typeof sandbox.montarFilasPinchables === "function" ? "si" : "no"));
console.log("entrenamientos sin reloj en las listas: " + (conSinReloj.join(", ") || "ninguno") + " | pinchables: " + (conApuntado.join(", ") || "ninguno"));
console.log("gimnasio: tabla de sesion " + (pintados.gsTabla ? "si" : "no") + " | peticiones " + (pintados.gsLista ? "si" : "no"));
console.log("mis pases: tabla " + (pintados.psTabla ? "si" : "no") + " | mejor dia tramo a tramo " + (pintados.psMejor ? "si" : "no"));
console.log("valoracion del entrenador: parrafos " + nParrafos + " | dianas " + nDianas);
console.log("boton del Garmin: " + (typeof sandbox.traerDelGarmin === "function" ? "si" : "no")
  + " | aviso en la pagina: " + (/id="garmAviso"/.test(html) ? "si" : "no"));

/* La plantilla del gimnasio: su caja, su boton y las dos funciones que hablan con el servidor. */
if (!documento.getElementById("gimPlantilla")) fallos.push("falta #gimPlantilla en la vista de Gimnasio");
if (!documento.getElementById("gimGuardar")) fallos.push("falta #gimGuardar (guardar lo del gimnasio)");
if (!documento.getElementById("gimFecha")) fallos.push("falta #gimFecha (el dia del gimnasio)");
if (typeof sandbox.pintarPlantillaGimnasio !== "function" || typeof sandbox.guardarGimnasio !== "function"
    || typeof sandbox.anadirEjercicioGimnasio !== "function") {
  fallos.push("faltan pintarPlantillaGimnasio/guardarGimnasio/anadirEjercicioGimnasio (la plantilla del gimnasio no va)");
}
if (!/escrito el/.test(html)) fallos.push("el informe del entrenador no dice cuando se escribio (falta 'escrito el ...')");
console.log("gimnasio: plantilla en la vista " + (documento.getElementById("gimPlantilla") ? "si" : "no"));

/* ---------- 12. la fuerza que sostiene el hombro (V1.4-01, V1.4-02) ---------------- */
{
  if (typeof sandbox.pintarFuerza !== "function") {
    fallos.push("el portal no sabe pintar la fuerza (falta pintarFuerza)");
  } else {
    const cajaD = (textoDe(cajones.fueDosis) + " " + String(pintados.fueDosis || "")).trim();
    const cajaC = (textoDe(cajones.fueCarga) + " " + String(pintados.fueCarga || "")).trim();
    const cajaS = (textoDe(cajones.fueSeguro) + " " + String(pintados.fueSeguro || "")).trim();
    const estados = ["sin empezar", "a medias", "cumplida"];
    if (!cajaD) fallos.push("la tarjeta de la dosis preventiva se queda en blanco");
    if (!estados.some((e) => cajaD.indexOf(e) >= 0)) {
      fallos.push("la dosis preventiva no dice su estado (" + estados.join(" / ") + ")");
    }
    if (cajaD.indexOf("T.7") < 0) fallos.push("la dosis preventiva no cita el anexo T.7");
    if (cajaD.indexOf("sesiones por semana") < 0) fallos.push("la dosis preventiva no dice la dosis que pide el anexo");
    if (!cajaC || cajaC.indexOf("kg") < 0) fallos.push("la carga de la fuerza no dice los kilos que se han levantado");
    if (cajaC.indexOf("RPE") < 0) fallos.push("la carga de la fuerza no dice nada del RPE (sin el, no se sabe si fue dura)");
    if (!cajaS) fallos.push("el cajon de avisos de la fuerza se queda sin pintar");
    const f = JSON.parse(datos).fuerza || {};
    console.log("fuerza: dosis " + f.estado + " (" + ((f.cita || []).join(", ") || "sin cita") + "), semana "
      + ((f.semana || {}).sesiones) + " sesion(es), " + ((f.semana || {}).volumen_kg) + " kg");
  }
}

/* Una base sin una sola fila de gimnasio: la dosis dice "sin empezar" y sigue citando T.7 (V1.4-02). */
{
  const copia = JSON.parse(datos);
  copia.fuerza = Object.assign({}, copia.fuerza, {
    estado: "sin empezar", hechas: 0, cita: ["T.7"],
    semana: Object.assign({}, copia.fuerza && copia.fuerza.semana, { sesiones: 0, series: 0, repeticiones: 0, volumen_kg: 0, con_rpe: 0, por_dia: {} }),
  });
  const htmlSinGim = html.replace(/<script id="datos"[^>]*>[\s\S]*?<\/script>/,
    '<script id="datos" type="application/json">' + JSON.stringify(copia) + "<\/script>");
  if (htmlSinGim === html) {
    console.log("fuerza sin gimnasio: no se ha podido cambiar el paquete de datos en la pagina");
  } else {
    const cajones2 = {};
    ids_html.forEach((id) => { cajones2[id] = elemento(id); });
    if (cajones2.datos) cajones2.datos.textContent = JSON.stringify(copia);
    const doc2 = Object.assign({}, documento, { getElementById(id) { return cajones2[id] || (cajones2[id] = elemento(id)); } });
    const caja2 = Object.assign({}, sandbox, { document: doc2 });
    vm.createContext(caja2);
    try {
      vm.runInContext(js, caja2, { timeout: 30000, filename: "app.js" });
      caja2.pintarFuerza();
      const visto = (textoDe(cajones2.fueDosis) + " " + String(pintados.fueDosis || "")).trim();
      if (visto.indexOf("sin empezar") < 0) fallos.push("sin gimnasio apuntado, la dosis no dice \"sin empezar\": " + visto.slice(0, 120));
      if (visto.indexOf("T.7") < 0) fallos.push("sin gimnasio apuntado, la dosis deja de citar T.7");
      console.log("fuerza sin gimnasio: la dosis dice \"sin empezar\" y cita T.7");
    } catch (e) {
      fallos.push("el portal no se puede arrancar con la base sin gimnasio: " + e.message);
    }
  }
}

if (fallos.length) {
  console.log("\nFALLA:\n- " + fallos.join("\n- "));
  process.exit(1);
}
console.log("\nOK: el cuadro de mando arranca, pinta y todos los ids cuadran.");
