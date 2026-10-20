# Postmortem — F9 (despliegue y cierre)

- **Fecha:** 2026-10-20
- **Alcance:** cierre del plan de conocimiento (F0–F9).
- **Estado:** v2 por defecto; rollback probado; capa LLM apagada.

## 1. Qué se ha cerrado

- Conocimiento TOML como fuente de verdad, con overlay privado separado.
- Motor de recomendación v2 con prioridades, opciones, scoring y restricciones duras.
- Estado del atleta, bucle de resultados, panel de decisión y explorador de conocimiento.
- Explicación LLM opcional, apagada por defecto, con payload público y fallback determinista.
- Activación de v2 por defecto, golden `f9`, rollback documentado y probado.
- Dual-run de 14 días sobre la base real: 0 regresiones y 0 errores de clasificación.

## 2. Qué ha funcionado

- El dual-run histórico permitió comparar v1/v2 sin esperar dos semanas y sin tocar la base.
- La separación público/local evitó que el conocimiento personal saliera en el payload del LLM.
- El golden normalizado por fecha evitó falsos cambios por el día de ejecución.
- El flag `v1` permite volver atrás sin migración inversa: las tablas nuevas son aditivas.

## 3. Qué no ha funcionado o queda abierto

1. **Observación en vivo:** el dual-run de F9-01 es una ventana histórica de 14 días, no dos semanas
   de uso real. Es el residual más importante.
2. **Firmas:** 0/40 criterios firmados. El motor funciona, pero el conocimiento propuesto sigue sin
   la firma del entrenador/atleta.
3. **Verificación de reglas:** 0/9 reglas con verificación en la base real. El bucle existe; faltan
   recomendaciones aceptadas y medidas después de 21 días.
4. **Panel sin autenticación:** decisión explícita del operador para uso doméstico. Está mitigado por
   `127.0.0.1` + Caddy; no debe exponerse directamente a Internet.
5. **Capa LLM:** no se ha probado con un proveedor real. Se ha validado el contrato, el fallback y el
   saneamiento del payload con `ProveedorFalso`.
6. **Datos derivados:** `data/`, `informes/`, `cuadro/` y los snapshots golden son privados y no se
   publican. La imagen Docker local contiene `plan_local.py` y `conocimiento/local/`; no se sube a un
   registro público.

## 4. Decisiones

- Activar v2 por defecto después de que las métricas técnicas del dual-run pasaran, dejando v1 como
  rollback inmediato.
- No falsear las métricas de gobernanza ni sembrar recomendaciones/verificaciones artificiales en la
  base real.
- Mantener `COACH_ENABLED=0`: la capa LLM no es necesaria para el núcleo y no se ha usado una cuenta
  real.
- Mantener el panel sin contraseña por decisión del operador, con escucha solo local.

## 5. Backlog priorizado

| Prioridad | Tarea | Criterio de cierre |
|---|---|---|
| P0 | Repetir el dual-run durante dos semanas de uso real | Informe con 0 regresiones y métricas técnicas al 100 % |
| P0 | Guardar y evaluar recomendaciones v2 reales | ≥80 % evaluadas a 21 días, sin inventar veredictos |
| P1 | Firmar los criterios del anexo T | ≥80 % de criterios firmados por entrenador/atleta |
| P1 | Verificar reglas con medidas reales | ≥80 % de reglas con al menos una verificación |
| P2 | Probar la capa LLM con un proveedor real y clave propia | Coste/latencia dentro del umbral y fallback probado |
| P2 | Revisar el aviso de alternativa sin día libre | La descarga sin sesión se entiende y no se confunde con una sesión |
| P3 | Publicar la rama y los tags cuando el operador lo autorice | Historial sin datos personales y CI en verde |

## 6. Riesgos residuales

- **R-01 (matices perdidos):** mitigado con dual-run y golden; queda la observación en vivo.
- **R-03 (alucinación LLM):** mitigado con contrato, citas y fallback; capa apagada.
- **R-04 (fuga de datos):** mitigado con payload público y sin `conocimiento/local`; el fallback local
  puede mostrar IDs locales al panel, que ya es privado.
- **R-05 (corrupción de DB):** no se ha restaurado ni migrado la base real en F9; las pruebas usan
  bases temporales. Mantener backup antes de cualquier migración.
- **R-08 (sobreajuste):** el conocimiento local sigue siendo del atleta actual; el público es genérico.
- **R-11 (coste/latencia LLM):** sin proveedor real no se puede medir; límites locales ya existen.
