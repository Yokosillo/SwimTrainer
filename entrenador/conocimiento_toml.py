#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""La base de conocimiento estructurada (TOML): cargar, validar, versionar y sincronizar.

F2 prepara la fuente de verdad nueva sin cambiar el motor: el anexo Markdown y las constantes de
`estimulos`/`reglas` siguen mandando (MOTOR_CONOCIMIENTO=v1). Aqui viven:

  1. `cargar(ruta)` - lee `conocimiento/*.toml` con `tomllib` y devuelve dataclasses inmutables.
     No escribe nada.
  2. `validar()` - devuelve `{ok, errores, avisos, version, hash, conteos}`. Falla cerrado si no
     hay conocimiento. Los avisos no invalidan (fuente huerfana, firma pendiente...).
  3. `sincronizar(cn)` - copia el TOML a las tablas SQLite aditivas con `INSERT ... ON CONFLICT`.
  4. `hash_canonico()` / `version` - `KV-<sha256(json canonico)[:16]>`; mismo contenido, mismo hash.
  5. `exportar_markdown()` y `comparar_markdown()` - salida a `data/derived/conocimiento/`, sin tocar
     `informes/`.

Nada de datos personales: el TOML es publico. Los datos del atleta viven en `plan_local.py` y en la
base privada.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

RUTA_CONOCIMIENTO = "conocimiento"
FICHEROS = (
    "fuentes.toml",
    "afirmaciones.toml",
    "parametros.toml",
    "reglas.toml",
    "estimulos.toml",
    "recetas.toml",
    "calendario.toml",
    "revisiones.toml",
)
RUTA_SALIDA = os.path.join("data", "derived", "conocimiento")
ID_RE = re.compile(r"^(FU|AF|RG|PA|ES|RE)-\d{3}$")
PROCEDENCIAS = ("evidencia", "criterio_firmado", "historial", "pactado")
DIRECCIONES = ("mejora", "neutro", "empeora", "incierto")
ESTADOS_AFIRMACION = ("propuesta", "revisada", "rechazada")


# --------------------------------------------------------------------------- dataclasses


def _s(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _lista(valor) -> tuple[str, ...]:
    if not valor:
        return ()
    return tuple(str(x).strip() for x in valor if str(x).strip())


def _num(valor) -> float | None:
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _congelar(valor):
    """Convierte dicts/listas anidadas en mapas y tuplas inmutables."""
    if isinstance(valor, Mapping):
        return MappingProxyType({str(k): _congelar(v) for k, v in valor.items()})
    if isinstance(valor, (list, tuple)):
        return tuple(_congelar(x) for x in valor)
    return valor


def _mapa(valor) -> Mapping:
    """Una tabla TOML inmutable; si el fichero trae otra cosa, se trata como vacia y el validador lo dice."""
    return _congelar(valor) if isinstance(valor, Mapping) else MappingProxyType({})


def _ent(valor) -> int | None:
    if valor is None or valor == "":
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Fuente:
    id: str
    tipo: str = ""
    titulo: str = ""
    autores: tuple[str, ...] = ()
    anio: int | None = None
    url: str = ""
    doi: str = ""
    cita: str = ""
    citas: tuple[str, ...] = ()
    poblacion: str = ""
    intervencion: str = ""
    resultado: str = ""
    limitaciones: str = ""
    certeza: str = ""
    revisado_por: str = ""
    revisado_en: str = ""
    legacy_id: str = ""
    notas: str = ""


@dataclass(frozen=True)
class ReferenciaFuente:
    id: str
    cita_local: str = ""


@dataclass(frozen=True)
class Afirmacion:
    id: str
    texto: str = ""
    condiciones: str = ""
    efecto: str = ""
    direccion: str = ""
    tamano: str = ""
    aplicabilidad: str = ""
    certeza: str = ""
    estado: str = "propuesta"
    criterio_firmado: bool = False
    firmado_por: str = ""
    firmado_en: str = ""
    fuentes: tuple[ReferenciaFuente, ...] = ()
    notas: str = ""


@dataclass(frozen=True)
class Parametro:
    id: str
    nombre: str = ""
    valor: object = None
    unidad: str = ""
    procedencia: str = ""
    fuente: str = ""
    afirmacion: str = ""
    firmado_por: str = ""
    firmado_en: str = ""
    nota: str = ""


@dataclass(frozen=True)
class Regla:
    id: str
    version: int = 1
    enunciado: str = ""
    cuando: dict = field(default_factory=dict)
    entonces: dict = field(default_factory=dict)
    evidencia: tuple[str, ...] = ()
    parametros: tuple[str, ...] = ()
    contraindicaciones: tuple[str, ...] = ()
    metrica_exito: dict = field(default_factory=dict)
    revisar_en_dias: int | None = None
    confianza: float | None = None
    estado: str = "revisada"
    estimulo: str = ""
    notas: str = ""


@dataclass(frozen=True)
class Estimulo:
    id: str
    nombre: str = ""
    entrena: str = ""
    no_entrena: str = ""
    recuperacion_h: float | None = None
    coste: str = ""
    papel_400: str = ""
    papel_3000: str = ""
    senal: str = ""
    afirmaciones: tuple[str, ...] = ()
    seccion_T: tuple[str, ...] = ()
    notas: str = ""


@dataclass(frozen=True)
class RecetaPaso:
    orden: int
    texto: str = ""
    tipo: str = ""
    metros: float | None = None
    ritmo_100: str = ""
    descanso_s: float | None = None
    material: str = ""
    intensidad: str = ""


@dataclass(frozen=True)
class Receta:
    id: str
    nombre: str = ""
    sesion: str = ""
    metros: float | None = None
    reps: int | None = None
    dist_m: float | None = None
    ritmo_rel: str = ""
    descanso_s: float | None = None
    salida_s: float | None = None
    desde_dia: str = ""
    porque: str = ""
    progresion: str = ""
    regresion: str = ""
    estimulo: str = ""
    afirmaciones: tuple[str, ...] = ()
    pasos: tuple[RecetaPaso, ...] = ()
    notas: str = ""


@dataclass(frozen=True)
class Calendario:
    dias_entrenador: tuple[str, ...] = ()
    dias_propios: tuple[str, ...] = ()
    dia_bici: str = ""
    dias_calidad: tuple[str, ...] = ()
    dias_largos: tuple[str, ...] = ()
    duro_h: float | None = None
    notas: str = ""


@dataclass(frozen=True)
class Conocimiento:
    fuentes: tuple[Fuente, ...] = ()
    afirmaciones: tuple[Afirmacion, ...] = ()
    parametros: tuple[Parametro, ...] = ()
    reglas: tuple[Regla, ...] = ()
    estimulos: tuple[Estimulo, ...] = ()
    recetas: tuple[Receta, ...] = ()
    calendario: Calendario = field(default_factory=Calendario)
    version: str = ""
    hash: str = ""
    ficheros: tuple[tuple[str, str], ...] = ()
    errores_carga: tuple[dict, ...] = ()

    def hay_conocimiento(self) -> bool:
        return bool(self.fuentes or self.afirmaciones or self.parametros or self.reglas
                    or self.estimulos or self.recetas or self.calendario.dias_entrenador
                    or self.calendario.dias_propios)


# --------------------------------------------------------------------------- carga


def _a_json(dato):
    """Convierte mapas inmutables y tuplas a algo que `json.dumps` serialice igual."""
    if isinstance(dato, Mapping):
        return {str(k): _a_json(v) for k, v in dato.items()}
    if isinstance(dato, (list, tuple)):
        return [_a_json(x) for x in dato]
    return dato


def _json_canonico(dato) -> str:
    return json.dumps(_a_json(dato), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _sha256_fichero(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _leer_toml(base: Path, nombre: str, errores: list[dict]) -> dict:
    ruta = base / nombre
    if not ruta.is_file():
        return {}
    try:
        with ruta.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        errores.append({"tipo": "toml_invalido", "fichero": nombre,
                        "detalle": f"{nombre}: sintaxis TOML rota: {exc}"})
    except (OSError, UnicodeDecodeError) as exc:
        errores.append({"tipo": "toml_ilegible", "fichero": nombre,
                        "detalle": f"{nombre}: no se puede leer: {exc}"})
    return {}


def _fuente(d: dict) -> Fuente:
    return Fuente(
        id=_s(d.get("id")), tipo=_s(d.get("tipo")), titulo=_s(d.get("titulo")),
        autores=_lista(d.get("autores")), anio=_ent(d.get("anio")), url=_s(d.get("url")),
        doi=_s(d.get("doi")), cita=_s(d.get("cita")), citas=_lista(d.get("citas")),
        poblacion=_s(d.get("poblacion")), intervencion=_s(d.get("intervencion")),
        resultado=_s(d.get("resultado")), limitaciones=_s(d.get("limitaciones")),
        certeza=_s(d.get("certeza")), revisado_por=_s(d.get("revisado_por")),
        revisado_en=_s(d.get("revisado_en")), legacy_id=_s(d.get("legacy_id")),
        notas=_s(d.get("notas")),
    )


def _afirmacion(d: dict) -> Afirmacion:
    refs = tuple(ReferenciaFuente(id=_s(x.get("id")), cita_local=_s(x.get("cita_local")))
                 for x in (d.get("fuentes") or []) if isinstance(x, dict) and _s(x.get("id")))
    return Afirmacion(
        id=_s(d.get("id")), texto=_s(d.get("texto")), condiciones=_s(d.get("condiciones")),
        efecto=_s(d.get("efecto")), direccion=_s(d.get("direccion")), tamano=_s(d.get("tamano")),
        aplicabilidad=_s(d.get("aplicabilidad")), certeza=_s(d.get("certeza")),
        estado=_s(d.get("estado")) or "propuesta", criterio_firmado=bool(d.get("criterio_firmado")),
        firmado_por=_s(d.get("firmado_por")), firmado_en=_s(d.get("firmado_en")),
        fuentes=refs, notas=_s(d.get("notas")),
    )


def _parametro(d: dict) -> Parametro:
    return Parametro(
        id=_s(d.get("id")), nombre=_s(d.get("nombre")), valor=d.get("valor"),
        unidad=_s(d.get("unidad")), procedencia=_s(d.get("procedencia")),
        fuente=_s(d.get("fuente")), afirmacion=_s(d.get("afirmacion")),
        firmado_por=_s(d.get("firmado_por")), firmado_en=_s(d.get("firmado_en")),
        nota=_s(d.get("nota")),
    )


def _regla(d: dict) -> Regla:
    return Regla(
        id=_s(d.get("id")), version=_ent(d.get("version")) or 1, enunciado=_s(d.get("enunciado")),
        cuando=_mapa(d.get("cuando")), entonces=_mapa(d.get("entonces")),
        evidencia=_lista(d.get("evidencia")), parametros=_lista(d.get("parametros")),
        contraindicaciones=_lista(d.get("contraindicaciones")),
        metrica_exito=_mapa(d.get("metrica_exito")),
        revisar_en_dias=_ent(d.get("revisar_en_dias")), confianza=_num(d.get("confianza")),
        estado=_s(d.get("estado")) or "revisada", estimulo=_s(d.get("estimulo")),
        notas=_s(d.get("notas")),
    )


def _estimulo(d: dict) -> Estimulo:
    return Estimulo(
        id=_s(d.get("id")), nombre=_s(d.get("nombre")), entrena=_s(d.get("entrena")),
        no_entrena=_s(d.get("no_entrena")), recuperacion_h=_num(d.get("recuperacion_h")),
        coste=_s(d.get("coste")), papel_400=_s(d.get("papel_400")), papel_3000=_s(d.get("papel_3000")),
        senal=_s(d.get("senal")), afirmaciones=_lista(d.get("afirmaciones")),
        seccion_T=_lista(d.get("seccion_T")), notas=_s(d.get("notas")),
    )


def _paso(d: dict, defecto: int) -> RecetaPaso:
    return RecetaPaso(
        orden=_ent(d.get("orden")) or defecto, texto=_s(d.get("texto")), tipo=_s(d.get("tipo")),
        metros=_num(d.get("metros")), ritmo_100=_s(d.get("ritmo_100")),
        descanso_s=_num(d.get("descanso_s")), material=_s(d.get("material")),
        intensidad=_s(d.get("intensidad")),
    )


def _receta(d: dict) -> Receta:
    pasos = tuple(_paso(x, i) for i, x in enumerate(d.get("pasos") or [], 1) if isinstance(x, dict))
    return Receta(
        id=_s(d.get("id")), nombre=_s(d.get("nombre")), sesion=_s(d.get("sesion")),
        metros=_num(d.get("metros")), reps=_ent(d.get("reps")), dist_m=_num(d.get("dist_m")),
        ritmo_rel=_s(d.get("ritmo_rel")), descanso_s=_num(d.get("descanso_s")),
        salida_s=_num(d.get("salida_s")), desde_dia=_s(d.get("desde_dia")), porque=_s(d.get("porque")),
        progresion=_s(d.get("progresion")), regresion=_s(d.get("regresion")),
        estimulo=_s(d.get("estimulo")), afirmaciones=_lista(d.get("afirmaciones")),
        pasos=pasos, notas=_s(d.get("notas")),
    )


def _calendario(d: dict) -> Calendario:
    d = _mapa(d)
    return Calendario(
        dias_entrenador=_lista(d.get("dias_entrenador")), dias_propios=_lista(d.get("dias_propios")),
        dia_bici=_s(d.get("dia_bici")), dias_calidad=_lista(d.get("dias_calidad")),
        dias_largos=_lista(d.get("dias_largos")), duro_h=_num(d.get("duro_h")), notas=_s(d.get("notas")),
    )


def cargar(ruta: str = RUTA_CONOCIMIENTO) -> Conocimiento:
    """Lee `conocimiento/*.toml` y devuelve el conocimiento como dataclasses inmutables.

    No escribe nada y no toca la base de datos. Si la carpeta no existe o esta vacia, devuelve un
    `Conocimiento` vacio con `version=""`; el validador lo rechaza (`sin_conocimiento`).
    """
    base = Path(ruta)
    errores_carga: list[dict] = []
    crudos: dict[str, dict] = {nombre: _leer_toml(base, nombre, errores_carga) for nombre in FICHEROS}
    canonico = _json_canonico(crudos)
    hash_ = _sha256_texto(canonico)
    hay = any(bool(v) for v in crudos.values()) and not errores_carga
    ficheros = tuple(sorted((nombre, _sha256_fichero(base / nombre))
                            for nombre in FICHEROS if (base / nombre).is_file()))
    return Conocimiento(
        fuentes=tuple(_fuente(x) for x in (crudos.get("fuentes.toml", {}).get("fuente") or [])
                      if isinstance(x, dict)),
        afirmaciones=tuple(_afirmacion(x) for x in (crudos.get("afirmaciones.toml", {}).get("afirmacion") or [])
                           if isinstance(x, dict)),
        parametros=tuple(_parametro(x) for x in (crudos.get("parametros.toml", {}).get("parametro") or [])
                         if isinstance(x, dict)),
        reglas=tuple(_regla(x) for x in (crudos.get("reglas.toml", {}).get("regla") or [])
                     if isinstance(x, dict)),
        estimulos=tuple(_estimulo(x) for x in (crudos.get("estimulos.toml", {}).get("estimulo") or [])
                        if isinstance(x, dict)),
        recetas=tuple(_receta(x) for x in (crudos.get("recetas.toml", {}).get("receta") or [])
                      if isinstance(x, dict)),
        calendario=_calendario(crudos.get("calendario.toml", {}).get("calendario") or {}),
        version=(f"KV-{hash_[:16]}" if hay else ""),
        hash=(hash_ if hay else ""),
        ficheros=ficheros,
        errores_carga=tuple(errores_carga),
    )


def version(ruta: str = RUTA_CONOCIMIENTO) -> str:
    return cargar(ruta).version


def estructura(c: Conocimiento | None = None, ruta: str = RUTA_CONOCIMIENTO) -> dict:
    """Resumen legible/JSON de lo que hay cargado."""
    c = c or cargar(ruta)
    return {
        "version": c.version,
        "hash": c.hash,
        "ficheros": [{"nombre": n, "sha256": h} for n, h in c.ficheros],
        "conteos": _conteos(c),
        "errores_carga": list(c.errores_carga),
    }


def _conteos(c: Conocimiento) -> dict:
    return {
        "fuentes": len(c.fuentes),
        "afirmaciones": len(c.afirmaciones),
        "parametros": len(c.parametros),
        "reglas": len(c.reglas),
        "estimulos": len(c.estimulos),
        "recetas": len(c.recetas),
        "pasos": sum(len(r.pasos) for r in c.recetas),
        "calendario": bool(c.calendario.dias_entrenador or c.calendario.dias_propios),
    }


# --------------------------------------------------------------------------- validacion


def _duplicados(ids: list[str], tipo: str) -> list[dict]:
    vistos: set[str] = set()
    fuera: list[dict] = []
    for x in ids:
        if x in vistos:
            fuera.append({"tipo": f"{tipo}_duplicado", "detalle": f"{x} aparece mas de una vez", "id": x})
        vistos.add(x)
    return fuera


def _error(errores: list, tipo: str, detalle: str, **extra) -> None:
    errores.append({"tipo": tipo, "detalle": detalle, **extra})


def _aviso(avisos: list, tipo: str, detalle: str, **extra) -> None:
    avisos.append({"tipo": tipo, "detalle": detalle, **extra})


def _requerido(errores: list, entidad: str, id_: str, campo: str, valor) -> None:
    """Error estructurado para un campo obligatorio vacio."""
    if not _s(valor):
        _error(errores, "campo_obligatorio", f"{entidad} {id_}: falta `{campo}`",
               id=id_, campo=campo, entidad=entidad)


def _normaliza(texto: str) -> str:
    return re.sub(r"\s+", " ", _s(texto).strip().strip('"').strip("'")).strip().lower()


def _cita_en_fuente(cita_local: str, fuente: Fuente) -> bool:
    """La cita local tiene que estar literalmente en alguna cita de la fuente (sin espacios de mas)."""
    buscada = _normaliza(cita_local)
    if not buscada:
        return False
    citas = list(fuente.citas) or []
    if fuente.cita:
        citas.append(fuente.cita)
    return any(buscada in _normaliza(c) for c in citas)


def validar(c: Conocimiento | None = None, ruta: str = RUTA_CONOCIMIENTO) -> dict:
    """Valida el TOML. Devuelve `{ok, errores, avisos, version, hash, conteos}`.

    Falla cerrado: sin conocimiento, `ok=False` (`sin_conocimiento`). Los errores invalidan; los
    avisos (fuente huerfana, firma pendiente, afirmacion propuesta) no.
    """
    c = c or cargar(ruta)
    errores: list[dict] = []
    avisos: list[dict] = []
    errores.extend(c.errores_carga)
    if not c.hay_conocimiento():
        _error(errores, "sin_conocimiento", f"no hay conocimiento en {ruta} (faltan los TOML o estan vacios)")
        return {"ok": False, "errores": errores, "avisos": avisos, "version": "", "hash": "",
                "conteos": _conteos(c)}

    fuentes = {f.id: f for f in c.fuentes}
    afirmaciones = {a.id: a for a in c.afirmaciones}
    parametros = {p.id: p for p in c.parametros}
    reglas = {r.id: r for r in c.reglas}
    estimulos = {e.id: e for e in c.estimulos}
    recetas = {r.id: r for r in c.recetas}

    # IDs: formato y duplicados.
    for tipo, entidades in (("fuente", c.fuentes), ("afirmacion", c.afirmaciones),
                            ("parametro", c.parametros), ("regla", c.reglas),
                            ("estimulo", c.estimulos), ("receta", c.recetas)):
        ids = [x.id for x in entidades]
        for x in ids:
            if not ID_RE.match(x):
                _error(errores, "id_mal_formado", f"{x!r} no cumple el formato {tipo.upper()}###", id=x)
        errores.extend(_duplicados(ids, tipo))

    # Fuentes: duplicado del numero antiguo y fuente huerfana.
    legados = [f.legacy_id for f in c.fuentes if f.legacy_id]
    for d in _duplicados(legados, "fuente_legacy"):
        _error(errores, "fuente_duplicada",
               f"el numero antiguo [{d['id']}] esta en dos fuentes", legacy_id=d["id"])

    citadas: set[str] = set()

    # Afirmaciones.
    for a in c.afirmaciones:
        if not a.texto:
            _error(errores, "afirmacion_vacia", f"{a.id} no tiene texto", id=a.id)
        if not a.fuentes and not a.criterio_firmado:
            _error(errores, "afirmacion_sin_fuente",
                   f"{a.id} no tiene fuente ni criterio firmado", id=a.id)
        if a.direccion and a.direccion not in DIRECCIONES:
            _error(errores, "afirmacion_direccion", f"{a.id} tiene direccion {a.direccion!r}", id=a.id)
        if a.estado not in ESTADOS_AFIRMACION:
            _error(errores, "afirmacion_estado", f"{a.id} tiene estado {a.estado!r}", id=a.id)
        if a.estado == "propuesta":
            _aviso(avisos, "afirmacion_propuesta",
                   f"{a.id} esta propuesta: aun no puede motivar una recomendacion", id=a.id)
        for ref in a.fuentes:
            citadas.add(ref.id)
            if ref.id not in fuentes:
                _error(errores, "fuente_inexistente",
                       f"{a.id} cita {ref.id}, que no existe", id=a.id, fuente=ref.id)
            elif not ref.cita_local:
                _error(errores, "cita_local_vacia",
                       f"{a.id} cita {ref.id} sin cita local", id=a.id, fuente=ref.id)
            elif not _cita_en_fuente(ref.cita_local, fuentes[ref.id]):
                _error(errores, "cita_local_inexistente",
                       f"{a.id}: la cita_local no aparece en {ref.id}", id=a.id, fuente=ref.id)
        if a.criterio_firmado and not a.firmado_por:
            _aviso(avisos, "firma_pendiente", f"{a.id} es criterio firmado pero no tiene firma", id=a.id)

    # Parametros.
    for p in c.parametros:
        if not p.nombre:
            _error(errores, "parametro_sin_nombre", f"{p.id} no tiene nombre", id=p.id)
        _requerido(errores, "parametro", p.id, "valor", p.valor)
        if p.procedencia not in PROCEDENCIAS:
            _error(errores, "parametro_sin_procedencia",
                   f"{p.id} tiene procedencia {p.procedencia!r}; validas: {', '.join(PROCEDENCIAS)}", id=p.id)
        if p.procedencia == "criterio_firmado" and not p.firmado_por:
            _aviso(avisos, "firma_pendiente",
                   f"{p.id} es criterio firmado y la firma esta pendiente (F3-07)", id=p.id)
        if p.fuente:
            citadas.add(p.fuente)
            if p.fuente not in fuentes:
                _error(errores, "fuente_inexistente", f"{p.id} apunta a {p.fuente}", id=p.id, fuente=p.fuente)
        if p.afirmacion and p.afirmacion not in afirmaciones:
            _error(errores, "afirmacion_inexistente",
                   f"{p.id} apunta a {p.afirmacion}", id=p.id, afirmacion=p.afirmacion)

    # Reglas.
    for r in c.reglas:
        if not r.enunciado:
            _error(errores, "regla_sin_enunciado", f"{r.id} no tiene enunciado", id=r.id)
        if not r.cuando:
            _error(errores, "regla_sin_condicion", f"{r.id} no tiene `cuando`", id=r.id)
        if not r.entonces:
            _error(errores, "regla_sin_accion", f"{r.id} no tiene `entonces`", id=r.id)
        if not r.metrica_exito.get("tipo") or not r.metrica_exito.get("criterio"):
            _error(errores, "regla_sin_metrica",
                   f"{r.id} no tiene metrica_exito con tipo y criterio", id=r.id)
        for af in r.evidencia:
            if af not in afirmaciones:
                _error(errores, "regla_afirmacion_inexistente",
                       f"{r.id} cita {af}, que no existe", id=r.id, afirmacion=af)
        for pa in r.parametros:
            if pa not in parametros:
                _error(errores, "regla_parametro_inexistente",
                       f"{r.id} usa {pa}, que no existe", id=r.id, parametro=pa)
        receta = _s(r.entonces.get("receta"))
        if receta and receta not in recetas:
            _error(errores, "receta_inexistente", f"{r.id} manda a {receta}", id=r.id, receta=receta)
        estimulo = _s(r.entonces.get("estimulo")) or r.estimulo
        if estimulo and estimulo not in estimulos:
            _error(errores, "estimulo_inexistente", f"{r.id} usa {estimulo}", id=r.id, estimulo=estimulo)
        if not r.contraindicaciones:
            _aviso(avisos, "regla_sin_contraindicaciones", f"{r.id} no declara contraindicaciones", id=r.id)

    # Estimulos.
    for e in c.estimulos:
        if not e.nombre:
            _error(errores, "estimulo_sin_nombre", f"{e.id} no tiene nombre", id=e.id)
        _requerido(errores, "estimulo", e.id, "entrena", e.entrena)
        for af in e.afirmaciones:
            if af not in afirmaciones:
                _error(errores, "afirmacion_inexistente", f"{e.id} cita {af}", id=e.id, afirmacion=af)
        if e.recuperacion_h is None:
            _aviso(avisos, "estimulo_sin_recuperacion", f"{e.id} no declara recuperacion_h", id=e.id)

    # Recetas.
    for r in c.recetas:
        if not r.nombre or not r.sesion or not r.pasos:
            _error(errores, "receta_incompleta",
                   f"{r.id} necesita nombre, sesion y al menos un paso", id=r.id)
        for i, paso in enumerate(r.pasos, 1):
            if not paso.orden or not paso.texto:
                _error(errores, "receta_paso_incompleto",
                       f"{r.id} paso {i} sin orden o sin texto", id=r.id)
        if r.estimulo and r.estimulo not in estimulos:
            _error(errores, "estimulo_inexistente", f"{r.id} usa {r.estimulo}", id=r.id, estimulo=r.estimulo)
        for af in r.afirmaciones:
            if af not in afirmaciones:
                _error(errores, "afirmacion_inexistente", f"{r.id} cita {af}", id=r.id, afirmacion=af)

    # Fuentes huerfanas: definidas y no citadas por afirmaciones ni parametros.
    for f in c.fuentes:
        for campo in ("tipo", "titulo", "url"):
            _requerido(errores, "fuente", f.id, campo, getattr(f, campo))
        if not f.cita and not f.citas:
            _requerido(errores, "fuente", f.id, "cita", "")
        if f.id not in citadas:
            _aviso(avisos, "fuente_huerfana",
                   f"{f.id} esta definida y no se cita en el piloto", fuente=f.id)

    if not c.calendario.dias_entrenador and not c.calendario.dias_propios:
        _aviso(avisos, "calendario_vacio", "calendario.toml no declara dias del entrenador ni propios")

    return {
        "ok": not errores,
        "errores": errores,
        "avisos": avisos,
        "version": c.version,
        "hash": c.hash,
        "conteos": _conteos(c),
    }


# --------------------------------------------------------------------------- SQLite


def _upsert_entidad(cn: sqlite3.Connection, tabla: str, fila: dict, clave: str = "id") -> None:
    columnas = ", ".join(fila)
    marcas = ", ".join("?" for _ in fila)
    updates = ", ".join(f"{c} = excluded.{c}" for c in fila if c != clave)
    sql = f"INSERT INTO {tabla} ({columnas}) VALUES ({marcas}) ON CONFLICT({clave}) DO UPDATE SET {updates}"
    cn.execute(sql, tuple(fila.values()))


def sincronizar(cn: sqlite3.Connection, c: Conocimiento | None = None,
                ruta: str = RUTA_CONOCIMIENTO) -> dict:
    """Copia el TOML validado a las tablas aditivas. Idempotente: mismo TOML, mismas filas.

    No borra tablas ni filas de otros origenes. Si el TOML no valida, no escribe nada.
    """
    from . import db

    c = c or cargar(ruta)
    v = validar(c)
    if not v["ok"]:
        raise ValueError("el conocimiento no valida: " + "; ".join(e["detalle"] for e in v["errores"]))
    try:
        cn.execute(
            """INSERT INTO conocimiento_version (id, creado_en, hash, ficheros, notas)
               VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING""",
            (c.version, db.ahora(), c.hash,
             json.dumps([{"nombre": n, "sha256": h} for n, h in c.ficheros], ensure_ascii=False), ""))
        for f in c.fuentes:
            _upsert_entidad(cn, "fuente", {
                "id": f.id, "tipo": f.tipo, "titulo": f.titulo, "autores": json.dumps(list(f.autores), ensure_ascii=False),
                "anio": f.anio, "url": f.url, "doi": f.doi, "cita": f.cita, "poblacion": f.poblacion,
                "intervencion": f.intervencion, "resultado": f.resultado, "limitaciones": f.limitaciones,
                "certeza": f.certeza, "revisado_por": f.revisado_por, "revisado_en": f.revisado_en})
        for a in c.afirmaciones:
            _upsert_entidad(cn, "afirmacion", {
                "id": a.id, "texto": a.texto, "condiciones": a.condiciones, "efecto": a.efecto,
                "direccion": a.direccion, "tamano": a.tamano, "aplicabilidad": a.aplicabilidad,
                "certeza": a.certeza, "estado": a.estado, "firma_id": a.firmado_por})
            for ref in a.fuentes:
                cn.execute(
                    """INSERT INTO afirmacion_fuente (afirmacion_id, fuente_id, cita_local)
                       VALUES (?, ?, ?) ON CONFLICT(afirmacion_id, fuente_id)
                       DO UPDATE SET cita_local = excluded.cita_local""",
                    (a.id, ref.id, ref.cita_local))
        for p in c.parametros:
            _upsert_entidad(cn, "parametro", {
                "id": p.id, "nombre": p.nombre, "valor": str(p.valor), "unidad": p.unidad,
                "procedencia": p.procedencia, "fuente_id": p.fuente or None,
                "afirmacion_id": p.afirmacion or None, "firmado_por": p.firmado_por,
                "firmado_en": p.firmado_en, "nota": p.nota})
        for r in c.reglas:
            _upsert_entidad(cn, "regla", {
                "id": r.id, "version": r.version, "enunciado": r.enunciado,
                "cuando_json": _json_canonico(r.cuando), "entonces_json": _json_canonico(r.entonces),
                "confianza": r.confianza, "estado": r.estado, "revisar_en_dias": r.revisar_en_dias,
                "metrica_exito_json": _json_canonico(r.metrica_exito)})
            for af in r.evidencia:
                cn.execute(
                    """INSERT INTO regla_afirmacion (regla_id, afirmacion_id, papel)
                       VALUES (?, ?, 'motiva') ON CONFLICT(regla_id, afirmacion_id, papel) DO NOTHING""",
                    (r.id, af))
            for pa in r.parametros:
                cn.execute(
                    """INSERT INTO regla_parametro (regla_id, parametro_id) VALUES (?, ?)
                       ON CONFLICT(regla_id, parametro_id) DO NOTHING""", (r.id, pa))
        for e in c.estimulos:
            _upsert_entidad(cn, "estimulo", {
                "id": e.id, "nombre": e.nombre, "entrena": e.entrena, "no_entrena": e.no_entrena,
                "recuperacion_h": e.recuperacion_h, "coste": e.coste, "papel_400": e.papel_400,
                "papel_3000": e.papel_3000})
        for r in c.recetas:
            _upsert_entidad(cn, "receta", {
                "id": r.id, "nombre": r.nombre, "sesion": r.sesion, "metros": r.metros,
                "reps": r.reps, "dist_m": r.dist_m, "ritmo_rel": r.ritmo_rel,
                "descanso_s": r.descanso_s, "salida_s": r.salida_s, "desde_dia": r.desde_dia,
                "porque": r.porque, "progresion": r.progresion, "regresion": r.regresion})
            for paso in r.pasos:
                cn.execute(
                    """INSERT INTO receta_paso (receta_id, orden, texto, tipo, metros, ritmo_100,
                                                descanso_s, material, intensidad)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(receta_id, orden) DO UPDATE SET
                           texto = excluded.texto, tipo = excluded.tipo, metros = excluded.metros,
                           ritmo_100 = excluded.ritmo_100, descanso_s = excluded.descanso_s,
                           material = excluded.material, intensidad = excluded.intensidad""",
                    (r.id, paso.orden, paso.texto, paso.tipo, paso.metros, paso.ritmo_100,
                     paso.descanso_s, paso.material, paso.intensidad))
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    return {"ok": True, "version": c.version, "hash": c.hash, "conteos": _conteos(c)}


# --------------------------------------------------------------------------- Markdown


def _md_fuente(f: Fuente) -> list[str]:
    lineas = [f"### {f.id} - {f.titulo or '(sin titulo)'}",
              f"- Tipo: {f.tipo or '-'}",
              f"- URL: {f.url or '-'}"]
    if f.legacy_id:
        lineas.append(f"- Numero antiguo: [{f.legacy_id}]")
    for cita in (f.citas or ((f.cita,) if f.cita else ())):
        lineas.append(f"- Cita: {cita}")
    if f.notas:
        lineas.append(f"- Notas: {f.notas}")
    return lineas


def _markdown(c: Conocimiento) -> str:
    lineas = ["# Base de conocimiento generada (F2)", "",
              f"- **Version:** {c.version or '(sin conocimiento)'}",
              f"- **Hash:** {c.hash or '-'}",
              f"- **Fuentes:** {len(c.fuentes)} | **Afirmaciones:** {len(c.afirmaciones)} | "
              f"**Parametros:** {len(c.parametros)} | **Reglas:** {len(c.reglas)} | "
              f"**Estimulos:** {len(c.estimulos)} | **Recetas:** {len(c.recetas)}", ""]
    lineas += ["## Fuentes", ""]
    for f in c.fuentes:
        lineas += _md_fuente(f) + [""]
    lineas += ["## Afirmaciones", ""]
    for a in c.afirmaciones:
        lineas += [f"### {a.id}", f"- Texto: {a.texto}", f"- Estado: {a.estado}",
                   f"- Certeza: {a.certeza or '-'}",
                   "- Fuentes: " + (", ".join(x.id for x in a.fuentes) or "(criterio firmado)"), ""]
    lineas += ["## Parametros", ""]
    for p in c.parametros:
        lineas += [f"### {p.id} - {p.nombre}", f"- Valor: {p.valor} {p.unidad}".rstrip(),
                   f"- Procedencia: {p.procedencia}", f"- Firma: {p.firmado_por or 'pendiente'}",
                   f"- Nota: {p.nota}", ""]
    lineas += ["## Reglas", ""]
    for r in c.reglas:
        lineas += [f"### {r.id}", f"- Enunciado: {r.enunciado}",
                   f"- Cuando: {_json_canonico(r.cuando)}", f"- Entonces: {_json_canonico(r.entonces)}",
                   f"- Evidencia: {', '.join(r.evidencia) or '-'}",
                   f"- Parametros: {', '.join(r.parametros) or '-'}",
                   f"- Metrica de exito: {_json_canonico(r.metrica_exito)}",
                   f"- Contraindicaciones: {', '.join(r.contraindicaciones) or '-'}", ""]
    lineas += ["## Estimulos", ""]
    for e in c.estimulos:
        lineas += [f"### {e.id} - {e.nombre}", f"- Entrena: {e.entrena}",
                   f"- No entrena: {e.no_entrena}", f"- Recuperacion: {e.recuperacion_h} h", ""]
    lineas += ["## Recetas", ""]
    for r in c.recetas:
        lineas += [f"### {r.id} - {r.nombre}", f"- Sesion: {r.sesion}",
                   f"- Estimulo: {r.estimulo or '-'}", f"- Porque: {r.porque}", "",
                   "| Orden | Tipo | Texto | Metros | Ritmo |", "|---|---|---|---|---|"]
        for p in r.pasos:
            lineas.append(f"| {p.orden} | {p.tipo} | {p.texto} | {p.metros or '-'} | {p.ritmo_100 or '-'} |")
        lineas.append("")
    lineas += ["## Calendario", "",
               f"- Dias del entrenador: {', '.join(c.calendario.dias_entrenador) or '-'}",
               f"- Dias propios: {', '.join(c.calendario.dias_propios) or '-'}",
               f"- Dia de bici: {c.calendario.dia_bici or '-'}",
               f"- Dias de calidad: {', '.join(c.calendario.dias_calidad) or '-'}",
               f"- Dias largos: {', '.join(c.calendario.dias_largos) or '-'}", ""]
    return "\n".join(lineas).rstrip() + "\n"


def exportar_markdown(c: Conocimiento | None = None, ruta: str = RUTA_CONOCIMIENTO,
                      destino: str | None = None) -> dict:
    """Escribe el Markdown generado en `data/derived/conocimiento/` (nunca en `informes/`)."""
    c = c or cargar(ruta)
    if not c.hay_conocimiento():
        raise ValueError("no hay conocimiento que exportar")
    destino = destino or os.path.join(RUTA_SALIDA, "T_base_generado.md")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    texto = _markdown(c)
    with open(destino, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    return {"ok": True, "destino": destino, "version": c.version, "hash": c.hash,
            "bytes": len(texto.encode("utf-8")), "conteos": _conteos(c)}


def comparar_markdown(c: Conocimiento | None = None, ruta: str = RUTA_CONOCIMIENTO,
                       ruta_anexo: str | None = None,
                       destino: str | None = None) -> dict:
    """Compara el TOML con el anexo Markdown actual y deja un informe de diferencias.

    La comparacion es semantica por entidades: fuentes por numero antiguo, conteos de criterios,
    reglas y recetas. El TOML de F2 es un piloto: el resto se migra en F3.
    """
    from . import conocimiento as md

    c = c or cargar(ruta)
    ruta_anexo = ruta_anexo or md.RUTA_ANEXO
    destino = destino or os.path.join(RUTA_SALIDA, "diferencias_markdown.md")
    if not os.path.isfile(ruta_anexo):
        return {"ok": False, "error": f"no existe el anexo {ruta_anexo}"}

    md_fuentes = md.fuentes(ruta_anexo)
    toml_fuentes = {f.legacy_id: f for f in c.fuentes if f.legacy_id}
    md_ids = {str(n) for n in md_fuentes}
    faltan = sorted(md_ids - set(toml_fuentes), key=int)
    sobran = sorted(set(toml_fuentes) - md_ids, key=int)
    url_distinta = []
    for n in sorted(md_ids & set(toml_fuentes), key=int):
        if md_fuentes[int(n)]["url"] != toml_fuentes[n].url:
            url_distinta.append(n)

    try:
        from . import estimulos, reglas
        md_reglas, md_recetas = len(reglas.REGLAS), len(estimulos.RECETAS)
    except Exception:  # noqa: BLE001 - el informe no debe romper por un modulo opcional
        md_reglas = md_recetas = None
    md_criterios = len(md.criterios(ruta_anexo))

    lineas = ["# Diferencias entre el anexo T y el TOML (F2)", "",
              f"- **Anexo:** `{ruta_anexo}`",
              f"- **TOML:** `{c.version or '(vacio)'}`",
              f"- **Fuentes:** anexo {len(md_fuentes)}, TOML {len(c.fuentes)}",
              f"- **Criterios del anexo:** {md_criterios}; **afirmaciones TOML:** {len(c.afirmaciones)}",
              f"- **Reglas:** anexo {md_reglas if md_reglas is not None else '?'}; TOML {len(c.reglas)}",
              f"- **Recetas:** anexo {md_recetas if md_recetas is not None else '?'}; TOML {len(c.recetas)}",
              "", "## Fuentes", "",
              f"- Faltan en TOML: {', '.join('[' + n + ']' for n in faltan) or 'ninguna'}",
              f"- Sobran en TOML: {', '.join('[' + n + ']' for n in sobran) or 'ninguna'}",
              f"- URL distinta: {', '.join('[' + n + ']' for n in url_distinta) or 'ninguna'}",
              "", "## Entidades del piloto", "",
              f"- Afirmaciones: {', '.join(a.id for a in c.afirmaciones) or '-'}",
              f"- Parametros: {', '.join(p.id for p in c.parametros) or '-'}",
              f"- Reglas: {', '.join(r.id for r in c.reglas) or '-'}",
              f"- Estimulos: {', '.join(e.id for e in c.estimulos) or '-'}",
              f"- Recetas: {', '.join(r.id for r in c.recetas) or '-'}",
              "", "## Nota", "",
              "F2 solo migra el corte vertical R2. Las diferencias de conteo son esperadas: el resto de",
              "reglas, recetas y criterios se migra en F3. El motor sigue en v1; este informe no cambia",
              "ningun comportamiento.", ""]
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lineas))
    return {"ok": True, "informe": destino, "version": c.version,
            "faltan_en_toml": faltan, "sobran_en_toml": sobran, "url_distinta": url_distinta,
            "conteos": {"anexo_fuentes": len(md_fuentes), "toml_fuentes": len(c.fuentes),
                        "anexo_criterios": md_criterios, "toml_afirmaciones": len(c.afirmaciones),
                        "anexo_reglas": md_reglas, "toml_reglas": len(c.reglas),
                        "anexo_recetas": md_recetas, "toml_recetas": len(c.recetas)}}
