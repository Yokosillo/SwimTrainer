"""El sueno que mide el reloj (V1.2-07): la puerta automatica del descanso.

**Como se saca**: no esta en los `.fit` de natacion ni en el export de actividades, y el navegador no hace falta
(el portal no habla con Garmin). Esta en **Garmin Connect**, y el proyecto ya tenia la puerta abierta para las
actividades: `scripts/garmin_conectar.py` (`garminconnect` + el token OAuth del atleta en `~/.garminconnect`). Aqui
solo vive el almacen; quien llama a la nube es el script, no el motor (la app es local y no depende de internet).

```bash
.venv/Scripts/python.exe scripts/garmin_conectar.py sueno --desde 2026-09-20    # baja y guarda
.venv/Scripts/python.exe scripts/garmin_conectar.py traer --tipo swimming       # las actividades tambien traen su sueno
```

**Quien manda**: el apunte del atleta. Si ha escrito como ha dormido (`apunte`, `tipo = 'sueno'`), eso es la
verdad; lo del reloj es lo que hay cuando no apunta nada, y se dice de donde sale (`descanso.de` devuelve
`sueno_fuente`). La fecha es la del dia en que **termina** la noche: la del 18/10 es la noche del 17 al 18.
"""
from __future__ import annotations

import sqlite3

from . import db

CAMPOS = ("fecha", "horas", "puntuacion", "despierto_s", "profundo_s", "ligero_s", "rem_s",
          "despertares", "eficiencia", "fuente")


def de(cn: sqlite3.Connection, fecha: str) -> dict | None:
    """La noche que termina ese dia, o `None` si el reloj no la tiene."""
    fila = cn.execute("SELECT * FROM sueno WHERE fecha = ?", (fecha,)).fetchone()
    return dict(fila) if fila else None


def guardar(cn: sqlite3.Connection, noches: list[dict], fuente: str = "garmin_connect") -> dict:
    """Mete o actualiza las noches que vienen de la nube. Devuelve cuantas nuevas y cuantas actualizadas.

    Idempotente por fecha: volver a bajar el mismo rango no duplica nada, solo refresca (el reloj puede corregir
    una noche al dia siguiente).
    """
    nuevas = actualizadas = 0
    for n in noches:
        if not n.get("fecha"):
            continue
        fila = {c: n.get(c) for c in CAMPOS}
        fila["fuente"] = fuente
        fila["traido_en"] = db.ahora()
        estaba = cn.execute("SELECT 1 FROM sueno WHERE fecha = ?", (fila["fecha"],)).fetchone()
        columnas = ", ".join(CAMPOS) + ", fuente, traido_en"
        huecos = ", ".join("?" * (len(CAMPOS) + 2))
        cn.execute(f"INSERT OR REPLACE INTO sueno ({columnas}) VALUES ({huecos})",
                   [fila.get(c) for c in CAMPOS] + [fila["fuente"], fila["traido_en"]])
        nuevas += 0 if estaba else 1
        actualizadas += 1 if estaba else 0
    cn.commit()
    return {"noches": len(noches), "nuevas": nuevas, "actualizadas": actualizadas}


def noches_de(rango: tuple[str, str], limite: int | None = None, cliente=None) -> list[dict]:
    """Baja de Garmin Connect las noches del rango.

    Es la unica funcion que sale a internet y **no la llama el motor**: la llama `scripts/garmin_conectar.py`
    (el mismo camino que ya trae las actividades). Si no le prestan un cliente, se lo pide al script; el motor
    nunca la llama, asi que la libreria de Garmin no es dependencia de la app.
    """
    import importlib.util
    from datetime import date, timedelta
    from pathlib import Path

    if cliente is None:
        ruta = Path(__file__).resolve().parent.parent / "scripts" / "garmin_conectar.py"
        spec = importlib.util.spec_from_file_location("garmin_conectar_para_sueno", ruta)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)          # type: ignore[union-attr]
        cliente = modulo._sesion()

    desde, hasta = rango
    dia, fin = date.fromisoformat(desde), date.fromisoformat(hasta)
    salida: list[dict] = []
    while dia <= fin:
        if limite is not None and len(salida) >= limite:
            break
        n = _de_la_nube(cliente, dia.isoformat())
        if n:
            salida.append(n)
        dia += timedelta(days=1)
    return salida


def _de_la_nube(cliente, fecha: str) -> dict | None:
    """Una noche del reloj, en el formato del almacen. `None` si el reloj no la tiene."""
    try:
        datos = cliente.get_sleep_data(fecha) or {}
    except Exception:
        return None
    d = datos.get("dailySleepDTO") or {}
    segundos = d.get("sleepTimeSeconds")
    if not segundos:
        return None
    puntuacion = (d.get("sleepScores") or {}).get("overall") or {}
    return {
        "fecha": fecha,
        "horas": round(segundos / 3600.0, 2),
        "puntuacion": puntuacion.get("value"),
        "despierto_s": d.get("awakeSleepSeconds"),
        "profundo_s": d.get("deepSleepSeconds"),
        "ligero_s": d.get("lightSleepSeconds"),
        "rem_s": d.get("remSleepSeconds"),
        "despertares": None,
        "eficiencia": (d.get("sleepScores") or {}).get("sleepEfficiency") or None,
    }
