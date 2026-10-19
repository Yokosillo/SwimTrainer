"""Garmin Connect: traer a este proyecto las actividades reales de la nube.

Esto NO es la app del movil ni el reloj: habla con connect.garmin.com con tu cuenta, igual que la web.
La sesion se guarda como token OAuth en ~/.garminconnect y dura alrededor de un anio, asi que se hace
login UNA vez. Las credenciales (correo y contrasenia) NO se guardan en ningun sitio.

Subcomandos:

    python scripts/garmin_conectar.py login                    # primer login (pide correo, contrasenia y MFA)
    python scripts/garmin_conectar.py estado                   # quien soy y si la sesion sigue viva
    python scripts/garmin_conectar.py actividades --desde 2026-10-01 [--hasta hoy] [--tipo swimming]
    python scripts/garmin_conectar.py bajar <id_actividad>     # baja el FIT original de una actividad
    python scripts/garmin_conectar.py traer --desde 2026-10-01 # baja los FIT nuevos y los mete en la base

En el PC, el primer login tiene su propio lanzador de doble clic: `conectar-garmin.bat`.
"""

import argparse
import os
import sys
from datetime import date, timedelta
from getpass import getpass
from pathlib import Path
from zipfile import ZipFile
import io
import tempfile

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TOKENS_POR_DEFECTO = "~/.garminconnect"          # la libreria guarda aqui garmin_tokens.json
CARPETA_FIT_POR_DEFECTO = RAIZ / "data" / "garmin"

# Que se considera "ya en la base". OJO: NO vale comparar por id. El id que guarda un export de Strava
# (`id_garmin` = el nombre del fichero) NO es el `activityId` de Garmin Connect: comprobado, la API no
# reconoce esos ids (21670453554 da error, mientras el de la misma sesion en Connect es 24660045743).
# Lo fiable es el dia y la distancia.
TOLERANCIA_M = 150          # la distancia de natacion del reloj y la contada por largos difieren en metros
SQL_YA_EN_BASE = """
    SELECT COUNT(*) FROM actividad
    WHERE disciplina = ? AND substr(inicio_local, 1, 10) = ? AND ABS(distancia_m - ?) <= ?
"""
SQL_YA_EN_BASE_SIN_DISCIPLINA = """
    SELECT COUNT(*) FROM actividad
    WHERE substr(inicio_local, 1, 10) = ? AND ABS(distancia_m - ?) <= ?
"""

# El `typeKey` de Garmin Connect a la disciplina que usa este proyecto (ver DISCIPLINAS_CSV de importar.py).
DISCIPLINA_GARMIN = {
    "lap_swimming": "natacion", "open_water_swimming": "natacion",
    "cycling": "ciclismo", "road_biking": "ciclismo", "indoor_cycling": "ciclismo",
    "running": "carrera", "treadmill_running": "carrera", "trail_running": "carrera",
    "walking": "caminata", "hiking": "senderismo",
    "strength_training": "gimnasio", "indoor_cardio": "gimnasio", "fitness_equipment": "gimnasio",
}


def _disciplina_de_garmin(actividad: dict) -> str | None:
    """Traduce el tipo de Garmin a la disciplina del proyecto; None si no lo conozco."""
    tipo = (actividad.get("activityType") or {}).get("typeKey") or ""
    return DISCIPLINA_GARMIN.get(tipo)


def _ya_en_base(cn, fecha_local: str, metros: float, disciplina: str | None = None) -> bool:
    """Dice si esa sesion ya esta en la base, mirando dia + distancia (no el id, ver arriba).

    Si no se conoce la disciplina, se compara solo dia + distancia: mejor eso que dar por nueva una
    sesion que ya esta (el error contrario, un duplicado, es peor).
    """
    if not fecha_local or not metros:
        return False
    if disciplina:
        fila = cn.execute(SQL_YA_EN_BASE, (disciplina, fecha_local[:10], metros, TOLERANCIA_M)).fetchone()
    else:
        fila = cn.execute(SQL_YA_EN_BASE_SIN_DISCIPLINA, (fecha_local[:10], metros, TOLERANCIA_M)).fetchone()
    return bool(fila and fila[0])


def _tokens() -> str:
    return str(Path(os.environ.get("GARMINTOKENS", TOKENS_POR_DEFECTO)).expanduser())


def _sesion(avisar: bool = True):
    """Devuelve un cliente con sesion, o None si no hay token guardado."""
    from garminconnect import Garmin, GarminConnectAuthenticationError, GarminConnectConnectionError

    cliente = Garmin()
    try:
        cliente.login(_tokens())
        return cliente
    except (GarminConnectAuthenticationError, GarminConnectConnectionError) as err:
        if avisar:
            print("No hay sesion guardada (o ha caducado).")
            print("  -> primer login:  doble clic en conectar-garmin.bat")
            print(f"     (detalle: {type(err).__name__})")
        return None


def _fecha(texto: str, por_defecto: str) -> str:
    return (texto or por_defecto).strip()


def cmd_login(args) -> int:
    """Primer login: pide correo y contrasenia por consola y guarda el token."""
    from garminconnect import (
        Garmin,
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarminConnectTooManyRequestsError,
    )

    print("=== Primer login en Garmin Connect (solo hace falta UNA vez) ===")
    print("Tu correo y tu contrasenia son los de connect.garmin.com (o los de la app del movil).")
    print("No se guardan en ningun sitio: al terminar solo queda un token en", _tokens())
    print()

    correo = os.environ.get("GARMIN_EMAIL") or input("Correo de Garmin: ").strip()
    if not correo:
        print("Sin correo no sigo.")
        return 1
    contrasenia = os.environ.get("GARMIN_PASSWORD") or getpass("Contrasenia (no se ve al escribir): ")
    if not contrasenia:
        print("Sin contrasenia no sigo.")
        return 1

    cliente = Garmin(
        email=correo,
        password=contrasenia,
        prompt_mfa=lambda: input("Codigo que te acaba de pedir Garmin (MFA): ").strip(),
    )
    contrasenia = None

    try:
        cliente.login(_tokens())
    except GarminConnectAuthenticationError:
        print()
        print("Correo o contrasenia incorrectos. Vuelve a intentarlo.")
        return 1
    except GarminConnectTooManyRequestsError:
        print()
        print("Garmin esta cortando tantos intentos. Espera un rato y prueba otra vez.")
        return 1
    except GarminConnectConnectionError as err:
        print()
        print(f"No he podido conectar con Garmin: {err}")
        return 1

    nombre = cliente.get_full_name() or "?"
    print()
    print(f"Listo. Sesion guardada para {nombre}.")
    print(f"Token en: {_tokens()}")
    print("No hace falta repetir esto hasta dentro de un anio (o si cambias la contrasenia).")
    return 0


def cmd_estado(args) -> int:
    """Dice si la sesion sigue viva, y de quien es."""
    tokens = _tokens()
    fichero = Path(tokens) / "garmin_tokens.json"
    print(f"Token: {fichero}  ({'existe' if fichero.exists() else 'NO existe'})")
    cliente = _sesion()
    if cliente is None:
        return 1
    try:
        nombre = cliente.get_full_name()
        unidad = cliente.get_unit_system()
        print(f"Sesion viva. Cuenta: {nombre} (unidades: {unidad})")
        try:
            reloj = cliente.get_device_last_used()
            print(f"Ultimo reloj usado: {reloj.get('deviceName', '?')}")
        except Exception:
            pass
    except Exception as err:
        print(f"La sesion responde a medias: {err}")
        return 1
    return 0


def cmd_actividades(args) -> int:
    """Lista actividades de Garmin Connect entre dos fechas, marcando las que ya estan en la base."""
    from entrenador import db

    desde = _fecha(args.desde, (date.today() - timedelta(days=30)).isoformat())
    hasta = _fecha(args.hasta, date.today().isoformat())
    cliente = _sesion()
    if cliente is None:
        return 1

    actividades = cliente.get_activities_by_date(desde, hasta, args.tipo or None) or []
    print(f"{len(actividades)} actividades entre {desde} y {hasta}"
          + (f" de tipo {args.tipo}" if args.tipo else "") + ":")

    cn = db.conectar(args.bd)
    ya = 0
    for a in actividades[: args.limite or len(actividades)]:
        aid = str(a.get("activityId"))
        seg = a.get("duration") or 0
        km = (a.get("distance") or 0) / 1000
        conocida = _ya_en_base(cn, a.get("startTimeLocal"), a.get("distance") or 0, _disciplina_de_garmin(a))
        ya += 1 if conocida else 0
        marca = "en la base" if conocida else "NUEVA"
        print("  %-12s %-10s %-22s %5.0f min %6.2f km  id=%s  [%s]" % (
            (a.get("startTimeLocal") or "")[:10], a.get("activityType", {}).get("typeKey", ""),
            (a.get("activityName") or "")[:22], seg / 60, km, aid, marca))
    print(f"\nYa en la base: {ya}. Nuevas: {len(actividades) - ya}.")
    return 0


def _escribir_fit(datos: bytes, destino: Path) -> Path:
    """El formato ORIGINAL de Garmin a veces viene envuelto en un zip: lo desenvuelve si hace falta."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    if datos[:2] == b"PK":                       # es un zip: dentro va el .fit (y puede venir el .csv)
        with ZipFile(io.BytesIO(datos)) as z:
            fits = [n for n in z.namelist() if n.lower().endswith(".fit")]
            if not fits:
                raise ValueError("el zip no traia ningun .fit")
            destino.write_bytes(z.read(fits[0]))
    else:
        destino.write_bytes(datos)
    return destino


def bajar_actividades(fechas: tuple[str, str], tipo: str | None, carpeta: Path, limite: int | None,
                      solo_nuevas: bool, bd: str) -> list[Path]:
    """Baja a disco los FIT originales de las actividades del rango. Devuelve los ficheros escritos."""
    from garminconnect import Garmin
    from entrenador import db

    cliente = _sesion()
    if cliente is None:
        return []

    desde, hasta = fechas
    actividades = cliente.get_activities_by_date(desde, hasta, tipo or None) or []
    if limite:
        actividades = actividades[:limite]

    cn = db.conectar(bd)
    escritos = []
    for a in actividades:
        aid = str(a.get("activityId"))
        if solo_nuevas and _ya_en_base(cn, a.get("startTimeLocal"), a.get("distance") or 0,
                                       _disciplina_de_garmin(a)):
            print(f"  {aid} ya estaba en la base (mismo dia y distancia)")
            continue
        destino = carpeta / f"{aid}.fit"
        if destino.exists():
            print(f"  {aid} ya bajado")
            escritos.append(destino)
            continue
        try:
            datos = cliente.download_activity(aid, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
            print(f"  bajado {aid} -> {_escribir_fit(datos, destino).name}")
            escritos.append(destino)
        except Exception as err:
            print(f"  {aid}: no he podido bajarlo ({type(err).__name__}: {err})")
    return escritos


def cmd_bajar(args) -> int:
    """Baja el FIT original de una actividad concreta."""
    from garminconnect import Garmin

    cliente = _sesion()
    if cliente is None:
        return 1
    destino = Path(args.a) if args.a else _escribir_destino(CARPETA_FIT_POR_DEFECTO, args.id)
    datos = cliente.download_activity(str(args.id), dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
    print("Guardado en", _escribir_fit(datos, destino))
    return 0


def _escribir_destino(carpeta: Path, aid: str) -> Path:
    return carpeta / f"{aid}.fit"


def traer(fechas: tuple[str, str], tipo: str | None, carpeta: Path, limite: int | None,
          solo_nuevas: bool, bd: str) -> dict:
    """Baja los FIT que falten y los mete en la base. Devuelve el recuento, no solo lo imprime.

    Es la parte reutilizable de `traer` por consola: el boton del portal llama a esta misma funcion (a traves
    del servidor local), para que el portal y la consola no puedan hacer cosas distintas.
    """
    from entrenador import importar, sueno

    ficheros = bajar_actividades(fechas, tipo, carpeta, limite, solo_nuevas=solo_nuevas, bd=bd)
    # El sueno de esas mismas fechas entra por la misma puerta (V1.2-07): el atleta no tiene que acordarse de nada.
    noches = sueno_de(fechas, bd)
    if not ficheros:
        return {"ficheros": [], "importacion": None, "sueno": noches}
    resultado = importar.importar_carpeta(importar.db.conectar(bd), str(carpeta), fuente="garmin_connect")
    return {"ficheros": [str(f) for f in ficheros], "importacion": resultado, "sueno": noches}


def sueno_de(fechas: tuple[str, str], bd: str, cliente=None, limite: int | None = None) -> dict:
    """Baja el sueno del rango y lo guarda. Sin sesion de Garmin no falla: dice que no lo ha podido traer."""
    from entrenador import importar, sueno

    cliente = cliente or _sesion(avisar=False)
    if cliente is None:
        return {"noches": 0, "nuevas": 0, "actualizadas": 0, "aviso": "sin sesion de Garmin"}
    noches = sueno.noches_de(fechas, limite, cliente=cliente)
    return sueno.guardar(importar.db.conectar(bd), noches, fuente="garmin_connect")


def cmd_sueno(args) -> int:
    """Baja el sueno del rango y lo guarda en la base (V1.2-07)."""
    desde = _fecha(args.desde, (date.today() - timedelta(days=30)).isoformat())
    hasta = _fecha(args.hasta, date.today().isoformat())

    print(f"Bajando el sueno de Garmin Connect ({desde} -> {hasta})")
    r = sueno_de((desde, hasta), args.bd, limite=args.limite)
    if r.get("aviso"):
        print(f"No se ha podido traer: {r['aviso']}. Prueba con conectar-garmin.bat.")
        return 1
    print(f"Noches del reloj: {r['noches']} ({r['nuevas']} nuevas, {r['actualizadas']} refrescadas)")
    return 0


def cmd_traer(args) -> int:
    """El flujo completo: baja los FIT nuevos del rango y los mete en la base con el importador."""
    desde = _fecha(args.desde, (date.today() - timedelta(days=30)).isoformat())
    hasta = _fecha(args.hasta, date.today().isoformat())
    carpeta = Path(args.carpeta) if args.carpeta else CARPETA_FIT_POR_DEFECTO

    print(f"Bajando de Garmin Connect ({desde} -> {hasta}) a {carpeta}")
    r = traer((desde, hasta), args.tipo, carpeta, args.limite, solo_nuevas=not args.todas, bd=args.bd)
    if not r["importacion"]:
        print("No hay nada nuevo que traer.")
        return 0

    print(f"\nImportando {len(r['ficheros'])} ficheros FIT en la base {args.bd}")
    print("Importacion:", r["importacion"])
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Garmin Connect: traer las actividades reales a este proyecto")
    p.add_argument("--bd", default="data/entrenador.db", help="base de datos (por defecto la real)")
    sub = p.add_subparsers(dest="orden", required=True)

    sub.add_parser("estado", help="dice si la sesion sigue viva y de quien es").set_defaults(fn=cmd_estado)
    sub.add_parser("login", help="primer login; guarda el token (~1 anio)").set_defaults(fn=cmd_login)

    a = sub.add_parser("actividades", help="lista las actividades del rango")
    a.add_argument("--desde", default=None)
    a.add_argument("--hasta", default=None)
    a.add_argument("--tipo", default="swimming", help="swimming, cycling, running... (vacio = todas)")
    a.add_argument("--limite", type=int, default=40)
    a.set_defaults(fn=cmd_actividades)

    b = sub.add_parser("bajar", help="baja el FIT original de una actividad")
    b.add_argument("id")
    b.add_argument("--a", default=None, help="ruta del fichero de salida")
    b.set_defaults(fn=cmd_bajar)

    t = sub.add_parser("traer", help="baja los FIT nuevos y los importa a la base")
    t.add_argument("--desde", default=None)
    t.add_argument("--hasta", default=None)
    t.add_argument("--tipo", default="swimming")
    t.add_argument("--carpeta", default=None)
    t.add_argument("--limite", type=int, default=None)
    t.add_argument("--todas", action="store_true", help="baja tambien las que ya estan en la base")
    t.set_defaults(fn=cmd_traer)

    s = sub.add_parser("sueno", help="baja el sueno del reloj y lo guarda en la base")
    s.add_argument("--desde", default=None)
    s.add_argument("--hasta", default=None)
    s.add_argument("--limite", type=int, default=None)
    s.set_defaults(fn=cmd_sueno)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
