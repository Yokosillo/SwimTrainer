#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Capa LLM **opcional** para explicar una recomendación ya calculada (F8).

Principios:

- El LLM no decide, no calcula y no inventa: recibe una recomendación determinista y un contexto
  mínimo de afirmaciones/fuentes/parámetros; devuelve una explicación validada.
- `COACH_ENABLED=0` por defecto. Sin clave, sin URL/modelo o con el flag apagado no se construye
  ningún proveedor ni se hace ninguna llamada.
- El proveedor se inyecta (`ProveedorFalso` en tests); no hay llamadas de red en la suite.
- Si la respuesta no cumple el contrato, se cae a la explicación determinista del motor.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from . import conocimiento_toml

CAMPOS = ("explicacion", "citas", "cifras", "avisos", "confianza")
CONFIANZAS = ("baja", "media", "alta")
PROHIBIDO_MEDICO = re.compile(
    r"\b(diagnost\w*|medicament\w*|tratamiento\w*|rehabilit\w*|curar\w*|fisioterapia\w*|"
    r"receta\w*|pastilla\w*|dosis\w*)\b", re.I)
PROHIBIDO_PROMESA = re.compile(
    r"(vas a bajar|bajar[aá]s|mejorar[aá]s|garantiz\w*|seguro que|conseguir[aá]s|"
    r"vas a conseguir|te aseguro)", re.I)
NUM = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?")


class CoachError(ValueError):
    pass


class Proveedor(Protocol):
    def completar(self, sistema: str, usuario: str) -> str: ...


@dataclass
class ProveedorFalso:
    """Proveedor de test: devuelve lo que se le diga y guarda el payload; nunca toca la red."""
    respuesta: object = "{}"
    error: Exception | None = None
    llamadas: list[tuple[str, str]] = field(default_factory=list)

    def completar(self, sistema: str, usuario: str) -> str:
        self.llamadas.append((sistema, usuario))
        if self.error:
            raise self.error
        if callable(self.respuesta):
            return str(self.respuesta(sistema, usuario))
        if isinstance(self.respuesta, (dict, list)):
            return json.dumps(self.respuesta, ensure_ascii=False)
        return str(self.respuesta)


class ProveedorOpenAICompatible:
    """Proveedor mínimo compatible con `/chat/completions` (stdlib, sin SDK)."""

    def __init__(self, base_url: str, model: str, api_key: str, timeout: float = 20.0,
                 max_tokens: int = 700):
        if not base_url or not model or not api_key:
            raise CoachError("faltan COACH_BASE_URL, COACH_MODEL o COACH_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = float(timeout)
        self.max_tokens = int(max_tokens)

    def completar(self, sistema: str, usuario: str) -> str:
        url = self.base_url if self.base_url.endswith("/chat/completions") else \
            self.base_url + "/chat/completions"
        cuerpo = json.dumps({
            "model": self.model, "temperature": 0, "max_tokens": self.max_tokens,
            "messages": [{"role": "system", "content": sistema},
                         {"role": "user", "content": usuario}],
        }, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=cuerpo, method="POST", headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + self.api_key})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                datos = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise CoachError(f"fallo del proveedor: {exc}") from exc
        try:
            return str(datos["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise CoachError("el proveedor no devolvio choices[0].message.content") from exc


def activo_entorno() -> bool:
    """¿Está encendida y configurada la capa? Apagada por defecto; no construye nada."""
    flag = (os.environ.get("COACH_ENABLED") or "0").strip().lower()
    return (flag in ("1", "true", "si", "sí", "on", "yes")
            and bool((os.environ.get("COACH_API_KEY") or "").strip())
            and bool((os.environ.get("COACH_BASE_URL") or "").strip())
            and bool((os.environ.get("COACH_MODEL") or "").strip()))


def construir_desde_entorno() -> Proveedor | None:
    if not activo_entorno():
        return None
    return ProveedorOpenAICompatible(
        os.environ.get("COACH_BASE_URL", ""), os.environ.get("COACH_MODEL", ""),
        os.environ.get("COACH_API_KEY", ""),
        timeout=float(os.environ.get("COACH_TIMEOUT") or 20),
        max_tokens=int(os.environ.get("COACH_MAX_TOKENS") or 700))


# --------------------------------------------------------------------------- contexto mínimo

def _partes(rec: dict) -> tuple[dict, dict]:
    """Extrae la recomendación y la opción elegida del formato del motor."""
    if not isinstance(rec, dict):
        return {}, {}
    if isinstance(rec.get("primera"), dict):
        r = rec["primera"]
        elegida = rec.get("elegida") or {}
    elif isinstance(rec.get("recomendaciones"), list) and rec["recomendaciones"]:
        r = rec["recomendaciones"][0]
        elegida = next((o for o in r.get("opciones") or [] if o.get("recomendada")), {})
    else:
        r = rec
        elegida = next((o for o in r.get("opciones") or [] if o.get("recomendada")), {})
    return r, elegida


def _resumen(rec: dict) -> dict:
    """Resumen interno (puede contener textos locales); no se serializa ni se envía al proveedor."""
    r, elegida = _partes(rec)
    return {
        "prioridad": r.get("prioridad"), "problema": r.get("problema"),
        "estado": {k: (r.get("estado") or {}).get(k) for k in
                   ("clase", "confianza", "metros_actuales", "metros_minimos", "pct", "grado", "seccion_T")},
        "evidencia": list(r.get("evidencia") or []),
        "parametros": list(r.get("parametros") or []),
        "contraindicaciones": list(r.get("contraindicaciones") or []),
        "metrica_exito": dict(r.get("metrica_exito") or {}),
        "revisar_en": r.get("revisar_en"),
        "explicacion_determinista": r.get("explicacion") or "",
        "opcion": {k: elegida.get(k) for k in ("id", "sesion", "dia", "metros", "ritmo", "confianza",
                                               "riesgo_etiqueta", "coste_etiqueta", "score", "porque")},
    }


_CODIGO = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


def payload_minimo(rec: dict, conocimiento=None) -> dict:
    """Resumen público de la recomendación; nunca incluye FIT/GPX/partes ni conocimiento local.

    Sin `conocimiento` no se incluye ninguna referencia AF/FU/PA: no hay forma de comprobar que sea
    pública. Con `conocimiento` se filtran las referencias y se omiten los textos que puede haber
    generado el overlay local (`problema`, `sesion`, `porque`, `explicacion`).
    """
    raw = _resumen(rec)
    evidencias: list[str] = []
    parametros: list[str] = []
    if conocimiento is not None:
        publicas = {a.id for a in conocimiento.afirmaciones} | {f.id for f in conocimiento.fuentes}
        publicos = {p.id for p in conocimiento.parametros}
        evidencias = [x for x in raw["evidencia"] if isinstance(x, str) and x in publicas]
        parametros = [x for x in raw["parametros"] if isinstance(x, str) and x in publicos]
    contra = [x for x in raw["contraindicaciones"]
              if isinstance(x, str) and _CODIGO.match(x)]
    metrica = raw.get("metrica_exito") or {}
    tipo_metrica = metrica.get("tipo")
    return {
        "prioridad": raw["prioridad"],
        "estado": raw["estado"],
        "evidencia": evidencias,
        "parametros": parametros,
        "contraindicaciones": contra,
        "metrica_exito": {
            "tipo": tipo_metrica if isinstance(tipo_metrica, str) and _CODIGO.match(tipo_metrica) else "",
            "medir_en": metrica.get("medir_en"),
        },
        "revisar_en": raw["revisar_en"],
        "opcion": {k: raw["opcion"].get(k) for k in
                   ("id", "dia", "metros", "ritmo", "confianza", "riesgo_etiqueta",
                    "coste_etiqueta", "score")},
    }


def _citas_de(c: conocimiento_toml.Conocimiento):
    af = {a.id: a for a in c.afirmaciones}
    fu = {f.id: f for f in c.fuentes}
    pa = {p.id: p for p in c.parametros}
    return af, fu, pa


def _seleccionar_af(c: conocimiento_toml.Conocimiento, payload: dict) -> list:
    af, _, _ = _citas_de(c)
    elegidas = []
    for x in payload.get("evidencia") or []:
        if x in af and x not in [a.id for a in elegidas]:
            elegidas.append(af[x])
    if not elegidas:
        # Solo se usan clase/estado públicos; nunca `problema`, `sesion` ni `porque`, que pueden
        # venir del overlay local.
        palabras = {w for w in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúñ]{5,}", " ".join([
            str((payload.get("estado") or {}).get("clase") or ""),
            str((payload.get("opcion") or {}).get("id") or ""),
        ])).lower()}
        for a in c.afirmaciones:
            if any(w in (a.texto or "").lower() for w in palabras):
                elegidas.append(a)
            if len(elegidas) >= 5:
                break
    if not elegidas:
        # Conocimiento público mínimo: mejor una cita pública genérica que dejar el contexto sin
        # ninguna afirmación y romper el contrato de citas.
        elegidas = list(c.afirmaciones[:3])
    return elegidas[:6]


def contexto(cn, rec: dict, pregunta: str | None = None) -> dict:
    """Contexto determinista y acotado: recomendación + AF citadas/seleccionadas + FU + PA."""
    c = conocimiento_toml.cargar(incluir_local=False)
    payload = payload_minimo(rec, c)
    afirmaciones = _seleccionar_af(c, payload)
    fuentes = {}
    fu_ids = []
    for a in afirmaciones:
        for ref in a.fuentes:
            if ref.id in {f.id for f in c.fuentes}:
                fu_ids.append(ref.id)
                if ref.id not in fuentes:
                    f = next(x for x in c.fuentes if x.id == ref.id)
                    fuentes[ref.id] = {"id": f.id, "titulo": f.titulo, "url": f.url,
                                       "cita": ref.cita_local or f.cita}
    params = {p.id: p for p in c.parametros}
    parametros = []
    for pid in payload.get("parametros") or []:
        p = params.get(pid)
        if p:
            parametros.append({"id": p.id, "nombre": p.nombre, "valor": p.valor,
                               "unidad": p.unidad, "procedencia": p.procedencia})
    ctx = {
        "recomendacion": payload,
        "afirmaciones": [{"id": a.id, "texto": a.texto, "fuentes": [r.id for r in a.fuentes],
                          "estado": a.estado, "procedencia": a.procedencia} for a in afirmaciones],
        "fuentes": list(fuentes.values()),
        "parametros": parametros,
        "pregunta": (pregunta or "").strip()[:500],
        "citas": sorted({a.id for a in afirmaciones} | set(fu_ids)),
        "origenes": sorted({a.id for a in afirmaciones} | set(fu_ids) |
                           {p["id"] for p in parametros} | {"recomendacion"}),
    }
    # Números que el LLM puede usar: solo los del contexto/payload/parámetros.
    texto = json.dumps(ctx, ensure_ascii=False, sort_keys=True)
    ctx["numeros"] = sorted({n.replace(",", ".") for n in NUM.findall(texto)})
    ctx["texto"] = texto
    return ctx


SISTEMA = (
    "Eres un entrenador que explica una recomendacion ya calculada. No decides, no calculas y no "
    "inventas. Usa solo los datos del contexto. No des consejo medico ni prometas marcas. "
    "Devuelve exclusivamente JSON con las claves explicacion (texto), citas (lista de AF/FU), "
    "cifras (lista de {valor,unidad,origen}), avisos (lista) y confianza (baja|media|alta)."
)


def _normaliza_num(v) -> str:
    try:
        return (f"{float(v):g}").replace(",", ".")
    except (TypeError, ValueError):
        return str(v).replace(",", ".")


def _json_de(texto: str) -> dict:
    limpio = (texto or "").strip()
    limpio = re.sub(r"^```(?:json)?\s*", "", limpio, flags=re.I)
    limpio = re.sub(r"\s*```$", "", limpio)
    try:
        d = json.loads(limpio)
    except ValueError:
        m = re.search(r"\{.*\}", limpio, re.S)
        if not m:
            raise CoachError("la respuesta no es JSON")
        try:
            d = json.loads(m.group(0))
        except ValueError as exc:
            raise CoachError("la respuesta no es JSON valido") from exc
    if not isinstance(d, dict):
        raise CoachError("la respuesta no es un objeto JSON")
    return d


def _validar_texto(texto: str, ctx: dict, etiqueta: str, err: list[str]) -> None:
    if not isinstance(texto, str):
        err.append(f"{etiqueta} no es texto")
        return
    numeros = {_normaliza_num(n) for n in (ctx.get("numeros") or [])}
    for n in NUM.findall(texto):
        nn = n.replace(",", ".")
        if re.fullmatch(r"(19|20)\d\d", nn):
            continue
        if nn not in numeros:
            err.append(f"{etiqueta}: numero no presente en el contexto: {n}")
    if PROHIBIDO_MEDICO.search(texto):
        err.append(f"{etiqueta}: consejo medico")
    if PROHIBIDO_PROMESA.search(texto):
        err.append(f"{etiqueta}: promesa de marca")


def validar_respuesta(d: dict, ctx: dict) -> list[str]:
    """Valida contrato, citas, cifras y límites de seguridad. Lista vacía = válida."""
    err = []
    if not isinstance(d, dict):
        return ["no es un objeto"]
    for k in CAMPOS:
        if k not in d:
            err.append(f"falta {k}")
    exp = d.get("explicacion")
    if not isinstance(exp, str) or not exp.strip():
        err.append("explicacion vacia")
    citas = d.get("citas")
    if not isinstance(citas, list):
        err.append("citas no es lista")
        citas = []
    permitidas = set(ctx.get("citas") or [])
    for c in citas:
        if not isinstance(c, str) or not (c.startswith("AF-") or c.startswith("FU-")):
            err.append(f"cita no permitida: {c!r}")
        elif c not in permitidas:
            err.append(f"cita inexistente en el contexto: {c}")
    if not citas:
        err.append("faltan citas")
    cifras = d.get("cifras")
    if not isinstance(cifras, list):
        err.append("cifras no es lista")
        cifras = []
    numeros = {_normaliza_num(n) for n in (ctx.get("numeros") or [])}
    for c in cifras:
        if not isinstance(c, dict) or "valor" not in c or "origen" not in c:
            err.append("cifra incompleta")
            continue
        if _normaliza_num(c.get("valor")) not in numeros:
            err.append(f"cifra inventada: {c.get('valor')}")
        if str(c.get("origen")) not in set(ctx.get("origenes") or []):
            err.append(f"origen de cifra inexistente: {c.get('origen')}")
    avisos = d.get("avisos")
    if not isinstance(avisos, list):
        err.append("avisos no es lista")
        avisos = []
    if d.get("confianza") not in CONFIANZAS:
        err.append("confianza invalida")
    if isinstance(exp, str):
        _validar_texto(exp, ctx, "explicacion", err)
    for i, aviso in enumerate(avisos):
        _validar_texto(aviso, ctx, f"aviso {i}", err)
    for i, c in enumerate(cifras):
        if isinstance(c, dict) and c.get("unidad"):
            _validar_texto(str(c["unidad"]), ctx, f"unidad cifra {i}", err)
    return err


def fallback(rec: dict, ctx: dict | None = None, errores: list[str] | None = None,
             motivo: str = "sin proveedor") -> dict:
    """Explicación determinista: la del motor, con sus citas/cifras; nunca inventa."""
    p = _resumen(rec)
    exp = p.get("explicacion_determinista") or (
        f"Que veo: {p.get('problema') or 'sin prioridad'}. "
        f"Que propongo: {(p.get('opcion') or {}).get('sesion') or 'mantener'}. "
        f"Revision: {p.get('revisar_en') or '—'}."
    )
    citas = [x for x in (p.get("evidencia") or []) if str(x).startswith(("AF-", "FU-"))]
    cifras = []
    metros = (p.get("opcion") or {}).get("metros")
    if metros is not None:
        cifras.append({"valor": metros, "unidad": "m", "origen": "recomendacion"})
    for pa in (p.get("parametros") or []):
        if ctx:
            for x in ctx.get("parametros") or []:
                if x.get("id") == pa:
                    cifras.append({"valor": x.get("valor"), "unidad": x.get("unidad") or "",
                                   "origen": x.get("id")})
    return {"ok": True, "fuente": "determinista", "explicacion": exp, "citas": citas,
            "cifras": cifras, "avisos": ["explicacion determinista del motor"], "confianza": "media",
            "validacion": list(errores or []), "motivo": motivo,
            "contexto": {"afirmaciones": len((ctx or {}).get("afirmaciones") or []),
                         "fuentes": len((ctx or {}).get("fuentes") or []),
                         "parametros": len((ctx or {}).get("parametros") or [])}}


def explicar(cn, rec: dict, pregunta: str | None = None, proveedor: Proveedor | None = None,
             activo: bool | None = None) -> dict:
    """Explica una recomendación. Si no hay proveedor o la respuesta no vale, fallback determinista."""
    activo = activo_entorno() if activo is None else bool(activo)
    if not activo or proveedor is None:
        return fallback(rec, None, ["capa LLM apagada o sin proveedor"], "apagado")
    ctx = contexto(cn, rec, pregunta)
    usuario = json.dumps({"contexto": ctx, "pregunta": ctx.get("pregunta") or ""},
                         ensure_ascii=False, sort_keys=True)
    try:
        texto = proveedor.completar(SISTEMA, usuario)
        d = _json_de(texto)
        errores = validar_respuesta(d, ctx)
    except Exception as exc:
        return fallback(rec, ctx, [str(exc)], "error del proveedor")
    if errores:
        return fallback(rec, ctx, errores, "respuesta no valida")
    return {"ok": True, "fuente": "llm", "explicacion": d["explicacion"], "citas": d["citas"],
            "cifras": d["cifras"], "avisos": d.get("avisos") or [], "confianza": d["confianza"],
            "validacion": [], "contexto": {"afirmaciones": len(ctx["afirmaciones"]),
                                           "fuentes": len(ctx["fuentes"]),
                                           "parametros": len(ctx["parametros"])}}
