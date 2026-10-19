# Base de conocimiento estructurada (TOML)

Esta carpeta es la **fuente de verdad nueva** del conocimiento de entrenamiento. En F2 convive con el
anexo Markdown (`informes/T_base_de_conocimiento.md`): el motor sigue leyendo el anexo y las constantes
actuales, y el TOML se carga, valida, versiona y sincroniza sin cambiar el comportamiento.

## Ficheros

| Fichero | Contenido |
|---|---|
| `fuentes.toml` | `[[fuente]]`: documentos, URL y citas literales (`FU-*`). |
| `afirmaciones.toml` | `[[afirmacion]]`: frases atómicas, condiciones y fuentes (`AF-*`). |
| `parametros.toml` | `[[parametro]]`: números con unidad, procedencia y firma (`PA-*`). |
| `reglas.toml` | `[[regla]]`: condición → acción, evidencia, parámetros y métrica (`RG-*`). |
| `estimulos.toml` | `[[estimulo]]`: clases de entrenamiento y su coste (`ES-*`). |
| `recetas.toml` | `[[receta]]`: sesiones con pasos, progresión y regresión (`RE-*`). |
| `calendario.toml` | `[calendario]`: días del entrenador y días propios. |
| `revisiones.toml` | `[[revision]]`: firmas y revisiones (`RV-*`), vacío en F2. |

## Campos

### `fuente`
Obligatorios: `id` (`FU-###`), `tipo`, `titulo`, `url`, `cita` y `citas` (lista no vacía).
Opcionales: `autores`, `anio`, `doi`, `poblacion`, `intervencion`, `resultado`, `limitaciones`,
`certeza`, `revisado_por`, `revisado_en`, `legacy_id` y `notas`.
`legacy_id` guarda el número `[n]` del bloque `## Sources` del anexo T.

### `afirmacion`
Obligatorios: `id` (`AF-###`), `texto` y `fuentes` (lista de `{ id = "FU-###", cita_local = "..." }`).
Alternativa al menos una fuente: `criterio_firmado = true` con `firmado_por`/`firmado_en`.
Opcionales: `condiciones`, `efecto`, `direccion` (`mejora|neutro|empeora|incierto`), `tamano`,
`aplicabilidad`, `certeza`, `estado` (`propuesta|revisada|rechazada`), `notas`.

### `parametro`
Obligatorios: `id` (`PA-###`), `nombre`, `valor`, `procedencia`
(`evidencia|criterio_firmado|historial|pactado`).
Opcionales: `unidad`, `fuente` (`FU-###`), `afirmacion` (`AF-###`), `firmado_por`, `firmado_en`, `nota`.
Si la procedencia es `criterio_firmado` y no hay firma, el validador avisa (`firma_pendiente`).

### `regla`
Obligatorios: `id` (`RG-###`), `enunciado`, `cuando` (tabla), `entonces` (tabla),
`metrica_exito` (tabla no vacía con `tipo` y `criterio`).
Opcionales: `version`, `evidencia` (`AF-###`), `parametros` (`PA-###`), `contraindicaciones`,
`revisar_en_dias`, `confianza`, `estado`, `estimulo`, `notas`.

### `estimulo`
Obligatorios: `id` (`ES-###`), `nombre`, `entrena`.
Opcionales: `no_entrena`, `recuperacion_h`, `coste`, `papel_400`, `papel_3000`, `senal`,
`afirmaciones`, `seccion_T`, `notas`.

### `receta`
Obligatorios: `id` (`RE-###`), `nombre`, `sesion`, `pasos` (lista no vacía con `orden` y `texto`).
Opcionales: `metros`, `reps`, `dist_m`, `ritmo_rel`, `descanso_s`, `salida_s`, `desde_dia`, `porque`,
`progresion`, `regresion`, `estimulo` (`ES-###`), `afirmaciones`, `notas`.

### `calendario`
`dias_entrenador`, `dias_propios`, `dia_bici`, `dias_calidad`, `dias_largos`, `duro_h` y `notas`.

## Uso

```bash
# estructura y version
docker compose exec -T entrenador python -m entrenador.cli conocimiento --estructura
docker compose exec -T entrenador python -m entrenador.cli conocimiento --version

# validacion TOML + Markdown
docker compose exec -T entrenador python -m entrenador.cli conocimiento --validar
docker compose exec -T entrenador python -m entrenador.cli conocimiento --validar --json

# sincronizar el TOML con las tablas SQLite (aditivo e idempotente)
docker compose exec -T entrenador python -m entrenador.cli conocimiento --sincronizar

# exportar a Markdown (data/derived/conocimiento/) sin tocar informes/
docker compose exec -T entrenador python -m entrenador.cli conocimiento --exportar-md
```

## Reglas

- Nada de datos personales: ni marcas, ni fechas, ni nombres del atleta.
- Los IDs son estables: no se renumeran al añadir entradas.
- El TOML se valida antes de sincronizar; el validador no escribe nada.
- El Markdown de `informes/` sigue siendo la referencia de F1/F2; en F3 se generará desde aquí.
