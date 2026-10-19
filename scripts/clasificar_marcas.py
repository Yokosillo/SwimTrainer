"""Audita la clasificacion de las marcas y compara lo guardado con el criterio de `entrenador/competicion.py`.

La logica NO vive aqui: vive en `competicion.py` (`clasificar_sesion`), que es la que usan el panel, las
consultas y las pruebas. Esto solo la enseña, dice que cambia respecto a lo que hay en la base y (con
--guardar) lo escribe.

El criterio, en una linea: una fila es SU MARCA o es un PASO de la prueba mas larga de la MISMA sesion (mismo
dia, misma hora cuando la federacion la sirve). Es la peticion literal del atleta: "junta las marcas de cada
dia y examina cuales pueden ser pases... si hay un 400 libres, duda del 50, del 100 y del 200".

Uso:  python scripts/clasificar_marcas.py [--bd ruta] [--guardar] [--dias]
"""
import argparse
import os
import sqlite3
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from entrenador import competicion  # noqa: E402


def _linea(f: dict) -> str:
    return (f"  {f['fecha']} {f['hora'] or '--:--':>5} {f['estilo']:9s} {f['distancia_m']:5d} m "
            f"pisc {f['piscina_m']:>2} {f['marca']:>12} {f['ritmo_100']:6.1f} s/100")


def _reparto(filas: list) -> str:
    cuenta: dict = {}
    for f in filas:
        cuenta[f["tipo"]] = cuenta.get(f["tipo"], 0) + 1
    return ", ".join(f"{k}: {v}" for k, v in sorted(cuenta.items()))


def main() -> None:
    ap = argparse.ArgumentParser(description="Audita (y opcionalmente guarda) la clasificacion de las marcas")
    ap.add_argument("--bd", default=os.path.join(RAIZ, "data", "entrenador.db"))
    ap.add_argument("--guardar", action="store_true",
                    help="escribe el tipo en la base (lo mismo que `entrenador competicion --clasificar`)")
    ap.add_argument("--dias", action="store_true", help="enseña las sesiones enteras, para poder revisarlas")
    a = ap.parse_args()

    cn = sqlite3.connect(a.bd)
    cn.row_factory = sqlite3.Row
    guardado = {r["id"]: r["tipo"] for r in cn.execute("SELECT id, tipo FROM competicion")}
    filas = competicion.clasificar(cn)

    print(f"Guardado en la base : {_reparto([{'tipo': t or 'prueba'} for t in guardado.values()])}")
    print(f"Criterio de ahora   : {_reparto(filas)}")

    cambios = [f for f in filas if (guardado.get(f["id"]) or "prueba") != f["tipo"]]
    print(f"\nCambian: {len(cambios)} filas")
    antes: dict = {}
    for f in cambios:
        k = f"{guardado.get(f['id']) or 'prueba'} -> {f['tipo']}"
        antes[k] = antes.get(k, 0) + 1
    for k, n in sorted(antes.items()):
        print(f"   {k}: {n}")

    print("\n=== QUE CAMBIA (las que dejan de contar como marca suya) ===")
    for f in sorted([x for x in cambios if (guardado.get(x["id"]) or "prueba") == "prueba" and x["tipo"] != "prueba"],
                    key=lambda x: (x["fecha"], x["estilo"], x["distancia_m"])):
        print(_linea(f))
        print(f"        antes: prueba  ->  ahora: {f['tipo']}  ({f['motivo']})")

    nuevas = [x for x in cambios if (guardado.get(x["id"]) or "prueba") != "prueba" and x["tipo"] == "prueba"]
    if nuevas:
        print("\n=== QUE VUELVEN A SER SU MARCA ===")
        for f in sorted(nuevas, key=lambda x: (x["fecha"], x["estilo"], x["distancia_m"])):
            print(_linea(f))
            print(f"        antes: {guardado.get(f['id'])}  ->  ahora: prueba  ({f['motivo']})")

    if a.dias:
        print("\n=== SESIONES DE PRUEBA LARGA (200 m o mas), enteras ===")
        largas = sorted({(f["fecha"], f["hora"], f["lugar"]) for f in filas
                         if f["tipo"] != "rara" and f["distancia_m"] >= 400})
        for fecha, hora, lugar in largas:
            grupo = [f for f in filas if f["fecha"] == fecha and f["hora"] == hora and f["lugar"] == lugar]
            print(f"\n== {fecha} {hora or '--:--'} {lugar}")
            for f in sorted(grupo, key=lambda x: -x["distancia_m"]):
                print(_linea(f) + f"   [{f['tipo']}]")

    if a.guardar:
        # Copia de seguridad antes de tocar nada: esto reescribe la clasificacion de las 579 filas.
        import datetime
        destino = os.path.join(RAIZ, "data", "backups")
        os.makedirs(destino, exist_ok=True)
        copia = os.path.join(destino, "entrenador_" + datetime.datetime.now().strftime("%Y%m%d-%H%M") + ".db")
        respaldo = sqlite3.connect(copia)
        cn.backup(respaldo)
        respaldo.close()
        print(f"\ncopia de seguridad: {copia}")
        print("guardado:", competicion.clasificar_y_guardar(cn))


if __name__ == "__main__":
    main()
