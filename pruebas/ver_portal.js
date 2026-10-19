// Ejecuta el JS del panel con datos reales y ensena lo que calcula (no solo que no reviente).
// Uso: node ver_panel.js <panel.html>
const fs = require("fs");
const vm = require("vm");

const ruta = process.argv[2] || "cuadro/panel.html";
const html = fs.readFileSync(ruta, "utf8");
const js = html.match(/<script>([\s\S]*)<\/script>/)[1];

const escrito = {};
function elemento(id) {
  const e = {
    id, dataset: {}, style: {}, value: "", textContent: "",
    classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
    addEventListener() {}, appendChild() {}, removeChild() {},
    querySelector() { return elemento("hijo"); }, querySelectorAll() { return []; },
    getAttribute(n) { return n === "href" ? "#" + id : null; }, setAttribute() {}, click() {},
  };
  Object.defineProperty(e, "innerHTML", {
    get() { return escrito[id] || ""; },
    set(v) { escrito[id] = v; },
  });
  Object.defineProperty(e, "textContent", {
    get() { return escrito[id + ":texto"] || ""; },
    set(v) { escrito[id + ":texto"] = v; },
  });
  return e;
}
const cache = new Map();
const doc = {
  getElementById(id) { if (!cache.has(id)) cache.set(id, elemento(id)); return cache.get(id); },
  querySelectorAll(sel) {
    if (sel === "#menu a") return ["resumen", "competicion", "plan", "entrenos", "gimnasio", "apuntar", "volumen", "bici"].map(elemento);
    if (sel === ".vista") return ["resumen", "competicion", "plan", "apuntar", "entrenos", "gimnasio", "bici", "volumen"].map(elemento);
    if (sel === ".pestanas") {
      const barra = elemento("pestComp");
      barra.querySelectorAll = () => ["c-mejores", "c-comparar", "c-todas"].map(p => {
        const b = elemento("b-" + p); b.dataset = { p }; return b;
      });
      return [barra];
    }
    return [];
  },
  querySelector() { return elemento("x"); },
};
const almacen = {};
const sandbox = {
  document: doc, console,
  window: { addEventListener() {}, scrollTo() {}, location: { hash: "" } },
  location: { hash: "" },
  localStorage: { getItem: k => (k in almacen ? almacen[k] : null), setItem: (k, v) => { almacen[k] = v; }, removeItem: k => { delete almacen[k]; } },
  navigator: { clipboard: { writeText: () => Promise.resolve() } },
  URL: { createObjectURL: () => "blob:x", revokeObjectURL() {} },
  Blob: function () {}, Date, Math, JSON, Set, Array, Object, String, Number, Promise,
};
vm.createContext(sandbox);
vm.runInContext(js, sandbox, { timeout: 30000 });

const limpio = (t) => (t || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
const titulo = (t) => console.log("\n=== " + t + " ===");

titulo("PREPARACION (vista Resumen)");
console.log(limpio(escrito["preparacion"]));

titulo("COMPARADOR: " + (escrito["cmpCuenta:texto"] || escrito["cmpCuenta"] || ""));
console.log(limpio(escrito["cmpTabla"]).slice(0, 900));
titulo("NOTA DEL COMPARADOR");
console.log(escrito["cmpNota:texto"]);
titulo("GRAFICO: puntos dibujados");
const pts = (escrito["cmpGrafico"] || "").match(/<circle/g);
console.log((pts || []).length + " puntos | " + ((escrito["cmpGrafico"] || "").match(/objetivo/g) || []).length + " marca(s) de objetivo | " +
            (((escrito["cmpGrafico"] || "").match(/class="meta"/g) || []).length) + " linea de objetivo");

titulo("TODAS LAS MARCAS: " + (escrito["fCuenta:texto"] || ""));
console.log(limpio(escrito["fTabla"]).slice(0, 700));

titulo("MENU");
["menuComp", "menuPlan", "menuPie"].forEach(id => console.log(id + ": " + limpio(escrito[id] || escrito[id + ":texto"])));
