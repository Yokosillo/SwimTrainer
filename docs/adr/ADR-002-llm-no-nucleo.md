# ADR-002 — El LLM es una capa opcional de lenguaje, nunca el núcleo de decisión

- **Estado:** aceptado; **firma del entrenador pendiente** (R-07)
- **Fecha:** 2026-10-19
- **Fase:** F0 (decisión); se implementa, si se implementa, en F8
- **Decisores:** proyecto Entrenador
- **Firma:** pendiente del entrenador; no hay firma registrada todavía.

## Contexto

El sistema debe decidir qué entrenar y por qué, con números trazables. Un LLM puede ayudar a
explicar, conversar y extraer afirmaciones de documentos, pero también puede:

- inventar cifras o citas;
- dar consejo médico;
- filtrar datos personales de salud a un tercero;
- no ser reproducible (misma entrada, salida distinta);
- costar dinero y latencia en un Celeron.

El plan fija los invariantes INV-03 (toda recomendación con respaldo), INV-05 (los números se
calculan, no se generan con LLM), INV-06 (reproducibilidad), INV-07 (migraciones aditivas) e
INV-09 (privacidad por defecto). Un LLM en el núcleo rompería varios a la vez.

## Decisión

El LLM es una **capa opcional**, apagada por defecto (`COACH_ENABLED=0`), y nunca decide carga ni
seguridad. Usos permitidos:

| Uso | ¿LLM? | Condición |
|---|---|---|
| Explicar una recomendación ya calculada | Sí | Solo reformula el JSON determinista; citas obligatorias |
| Responder «¿por qué?» / «¿y si…?» | Sí | Herramientas deterministas; no inventa cifras |
| Extraer afirmaciones de papers | Sí | Revisión humana y firma antes de entrar en el conocimiento |
| Convertir notas en partes | Sí | Validación posterior |
| Revisar un plan candidato como crítico | Sí | No decide; avisa |
| Calcular ritmos, zonas o volumen | **No** | Determinista |
| Decidir carga o seguridad | **No** | Reglas y optimizador |
| Ser fuente de verdad | **No** | TOML + SQLite |

Contrato de salida y validadores (F8-04):

```json
{
  "explicacion": "texto",
  "citas": ["AF-001", "FU-003"],
  "cifras": [{"valor": 400, "unidad": "m", "origen": "PA-001"}],
  "avisos": ["..."],
  "confianza": "media"
}
```

- Toda cifra debe existir en el contexto de entrada.
- Toda cita debe existir en el conocimiento.
- No se permiten consejos médicos.
- Si falla la validación, se descarta la respuesta y se muestra la explicación determinista.

Privacidad y operación:

- La clave vive en el servidor; nunca llega al navegador.
- Proveedor abstracto (`COACH_PROVIDER`), clave propia (no se reutiliza la de OpenCode).
- No se envían FIT, GPX, partes completas ni la base: solo métricas agregadas y extractos de
  conocimiento.
- *Logs* redactados, límite de tokens/coste y caché por `recomendacion_id + knowledge_version`.
- Si no hay red o el proveedor falla, la aplicación funciona igual.

## Consecuencias

**Buenas**

- El motor sigue siendo determinista, reproducible y auditable sin LLM.
- Se puede activar solo para explicar, con *fallback* permanente.
- Se evita la fuga de datos crudos y el consejo médico por diseño.
- El coste y la latencia son opcionales, no estructurales.

**Malas / costes**

- Hay que construir y mantener dos caminos: explicación determinista y explicación con LLM.
- La validación de citas y cifras es trabajo real (F8-04, F8-07).
- El LLM no arregla un conocimiento mal estructurado: primero hay que hacer F2/F3.
- La calidad de la explicación puede mejorar poco si el contrato es muy restrictivo; se mide
  (F8-06) y, si no aporta, se apaga.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| LLM como núcleo que decide la carga | Rompe la reproducibilidad, la trazabilidad y la seguridad; puede inventar cifras y consejo médico |
| Usar la suscripción de OpenCode para la app | Es para agentes de programación; la credencial es personal y no debe ir en la app |
| Modelo local en el Celeron | No es viable con la calidad necesaria en este hardware |
| No tener LLM nunca | Válido, pero se pierde una mejora barata de explicación/conversación; se deja como capa opcional y se evalúa |
| LLM solo para extraer papers | Insuficiente: el valor grande está en explicar al atleta; se permite también, con validadores |

## Notas

- Esta ADR no implementa nada: fija el límite. F8 puede decidir no activarlo tras la evaluación.
- Cualquier uso nuevo del LLM que no esté en la tabla exige una ADR nueva.
