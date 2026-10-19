"""Espia un Chrome abierto por CDP: que pide, que le responden y que se ve en pantalla.

Para que sirve: encontrar la API que usa una web (URL exacta y cabeceras, incluido el token) sin
adivinar, y leer el texto de la pestana cuando la web solo se deja ver en un navegador de verdad.

Requiere un Chrome arrancado con --remote-debugging-port=9222 y un --user-data-dir propio.

Uso:
    python scripts/cdp_captura.py --pestanas
    python scripts/cdp_captura.py --texto
    python scripts/cdp_captura.py --url https://... --segundos 40
"""

import argparse
import asyncio
import json
import re
import urllib.request

PUERTO = 9222


def _json(path):
    url = "http://127.0.0.1:%d%s" % (PUERTO, path)
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def pestanas():
    return [t for t in _json("/json") if t.get("type") == "page"]


def listar():
    for t in pestanas():
        print("%-38s %s" % (t.get("title", "")[:38], t.get("url", "")[:110]))
        print("   ws: %s" % t.get("webSocketDebuggerUrl"))


class Espia:
    """Cliente CDP minimo sobre websockets."""

    def __init__(self, ws):
        self.ws = ws
        self.n = 0
        self.pendientes = {}

    async def enviar(self, method, **params):
        self.n += 1
        self.pendientes[self.n] = (method, params)
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        return self.n

    async def recibir(self, timeout=5.0):
        try:
            msg = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        return json.loads(msg)


CAB = re.compile(r"authorization|cookie|x-api|api-key|token", re.I)


async def capturar(url, segundos, volcar_texto, filtro):
    objetivo = None
    for t in pestanas():
        if not filtro or filtro in t.get("url", ""):
            objetivo = t
            break
    if objetivo is None:
        print("no hay pestana que encaje (usa --pestanas para verlas)")
        return
    import websockets

    peticiones = {}
    respuestas = {}
    cuerpos = {}
    fallos = []
    textos = {}
    async with websockets.connect(objetivo["webSocketDebuggerUrl"], max_size=None) as ws:
        e = Espia(ws)
        await e.enviar("Network.enable")
        await e.enviar("Page.enable")
        await e.enviar("Runtime.enable")
        if url:
            await e.enviar("Page.navigate", url=url)
        fin = asyncio.get_event_loop().time() + segundos
        while True:
            restante = fin - asyncio.get_event_loop().time()
            if restante <= 0:
                break
            ev = await e.recibir(timeout=min(restante, 5.0))
            if ev is None:
                continue
            m = ev.get("method")
            p = ev.get("params") or {}
            if m == "Network.requestWillBeSent":
                r = p.get("request") or {}
                peticiones[p.get("requestId")] = {
                    "url": r.get("url"), "metodo": r.get("method"),
                    "tipo": p.get("type"), "cabeceras": r.get("headers") or {},
                    "post": r.get("postData"),
                }
            elif m == "Network.responseReceived":
                r = p.get("response") or {}
                respuestas[p.get("requestId")] = {
                    "url": r.get("url"), "estado": r.get("status"),
                    "mime": r.get("mimeType"),
                }
                if re.search(r"api|json", (r.get("url") or "") + (r.get("mimeType") or ""), re.I):
                    idx = await e.enviar("Network.getResponseBody", requestId=p.get("requestId"))
                    textos[idx] = p.get("requestId")
            elif m == "Network.loadingFailed":
                fallos.append((p.get("requestId"), p.get("errorText")))
            elif m == "Runtime.consoleAPICalled":
                pass
            elif "id" in ev and ev.get("id") in textos:
                rid = textos.pop(ev["id"])
                res = ev.get("result") or {}
                if res.get("body"):
                    cuerpos[rid] = res["body"][:4000]

    print("== pestana:", objetivo.get("url", "")[:120])
    print("== peticiones:", len(peticiones), " respuestas:", len(respuestas), " fallos:", len(fallos))
    api = [v for v in peticiones.values() if re.search(r"api|graphql", v["url"] or "", re.I)]
    print("\n== peticiones a APIs (%d) ==" % len(api))
    for v in api:
        print("\n   %s %s   [%s]" % (v["metodo"], v["url"], v["tipo"]))
        for k, val in v["cabeceras"].items():
            if CAB.search(k):
                print("      %s: %s" % (k, str(val)[:160]))
        r = respuestas.get(next((k for k, x in peticiones.items() if x is v), None)) or {}
        if r:
            print("      -> %s %s" % (r.get("estado"), (r.get("mime") or "")[:40]))
    if cuerpos:
        print("\n== cuerpos JSON capturados (%d) ==" % len(cuerpos))
        for rid, txt in list(cuerpos.items())[:6]:
            u = (respuestas.get(rid) or {}).get("url", "?")
            print("\n   %s\n      %s" % (u[:130], txt[:700].replace("\n", " ")))
    if fallos:
        print("\n== fallos ==")
        for rid, err in fallos[:12]:
            u = (peticiones.get(rid) or {}).get("url", "?")
            print("   %-60s %s" % (u[:60], err))
    if volcar_texto:
        await e.enviar("Page.navigate", url="about:blank") if False else None
        idx = await e.enviar("Runtime.evaluate", expression="document.body.innerText.slice(0,4000)",
                             returnByValue=True)
        txt = None
        for _ in range(20):
            ev = await e.recibir(timeout=3.0)
            if ev and ev.get("id") == idx:
                txt = ((ev.get("result") or {}).get("result") or {}).get("value")
                break
        print("\n== texto visible ==")
        print(txt or "(vacio)")


def texto():
    async def _() -> object:
        for t in pestanas():
            import websockets
            async with websockets.connect(t["webSocketDebuggerUrl"], max_size=None) as ws:
                e = Espia(ws)
                await e.enviar("Runtime.enable")
                idx = await e.enviar("Runtime.evaluate",
                                     expression="document.body.innerText.slice(0,6000)",
                                     returnByValue=True)
                for _ in range(20):
                    ev = await e.recibir(timeout=3.0)
                    if ev and ev.get("id") == idx:
                        val = ((ev.get("result") or {}).get("result") or {}).get("value")
                        print("== %s\n%s" % (t.get("url", "")[:110], val or "(vacio)"))
                        return
    asyncio.run(_())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pestanas", action="store_true")
    ap.add_argument("--texto", action="store_true")
    ap.add_argument("--url")
    ap.add_argument("--filtro", default="")
    ap.add_argument("--segundos", type=int, default=30)
    a = ap.parse_args()
    if a.pestanas:
        listar()
    elif a.texto:
        texto()
    else:
        asyncio.run(capturar(a.url, a.segundos, True, a.filtro))
