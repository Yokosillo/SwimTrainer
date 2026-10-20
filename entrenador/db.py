#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Esquema y acceso a la base de datos del Entrenador (SQLite).

Regla del proyecto: la base de datos vive en `data/entrenador.db` y **solo se escribe aqui**.
Los datos de origen (export de Strava, ficheros del reloj) nunca se modifican.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

RUTA_POR_DEFECTO = os.path.join("data", "entrenador.db")

ESQUEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Una fila por actividad. `id_garmin` es el numero del fichero FIT que genera el reloj;
-- `id_strava` es el numero que asigna Strava. Son distintos y se guardan los dos para poder
-- cruzar las dos vias de importacion sin duplicar sesiones.
CREATE TABLE IF NOT EXISTS actividad (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    id_garmin     TEXT,
    id_strava     TEXT,
    fichero       TEXT NOT NULL,
    hash          TEXT NOT NULL UNIQUE,
    fuente        TEXT NOT NULL,
    disciplina    TEXT,
    sub_disciplina TEXT,
    nombre        TEXT,
    inicio_utc    TEXT,
    inicio_local  TEXT,
    duracion_s    REAL,
    distancia_m   REAL,
    distancia_fit_m REAL,
    importado_en  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_act_garmin  ON actividad(id_garmin);
CREATE INDEX IF NOT EXISTS idx_act_strava  ON actividad(id_strava);
CREATE INDEX IF NOT EXISTS idx_act_inicio  ON actividad(inicio_local);

-- Detalle de natacion: una fila por sesion de piscina o aguas abiertas.
CREATE TABLE IF NOT EXISTS natacion_sesion (
    actividad_id      INTEGER PRIMARY KEY REFERENCES actividad(id) ON DELETE CASCADE,
    largo_piscina_m   REAL,
    n_largos          INTEGER,
    n_largos_activos  INTEGER,
    n_laps            INTEGER,
    brazadas          INTEGER,
    fc_media          REAL,
    fc_max            REAL,
    calorias          REAL,
    sensacion         INTEGER,   -- workout_feel de Garmin (0/25/50/75/100)
    rpe               INTEGER,   -- workout_rpe de Garmin (10-100)
    carga_aerobica    REAL,      -- total_training_effect
    swolf_medio       REAL       -- no hay dato del reloj: queda vacio a proposito
);

CREATE TABLE IF NOT EXISTS natacion_lap (
    actividad_id     INTEGER NOT NULL REFERENCES actividad(id) ON DELETE CASCADE,
    lap_idx          INTEGER NOT NULL,
    inicio           TEXT,
    dist_m           REAL,
    timer_s          REAL,
    elapsed_s        REAL,
    n_largos         INTEGER,
    n_largos_activos INTEGER,
    estilo           TEXT,
    fc_media         REAL,
    fc_max           REAL,
    brazadas         INTEGER,
    disparador       TEXT,     -- manual | distancia | tiempo | otro
    intensidad       TEXT,
    es_descanso      INTEGER,  -- 1 si dist_m <= 0
    material         TEXT DEFAULT 'sin_etiquetar',
    PRIMARY KEY (actividad_id, lap_idx)
);

CREATE TABLE IF NOT EXISTS natacion_largo (
    actividad_id INTEGER NOT NULL REFERENCES actividad(id) ON DELETE CASCADE,
    len_idx      INTEGER NOT NULL,
    inicio       TEXT,
    tipo         TEXT,         -- active | idle
    estilo       TEXT,
    timer_s      REAL,
    elapsed_s    REAL,
    brazadas         INTEGER,
    cadencia         INTEGER,
    vel_m_s          REAL,
    PRIMARY KEY (actividad_id, len_idx)
);

-- Etiquetas puestas por el atleta o deducidas del nombre de la actividad.
CREATE TABLE IF NOT EXISTS etiqueta (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    actividad_id INTEGER NOT NULL REFERENCES actividad(id) ON DELETE CASCADE,
    tipo         TEXT NOT NULL,   -- material | piscina | sensacion | otra
    valor        TEXT NOT NULL,
    origen       TEXT NOT NULL,   -- nombre_garmin | manual | automatico
    confianza    TEXT,            -- alta | media | baja
    UNIQUE(actividad_id, tipo, valor)
);

-- Series reconstruidas (mismo criterio que la auditoria, documentado en el README).
CREATE TABLE IF NOT EXISTS serie (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    actividad_id   INTEGER NOT NULL REFERENCES actividad(id) ON DELETE CASCADE,
    orden          INTEGER NOT NULL,
    rep_m          REAL NOT NULL,
    n_reps         INTEGER NOT NULL,
    n_reps_validas INTEGER,
    volumen_m      REAL,
    ritmo_medio_100 REAL,
    mejor_100      REAL,
    peor_100       REAL,
    sd_100         REAL,
    descanso_medio_s REAL,
    deriva_s       REAL,
    estilo         TEXT,
    material       TEXT DEFAULT 'sin_etiquetar',
    calidad        TEXT DEFAULT 'normal',
    comparable     INTEGER DEFAULT 0,
    UNIQUE(actividad_id, orden)
);

-- Traza GPS de una actividad (solo las que tienen coordenadas: bici, carrera, senderismo, caminata).
-- Los puntos van comprimidos en un BLOB (ver `lector_gpx.empaquetar`): una fila por actividad en vez de
-- decenas de miles, para que la base no se hinche.
CREATE TABLE IF NOT EXISTS ruta (
    actividad_id INTEGER PRIMARY KEY REFERENCES actividad(id) ON DELETE CASCADE,
    n_puntos     INTEGER NOT NULL,
    lat_min      REAL, lat_max REAL, lon_min REAL, lon_max REAL,
    ele_min      REAL, ele_max REAL,
    con_hora     INTEGER DEFAULT 0,
    dist_m       REAL,               -- distancia y desnivel medidos sobre la traza (se rellenan al analizar)
    desnivel_m   REAL,
    vel_media_kmh REAL,
    puntos       BLOB NOT NULL
);

-- Segmentos de bici tal y como los nombra el atleta (llegados del export de Strava: `segments.csv`).
CREATE TABLE IF NOT EXISTS segmento_bici (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre      TEXT NOT NULL UNIQUE,
    lat_ini     REAL NOT NULL, lon_ini REAL NOT NULL,
    lat_fin     REAL NOT NULL, lon_fin REAL NOT NULL,
    id_strava   TEXT,               -- actividad de ejemplo que da el export (no es el esfuerzo)
    dist_m      REAL,               -- se rellena al medir los esfuerzos (geometria real de la traza)
    desnivel_m  REAL,
    pendiente_pct REAL,
    n_esfuerzos INTEGER DEFAULT 0,
    dudoso      INTEGER DEFAULT 0     -- 1 = sus trazas lo cruzan por caminos distintos (aviso, no se oculta)
);

-- Una fila por vez que el atleta ha pasado por un segmento (el mejor intento de cada salida).
CREATE TABLE IF NOT EXISTS esfuerzo_bici (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    segmento_id  INTEGER NOT NULL REFERENCES segmento_bici(id) ON DELETE CASCADE,
    actividad_id INTEGER NOT NULL REFERENCES actividad(id) ON DELETE CASCADE,
    tiempo_s     REAL NOT NULL,
    dist_m       REAL,
    desnivel_m   REAL,
    pendiente_pct REAL,
    vel_media_kmh REAL,
    fecha        TEXT,
    UNIQUE(segmento_id, actividad_id)
);
CREATE INDEX IF NOT EXISTS idx_esf_seg ON esfuerzo_bici(segmento_id);

-- Segmentos descubiertos por el agente a partir de las trazas GPS propias (los GPX del reloj). Son los
-- tramos que el atleta repite sin que nadie se los haya definido antes.
CREATE TABLE IF NOT EXISTS segmento_minado (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre        TEXT NOT NULL,
    lat_ini       REAL NOT NULL, lon_ini REAL NOT NULL,
    lat_fin       REAL NOT NULL, lon_fin REAL NOT NULL,
    n_puntos      INTEGER NOT NULL,
    puntos        BLOB NOT NULL,    -- polilinea real del segmento (mismo formato que `ruta`)
    celdas        TEXT NOT NULL,    -- celdas de la rejilla de 15 m que hay que pisar (JSON)
    dist_m        REAL, desnivel_m REAL, pendiente_pct REAL,
    n_salidas     INTEGER DEFAULT 0,   -- salidas distintas en las que sale el tramo (al descubrirlo)
    n_intentos    INTEGER DEFAULT 0,   -- intentos medidos que pasan la prueba de cobertura
    votos         INTEGER DEFAULT 0,   -- parejas de salidas que lo han propuesto (confianza)
    primera       TEXT, ultima TEXT,
    km            REAL,                -- punto kilometrico del inicio dentro de la salida (orientativo)
    nombre_manual INTEGER DEFAULT 0,   -- 1 = el atleta lo ha renombrado; no se pisa
    oculto        INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_segmin_nombre ON segmento_minado(nombre);

-- Un intento del atleta en un segmento descubierto (el mejor de cada salida).
CREATE TABLE IF NOT EXISTS esfuerzo_minado (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    segmento_id   INTEGER NOT NULL REFERENCES segmento_minado(id) ON DELETE CASCADE,
    actividad_id  INTEGER NOT NULL REFERENCES actividad(id) ON DELETE CASCADE,
    tiempo_s      REAL NOT NULL,
    dist_m        REAL, desnivel_m REAL, pendiente_pct REAL, vel_media_kmh REAL,
    cobertura     REAL,             -- fraccion del segmento pisada (1.0 = entero)
    fecha         TEXT,
    UNIQUE(segmento_id, actividad_id)
);
CREATE INDEX IF NOT EXISTS idx_esfmin_seg ON esfuerzo_minado(segmento_id);

-- Poblaciones del entorno (una consulta a OpenStreetMap, para poner nombre a los segmentos sin conexion).
CREATE TABLE IF NOT EXISTS poblacion (
    nombre TEXT NOT NULL,
    tipo   TEXT,
    lat    REAL NOT NULL, lon REAL NOT NULL,
    PRIMARY KEY (nombre, lat, lon)
);

-- Marcas de competicion oficiales (RFEN). Una fila por marca, tal y como la publica la federacion.
-- No vienen del reloj: se bajan con `scripts/rfen_historial.py` y se cargan con `entrenador competicion`.
-- `clave` es la huella de la fila de origen: sirve para reimportar sin duplicar.
CREATE TABLE IF NOT EXISTS competicion (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fuente       TEXT NOT NULL DEFAULT 'RFEN',
    clave        TEXT NOT NULL UNIQUE,
    fecha        TEXT,                -- ISO (YYYY-MM-DD)
    hora         TEXT,                -- HH:MM:SS cuando la federacion la da
    lugar        TEXT,
    club         TEXT,
    estilo       TEXT,                -- libre | espalda | braza | mariposa | estilos
    distancia_m  INTEGER,
    piscina_m    INTEGER,             -- 25 | 50
    crono        TEXT,                -- electronico | manual
    parcial      TEXT,                -- si la fila es un parcial dentro de la prueba
    relevo       TEXT,
    marca        TEXT NOT NULL,       -- el texto original: 00:05:00.00
    segundos     REAL,
    ritmo_100    REAL,                -- segundos por 100 m
    valida       INTEGER DEFAULT 1,   -- 0 = la federacion la tiene corrupta (minutos > 59)
    tipo         TEXT,                -- prueba (marca suya) | pase (tramo de una prueba mayor del dia) | rara
    motivo       TEXT,                -- por que se clasifico asi (se calcula mirando el dia entero)
    importado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comp_fecha ON competicion(fecha);
CREATE INDEX IF NOT EXISTS idx_comp_prueba ON competicion(estilo, distancia_m, piscina_m);

-- Apuntes que llegan del formulario del cuadro de mando (cuadro/panel.html): lo que el reloj no registra
-- (ejercicios de gimnasio, pesos, como de duro fue, material). Se cargan con `entrenador apuntes --importar`.
-- `clave` es la huella del contenido: reimportar el mismo fichero no duplica nada.
CREATE TABLE IF NOT EXISTS apunte (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    clave        TEXT NOT NULL UNIQUE,
    fecha        TEXT,
    tipo         TEXT,                 -- natacion | gimnasio | bici | otro
    distancia_m  REAL,
    minutos      REAL,
    material     TEXT,
    sensacion    REAL,                 -- 1-10, como lo noto
    fc_media     REAL,
    piscina_m    REAL,
    notas        TEXT,
    fuente       TEXT NOT NULL DEFAULT 'portal',
    importado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_apunte_fecha ON apunte(fecha);
CREATE INDEX IF NOT EXISTS idx_apunte_tipo ON apunte(tipo, fecha);

-- Peticiones de gimnasio: las pide desde el cuadro de mando el boton "Solicitar trabajo de gimnasio"
-- (objetivo, minutos, material disponible, molestias y notas). Se cargan con `apuntes --importar`.
CREATE TABLE IF NOT EXISTS gimnasio_peticion (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    clave        TEXT NOT NULL UNIQUE,
    fecha        TEXT,                 -- para cuando la quiere (la elige el en el portal)
    pedida_en    TEXT,                 -- cuando la escribio
    objetivo     TEXT,
    minutos      REAL,
    donde        TEXT,
    material     TEXT,                 -- lo que tiene a mano, separado por comas
    molestias    TEXT,                 -- lo que le molesta o no quiere trabajar
    notas        TEXT,
    importado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_gimpet_fecha ON gimnasio_peticion(fecha);

-- Sesiones de gimnasio hechas y apuntadas en el portal (ejercicios, series, repeticiones y kilos).
CREATE TABLE IF NOT EXISTS gimnasio_sesion (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    clave        TEXT NOT NULL UNIQUE,
    fecha        TEXT,
    ejercicios   TEXT,                 -- JSON: [{ejercicio, series, reps, kg, rpe}]
    series       INTEGER,
    repeticiones INTEGER,
    volumen_kg   REAL,                 -- suma de series x repeticiones x kilos
    notas        TEXT,
    importado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_gimses_fecha ON gimnasio_sesion(fecha);

-- Sesiones que manda el programa (las escribe el agente a partir de lo que se ha pedido): el portal las
-- ensena como "lo que toca" para que se puedan seguir en el gimnasio sin mirar el movil.
CREATE TABLE IF NOT EXISTS gimnasio_prescrita (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    clave      TEXT NOT NULL UNIQUE,
    fecha      TEXT,
    titulo     TEXT,
    bloques    TEXT,                   -- JSON: [{ejercicio, series, reps, kg, nota}]
    notas      TEXT,
    escrita_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_gimpre_fecha ON gimnasio_prescrita(fecha);

-- El catalogo de ejercicios del gimnasio: la plantilla del atleta. `nombre` es el que sale en el portal y `como`
-- son sus palabras para reconocer la maquina. Lo que hizo cada dia va en `gimnasio_sesion.ejercicios`.
CREATE TABLE IF NOT EXISTS gimnasio_ejercicio (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre    TEXT NOT NULL UNIQUE,
    grupo     TEXT,                    -- core, pecho, hombro, biceps, triceps, gemelos, lumbares...
    como      TEXT,                    -- como es la maquina o el movimiento, con sus palabras
    orden     INTEGER DEFAULT 0,       -- el orden de una sesion suya
    activo    INTEGER DEFAULT 1,
    creado_en TEXT
);

-- El parte de una sesion de natacion: lo que el reloj no registra y el atleta rellena en el portal
-- (grupos, material e intensidad). Una fila por sesion; los grupos van en `parte_serie`. Es informacion
-- aparte de `natacion_lap`: el parte **manda** sobre el material y la intensidad, y el reloj no se toca.
CREATE TABLE IF NOT EXISTS parte (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    clave        TEXT NOT NULL UNIQUE,   -- huella del contenido: reimportar no duplica
    fecha        TEXT,
    actividad_id INTEGER REFERENCES actividad(id) ON DELETE CASCADE,
    piscina_m    REAL,
    metros       REAL,
    minutos      REAL,
    sensacion    REAL,
    notas        TEXT,
    compania     TEXT,                  -- solo | entrenador: de quien era la sesion
    fuente       TEXT NOT NULL DEFAULT 'portal',
    importado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_parte_fecha ON parte(fecha);

-- Un grupo del parte: o una serie (6x100) o un bloque continuo (1000 seguidos). `laps` guarda los indices de
-- los intervalos del reloj que forman el grupo, para poder volver a mirarlos y para saber que laps excluir.
CREATE TABLE IF NOT EXISTS parte_serie (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    parte_id     INTEGER NOT NULL REFERENCES parte(id) ON DELETE CASCADE,
    orden        INTEGER NOT NULL,
    tipo         TEXT,                  -- serie | continuo
    rep_m        REAL,
    n_reps       INTEGER,
    metros       REAL,
    tiempo_s     REAL,
    ritmo_100    REAL,
    descanso_s   REAL,
    cada_s       REAL,                  -- intervalo de salida: del inicio de una repeticion al de la siguiente
    estilo       TEXT,
    material     TEXT,                  -- lista separada por comas (palas,aletas,pull...)
    intensidad   TEXT,                  -- cal | ae1 | ae2 | ae3
    nota         TEXT,
    prueba       TEXT,                  -- prueba de medicion que le pone el atleta a este bloque (1500, 10x100...)
    laps         TEXT,                  -- JSON con los intervalos del reloj que forman el grupo
    UNIQUE(parte_id, orden)
);
CREATE INDEX IF NOT EXISTS idx_parteserie_parte ON parte_serie(parte_id);

-- Ajustes de plan que PROPONE la evaluacion a partir de lo que se ha hecho. No se aplican solos: quedan
-- propuestos y el atleta (o el agente, con su "si") los acepta. `que` lleva la semana propuesta en JSON.
CREATE TABLE IF NOT EXISTS plan_ajuste (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    clave        TEXT NOT NULL UNIQUE,
    semana       TEXT,
    propuesto_en TEXT,
    que          TEXT,
    motivo       TEXT,
    estado       TEXT DEFAULT 'propuesto'   -- propuesto | aceptado | descartado
);
CREATE INDEX IF NOT EXISTS idx_planajuste_semana ON plan_ajuste(semana);

CREATE TABLE IF NOT EXISTS importacion (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    momento     TEXT NOT NULL,
    fuente      TEXT NOT NULL,
    ruta        TEXT,
    leidos      INTEGER, nuevos INTEGER, actualizados INTEGER, omitidos INTEGER,
    incidencias INTEGER
);

-- Quien ha revisado cada seccion del anexo T (el saber de natacion) y cuando. Una seccion firmada por el
-- entrenador pesa mas que cualquier fuente: es el unico saber que no viene de un documento.
CREATE TABLE IF NOT EXISTS conocimiento_revision (
    seccion      TEXT PRIMARY KEY,   -- 'T.2'
    revisado_por TEXT,               -- 'entrenador' | 'medrano' | ...
    revisado_en  TEXT,               -- ISO
    notas        TEXT
);

-- Lo que el atleta corrige de un entrenamiento, con motivo y autor. El reloj no siempre acierta y el atleta tiene
-- la ultima palabra sobre lo suyo, pero su dato no se toca: la correccion va ENCIMA, se dice siempre y cualquiera
-- que mida un tramo puede preguntar cuanto se corrige dentro de el (V1.2-06).
CREATE TABLE IF NOT EXISTS correccion (
    id           INTEGER PRIMARY KEY,
    actividad_id INTEGER NOT NULL REFERENCES actividad(id) ON DELETE CASCADE,
    desde_m      REAL NOT NULL,      -- metros ACUMULADOS dentro de la sesion donde empieza lo corregido
    hasta_m      REAL NOT NULL,      -- y donde acaba (el 1.500 del 3.100 de hoy: 850 -> 2.350)
    segundos     REAL NOT NULL,      -- negativo resta (se paso de ritmo), positivo suma
    motivo       TEXT NOT NULL,      -- en palabras del atleta
    fuente       TEXT,               -- 'atleta' | ...
    creado_en    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_correccion_act ON correccion(actividad_id);

-- El sueno que el reloj de Garmin mide por la noche (V1.2-07). El apunte del atleta MANDA sobre esto (es su palabra),
-- pero esto es lo que hay cuando no apunta nada: es la unica puerta automatica del descanso. Una fila por noche, con
-- la fecha del dia en que TERMINA la noche (la del 18/10 es la noche del 17 al 18).
CREATE TABLE IF NOT EXISTS sueno (
    fecha         TEXT PRIMARY KEY,  -- '2026-10-18'
    horas         REAL,              -- horas dormidas
    puntuacion    INTEGER,           -- la del reloj, 0-100
    despierto_s   REAL,
    profundo_s    REAL,
    ligero_s      REAL,
    rem_s         REAL,
    despertares   INTEGER,
    eficiencia    REAL,              -- % de tiempo dormido sobre el tiempo en la cama
    fuente        TEXT,              -- 'garmin_connect'
    traido_en     TEXT               -- ISO
);

-- El bucle cerrado (S.6.4, V1.3): cada consejo con los numeros que lo sostienen, las reglas que lo aplican, lo que
-- decide el atleta y si la regla acerto. Sin esto, lo propuesto se pierde al cerrar la consola.
CREATE TABLE IF NOT EXISTS recomendacion (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha        TEXT,
    ambito       TEXT,               -- sesion | semana | bloque
    semana       TEXT,               -- S1, S2... cuando el ambito es la semana
    actividad_id INTEGER,
    titulo       TEXT NOT NULL,
    cuerpo       TEXT,
    origen       TEXT DEFAULT 'motor',   -- motor | atleta
    creada_en    TEXT
);
CREATE INDEX IF NOT EXISTS idx_rec_fecha ON recomendacion(fecha);

-- F5: las opciones que evaluó el motor v2. Se guardan todas, no solo la elegida; `descartada` y
-- `motivo_descarte` dejan visible por qué una opción no se podía usar.
CREATE TABLE IF NOT EXISTS recomendacion_opcion (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    recomendacion_id INTEGER NOT NULL REFERENCES recomendacion(id) ON DELETE CASCADE,
    opcion_id        TEXT NOT NULL,              -- A, B, C, D
    recomendada      INTEGER NOT NULL DEFAULT 0,
    sesion_json      TEXT NOT NULL,
    efecto_esperado  TEXT,
    confianza        REAL,
    riesgo           TEXT,
    coste            TEXT,
    porque           TEXT,
    score            REAL,
    descartada       INTEGER DEFAULT 0,
    motivo_descarte  TEXT,
    UNIQUE (recomendacion_id, opcion_id)
);
CREATE INDEX IF NOT EXISTS idx_recopc_rec ON recomendacion_opcion(recomendacion_id);

-- Los numeros que sostienen una recomendacion. `fuente` dice de donde salen (`tabla.campo` o `modulo.funcion`).
CREATE TABLE IF NOT EXISTS recomendacion_dato (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    recomendacion_id INTEGER NOT NULL REFERENCES recomendacion(id) ON DELETE CASCADE,
    fuente           TEXT,
    ref              TEXT,
    valor            TEXT,
    nota             TEXT
);
CREATE INDEX IF NOT EXISTS idx_recdato_rec ON recomendacion_dato(recomendacion_id);

-- Las reglas que la motivan, la limitan o avisan. El grado y la seccion del anexo T NO se copian aqui: se
-- resuelven al leer, con `conocimiento`, para que no se queden viejos cuando el anexo cambie.
CREATE TABLE IF NOT EXISTS recomendacion_regla (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    recomendacion_id INTEGER NOT NULL REFERENCES recomendacion(id) ON DELETE CASCADE,
    regla_id         TEXT,
    papel            TEXT,           -- motiva | limita | avisa
    UNIQUE (recomendacion_id, regla_id)
);

-- Que hizo el atleta: aceptada, cambiada (con su motivo) o ignorada. Una por recomendacion: la ultima manda.
CREATE TABLE IF NOT EXISTS decision (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    recomendacion_id INTEGER NOT NULL REFERENCES recomendacion(id) ON DELETE CASCADE,
    fecha            TEXT,
    tomada           TEXT,           -- aceptada | cambiada | ignorada
    respuesta        TEXT,
    motivo           TEXT,
    decidida_en      TEXT,
    UNIQUE (recomendacion_id)
);

-- Si la regla acerto: a favor, en contra o sin datos. `sin_datos` es una respuesta legitima y se dice: aqui no se
-- finge un veredicto cuando todavia no hay medida.
CREATE TABLE IF NOT EXISTS verificacion (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    recomendacion_id INTEGER NOT NULL REFERENCES recomendacion(id) ON DELETE CASCADE,
    regla_id         TEXT,
    fecha            TEXT,
    metrica          TEXT,
    antes            REAL,
    despues          REAL,
    veredicto        TEXT,           -- a_favor | en_contra | sin_datos
    notas            TEXT
);
CREATE INDEX IF NOT EXISTS idx_verif_regla ON verificacion(regla_id, fecha);

-- ---------------------------------------------------------------------------
-- Base de conocimiento estructurada (F2). Todo aditivo: no toca las tablas de arriba.
-- La fuente de verdad es `conocimiento/*.toml`; estas tablas son la copia consultable.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS conocimiento_version (
    id          TEXT PRIMARY KEY,   -- KV-xxxxxxxx
    creado_en   TEXT NOT NULL,
    hash        TEXT NOT NULL,
    ficheros    TEXT,               -- JSON: [{nombre, sha256}]
    notas       TEXT
);

-- F4: foto versionada del estado del atleta. `id` es el hash canonico de fecha + version + contenido;
-- `json` guarda la foto completa (metricas, n, dispersion, confianza, fuentes y limitaciones). No se
-- duplican las metricas en tablas auxiliares: el snapshot es la unidad que cita una recomendacion.
CREATE TABLE IF NOT EXISTS estado_atleta (
    id            TEXT PRIMARY KEY, -- EA-<16>
    fecha         TEXT NOT NULL,
    version_hash  TEXT,
    json          TEXT NOT NULL,
    creado_en     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_estado_fecha ON estado_atleta(fecha);

CREATE TABLE IF NOT EXISTS fuente (
    id            TEXT PRIMARY KEY, -- FU-001
    tipo          TEXT NOT NULL,
    titulo        TEXT,
    autores       TEXT,             -- JSON: ["..."]
    anio          INTEGER,
    url           TEXT,
    doi           TEXT,
    cita          TEXT,
    poblacion     TEXT,
    intervencion  TEXT,
    resultado     TEXT,
    limitaciones  TEXT,
    certeza       TEXT,
    revisado_por  TEXT,
    revisado_en   TEXT
);

CREATE TABLE IF NOT EXISTS afirmacion (
    id            TEXT PRIMARY KEY, -- AF-001
    texto         TEXT NOT NULL,
    condiciones   TEXT,
    efecto        TEXT,
    direccion     TEXT,             -- mejora | neutro | empeora | incierto
    tamano        TEXT,
    aplicabilidad TEXT,
    certeza       TEXT,
    estado        TEXT NOT NULL DEFAULT 'propuesta',
    procedencia   TEXT,             -- evidencia | historial | pactado | metodo | criterio_firmado
    firma_id      TEXT
);

CREATE TABLE IF NOT EXISTS afirmacion_fuente (
    afirmacion_id TEXT NOT NULL REFERENCES afirmacion(id) ON DELETE CASCADE,
    fuente_id     TEXT NOT NULL REFERENCES fuente(id) ON DELETE CASCADE,
    cita_local    TEXT,
    PRIMARY KEY (afirmacion_id, fuente_id)
);

CREATE TABLE IF NOT EXISTS parametro (
    id            TEXT PRIMARY KEY, -- PA-001
    nombre        TEXT NOT NULL,
    valor         TEXT NOT NULL,
    unidad        TEXT,
    procedencia   TEXT NOT NULL,    -- evidencia | criterio_firmado | historial | pactado
    fuente_id     TEXT REFERENCES fuente(id),
    afirmacion_id TEXT REFERENCES afirmacion(id),
    firmado_por   TEXT,
    firmado_en    TEXT,
    nota          TEXT
);

CREATE TABLE IF NOT EXISTS regla (
    id                 TEXT PRIMARY KEY, -- RG-002
    version            INTEGER NOT NULL DEFAULT 1,
    enunciado          TEXT NOT NULL,
    cuando_json        TEXT NOT NULL,
    entonces_json      TEXT NOT NULL,
    confianza          REAL,
    estado             TEXT NOT NULL DEFAULT 'revisada',
    revisar_en_dias    INTEGER,
    metrica_exito_json TEXT
);

CREATE TABLE IF NOT EXISTS regla_afirmacion (
    regla_id      TEXT NOT NULL REFERENCES regla(id) ON DELETE CASCADE,
    afirmacion_id TEXT NOT NULL REFERENCES afirmacion(id) ON DELETE CASCADE,
    papel         TEXT,             -- motiva | limita | avisa
    PRIMARY KEY (regla_id, afirmacion_id, papel)
);

CREATE TABLE IF NOT EXISTS regla_parametro (
    regla_id     TEXT NOT NULL REFERENCES regla(id) ON DELETE CASCADE,
    parametro_id TEXT NOT NULL REFERENCES parametro(id) ON DELETE CASCADE,
    PRIMARY KEY (regla_id, parametro_id)
);

CREATE TABLE IF NOT EXISTS estimulo (
    id             TEXT PRIMARY KEY, -- ES-001
    nombre         TEXT NOT NULL,
    entrena        TEXT,
    no_entrena     TEXT,
    recuperacion_h REAL,
    coste          TEXT,
    papel_400      TEXT,
    papel_3000     TEXT
);

CREATE TABLE IF NOT EXISTS receta (
    id         TEXT PRIMARY KEY,   -- RE-001
    nombre     TEXT NOT NULL,
    sesion     TEXT NOT NULL,
    metros     REAL,
    reps       INTEGER,
    dist_m     REAL,
    ritmo_rel  TEXT,
    descanso_s REAL,
    salida_s   REAL,
    desde_dia  TEXT,
    porque     TEXT,
    progresion TEXT,
    regresion  TEXT
);

CREATE TABLE IF NOT EXISTS receta_paso (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    receta_id  TEXT NOT NULL REFERENCES receta(id) ON DELETE CASCADE,
    orden      INTEGER NOT NULL,
    texto      TEXT NOT NULL,
    tipo       TEXT,                -- calentamiento | serie | suelta
    metros     REAL,
    ritmo_100  TEXT,
    descanso_s REAL,
    material   TEXT,
    intensidad TEXT,
    UNIQUE (receta_id, orden)
);
"""

# Columnas anadidas despues de la primera version del esquema. `conectar` las crea si faltan, para
# que una base de datos antigua siga funcionando sin tener que reimportar los ficheros del reloj.
MIGRACIONES = {
    "serie": {"n_reps_validas": "INTEGER", "calidad": "TEXT DEFAULT 'normal'"},
    "ruta": {"dist_m": "REAL", "desnivel_m": "REAL", "vel_media_kmh": "REAL"},
    "segmento_bici": {"n_esfuerzos": "INTEGER DEFAULT 0", "dist_m": "REAL", "desnivel_m": "REAL",
                      "pendiente_pct": "REAL", "id_strava": "TEXT", "dudoso": "INTEGER DEFAULT 0"},
    "competicion": {"tipo": "TEXT", "motivo": "TEXT"},
    # Repeticiones del grupo del parte con lo que puede cambiar de una a otra: intensidad, material y el SWOLF
    # medido. Los indices de lap y los numeros ya viven en `parte_serie`; aqui solo va lo que elige el atleta.
    "parte_serie": {"reps": "TEXT", "cada_s": "REAL", "prueba": "TEXT"},
    # De quien era la sesion: las de lunes, miercoles y viernes las manda el entrenador del equipo y no se
    # tocan; las demas son del atleta. Se guarda por parte para poder separar unas de otras al analizar.
    "parte": {"compania": "TEXT"},
    # La sesion del entrenador (V1.3-05): una linea por sesion en `apunte` con `quien` = 'entrenador'. Los
    # lunes, miercoles y viernes dejan de ser un hueco que el plan adivina: son carga de la semana como
    # cualquier otra.
    "apunte": {"quien": "TEXT DEFAULT 'atleta'"},
    # F3: la procedencia de la afirmacion (evidencia, historial, pactado, metodo o criterio).
    "afirmacion": {"procedencia": "TEXT"},
    # F5: versiones y decisión del motor v2. Aditivo: v1 sigue funcionando sin estas columnas.
    "recomendacion": {"knowledge_version": "TEXT", "estado_id": "TEXT", "prioridad": "INTEGER DEFAULT 3",
                      "elegida": "TEXT", "metrica_exito_json": "TEXT", "revisar_en": "TEXT",
                      "confianza": "REAL"},
    # F6 preparada: veredicto y aprendizaje; F5 no la rellena.
    "verificacion": {"resultado": "TEXT", "delta": "REAL", "confianza": "TEXT", "aprendizaje": "TEXT"},
}

# Indices sobre columnas que llegan por migracion (no existian en las bases viejas al crear la tabla): hay que
# crearlos DESPUES de migrar, o el ESQUEMA revienta sobre una base que todavia no tiene la columna.
INDICES_POST_MIGRACION = """
CREATE INDEX IF NOT EXISTS idx_comp_tipo ON competicion(tipo);
CREATE INDEX IF NOT EXISTS idx_apunte_quien ON apunte(quien, fecha);
"""


def _migrar(cn: sqlite3.Connection) -> None:
    """Anade las columnas que falten a las tablas ya existentes (ALTER TABLE ADD COLUMN)."""
    for tabla, columnas in MIGRACIONES.items():
        existentes = {f[1] for f in cn.execute(f"PRAGMA table_info({tabla})")}
        for nombre, tipo in columnas.items():
            if nombre not in existentes:
                cn.execute(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}")
    cn.commit()


def conectar(ruta: str = RUTA_POR_DEFECTO) -> sqlite3.Connection:
    """Abre (y crea si hace falta) la base de datos."""
    carpeta = os.path.dirname(os.path.abspath(ruta))
    os.makedirs(carpeta, exist_ok=True)
    cn = sqlite3.connect(ruta)
    cn.row_factory = sqlite3.Row
    cn.executescript(ESQUEMA)
    _migrar(cn)
    # Los indices de columnas que llegan por migracion se crean aqui: en el ESQUEMA fallarian sobre una base
    # vieja que todavia no tiene la columna (el CREATE TABLE IF NOT EXISTS no la añade).
    cn.executescript(INDICES_POST_MIGRACION)
    return cn


def ahora() -> str:
    """Marca temporal UTC en formato ISO (sin microsegundos)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
