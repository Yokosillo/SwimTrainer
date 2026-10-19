# Entrenador: la aplicacion en un contenedor.
#
# La imagen lleva el codigo y las dependencias; los datos NO. La base SQLite, los FIT y los
# informes se montan desde el disco de la maquina (ver docker-compose.yml): son personales y
# tienen que sobrevivir a cualquier reconstruccion de la imagen.

FROM python:3.12-slim

ARG UID=1001
ARG GID=1001

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Madrid \
    ENTRENADOR_HOST=0.0.0.0 \
    ENTRENADOR_PUERTO=8181

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# El usuario del contenedor tiene el mismo UID/GID que el usuario del host para que pueda
# escribir en `data/`, `informes/` y `cuadro/` sin dejar ficheros de root.
RUN groupadd --gid "${GID}" entrenador \
    && useradd --uid "${UID}" --gid "${GID}" --create-home --shell /usr/sbin/nologin entrenador

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY entrenador ./entrenador
COPY scripts ./scripts
COPY pruebas ./pruebas
COPY README.md DESPLIEGUE.md ./

COPY docker/entrada.sh /usr/local/bin/entrada.sh
RUN chmod 0755 /usr/local/bin/entrada.sh \
    && mkdir -p /app/data /app/informes /app/cuadro \
    && chown -R entrenador:entrenador /app

USER entrenador

EXPOSE 8181

HEALTHCHECK --interval=30s --timeout=5s --start-period=3m --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8181/salud', timeout=3)"

ENTRYPOINT ["/usr/local/bin/entrada.sh"]
