"""Comprueba que el plan se recalcula cuando entra un entrenamiento nuevo (sobre una copia, no la base real).

Coge la copia de la base, le mete la sesion del domingo 18/10 (la del test de 1.500, que hoy todavia no ha
entrado) y compara lo que decia el plan antes y lo que dice despues.
"""
import json, shutil, subprocess, sys, os, tempfile
from datetime import date

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGEN = os.path.join(RAIZ, "data", "entrenador.db")
COPIA = os.path.join(tempfile.gettempdir(), "entrenador-simulacion-plan-vivo.db")
PY = os.path.join(RAIZ, ".venv", "Scripts", "python.exe")


def plan_de(ruta_bd: str, fecha: str) -> str:
    r = subprocess.run([PY, "-m", "entrenador.cli", "--bd", ruta_bd, "plan", "--recalculado", "--fecha", fecha],
                       cwd=RAIZ, capture_output=True, text=True)
    if r.returncode:
        return "FALLO: " + (r.stderr or "")[-400:]
    return r.stdout


shutil.copy2(ORIGEN, COPIA)
antes = plan_de(COPIA, "2026-10-18")

sys.path.insert(0, RAIZ)
from entrenador import db, partes                                   # noqa: E402

# La sesion del domingo 18/10: una actividad de natacion de verdad, con la fecha y los metros cambiados.
cn = db.conectar(COPIA)
cols = [c[1] for c in cn.execute("PRAGMA table_info(actividad)")]
fila = dict(zip(cols, cn.execute(
    "SELECT * FROM actividad WHERE distancia_m > 1000 ORDER BY inicio_local DESC LIMIT 1").fetchone()))
fila["id_garmin"] = 999999999
fila["inicio_local"] = "2026-10-18T09:30:00"
fila["distancia_m"] = 1925.0
fila["hash"] = "simulacion-plan-vivo-2026-10-18"     # es unico: hay que darle uno propio
usar = [c for c in cols if c != "id"]        # el id lo pone la base (autonumerico)
cn.execute("INSERT INTO actividad (%s) VALUES (%s)" % (",".join(usar), ",".join("?" * len(usar))),
           [fila[c] for c in usar])
nueva_id = cn.execute("SELECT id FROM actividad WHERE id_garmin = 999999999").fetchone()["id"]

# Y el parte de esa sesion, como lo manda el portal (se coge uno de verdad y se le cambia el dia).
parte = json.load(open(os.path.join(RAIZ, "data", "apuntes", "partes_del_navegador_2026-10-18.json"),
                       encoding="utf-8"))[0]
parte = dict(parte, fecha="2026-10-18", actividad_id=nueva_id)
r = partes.importar_datos(cn, [parte], origen="simulacion (comprobacion del plan vivo)")
cn.commit()
print("metido en la copia: actividad", nueva_id, "el 2026-10-18 con 1.925 m y su parte ->", r)
cn.close()

despues = plan_de(COPIA, "2026-10-18")


def linea(texto: str, semana: str) -> str:
    for l in texto.splitlines():
        if l.startswith(semana + " "):
            return l.strip()
    return "(no sale la semana " + semana + ")"


print()
for s in ("S1", "S2", "S3"):
    print("ANTES   " + linea(antes, s))
    print("DESPUES " + linea(despues, s))
    print()
cambio = linea(antes, "S2") != linea(despues, "S2")
print("EL PLAN CAMBIA AL ENTRAR EL ENTRENAMIENTO:", "si" if cambio else "NO")
sys.exit(0)
