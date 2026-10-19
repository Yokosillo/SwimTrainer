/* Comprueba el editor del parte en un DOM de verdad (jsdom): lo que el atleta toca con el raton y el teclado,
   que es justo lo que un truco de cadenas no ve. Aqui se pillo el bucle infinito de guardar/repintar.

   Hace falta jsdom:  npm install   (una vez, en la carpeta del proyecto).
   Uso:  node pruebas/comprobar_dom.js [cuadro/panel.html]

   Se abre una sesion del cuadro de mando, se escribe en las casillas como el atleta y se comprueba que lo
   apuntado se queda: la distancia del bloque (cabecera), el "cada" de las series y la distancia de una
   repeticion de dentro del grupo. */
const fs = require("fs");

let JSDOM;
try { ({ JSDOM } = require("jsdom")); } catch (e) {
  console.log("sin jsdom instalado -> me salto la comprobacion del editor (npm install en el proyecto).");
  process.exit(0);
}

const RUTA = process.argv[2] || "cuadro/panel.html";
const html = fs.readFileSync(RUTA, "utf8");
const dom = new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true, url: "http://127.0.0.1:8181/" });
const w = dom.window, d = w.document;

let fallos = 0, hechas = 0;
function comprobar(que, bien, visto) {
  hechas++;
  console.log("  [" + (bien ? "OK  " : "FALLA") + "] " + que + (visto === undefined ? "" : " -> " + visto));
  if (!bien) fallos++;
}
const esc = (t) => JSON.stringify(String(t === undefined ? "" : t));

setTimeout(() => {
  w.Element.prototype.scrollIntoView = function () {};   // jsdom no lo trae y abrirParte lo usa

  try {
    const ids = w.eval("(PPA().pendientes || []).map((s) => s.actividad_id)");
    const sesion = ids.filter((id) => {
      const gs = w.eval("PPA().pendientes.filter((s) => String(s.actividad_id) === '" + id + "')[0].grupos || []");
      return gs.some((g) => (g.reps || []).length < 2 && !g.no_cuenta) && gs.some((g) => (g.reps || []).length >= 2);
    })[0];
    if (sesion === undefined) {
      console.log("  [----] no hay ninguna sesion con un bloque de una sola serie y otro de series.");
    } else {
      const grupos = () => w.eval("PPA().pendientes.filter((s) => String(s.actividad_id) === '" + sesion + "')[0].grupos");
      const grupo = (k) => w.eval("(() => { const x = PPA().pendientes.filter((s) => String(s.actividad_id) === '" + sesion + "')[0].grupos[" + k + "];"
        + " return { metros: x.metros, rep_m: x.rep_m, cada_s: x.cada_s, tiempo_s: x.tiempo_s, ritmo: x.ritmo_100,"
        + " d0: x.reps && x.reps[0] && x.reps[0].dist_m, d1: x.reps && x.reps[1] && x.reps[1].dist_m }; })()");
      const gs = grupos();
      const kUna = gs.findIndex((g) => (g.reps || []).length < 2 && !g.no_cuenta);
      const kSerie = gs.findIndex((g) => (g.reps || []).length >= 2 && !g.no_cuenta);

      w.eval("abrirParte('" + sesion + "', null, true)");
      const cajas = () => Array.from(d.querySelectorAll("#entrenosDetalle .grupo"));
      comprobar("el detalle de la sesion se pinta entero", cajas().length === gs.length,
                cajas().length + " de " + gs.length + " bloques");
      w.eval("localStorage.removeItem && 0");   // (el almacen de jsdom arranca limpio)

      /* 1. La distancia del bloque, en la cabecera (y en un bloque de UNA sola serie, que es lo que fallaba). */
      const caja = cajas()[kUna], cab = caja.querySelector(".grupo-cab");
      const inM = cab ? cab.querySelector("input.mini-num") : null;
      comprobar("un bloque de una sola serie deja cambiar la distancia en su cabecera", !!inM,
                cab ? esc(cab.textContent.trim()) : "sin cabecera");
      comprobar("y ese bloque no pide el \"cada\" (no hay repeticiones que espaciar)",
                (caja.textContent || "").indexOf("Cada") < 0);
      if (inM) {
        inM.value = "333";
        inM.dispatchEvent(new w.Event("input", { bubbles: true }));
        comprobar("escribir la distancia cambia los metros del bloque", grupo(kUna).metros === 333,
                  esc(grupo(kUna).metros));
        inM.dispatchEvent(new w.Event("change", { bubbles: true }));   // aqui reventaba el bucle guardar/repintar
        const inM2 = cajas()[kUna].querySelector(".grupo-cab input.mini-num");
        comprobar("y sigue ahi despues de repintar (sin reventar por el bucle de guardar/repintar)",
                  !!inM2 && inM2.value === "333" && grupo(kUna).metros === 333,
                  (inM2 ? esc(inM2.value) : "sin casilla") + " / " + grupo(kUna).metros + " m");
        comprobar("lo que se escribe en el detalle se guarda solo en el navegador",
                  w.eval("(leerPartes() || []).filter((p) => String(p.actividad_id) === '" + sesion + "').length") > 0);
      }

      /* 1b. La distancia Y el tiempo, en esa misma cabecera (el ritmo de cada cien sale solo): la fila aparte del
         tiempo del grupo ya no hace falta. */
      const inT = cajas()[kUna].querySelector(".grupo-cab input.mini-tiempo");
      comprobar("la cabecera de un bloque de una sola serie deja escribir el tiempo", !!inT,
                esc(cajas()[kUna].querySelector(".grupo-cab").textContent.trim()));
      comprobar("y ya no baja una fila de \"Tiempo del grupo\"",
                (cajas()[kUna].textContent || "").indexOf("Tiempo del grupo") < 0);
      if (inT) {
        inT.value = "6:00";
        inT.dispatchEvent(new w.Event("input", { bubbles: true }));
        const g = grupo(kUna);
        comprobar("el tiempo que escribe el atleta es el que vale (6:00 = 360 s)", Math.round(g.tiempo_s) === 360,
                  esc(g.tiempo_s));
        comprobar("y el ritmo de cada cien sale de el (333 m en 6:00 -> 1:48,1)", Math.round(g.ritmo) === 108,
                  esc(g.ritmo));
      }

      /* 2. El "cada" de un bloque de series. */
      const cajaSerie = cajas()[kSerie];
      const filaCada = Array.from(cajaSerie.querySelectorAll(".fila")).filter((f) => /Cada/.test(f.textContent))[0];
      const cada = filaCada ? filaCada.querySelector("input") : null;
      comprobar("un bloque de series si pide el \"cada\"", !!cada);
      if (cada) {
        cada.value = "2:00";
        cada.dispatchEvent(new w.Event("input", { bubbles: true }));
        comprobar("el cada que escribe el atleta es el que vale (2:00 = 120 s)",
                  Math.round(grupo(kSerie).cada_s) === 120, esc(grupo(kSerie).cada_s));
      }


      /* 3. La distancia de una repeticion de dentro del grupo. */
      const filas = Array.from(cajaSerie.querySelectorAll("tbody tr"));
      const celdas = filas[1] ? Array.from(filas[1].querySelectorAll("td")) : [];
      const inRep = celdas.map((td) => td.querySelector("input")).filter((x) => x)[0];
      comprobar("cada repeticion de un grupo tiene su casilla de metros", !!inRep, filas.length + " repeticiones pintadas");
      if (inRep) {
        inRep.value = "50";
        inRep.dispatchEvent(new w.Event("input", { bubbles: true }));
        const g = grupo(kSerie);
        comprobar("cambiar la distancia de una repeticion rehace los metros del grupo", g.metros !== 1900,
                  "100 + 50 + el resto = " + g.metros + " m");
        comprobar("con repeticiones distintas el grupo ya no dice una sola distancia", g.rep_m === null, esc(g.rep_m));
      }
      /* 4. La cabecera de un bloque con series dentro: sus metros y lo que duro (descansos incluidos), y sin
         casillas que tocar ahi: es la suma de lo de dentro, y la distancia se corrige repeticion a repeticion. */
      const cabSerie = cajaSerie.querySelector(".grupo-cab");
      const txtSerie = cabSerie ? cabSerie.textContent.replace(/\s+/g, " ") : "";
      comprobar("la cabecera de un bloque de series dice el total con sus descansos", /con descansos/.test(txtSerie),
                esc(txtSerie));
      comprobar("y ahi no hay nada que tocar (es la suma de lo de dentro)", cabSerie && !cabSerie.querySelector("input"),
                cabSerie && cabSerie.querySelector("input") ? "tiene casilla" : "sin casillas");
      comprobar("la cabecera de ese bloque canta el \"cada\"", /\u00b7 cada /.test(txtSerie), esc(txtSerie));
      comprobar("la cabecera dice los metros del bloque entero y ningun guion donde iria la distancia",
                txtSerie.indexOf("x\u2014") < 0 && /\d+ m \u00b7/.test(txtSerie),
                esc((txtSerie.match(/\d+ m \u00b7 [^ ]+\s*[^ ]*/) || ["nada"])[0]));

      /* 5. Un bloque que dice que tiene mas series de las que trae (pasa al corregir a mano el numero de
         series): las que faltan se ponen en la tabla, para poder escribirles el tiempo. Al atleta le
         "desaparecian las series": el bloque decia 2x50 y dentro solo habia una. */
      w.eval("(() => { const g = PPA().pendientes.filter((s) => String(s.actividad_id) === '" + sesion + "')[0].grupos[" + kSerie + "];"
        + " g.reps = (g.reps || []).slice(0, 1); g.n_reps = 2; g.rep_m = g.reps[0] ? g.reps[0].dist_m : 50;"
        + " g.metros = g.rep_m * 2; repintarDetalle(); })()");
      const filasCuadradas = cajas()[kSerie].querySelectorAll("table.tabla-reps tbody tr").length;
      comprobar("un bloque que declara mas series de las que trae pone las que faltan (2x50 con una sola dentro)",
                filasCuadradas === 2, filasCuadradas + " series en la tabla");
      /* 5b. El cada de un bloque juntado a mano: es el tiempo de la repeticion mas el descanso que va detras de
         ella, redondeado a los 5 s (el atleta: "el cada es el tiempo de la serie mas el descanso ... esto
         siempre hay que redondearlo, porque no es exacto con lo que pulso en la piscina"). */
      const descansos = w.eval("PPA().pendientes.filter((s) => String(s.actividad_id) === '" + sesion
        + "')[0].grupos[" + kSerie + "].reps.map((r) => r.descanso_s)");
      const todosDescansos = descansos.slice(0, -1);   /* la ultima repeticion no lleva descanso detras */
      comprobar("cada repeticion de un bloque trae el descanso que va detras",
                todosDescansos.length > 0 && todosDescansos.every((x) => typeof x === "number" && x >= 0),
                esc(descansos));
      const cadaSuelto = w.eval("(() => { const g = PPA().pendientes.filter((s) => String(s.actividad_id) === '"
        + sesion + "')[0].grupos[" + kSerie + "]; g.cada_s = null; g.descanso_s = null; g.cada_apuntado = null;"
        + " return cadaDeducido(g); })()");
      comprobar("y el cada sale de la repeticion mas su descanso, redondeado a los 5 s (1:23,3 + 0:27 -> 1:50)",
                cadaSuelto % 5 === 0 && cadaSuelto > 100 && cadaSuelto < 130, esc(cadaSuelto));
      /* 7. El cada: viene relleno (no en una etiqueta al lado) y lo que escribe el atleta se guarda. */
      const filaDelCada = Array.from(cajas()[kSerie].querySelectorAll(".fila"))
        .filter((f) => /Cada \(/.test(f.textContent))[0];
      const cajaDelCada = filaDelCada ? filaDelCada.querySelector("input.mini-tiempo") : null;
      comprobar("el cada del bloque viene relleno y sin etiqueta que lo anuncie",
                !!cajaDelCada && cajaDelCada.value !== "" && !/estimado/.test(filaDelCada.textContent),
                esc(cajaDelCada && cajaDelCada.value));
      if (cajaDelCada) {
        cajaDelCada.value = "2:30";
        cajaDelCada.dispatchEvent(new w.Event("input", { bubbles: true }));
        cajaDelCada.dispatchEvent(new w.Event("change", { bubbles: true }));
        const suyo = (JSON.parse(w.localStorage.getItem("entrenador.partes.v1") || "[]")
          .filter((p) => String(p.actividad_id) === String(sesion))[0] || { series: [] }).series
          .filter((x) => x.cada_apuntado === "2:30")[0];
        comprobar("y el cada que escribe el atleta se guarda con su marca (cada_s 150, apuntado 2:30)",
                  !!suyo && Number(suyo.cada_s) === 150,
                  esc(suyo && [suyo.cada_s, suyo.cada_apuntado]));
      }
      const filaT2 = cajas()[kSerie].querySelectorAll("table.tabla-reps tbody tr")[1];
      const cajaT2 = filaT2 ? filaT2.querySelector("input.mini-tiempo") : null;
      comprobar("la serie que faltaba deja escribirle el tiempo", !!cajaT2);
      if (cajaT2) {
        cajaT2.value = "1:01,7";
        cajaT2.dispatchEvent(new w.Event("input", { bubbles: true }));
        const reps = w.eval("PPA().pendientes.filter((s) => String(s.actividad_id) === '" + sesion
          + "')[0].grupos[" + kSerie + "].reps");
        comprobar("y el tiempo de esa serie se queda (1:01,7 = 62 s)",
                  reps.length === 2 && Math.round(reps[1].tiempo_s) === 62, esc(reps[1] && reps[1].tiempo_s));
      }
      /* 9. "Añadir serie" mete la serie DENTRO del bloque, no un bloque entero (el atleta: "cuando añado una
         serie me esta añadiendo un bloque entero, no solo una serie; tiene que añadir una serie dentro del
         bloque donde esta"). */
      const nReps = (k) => w.eval("(PPA().pendientes.filter((s) => String(s.actividad_id) === '" + sesion
        + "')[0].grupos[" + k + "].reps || []).length");
      const botonAnadir = Array.from(cajas()[kSerie].querySelectorAll("button"))
        .filter((b) => /Añadir serie/.test(b.textContent))[0];
      comprobar("el bloque de series trae el boton de añadir una serie", !!botonAnadir);
      if (botonAnadir) {
        const antesBloques = grupos().length, antesReps = nReps(kSerie);
        botonAnadir.dispatchEvent(new w.Event("click", { bubbles: true }));
        comprobar("añadir una serie no mete un bloque nuevo", grupos().length === antesBloques,
                  grupos().length + " de " + antesBloques + " bloques");
        comprobar("añadir una serie deja una repeticion mas dentro del bloque", nReps(kSerie) === antesReps + 1,
                  nReps(kSerie) + " de " + (antesReps + 1));
        const cabSerie = (cajas()[kSerie].querySelector(".grupo-cab") || {}).textContent || "";
        comprobar("y la cabecera del bloque cuenta la serie nueva", /\d+x\d+/.test(cabSerie), esc(cabSerie));
      }

      /* 7b. En el resumen tiene que salir lo nadado en los ultimos 7 dias (el atleta: "en el resumen deberia
         salir lo que llevamos nadado en los ultimos siete dias"). */
      const kpi7 = Array.from(d.querySelectorAll("#kpis .kpi"))
        .map((c) => c.textContent || "").filter((t) => /ultimos 7 dias/.test(t))[0] || "";
      comprobar("el resumen dice lo nadado en los ultimos 7 dias",
                /\d/.test(kpi7) && / m /.test(kpi7 + " ") && /dias en el agua/.test(kpi7),
                esc(kpi7.slice(0, 110)));

      /* 8. Partir o juntar un bloque repinta el detalle: el scroll tiene que volver donde estaba (el atleta:
         "cada vez que pulso partir con intervalos o juntar se me va el scroll y no se donde estoy"). */
      const marco = d.getElementById("entrenosDetalle");
      if (marco && kSerie > 1) {
        marco.scrollTop = 240;
        w.eval("juntarGrupo(PPA().pendientes.filter((s) => String(s.actividad_id) === '" + sesion + "')[0], "
               + kSerie + ")");
        const trasJuntar = d.getElementById("entrenosDetalle").scrollTop;
        comprobar("juntar un bloque deja el scroll donde estaba", trasJuntar === 240, esc(trasJuntar));
      }
    }
  } catch (e) {
    comprobar("el editor no revienta al tocarlo", false, e.message + " | " + (e.stack || "").split("\n")[1]);
  }

  console.log(fallos ? ("FALLOS: " + fallos + " de " + hechas) : ("OK: el editor del parte se puede tocar (" + hechas + " comprobaciones)."));
  process.exit(fallos ? 1 : 0);
}, 400);
