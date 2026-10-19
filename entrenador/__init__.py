# -*- coding: utf-8 -*-
"""Entrenador: gestion de entrenamientos (proyecto personal).

Modulos:
- `db`: esquema y acceso a SQLite (`data/entrenador.db`).
- `lector_fit`: lectura pura de FIT del reloj Garmin (sin base de datos).
- `series`: reconstruccion de series y deteccion de material por palabra clave.
- `importar`: importacion incremental (carpeta / reloj por USB / export de Strava).
- `competicion`: marcas oficiales de la RFEN (tabla `competicion`, bajadas con `scripts/rfen_historial.py`).
- `cli`: interfaz de linea de ordenes.
"""

__version__ = "0.1.0"
