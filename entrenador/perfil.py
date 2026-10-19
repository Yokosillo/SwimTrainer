"""Quien firma el panel: los datos del atleta, **fuera del codigo**.

El repositorio se publica sin el nombre de nadie. Aqui viven los valores por defecto (vacios) y, si existe un
`perfil_local.py` al lado -que **no** se sube: esta en `.gitignore`-, manda ese. Asi el panel de casa sigue
diciendo el nombre completo y el club, y lo que se publica no dice ninguno de los dos.
"""

from __future__ import annotations

NOMBRE = ""      # el nombre largo (el titulo de la pagina)
CORTO = ""       # como se le llama en la cabecera
INICIALES = ""   # el sello de la esquina
CLUB = ""        # equipo y categoria, si se quiere decir

try:  # pragma: no cover - depende de la maquina, no del codigo
    from .perfil_local import CLUB as _CLUB, CORTO as _CORTO, INICIALES as _INI, NOMBRE as _NOMBRE

    NOMBRE = (_NOMBRE or "").strip()
    CORTO = (_CORTO or "").strip()
    INICIALES = (_INI or "").strip()
    CLUB = (_CLUB or "").strip()
except Exception:  # sin fichero local todo se queda vacio: eso, y no otra cosa, es lo que se publica
    pass


def titulo() -> str:
    """El titulo de la pagina: "Entrenamiento" y, si hay nombre configurado, detras."""
    return "Entrenamiento" + (f" \u00b7 {NOMBRE}" if NOMBRE else "")


def descripcion() -> str:
    """La descripcion del `<meta>`: con nombre o sin el."""
    return ("Panel local de entrenamiento de natacion, gimnasio y bici"
            + (f" de {NOMBRE}." if NOMBRE else "."))
