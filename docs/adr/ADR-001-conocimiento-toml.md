# ADR-001 — El conocimiento vive en TOML versionado, no en constantes de Python

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** F0 (decisión); se implementa en F2/F3
- **Decisores:** proyecto Entrenador (revisión del entrenador pendiente para las firmas)

## Contexto

Hoy el saber de natación está en dos sitios que no se hablan:

1. `informes/T_base_de_conocimiento.md`, un anexo excelente para auditar pero que **no gobierna el
   motor**: cambiarlo no cambia ninguna recomendación.
2. Constantes de Python (`estimulos.CLASES`, `estimulos.RECETAS`, `reglas.REGLAS`,
   `reglas.REPARTO_OBJETIVO`, `reglas.MINIMOS_OBLIGATORIOS`, `planificador.DIAS_*`,
   `plan_vivo.TOPE_*`, `evaluacion.TOLERANCIA_*`, `valoracion.AYUDA_MATERIAL`…).

Eso produce tres problemas medidos en el diagnóstico del plan (D-03, D-04, D-13):

- el anexo y el motor pueden decir cosas distintas y nadie se entera;
- los números no tienen procedencia ni firma;
- no se puede saber qué versión del conocimiento produjo una recomendación.

El proyecto es local, sin dependencias pesadas y con Python 3.12. `tomllib` es de la biblioteca
estándar desde 3.11, es legible y produce *diffs* limpios en git.

## Decisión

La **fuente de verdad** del conocimiento pasa a ser un conjunto de ficheros TOML versionados en
`conocimiento/`:

```text
conocimiento/
  fuentes.toml        # FU-*: documento, URL, cita literal, certeza
  afirmaciones.toml   # AF-*: frase atómica + fuentes + estado
  reglas.toml         # RG-*: condición -> acción + evidencia + métrica
  parametros.toml     # PA-*: número + unidad + procedencia + firma
  estimulos.toml      # ES-*: clases de estímulo y su coste
  recetas.toml        # RE-*: sesiones concretas, progresión y regresión
  calendario.toml     # días, recuperación, pruebas
  revisiones.toml     # RV-*: quién firma qué y cuándo
  CHANGELOG.md
```

Reglas que se derivan de la decisión:

1. El Markdown `informes/T_base_de_conocimiento.md` se **genera** desde los TOML (el Markdown deja
   de ser fuente). Mientras dure la migración, el parser actual sigue leyendo el Markdown.
2. `entrenador/conocimiento.py` carga, valida, consulta, versiona y exporta. Un único módulo.
3. `knowledge_version = sha256(json_canónico(...))[:16]` se guarda en cada recomendación.
4. Ningún parámetro entra sin `procedencia ∈ {evidencia, criterio_firmado, historial, pactado}`;
   los que no tienen fuente se firman como criterio del entrenador.
5. La migración es **aditiva** y con *dual-run* (`MOTOR_CONOCIMIENTO=v1|v2`): v1 sigue funcionando
   y se puede volver atrás.

## Consecuencias

**Buenas**

- Cambiar el conocimiento cambia el motor sin tocar Python (objetivo OB-01).
- Cada número se puede rastrear a una fuente o a una firma (OB-02, OB-05).
- El *diff* de un cambio de conocimiento es legible y revisable.
- La versión del conocimiento queda guardada y permite auditar una recomendación antigua.
- Sin dependencias nuevas (`tomllib`).

**Malas / costes**

- F2 y F3 son trabajo real: esquemas, *loader*, validador, exportador y migración de todas las
  constantes del anexo A.
- Hay que mantener dos caminos (Markdown y TOML) durante la migración; el *dual-run* lo hace
  explícito.
- El TOML no permite expresar fórmulas: las reglas ejecutables siguen necesitando código; el TOML
  declara condición, acción, evidencia y parámetros, no la implementación.
- El entrenador tiene que firmar los criterios; sin firma no pueden motivar una recomendación.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Dejar el Markdown como fuente y parsearlo | Parser frágil (ya hay defectos: `T.9` duplicado, citas por sección); sin tipos ni validación; el Markdown generado se edita a mano y se desincroniza |
| JSON | Legible por máquina, pero peor para escribir y revisar a mano: sin comentarios, comas y comillas en cada línea |
| YAML | Necesita dependencia externa (`PyYAML`) y su sangría es una fuente de errores |
| SQLite como única fuente | Ya se usa para consultar, pero no es un buen formato de revisión: un cambio no se lee en un *diff* |
| Seguir con constantes de Python | Es el problema de partida: cambiar el anexo no cambia el motor y no hay trazabilidad |

## Notas

- Esta ADR no activa TOML: solo fija el formato. La implementación y el *dual-run* son F2/F3.
- Si el piloto del corte vertical (`R2`/`ritmo_prueba`) no demuestra valor, la decisión se revisa
  antes de migrar el resto.
