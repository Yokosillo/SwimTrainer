#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Estado del atleta: una foto reproducible de lo que se sabe en una fecha (F4).

No es un modelo de IA ni un pronostico. Cada numero sale de una tabla o de un modulo ya existente
(`analitica`, `competicion`, `evaluacion`, `fuerza`, `gimnasio`) y lleva:

- `valor` y `unidad`;
- `n` (cuantas observaciones lo sostienen);
- `dispersion` (desviacion tipica, cuando se puede calcular);
- `confianza` (`baja`, `media`, `alta`);
- `fuente` (tablas/modulos de donde sale);
- `limitaciones` (lo que no se puede concluir).

Si no hay datos, la metrica queda en `estado="sin_datos"` con el motivo. Nunca se rellena un cero
para que la foto parezca completa.

La regla de confianza esta en `REGLA_CONFIANZA` y en `_confianza()`. Es deliberadamente conservadora:
un dato aislado es `baja`, aunque sea exacto.

El snapshot se identifica con un hash canonico de fecha + version del conocimiento + contenido. La
fecha de generacion no entra en el id: dos calculos con los mismos datos dan el mismo `estado_id`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import statistics as st
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from types import MappingProxyType

from . import db

REGLA_CONFIANZA = (
    "Confianza: alta si hay muchas observaciones y la ventana esta cubierta; media si hay una base "
    "suficiente para orientar; baja si n es pequeño, faltan partes o la dispersion no se puede medir. "
    "Sin observaciones, estado=sin_datos (no se inventa un cero)."
)

# Umbrales de la regla, por familia de metrica. Estan aqui para poder auditarlos.
FORMULAS_CARGA = {
    "aguda_7d": "suma de minutos de las sesiones con fecha en [fecha-6, fecha]",
    "cronica_28d": "suma de minutos en [fecha-27, fecha] / 4",
    "ratio_carga": "aguda_7d / cronica_28d (si cronica_28d > 0)",
    "monotonia_7d": "media(minutos diarios de los 7 dias) / desviacion_tipica_poblacional(esos 7 dias)",
    "strain_7d": "aguda_7d * monotonia_7d",
}

UMBRALES = {
    "marcas": (4, 8),       # (media, alta)
    "carga": (8, 20),
    "sueno": (5, 14),
    "fuerza": (4, 8),
    "adherencia": (5, 12),
    "respuesta": (5, 15),
    "general": (5, 12),
}


def _congelar(valor):
    """Copia profunda e inmutable: dict -> MappingProxyType, lista -> tupla, conjunto -> frozenset."""
    if isinstance(valor, Mapping):
        return MappingProxyType({str(k): _congelar(v) for k, v in valor.items()})
    if isinstance(valor, (list, tuple)):
        return tuple(_congelar(v) for v in valor)
    if isinstance(valor, (set, frozenset)):
        return frozenset(_congelar(v) for v in valor)
    return valor


def _descongelar(valor):
    """Vuelve a dict/list para serializar el snapshot sin perder la copia inmutable interna."""
    if isinstance(valor, Mapping):
        return {str(k): _descongelar(v) for k, v in valor.items()}
    if isinstance(valor, tuple):
        return [_descongelar(v) for v in valor]
    if isinstance(valor, frozenset):
        return [_descongelar(v) for v in sorted(valor, key=repr)]
    return valor


@dataclass(frozen=True)
class Metrica:
    clave: str
    etiqueta: str
    valor: object = None
    unidad: str = ""
    n: int = 0
    dispersion: float | None = None
    confianza: str = "baja"
    fuente: tuple[str, ...] = ()
    limitaciones: tuple[str, ...] = ()
    estado: str = "sin_datos"
    detalle: Mapping = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self):
        object.__setattr__(self, "fuente", tuple(self.fuente or ()))
        object.__setattr__(self, "limitaciones", tuple(self.limitaciones or ()))
        object.__setattr__(self, "detalle", _congelar(self.detalle or {}))

    def a_dict(self) -> dict:
        return {
            "clave": self.clave, "etiqueta": self.etiqueta, "valor": self.valor,
            "unidad": self.unidad, "n": self.n, "dispersion": self.dispersion,
            "confianza": self.confianza, "fuente": list(self.fuente),
            "limitaciones": list(self.limitaciones), "estado": self.estado,
            "detalle": _descongelar(self.detalle),
        }


@dataclass(frozen=True)
class SeccionEstado:
    clave: str
    titulo: str
    metricas: tuple[Metrica, ...] = ()
    notas: tuple[str, ...] = ()

    def a_dict(self) -> dict:
        return {"clave": self.clave, "titulo": self.titulo,
                "metricas": [m.a_dict() for m in self.metricas], "notas": list(self.notas)}


@dataclass(frozen=True)
class EstadoAtleta:
    fecha: str
    version_conocimiento: str
    version_hash: str
    secciones: tuple[SeccionEstado, ...]
    avisos: tuple[str, ...] = ()
    fuentes: tuple[str, ...] = ()
    generado_en: str = ""
    estado_id: str = ""
    hash: str = ""
    knowledge_hash: str = ""
    state_hash: str = ""
    regla_confianza: str = REGLA_CONFIANZA

    def a_dict(self, incluir_generado: bool = True) -> dict:
        d = {
            "estado_id": self.estado_id,
            "fecha": self.fecha,
            "version_conocimiento": self.version_conocimiento,
            "version_hash": self.version_hash,
            "knowledge_hash": self.knowledge_hash,
            "state_hash": self.state_hash,
            "hash": self.hash,
            "regla_confianza": self.regla_confianza,
            "formulas_carga": dict(FORMULAS_CARGA),
            "secciones": [s.a_dict() for s in self.secciones],
            "avisos": list(self.avisos),
            "fuentes": list(self.fuentes),
            "sin_datos": sum(1 for s in self.secciones for m in s.metricas if m.estado == "sin_datos"),
            "metricas": sum(len(s.metricas) for s in self.secciones),
        }
        if incluir_generado:
            d["generado_en"] = self.generado_en
        return d

    def texto(self) -> str:
        lineas = [
            f"ESTADO DEL ATLETA · {self.fecha} · {self.estado_id}",
            f"Conocimiento: {self.version_conocimiento or 'sin version'} (knowledge {self.knowledge_hash[:16]})",
            f"Snapshot: {self.estado_id} (state {self.state_hash[:16]}; version {self.version_hash[:16]})",
            f"Regla de confianza: {self.regla_confianza}",
            "",
        ]
        for s in self.secciones:
            lineas.append(s.titulo.upper())
            for m in s.metricas:
                if m.estado == "sin_datos":
                    valor, unidad = "sin datos", ""
                else:
                    valor, unidad = _formato(m.valor), m.unidad
                extra = f"{m.n} obs" if m.n else "0 obs"
                if m.dispersion is not None:
                    extra += f", disp {_formato(m.dispersion)}"
                lineas.append(f"  {m.etiqueta}: {valor} {unidad}".rstrip()
                              + f"  [{m.confianza}; {extra}]")
                if m.fuente:
                    lineas.append(f"    fuente: {', '.join(m.fuente)}")
                for limitacion in m.limitaciones:
                    lineas.append(f"    limite: {limitacion}")
            for nota in s.notas:
                lineas.append(f"  nota: {nota}")
            lineas.append("")
        if self.avisos:
            lineas.append("AVISOS")
            lineas.extend(f"  - {a}" for a in self.avisos)
        return "\n".join(lineas).rstrip()


# --------------------------------------------------------------------------- utilidades

def _formato(valor) -> str:
    if isinstance(valor, float):
        return f"{valor:.2f}".rstrip("0").rstrip(".")
    return str(valor)


def _media(valores):
    return round(float(st.mean(valores)), 2) if valores else None


def _dispersion(valores):
    return round(float(st.pstdev(valores)), 2) if len(valores) >= 2 else None


def _confianza(n: int, familia: str = "general") -> str:
    """Aplica los umbrales de `UMBRALES`; n=0 no es una confianza, es ausencia de datos."""
    if n <= 0:
        return "baja"
    media, alta = UMBRALES.get(familia, UMBRALES["general"])
    if n >= alta:
        return "alta"
    if n >= media:
        return "media"
    return "baja"


def _bajar_confianza(conf: str) -> str:
    return {"alta": "media", "media": "baja", "baja": "baja"}.get(conf, "baja")


def _fuentes(*nombres) -> tuple[str, ...]:
    return tuple(dict.fromkeys(n for n in nombres if n))


def _metrica(clave: str, etiqueta: str, valor=None, unidad: str = "", n: int = 0,
             dispersion=None, confianza: str | None = None, fuente=(), limitaciones=(),
             estado: str | None = None, detalle=None, familia: str = "general") -> Metrica:
    lims = list(limitaciones)
    if valor is None or n <= 0:
        if not lims:
            lims = ["No hay observaciones suficientes en la ventana."]
        return Metrica(clave=clave, etiqueta=etiqueta, valor=None, unidad=unidad, n=0,
                       dispersion=None, confianza="baja", fuente=tuple(fuente),
                       limitaciones=tuple(lims), estado="sin_datos", detalle=_congelar(detalle or {}))
    conf = confianza or _confianza(n, familia)
    if conf == "baja" and not lims:
        lims = [f"n={n}: base pequeña, orientativo, no concluyente."]
    if estado is None:
        estado = "parcial" if conf == "baja" else "ok"
    return Metrica(clave=clave, etiqueta=etiqueta, valor=valor, unidad=unidad, n=int(n),
                   dispersion=dispersion, confianza=conf, fuente=tuple(fuente),
                   limitaciones=tuple(lims), estado=estado, detalle=_congelar(detalle or {}))


def _rango(fecha: str, dias: int) -> tuple[str, str]:
    fin = date.fromisoformat(fecha[:10])
    inicio = fin - timedelta(days=max(1, dias) - 1)
    return inicio.isoformat(), fin.isoformat()


def _seccion(clave: str, titulo: str, metricas, notas=()) -> SeccionEstado:
    return SeccionEstado(clave=clave, titulo=titulo, metricas=tuple(metricas), notas=tuple(notas))


# --------------------------------------------------------------------------- rendimiento

def _bloques_libres(cn: sqlite3.Connection) -> list[dict]:
    from . import analitica
    return [b for b in analitica.bloques(cn)
            if b.get("estilo") == "libre" and b.get("fiable") and b.get("ritmo_100")
            and b.get("piscina_m") == 25]


def _mejor_bloque(cn: sqlite3.Connection, clave: str, etiqueta: str, minimo: float, maximo: float) -> Metrica:
    bloqueos = [b for b in _bloques_libres(cn) if minimo <= b["dist_m"] < maximo]
    if not bloqueos:
        return _metrica(clave, etiqueta, None, "s/100", 0, fuente=_fuentes("analitica.bloques"),
                        limitaciones=(f"No hay bloques fiables de {minimo:.0f}-{maximo:.0f} m en piscina de 25 m.",))
    ritmos = [float(b["ritmo_100"]) for b in bloqueos]
    mejor = min(bloqueos, key=lambda b: b["ritmo_100"])
    sin_material = sum(1 for b in bloqueos if not b.get("material_conocido"))
    lims = []
    conf = _confianza(len(bloqueos), "marcas")
    if sin_material:
        lims.append(f"{sin_material} de {len(bloqueos)} bloques sin parte: el material es desconocido.")
        if sin_material / len(bloqueos) > 0.5:
            conf = _bajar_confianza(conf)
    return _metrica(clave, etiqueta, round(float(mejor["ritmo_100"]), 2), "s/100",
                    len(bloqueos), _dispersion(ritmos), confianza=conf,
                    fuente=_fuentes("analitica.bloques"), limitaciones=lims, familia="marcas",
                    detalle={"mejor_tiempo_s": round(float(mejor["tiempo_s"]), 2),
                             "dist_m": round(float(mejor["dist_m"]), 1),
                             "fecha": mejor.get("fecha"), "material_conocido": bool(mejor.get("material_conocido"))})


def _ritmo_referencia(cn: sqlite3.Connection) -> Metrica:
    bloqueos = [b for b in _bloques_libres(cn) if 400 <= b["dist_m"] < 500]
    if not bloqueos:
        return _metrica("ritmo_referencia", "Ritmo de referencia del 400", None, "s/100", 0,
                        fuente=_fuentes("analitica.bloques"),
                        limitaciones=("No hay bloques de 400 m para fijar una referencia.",))
    ritmos = sorted(float(b["ritmo_100"]) for b in bloqueos)
    base = ritmos[:3]
    sin_material = sum(1 for b in bloqueos if not b.get("material_conocido"))
    conf = _confianza(len(bloqueos), "marcas")
    if len(bloqueos) and sin_material / len(bloqueos) > 0.5:
        conf = _bajar_confianza(conf)
    return _metrica("ritmo_referencia", "Ritmo de referencia del 400", round(float(st.median(base)), 2),
                    "s/100", len(bloqueos), _dispersion(ritmos), confianza=conf,
                    fuente=_fuentes("analitica.bloques"),
                    limitaciones=("Es una referencia de entrenamiento, no una marca oficial.",
                                  f"{sin_material} bloques sin parte: material desconocido.") if sin_material else
                    ("Es una referencia de entrenamiento, no una marca oficial.",),
                    familia="marcas", detalle={"mediana_mejores_3": round(float(st.median(base)), 2)})


def _velocidad_critica(cn: sqlite3.Connection) -> Metrica:
    b400 = [b for b in _bloques_libres(cn) if 400 <= b["dist_m"] < 500]
    b1000 = [b for b in _bloques_libres(cn) if 1000 <= b["dist_m"] < 1250]
    if not b400 or not b1000:
        return _metrica("velocidad_critica", "Velocidad critica", None, "s/100", 0,
                        fuente=_fuentes("analitica.bloques"),
                        limitaciones=("Hacen falta un bloque de 400 y otro de 1.000 m para estimarla.",))
    a = min(b400, key=lambda b: b["tiempo_s"])
    b = min(b1000, key=lambda b: b["tiempo_s"])
    d1, t1 = float(a["dist_m"]), float(a["tiempo_s"])
    d2, t2 = float(b["dist_m"]), float(b["tiempo_s"])
    if t2 <= t1 or d2 <= d1:
        return _metrica("velocidad_critica", "Velocidad critica", None, "s/100", 0,
                        fuente=_fuentes("analitica.bloques"),
                        limitaciones=("Los dos bloques no permiten calcular una pendiente positiva.",))
    cs = (d2 - d1) / (t2 - t1)          # m/s
    if cs <= 0:
        return _metrica("velocidad_critica", "Velocidad critica", None, "s/100", 0,
                        fuente=_fuentes("analitica.bloques"),
                        limitaciones=("La velocidad critica sale negativa: los bloques no son comparables.",))
    ritmo = 100.0 / cs
    return _metrica("velocidad_critica", "Velocidad critica", round(ritmo, 2), "s/100", 2,
                    None, confianza="baja", fuente=_fuentes("analitica.bloques"),
                    limitaciones=("Solo dos puntos (400 y 1.000) y sin parte en algunos bloques: "
                                  "estimacion gruesa, no una prueba de laboratorio.",),
                    estado="parcial", detalle={"velocidad_m_s": round(cs, 3),
                                               "bloque_400": a.get("fecha"),
                                               "bloque_1000": b.get("fecha")})


def _oficiales(cn: sqlite3.Connection, distancia: int) -> Metrica:
    from . import competicion
    filas = competicion.historial(cn, "libre", distancia, piscina=25, orden="marca", completas=True)
    piscina = 25
    if not filas:
        filas = competicion.historial(cn, "libre", distancia, orden="marca", completas=True)
        piscina = None
    if not filas:
        return _metrica(f"mejor_{distancia}_oficial", f"Mejor {distancia} oficial", None, "s", 0,
                        fuente=_fuentes("competicion"),
                        limitaciones=(f"No hay marcas oficiales validas de {distancia} m libre.",))
    tiempos = [float(f["segundos"]) for f in filas if f["segundos"]]
    if not tiempos:
        return _metrica(f"mejor_{distancia}_oficial", f"Mejor {distancia} oficial", None, "s", 0,
                        fuente=_fuentes("competicion"),
                        limitaciones=(f"Las marcas de {distancia} no tienen tiempo utilizable.",))
    mejor = min(filas, key=lambda f: f["segundos"])
    lims = []
    if piscina is None:
        lims.append("Se mezclan piscinas de 25 y 50 m: no son equivalentes.")
    return _metrica(f"mejor_{distancia}_oficial", f"Mejor {distancia} oficial",
                    round(float(mejor["segundos"]), 2), "s", len(tiempos), _dispersion(tiempos),
                    fuente=_fuentes("competicion"), limitaciones=lims, familia="marcas",
                    detalle={"marca": mejor["marca"], "fecha": mejor["fecha"],
                             "piscina_m": mejor["piscina_m"],
                             "ritmo_100": round(float(mejor["ritmo_100"]), 2) if mejor["ritmo_100"] else None})


def _tendencia_oficial(cn: sqlite3.Connection) -> Metrica:
    from . import competicion
    try:
        d = competicion.comparar(cn, "libre", 400, piscina=25)
    except Exception as exc:                       # la base sintetica puede no tener la tabla completa
        return _metrica("tendencia_400_oficial", "Tendencia oficial del 400", None, "s/100 por ano", 0,
                        fuente=_fuentes("competicion"), limitaciones=(f"No se pudo calcular: {exc}",))
    t = d.get("tendencia")
    if not t:
        return _metrica("tendencia_400_oficial", "Tendencia oficial del 400", None, "s/100 por ano", 0,
                        fuente=_fuentes("competicion"),
                        limitaciones=("Hacen falta al menos 5 marcas oficiales de 400 m para estimar tendencia.",))
    return _metrica("tendencia_400_oficial", "Tendencia oficial del 400",
                    round(float(t["pendiente_s_por_ano"]), 2), "s/100 por ano", int(t["n"]), None,
                    fuente=_fuentes("competicion"),
                    limitaciones=(t.get("lectura", "") + ": pendiente observada, no prediccion.",),
                    familia="marcas", detalle={"n": t["n"], "desde": t["desde"], "hasta": t["hasta"]})


def _seccion_rendimiento(cn: sqlite3.Connection) -> SeccionEstado:
    metricas = [
        _mejor_bloque(cn, "mejor_400", "Mejor 400 (bloque)", 400, 500),
        _mejor_bloque(cn, "mejor_1000", "Mejor 1.000 (bloque)", 1000, 1250),
        _ritmo_referencia(cn),
        _velocidad_critica(cn),
        _oficiales(cn, 400),
        _oficiales(cn, 1000),
        _tendencia_oficial(cn),
    ]
    return _seccion("rendimiento", "Rendimiento", metricas, (
        "Los bloques de entrenamiento no son marcas oficiales: mezclan material, piscina y momento del ciclo.",
    ))


# --------------------------------------------------------------------------- carga

def _eventos(cn: sqlite3.Connection, desde: str, hasta: str) -> list[dict]:
    fuera: list[dict] = []
    for f in cn.execute(
        """SELECT inicio_local, disciplina, duracion_s, distancia_m
           FROM actividad WHERE substr(inicio_local, 1, 10) BETWEEN ? AND ?""", (desde, hasta)):
        fecha = (f["inicio_local"] or "")[:10]
        if not fecha:
            continue
        fuera.append({"fecha": fecha, "min": float(f["duracion_s"] or 0) / 60.0,
                      "metros": float(f["distancia_m"] or 0) if f["disciplina"] == "natacion" else 0.0,
                      "tipo": f["disciplina"] or "otro", "fuente": "actividad"})
    for f in cn.execute(
        """SELECT fecha, tipo, minutos, distancia_m FROM apunte
           WHERE fecha BETWEEN ? AND ?""", (desde, hasta)):
        fecha = (f["fecha"] or "")[:10]
        if not fecha:
            continue
        fuera.append({"fecha": fecha, "min": float(f["minutos"] or 0),
                      "metros": float(f["distancia_m"] or 0) if (f["tipo"] or "").lower() == "natacion" else 0.0,
                      "tipo": f["tipo"] or "otro", "fuente": "apunte"})
    return fuera


def _por_dia(eventos: list[dict]) -> dict[str, dict]:
    dias: dict[str, dict] = {}
    for e in eventos:
        d = dias.setdefault(e["fecha"], {"min": 0.0, "metros": 0.0, "sesiones": 0})
        d["min"] += e["min"]
        d["metros"] += e["metros"]
        d["sesiones"] += 1
    return dias


def _carga(cn: sqlite3.Connection, fecha: str) -> SeccionEstado:
    d7, h = _rango(fecha, 7)
    d28, _ = _rango(fecha, 28)
    ev7, ev28 = _eventos(cn, d7, h), _eventos(cn, d28, h)
    dias7, dias28 = _por_dia(ev7), _por_dia(ev28)
    mins7 = [dias7.get((date.fromisoformat(d7) + timedelta(days=i)).isoformat(), {}).get("min", 0.0)
             for i in range(7)]
    mins28 = [dias28.get((date.fromisoformat(d28) + timedelta(days=i)).isoformat(), {}).get("min", 0.0)
              for i in range(28)]
    total7, total28 = sum(mins7), sum(mins28)
    ses7, ses28 = len(ev7), len(ev28)
    aguda, cronica = total7, total28 / 4.0
    ratio = (aguda / cronica) if cronica > 0 else None
    media7, sd7 = (st.mean(mins7), st.pstdev(mins7)) if mins7 else (None, None)
    # Monotonia 7 d: media diaria / desviacion tipica poblacional de esos mismos 7 dias.
    monotonia = (media7 / sd7) if (media7 and sd7) else None
    # Strain 7 d: carga aguda de la misma ventana por la monotonia de 7 d.
    strain = (total7 * monotonia) if monotonia is not None else None
    # Racha: dias seguidos con carga hasta el ultimo dia que se entreno (no se convierte un descanso en 0).
    ultimo_entreno = max((d for d, v in dias28.items() if v.get("min", 0) > 0 and d <= fecha), default=None)
    racha = 0
    if ultimo_entreno:
        cursor = date.fromisoformat(ultimo_entreno)
        while cursor >= date.fromisoformat(d28) and dias28.get(cursor.isoformat(), {}).get("min", 0) > 0:
            racha += 1
            cursor -= timedelta(days=1)
    # Cobertura de RPE y de partes en las sesiones de natacion de la ventana.
    rpe_n = cn.execute(
        """SELECT COUNT(*) FROM natacion_sesion ns JOIN actividad a ON a.id = ns.actividad_id
           WHERE a.disciplina = 'natacion' AND substr(a.inicio_local, 1, 10) BETWEEN ? AND ?
             AND ns.rpe IS NOT NULL""", (d28, h)).fetchone()[0]
    swim_n = cn.execute(
        """SELECT COUNT(*) FROM natacion_sesion ns JOIN actividad a ON a.id = ns.actividad_id
           WHERE a.disciplina = 'natacion' AND substr(a.inicio_local, 1, 10) BETWEEN ? AND ?""",
        (d28, h)).fetchone()[0]
    partes_n = cn.execute("SELECT COUNT(*) FROM parte WHERE fecha BETWEEN ? AND ?", (d28, h)).fetchone()[0]
    lims = []
    if swim_n and rpe_n < swim_n:
        lims.append(f"RPE disponible en {rpe_n} de {swim_n} sesiones de natacion.")
    if swim_n and partes_n < swim_n:
        lims.append(f"Parte disponible en {partes_n} de {swim_n} sesiones de natacion.")
    lims.append("Carga en minutos registrados; incluye natacion, bici y otras actividades con duracion.")
    metricas = [
        _metrica("carga_aguda_7d", "Carga aguda (7 d)", round(aguda, 1), "min", ses7,
                 _dispersion(mins7), fuente=_fuentes("actividad", "natacion_sesion", "apunte"),
                 limitaciones=lims, familia="carga",
                 detalle={"dias_con_carga": sum(1 for x in mins7 if x > 0),
                          "formula": FORMULAS_CARGA["aguda_7d"]}),
        _metrica("carga_cronica_28d", "Carga cronica (media semanal 28 d)", round(cronica, 1), "min/sem",
                 ses28, _dispersion(mins28), fuente=_fuentes("actividad", "natacion_sesion", "apunte"),
                 limitaciones=lims, familia="carga",
                 detalle={"total_28d_min": round(total28, 1),
                          "formula": FORMULAS_CARGA["cronica_28d"]}),
        _metrica("ratio_carga", "Ratio aguda/cronica", round(ratio, 2) if ratio is not None else None, "x",
                 min(ses28, 28), None, fuente=_fuentes("actividad", "apunte"),
                 limitaciones=lims if ratio is not None else ("No hay carga cronica: no se puede calcular.",),
                 familia="carga", detalle={"aguda_min": round(aguda, 1), "cronica_min": round(cronica, 1),
                                            "formula": FORMULAS_CARGA["ratio_carga"]}),
        _metrica("monotonia", "Monotonia (7 d)", round(monotonia, 2) if monotonia is not None else None, "x",
                 7 if monotonia is not None else 0, None, fuente=_fuentes("actividad", "apunte"),
                 limitaciones=lims + (["Sin variacion diaria: la monotonia no esta definida."]
                                      if monotonia is None else []),
                 familia="carga", detalle={"media_diaria_7d_min": round(media7, 2) if media7 else None,
                                            "sd_diaria_7d_min": round(sd7, 2) if sd7 else None,
                                            "formula": FORMULAS_CARGA["monotonia_7d"]}),
        _metrica("strain", "Strain (7 d)", round(strain, 1) if strain is not None else None, "UA",
                 7 if strain is not None else 0, None, fuente=_fuentes("actividad", "apunte"),
                 limitaciones=lims + (["Sin monotonia no se puede calcular el strain."] if strain is None else []),
                 familia="carga", detalle={"formula": FORMULAS_CARGA["strain_7d"]}),
        _metrica("dias_consecutivos", "Dias consecutivos entrenando", racha, "dias", racha, None,
                 fuente=_fuentes("actividad", "apunte"),
                 limitaciones=("Cuenta la racha hasta el ultimo dia con sesion; si la fecha es de descanso no se "
                               "convierte en 0.",) if racha else ("No hay sesiones en la ventana para medir una racha.",),
                 familia="carga", detalle={"ultimo_dia_con_sesion": ultimo_entreno}),
        _metrica("metros_7d", "Metros nadados (7 d)", round(sum(d["metros"] for d in dias7.values()), 1), "m",
                 ses7, None, fuente=_fuentes("actividad", "apunte"), limitaciones=lims, familia="carga"),
        _metrica("sesiones_7d", "Sesiones (7 d)", ses7, "sesiones", ses7, None,
                 fuente=_fuentes("actividad", "apunte"), limitaciones=lims, familia="carga"),
        _metrica("metros_28d", "Metros nadados (28 d)", round(sum(d["metros"] for d in dias28.values()), 1), "m",
                 ses28, None, fuente=_fuentes("actividad", "apunte"), limitaciones=lims, familia="carga"),
        _metrica("sesiones_28d", "Sesiones (28 d)", ses28, "sesiones", ses28, None,
                 fuente=_fuentes("actividad", "apunte"), limitaciones=lims, familia="carga"),
    ]
    return _seccion("carga", "Carga", metricas, (
        "La carga se mide en minutos registrados, no en RPE: el RPE falta en muchas sesiones. "
        "La ventana es la que termina en la fecha del estado.",
    ))


# --------------------------------------------------------------------------- recuperacion

def _sueno(cn: sqlite3.Connection, fecha: str) -> Metrica:
    desde, hasta = _rango(fecha, 7)
    filas = [dict(f) for f in cn.execute(
        "SELECT horas, puntuacion, eficiencia FROM sueno WHERE fecha BETWEEN ? AND ?", (desde, hasta))]
    valores = [float(f["horas"]) for f in filas if f["horas"] is not None]
    if not valores:
        return _metrica("sueno_horas_7d", "Sueno (7 d)", None, "h", 0, fuente=_fuentes("sueno"),
                        limitaciones=("No hay noches registradas en los ultimos 7 dias.",))
    return _metrica("sueno_horas_7d", "Sueno (7 d)", _media(valores), "h", len(valores),
                    _dispersion(valores), fuente=_fuentes("sueno"),
                    limitaciones=("Solo noches del reloj; el apunte del atleta manda cuando existe.",),
                    familia="sueno", detalle={"puntuacion_media": _media([f["puntuacion"] for f in filas
                                                                          if f["puntuacion"] is not None]),
                                               "eficiencia_media": _media([f["eficiencia"] for f in filas
                                                                           if f["eficiencia"] is not None])})


def _rpe(cn: sqlite3.Connection, fecha: str) -> Metrica:
    desde, hasta = _rango(fecha, 28)
    valores = [float(f["rpe"]) / 10.0 for f in cn.execute(
        """SELECT ns.rpe FROM natacion_sesion ns JOIN actividad a ON a.id = ns.actividad_id
           WHERE a.disciplina = 'natacion' AND substr(a.inicio_local, 1, 10) BETWEEN ? AND ?
             AND ns.rpe IS NOT NULL""", (desde, hasta))]
    if not valores:
        return _metrica("rpe_28d", "RPE medio (28 d)", None, "1-10", 0,
                        fuente=_fuentes("natacion_sesion"),
                        limitaciones=("No hay RPE de sesion en la ventana.",))
    return _metrica("rpe_28d", "RPE medio (28 d)", _media(valores), "1-10", len(valores),
                    _dispersion(valores), fuente=_fuentes("natacion_sesion"),
                    limitaciones=("El RPE es de sesion, no de cada bloque; el reloj no lo trae en todas.",),
                    familia="general")


def _sensacion(cn: sqlite3.Connection, fecha: str) -> Metrica:
    desde, hasta = _rango(fecha, 28)
    valores = [float(f["sensacion"]) / 20.0 for f in cn.execute(
        """SELECT ns.sensacion FROM natacion_sesion ns JOIN actividad a ON a.id = ns.actividad_id
           WHERE a.disciplina = 'natacion' AND substr(a.inicio_local, 1, 10) BETWEEN ? AND ?
             AND ns.sensacion IS NOT NULL""", (desde, hasta))]
    if not valores:
        return _metrica("sensacion_28d", "Sensacion media (28 d)", None, "0-5", 0,
                        fuente=_fuentes("natacion_sesion"),
                        limitaciones=("No hay sensacion declarada en la ventana.",))
    return _metrica("sensacion_28d", "Sensacion media (28 d)", _media(valores), "0-5", len(valores),
                    _dispersion(valores), fuente=_fuentes("natacion_sesion"),
                    limitaciones=("Escala Garmin 0-100 convertida a 0-5; es subjetiva.",),
                    familia="general")


def _fc(cn: sqlite3.Connection, fecha: str) -> list[Metrica]:
    desde, hasta = _rango(fecha, 28)
    filas = [dict(f) for f in cn.execute(
        """SELECT ns.fc_media, ns.fc_max FROM natacion_sesion ns JOIN actividad a ON a.id = ns.actividad_id
           WHERE a.disciplina = 'natacion' AND substr(a.inicio_local, 1, 10) BETWEEN ? AND ?""",
        (desde, hasta))]
    medias = [float(f["fc_media"]) for f in filas if f["fc_media"] is not None]
    maximas = [float(f["fc_max"]) for f in filas if f["fc_max"] is not None]
    lims = ("FC de las sesiones de natacion; no hay FC en reposo ni variabilidad cardiaca.",)
    return [
        _metrica("fc_media_28d", "FC media en sesiones (28 d)", _media(medias), "lpm", len(medias),
                 _dispersion(medias), fuente=_fuentes("natacion_sesion"), limitaciones=lims),
        _metrica("fc_max_28d", "FC maxima en sesiones (28 d)", max(maximas) if maximas else None, "lpm",
                 len(maximas), None, fuente=_fuentes("natacion_sesion"), limitaciones=lims),
    ]


def _seccion_recuperacion(cn: sqlite3.Connection, fecha: str) -> SeccionEstado:
    metricas = [_sueno(cn, fecha), _rpe(cn, fecha), _sensacion(cn, fecha)] + _fc(cn, fecha)
    return _seccion("recuperacion", "Recuperacion", metricas, (
        "Sueño, RPE, sensacion y FC se miran por separado: no se combinan en un indice unico que oculte "
        "que falta un dato.",
    ))


# --------------------------------------------------------------------------- fuerza

def _gym_hombro(cn: sqlite3.Connection, desde: str, hasta: str) -> tuple[int, int, list[str]]:
    catalogo = {r["nombre"].lower(): (r["grupo"] or "").lower()
                for r in cn.execute("SELECT nombre, grupo FROM gimnasio_ejercicio")}
    sesiones = 0
    series = 0
    nombres: list[str] = []
    for f in cn.execute("SELECT ejercicios FROM gimnasio_sesion WHERE fecha BETWEEN ? AND ?", (desde, hasta)):
        try:
            detalle = json.loads(f["ejercicios"] or "[]")
        except (TypeError, ValueError):
            detalle = []
        tocado = False
        for d in detalle if isinstance(detalle, list) else []:
            if not isinstance(d, dict):
                continue
            nombre = str(d.get("ejercicio") or "").strip()
            grupo = catalogo.get(nombre.lower(), "")
            if grupo == "hombro" or "hombro" in nombre.lower():
                tocado = True
                series += int(d.get("series") or 0)
                if nombre and nombre not in nombres:
                    nombres.append(nombre)
        if tocado:
            sesiones += 1
    return sesiones, series, nombres


def _seccion_fuerza(cn: sqlite3.Connection, fecha: str) -> SeccionEstado:
    from . import fuerza, gimnasio
    desde, hasta = _rango(fecha, 28)
    try:
        c = gimnasio.carga_semanal(cn, desde, hasta)
    except Exception:
        c = {"sesiones": 0, "series": 0, "repeticiones": 0, "volumen_kg": None, "con_rpe": 0, "por_dia": []}
    rpes = [d["rpe_max"] for d in c.get("por_dia", []) if d.get("rpe_max")]
    hombro_ses, hombro_series, hombro_nombres = _gym_hombro(cn, desde, hasta)
    lims = ("El reloj no guarda ejercicios, series ni kilos: esto sale de lo apuntado a mano.",)
    metricas = [
        _metrica("fuerza_sesiones_28d", "Sesiones de fuerza (28 d)", int(c.get("sesiones") or 0), "sesiones",
                 int(c.get("sesiones") or 0), None, fuente=_fuentes("gimnasio_sesion"),
                 limitaciones=lims, familia="fuerza"),
        _metrica("fuerza_series_28d", "Series de fuerza (28 d)", int(c.get("series") or 0), "series",
                 int(c.get("sesiones") or 0), None, fuente=_fuentes("gimnasio_sesion"),
                 limitaciones=lims, familia="fuerza"),
        _metrica("fuerza_volumen_28d", "Volumen de fuerza (28 d)", c.get("volumen_kg"), "kg",
                 int(c.get("sesiones") or 0), None, fuente=_fuentes("gimnasio_sesion"),
                 limitaciones=(lims[0], "Sin kilos (core, lumbares) el volumen no se suma.") if c.get("volumen_kg") is None else lims,
                 familia="fuerza"),
        _metrica("fuerza_rpe_max_28d", "RPE maximo de fuerza (28 d)", max(rpes) if rpes else None, "1-10",
                 len(rpes), None, fuente=_fuentes("gimnasio_sesion"),
                 limitaciones=(lims[0], "Sin RPE no se sabe si la sesion fue dura.") if not rpes else lims,
                 familia="fuerza"),
        _metrica("fuerza_hombro_28d", "Trabajo de hombro (28 d)", hombro_ses, "sesiones", hombro_ses, None,
                 fuente=_fuentes("gimnasio_sesion", "gimnasio_ejercicio"),
                 limitaciones=(lims[0], "Solo cuenta lo que se llama hombro o esta en ese grupo.") if hombro_ses else
                 (lims[0], "No consta trabajo de hombro en la ventana."),
                 familia="fuerza", detalle={"series": hombro_series, "ejercicios": hombro_nombres}),
    ]
    try:
        dosis = fuerza.dosis_preventiva(cn, fecha)
        metricas.append(_metrica("fuerza_dosis", "Dosis preventiva del hombro", dosis.get("estado"), "",
                                 1, None, fuente=_fuentes("fuerza"),
                                 limitaciones=("Dosis del anexo T.7; no dice si el hombro duele.",),
                                 familia="fuerza", detalle={"dosis": dosis.get("dosis"),
                                                            "hechas": dosis.get("hechas"),
                                                            "cita": dosis.get("cita")}))
    except Exception:
        pass
    return _seccion("fuerza", "Fuerza", metricas, (
        "La fuerza se mide por lo apuntado; el reloj solo guarda la duracion de la sesion.",
    ))


# --------------------------------------------------------------------------- restricciones

def _restricciones(cn: sqlite3.Connection, fecha: str) -> SeccionEstado:
    from . import fuerza
    desde, hasta = _rango(fecha, 28)
    dias_ent = set()
    for f in cn.execute("SELECT fecha FROM apunte WHERE quien = 'entrenador' AND fecha BETWEEN ? AND ?",
                        (desde, hasta)):
        if f["fecha"]:
            dias_ent.add(f["fecha"][:10])
    for f in cn.execute("SELECT fecha FROM parte WHERE compania = 'entrenador' AND fecha BETWEEN ? AND ?",
                        (desde, hasta)):
        if f["fecha"]:
            dias_ent.add(f["fecha"][:10])
    bici = [dict(f) for f in cn.execute(
        """SELECT inicio_local, duracion_s, distancia_m FROM actividad
           WHERE disciplina = 'ciclismo' AND substr(inicio_local, 1, 10) BETWEEN ? AND ?""", (desde, hasta))]
    bici_min = sum(float(f["duracion_s"] or 0) / 60.0 for f in bici)
    materiales = []
    partes_material = set()
    for f in cn.execute(
        """SELECT p.id AS parte_id, ps.material FROM parte_serie ps JOIN parte p ON p.id = ps.parte_id
           WHERE p.fecha BETWEEN ? AND ? AND ps.material IS NOT NULL AND trim(ps.material) <> ''""",
        (desde, hasta)):
        partes_material.add(f["parte_id"])
        materiales.extend(x.strip() for x in (f["material"] or "").split(",") if x.strip())
    piscinas = [f["largo_piscina_m"] for f in cn.execute(
        """SELECT ns.largo_piscina_m FROM natacion_sesion ns JOIN actividad a ON a.id = ns.actividad_id
           WHERE a.disciplina = 'natacion' AND substr(a.inicio_local, 1, 10) BETWEEN ? AND ?
             AND ns.largo_piscina_m IS NOT NULL""", (desde, hasta))]
    piscina = None
    if piscinas:
        piscina = max(set(piscinas), key=piscinas.count)
    casos = list(fuerza.dolor_declarado(cn, desde))
    # El dolor tambien puede estar escrito en el parte o en un apunte, no solo en gimnasio.
    for tabla, campo in (("parte", "notas"), ("apunte", "notas")):
        for f in cn.execute(
            f"SELECT fecha, {campo} AS texto FROM {tabla} WHERE fecha BETWEEN ? AND ?", (desde, hasta)):
            texto = (f["texto"] or "").lower()
            if any(p in texto for p in fuerza.PALABRAS_DOLOR):
                casos.append({"fecha": f["fecha"], "notas": f["texto"], "fuente": tabla})
    if casos:
        dolor = _metrica("dolor_lesion", "Dolor o lesion declarada", "si", "", len(casos), None,
                         confianza="alta", fuente=_fuentes("gimnasio_sesion", "gimnasio_peticion", "parte", "apunte"),
                         limitaciones=("Es lo que el atleta ha escrito; no es un diagnostico.",),
                         detalle={"casos": casos[:10]})
    else:
        dolor = _metrica("dolor_lesion", "Dolor o lesion declarada", None, "", 0,
                         fuente=_fuentes("gimnasio_sesion", "gimnasio_peticion"),
                         limitaciones=("No hay un registro sistematico de dolor: la ausencia de avisos no lo descarta.",))
    metricas = [
        _metrica("dias_entrenador_28d", "Dias con sesion del entrenador (28 d)", len(dias_ent), "dias",
                 len(dias_ent), None, fuente=_fuentes("apunte", "parte"),
                 limitaciones=("Solo consta lo apuntado; el calendario del plan no se copia como si fuera un hecho.",),
                 familia="general"),
        _metrica("bici_sesiones_28d", "Salidas de bici (28 d)", len(bici), "sesiones", len(bici), None,
                 fuente=_fuentes("actividad"), limitaciones=("Bici registrada por el reloj; no se mezcla con nado.",),
                 familia="general", detalle={"minutos": round(bici_min, 1)}),
        _metrica("material_28d", "Sesiones con material etiquetado (28 d)", len(partes_material), "sesiones",
                 len(partes_material), None, fuente=_fuentes("parte_serie"),
                 limitaciones=("Solo se sabe por el parte; el reloj no registra material.",),
                 familia="general", detalle={"materiales": sorted(set(materiales))}),
        _metrica("piscina_habitual", "Piscina habitual (28 d)", piscina, "m", len(piscinas), None,
                 fuente=_fuentes("natacion_sesion"), limitaciones=("Mezclar 25 y 50 m cambia el ritmo.",),
                 familia="general", detalle={"valores": sorted(set(piscinas))}),
        dolor,
    ]
    notas = []
    if casos:
        notas.append("AVISO: hay dolor o lesion declarada; no se debe tratar ni adaptar por cuenta propia. "
                     "Parar esa parte y consultar a un profesional (T.7).")
    return _seccion("restricciones", "Restricciones y contexto", metricas, tuple(notas))


# --------------------------------------------------------------------------- adherencia

def _adherencia(cn: sqlite3.Connection, fecha: str) -> SeccionEstado:
    from . import evaluacion
    desde, hasta = _rango(fecha, 90)
    try:
        d = evaluacion.evaluar_hasta(cn, fecha, semanas=4)
        semanas = d.get("semanas") or []
    except Exception as exc:
        semanas = []
        error = str(exc)
    else:
        error = ""
    plan_n = sum(int(s.get("sesiones_plan") or 0) for s in semanas)
    hechas = sum(int(s.get("sesiones_hechas") or 0) for s in semanas)
    evaluables = sum(int(s.get("sesiones_evaluables") or 0) for s in semanas)
    sin_parte = sum(1 for s in semanas for v in (s.get("sesiones") or []) if v.get("estado") == "sin_parte")
    ratio = (hechas / evaluables) if evaluables else None
    lims = []
    if error:
        lims.append(f"No se pudo evaluar el plan: {error}")
    if sin_parte:
        lims.append(f"{sin_parte} sesiones sin parte: no se juzgan.")
    if not semanas:
        lims.append("No hay semanas del plan empezadas en la ventana.")
    decisiones = [dict(f) for f in cn.execute(
        """SELECT d.fecha, d.motivo FROM decision d WHERE d.fecha BETWEEN ? AND ?
           AND d.tomada = 'cambiada' AND d.motivo IS NOT NULL AND trim(d.motivo) <> ''
           ORDER BY d.fecha DESC""", (desde, hasta))]
    motivos = []
    for f in decisiones:
        if f["motivo"] not in motivos:
            motivos.append(f["motivo"])
    metricas = [
        _metrica("adherencia_4s", "Adherencia al plan (4 semanas)", round(ratio, 2) if ratio is not None else None,
                 "hechas/evaluables", evaluables, None, fuente=_fuentes("evaluacion", "plan", "parte", "actividad"),
                 limitaciones=lims, familia="adherencia",
                 detalle={"sesiones_plan": plan_n, "hechas": hechas, "evaluables": evaluables,
                          "sin_parte": sin_parte}),
        _metrica("cambios_con_motivo", "Cambios de plan con motivo", len(decisiones), "cambios",
                 len(decisiones), None, fuente=_fuentes("recomendacion", "decision"),
                 limitaciones=("Solo cuenta decisiones registradas; lo que no se registra no se puede leer.",)
                 if decisiones else ("No hay decisiones de cambio registradas en la ventana.",),
                 familia="adherencia", detalle={"motivos": motivos[:10]}),
    ]
    return _seccion("adherencia", "Adherencia", metricas, (
        "Adherencia = sesiones hechas / sesiones evaluables. Una sesion sin parte no se da por no hecha: "
        "queda fuera del denominador y se declara.",
    ))


# --------------------------------------------------------------------------- respuesta por estimulo

def _piscina(valor):
    try:
        return int(round(float(valor))) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _respuesta(cn: sqlite3.Connection, fecha: str) -> SeccionEstado:
    desde, hasta = _rango(fecha, 90)
    filas = [dict(f) for f in cn.execute(
        """SELECT ps.intensidad, ps.ritmo_100, ps.metros, ps.tiempo_s, ps.material,
                  p.fecha, p.id AS parte_id, p.piscina_m, ns.rpe, ns.fc_media
           FROM parte_serie ps JOIN parte p ON p.id = ps.parte_id
           LEFT JOIN natacion_sesion ns ON ns.actividad_id = p.actividad_id
           WHERE p.fecha BETWEEN ? AND ? AND ps.intensidad IS NOT NULL
             AND trim(ps.intensidad) <> ''""", (desde, hasta))]
    grupos: dict[tuple[str, int | None], list[dict]] = {}
    for f in filas:
        ritmo = f["ritmo_100"]
        if ritmo is None and f["tiempo_s"] and f["metros"]:
            ritmo = 100.0 * float(f["tiempo_s"]) / float(f["metros"])
        if not ritmo:
            continue
        f["ritmo"] = float(ritmo)
        f["piscina"] = _piscina(f.get("piscina_m"))
        f["clase"] = str(f["intensidad"]).strip().lower()
        grupos.setdefault((f["clase"], f["piscina"]), []).append(f)
    if not grupos:
        return _seccion("respuesta", "Respuesta por estimulo", (
            _metrica("respuesta", "Respuesta por clase de estimulo", None, "s/100", 0,
                     fuente=_fuentes("parte_serie", "parte", "natacion_sesion"),
                     limitaciones=("No hay clases de estimulo con ritmo en los partes de los ultimos 90 dias.",)),
        ), ("No se declara causalidad: sin partes y sin repetir la misma clase no hay respuesta que medir.",))
    # La referencia es la mediana de la MISMA piscina: un 25 y un 50 no son comparables.
    ritmos_pool: dict[int | None, list[float]] = {}
    for f in filas:
        ritmo = f.get("ritmo")
        if ritmo:
            ritmos_pool.setdefault(_piscina(f.get("piscina_m")), []).append(float(ritmo))
    fc_pool: dict[int | None, list[float]] = {}
    rpe_pool: dict[int | None, list[float]] = {}
    for f in filas:
        p = _piscina(f.get("piscina_m"))
        if f.get("fc_media") is not None:
            fc_pool.setdefault(p, []).append(float(f["fc_media"]))
        if f.get("rpe") is not None:
            rpe_pool.setdefault(p, []).append(float(f["rpe"]) / 10.0)
    clases_pool: dict[str, set] = {}
    for (clase, piscina) in grupos:
        clases_pool.setdefault(clase, set()).add(piscina)
    etiquetas = {"cal": "Calentamiento", "ae1": "Aerobico 1", "ae2": "Aerobico 2",
                 "ae3": "Aerobico 3", "sp": "Velocidad / potencia", "pies": "Pies"}
    metricas = []
    for (clase, piscina) in sorted(grupos, key=lambda x: (x[0], x[1] if x[1] is not None else -1)):
        g = grupos[(clase, piscina)]
        ritmos = [x["ritmo"] for x in g]
        mediana = float(st.median(ritmos))
        base = float(st.median(ritmos_pool[piscina])) if ritmos_pool.get(piscina) else mediana
        delta = mediana - base
        fcs = [float(x["fc_media"]) for x in g if x.get("fc_media") is not None]
        rpes = [float(x["rpe"]) / 10.0 for x in g if x.get("rpe") is not None]
        base_fc = _media(fc_pool.get(piscina))
        base_rpe = _media(rpe_pool.get(piscina))
        materiales = sorted({m.strip() for x in g for m in (x.get("material") or "").split(",") if m.strip()})
        varias = len(clases_pool.get(clase, set())) > 1
        sufijo = f"_{piscina}m" if piscina is not None else "_sin_piscina"
        clave = f"respuesta_{clase}" + (sufijo if varias else "")
        etiqueta = f"Respuesta {etiquetas.get(clase, clase)}"
        if piscina is not None:
            etiqueta += f" ({piscina} m)"
        else:
            etiqueta += " (piscina desconocida)"
        lims = ["Delta frente a la mediana de la misma piscina; no es un efecto causal.",
                "FC y RPE son de la sesion, no del bloque."]
        if varias:
            lims.append("Esta clase tiene mas de una piscina: se separa porque 25 y 50 m no son equivalentes.")
        if piscina is None:
            lims.append("Piscina desconocida: no se puede comparar con 25 ni con 50 m.")
        if materiales:
            lims.append(f"Hay bloques con material ({', '.join(materiales)}): confounder.")
        if len(g) < 5:
            lims.append("Pocas observaciones: no se puede separar la clase del resto de la sesion.")
        metricas.append(_metrica(
            clave, etiqueta, round(delta, 2), "s/100", len(g), _dispersion(ritmos),
            fuente=_fuentes("parte_serie", "parte", "natacion_sesion"),
            limitaciones=lims, familia="respuesta",
            detalle={"clase": clase, "piscina_m": piscina, "ritmo_mediano_s100": round(mediana, 2),
                     "ritmo_base_piscina_s100": round(base, 2),
                     "delta_fc_lpm": round((_media(fcs) - base_fc), 2)
                     if (fcs and base_fc is not None) else None,
                     "delta_rpe": round((_media(rpes) - base_rpe), 2)
                     if (rpes and base_rpe is not None) else None,
                     "n_sesiones": len({x["parte_id"] for x in g}), "materiales": materiales}))
    hay_mezcla = any(len(p) > 1 for p in clases_pool.values())
    notas = ["No se declara causalidad: el delta es descriptivo y puede estar confundido por material, fatiga, "
             "piscina o el resto de la sesion."]
    if hay_mezcla:
        notas.append("Se separa por piscina: 25 y 50 m no son equivalentes y no se comparan entre si.")
    return _seccion("respuesta", "Respuesta por estimulo", metricas, tuple(notas))


# --------------------------------------------------------------------------- snapshot

def _canonico(fecha: str, version: str, secciones, avisos, fuentes) -> str:
    d = {"fecha": fecha, "version_conocimiento": version,
         "secciones": [s.a_dict() for s in secciones], "avisos": list(avisos), "fuentes": list(fuentes)}
    return json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def calcular(cn: sqlite3.Connection, fecha: str | None = None) -> EstadoAtleta:
    """Calcula la foto. No escribe en la base; para guardarla, `guardar()`."""
    from . import conocimiento_toml
    fecha = (fecha or date.today().isoformat())[:10]
    c = conocimiento_toml.cargar()
    secciones = (
        _seccion_rendimiento(cn),
        _carga(cn, fecha),
        _seccion_recuperacion(cn, fecha),
        _seccion_fuerza(cn, fecha),
        _restricciones(cn, fecha),
        _adherencia(cn, fecha),
        _respuesta(cn, fecha),
    )
    fuentes = tuple(sorted({f for s in secciones for m in s.metricas for f in m.fuente}))
    avisos = []
    for s in secciones:
        avisos.extend(s.notas)
    if not c.version:
        avisos.append("Sin version de conocimiento: el snapshot no puede citar una base estable.")
    canon = _canonico(fecha, c.version, secciones, avisos, fuentes)
    state_hash = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    knowledge_hash = c.hash
    # `version_hash` cubre las dos cosas: la base de conocimiento y la foto. `state_hash` es solo la
    # foto; `knowledge_hash` es solo el TOML. Se guardan los tres para no confundir que cubre cada uno.
    version_hash = hashlib.sha256(f"{knowledge_hash}:{state_hash}".encode("utf-8")).hexdigest()
    estado_id = "EA-" + state_hash[:16]
    return EstadoAtleta(fecha=fecha, version_conocimiento=c.version, version_hash=version_hash,
                        knowledge_hash=knowledge_hash, state_hash=state_hash,
                        secciones=secciones, avisos=tuple(avisos), fuentes=fuentes,
                        generado_en=db.ahora(), estado_id=estado_id, hash=state_hash)


def guardar(cn: sqlite3.Connection, estado: EstadoAtleta) -> str:
    """Guarda el snapshot. Misma entrada -> mismo id; la fecha de creacion no entra en el hash."""
    d = estado.a_dict()
    cn.execute(
        """INSERT INTO estado_atleta (id, fecha, version_hash, json, creado_en)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               fecha = excluded.fecha, version_hash = excluded.version_hash,
               json = excluded.json, creado_en = excluded.creado_en""",
        (estado.estado_id, estado.fecha, estado.version_hash,
         json.dumps(d, ensure_ascii=False, sort_keys=True), db.ahora()))
    cn.commit()
    return estado.estado_id


def cargar(cn: sqlite3.Connection, estado_id: str) -> dict | None:
    fila = cn.execute("SELECT json FROM estado_atleta WHERE id = ?", (estado_id,)).fetchone()
    if not fila:
        return None
    try:
        return json.loads(fila["json"])
    except (TypeError, ValueError):
        return None


def ultimo(cn: sqlite3.Connection) -> dict | None:
    fila = cn.execute("SELECT json FROM estado_atleta ORDER BY creado_en DESC, id DESC LIMIT 1").fetchone()
    if not fila:
        return None
    try:
        return json.loads(fila["json"])
    except (TypeError, ValueError):
        return None
