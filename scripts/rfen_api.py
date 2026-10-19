"""Cliente minimo para hablar con la RFEN (natacion.rfen.es y su API).

Problema conocido (11/10/2026): natacion.rfen.es pide renegociacion TLS (legacy) y con eso
curl (schannel) y el navegador automatizado se quedan colgados sin respuesta. Python usa
OpenSSL: hay que activar SSL_OP_LEGACY_SERVER_CONNECT (0x4) o la conexion se corta.

Uso:
    python scripts/rfen_api.py get <url> [url2 ...]
    python scripts/rfen_api.py json <url> [url2 ...]
"""

import gzip
import http.client
import json
import ssl
import sys
import urllib.parse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
SSL_OP_LEGACY_SERVER_CONNECT = 0x4


def _ctx():
    c = ssl.create_default_context()
    c.options |= SSL_OP_LEGACY_SERVER_CONNECT
    return c


def fetch(url, timeout=25, headers=None, method="GET", body=None):
    """Devuelve (status, cabeceras, bytes). Sin seguir redirecciones."""
    p = urllib.parse.urlsplit(url)
    host = p.hostname
    port = p.port or (443 if p.scheme == "https" else 80)
    path = urllib.parse.urlunsplit(("", "", p.path or "/", p.query, ""))
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip", "Connection": "close"}
    h.update(headers or {})
    if p.scheme == "https":
        conn = http.client.HTTPSConnection(host, port, context=_ctx(), timeout=timeout)
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read()
    if r.getheader("Content-Encoding") == "gzip":
        try:
            data = gzip.decompress(data)
        except Exception:
            pass
    ch = dict(r.getheaders())
    conn.close()
    return r.status, ch, data


def fetch_text(url, **kw):
    st, h, b = fetch(url, **kw)
    try:
        txt = b.decode("utf-8", "replace")
    except Exception:
        txt = ""
    return st, h, txt


def get(*urls):
    for u in urls:
        try:
            st, h, txt = fetch_text(u)
            print("=" * 78)
            print(u, "->", st, h.get("Content-Type", ""), len(txt), "chars")
            print(txt[:900].replace("\n", " ")[:900])
        except Exception as e:
            print("=" * 78)
            print(u, "-> ERROR", type(e).__name__, e)


def get_json(*urls):
    for u in urls:
        try:
            st, h, txt = fetch_text(u, headers={"Accept": "application/json"})
            print("=" * 78)
            print(u, "->", st, h.get("Content-Type", ""), len(txt), "chars")
            try:
                print(json.dumps(json.loads(txt), ensure_ascii=False)[:1200])
            except Exception:
                print(txt[:600])
        except Exception as e:
            print("=" * 78)
            print(u, "-> ERROR", type(e).__name__, e)


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "get"
    urls = sys.argv[2:]
    (get_json if modo == "json" else get)(*urls)
