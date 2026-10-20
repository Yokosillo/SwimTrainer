# ADR-003 — Capa LLM opcional para explicar recomendaciones

- **Estado:** aceptada (F8), apagada por defecto.
- **Contexto:** F5/F7 ya producen una recomendación determinista con prioridad, opciones, evidencia,
  parámetros, métrica y revisión. El atleta pide una explicación más conversacional, pero el motor no
  puede delegar decisiones, cálculos ni cifras en un modelo generativo.

## Decisión

Añadir una capa **opcional** de explicación, solo backend, que reformule una recomendación ya calculada.
No decide, no puntúa, no calcula y no crea sesiones. Si falla, se usa la explicación determinista.

### Proveedor

- Interfaz compatible con OpenAI (`POST /chat/completions`), implementada con `urllib` de la stdlib.
- Variables: `COACH_ENABLED`, `COACH_BASE_URL`, `COACH_MODEL`, `COACH_API_KEY`.
- `COACH_ENABLED=0` por defecto. Si falta la clave, la URL o el modelo, la capa queda apagada.
- No se reutilizan credenciales de OpenCode Go. La clave vive solo en `.env`/entorno del servidor;
  nunca se envía al navegador ni al repositorio.

### Datos que se envían

- La recomendación resumida: prioridad, problema, estado mínimo, opción recomendada, evidencia,
  parámetros y métrica.
- Afirmaciones `AF-*` citadas (o seleccionadas por palabras clave) y sus fuentes `FU-*`, con citas.
- Parámetros `PA-*` usados por la recomendación.

### Datos que NO se envían

- FIT, GPX, la base SQLite, partes completas, notas personales, nombre/club, historial de actividades,
  credenciales de Garmin/Strava/OpenCode ni `conocimiento/local`.
- No se envían vectores ni documentos completos: solo el contexto acotado de la recomendación.

### Retención y coste

- El proveedor puede retener la petición según su política; se documenta en el contrato del proveedor
  elegido. El proyecto no guarda prompts/respuestas del LLM en la base por defecto.
- Coste acotado por `COACH_MAX_TOKENS` y una sola llamada por acción; sin llamadas automáticas.
- `COACH_TIMEOUT` limita la latencia; si se supera, fallback determinista.

## Contrato de salida

```json
{
  "explicacion": "texto",
  "citas": ["AF-...", "FU-..."],
  "cifras": [{"valor": 0, "unidad": "...", "origen": "PA-..."}],
  "avisos": [],
  "confianza": "baja|media|alta"
}
```

Validadores: JSON, citas existentes en el contexto, cifras presentes en el contexto, sin consejo médico
y sin promesas de marca. Si falla, se devuelve la explicación determinista y se registra el motivo.

## Fallback

- Flag apagado, sin clave, timeout, error del proveedor o respuesta inválida → explicación determinista
  del motor.
- El endpoint `/coach` devuelve 403 si la capa está apagada; el panel no muestra el botón.
- El endpoint exige la autenticación normal del servidor local; la clave del proveedor no viaja al
  navegador.

## Consecuencias

- La interfaz F7 sigue funcionando igual con `COACH_ENABLED=0`; el golden F7 no cambia.
- El LLM es una ayuda de lectura, no una fuente de verdad. La decisión, la puntuación y la verificación
  siguen siendo deterministas.
