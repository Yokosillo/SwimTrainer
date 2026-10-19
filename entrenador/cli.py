#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Interfaz de linea de ordenes del Entrenador.

Ejemplos:

    python -m entrenador.cli init
    python -m entrenador.cli importar-strava data/export_2026-10-11
    python -m entrenador.cli importar F:/GARMIN/ACTIVITY --fuente garmin_usb
    python -m entrenador.cli resumen
    python -m entrenador.cli etiquetar 21670453554 --material palas
    python -m entrenador.cli series --top 10
    python -m entrenador.cli analizar
    python -m entrenador.cli segmentos
    python -m entrenador.cli bici
    python -m entrenador.cli bici --segmento segmento-ejemplo
    python -m entrenador.cli minar
    python -m entrenador.cli minados --top 20
    python -m entrenador.cli minados --segmento 12
"""

from __future__ import annotations

import argparse
import os
import sys

from . import db, importar, analitica, panel, bici, segmentos_gpx, servidor


def _crono(segundos) -> str:
    """Un tiempo en minutos:segundos,1 con la coma espanola (lo que se lee en la piscina)."""
    s = float(segundos or 0)
    return f"{int(s // 60)}:{s - 60 * int(s // 60):04.1f}".replace(".", ",")


def _prueba(cn, args) -> int:
    """Marca una prueba de medicion en una sesion ya hecha (V1.2-11): las que el atleta hizo antes de la marca."""
    from . import partes
    try:
        r = partes.marcar_prueba(cn, args.actividad, args.nombre, lap_idx=args.lap, metros=args.metros)
    except ValueError as e:
        print(f"  {e}")
        return 2
    print(f"  Sesion {r['actividad_id']}: bloque lap {r['lap']}, {r['metros_del_bloque']:.0f} m"
          + (f" en {_crono(r['tiempo_s'])}" if r["tiempo_s"] else "")
          + (f" (ritmo {_crono(r['ritmo_100'])})" if r["ritmo_100"] else "")
          + f" -> prueba de medicion: {r['prueba']}.")
    if r.get("en_su_parte"):
        print("  Iba en el parte que ya tenia esa sesion: se ha marcado ahi, sin crear otro parte.")
        return 0
    print(f"  Partes: {r['nuevos']} nuevo(s), {r['actualizados']} ya estaba(n). El resto del parte es la propuesta")
    print("  del motor; si quieres retocarlo, abrelo en el portal (Entrenamientos).")
    return 0


def _linea_de_gimnasio(texto: str) -> dict:
    """'press banca=3x10@40' -> {'ejercicio': 'press banca', 'series': 3, 'reps': 10, 'kg': 40}.

    Los kilos son opcionales (el core, las lumbares) y las repeticiones tambien ('press banca=3x10').
    """
    nombre, _, resto = texto.partition("=")
    resto = resto.replace(" ", "").replace(",", ".")
    kg = None
    if "@" in resto:
        resto, _, k = resto.partition("@")
        kg = k
    series = reps = None
    if "x" in resto.lower():
        a, _, b = resto.lower().partition("x")
        series, reps = a, b
    else:
        series = resto or None
    return {"ejercicio": nombre.strip(), "series": series, "reps": reps, "kg": kg}


def _apunte(cn, args) -> int:
    """Apunta una sesion que no trae el reloj: la del entrenador, con su fecha y sus metros (V1.3-05).

    El entrenador ya no es un hueco que el plan adivina: es una linea con su fecha, sus metros y de quien es, y asi
    la semana sabe que carga lleva. Si el mismo dia se vuelve a apuntar, se actualiza en vez de duplicarse.
    """
    from . import apuntes, db
    fecha = (args.fecha or db.ahora()[:10])[:10]
    quien = "entrenador" if args.quien == "entrenador" else "atleta"
    fila = apuntes.anotar(cn, fecha=fecha, tipo=args.tipo, quien=quien, distancia_m=args.metros,
                          minutos=args.minutos, material=args.material, sensacion=args.sensacion,
                          notas=args.notas, piscina_m=args.piscina)
    metros = f", {int(fila['distancia_m'])} m" if fila.get("distancia_m") else ""
    print(f"  Apuntado: {fila.get('fecha')} | {fila.get('tipo')} | de {fila.get('quien')}{metros}")
    if quien == "entrenador":
        print("  Esa sesion cuenta como carga de la semana y el dia siguiente no lleva calidad.")
    return 0


def _apuntar_gimnasio(cn, args) -> int:
    """Apunta un dia de gimnasio desde la consola: los mismos numeros que apunta el portal."""
    from . import db, gimnasio
    filas = [_linea_de_gimnasio(t) for t in args.apuntar]
    try:
        r = gimnasio.apuntar(cn, args.fecha or db.ahora()[:10], filas)
    except ValueError as e:
        print(f"  {e}")
        return 2
    print(f"  Apuntado el {r['fecha']}: {len(r['ejercicios'])} ejercicio(s), {r['series']} series, "
          f"{r['repeticiones']} repeticiones"
          + (f", {r['volumen_kg']:g} kg de volumen." if r["volumen_kg"] else "."))
    for d in r["ejercicios"]:
        print("   · " + d["ejercicio"]
              + (" " + "x".join(str(x) for x in (d.get("series"), d.get("reps")) if x)
                 if d.get("series") or d.get("reps") else "")
              + (f" a {d['kg']:g} kg" if d.get("kg") else ""))
    return 0


def _historial_gimnasio(cn, args) -> int:
    """Lo que ha ido apuntando, lo mas nuevo primero (y su mejor dia si se pide un ejercicio)."""
    from . import gimnasio
    cual = (args.historial or "").strip() or None
    filas = gimnasio.historial(cn, cual, limite=args.limite)
    if not filas:
        print("  No hay nada apuntado" + (f" de {cual}" if cual else "") + ".")
        return 0
    for s in filas:
        print(f"  {s['fecha']}" + (f" · {s['volumen_kg']:g} kg" if s["volumen_kg"] else "") + ": "
              + ", ".join(d["ejercicio"] + " "
                          + "x".join(str(x) for x in (d.get("series"), d.get("reps")) if x)
                          + (f" a {d['kg']:g} kg" if d.get("kg") else "")
                          for d in s["ejercicios"]))
    if cual:
        m = gimnasio.mejor_de(cn, cual)
        if m:
            print(f"  Su mejor {cual}: {m['kg']:g} kg el {m['fecha']}.")
    return 0


def _corregir(cn, args) -> int:
    """Lo corregido de una sesion, o una correccion nueva del atleta (V1.2-06).

    El reloj no siempre acierta y el atleta tiene la ultima palabra sobre su entrenamiento, pero su dato no se toca:
    la correccion se apunta ENCIMA, con motivo, y se dice siempre que se enseñe ese tramo.
    """
    from . import correcciones
    act = cn.execute("SELECT id, inicio_local, distancia_m FROM actividad WHERE id = ?",
                     (args.actividad,)).fetchone()
    if not act:
        print(f"  No hay ninguna actividad con el numero {args.actividad}.")
        return 1
    fecha = (act["inicio_local"] or "")[:10]
    print(f"  Actividad {act['id']} · {fecha} · {(act['distancia_m'] or 0):.0f} m")
    if args.desde is None and args.segundos is None:
        dichas = correcciones.de(cn, act["id"])
        if not dichas:
            print("  Sin correcciones: lo que hay es lo que trae el reloj.")
            return 0
        for c in dichas:
            print(f"  · {correcciones.texto(c)}")
        return 0
    if args.desde is None or args.hasta is None or args.segundos is None or not args.motivo:
        print("  Para apuntar una correccion hacen falta --desde, --hasta, --segundos y --motivo.")
        return 2
    correcciones.anotar(cn, act["id"], args.desde, args.hasta, args.segundos, args.motivo)
    dichas = correcciones.de(cn, act["id"])
    print(f"  Apuntado. {correcciones.texto(dichas[-1])}")
    print("  El dato del reloj no se toca: la correccion va encima y se dice siempre.")
    return 0


def _minados(cn, args) -> int:
    """Enseña los segmentos descubiertos en las trazas propias y, si se pide, todos sus intentos."""
    if args.segmento:
        filas = segmentos_gpx.historial(cn, args.segmento)
        if not filas:
            print("No hay ningun segmento descubierto con ese nombre ni con ese numero.")
            return 1
        print(f"=== {filas[0]['segmento']} | {len(filas)} intentos ===")
        print(f"  {'fecha':<19} {'tiempo':>9} {'vel':>7} {'dist':>9} {'desnivel':>9} {'visto':>7}  salida")
        mejor = min(f["tiempo_s"] for f in filas)
        for f in filas:
            marca = "  <-- tu mejor" if f["tiempo_s"] == mejor else ""
            print(f"  {(f['fecha'] or '')[:19]:<19} {bici.horas(f['tiempo_s']):>9} "
                  f"{f['vel_kmh'] or 0:>6.1f} {f['dist_m'] or 0:>7.0f} m {f['desnivel_m'] or 0:>7.0f} m "
                  f"{100 * (f['cobertura'] or 0):>5.0f} %  {(f['salida'] or '')[:30]}{marca}")
        return 0
    filas = segmentos_gpx.resumen(cn, args.top)
    filas = [f for f in filas if f["n_intentos"] >= args.min_intentos]
    if not filas:
        print("Todavia no hay segmentos descubiertos. Lanza `minar` primero.")
        return 1
    print(f"=== Segmentos descubiertos en tus trazas: {len(filas)} (los mas repetidos) ===")
    print(f"  {'n':>4}  {'segmento':<38} {'dist':>8} {'pend':>7} {'veces':>6} {'mejor':>9}"
          f" {'ultima':>11}")
    for f in filas:
        print(f"  {f['id']:>4}  {(f['nombre'] or '')[:38]:<38} {f['dist_m'] / 1000:>6.2f} km "
              f"{f['pendiente_pct'] or 0:>6.1f}% {f['n_intentos']:>6} "
              f"{bici.horas(f['mejor_s']):>9} {(f['ultima'] or '')[:10]:>11}")
    print("\n  Para ver todos tus tiempos: `minados --segmento <numero o nombre>`.")
    return 0


def _bici(cn, args) -> int:
    """Enseña los segmentos de bici: cuales repite, en cuanto tiempo, y el historial si se pide uno."""
    if args.segmento:
        nombre = bici.nombre_segmento(cn, args.segmento)
        filas = bici.historial(cn, nombre)
        print(f"=== {nombre} — {len(filas)} intentos ===")
        if not filas:
            print("  (todavia no hay ningun intento medido)")
            return 0
        print(f"  {'fecha':<19} {'tiempo':>8} {'vel media':>10} {'pendiente':>10}  salida")
        for f in filas:
            vel = f"{f['vel_media_kmh']:.1f} km/h" if f["vel_media_kmh"] else "—"
            pen = f"{f['pendiente_pct']:.1f} %" if f["pendiente_pct"] is not None else "—"
            print(f"  {(f['fecha'] or '')[:19]:<19} {bici.horas(f['tiempo_s']):>8} {vel:>10} {pen:>10}  "
                  f"{(f['salida'] or '')[:40]}")
        mejor = min(filas, key=lambda f: f["tiempo_s"])
        ultimo = filas[-1]
        print(f"\n  mejor: {bici.horas(mejor['tiempo_s'])} el {(mejor['fecha'] or '')[:10]}"
              f" | ultima: {bici.horas(ultimo['tiempo_s'])} el {(ultimo['fecha'] or '')[:10]}")
        return 0

    filas = bici.resumen_segmentos(cn, min_veces=args.min_veces)
    total = cn.execute("SELECT COUNT(*) FROM segmento_bici").fetchone()[0]
    intentos = cn.execute("SELECT COUNT(*) FROM esfuerzo_bici").fetchone()[0]
    repetidos = sum(1 for f in filas if f["veces"] >= 2)
    dudosos = sum(1 for f in filas if f["dudoso"])
    print(f"=== Segmentos de bici: {total} en el catalogo, {len(filas)} con intentos medidos "
          f"({repetidos} repetidos, {intentos} intentos) ===")
    print(f"  {'segmento':<32} {'dist':>7} {'desniv':>7} {'pend':>6} {'veces':>5} "
          f"{'mejor':>8} {'mediana':>8} {'tendencia':>9}  ultima")
    for f in filas[:args.top]:
        dist = f"{f['dist_m'] / 1000:.1f} km" if f["dist_m"] else "—"
        desn = f"{f['desnivel_m']:.0f} m" if f["desnivel_m"] is not None else "—"
        pend = f"{f['pendiente_pct']:.1f}%" if f["pendiente_pct"] is not None else "—"
        tend = f"{f['tendencia_pct']:+.1f}%" if f["tendencia_pct"] is not None else "—"
        print(f"  {f['nombre'][:32] + (' *' if f['dudoso'] else ''):<32} {dist:>7} {desn:>7} {pend:>6} "
              f"{f['veces']:>5} {bici.horas(f['mejor_s']):>8} {bici.horas(f['mediana_s']):>8} {tend:>9}  "
              f"{f['ultima']}")
    print("\n  (el orden es veces x distancia: los tramos largos y repetidos primero;"
          " 'tendencia' en negativo = has mejorado)")
    if dudosos:
        print(f"  (*) {dudosos} segmento(s) con dudoso: sus trazas los cruzan por caminos de distinta longitud,"
              " asi que los tiempos del grupo no son todos del mismo recorrido. Se usa el camino mas habitual.")
    return 0



def _valoracion(cn, refrescar: bool = False, sesion: int | None = None) -> None:
    """El discurso del entrenador por consola: los parrafos y las dianas de entrenamiento.

    Con `sesion` (la actividad_id) mira UN entrenamiento concreto -- lo mismo que hace el boton "Evaluar" del
    portal: tiempos bloque a bloque, distancia, esfuerzo previo y descansos, y como va el plan. Sin `sesion`
    suelta el discurso entero de la temporada.

    Lee el cuadro de mando ya escrito (que es el mismo que pinta el portal) y solo recalcula si se pide o si
    todavia no hay nada escrito: asi el discurso de la consola y el del Resumen no pueden decir cosas distintas.
    """
    import json

    from . import valoracion as _val

    ruta = os.path.join("data", "derived", "analitica.json")
    datos = None
    if not refrescar and os.path.isfile(ruta):
        try:
            with open(ruta, encoding="utf-8") as f:
                datos = json.load(f)
        except (OSError, ValueError):
            datos = None
    if sesion is not None:
        v = _val.sesion(cn, int(sesion), datos or {})
        if not v:
            print(f"No encuentro la sesion {sesion}.")
            return
        print(f"{v['titulo']}  ·  {v['cabecera']}")
        print()
        for p in v["parrafos"]:
            print(p["titulo"].upper())
            print("  " + p["texto"])
            print()
        return
    if not datos or not datos.get("valoracion"):
        datos = analitica.analizar(cn)
    print(_val.texto(datos["valoracion"]))


def _resumen(cn) -> None:
    def uno(sql, *args):
        return cn.execute(sql, args).fetchone()[0]

    print("=== Resumen de la base de datos ===")
    print(f"Ruta: {db.RUTA_POR_DEFECTO}")
    for fila in cn.execute(
        """SELECT disciplina, COUNT(*) n, ROUND(SUM(distancia_m)/1000.0, 1) km,
                  MIN(substr(inicio_local,1,10)) desde, MAX(substr(inicio_local,1,10)) hasta
           FROM actividad GROUP BY disciplina ORDER BY n DESC"""
    ):
        print(f"  {fila['disciplina'] or 'sin_clasificar':<14} {fila['n']:>5} actividades "
              f"{fila['km'] or 0:>9.1f} km   {fila['desde']} .. {fila['hasta']}")
    print()
    print(f"Natacion: {uno('SELECT COUNT(*) FROM natacion_sesion')} sesiones | "
          f"{uno('SELECT COUNT(*) FROM natacion_lap')} laps | "
          f"{uno('SELECT COUNT(*) FROM natacion_largo')} largos | "
          f"{uno('SELECT COUNT(*) FROM serie')} series ({uno('SELECT COUNT(*) FROM serie WHERE comparable=1')} comparables)")
    print(f"Sesiones con sensacion (workout_feel): {uno('SELECT COUNT(*) FROM natacion_sesion WHERE sensacion IS NOT NULL')} | "
          f"con RPE: {uno('SELECT COUNT(*) FROM natacion_sesion WHERE rpe IS NOT NULL')}")
    print(f"Series con material etiquetado: "
          f"{uno('SELECT COUNT(*) FROM serie WHERE material IS NOT NULL AND material <> ?', 'sin_etiquetar')} "
          f"| series pendientes de etiquetar: "
          f"{uno('SELECT COUNT(*) FROM serie WHERE material = ?', 'sin_etiquetar')}")
    print()
    print("Sesiones por largo de piscina:")
    for fila in cn.execute(
        """SELECT largo_piscina_m, COUNT(*) n, ROUND(SUM(l.n_largos_activos*l.largo_piscina_m)/1000.0,1) km
           FROM natacion_sesion l GROUP BY largo_piscina_m ORDER BY n DESC"""
    ):
        print(f"  {fila['largo_piscina_m'] or 'sin_dato'} m -> {fila['n']:>4} sesiones, {fila['km']} km")
    print()
    print("Comprobacion de coherencia (distancia declarada por el reloj vs distancia por largos):")
    fila = cn.execute(
        """SELECT COUNT(*) n, ROUND(AVG(ABS(a.distancia_m - a.distancia_fit_m)),1) dif_media
           FROM actividad a JOIN natacion_sesion s ON s.actividad_id = a.id
           WHERE a.distancia_fit_m IS NOT NULL AND s.largo_piscina_m IS NOT NULL"""
    ).fetchone()
    print(f"  {fila['n']} sesiones comparables, diferencia media de {fila['dif_media']} m "
          f"(0 = el reloj y los largos coinciden exactamente)")
    print()
    print("Ultima importacion:")
    for fila in cn.execute("SELECT momento, fuente, leidos, nuevos, actualizados, omitidos, incidencias "
                           "FROM importacion ORDER BY id DESC LIMIT 3"):
        print(f"  {fila['momento']}  {fila['fuente']:<14} leidos={fila['leidos']} nuevos={fila['nuevos']} "
              f"actualizados={fila['actualizados']} omitidos={fila['omitidos']} incidencias={fila['incidencias']}")


def _rehacer_cuadro(cn, carpeta: str) -> None:
    """Rehace lo derivado y el cuadro de mando (lo mismo que hace `analizar`).

    Se llama cuando entra un entrenamiento nuevo para que el plan se recalcule con lo que acaba de entrar, sin
    tener que acordarse de lanzar `analizar` a mano. Es lo mismo que hace el servidor cuando le suben un parte.
    """
    from . import analitica, panel
    datos = analitica.analizar(cn)
    analitica.guardar_json(datos, os.path.join(carpeta, "data", "derived", "analitica.json"))
    panel.escribir(datos, carpeta)


def _generar_semana(cn, args) -> int:
    """Guarda la propuesta de la semana con su porque (V1.3-02).

    Desde aqui cada dia propuesto tiene guardados los numeros que lo sostienen y las reglas que lo aplican, y se
    puede registrar que decide el atleta. Lo que no se sostiene con numeros no entra: lo impide `decision.registrar`.
    """
    from . import decision
    r = decision.proponer_semana(cn, getattr(args, "fecha", None))
    if not r.get("cuantas"):
        print("No hay nada que proponer: sin series medidas en la ventana, no hay deficit que sostenga la semana.")
        return 0
    print(f"Guardada la propuesta de {r['semana'] or 'la semana'}: {r['cuantas']} dias, cada uno con sus datos y"
          " sus reglas.")
    for rid in r["ids"]:
        d = decision.detalle(cn, rid)
        print(f"  #{rid}  {d['titulo']}   ({len(d['datos'])} datos, {len(d['reglas'])} reglas)")
    print("Cuando lo hagas (o no), apunta tu decision:  cli decision --aceptar <n> | --cambiar <n> --motivo \"...\"")
    return 0


def _fuerza(cn, args) -> int:
    """La fuerza: la dosis preventiva (T.7), el aviso de abandono y la carga de la semana (V1.4)."""
    from . import fuerza
    print(fuerza.texto(cn, getattr(args, "fecha", None)))
    return 0


def _conocimiento(cn, args) -> int:
    """La base de conocimiento: TOML (F2) y anexo Markdown (F1): carga, valida, versiona y firma."""
    import json as _json

    from . import conocimiento, conocimiento_toml

    formato = getattr(args, "formato", None) or ("json" if getattr(args, "json", False) else "texto")
    ruta_toml = getattr(args, "ruta_toml", conocimiento_toml.RUTA_CONOCIMIENTO)

    if getattr(args, "firmar", None):
        try:
            r = conocimiento_toml.firmar(ruta=ruta_toml, id_=args.firmar,
                                         quien=args.quien or "entrenador", notas=args.notas or "")
        except ValueError as exc:
            print(f"No se puede firmar: {exc}")
            return 1
        if formato == "json":
            print(_json.dumps(r, ensure_ascii=False, indent=2))
        else:
            print(f"{r['id']} firmado por {r['firmado_por']} el {r['firmado_en']}.")
        return 0
    if getattr(args, "version", False):
        e = conocimiento_toml.estructura(ruta=ruta_toml)
        if formato == "json":
            print(_json.dumps({"version": e["version"], "hash": e["hash"]}, ensure_ascii=False, indent=2))
        else:
            print(e["version"] or "sin conocimiento TOML")
            if e["hash"]:
                print(f"hash: {e['hash']}")
        return 0 if e["version"] else 1
    if getattr(args, "estructura", False):
        e = conocimiento_toml.estructura(ruta=ruta_toml)
        if formato == "json":
            print(_json.dumps(e, ensure_ascii=False, indent=2))
        else:
            print(f"Conocimiento TOML: {e['version'] or '(sin conocimiento)'}")
            for f in e["ficheros"]:
                print(f"  {f['nombre']:<22} sha256={f['sha256'][:12]}")
            print("  " + " | ".join(f"{k}={v}" for k, v in e["conteos"].items()))
        return 0 if e["version"] else 1
    if getattr(args, "exportar_md", False):
        try:
            r = conocimiento_toml.exportar_markdown(ruta=ruta_toml)
            d = conocimiento_toml.comparar_markdown(ruta=ruta_toml)
        except ValueError as exc:
            print(f"No se puede exportar: {exc}")
            return 1
        if not d.get("ok"):
            if formato == "json":
                print(_json.dumps({"exportado": r, "diferencias": d}, ensure_ascii=False, indent=2))
            else:
                print(f"Markdown generado: {r['destino']} ({r['bytes']} bytes, {r['version']})")
                print(f"El informe de diferencias fallo: {d.get('error', '?')}")
            return 1
        if formato == "json":
            print(_json.dumps({"exportado": r, "diferencias": d}, ensure_ascii=False, indent=2))
        else:
            print(f"Markdown generado: {r['destino']} ({r['bytes']} bytes, {r['version']})")
            print(f"Informe de diferencias: {d['informe']}")
            print("  " + " | ".join(f"{k}={v}" for k, v in d["conteos"].items()))
        return 0
    if getattr(args, "sincronizar", False):
        try:
            r = conocimiento_toml.sincronizar(cn, ruta=ruta_toml)
        except ValueError as exc:
            print(f"No se sincroniza: {exc}")
            return 1
        if formato == "json":
            print(_json.dumps(r, ensure_ascii=False, indent=2))
        else:
            print(f"Sincronizado {r['version']} en las tablas de conocimiento.")
            print("  " + " | ".join(f"{k}={v}" for k, v in r["conteos"].items()))
        return 0
    if getattr(args, "validar", False):
        md = conocimiento.validar()
        toml = conocimiento_toml.validar(ruta=ruta_toml)
        ok = bool(md["ok"] and toml["ok"])
        errores = [dict(e, origen="markdown") for e in md["errores"]] + \
                  [dict(e, origen="toml") for e in toml["errores"]]
        avisos = [dict(a, origen="markdown") for a in md["avisos"]] + \
                 [dict(a, origen="toml") for a in toml["avisos"]]
        if formato == "json":
            print(_json.dumps({"ok": ok, "errores": errores, "avisos": avisos,
                               "version": toml.get("version"), "conteos": toml.get("conteos"),
                               "markdown": md, "toml": toml}, ensure_ascii=False, indent=2))
        else:
            print(f"Markdown: {md['anexo']}: {md['secciones']} secciones, {md['fuentes']} fuentes, "
                  f"{md['citas_usadas']} citas distintas.")
            print(f"TOML: {toml.get('version') or '(sin conocimiento)'}: "
                  f"{toml.get('conteos') or {}}.")
            for e in errores:
                print(f"  [ERROR] {e['origen']}/{e['tipo']}: {e['detalle']}")
            for a in avisos:
                print(f"  [AVISO] {a['origen']}/{a['tipo']}: {a['detalle']}")
            print("OK: el conocimiento es coherente." if ok
                  else f"FALLAN {len(errores)} comprobacion(es).")
        return 0 if ok else 1
    if getattr(args, "criterios", False):
        filas = conocimiento.criterios(cn=cn)
        if formato == "json":
            print(_json.dumps(filas, ensure_ascii=False, indent=2))
        elif formato == "md":
            print(conocimiento.criterios_markdown(filas), end="")
        else:
            print(f"{len(filas)} clausulas [criterio] (21 lineas marcadas; T.5 lleva dos marcas).")
            print("Estado: firmada (entrenador/atleta), revisada_por_asistente (sigue pendiente) o pendiente.")
            for i, x in enumerate(filas, 1):
                estado = conocimiento.etiqueta_estado(x.get("estado", "pendiente"))
                print(f"  {i:>2}. {x['seccion']:<5} [{estado}] {x['afirmacion']}")
        return 0
    if args.revisar:
        if not conocimiento.seccion(args.revisar):
            print(f"No existe la seccion {args.revisar} en el anexo.")
            return 1
        quien = args.quien or "atleta"
        conocimiento.marcar_revision(cn, args.revisar, quien, args.notas or "")
        firma = quien.strip().lower() in conocimiento.FIRMANTES
        print(f"{args.revisar} revisada por {quien}" +
              ("" if firma else " (no cuenta como firma: solo entrenador/atleta)"))
    c = conocimiento.cuadro_revision(cn)
    print(f"{c['anexo']}: {c['total']} secciones, {c['revisadas']} firmadas, "
          f"{c['revisadas_por_asistente']} revisadas por asistente, {c['sin_fuente']} criterios sin firma.")
    for x in c["secciones"]:
        estado = x.get("estado_revision") or "sin_revisar"
        if estado == "firmada":
            firma = f"firmada por {x['revisado_por']} el {str(x['revisado_en'])[:10]}"
        elif estado == "revisada_por_asistente":
            firma = f"revisada por {x['revisado_por']}, pendiente de firma"
        else:
            firma = "sin revisar"
        respaldo = (", ".join("[" + str(n) + "]" for n in x["fuentes"]) if x["con_fuente"]
                    else ("criterio (sin fuente)" if x["criterio"] else "sin fuente declarada"))
        print(f"  {x['seccion']:<5} {respaldo:<26} {firma:<44} {str(x['titulo'])[:38]}")
    return 0


def _reglas(cn, args) -> int:
    """El credito de cada regla (V1.3-04): cuantas veces se propone, que decides y si acierta."""
    from . import decision
    panel = decision.panel_reglas(cn, getattr(args, "desde", None), getattr(args, "hasta", None))
    if not panel:
        print("No hay reglas declaradas.")
        return 0
    for r in panel:
        secciones = ", ".join(r["seccion_T"]) if r["seccion_T"] else ("criterio" if r["grado"] == "criterio" else "-")
        d = r["decisiones"]
        print(f"{r['regla_id']:<5} {secciones:<22} {r['veredicto']:<10} propuestas={r['propuestas']:<3}"
              f" aceptadas={d.get('aceptada', 0)} cambiadas={d.get('cambiada', 0)} ignoradas={d.get('ignorada', 0)}"
              f" sin_decidir={d.get('sin_registrar', 0)}")
        print(f"      {r['enunciado']}")
        if r["notas"]:
            print(f"      {r['notas']}")
        if r["revisar"]:
            print(f"      [!] {r['regla_id']}: {r['ventanas_en_contra']} ventanas en contra. No se retira sola: la revisas tu.")
    return 0


def _decision(cn, args) -> int:
    """Lista, explica o registra lo que haces con una propuesta (V1.3-03)."""
    from . import decision
    if getattr(args, "explicar", None):
        d = decision.detalle(cn, args.explicar)
        if not d:
            print(f"No hay ninguna recomendacion con el numero {args.explicar}.")
            return 1
        print(f"#{d['id']}  {d['fecha']}  {d['titulo']}")
        if d["cuerpo"]:
            print(d["cuerpo"])
        print("")
        print("Datos usados (de donde sale cada numero):")
        for x in d["datos"]:
            print(f"  - {x['fuente']}  {x['ref']} = {x['valor']}   {x['nota'] or ''}")
        print("Reglas que lo aplican:")
        for x in d["reglas"]:
            # `fuentes` son los numeros [n] del anexo T (enteros); la seccion puede faltar y la regla sigue
            # valiendo como criterio, pero eso se dice: no se disfraza de saber con respaldo.
            secciones = ", ".join(x["seccion_T"]) or f"criterio ({x['grado']})"
            fuentes = ", ".join(f"[{n}]" for n in x["fuentes"]) or "-"
            print(f"  - {x['regla_id']} ({x['papel']}, {x['grado']})  {secciones}  fuentes: {fuentes}")
        if d["decision"]:
            motivo = f" - {d['decision']['motivo']}" if d["decision"].get("motivo") else ""
            print(f"Tu decision ({d['decision']['fecha']}): {d['decision']['tomada']}{motivo}")
        for v in d["verificacion"]:
            print(f"Verificacion de {v['regla_id']} ({v['fecha']}): {v['veredicto']} - {v['notas']}")
        return 0
    tomada, n = None, None
    for estado in ("aceptar", "cambiar", "ignorar"):
        if getattr(args, estado, None):
            n = getattr(args, estado)
            tomada = {"aceptar": "aceptada", "cambiar": "cambiada", "ignorar": "ignorada"}[estado]
    if n:
        try:
            decision.decidir(cn, n, tomada, respuesta=args.respuesta, motivo=args.motivo)
        except ValueError as e:
            print(f"No se ha podido registrar: {e}")
            return 1
        print(f"#{n}: {tomada}" + (f"  ({args.motivo})" if args.motivo else ""))
        return 0
    lista = decision.recomendaciones(cn, limite=20)
    if not lista:
        print("Todavia no hay propuestas guardadas. Se guardan con:  cli plan --generar")
        return 0
    print(f"{'#':<5} {'fecha':<11} {'semana':<7} {'estado':<13} titulo")
    for r in lista:
        print(f"{r['id']:<5} {r['fecha']:<11} {r['semana'] or '-':<7} {r.get('tomada') or 'sin decidir':<13} {r['titulo']}")
    return 0

def _estado(cn, args) -> int:
    """Imprime o guarda la foto del estado del atleta (F4). No toca el motor ni las recomendaciones."""
    import json
    from . import estado
    if getattr(args, "id", None):
        d = estado.cargar(cn, args.id)
        if not d:
            print(f"No hay ningun estado guardado con id {args.id}.")
            return 1
        if args.json:
            print(json.dumps(d, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"{d.get('estado_id')}  {d.get('fecha')}  {d.get('version_conocimiento') or 'sin version'}")
        return 0
    e = estado.calcular(cn, getattr(args, "fecha", None))
    guardado = False
    if getattr(args, "guardar", False):
        estado.guardar(cn, e)
        guardado = True
    if args.json:
        d = e.a_dict()
        if guardado:
            d["guardado"] = True
        print(json.dumps(d, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(e.texto())
    if guardado:
        print(f"\nGuardado: {e.estado_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="entrenador", description="Gestor de entrenamientos (uso personal).")
    p.add_argument("--bd", default=db.RUTA_POR_DEFECTO, help="ruta de la base de datos SQLite")
    sub = p.add_subparsers(dest="orden", required=True)

    sub.add_parser("init", help="crea la base de datos y el esquema")

    pi = sub.add_parser("importar", help="importa FIT de una carpeta (reloj por USB o export de Garmin)")
    pi.add_argument("ruta")
    pi.add_argument("--fuente", default="carpeta",
                    help="carpeta | garmin_usb | garmin_export (queda registrado para trazabilidad)")

    ps = sub.add_parser("importar-strava", help="importa un export de Strava ya descomprimido")
    ps.add_argument("ruta")

    sub.add_parser("resumen", help="cuadro de mando por consola")

    pe = sub.add_parser("etiquetar", help="etiqueta una sesion a mano (material, piscina, ...)")
    pe.add_argument("id_garmin")
    pe.add_argument("--material", choices=["palas", "aletas", "pull", "tabla", "snorkel", "brazo_libre"])
    pe.add_argument("--piscina", type=float, help="largo de piscina en metros, si el reloj estaba mal")

    pse = sub.add_parser("series", help="lista las mejores series (ritmo medio)")
    pse.add_argument("--top", type=int, default=10)
    pse.add_argument("--metros", type=int, help="filtra por distancia de repeticion (100, 200, 400...)")
    pse.add_argument("--comparables", action="store_true", help="solo series comparables (sin material, >=3 reps)")

    sub.add_parser("recalcular", help="rehace las series a partir de los laps ya importados (no reimporta)")

    pcomp = sub.add_parser("competicion", help="tus marcas oficiales de la RFEN: las carga y las resume")
    pcomp.add_argument("--csv", default=None, help="CSV bajado con scripts/rfen_historial.py")
    pcomp.add_argument("--estilo", help="libre | espalda | braza | mariposa | estilos")
    pcomp.add_argument("--distancia", type=int, help="filtra por distancia (400, 1500, 3000...)")
    pcomp.add_argument("--piscina", type=int, choices=(25, 50), help="25 o 50 m (no son equivalentes)")
    pcomp.add_argument("--temporada", help="'2025/26' (de septiembre a agosto)")
    pcomp.add_argument("--desde", help="fecha minima (YYYY-MM-DD)")
    pcomp.add_argument("--hasta", help="fecha maxima (YYYY-MM-DD)")
    pcomp.add_argument("--lugar", help="busca en el lugar y en el club")
    pcomp.add_argument("--orden", dest="orden_marcas", default="fecha",
                       choices=("fecha", "marca", "distancia", "ritmo"),
                       help="orden de la lista (ojo: dest distinto de 'orden', que es el del propio CLI)")
    pcomp.add_argument("--comparar", action="store_true", help="cuadro temporada a temporada y tendencia")
    pcomp.add_argument("--clasificar", action="store_true",
                       help="rehace que filas son prueba suya y que filas son tramos de otra (mirando el dia)")
    pcomp.add_argument("--sin-importar", action="store_true", help="solo consultar lo que ya hay")

    pplan = sub.add_parser("plan", help="el plan de las proximas semanas (objetivos 400 y 3.000)")
    pplan.add_argument("--semana", help="S1, S2, S3, S4 o S5")
    pplan.add_argument("--fecha", help="la semana que contiene esa fecha (YYYY-MM-DD)")
    pplan.add_argument("--recalculado", action="store_true",
                       help="el plan recalculado con lo que ha entrado (no el escrito)")

    pplan.add_argument("--generar", action="store_true",
                       help="guarda la propuesta de la semana con su porque (datos y reglas) para que conste")

    preg = sub.add_parser("reglas", help="el credito de cada regla: cuanto se propone, que decides y si acierta")
    preg.add_argument("--desde", default=None, help="desde que fecha (YYYY-MM-DD)")
    preg.add_argument("--hasta", default=None, help="hasta que fecha (YYYY-MM-DD)")

    pfu = sub.add_parser("fuerza", help="la dosis preventiva del hombro (T.7), el aviso de abandono y su carga")
    pfu.add_argument("--fecha", default=None, help="la fecha del dia (por defecto, hoy)")

    pest = sub.add_parser("estado", help="la foto del atleta en una fecha: metricas, n, dispersion y confianza")
    pest.add_argument("--fecha", default=None, help="fecha de la foto (YYYY-MM-DD; por defecto, hoy)")
    pest.add_argument("--guardar", action="store_true", help="guarda el snapshot en la base (id determinista)")
    pest.add_argument("--json", action="store_true", help="salida JSON valida")
    pest.add_argument("--id", default=None, metavar="EA-...", help="lee un snapshot guardado por su id")

    pco = sub.add_parser("conocimiento", help="la base de conocimiento: validacion, criterios y firmas")
    pco.add_argument("--revisar", default=None, metavar="SECCION",
                     help="firma una seccion como revisada (T.4, T.8...): quien la ha mirado y cuando")
    pco.add_argument("--validar", action="store_true",
                     help="valida el TOML y el anexo Markdown (0 = sin errores)")
    pco.add_argument("--firmar", default=None, metavar="ID",
                     help="firma un criterio/parametro local (AF-101, PA-101...)")
    pco.add_argument("--estructura", action="store_true",
                     help="resumen del conocimiento TOML: version, ficheros y conteos")
    pco.add_argument("--version", action="store_true", help="version KV-* y hash canonico del TOML")
    pco.add_argument("--exportar-md", action="store_true",
                     help="exporta el TOML a data/derived/conocimiento/ y deja el informe de diferencias")
    pco.add_argument("--sincronizar", action="store_true",
                     help="copia el TOML a las tablas SQLite de conocimiento (idempotente)")
    pco.add_argument("--ruta-toml", default="conocimiento", help="carpeta del conocimiento TOML")
    pco.add_argument("--criterios", action="store_true",
                     help="lista las afirmaciones [criterio] pendientes de firma, con su estado")
    pco.add_argument("--json", action="store_true", help="salida JSON")
    pco.add_argument("--formato", choices=("texto", "json", "md"), default=None,
                     help="formato de salida: texto (por defecto), json o md (md solo para --criterios)")
    pco.add_argument("--quien", default=None, help="quien la firma (por defecto, el atleta)")
    pco.add_argument("--notas", default=None, help="con que notas queda firmada")

    pdec = sub.add_parser("decision", help="que haces con lo que se te propone: aceptar, cambiar o ignorar")
    pdec.add_argument("--lista", action="store_true", help="las ultimas propuestas guardadas, con su decision")
    pdec.add_argument("--aceptar", type=int, default=None, help="numero de la propuesta que aceptas")
    pdec.add_argument("--cambiar", type=int, default=None, help="numero de la propuesta que cambias")
    pdec.add_argument("--ignorar", type=int, default=None, help="numero de la propuesta que ignoras")
    pdec.add_argument("--motivo", default=None, help="por que la cambias o la ignoras (en tus palabras)")
    pdec.add_argument("--respuesta", default=None, help="que hiciste de verdad en la piscina")
    pdec.add_argument("--explicar", type=int, default=None,
                      help="el porque de una propuesta: dato -> regla -> seccion del anexo T")

    pap = sub.add_parser("apunte", help="apuntar algo que no trae el reloj: la sesion del entrenador, una molestia")
    pap.add_argument("--quien", choices=["yo", "atleta", "entrenador"], default="yo",
                     help="de quien es la sesion (por defecto, tuya)")
    pap.add_argument("--fecha", default=None, help="la fecha del dia (por defecto, hoy)")
    pap.add_argument("--tipo", default="natacion", choices=["natacion", "gimnasio", "bici", "otro", "sueno"],
                     help="de que fue la sesion")
    pap.add_argument("--metros", type=float, default=None, help="los metros de esa sesion")
    pap.add_argument("--minutos", type=float, default=None, help="los minutos")
    pap.add_argument("--material", default="ninguno", help="palas, aletas, pull, tabla...")
    pap.add_argument("--sensacion", type=float, default=None, help="1-10, como lo noto")
    pap.add_argument("--notas", default="", help="lo que quieras dejar escrito")
    pap.add_argument("--piscina", type=float, default=None, help="la piscina en metros (25 hasta junio)")

    papu = sub.add_parser("apuntes", help="lo que apuntas desde el cuadro de mando (gimnasio, material, sensaciones)")
    papu.add_argument("--importar", action="store_true", help="lee el fichero y lo mete en la base (idempotente)")
    papu.add_argument("--ruta", default=None, help="otro fichero (por defecto, Descargas/partes_entrenador.json)")
    papu.add_argument("--top", type=int, default=40, help="cuantos apuntes ensenar")

    ppa = sub.add_parser("partes", help="el parte de una sesion de natacion: agrupar intervalos, material e intensidad")
    ppa.add_argument("--pendientes", action="store_true",
                     help="sesiones del reloj que no tienen parte, con los grupos propuestos")
    ppa.add_argument("--importar", action="store_true", help="lee el fichero del portal y lo mete en la base")
    ppa.add_argument("--escribir", default=None,
                     help="el parte dictado en el chat: un JSON con el bloque partes_natacion que se mete en la base")
    ppa.add_argument("--ruta", default=None, help="otro fichero (por defecto, Descargas/partes_entrenador.json)")
    ppa.add_argument("--carpeta", default=".", help="carpeta del proyecto donde rehacer el cuadro")
    ppa.add_argument("--limite", type=int, default=3, help="cuantas sesiones sin parte mirar")
    ppa.add_argument("--reaplicar", action="store_true",
                     help="vuelve a llevar a los laps el material y los tiempos de los partes ya guardados")

    ppr = sub.add_parser("prueba", help="marca una prueba de medicion en una sesion ya hecha (un tiron de 30 minutos)")
    ppr.add_argument("--actividad", type=int, required=True, help="el numero de sesion (el que se ve en el portal)")
    ppr.add_argument("--nombre", required=True, help="el nombre de la prueba, tal como lo quieres ver")
    ppr.add_argument("--lap", type=int, default=None, help="el lap del tiron, si lo sabes")
    ppr.add_argument("--metros", type=float, default=None, help="o los metros del tiron, si no lo sabes")

    pev = sub.add_parser("evaluar", help="cruza lo hecho con el plan: veredicto por sesion y ajuste propuesto")
    pev.add_argument("--semana", help="S1, S2, S3, S4 o S5 (por defecto, las ultimas tres ya empezadas)")
    pev.add_argument("--semanas", type=int, default=3, help="cuantas semanas evaluar")
    pev.add_argument("--guardar", action="store_true",
                     help="deja el ajuste propuesto apuntado en la base (el plan no se toca)")

    pgim = sub.add_parser("gimnasio", help="lo pedido en el portal: lo que se ha pedido, lo hecho y lo que manda el programa")
    pgim.add_argument("--escribir", default=None, help="fichero JSON con la sesion (o sesiones) que manda el programa")
    pgim.add_argument("--plantilla", action="store_true",
                      help="los ejercicios de su plantilla, con lo ultimo de cada uno")
    pgim.add_argument("--apuntar", action="append", default=None, metavar="EJERCICIO=SERIESxREPS@KG",
                      help="lo hecho ese dia; repetible: --apuntar \"press banca=3x10@40\" --apuntar \"core=3x20\"")
    pgim.add_argument("--fecha", default=None, help="el dia de lo apuntado (por defecto, hoy)")
    pgim.add_argument("--historial", nargs="?", const="", default=None,
                      help="lo apuntado, lo mas nuevo primero (o de un ejercicio: --historial \"press banca\")")
    pgim.add_argument("--limite", type=int, default=12, help="cuantas sesiones del historial")

    pan = sub.add_parser("analizar", help="analitica de segmentos + cuadro de mando (HTML) + informe")
    pan.add_argument("--carpeta", default=".", help="carpeta del proyecto donde escribir las salidas")

    pval = sub.add_parser("valoracion",
                          help="el discurso del entrenador: como vamos, que queda y con que tiempos entrenar")
    pval.add_argument("--refrescar", action="store_true",
                      help="recalcular el cuadro de mando antes de hablar")
    pval.add_argument("--sesion", type=int, default=None,
                      help="evaluar UN entrenamiento (la actividad_id): tiempos, distancia, esfuerzo previo y descansos")

    pseg = sub.add_parser("segmentos", help="importa tus segmentos de bici del export y mide cada intento")
    pseg.add_argument("--export", default="data/export_2026-10-11", help="carpeta del export de Strava")
    pseg.add_argument("--pasadas", type=int, default=2,
                      help="pasadas de medicion (2 = mide, descubre la distancia tipica y vuelve a medir)")

    pb = sub.add_parser("bici", help="tus segmentos de bici: cuales repites y cuanto tardas")
    pb.add_argument("--min-veces", type=int, default=1, help="solo segmentos hechos al menos N veces")
    pb.add_argument("--top", type=int, default=25)
    pb.add_argument("--segmento", help="historial de intentos de un segmento (para comparar tus resultados)")

    pm = sub.add_parser("minar", help="descubre en tus trazas GPS los segmentos que repites y los mide")
    pm.add_argument("--disciplina", default="ciclismo")
    pm.add_argument("--limite", type=int, help="para pruebas: usa solo las N salidas mas recientes")
    pm.add_argument("--solo-minar", action="store_true", help="descubre pero no mide los intentos")
    pm.add_argument("--poblaciones", action="store_true", help="vuelve a traer los pueblos de OpenStreetMap")

    pmin = sub.add_parser("minados", help="los segmentos descubiertos en tus trazas")
    pmin.add_argument("--top", type=int, default=25)
    pmin.add_argument("--min-intentos", type=int, default=1)
    pmin.add_argument("--segmento", help="todos tus tiempos en ese segmento (numero o nombre)")

    pcor = sub.add_parser("corregir", help="lo que tu corriges de un entrenamiento (el reloj no siempre acierta)")
    pcor.add_argument("actividad", type=int, help="numero de la actividad")
    pcor.add_argument("--desde", type=float, help="metros acumulados dentro de la sesion donde empieza lo corregido")
    pcor.add_argument("--hasta", type=float, help="metros acumulados donde acaba")
    pcor.add_argument("--segundos", type=float, help="negativo resta (te pasaste de ritmo), positivo suma")
    pcor.add_argument("--motivo", help="por que, en tus palabras: es lo que la hace tuya")

    pport = sub.add_parser("portal", help="escribe el portal de bici (mapa, segmentos y tiempos) en HTML")
    pport.add_argument("--destino", default=None, help="donde escribirlo (por defecto cuadro/strava/index.html)")

    pserv = sub.add_parser("servir", help="sirve el cuadro de mando y recibe los partes que se suben del portal")
    pserv.add_argument("--puerto", type=int, default=servidor.PUERTO_POR_DEFECTO, help="puerto (por defecto 8181)")
    pserv.add_argument("--host", default=servidor.HOST_POR_DEFECTO,
                       help="direccion donde escuchar (127.0.0.1 en el PC; 0.0.0.0 en Docker)")
    pserv.add_argument("--carpeta", default=".", help="carpeta del proyecto (por defecto la actual)")
    pserv.add_argument("--rapido", action="store_true", help="no rehacer el cuadro de mando en cada parte")
    pserv.add_argument("--abrir", action="store_true", help="abrir el cuadro de mando en el navegador al arrancar")

    args = p.parse_args(argv)
    cn = db.conectar(args.bd)

    if args.orden == "init":
        print(f"Base de datos lista en {args.bd}")
    elif args.orden == "importar":
        r = importar.importar_carpeta(cn, args.ruta, fuente=args.fuente)
        print(f"Importados: leidos={r['leidos']} nuevos={r['nuevos']} actualizados={r['actualizados']} "
              f"omitidos={r['omitidos']} incidencias={r['incidencias']}")
        if r["nuevos"] or r["actualizados"]:
            _rehacer_cuadro(cn, getattr(args, "carpeta", "."))     # el plan se recalcula con lo que acaba de entrar
            print("Cuadro de mando rehecho: el plan se ha recalculado con los entrenamientos que han entrado.")
    elif args.orden == "importar-strava":
        r = importar.importar_export_strava(cn, args.ruta)
        print(f"Export leido: {r['filas_csv']} filas | con FIT: {r['con_fit']} | sin FIT: {r['sin_fit']}")
        print(f"Importadas: nuevos={r['nuevos']} actualizados={r['actualizados']} omitidos={r['omitidos']} "
              f"incidencias={r['incidencias']}")
        if r["nuevos"] or r["actualizados"]:
            _rehacer_cuadro(cn, getattr(args, "carpeta", "."))
            print("Cuadro de mando rehecho: el plan se ha recalculado con los entrenamientos que han entrado.")
    elif args.orden == "resumen":
        _resumen(cn)
    elif args.orden == "etiquetar":
        fila = cn.execute("SELECT id FROM actividad WHERE id_garmin = ?", (args.id_garmin,)).fetchone()
        if not fila:
            print(f"No encuentro la actividad con id_garmin={args.id_garmin}", file=sys.stderr)
            return 1
        if args.material:
            cn.execute("INSERT OR REPLACE INTO etiqueta (actividad_id, tipo, valor, origen, confianza) "
                       "VALUES (?, 'material', ?, 'manual', 'alta')", (fila["id"], args.material))
            material = "sin_etiquetar" if args.material == "brazo_libre" else args.material
            cn.execute("UPDATE serie SET material = ?, comparable = CASE WHEN ? = 'sin_etiquetar' "
                       "THEN comparable ELSE 0 END WHERE actividad_id = ?", (material, material, fila["id"]))
            cn.execute("UPDATE natacion_lap SET material = ? WHERE actividad_id = ? AND es_descanso = 0",
                       (material, fila["id"]))
        if args.piscina:
            cn.execute("INSERT OR REPLACE INTO etiqueta (actividad_id, tipo, valor, origen, confianza) "
                       "VALUES (?, 'piscina', ?, 'manual', 'alta')", (fila["id"], str(args.piscina)))
            cn.execute("UPDATE natacion_sesion SET largo_piscina_m = ? WHERE actividad_id = ?",
                       (args.piscina, fila["id"]))
        cn.commit()
        print(f"Etiquetada la actividad {args.id_garmin}")
    elif args.orden == "recalcular":
        n = importar.recalcular_series(cn)
        comparables = cn.execute("SELECT COUNT(*) FROM serie WHERE comparable = 1").fetchone()[0]
        print(f"Series recalculadas desde los laps: {n} ({comparables} comparables)")
    elif args.orden == "valoracion":
        _valoracion(cn, args.refrescar, args.sesion)
    elif args.orden == "analizar":
        datos = analitica.analizar(cn)   # ya trae las marcas oficiales y el plan (los pinta el cuadro de mando)
        json_ruta = analitica.guardar_json(datos, os.path.join(args.carpeta, "data", "derived", "analitica.json"))
        rutas = panel.escribir(datos, args.carpeta)
        k = datos["kpis"]
        comp = datos.get("competicion")
        if comp:
            r = comp["resumen"]
            h400 = min(comp["h400"], key=lambda m: m["segundos"]) if comp["h400"] else None
            print(f"Marcas oficiales: {r['total']} ({r['validas']} validas, {r['invalidas']} corruptas) en "
                  f"{r['competiciones']} competiciones, de {r['desde']} a {r['hasta']}")
            if h400:
                print(f"  mejor 400 libre: {h400['marca']} ({h400['ritmo_100']} s/100) el {h400['fecha']} "
                      f"en {h400['lugar']}")
        from . import plan as _plan
        sem = _plan.semana_de()
        if sem:
            print(f"Plan: {sem['clave']} ({sem['desde']} a {sem['hasta']}), {sem['km']} km - {sem['foco']}")
        print(f"Sesiones analizadas: {k['sesiones']} ({k['primera']} a {k['ultima']}, "
              f"{k['metros_totales'] / 1000:.0f} km)")
        print(f"Bloques seguidos: {k['bloques']} ({k.get('bloques_800', 0)} de mas de 800 m, "
              f"{k.get('verificados', 0)} verificados) | series: {k['series']} "
              f"({k.get('series_comparables', 0)} comparables)")
        print(f"Segmentos descubiertos: {k['segmentos']}  (el mas habitual: "
              f"{datos['segmentos'][0]['nombre']} x{datos['segmentos'][0]['apariciones']})"
              if datos["segmentos"] else "Segmentos descubiertos: 0")
        for etiqueta, clave in (("400 m", "mejor_400"), ("1.000 m", "mejor_1000"), ("1.500 m", "mejor_1500")):
            m = k.get(clave)
            if m:
                print(f"  marca de referencia en bloques de {etiqueta:<7}: {m['fiable']} s/100 "
                      f"(mediana de las 3 mejores de {m['veces']} veces; la mejor registrada {m['absoluto']} "
                      f"s/100 el {m['fecha']})")
        print(f"\nCuadro de mando: {rutas['panel']}\nInforme: {rutas['informe']}\nDatos: {json_ruta}")
        bk = datos.get("bici", {}).get("kpis")
        if bk:
            print(f"Bici: {bk['salidas']} salidas ({bk['con_traza']} con traza), {bk['km']:.0f} km, "
                  f"{bk['desnivel']} m de desnivel | {bk['segmentos']} segmentos "
                  f"({bk['repetidos']} repetidos) con {bk['intentos']} intentos medidos")
    elif args.orden == "servir":
        return servidor.servir(args.bd, args.carpeta, args.puerto, regenerar=not args.rapido,
                               abrir=args.abrir, host=args.host)
    elif args.orden == "plan":
        from . import plan, plan_vivo
        if getattr(args, "generar", False):
            return _generar_semana(cn, args)
        if args.recalculado:
            print(plan_vivo.texto(cn, args.fecha))
        else:
            print(plan.texto(args.fecha, args.semana))
    elif args.orden == "partes":
        from . import partes
        if args.importar or args.escribir:
            ruta = args.escribir or args.ruta or partes.ruta_por_defecto()
            r = partes.importar(cn, ruta)
            if args.escribir:
                print(f"Parte dictado en el chat y guardado (de {ruta}): {r['leidos']} "
                      f"(nuevos {r['nuevos']}, ya estaban {r['actualizados']})")
            else:
                print(f"Partes leidos de {ruta}: {r['leidos']} (nuevos {r['nuevos']}, ya estaban {r['actualizados']})")
            if r["nuevos"] or r["actualizados"]:
                _rehacer_cuadro(cn, getattr(args, "carpeta", "."))
                print("Cuadro de mando rehecho: el plan se ha recalculado con los partes que han entrado.")
        elif args.pendientes:
            partes.mostrar_pendientes(cn, args.limite)
            return 0
        elif args.reaplicar:
            r = partes.reaplicar(cn)
            print(f"Partes revisados: {r['partes']} (aplicados {r['aplicados']}, sin sesion que les cuadre "
                  f"{r['sin_sesion']}). El material y los tiempos ya estan en los laps.")
        partes.mostrar(cn)
    elif args.orden == "prueba":
        return _prueba(cn, args)
    elif args.orden == "evaluar":
        from . import evaluacion
        if args.guardar:
            from . import plan as _plan
            for s in _plan.SEMANAS:
                prop = evaluacion.propuesta(cn, s["clave"])
                if prop["sesiones_plan"]:
                    clave = evaluacion.guardar_propuesta(cn, prop)
                    print(f"Ajuste propuesto apuntado: {clave} -> {prop['ajuste']['accion']}")
        evaluacion.mostrar(cn, args.semana, args.semanas)
    elif args.orden == "apuntes":
        from . import apuntes, partes
        ruta = args.ruta or apuntes.ruta_por_defecto()
        if args.importar:
            r = apuntes.importar(cn, ruta)
            print(f"Apuntes leidos de {ruta}: {r['leidas']} (nuevos {r['nuevas']}, ya estaban {r['actualizadas']})")
            print(f"  Peticiones de gimnasio: {r['peticiones']['leidas']} "
                  f"(nuevas {r['peticiones']['nuevas']}, ya estaban {r['peticiones']['actualizadas']})")
            print(f"  Sesiones de gimnasio  : {r['sesiones_gimnasio']['leidas']} "
                  f"(nuevas {r['sesiones_gimnasio']['nuevas']}, ya estaban {r['sesiones_gimnasio']['actualizadas']})")
            # El mismo fichero lleva los partes de natacion: se importan en la misma pasada.
            try:
                rp = partes.importar(cn, ruta)
                print(f"  Partes de natacion    : {rp['leidos']} "
                      f"(nuevos {rp['nuevos']}, ya estaban {rp['actualizados']})")
            except (FileNotFoundError, ValueError) as exc:
                print(f"  Partes de natacion    : no hay ninguno en el fichero ({exc})")
        apuntes.mostrar(cn, args.top)
    elif args.orden == "apunte":
        return _apunte(cn, args)
    elif args.orden == "fuerza":
        return _fuerza(cn, args)
    elif args.orden == "estado":
        return _estado(cn, args)
    elif args.orden == "conocimiento":
        return _conocimiento(cn, args)
    elif args.orden == "reglas":
        return _reglas(cn, args)
    elif args.orden == "decision":
        return _decision(cn, args)
    elif args.orden == "gimnasio":
        from . import apuntes, gimnasio
        if args.escribir:
            r = apuntes.escribir_prescrita(cn, args.escribir)
            print(f"Sesiones de gimnasio escritas: {r['escritas']} (desde {args.escribir})")
        if args.apuntar:
            return _apuntar_gimnasio(cn, args)
        if args.historial is not None:
            return _historial_gimnasio(cn, args)
        if args.plantilla:
            print(gimnasio.texto(cn))
            return 0
        apuntes.mostrar_gimnasio(cn)
    elif args.orden == "segmentos":
        r = bici.importar_segmentos(cn, args.export)
        print(f"Segmentos leidos del export: {r['leidos']} (nuevos {r['nuevos']}, ya estaban {r['ya_estaban']},"
              f" sin datos {r['sin_datos']})")
        m = bici.medir_esfuerzos(cn, pasadas=args.pasadas)
        print(f"Salidas de bici con traza: {m['salidas']} | intentos medidos: {m['intentos']} "
              f"(en {m['pasadas']} pasadas; distancia tipica conocida en {m['con_distancia']} segmentos, "
              f"{m['dudosos']} de ellos dudosos por haber mas de un camino; "
              f"{m['descartados']} veces la traza no pasaba por el segmento)")
        t = bici.anotar_rutas(cn)
        print(f"Trazas con distancia y desnivel calculados: {t['anotadas']} de {t['trazas']}")
        repetidos = cn.execute("SELECT COUNT(*) FROM (SELECT segmento_id FROM esfuerzo_bici"
                               " GROUP BY segmento_id HAVING COUNT(*) > 1)").fetchone()[0]
        print(f"Segmentos con intentos: {cn.execute('SELECT COUNT(DISTINCT segmento_id) FROM esfuerzo_bici').fetchone()[0]}"
              f" ({repetidos} hechos mas de una vez)")
        print("Siguiente: `bici` para ver tus segmentos, o `bici --segmento <nombre>` para un historial.")
    elif args.orden == "bici":
        return _bici(cn, args)
    elif args.orden == "minar":
        if args.poblaciones:
            segmentos_gpx.cargar_poblaciones(cn)
        if args.solo_minar:
            r = segmentos_gpx.minar(cn, args.disciplina, args.limite)
            segmentos_gpx.nombrar(cn)
        else:
            r = segmentos_gpx.minar_todo(cn, args.disciplina, args.limite)
        print(f"Tramos candidatos: {r['candidatos']} | segmentos guardados: {r['segmentos']} "
              f"(parejas de salidas comparadas: {r['parejas']}, {r['segundos']:.0f} s)")
        if "intentos" in r:
            print(f"Intentos medidos: {r['intentos']} | segmentos sin ningun intento: {r['sin_intentos']} "
                  f"| mediciones descartadas por no cuadrar: {r['descartados']}")
        print("Siguiente: `minados` para verlos, o `minados --segmento <n>` para todos tus tiempos.")
    elif args.orden == "minados":
        return _minados(cn, args)
    elif args.orden == "corregir":
        return _corregir(cn, args)
    elif args.orden == "portal":
        from . import portal
        destino = args.destino or portal.DESTINO
        r = portal.escribir(cn, destino)
        print(f"Portal escrito en {r['destino']} ({r['mb']} MB)")
        print(f"  {r['actividades']} actividades con mapa | {r['segmentos']} segmentos | "
              f"{r['intentos']} tiempos medidos")
        print("Abrelo con doble clic (necesita internet solo para el mapa).")
    elif args.orden == "competicion":
        from . import competicion
        ruta = args.csv or competicion.RUTA_CSV
        if not args.sin_importar:
            r = competicion.importar(cn, ruta)
            print(f"Marcas leidas de {ruta}: {r['leidas']} (nuevas {r['nuevas']}, actualizadas {r['actualizadas']},"
                  f" no validas {r['invalidas']})")
            print("  clasificacion por dia: " + ", ".join(f"{k} {v}" for k, v in sorted(r["tipos"].items())))
        elif args.clasificar:
            print("clasificacion por dia: " + ", ".join(
                f"{k} {v}" for k, v in sorted(competicion.clasificar_y_guardar(cn).items())))
        competicion.mostrar(cn, args.estilo, args.distancia, args.piscina, args.temporada, args.desde,
                            args.hasta, args.lugar, args.orden_marcas, args.comparar)
    elif args.orden == "series":
        # La fecha no esta en la tabla de series: vive en la actividad (join).
        sql = """SELECT a.inicio_local AS fecha, a.id_garmin, s.rep_m, s.n_reps,
                        ROUND(s.ritmo_medio_100,1) ritmo, ROUND(s.mejor_100,1) mejor,
                        ROUND(s.deriva_s,1) deriva, s.material, a.sub_disciplina, l.largo_piscina_m
                 FROM serie s JOIN actividad a ON a.id = s.actividad_id
                 JOIN natacion_sesion l ON l.actividad_id = a.id
                 WHERE 1=1"""
        if args.metros:
            sql += f" AND s.rep_m = {int(args.metros)}"
        if args.comparables:
            sql += " AND s.comparable = 1"
        sql += " ORDER BY s.ritmo_medio_100 LIMIT ?"
        print(f"  {'fecha':<19} {'serie':>11} {'ritmo':>7} {'mejor':>7} {'deriva':>7}  {'piscina':>7}  material")
        for fila in cn.execute(sql, (args.top,)):
            piscina = f"{fila['largo_piscina_m']:g} m" if fila["largo_piscina_m"] else "aguas ab."
            print(f"  {(fila['fecha'] or '')[:19]:<19} {fila['n_reps']}x{int(fila['rep_m'])} m".ljust(30)
                  + f"{fila['ritmo']:>6} {fila['mejor']:>6} {fila['deriva']:>6}  {piscina:>8}  {fila['material']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
