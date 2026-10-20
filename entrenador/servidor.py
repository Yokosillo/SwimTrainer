"""Servidor local del cuadro de mando: sirve `cuadro/panel.html` y recibe los partes que se suben desde el portal.

Es lo que hace que el boton "Subir" funcione sin bajar ficheros ni teclear ordenes: el portal es un fichero
suelto (se abre con doble clic) y no puede escribir en la base por su cuenta, asi que le manda el parte a este
servidor, que corre en este mismo PC (127.0.0.1) y escribe en SQLite. No sale nada a la red.

Se levanta con `python -m entrenador.cli servir` (o doble clic en `servir-entrenador.bat`, que ademas abre el
cuadro de mando en el navegador). Mientras siga abierto, el boton "Subir" del portal mete el parte en la base y
recarga el cuadro con los datos ya actualizados.
"""
from __future__ import annotations

import base64
import contextlib
import hmac
import importlib.util
import io
import json
import os
import threading
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import analitica, db, panel, partes

PUERTO_POR_DEFECTO = 8181
HOST_POR_DEFECTO = os.environ.get("ENTRENADOR_HOST", "127.0.0.1")
# Para servirlo fuera del propio PC (Docker detras de Caddy, por ejemplo) se pone una contrasenia.
# Sin `ENTRENADOR_CLAVE` el servidor se queda como siempre: abierto solo para 127.0.0.1.
USUARIO_POR_DEFECTO = os.environ.get("ENTRENADOR_USUARIO", "atleta")
CLAVE_POR_DEFECTO = os.environ.get("ENTRENADOR_CLAVE", "")
MAX_CUERPO = 4 * 1024 * 1024  # un parte con muchas series cabe de sobra; mas que esto es un error
DIAS_GARMIN_POR_DEFECTO = 21  # lo que mira el boton del portal hacia atras si no se le dice otra cosa


def _cargar_garmin(carpeta: str):
    """Carga `scripts/garmin_conectar.py` por ruta.

    No es un paquete (vive en `scripts/`), asi que se carga a mano: el boton del portal usa **el mismo codigo**
    que la consola, en vez de una copia que se quede desfasada.
    """
    ruta = os.path.join(carpeta, "scripts", "garmin_conectar.py")
    if not os.path.isfile(ruta):
        raise FileNotFoundError(f"no encuentro {ruta}")
    spec = importlib.util.spec_from_file_location("garmin_conectar_portal", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class _Base:
    """La base de datos y el panel, con una conexion SQLite por hilo (el servidor atiende en varios).

    `traer` se puede inyectar (lo hacen las pruebas) para probar el boton del Garmin sin tocar la red.
    """

    def __init__(self, ruta_bd: str, carpeta: str, regenerar: bool = True, traer=None, coach=None):
        self.ruta_bd = ruta_bd
        self.carpeta = carpeta
        self.regenerar = regenerar
        self.traer = traer
        self.coach = coach
        self.local = threading.local()

    def cn(self):
        cn = getattr(self.local, "cn", None)
        if cn is None:
            cn = self.local.cn = db.conectar(self.ruta_bd)
        return cn

    def renovar(self):
        """Tira la conexion del hilo para que la siguiente sea nueva.

        Hace falta cuando lo que ha cambiado lo ha escrito **otra** conexion (el importador que mete lo del
        Garmin): una conexion abierta antes se queda con la foto de entonces y no veria lo recien metido, asi
        que el cuadro se reharia sin la sesion nueva.
        """
        cn = getattr(self.local, "cn", None)
        if cn is not None:
            cn.close()
            self.local.cn = None

    def subir(self, datos) -> dict:
        """Mete el parte en la base y rehace el cuadro de mando para que el portal lo vea ya todo al dia."""
        r = partes.importar_datos(self.cn(), datos, origen="portal (Subir)")
        if self.regenerar:
            panel.escribir(analitica.analizar(self.cn()), self.carpeta)
        return r

    def decidir(self, opciones: dict | None = None) -> dict:
        """Lo que el atleta hace con una propuesta: aceptarla, cambiarla (con motivo) o ignorarla (V1.3-03).

        Lo que no cuadra (una decision que no existe, un cambio sin motivo) es un error del atleta, y se le cuenta
        como tal: `ValueError`, que el portal enseña en el aviso. Aqui no se inventa nada.
        """
        from . import decision
        opciones = opciones or {}
        decision.decidir(self.cn(), opciones.get("recomendacion_id"), opciones.get("tomada") or "",
                         respuesta=opciones.get("respuesta"), motivo=opciones.get("motivo"))
        return self.datos_entrenador()

    def proponer_semana(self, opciones: dict | None = None) -> dict:
        """Guarda la propuesta de la semana que toca, con su porque (V1.3-02): el boton del portal y el CLI.

        Devuelve lo guardado y el estado nuevo del bucle cerrado, para que el portal lo pinte sin recargar.
        """
        from . import decision
        r = decision.proponer_semana(self.cn(), (opciones or {}).get("fecha"))
        if self.regenerar:
            panel.escribir(analitica.analizar(self.cn()), self.carpeta)
        return {**r, "entrenador": self.datos_entrenador()}

    def datos_entrenador(self) -> dict:
        """El credito de las reglas y las propuestas enteras: lo que pinta la vista Reglas."""
        from . import decision
        return decision.datos_entrenador(self.cn())

    def evaluar_sesion(self, opciones: dict | None = None) -> dict:
        """La valoracion del entrenador de UN entrenamiento: lo que hace el boton "Evaluar" del portal.

        Sin `actividad_id` (o con `ultimo`), coge la ultima sesion de natacion. No toca el Garmin ni la base:
        lee lo que ya hay (laps, parte, plan) y compone el discurso de esa sesion.
        """
        from . import valoracion
        opciones = opciones or {}
        cn = self.cn()
        actividad_id = opciones.get("actividad_id")
        if not actividad_id:
            fila = cn.execute(
                """SELECT a.id FROM actividad a JOIN natacion_sesion s ON s.actividad_id = a.id
                   ORDER BY a.inicio_local DESC LIMIT 1""").fetchone()
            if not fila:
                return {"ok": True, "evaluacion": None, "aviso": "no hay ninguna sesion de natacion"}
            actividad_id = int(fila["id"])
        datos = {}
        ficha = os.path.join(self.carpeta, "data", "derived", "analitica.json")
        if os.path.isfile(ficha):
            try:
                with open(ficha, encoding="utf-8") as f:
                    datos = json.load(f) or {}
            except (ValueError, OSError):
                datos = {}
        v = valoracion.sesion(cn, int(actividad_id), datos)
        return {"ok": True, "evaluacion": v,
                "aviso": None if v else f"no encuentro la sesion {actividad_id}"}

    def explicar_coach(self, datos: dict | None = None) -> dict:
        """Capa LLM opcional: solo reformula una recomendación; nunca decide ni calcula."""
        from . import coach_llm
        datos = datos or {}
        proveedor = self.coach
        if proveedor is None:
            proveedor = coach_llm.construir_desde_entorno()
        if proveedor is None:
            return {"ok": False, "codigo": 403,
                    "error": "capa LLM apagada o sin configurar (COACH_ENABLED/COACH_API_KEY)"}
        rec = datos.get("recomendacion")
        if not isinstance(rec, dict):
            raise ValueError("falta la recomendacion para explicar")
        return coach_llm.explicar(self.cn(), rec, datos.get("pregunta"), proveedor=proveedor, activo=True)

    def traer_del_garmin(self, opciones: dict | None = None) -> dict:
        """Trae de Garmin Connect lo que falte y lo mete en la base: lo que hace el boton del portal.

        Mismo camino que `python scripts/garmin_conectar.py traer`: baja los FIT originales que no estan en la
        base (se compara por **dia + disciplina + distancia**, nunca por id) y los importa. No se guardan
        credenciales: usa el token OAuth que ya dejo el atleta con `conectar-garmin.bat`.
        """
        if self.traer is not None:
            return self.traer(opciones or {})

        opciones = opciones or {}
        modulo = _cargar_garmin(self.carpeta)
        hasta = opciones.get("hasta") or date.today().isoformat()
        dias = int(opciones.get("dias") or DIAS_GARMIN_POR_DEFECTO)
        desde = opciones.get("desde") or (date.today() - timedelta(days=dias)).isoformat()
        carpeta_fit = Path(opciones["carpeta"]) if opciones.get("carpeta") else modulo.CARPETA_FIT_POR_DEFECTO

        self.renovar()  # el importador abre su propia conexion: la del hilo tiene que partir de cero
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            r = modulo.traer((desde, hasta), opciones.get("tipo") or None, carpeta_fit,
                             opciones.get("limite"), solo_nuevas=not opciones.get("todas"), bd=self.ruta_bd)
        importacion = r.get("importacion") or {}
        nuevos = int(importacion.get("nuevos") or 0)
        recargar = False
        if nuevos and self.regenerar:
            # Lo que ha entrado tiene que aparecer ya en el cuadro: se rehace antes de decirlo al portal.
            self.renovar()  # y con una conexion nueva, para que vea lo que acaba de meter el importador
            panel.escribir(analitica.analizar(self.cn()), self.carpeta)
            recargar = True
        return {"traidos": len(r["ficheros"]), "nuevos": nuevos, "importacion": importacion or None,
                "desde": desde, "hasta": hasta, "recargar": recargar, "consola": salida.getvalue().strip()}


def _handler(base: _Base):
    # Se leen al montar el servidor (y no al importar el modulo) para que las pruebas puedan
    # encender y apagar la contrasenia sin recargar nada.
    usuario = os.environ.get("ENTRENADOR_USUARIO", USUARIO_POR_DEFECTO)
    clave = os.environ.get("ENTRENADOR_CLAVE", CLAVE_POR_DEFECTO)

    class Handler(BaseHTTPRequestHandler):
        server_version = "Entrenador"

        def log_message(self, fmt, *args):  # consola corta y con hora, sin el ruido del modulo
            print("  " + (fmt % args), flush=True)

        # ---------------------------------------------------------------- utilidades

        def _cors(self):
            # El portal puede estar abierto como fichero (file://): hay que dejarle hablar con 127.0.0.1.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def _autorizado(self) -> bool:
            """HTTP Basic, solo si hay contrasenia configurada.

            En el PC de casa no hay ninguna y todo sigue abierto en 127.0.0.1. Cuando se sirve en red
            (Docker detras de Caddy) la contrasenia va en `ENTRENADOR_CLAVE`: los datos de entrenamiento
            son personales y no pueden quedar a la vista de cualquiera que llegue a la maquina.
            """
            if not clave:
                return True
            cabecera = self.headers.get("Authorization", "")
            if not cabecera.startswith("Basic "):
                return False
            try:
                descifrado = base64.b64decode(cabecera[6:]).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return False
            quien, separador, lo_que_pasa = descifrado.partition(":")
            return (bool(separador)
                    and hmac.compare_digest(quien, usuario)
                    and hmac.compare_digest(lo_que_pasa, clave))

        def _pedir_credenciales(self):
            cuerpo = "Entrenador: hace falta usuario y contrasenia.\n".encode("utf-8")
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Entrenador", charset="UTF-8"')
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(cuerpo)

        def _responder(self, codigo: int, cuerpo: bytes, tipo: str):
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(cuerpo)

        def _json(self, codigo: int, obj: dict):
            self._responder(codigo, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                            "application/json; charset=utf-8")

        # ------------------------------------------------------------------ rutas

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            ruta = self.path.split("?")[0]
            # `/salud` queda fuera de la contrasenia: es lo que consultan Docker y el portal de estado.
            if ruta != "/salud" and not self._autorizado():
                self._pedir_credenciales()
                return
            if ruta in ("/", "/panel.html", "/index.html"):
                ficha = os.path.join(base.carpeta, "cuadro", "panel.html")
                if not os.path.isfile(ficha):
                    self._json(404, {"ok": False, "error": "todavia no hay cuadro/panel.html: lanza `analizar`"})
                    return
                with open(ficha, "rb") as f:
                    self._responder(200, f.read(), "text/html; charset=utf-8")
                return
            if ruta in ("/strava", "/strava/", "/strava/index.html"):
                # El boton "Portal de bici" del panel enlaza con `strava/index.html`, al lado de la pagina.
                ficha = os.path.join(base.carpeta, "cuadro", "strava", "index.html")
                if not os.path.isfile(ficha):
                    self._json(404, {"ok": False, "error": "todavia no hay portal de bici: lanza `portal`"})
                    return
                with open(ficha, "rb") as f:
                    self._responder(200, f.read(), "text/html; charset=utf-8")
                return
            if ruta == "/salud":
                self._json(200, {"ok": True, "base": base.ruta_bd, "regenerar": base.regenerar})
                return
            if ruta == "/gimnasio":
                # La plantilla del gimnasio con lo ultimo de cada ejercicio: la pinta la vista de Gimnasio.
                from . import gimnasio
                try:
                    self._json(200, {"ok": True, **gimnasio.hoja(base.cn())})
                except Exception as exc:
                    print(f"  no se pudo leer el gimnasio: {exc}", flush=True)
                    self._json(500, {"ok": False, "error": str(exc)})
                return
            if ruta == "/garmin":
                # Solo informa (no toca la red): si hay token guardado y en que carpeta.
                try:
                    modulo = _cargar_garmin(base.carpeta)
                    tokens = modulo._tokens()
                except Exception:
                    tokens = ""
                ficha = os.path.join(tokens, "garmin_tokens.json") if tokens else ""
                self._json(200, {"ok": True, "token": bool(ficha and os.path.isfile(ficha)), "tokens": tokens})
                return
            self._json(404, {"ok": False, "error": "no hay nada en " + ruta})

        def do_POST(self):
            if not self._autorizado():
                self._pedir_credenciales()
                return
            ruta = self.path.split("?")[0]
            if ruta == "/gimnasio":
                self._apuntar_gimnasio()
                return
            if ruta == "/garmin/traer":
                self._traer_garmin()
                return
            if ruta == "/evaluar":
                self._evaluar()
                return
            if ruta == "/decision":
                self._decidir()
                return
            if ruta == "/plan/generar":
                self._proponer_semana()
                return
            if ruta == "/coach":
                self._coach()
                return
            if ruta != "/partes":
                self._json(404, {"ok": False, "error": "no hay nada en " + self.path})
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n <= 0 or n > MAX_CUERPO:
                self._json(400, {"ok": False, "error": "el parte viene vacio o es demasiado grande"})
                return
            try:
                datos = json.loads(self.rfile.read(n).decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                self._json(400, {"ok": False, "error": "no entiendo el parte: " + str(exc)})
                return
            try:
                r = base.subir(datos)
            except Exception as exc:  # se le cuenta al portal, que lo enseña en el aviso
                print(f"  no se pudo meter el parte: {exc}", flush=True)
                self._json(500, {"ok": False, "error": str(exc)})
                return
            print(f"  parte recibido y metido en la base: {r['leidos']} leidos (nuevos {r['nuevos']}, "
                  f"ya estaba {r['actualizados']})", flush=True)
            self._json(200, {"ok": True, "recargar": bool(base.regenerar), **r})

        def _cuerpo(self, aviso: str):
            """El JSON del cuerpo de una peticion. Si no se entiende, contesta 400 y devuelve None.

            Existe para que las ordenes nuevas no repitan (ni se salten) el mismo cuidado con el tamaño del cuerpo.
            """
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n <= 0 or n > MAX_CUERPO:
                self._json(400, {"ok": False, "error": "no viene nada: " + aviso})
                return None
            try:
                return json.loads(self.rfile.read(n).decode("utf-8")) or {}
            except (ValueError, UnicodeDecodeError) as exc:
                self._json(400, {"ok": False, "error": aviso + ": " + str(exc)})
                return None

        def _decidir(self):
            """Los botones Aceptar / Cambiar / Ignorar de la vista Reglas (V1.3-03).

            El cuerpo lleva `{"recomendacion_id": 3, "tomada": "cambiada", "motivo": "el jueves no pude"}`. Devuelve
            el bucle cerrado al dia (propuestas y credito), que es lo que el portal repinta.
            """
            datos = self._cuerpo("no entiendo la decision")
            if datos is None:
                return
            try:
                estado = base.decidir(datos)
            except ValueError as exc:  # lo que no cuadra es cosa del atleta: se le dice, no es un fallo del servidor
                self._json(400, {"ok": False, "error": str(exc)})
                return
            except Exception as exc:
                print(f"  no se pudo registrar la decision: {exc}", flush=True)
                self._json(500, {"ok": False, "error": str(exc)})
                return
            print(f"  decision registrada: propuesta {datos.get('recomendacion_id')} -> {datos.get('tomada')}",
                  flush=True)
            self._json(200, {"ok": True, "entrenador": estado})

        def _proponer_semana(self):
            """El boton "Guardar la propuesta de esta semana": la guarda con su porque para poder decidirla.

            Sin cuerpo. No toca el entrenamiento: solo escribe lo que el motor ya estaba diciendo.
            """
            datos = self._cuerpo("no entiendo la peticion") or {}
            try:
                r = base.proponer_semana(datos)
            except Exception as exc:
                print(f"  no se pudo guardar la propuesta: {exc}", flush=True)
                self._json(500, {"ok": False, "error": str(exc)})
                return
            print(f"  propuesta guardada: {r.get('semana') or 'sin semana'} · {r.get('cuantas', 0)} dia(s)", flush=True)
            self._json(200, {"ok": True, **r})

        def _apuntar_gimnasio(self):
            """El boton "Guardar" de la vista de Gimnasio: lo que el atleta ha hecho, ejercicio a ejercicio.

            El cuerpo lleva `{"fecha": "2026-10-18", "ejercicios": [{ejercicio, series, reps, kg, nota}]}`; lo que no
            llegue se queda como estaba ese dia. No recarga el cuadro: devuelve la hoja nueva y el portal la pinta.
            """
            from . import gimnasio
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n <= 0 or n > MAX_CUERPO:
                self._json(400, {"ok": False, "error": "no viene nada que apuntar"})
                return
            try:
                datos = json.loads(self.rfile.read(n).decode("utf-8")) or {}
            except (ValueError, UnicodeDecodeError) as exc:
                self._json(400, {"ok": False, "error": "no entiendo lo apuntado: " + str(exc)})
                return
            try:
                r = gimnasio.apuntar(base.cn(), datos.get("fecha") or "", datos.get("ejercicios") or [])
            except ValueError as exc:  # lo que falta o no cuadra: se le dice al atleta, no es un fallo del servidor
                self._json(400, {"ok": False, "error": str(exc)})
                return
            except Exception as exc:  # se le cuenta al portal, que lo ensena en el aviso
                print(f"  no se pudo apuntar el gimnasio: {exc}", flush=True)
                self._json(500, {"ok": False, "error": str(exc)})
                return
            print(f"  gimnasio apuntado: {r['fecha']} · {len(r['ejercicios'])} ejercicio(s)", flush=True)
            self._json(200, {"ok": True, **r, "hoja": gimnasio.hoja(base.cn())})

        def _evaluar(self):
            """El boton "Evaluar" del portal: la valoracion del entrenador de un entrenamiento (o del ultimo).

            El cuerpo es opcional: `{"actividad_id": 1540}`. Sin nada, evalua la ultima sesion de natacion. No
            recarga el cuadro: devuelve el discurso, y el portal lo pinta donde esta.
            """
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            opciones = {}
            if 0 < n <= MAX_CUERPO:
                try:
                    opciones = json.loads(self.rfile.read(n).decode("utf-8")) or {}
                except (ValueError, UnicodeDecodeError) as exc:
                    self._json(400, {"ok": False, "error": "no entiendo la peticion: " + str(exc)})
                    return
            try:
                r = base.evaluar_sesion(opciones)
            except Exception as exc:  # se le cuenta al portal, que lo enseña en el aviso
                print(f"  no se pudo evaluar la sesion: {exc}", flush=True)
                self._json(500, {"ok": False, "error": str(exc)})
                return
            v = r.get("evaluacion") or {}
            print(f"  evaluacion: {v.get('fecha', '?')} {v.get('titulo', '')} "
                  f"({len(v.get('parrafos') or [])} parrafos)", flush=True)
            self._json(200, r)

        def _coach(self):
            """Explicar una recomendación con la capa LLM opcional; apagada por defecto."""
            from . import coach_llm
            proveedor = base.coach
            if proveedor is None and not coach_llm.activo_entorno():
                self._json(403, {"ok": False,
                                 "error": "capa LLM apagada o sin configurar (COACH_ENABLED=0)"})
                return
            datos = self._cuerpo("no entiendo la peticion al coach")
            if datos is None:
                return
            try:
                r = base.explicar_coach(datos)
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
                return
            except Exception as exc:
                print(f"  no se pudo explicar con el coach: {exc}", flush=True)
                self._json(500, {"ok": False, "error": str(exc)})
                return
            if not r.get("ok"):
                self._json(int(r.get("codigo") or 403), r)
                return
            print(f"  coach: {r.get('fuente')} · {len(r.get('citas') or [])} citas", flush=True)
            self._json(200, r)

        def _traer_garmin(self):
            """El boton del portal: baja de Garmin Connect lo que falte, lo mete en la base y lo cuenta.

            El cuerpo es opcional (`{"dias": 21}` o `{"desde": "...", "hasta": "...", "tipo": "swimming"}`). Sin
            nada, mira las ultimas tres semanas y todas las disciplinas. Puede tardar: baja el FIT de cada
            actividad nueva.
            """
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            opciones = {}
            if 0 < n <= MAX_CUERPO:
                try:
                    opciones = json.loads(self.rfile.read(n).decode("utf-8")) or {}
                except (ValueError, UnicodeDecodeError) as exc:
                    self._json(400, {"ok": False, "error": "no entiendo las opciones: " + str(exc)})
                    return
            try:
                r = base.traer_del_garmin(opciones)
            except Exception as exc:  # se le cuenta al portal, que lo enseña en el aviso
                print(f"  no se pudo traer del Garmin: {exc}", flush=True)
                self._json(500, {"ok": False, "error": str(exc)})
                return
            print(f"  Garmin: {r['traidos']} FIT traidos ({r['desde']} -> {r['hasta']}), "
                  f"{r['nuevos']} nuevos en la base", flush=True)
            self._json(200, {"ok": True, **r})

    return Handler


def servir(ruta_bd: str = db.RUTA_POR_DEFECTO, carpeta: str = ".", puerto: int = PUERTO_POR_DEFECTO,
           regenerar: bool = True, abrir: bool = False, host: str = HOST_POR_DEFECTO) -> int:
    """Levanta el servidor hasta Ctrl+C. `regenerar` rehace el cuadro de mando en cada parte que entra.

    `host` es `127.0.0.1` por defecto (el PC de casa). En Docker se pasa `0.0.0.0` y el puerto se publica
    solo en la loopback de la maquina, delante de Caddy y de su contrasenia.
    """
    base = _Base(ruta_bd, carpeta, regenerar)
    try:
        servidor = ThreadingHTTPServer((host, puerto), _handler(base))
    except OSError as exc:
        print(f"No he podido abrir {host}:{puerto}: {exc}")
        print("Puede que ya tengas otro servidor del entrenador abierto. Cierra esa ventana o usa --puerto 8182.")
        return 1
    servidor.daemon_threads = True
    direccion = f"http://{host}:{puerto}/"
    print("Cuadro de mando servido en " + direccion)
    print(f"  base: {ruta_bd}")
    if os.environ.get("ENTRENADOR_CLAVE", CLAVE_POR_DEFECTO):
        print(f"  pide usuario y contrasenia (usuario: "
              f"{os.environ.get('ENTRENADOR_USUARIO', USUARIO_POR_DEFECTO)})")
    print("  el boton \"Subir\" del portal mete el parte en la base mientras esta ventana siga abierta"
          + ("" if regenerar else " (sin rehacer el cuadro)"))
    print("  deja esta ventana abierta; Ctrl+C para parar.")
    if abrir:
        threading.Timer(0.6, lambda: webbrowser.open(direccion)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor parado.")
    finally:
        servidor.server_close()
    return 0
