"""Baja TODOS los resultados oficiales del nadador desde la intranet de la RFEN.

Camino (todo con peticiones GET normales, sin navegador):
  1. La pagina publica `intranet.rfen.es/buscarPersonas` tiene un formulario que no
     envia nada al servidor: arma una peticion a `FormularioAjaxProcesar` con
     x_nombre / x_apellidos / x_genero / buscar=1 y pinta la respuesta en un div.
  2. Esa respuesta trae una fila por persona con un enlace
     `ConsultarHistorial?d=<nombre>&e=<hash opaco>` — el `e` es la credencial.
  3. `ConsultarHistorial.dcl?x_OPCION=MejoresMarcas` = la mejor marca de cada prueba.
     `ConsultarHistorial.dcl?x_OPCION=ResultadosNatacion` = TODAS las marcas.
  4. Esa tabla viene paginada de 10 en 10 y no acepta un tamano de pagina mayor
     (probado eje=30/60/200/1000: siempre 10 filas), asi que se recorren todas las
     paginas y se juntan. Eso es el "todos los resultados de una vez".

Uso:
    .venv/Scripts/python.exe scripts/rfen_historial.py
    .venv/Scripts/python.exe scripts/rfen_historial.py --nombre NOMBRE --apellidos "APELLIDOS" --genero M

Salida (dentro del proyecto):
    data/competicion/historial_rfen.csv     todas las marcas, una por linea
    data/competicion/historial_rfen.json    lo mismo, con los campos nombrados
    data/competicion/mejores_marcas.csv     la mejor marca de cada prueba
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://intranet.rfen.es"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
CAMPOS = ["CLUB", "FECHA", "LUGAR", "ESTILO", "DISTANCIA", "CRONO", "PISCINA", "PARCIAL", "RELEVO", "RESULTADO"]


def bajar(url: str, intentos: int = 3) -> str:
    """Descarga una URL y la decodifica (el servidor contesta en ISO-8859-1)."""
    ultimo = None
    for n in range(intentos):
        try:
            pet = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-ES,es"})
            with urllib.request.urlopen(pet, timeout=45) as r:
                return r.read().decode("latin-1", "replace")
        except Exception as e:  # red inestable
            ultimo = e
            time.sleep(1.5 * (n + 1))
    raise RuntimeError("no se pudo bajar %s: %s" % (url, ultimo))


def buscar_persona(nombre: str, apellidos: str, genero: str) -> tuple[str, str]:
    """Devuelve (etiqueta, e) de la primera persona que coincide."""
    q = urllib.parse.urlencode({"x_nombre": nombre, "x_apellidos": apellidos, "x_genero": genero, "buscar": "1"})
    t = bajar("%s/FormularioAjaxProcesar?%s" % (BASE, q))
    m = re.search(r'href="ConsultarHistorial\?d=([^&"]+)&e=([0-9A-F]+)"', t, re.I)
    if not m:
        raise RuntimeError("la busqueda no devolvio ninguna persona (respuesta de %d bytes)" % len(t))
    return urllib.parse.unquote(m.group(1)).strip(), m.group(2)


def texto_celda(c: str) -> str:
    """Texto de una celda de la tabla.

    OJO: las columnas PARCIAL y RELEVO no llevan texto, llevan un icono: verde (fa-check) = si,
    rojo (fa-remove) = no. Si se limpia el HTML a lo bruto se pierde el dato y las dos columnas
    salen vacias en todas las filas (paso justo eso: 577 marcas con el parcial en blanco).
    """
    bajo = c.lower()
    checo, cruz = "fa-check" in bajo, "fa-remove" in bajo
    if checo and cruz:
        return "S,N"
    if checo:
        return "S"
    if cruz:
        return "N"
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()


def filas_de_tabla(t: str) -> list[list[str]]:
    """Saca las filas de la tabla de resultados (sin la cabecera)."""
    filas = []
    for f in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", t):
        celdas = [texto_celda(c) for c in re.findall(r"(?s)<t[dh][^>]*>(.*?)</t[dh]>", f)]
        if celdas and celdas[0].upper() != "CLUB":
            filas.append(celdas)
    return filas


def historial(e: str, opcion: str = "ResultadosNatacion", pausa: float = 0.3,
              desde: int = 2016, hasta: int = 2027, por_anio: bool = True):
    """Recorre TODAS las paginas del historial. Devuelve (filas_distintas, total_declarado, paginas, filas_brutas).

    Dos trucos, los dos necesarios para que salgan TODAS las marcas en una sola pasada:
      * `order=DATE`: sin orden explicito el servidor devuelve las paginas desordenadas.
      * trocear por anos con `x_FILTRO5_INICIO/FIN`: la tabla completa son 60 paginas de 10 filas
        y, con fechas repetidas, el servidor desempata de forma arbitraria, asi que en una pasada
        larga se cuelan filas repetidas y se pierden otras. Con un ano por consulta (<= 10
        paginas) cada tramo es estable y la union de todos los tramos es completa.
    """
    todo: list[list[str]] = []
    vistas: set[tuple] = set()
    brutas = 0
    total = 0
    paginas = 0
    if por_anio:
        tramos = ["&x_FILTRO5_INICIO=%d-01-01&x_FILTRO5_FIN=%d-12-31" % (y, y) for y in range(desde, hasta + 1)]
    else:
        tramos = [""]
    for extra in tramos:
        antes = len(vistas)
        pag_tramo, total_tramo, npag = 1, 0, 0
        while True:
            url = ("%s/ConsultarHistorial.dcl?eje=30&page=%d&x_VARIABLE=&x_OPCION=%s&e=%s&order=DATE%s"
                   % (BASE, pag_tramo, opcion, e, extra))
            t = bajar(url)
            if pag_tramo == 1:
                m = re.search(r"Total Registros:\s*(\d+)", t)
                total_tramo = int(m.group(1)) if m else 0
                total += total_tramo
                m = re.search(r"P.gina\s*\d+\s*de\s*(\d+)", t)
                npag = int(m.group(1)) if m else 0
                paginas += npag
            filas = filas_de_tabla(t)
            brutas += len(filas)
            for f in filas:
                vistas.add(tuple(f))
            if (npag and pag_tramo >= npag) or pag_tramo > 60:
                break
            pag_tramo += 1
            time.sleep(pausa)
        todo = [list(f) for f in vistas]
        if total_tramo or len(vistas) - antes:
            print("   %-14s declaradas %-4d paginas %-3d nuevas %3d (distintas %3d)"
                  % (extra[16:26] if extra else "todo", total_tramo, npag, len(vistas) - antes, len(vistas)))
    return todo, total, paginas, brutas


def segundos(marca: str) -> float | None:
    """'00:05:10.00' -> 299.39 segundos. None si la marca es imposible.

    En la base de la RFEN hay marcas corruptas tipo '00:1394:14.12' (minutos > 59):
    se descartan para que no figuren como 'mejor' marca de una prueba.
    """
    m = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)$", (marca or "").strip())
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    if mi > 59 or s >= 60 or h > 5:
        return None
    return h * 3600 + mi * 60 + s


def mejores(filas: list[list[str]]) -> list[list[str]]:
    """La mejor marca de cada (estilo, distancia, piscina, crono)."""
    mejor: dict[tuple, list[str]] = {}
    for f in filas:
        if len(f) < 10:
            continue
        clave = (f[3], f[4], f[6], f[5])
        s = segundos(f[9])
        if s is None:
            continue
        if clave not in mejor or s < (segundos(mejor[clave][9]) or 9e9):
            mejor[clave] = f
    orden = sorted(mejor.values(), key=lambda f: (f[3], int(re.sub(r"\D", "", f[4]) or 0), f[6]))
    return orden


def _persona_local() -> dict:
    """Los datos del nadador, del fichero local que no se sube. Sin el, vacio: los pasa quien llame."""
    import json as _json
    import pathlib as _pathlib

    f = _pathlib.Path(__file__).resolve().parent.parent / "data" / "rfen_persona.json"
    try:
        return _json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Baja el historial completo de la RFEN")
    # Los datos del nadador no se escriben aqui: se leen de `data/rfen_persona.json` (que no se sube, porque
    # `data/` se queda fuera) y, si no esta, hay que pasarlos a mano.
    persona = _persona_local()
    ap.add_argument("--nombre", default=persona.get("nombre", ""))
    ap.add_argument("--apellidos", default=persona.get("apellidos", ""))
    ap.add_argument("--genero", default="M")
    ap.add_argument("--salida", default="data/competicion")
    a = ap.parse_args()

    etiqueta, e = buscar_persona(a.nombre, a.apellidos, a.genero)
    print("Nadador: %s  (e=%s)" % (etiqueta, e))

    print("\nTodas las marcas (x_OPCION=ResultadosNatacion, un tramo por ano):")
    filas, total, paginas, brutas = historial(e, "ResultadosNatacion")
    print("   -> %d marcas distintas (el servidor declara %d; %d filas servidas, %d repetidas)"
          % (len(filas), total, brutas, brutas - len(filas)))

    print("\nMejor marca de cada prueba (x_OPCION=MejoresMarcas):")
    filas_mejores, _, _, _ = historial(e, "MejoresMarcas", por_anio=False)
    print("   -> %d filas" % len(filas_mejores))

    fuera = Path(a.salida)
    fuera.mkdir(parents=True, exist_ok=True)

    with (fuera / "historial_rfen.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(CAMPOS)
        w.writerows(filas)

    datos = [dict(zip(CAMPOS, f)) for f in filas]
    for d in datos:
        d["segundos"] = segundos(d["RESULTADO"])
    (fuera / "historial_rfen.json").write_text(
        json.dumps({"nadador": etiqueta, "e": e, "total_declarado": total, "marcas": datos},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    mm = mejores(filas)
    with (fuera / "mejores_marcas.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(CAMPOS + ["S/100 m", "PISCINA"])
        for f in mm:
            s = segundos(f[9])
            dist = int(re.sub(r"\D", "", f[4]) or 0)
            w.writerow(f + ["%.1f" % (s * 100.0 / dist) if s and dist else "", f[6] + "m"])

    print("\nGuardado en %s/: historial_rfen.csv (%d filas), historial_rfen.json, mejores_marcas.csv (%d pruebas)"
          % (fuera, len(filas), len(mm)))

    print("\nLibre, mejores marcas por distancia y piscina:")
    for f in mm:
        if f[3].lower() != "libre":
            continue
        s = segundos(f[9])
        dist = int(re.sub(r"\D", "", f[4]) or 0)
        print("   %5s m  %-3s  %-10s  %-22s %s" %
              (f[4], f[6], f[9], (f[1] + " " + f[2])[:22], "%.1f s/100" % (s * 100.0 / dist) if s and dist else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
