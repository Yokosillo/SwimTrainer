# ADR-004 — Activar v2 por defecto y conservar el rollback

- **Estado:** aceptada (F9).
- **Contexto:** F3 dejó el conocimiento TOML y el adaptador v1/v2 listos; F5 añadió el motor de
  recomendación v2; F6/F7/F8 cerraron el bucle de resultados, la interfaz y la capa LLM opcional. El
  dual-run de F9 no encontró regresiones ni errores y el golden `f9` es estable. Toca pasar v2 a
  producción sin perder la vuelta atrás.

## Decisión

1. `MOTOR_CONOCIMIENTO` vale `v2` por defecto: `estimulos`, `reglas` y `planificador` leen el TOML
   público + local. Un valor vacío o desconocido cae a `v2`.
2. `MOTOR_RECOMENDACION` vale `v2` por defecto: el panel y las integraciones usan prioridades,
   opciones y scoring de v2. `dual` sigue disponible para comparar sin escribir.
3. `v1` sigue siendo un valor válido de ambas banderas. El rollback es cambiar las dos variables a
   `v1` y reiniciar; no requiere migración inversa ni restauración de la base.
4. `COACH_ENABLED` sigue en `0`. Activar v2 no enciende la capa LLM ni envía datos a ningún proveedor.

## Consecuencias

- El panel muestra la tarjeta de prioridad/acción de v2 y el plan semanal sigue siendo la referencia
  de volumen.
- Las tablas nuevas (`recomendacion`, `recomendacion_opcion`, `verificacion`, conocimiento TOML) son
  aditivas. v1 las ignora.
- El golden de referencia pasa a `f9`; `f1`, `f3`, `f4`, `f6` y `f7` quedan como referencias
  históricas de sus fases.
- Si el dual-run o un uso real muestra una regresión, se vuelve a `v1` sin borrar datos y se investiga
  con el informe `data/derived/f9/dual_run_*.json`.
- Las métricas de gobernanza (firmas de criterios y reglas con verificación) siguen pendientes y se
  registran en el postmortem; no bloquean el rollback técnico.
