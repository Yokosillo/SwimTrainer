#!/bin/sh
# Arranque del contenedor del Entrenador.
#
# 1. Se asegura de que la base existe.
# 2. Rehace el cuadro de mando (y, si se quiere, el portal de bici) con lo que hay en la base.
# 3. Sirve el panel y la API en 0.0.0.0:8181; delante va Caddy (o el proxy que haya).
#
# Variables:
#   ENTRENADOR_BD             ruta de SQLite (por defecto /app/data/entrenador.db)
#   ENTRENADOR_REGENERAR      1 = rehacer el cuadro al arrancar (por defecto 1)
#   ENTRENADOR_PORTAL_BICI    1 = escribir tambien el portal de bici (por defecto 1)
#   ENTRENADOR_HOST/PUERTO    donde escucha el servidor (0.0.0.0:8181 por defecto)

set -eu

CARPETA=/app
BD="${ENTRENADOR_BD:-$CARPETA/data/entrenador.db}"
REGENERAR="${ENTRENADOR_REGENERAR:-1}"
PORTAL_BICI="${ENTRENADOR_PORTAL_BICI:-1}"

mkdir -p "$(dirname "$BD")" "$CARPETA/data/derived" "$CARPETA/cuadro" "$CARPETA/informes"

if [ ! -f "$BD" ]; then
    echo "[entrada] no hay base en $BD: creando el esquema"
    python -m entrenador.cli --bd "$BD" init
fi

if [ "$REGENERAR" = "1" ] || [ ! -f "$CARPETA/cuadro/panel.html" ]; then
    echo "[entrada] generando el cuadro de mando..."
    python -m entrenador.cli --bd "$BD" analizar --carpeta "$CARPETA"
else
    echo "[entrada] cuadro de mando ya generado (ENTRENADOR_REGENERAR=0)"
fi

if [ "$PORTAL_BICI" = "1" ] || [ ! -f "$CARPETA/cuadro/strava/index.html" ]; then
    echo "[entrada] generando el portal de bici..."
    # No es imprescindible para arrancar: si falla, se avisa y el panel sigue funcionando.
    python -m entrenador.cli --bd "$BD" portal \
        --destino "$CARPETA/cuadro/strava/index.html" \
        || echo "[entrada] aviso: no se pudo generar el portal de bici"
else
    echo "[entrada] portal de bici ya generado (ENTRENADOR_PORTAL_BICI=0)"
fi

echo "[entrada] sirviendo en ${ENTRENADOR_HOST:-0.0.0.0}:${ENTRENADOR_PUERTO:-8181}"
exec python -m entrenador.cli --bd "$BD" servir \
    --host "${ENTRENADOR_HOST:-0.0.0.0}" \
    --puerto "${ENTRENADOR_PUERTO:-8181}" \
    --carpeta "$CARPETA"
