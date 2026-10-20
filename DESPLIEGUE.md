# Despliegue con Docker

La aplicacion se empaqueta en una imagen con el codigo y las dependencias. **Los datos no van
dentro de la imagen**: la base SQLite, los FIT de Garmin, los informes y el HTML generado se
montan desde el disco. Asi se puede reconstruir la imagen sin tocar el historial del atleta.

```
navegador
   │  https://dalmacia/entrenador/   (Tailscale)  o  http://dalmacia/entrenador/  (LAN)
   ▼
Caddy (:80)  ──  /entrenador/*  ──►  127.0.0.1:8181  (contenedor)
                                         │
                                         ├── /app/data/entrenador.db   (host: data/)
                                         ├── /app/informes/            (host: informes/)
                                         └── /app/cuadro/              (host: cuadro/)
```

El contenedor escucha en `0.0.0.0:8181`, pero el puerto se publica **solo en `127.0.0.1`** para que
no quede abierto a la red sin pasar por Caddy. El servidor pide usuario y contrasenia (HTTP Basic)
cuando existe `ENTRENADOR_CLAVE`; `/salud` queda libre para el *healthcheck*.

## 1. Preparar los datos

En esta maquina los datos personales estan en `../SwimTrainer-personal/`. La primera vez hay que
dejarlos en el proyecto, que es donde el contenedor los monta:

```bash
cd <ruta-del-proyecto>/SwimTrainer
mkdir -p data informes cuadro
cp -a ../SwimTrainer-personal/data/.  data/
cp -a ../SwimTrainer-personal/informes/. informes/
```

`data/`, `informes/` y `cuadro/` estan en `.gitignore`: no se suben nunca al repositorio publico.
Si se parte de cero, el arranque crea una base vacia con `cli init`.

El plan personal y el perfil tambien son privados. Se copian desde el repositorio privado:

```bash
cp -a ../SwimTrainer-personal/entrenador/plan_local.py entrenador/
cp -a ../SwimTrainer-personal/entrenador/perfil_local.py entrenador/ 2>/dev/null || true
mkdir -p conocimiento/local
cp -a ../SwimTrainer-personal/conocimiento/local/. conocimiento/local/
```

Sin `plan_local.py` la aplicacion arranca igual, pero con el plan vacio. Sin
`conocimiento/local/`, el motor v2 usa solo el conocimiento publico.

## 2. Contrasenia

```bash
cp .env.example .env
chmod 600 .env
sed -i "s/^ENTRENADOR_CLAVE=.*/ENTRENADOR_CLAVE=$(openssl rand -hex 24)/" .env
```

`.env` tambien lleva el UID/GID del usuario dueno de `data/`, `informes/` y `cuadro/`:

```bash
id -u   # 1001 en dalmacia
id -g   # 1001
```

Sin `ENTRENADOR_CLAVE` el servidor queda abierto. Eso solo vale para `127.0.0.1` en el PC de casa;
nunca detras de Caddy ni en red.

## 3. Construir y arrancar

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f entrenador
```

El arranque hace tres cosas: crea la base si no existe, rehace `cuadro/panel.html` (y el portal de
bici) con los datos de la base y levanta el servidor. En el Celeron de dalmacia puede tardar uno o
dos minutos; el *healthcheck* da tres minutos de margen.

Para no rehacer el portal de bici en cada arranque (es la parte mas lenta), en `.env`:

```
ENTRENADOR_PORTAL_BICI=0
```

y generarlo cuando haga falta:

```bash
docker compose exec entrenador python -m entrenador.cli portal \
    --destino /app/cuadro/strava/index.html
```

### Datos privados dentro de la imagen local

La imagen `entrenador:local` se construye en esta maquina y **no se publica**. El `Dockerfile` copia
`entrenador/` completo y `conocimiento/` completo, asi que `entrenador/perfil_local.py`,
`entrenador/plan_local.py` y `conocimiento/local/` (privados y en `.gitignore`) van dentro de la
imagen. No se sube a ningun registro ni se comparte.

Si algun dia se publica o se comparte la imagen, hay que reconstruirla sin esos dos ficheros o
montarlos como volumen de solo lectura. Sin `plan_local.py` la app arranca igual: el plan queda vacio
(`plan.SEMANAS == []`) y el panel no muestra plan; sin `perfil_local.py` el panel no lleva nombre; sin
`conocimiento/local/` el motor v2 usa solo el conocimiento publico y avisa.

### Version de los motores

La bandera `MOTOR_CONOCIMIENTO` elige que motor de conocimiento usa la aplicacion. Desde F9 el valor
por defecto es `v2` (TOML); `v1` recupera las constantes historicas para rollback y `dual` compara
ambos sin cambiar el resultado. Un valor desconocido cae a `v2`: la bandera no puede dejar el sistema
sin motor. Se lee en un unico sitio (`conocimiento.motor_version()`).

`MOTOR_RECOMENDACION` elige el motor de recomendaciones: `v2` (por defecto desde F9), `v1` (rollback)
o `dual` (compara sin escribir). El panel muestra la tarjeta de v2 solo cuando esta activo.

```bash
# en .env
MOTOR_CONOCIMIENTO=v2
MOTOR_RECOMENDACION=v2
```

Rollback: poner ambas en `v1`, reconstruir la imagen con el commit anterior si hace falta y reiniciar.
Las tablas nuevas son aditivas y v1 las ignora; no hay que restaurar la base salvo corrupcion.

## 3b. Capa LLM opcional (F8)

La explicación conversacional está **apagada por defecto**. No decide ni calcula: solo reformula una
recomendación ya calculada. Para activarla, rellena en `.env` (nunca en el navegador):

```bash
COACH_ENABLED=1
COACH_BASE_URL=https://proveedor-compatible/v1
COACH_MODEL=modelo
COACH_API_KEY=...
# opcionales
COACH_TIMEOUT=20
COACH_MAX_TOKENS=700
COACH_MAX_LLAMADAS_MINUTO=5
```

Sin `COACH_API_KEY`, sin URL/modelo o con `COACH_ENABLED=0`, el endpoint `/coach` responde 403 y el
botón no aparece. El límite `COACH_MAX_LLAMADAS_MINUTO` (5 por defecto) es local y en proceso; no
expongas `/coach` sin autenticación/proxy. Los datos enviados se limitan a la recomendación resumida, sus `AF-*`, `FU-*` y
`PA-*`; no se envían FIT/GPX, la base, partes completas ni datos personales. Si el proveedor falla o la
respuesta no valida, se usa la explicación determinista del motor. Ver
`docs/adr/ADR-003-llm-capa-opcional.md`.

## 4. Caddy (`/entrenador/`)

Caddy ya escucha en `:80` en dalmacia. La ruta se activa cuando existe
`/srv/entrenador/entrenador/cli.py`. Para no duplicar el proyecto, se deja un enlace al directorio
de trabajo:

```bash
sudo ln -sfn <ruta-del-proyecto>/SwimTrainer /srv/entrenador
```

En el `Caddyfile`, ademas del bloque que ya genera `dalmacia-f1-web.sh`:

```caddyfile
redir /entrenador /entrenador/ 308

handle_path /entrenador/* {
    reverse_proxy 127.0.0.1:8181
}
```

El `handle_path` quita el prefijo, asi que la aplicacion recibe `/`, `/partes`, `/gimnasio`... tal
como espera. El JS del panel arma las llamadas con la ruta actual (`urlApi`), por eso funciona igual
en `/entrenador/` que abierto como fichero en el PC.

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Acceso:

- Tailnet: `https://dalmacia.<tailnet>.ts.net/entrenador/` (HTTPS, recomendado).
- LAN: `http://dalmacia/entrenador/` (Basic auth viaja sin cifrar; usar solo en casa).

## 5. Garmin Connect (opcional)

El token OAuth vive en `~/.garminconnect`, montado en `./.garminconnect`. El primer login se hace
dentro del contenedor, con una terminal interactiva (pide correo, contrasenia y MFA; no se guardan):

```bash
docker compose run --rm entrenador sh -lc \
  'python scripts/garmin_conectar.py login'
```

Despues, el boton *Traer lo nuevo del Garmin* del panel usa ese token. Si caduca, se repite el login.

## 6. Actualizar

```bash
cd <ruta-del-proyecto>/SwimTrainer
git pull
docker compose up -d --build
```

Los datos y los informes no se tocan: estan fuera de la imagen.

## 7. Copia de seguridad

Con el contenedor parado, o con la copia consistente de SQLite:

```bash
docker compose exec entrenador python -c \
  "import sqlite3; a=sqlite3.connect('/app/data/entrenador.db'); b=sqlite3.connect('/app/data/copia.db'); a.backup(b); b.close()"
docker compose cp entrenador:/app/data/copia.db ./entrenador-$(date +%F).db
```

## 8. Problemas frecuentes

- **El healthcheck tarda**: el primer arranque genera el panel y el portal de bici. Mirar
  `docker compose logs -f entrenador`; el margen es de 3 minutos.
- **Permisos en `data/`**: el UID/GID de `.env` tiene que ser el dueno de esas carpetas. Se corrige
  con `sudo chown -R $(id -u):$(id -g) data informes cuadro` y `docker compose up -d --build`.
- **401 en el navegador**: usuario y contrasenia de `.env`; el navegador puede cachear las
  credenciales antiguas (probar en ventana privada).
- **Puerto 8181 ocupado**: `ss -ltnp | grep 8181`. El contenedor publica solo en `127.0.0.1`; si hay
  otro proceso, pararlo o cambiar el puerto en `docker-compose.yml` y el proxy.
- **Garmin pide renovar la sesion**: repetir el login del punto 5.
