#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Propone la migracion del conocimiento actual (Markdown + constantes) a TOML.

F2 no cambia el conocimiento canonico: este script solo **propone** ficheros TOML en
`data/derived/conocimiento/propuesta/` para que F3 los revise. Por defecto hace `--dry-run`;
para escribir hace falta `--apply --si` y se guarda una copia de la propuesta anterior.

No toca `informes/` ni `conocimiento/`. El motor sigue en v1.

Uso:
    python scripts/migrar_conocimiento.py                 # dry-run
    python scripts/migrar_conocimiento.py --apply --si    # escribe la propuesta (con backup)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

DESTINO = Path("data") / "derived" / "conocimiento" / "propuesta"


def _s(valor) -> str:
    return json.dumps("" if valor is None else str(valor), ensure_ascii=False)


def _lista(valores) -> str:
    return "[" + ", ".join(_s(x) for x in (valores or [])) + "]"


def _num(valor) -> str:
    if valor is None or valor == "":
        return "0.0"
    try:
        return repr(float(valor))
    except (TypeError, ValueError):
        return "0.0"


def _fuentes() -> tuple[str, int]:
    from entrenador import conocimiento

    datos = conocimiento.fuentes()
    if not datos:
        return "", 0
    lineas = ["# Propuesta generada desde el bloque `## Sources` del anexo T.", ""]
    for n in sorted(datos):
        f = datos[n]
        lineas += ["[[fuente]]", f'id = "FU-{n:03d}"', 'tipo = "articulo"',
                   f"titulo = {_s(f['titulo'])}", "autores = []", f"url = {_s(f['url'])}",
                   'doi = ""', f"cita = {_s(f['citas'][0] if f['citas'] else '')}",
                   "citas = ["]
        lineas += ["  " + _s(c) + "," for c in f["citas"]]
        lineas += ["]", 'poblacion = ""', 'intervencion = ""', 'resultado = ""',
                   'limitaciones = ""', 'certeza = ""', 'revisado_por = ""', 'revisado_en = ""',
                   f'legacy_id = "{n}"', f'notas = "Migrado del anexo T [{n}]."', ""]
    return "\n".join(lineas), len(datos)


def _afirmaciones() -> tuple[str, int]:
    from entrenador import conocimiento

    criterios = conocimiento.criterios()
    if not criterios:
        return "", 0
    lineas = ["# Propuesta: una afirmacion por clausula [criterio] del anexo T.",
              "# Sin fuente atomica ni firma: F3 las revisa, cita y firma.", ""]
    for i, x in enumerate(criterios, 1):
        lineas += ["[[afirmacion]]", f'id = "AF-{100 + i:03d}"', f"texto = {_s(x['afirmacion'])}",
                   'condiciones = ""', 'efecto = ""', 'direccion = ""', 'tamano = ""',
                   'aplicabilidad = ""', f"certeza = \"\"", 'estado = "propuesta"',
                   "criterio_firmado = false", 'firmado_por = ""', 'firmado_en = ""',
                   "fuentes = []", f'notas = "Extraida de {x["seccion"]} del anexo T; falta fuente y firma."', ""]
    return "\n".join(lineas), len(criterios)


def _parametros() -> tuple[str, int]:
    from entrenador import estimulos, plan_vivo, planificador, reglas

    valores = [
        ("minimo_ritmo_prueba_m", reglas.MINIMOS_OBLIGATORIOS["ritmo_prueba"], "m", "reglas.MINIMOS_OBLIGATORIOS"),
        ("minimo_velocidad_resistencia_m", reglas.MINIMOS_OBLIGATORIOS["velocidad_resistencia"], "m",
         "reglas.MINIMOS_OBLIGATORIOS"),
        ("ventana_decision_dias", estimulos.VENTANA_DIAS, "dias", "estimulos.VENTANA_DIAS"),
        ("minimo_continuo_m", estimulos.MIN_CONTINUO_M, "m", "estimulos.MIN_CONTINUO_M"),
        ("dias_sin_parar", estimulos.DIAS_SIN_PARAR, "dias", "estimulos.DIAS_SIN_PARAR"),
        ("tope_subida_semanal_pct", plan_vivo.TOPE_SUBIDA_PCT, "%", "plan_vivo.TOPE_SUBIDA_PCT"),
        ("umbral_cumplir_semana", plan_vivo.UMBRAL_CUMPLIR, "fraccion", "plan_vivo.UMBRAL_CUMPLIR"),
        ("bajada_por_deriva", plan_vivo.BAJADA_DERIVA, "fraccion", "plan_vivo.BAJADA_DERIVA"),
        ("tope_descarga", plan_vivo.TOPE_DESCARGA, "fraccion", "plan_vivo.TOPE_DESCARGA"),
        ("duro_h", planificador.DURO_H, "horas", "planificador.DURO_H"),
    ]
    lineas = ["# Propuesta: numeros del motor actual, sin duplicar todavia en el conocimiento canonico.", ""]
    for i, (nombre, valor, unidad, origen) in enumerate(valores, 1):
        lineas += ["[[parametro]]", f'id = "PA-{100 + i:03d}"', f"nombre = {_s(nombre)}",
                   f"valor = {_num(valor) if isinstance(valor, (int, float)) else _s(valor)}",
                   f"unidad = {_s(unidad)}", 'procedencia = "criterio_firmado"', 'fuente = ""',
                   'afirmacion = ""', 'firmado_por = ""', 'firmado_en = ""',
                   f'nota = "Extraido de {origen}; firma pendiente (F3-07)."', ""]
    return "\n".join(lineas), len(valores)


def _estimulos() -> tuple[str, int]:
    from entrenador import estimulos

    lineas = ["# Propuesta: clases de estimulo del motor actual.", ""]
    for i, (clave, v) in enumerate(estimulos.CLASES.items(), 1):
        lineas += ["[[estimulo]]", f'id = "ES-{100 + i:03d}"', f"nombre = {_s(v.get('nombre'))}",
                   f"entrena = {_s(v.get('entrena'))}", f"no_entrena = {_s(v.get('no_entrena'))}",
                   f"recuperacion_h = {_num(v.get('recuperacion'))}", 'coste = "medio"',
                   f"papel_400 = {_s(v.get('papel400'))}", f"papel_3000 = {_s(v.get('papel3000'))}",
                   f"senal = {_s(v.get('senal'))}", f"seccion_T = {_lista(v.get('seccion_T'))}",
                   f'notas = "Clase {clave} de estimulos.py; grado {v.get("grado", "criterio")}."', ""]
    return "\n".join(lineas), len(estimulos.CLASES)


def _recetas() -> tuple[str, int]:
    from entrenador import estimulos

    lineas = ["# Propuesta: recetas del motor actual. F3 las desglosa en pasos.", ""]
    for i, (clave, v) in enumerate(estimulos.RECETAS.items(), 1):
        sesion = v.get("sesion") or ""
        lineas += ["[[receta]]", f'id = "RE-{100 + i:03d}"', f"nombre = {_s(v.get('nombre'))}",
                   f"sesion = {_s(sesion)}", f"metros = {_num(v.get('metros'))}",
                   f"reps = {int(v.get('reps') or 1)}", f"dist_m = {_num(v.get('dist_m'))}",
                   f"ritmo_rel = {_s(v.get('rel_ritmo'))}", f"descanso_s = {_num(v.get('descanso_s'))}",
                   f"salida_s = {_num(v.get('salida'))}", f"desde_dia = {_s(v.get('desde'))}",
                   f"porque = {_s(v.get('porque'))}", 'progresion = ""', 'regresion = ""',
                   'afirmaciones = []', "pasos = [",
                   f'  {{ orden = 1, texto = {_s(sesion)}, tipo = "serie", metros = {_num(v.get("metros"))}, ritmo_100 = "", descanso_s = {_num(v.get("descanso_s"))}, material = "", intensidad = "ae3" }},',
                   "]", f'notas = "Receta {clave} de estimulos.py; falta desglose y fuentes (F3)."', ""]
    return "\n".join(lineas), len(estimulos.RECETAS)


def _reglas() -> tuple[str, int]:
    from entrenador import reglas

    lineas = ["# Propuesta: reglas del motor actual. Faltan condicion, accion y metrica (F3).", ""]
    for i, r in enumerate(reglas.REGLAS, 1):
        lineas += ["[[regla]]", f'id = "RG-{100 + i:03d}"', "version = 1",
                   f"enunciado = {_s(r.get('enunciado'))}", "cuando = {}", "entonces = {}",
                   "evidencia = []", "parametros = []", f"contraindicaciones = {_lista(['dolor_hombro', 'lesion_activa'])}",
                   "metrica_exito = {}", f"revisar_en_dias = 21", "confianza = 0.5",
                   'estado = "propuesta"', f'notas = "Regla {r.get("id")}: fuente {r.get("fuente")}; migracion pendiente (F3)."', ""]
    return "\n".join(lineas), len(reglas.REGLAS)


def _calendario() -> tuple[str, int]:
    from entrenador import planificador

    texto = "\n".join([
        "[calendario]",
        f"dias_entrenador = {_lista(planificador.DIAS_ENTRENADOR)}",
        f"dias_propios = {_lista(planificador.DIAS_PROPIOS)}",
        f"dia_bici = {_s(planificador.DIA_BICI)}",
        f"dias_calidad = {_lista(planificador.DIAS_CALIDAD)}",
        f"dias_largos = {_lista(planificador.DIAS_LARGOS)}",
        f"duro_h = {_num(planificador.DURO_H)}",
        'notas = "Propuesta desde planificador.py; el motor v1 sigue leyendo ese modulo."',
        "",
    ])
    return texto, 1


def proponer() -> dict[str, tuple[str, int]]:
    """Devuelve `{nombre_fichero: (texto, entidades)}`. No escribe nada."""
    return {
        "fuentes.toml": _fuentes(),
        "afirmaciones.toml": _afirmaciones(),
        "parametros.toml": _parametros(),
        "reglas.toml": _reglas(),
        "estimulos.toml": _estimulos(),
        "recetas.toml": _recetas(),
        "calendario.toml": _calendario(),
    }


def _resumen(propuesta: dict[str, tuple[str, int]]) -> str:
    lineas = ["Propuesta de migracion (TOML):"]
    for nombre, (texto, n) in propuesta.items():
        lineas.append(f"  {nombre:<22} {n:>3} entidades, {len(texto.encode('utf-8')):>6} bytes")
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Propone la migracion del conocimiento actual a TOML.")
    p.add_argument("--dry-run", action="store_true", help="solo muestra la propuesta (por defecto)")
    p.add_argument("--apply", action="store_true", help="escribe la propuesta en --destino")
    p.add_argument("--si", action="store_true", help="confirma --apply")
    p.add_argument("--destino", default=str(DESTINO), help=f"carpeta de propuesta (por defecto {DESTINO})")
    args = p.parse_args(argv)

    if args.apply and args.dry_run:
        print("Elige --dry-run o --apply, no las dos.")
        return 2
    propuesta = proponer()
    print(_resumen(propuesta))
    if not args.apply:
        print(f"\n(dry-run) No se ha escrito nada. Destino previsto: {args.destino}")
        print("Para escribir: --apply --si")
        return 0
    if not args.si:
        print("\n--apply necesita --si (confirmacion). No se ha escrito nada.")
        return 2

    destino = Path(args.destino)
    if destino.exists():
        sello = datetime.now().strftime("%Y%m%d-%H%M%S")
        copia = destino.with_name(destino.name + f".bak-{sello}")
        shutil.copytree(destino, copia)
        print(f"Backup de la propuesta anterior: {copia}")
    destino.mkdir(parents=True, exist_ok=True)
    for nombre, (texto, _) in propuesta.items():
        (destino / nombre).write_text(texto, encoding="utf-8")
    print(f"\nPropuesta escrita en {destino} ({len(propuesta)} ficheros).")
    print("No se ha tocado `informes/` ni `conocimiento/`; el motor sigue en v1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
