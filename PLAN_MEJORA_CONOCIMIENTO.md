# Plan de mejora del modelo de conocimiento del Entrenador

**Versión:** 1.0  
**Fecha:** 2026-10-19  
**Estado:** propuesta para aprobar antes de tocar código  
**Ámbito:** conocimiento, motor de decisión, estado del atleta, bucle de resultados, interfaz y capa opcional de LLM.  
**Documento de trabajo:** este plan es la referencia. Si una tarea no está aquí, no entra en el alcance sin añadirla y justificarla.

---

## 0. Resumen ejecutivo

### Qué se quiere conseguir

Pasar de un sistema que **describe** lo que ha pasado y repite reglas generales, a un sistema que **decide** qué hacer ahora, con:

1. una base de conocimiento única, estructurada y versionada;
2. trazabilidad afirmación → fuente → regla → parámetro → recomendación → resultado;
3. recomendaciones con prioridad, alternativas, riesgo, métrica de éxito y fecha de revisión;
4. un bucle real que aprenda de lo que el atleta hace y de lo que funciona;
5. una capa opcional de LLM para explicar y conversar, nunca para inventar números ni decidir la carga.

### Diagnóstico en una frase

La base de conocimiento actual es un **anexo documental** excelente para auditar, pero el motor real está en constantes de Python; por eso cambiar el anexo no cambia las recomendaciones, y las recomendaciones son un informe largo, no una decisión.

### Estrategia

No hacer una reescritura total de golpe. Se hará un **corte vertical primero** con una sola regla (`R2` / `ritmo_prueba`) para demostrar el circuito completo:

```text
afirmación → fuente → regla → parámetro → estado del atleta → opciones → recomendación
→ decisión → sesión → resultado → verificación → aprendizaje
```

Cuando ese circuito funcione y esté probado, se migra el resto.

### Decisiones propuestas

| Decisión | Propuesta | Motivo |
|---|---|---|
| Fuente de verdad del conocimiento | Ficheros TOML versionados + carga validada | Legible, diff en git, sin dependencias nuevas (`tomllib` es estándar) |
| Auditoría y consultas | Tablas SQLite adicionales | El proyecto ya usa SQLite y permite unir conocimiento, estado y resultados |
| Formato de recomendación | JSON estructurado con opciones | Permite pintar, validar, auditar y comparar versiones |
| LLM | Capa opcional, no núcleo | Evita alucinaciones, coste y fuga de datos personales |
| Migración | Aditiva, con *feature flag* y *dual-run* | Permite volver atrás sin tocar datos |
| Entrega | Por fases con criterios de aceptación | Evita un big bang y permite revisar cada paso |

### Resultado esperado

- El atleta ve **una prioridad**, **una acción**, **por qué**, **cómo medirla** y **qué hacer si no puede**.
- Cada número de una recomendación se puede rastrear hasta una fuente, un criterio firmado o un dato del atleta.
- Se puede comparar la recomendación con la alternativa y con “no hacer nada”.
- El sistema aprende de los resultados, no solo de la teoría.
- El LLM, si se activa, solo mejora la explicación y la conversación; el motor sigue siendo determinista.

---

## 1. Objetivo, alcance y no objetivos

### 1.1. Objetivos medibles

| ID | Objetivo | Métrica de éxito |
|---|---|---|
| OB-01 | Una sola fuente de verdad del conocimiento | 0 constantes de conocimiento duplicadas en código; `conocimiento --validar` sin errores |
| OB-02 | Trazabilidad por afirmación | 100 % de reglas con al menos una afirmación enlazada; 100 % de parámetros con procedencia |
| OB-03 | Recomendaciones accionables | Cada recomendación tiene prioridad, opción recomendada, 1-3 alternativas, métrica de éxito y fecha de revisión |
| OB-04 | Bucle de resultados | ≥ 80 % de recomendaciones aceptadas/cambiadas con resultado evaluable a los 21 días |
| OB-05 | Explicabilidad | Cualquier número mostrado se puede rastrear a `AF-*`, `PA-*` o a una consulta documentada al estado del atleta |
| OB-06 | No regresión | La suite actual sigue pasando; los cambios de comportamiento son intencionales y revisados con *golden tests* |
| OB-07 | Privacidad | Ningún dato crudo de salud sale del servidor; si se activa LLM, solo salen métricas agregadas y con opt-in |
| OB-08 | Reproducibilidad | Misma base + misma versión de conocimiento + misma fecha ⇒ misma recomendación |

### 1.2. Dentro del alcance

- Rediseño de la base de conocimiento y su compilación.
- Migración de `CLASES`, `CONOCIMIENTO`, `REGLAS`, `REPARTO_OBJETIVO`, `MINIMOS_OBLIGATORIOS`, `RECETAS` y parámetros relacionados.
- Modelo de estado del atleta.
- Motor de decisión con opciones, prioridad, riesgo y métrica.
- Bucle de resultados y verificación.
- Cambios de interfaz del panel y de la consola.
- Capa opcional de LLM para explicación/extracción/conversación.
- Pruebas, migración, documentación y despliegue.

### 1.3. Fuera del alcance

- Diagnóstico o tratamiento médico.
- Sustituir al entrenador personal en los días que manda el entrenador.
- Prescribir rehabilitación o manejar dolor/lesión sin derivación.
- Aplicación móvil nativa.
- Integración en tiempo real con reloj, pulsera o sensors.
- Cambiar el importador de FIT/GPX/Strava salvo lo necesario para enlazar resultados.
- Entrenar un modelo propio de IA.
- Publicar datos personales en el repositorio público.

### 1.4. Supuestos

- Python 3.12, SQLite, Docker y Caddy ya funcionando.
- El proyecto sigue siendo local/privado; los datos viven en `data/`.
- `informes/` es privado y no se publica.
- No se añaden dependencias pesadas sin justificarlo.
- El atleta/entrenador revisa y firma los criterios; el sistema no se autofirma.
- Las estimaciones de tiempo son rangos de trabajo efectivo, no promesas.

---

## 2. Principios e invariantes

Estos principios no se negocian. Si una tarea los rompe, se para y se revisa.

| ID | Invariante | Cómo se comprueba |
|---|---|---|
| INV-01 | Una sola fuente de verdad por dato de conocimiento | Test que prohíbe constantes de conocimiento fuera de `conocimiento/` |
| INV-02 | Ninguna recomendación sin datos del atleta | Validación de esquema: `estado_id` y ≥ 1 `dato` |
| INV-03 | Ninguna recomendación sin respaldo declarado | ≥ 1 `AF-*` o `PA-*` con procedencia `criterio_firmado` |
| INV-04 | Ningún parámetro sin procedencia | `procedencia ∈ {evidencia, criterio_firmado, historial, pactado}` + firma cuando toca |
| INV-05 | Los números se calculan, no se generan con LLM | Test de contrato: el LLM no puede devolver cifras nuevas |
| INV-06 | Reproducibilidad | `knowledge_version` + `estado_version` guardados en cada recomendación |
| INV-07 | Migraciones aditivas | No se borra ni renombra una columna/tabla en la misma versión |
| INV-08 | Rollback posible | *Feature flag* `MOTOR_CONOCIMIENTO=v1|v2` y datos antiguos intactos |
| INV-09 | Privacidad por defecto | Sin LLM activo, la app funciona igual; sin red, también |
| INV-10 | Seguridad primero | Dolor/lesión ⇒ parar y derivar; nunca adaptar como si fuera carga |
| INV-11 | Honestidad | Si no hay datos, se dice `sin_datos`; no se rellena con prosa |
| INV-12 | Cada tarea deja evidencia | Comando ejecutado + resultado + test que lo cubre |

---

## 3. Diagnóstico de partida

### 3.1. Mapa actual

| Capa | Ficheros | Qué hace hoy | Problema |
|---|---|---|---|
| Documento | `informes/T_base_de_conocimiento.md` | 10 secciones, 22 fuentes definidas (numeración hasta 29; `[24]` huérfana), 21 líneas `[criterio]` (22 cláusulas) | Es documentación; no gobierna el motor |
| Parser | `entrenador/conocimiento.py` | Lee secciones, citas y firmas | Parser frágil; citas por sección; duplicado `T.9` |
| Conocimiento hardcodeado | `entrenador/estimulos.py` | `CLASES`, `CONOCIMIENTO`, `MATERIAL`, `RECETAS` | Duplica el anexo; parámetros sin enlace |
| Reglas hardcodeadas | `entrenador/reglas.py` | `REGLAS`, `REPARTO_OBJETIVO`, `MINIMOS_OBLIGATORIOS` | Porcentajes y mínimos sin trazabilidad fina |
| Planificación | `entrenador/planificador.py` | Reparte sesiones por días | Reglas de recuperación fijas; no optimiza |
| Plan escrito | `entrenador/plan.py`, `entrenador/plan_vivo.py` | Calendario y ajuste de volumen | Contenido y parámetros mezclados con código |
| Evaluación | `entrenador/evaluacion.py` | Veredicto de sesión/semana | Métricas limitadas; poca respuesta individual |
| Discurso | `entrenador/valoracion.py` | Genera “El entrenador dice” | Largo, descriptivo, sin alternativas |
| Bucle | `entrenador/decision.py` | Propuestas, decisión, verificación | Infraestructura existe, pero no se usa |
| Estado | `series_dia.py`, `aprendizaje.py`, `analitica.py` | Ventanas y métricas | Ventana de 14 días; poca incertidumbre |
| Interfaz | `panel.py`, `app/*`, `portal.py` | Panel y portal de bici | Muestra el discurso entero; no prioriza |

### 3.2. Defectos concretos

| ID | Defecto | Evidencia | Impacto | Se resuelve en |
|---|---|---|---|---|
| D-01 | `T.9` duplicado y sobrescrito | Hay dos `## T.9`; el parser usa un diccionario y el segundo gana | `fuente_de("como_se_mantiene")` devuelve fuentes del cierre | F1-01 |
| D-02 | Citas por sección, no por afirmación | `fuente_de` agrega todas las fuentes de `T.1`, `T.2`, `T.3` | Se puede citar una sección que no sostiene el número concreto | F2 |
| D-03 | Conocimiento duplicado en código | `CLASES`, `REGLAS`, `RECETAS`, `REPARTO_OBJETIVO` | Cambiar el anexo no cambia la recomendación | F3 |
| D-04 | Parámetros sin procedencia | 25 %, 400 m, 36 h, descuentos de material | Un criterio puede parecer evidencia | F2/F3 |
| D-05 | Criterios sin firmar | 21 líneas `[criterio]` | No se sabe qué está aprobado por el entrenador | F1/F3 |
| D-06 | Bucle sin usar | `cli reglas`: 9 reglas `sin_datos`, 0 propuestas | No hay aprendizaje | F6 |
| D-07 | Verificación casi inexistente | Solo `R2` tiene `METRICAS` | No se sabe si una regla acierta | F6 |
| D-08 | Ventana de 14 días | `estimulos.VENTANA_DIAS` | Señal ruidosa; ignora tendencia y carga crónica | F4 |
| D-09 | Recetas fijas | 7 recetas en `RECETAS` | Poca adaptación a fatiga, material y disponibilidad | F3/F5 |
| D-10 | Discurso no es decisión | `valoracion._falta_y_toca` | Mucho texto, poca acción | F5/F7 |
| D-11 | Sin alternativas | La recomendación no compara opciones | El atleta no sabe qué hacer si no puede | F5 |
| D-12 | Sin métrica de éxito | No hay “cómo saber si funcionó” | No se puede cerrar el bucle | F5/F6 |
| D-13 | Sin versión de conocimiento | No se guarda qué base produjo una recomendación | No se puede auditar un cambio | F2 |
| D-14 | Fuente huérfana | `[24]` está en fuentes y no se cita | Ruido y posible error de mantenimiento | F1-02 |
| D-15 | Sin parser de fuentes | El bloque `## Sources` no se valida | Citas rotas no se detectan | F1-02 |
| D-16 | `sin_fuente()` engañoso | Devuelve `[]` con 21 líneas de criterio | El portal puede decir que todo tiene fuente | F1-03 |
| D-17 | UI sobrecargada | “El entrenador dice” con 9 párrafos | El atleta no encuentra la acción | F7 |
| D-18 | Sin estado del atleta | Métricas dispersas por módulos | La decisión no tiene una foto única | F4 |

### 3.3. Línea base cuantitativa

Registrar antes de tocar nada (F0-01):

- `git rev-parse HEAD` de ambos repositorios.
- Digest de la imagen Docker y `docker compose config`.
- `PRAGMA integrity_check` y conteo de tablas principales.
- Número de secciones, fuentes, criterios, reglas, clases, recetas.
- Salida actual de `cli valoracion`, `cli plan --recalculado`, `cli reglas`, `cli decision --lista`.
- Tiempo de `cli analizar` y tamaño de `cuadro/panel.html`.
- Resultado de la suite Python y del test Node.

Estos datos son la referencia para comparar. No se guardan en el repositorio público si contienen datos personales; se guardan en `informes/` o en `data/derived/`.

---

## 4. Arquitectura objetivo

### 4.1. Capas

```text
┌─────────────────────────────────────────────────────────────┐
│ 4. Presentación                                             │
│ panel.html / portal.py / CLI                                │
│ tarjetas de decisión, explorador de conocimiento, historial │
└──────────────────────────────┬──────────────────────────────┘
                               │ JSON validado
┌──────────────────────────────▼──────────────────────────────┐
│ 3. Motor de decisión                                        │
│ opciones → restricciones → puntuación → recomendación       │
│ explicación determinista, métrica de éxito, revisión        │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ 2. Estado del atleta                                        │
│ rendimiento, carga, recuperación, fuerza, restricciones,    │
│ adherencia, respuesta individual, incertidumbre             │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ 1. Conocimiento                                             │
│ fuentes → afirmaciones → reglas → parámetros → recetas      │
│ validado, versionado, con firma y procedencia               │
└─────────────────────────────────────────────────────────────┘

Capa transversal: trazabilidad, pruebas, privacidad, feature flags.
Capa opcional: LLM (solo explicación/extracción/conversación).
```

### 4.2. Módulos objetivo

| Módulo | Responsabilidad | Sustituye/absorbe |
|---|---|---|
| `conocimiento/fuentes.toml` | Fuentes y citas literales | Bloque `## Sources` |
| `conocimiento/afirmaciones.toml` | Afirmaciones atómicas | Texto de `T.1`–`T.8` |
| `conocimiento/reglas.toml` | Reglas ejecutables | `reglas.REGLAS`, `REPARTO_OBJETIVO`, `MINIMOS_OBLIGATORIOS` |
| `conocimiento/estimulos.toml` | Clases de estímulo | `estimulos.CLASES`, `CONOCIMIENTO`, `MATERIAL` |
| `conocimiento/recetas.toml` | Recetas y variantes | `estimulos.RECETAS` |
| `conocimiento/calendario.toml` | Reglas de días, recuperación y pruebas | `planificador` |
| `entrenador/conocimiento.py` | Cargar, validar, consultar, versionar, exportar Markdown | Parser actual |
| `entrenador/estado.py` | Estado del atleta y versiones | Métricas dispersas |
| `entrenador/motor.py` | Generar y puntuar opciones | `planificador` + parte de `valoracion` |
| `entrenador/resultados.py` | Enlazar recomendación, sesión y resultado | `decision.verificar` ampliado |
| `entrenador/coach_llm.py` | Capa opcional de lenguaje | Nuevo |
| `entrenador/panel.py` / `app/*` | Presentación | Ampliar |

### 4.3. Flujo de una recomendación

1. Cargar conocimiento validado y versión.
2. Calcular estado del atleta y versión.
3. Detectar prioridades (déficits, riesgos, oportunidades).
4. Generar opciones candidatas.
5. Aplicar restricciones duras (calendario, recuperación, dolor, material).
6. Puntuar opciones (efecto esperado × confianza − riesgo − coste).
7. Elegir y guardar la recomendación con sus opciones y versiones.
8. Generar la explicación determinista.
9. El atleta decide.
10. Se enlaza con la sesión realizada.
11. Se evalúa el resultado y se actualiza la verificación.
12. Se revisa el conocimiento si el resultado contradice la regla.

---

## 5. Modelo de conocimiento

### 5.1. Entidades

| Entidad | ID | Propósito |
|---|---|---|
| Fuente | `FU-###` | Documento, artículo, libro, norma o criterio firmado |
| Afirmación | `AF-###` | Una frase atómica con condiciones y efecto |
| Regla | `RG-###` | Condición → acción, con prioridad y contraindicaciones |
| Parámetro | `PA-###` | Número con unidad, procedencia y firma |
| Estímulo | `ES-###` | Clase de entrenamiento y su coste/beneficio |
| Receta | `RE-###` | Sesión concreta, con progresión y regresión |
| Revisión | `RV-###` | Quién firma qué y cuándo |
| Versión | `KV-###` | Hash canónico del conjunto de conocimiento |

### 5.2. Estructura de ficheros

```text
conocimiento/
  fuentes.toml
  afirmaciones.toml
  reglas.toml
  parametros.toml
  estimulos.toml
  recetas.toml
  calendario.toml
  revisiones.toml
  CHANGELOG.md
```

El Markdown `informes/T_base_de_conocimiento.md` se **genera** desde estos ficheros. La fuente de verdad es el TOML.

### 5.3. Esquema de fuente

```toml
[[fuente]]
id = "FU-001"
tipo = "articulo"            # articulo | libro | norma | consenso | criterio_entrenador
titulo = "..."
autores = ["..."]
anio = 2013
url = "https://..."
doi = "..."
cita = "Texto literal que sostiene la afirmación."
poblacion = "..."
intervencion = "..."
resultado = "..."
limitaciones = "..."
certeza = "moderada"         # alta | moderada | baja | muy_baja
revisado_por = ""
revisado_en = ""
```

### 5.4. Esquema de afirmación

```toml
[[afirmacion]]
id = "AF-001"
texto = "Series cortas y largas, igualadas en volumen e intensidad, mejoran de forma similar."
condiciones = "nadadores entrenados; 8 semanas; 50 m vs 100 m"
efecto = "rendimiento similar en 100 y 400 m"
direccion = "neutro"         # mejora | neutro | empeora | incierto
tamano = "..."
aplicabilidad = "parcial para 400; no probado en 3.000"
certeza = "moderada"
estado = "revisada"          # propuesta | revisada | rechazada
fuentes = [
  { id = "FU-003", cita_local = "..." }
]
```

### 5.5. Esquema de regla

```toml
[[regla]]
id = "RG-002"
version = 1
enunciado = "Si en 14 días hay menos de 400 m a ritmo de prueba, priorizar una sesión específica."
cuando = { fase = "especifico_400", metros_ritmo_prueba = "<400" }
entonces = { prioridad = 1, receta = "RE-003", minimo_m = 400 }
evidencia = ["AF-001", "AF-002"]
parametros = ["PA-001", "PA-002"]
contraindicaciones = ["dolor_hombro", "carga_alta", "lesion_activa"]
metrica_exito = { tipo = "ritmo_serie", criterio = "caida_ultima_rep < 3 s/100", ventana_dias = 3 }
revisar_en_dias = 21
confianza = 0.6
estado = "revisada"
```

### 5.6. Esquema de parámetro

```toml
[[parametro]]
id = "PA-001"
nombre = "minimo_ritmo_prueba_m"
valor = 400
unidad = "m"
procedencia = "criterio_firmado"   # evidencia | criterio_firmado | historial | pactado
fuente = "AF-002"
firmado_por = ""
firmado_en = ""
nota = "No hay fuente que fije el número; se aprueba como criterio del entrenador."
```

### 5.7. Validaciones obligatorias

`conocimiento --validar` debe fallar si:

1. Hay IDs duplicados.
2. Una afirmación no tiene fuente ni criterio firmado.
3. Una regla cita una afirmación inexistente.
4. Un parámetro no tiene procedencia o firma cuando la necesita.
5. Un `[n]` no tiene `FU-###` correspondiente.
6. Hay una fuente sin usar (aviso, no error, salvo que sea obligatoria).
7. Una regla no tiene métrica de éxito.
8. Una receta no tiene parámetros completos.
9. Una sección del Markdown generado no coincide con el TOML.
10. Hay una regla con contraindicación de seguridad sin ruta de derivación.

### 5.8. Versionado

- `knowledge_version = sha256(json_canonico(fuentes + afirmaciones + reglas + parametros + estimulos + recetas + calendario))[:16]`.
- Se guarda en cada recomendación y en `conocimiento_version`.
- `CHANGELOG.md` registra: fecha, autor, IDs cambiados, motivo, revisión.
- Cambiar un parámetro firmado exige nueva firma y nueva versión.
- El panel muestra la versión y la fecha de la última revisión.

### 5.9. Flujo de revisión

```text
propuesta (IA o humano)
   → revisión técnica (¿la cita sostiene la afirmación?)
   → revisión del entrenador (¿lo aplicamos a este atleta?)
   → firma (quién, cuándo, notas)
   → estado revisada
   → se puede usar en reglas
```

Sin firma, una afirmación puede existir como `propuesta`, pero **no puede motivar una recomendación**.

---

## 6. Modelo del atleta

### 6.1. Campos

| Grupo | Campos | Fuente |
|---|---|---|
| Rendimiento | mejor 400, mejor 1.000, velocidad crítica, tendencia, marcas oficiales | `analitica`, `competicion` |
| Carga | aguda 7d, crónica 28d, ratio, monotonía, strain, días consecutivos | `actividad`, `parte`, `apunte` |
| Recuperación | sueño, RPE, sensación, FC media/máx | `sueno`, `natacion_sesion`, `parte` |
| Fuerza | sesiones, volumen, RPE, hombro | `gimnasio_*`, `fuerza` |
| Restricciones | días del entrenador, bici, viajes, material, piscina, dolor | `plan`, `parte`, `apunte` |
| Adherencia | propuesto vs hecho, motivos de cambio | `recomendacion`, `decision`, `evaluacion` |
| Respuesta | delta de ritmo/FC/RPE por estímulo | histórico + `resultados` |
| Incertidumbre | n, dispersión, confianza | cálculo |

### 6.2. Ventanas

- **Aguda:** 7 días.
- **Crónica:** 28 días.
- **Tendencia:** 90 días con peso exponencial.
- **Histórico:** todo, con decaimiento.
- **Ventana de decisión:** configurable, no fija en 14 días.

### 6.3. Incertidumbre

Cada métrica debe llevar:

```json
{
  "valor": 1.284,
  "unidad": "m",
  "n": 7,
  "dispersion": 0.18,
  "confianza": "media",
  "fuente": "parte+reloj",
  "limitaciones": ["4 de 10 días sin parte"]
}
```

La recomendación no puede presentar una métrica con confianza baja como si fuera un hecho.

### 6.4. Snapshot

Tabla `estado_atleta`:

```sql
CREATE TABLE estado_atleta (
  id            TEXT PRIMARY KEY,   -- hash de fecha + datos de entrada
  fecha         TEXT NOT NULL,
  version_hash  TEXT NOT NULL,
  json          TEXT NOT NULL,
  creado_en     TEXT NOT NULL
);
```

Cada recomendación guarda `estado_id`. Así se puede reconstruir exactamente qué se sabía cuando se propuso.

---

## 7. Motor de decisión

### 7.1. Objeto recomendación

```json
{
  "id": 123,
  "fecha": "2026-10-19",
  "ambito": "semana",
  "semana": "S2",
  "knowledge_version": "a1b2c3d4e5f6",
  "estado_id": "estado-2026-10-19-abc",
  "prioridad": 1,
  "problema": "Falta ritmo de prueba con pausa corta",
  "estado": {
    "metros_ritmo_prueba_14d": 200,
    "minimo_m": 400,
    "confianza": "media"
  },
  "opciones": [
    {
      "id": "A",
      "recomendada": true,
      "sesion": "8x100 con 25-30 s, salida cada 2:00",
      "dia": "martes",
      "metros": 1700,
      "ritmo": "1:16-1:17",
      "efecto_esperado": "alto",
      "confianza": 0.6,
      "riesgo": "medio",
      "coste": "medio",
      "porque": "es el estímulo más específico y el que menos has hecho"
    },
    {
      "id": "B",
      "recomendada": false,
      "sesion": "4x200 con 40 s",
      "dia": "jueves",
      "efecto_esperado": "medio",
      "confianza": 0.5,
      "riesgo": "bajo",
      "coste": "medio",
      "porque": "menos específico, pero cabe si el martes no puedes"
    }
  ],
  "evidencia": ["AF-001", "AF-002"],
  "parametros": ["PA-001"],
  "contraindicaciones": ["dolor_hombro", "carga_alta"],
  "metrica_exito": {
    "tipo": "ritmo_serie",
    "criterio": "caída de la última repetición < 3 s/100",
    "medir_en": "2026-10-22"
  },
  "revisar_en": "2026-10-26",
  "explicacion": "..."
}
```

### 7.2. Generación de opciones

1. Detectar prioridades (máximo 3).
2. Para cada prioridad, cargar reglas aplicables.
3. Generar 2-4 opciones:
   - la recomendada,
   - una alternativa menos específica,
   - una alternativa de mínimo volumen,
   - “no hacer nada / mantener”.
4. Aplicar restricciones duras:
   - días del entrenador,
   - recuperación,
   - dolor/lesión,
   - material,
   - piscina,
   - viajes.
5. Puntuar:
   ```text
   score = efecto_esperado × confianza − riesgo − coste
   ```
   Los pesos son configurables y auditables.
6. Elegir la mejor; si hay empate, la de menor riesgo.
7. Guardar todas las opciones, no solo la elegida.

### 7.3. Reglas de seguridad

- Dolor declarado ⇒ no se prescribe; se deriva.
- Lesión activa ⇒ no se prescribe carga; se deriva.
- Sin datos suficientes ⇒ `sin_datos`, no se inventa.
- Contraindicación ⇒ la opción se descarta y se explica.
- La recomendación nunca promete una marca.

### 7.4. Explicación determinista

Plantilla:

```text
Qué veo: [dato] ([confianza]).
Por qué importa: [afirmación] ([AF-###], [FU-###]).
Qué propongo: [opción A].
Cómo lo medimos: [métrica] el [fecha].
Riesgo: [riesgo]; si [condición], haz [opción B].
Revisión: [fecha].
```

El LLM, si está activo, solo reescribe esto; no añade cifras.

---

## 8. Feedback y aprendizaje

### 8.1. Enlace

```text
recomendacion.id
  → decision (aceptada | cambiada | ignorada)
  → actividad_id / parte_id / apunte_id
  → resultado (métrica antes/después)
  → verificacion (a_favor | en_contra | sin_datos)
  → aprendizaje (qué se ajusta)
```

### 8.2. Métricas por regla

Cada regla debe declarar:

- métrica,
- ventana,
- valor antes,
- valor después,
- confounders,
- criterio de éxito,
- fecha de revisión.

### 8.3. Confounders

Registrar al menos:

- sueño,
- carga previa,
- material,
- piscina,
- viaje,
- enfermedad,
- dolor,
- cambios de plan,
- días sin parte.

No se declara causalidad si hay confounders importantes; se dice “no concluyente”.

### 8.4. Aprendizaje

- No se cambia una regla automáticamente.
- Se propone un cambio, se revisa y se firma.
- Se guarda `aprendizaje` con evidencia y fecha.
- Se puede comparar `knowledge_version` antigua vs nueva.

---

## 9. Interfaz

### 9.1. Tarjeta principal

```text
┌────────────────────────────────────────────────────────────┐
│ PRIORIDAD 1 · Esta semana                                  │
│ Ritmo de prueba con pausa corta                            │
│                                                            │
│ Qué veo: 200 m en 14 días; el mínimo son 400 m.            │
│ Qué propongo: 8x100 a 1:16-1:17 con 25-30 s, martes.       │
│ Por qué: es el estímulo más específico y el que menos      │
│ has hecho. Evidencia: AF-001, AF-002.                      │
│ Cómo lo medimos: caída de la última repetición < 3 s/100.  │
│ Riesgo: si el hombro duele, no; alternativa: 4x200 jueves. │
│ Revisión: 26/10.                                           │
└────────────────────────────────────────────────────────────┘
```

### 9.2. Niveles

1. **Una prioridad** visible.
2. **Una acción** visible.
3. **Por qué / cómo medir / riesgo** en desplegable.
4. **Alternativas** en desplegable.
5. **Conocimiento** en un explorador aparte: afirmación, fuente, cita, revisión.
6. **Historial**: qué se propuso, qué se hizo, qué pasó.

### 9.3. Criterios de aceptación

- Encontrar la acción de la semana en < 30 s.
- Cada cifra tiene un enlace o explicación de procedencia.
- Se puede ver la versión del conocimiento.
- No se rompe la vista actual de entrenamientos, competición, plan, gimnasio.
- Funciona sin JavaScript? No es requisito; el panel ya depende de JS.
- Test Node sin errores.

---

## 10. Capa opcional de LLM

### 10.1. Decisión

**No** como núcleo. **Sí** como capa opcional de:

| Uso | ¿LLM? | Condición |
|---|---|---|
| Extraer afirmaciones de papers | Sí | Revisión humana y firma antes de entrar |
| Explicar una recomendación ya calculada | Sí | Solo reformula JSON; citas obligatorias |
| Responder “¿por qué?” / “¿y si…?” | Sí | Herramientas deterministas; no inventa cifras |
| Revisar un plan candidato | Sí, como crítico | No decide; avisa |
| Convertir notas en partes | Sí | Validación posterior |
| Calcular ritmos, zonas, volumen | No | Determinista |
| Decidir carga o seguridad | No | Reglas y optimizador |
| Fuente de verdad | No | TOML + SQLite |

### 10.2. Arquitectura

```text
panel → POST /coach (backend) → orquestador
                                  ├── RAG sobre AF/FU
                                  ├── herramientas: estado, plan, métricas
                                  ├── prompt con contrato JSON
                                  └── validador de citas/cifras
                                        ↓
                                  respuesta validada o fallback
```

- La clave nunca llega al navegador.
- Proveedor abstracto (`COACH_PROVIDER`).
- `COACH_ENABLED=0` por defecto.
- Si falla, se muestra la explicación determinista.
- No se envían FIT, GPX, partes completas ni la base.
- Se envían métricas agregadas y extractos de conocimiento.
- Logs redactados.
- Retención cero si el proveedor lo permite.
- Límite de tokens y coste por petición.
- Cache de explicaciones por `recomendacion_id + knowledge_version`.

### 10.3. Contrato de salida

```json
{
  "explicacion": "texto",
  "citas": ["AF-001", "FU-003"],
  "cifras": [
    {"valor": 400, "unidad": "m", "origen": "PA-001"}
  ],
  "avisos": ["..."],
  "confianza": "media"
}
```

Validadores:

- Toda cifra debe existir en el contexto de entrada.
- Toda cita debe existir en el conocimiento.
- No se permiten consejos médicos.
- Si falla, se descarta la respuesta.

### 10.4. Evaluación

- Baseline determinista vs LLM.
- Métricas: utilidad percibida, tiempo hasta decidir, adherencia, citas válidas, coste, latencia.
- No se evalúa por marca deportiva al principio.
- Pruebas de privacidad: payload sin datos crudos.
- Pruebas de alucinación: cifras inventadas deben ser rechazadas.

### 10.5. OpenCode Go

- Técnicamente compatible, pero es una suscripción orientada a agentes de programación.
- No reutilizar la credencial de OpenCode para la app.
- Si se usa, clave propia, backend, contexto mínimo y revisión de términos.
- Alternativa recomendada: proveedor general con retención cero.
- En el Celeron actual, un modelo local útil no es viable.

---

## 11. Plan de ejecución

### 11.1. Corte vertical primero

Antes de migrar todo, se hará un piloto con `R2` / `ritmo_prueba`:

- una afirmación (`AF-*`),
- una regla (`RG-*`),
- dos parámetros (`PA-*`),
- una receta (`RE-*`),
- estado del atleta,
- dos opciones,
- métrica de éxito,
- recomendación guardada,
- resultado y verificación.

Si el piloto no demuestra valor, no se escala.

### 11.2. Fases

Las duraciones son rangos de trabajo efectivo. No incluyen esperas de revisión del entrenador.

**Tablero de tareas.** La definición canónica de cada tarea es su fila en la fase correspondiente. Para seguirlas
sin perder nada, `PLAN_TAREAS.csv` contiene una fila por tarea (ID, fase, entregable, dependencia, aceptación,
prueba y estado). Se regenera desde este plan con:

```bash
python scripts/exportar_plan_tareas.py
```

Si hay discrepancia entre el CSV y este documento, manda este documento. El CSV es una vista de trabajo, no una
segunda fuente de verdad.

---

#### F0 — Línea base y red de seguridad

**Objetivo:** poder comparar y volver atrás.

**Duración:** 2-3 días.

| Tarea | Entregable | Depende de | Aceptación | Prueba |
|---|---|---|---|---|
| F0-01 | Backup de DB, tag de git, digest de imagen, inventario de counts | — | Backup restaurable; `integrity_check=ok` | Restaurar en copia y consultar |
| F0-02 | Inventario de todo el conocimiento hardcodeado y su mapa a IDs | — | Tabla completa en este plan (anexo A) | Revisión manual |
| F0-03 | Golden snapshots de `valoracion`, `plan`, `reglas`, `decision` | F0-01 | Salidas guardadas y comparables | Script `scripts/golden.py` |
| F0-04 | Feature flag `MOTOR_CONOCIMIENTO=v1` | F0-01 | v1 sigue funcionando igual | Tests + arranque |
| F0-05 | ADR-001 (formato TOML) y ADR-002 (LLM no núcleo) | — | ADR aceptados; firma del entrenador pendiente | Revisión |
| F0-06 | Protocolo de evidencia: cada tarea adjunta comando + salida | — | Plantilla en `informes/` o `docs/` | Revisión |

**Criterio de salida:** no se ha cambiado comportamiento; todo está medido y hay vuelta atrás.

---

#### F1 — Integridad del conocimiento actual

**Objetivo:** que el documento actual no mienta ni se sobrescriba.

**Duración:** 2-3 días.

| Tarea | Entregable | Depende de | Aceptación | Prueba |
|---|---|---|---|---|
| F1-01 | Separar `T.9` en `T.9` (mantenimiento) y `T.10` (cierre) o eliminar el cierre | F0 | No hay IDs duplicados; `fuente_de("como_se_mantiene")` correcto | Test de secciones |
| F1-02 | Parser del bloque `## Sources` con `FU-*`, URL, cita | F1-01 | Toda cita `[n]` resuelve; `[24]` detectada como huérfana | Test de fuentes |
| F1-03 | Corregir `sin_fuente()` y contar los criterios (21 líneas marcadas → 22 cláusulas) | F1-01 | El portal no dice “todo con fuente” si hay criterios | Test de criterios |
| F1-04 | `cli conocimiento --validar` con salida JSON y código de error | F1-02 | 0 errores en el documento actual | Ejecución |
| F1-05 | Tests de duplicados, citas rotas, fuentes huérfanas, criterios | F1-02 | Tests verdes | Suite |
| F1-06 | Lista de criterios (22 cláusulas; 21 líneas marcadas) para firmar | F1-03 | Lista exportable y con estado | `cli conocimiento --criterios` |

**Criterio de salida:** el documento actual es consistente y validable. No se ha migrado aún.

---

#### F2 — Base estructurada y compilador

**Objetivo:** una fuente de verdad TOML validada y versionada.

**Duración:** 4-6 días.

| Tarea | Entregable | Depende de | Aceptación | Prueba |
|---|---|---|---|---|
| F2-01 | Esquemas TOML de fuente, afirmación, regla, parámetro, estímulo, receta | F1 | Documentados y con ejemplo | Revisión |
| F2-02 | Loader `conocimiento.cargar()` con dataclasses | F2-01 | Carga sin efectos secundarios | Unit test |
| F2-03 | Validador con lista completa de errores | F2-02 | Falla con IDs duplicados, citas rotas, parámetros sin firma | Tests de error |
| F2-04 | Tablas SQLite y sincronización | F2-02 | `conocimiento_version` estable | Test de sync |
| F2-05 | Hash canónico y `KV-*` | F2-04 | Mismo contenido ⇒ mismo hash | Test determinista |
| F2-06 | Exportador a Markdown | F2-02 | Markdown generado ≈ actual, diff revisado | Diff |
| F2-07 | Script de migración con `--dry-run` y diff | F2-02 | No escribe sin `--apply` | Ejecución en copia |
| F2-08 | Tests de esquema y validación | F2-03 | Cobertura de todos los errores | Suite |

**Criterio de salida:** el conocimiento se puede cargar, validar y versionar; el Markdown se genera desde TOML.

---

#### F3 — Migración del conocimiento hardcodeado

**Objetivo:** que el motor lea del conocimiento estructurado, no de constantes.

**Duración:** 5-8 días.

| Tarea | Entregable | Depende de | Aceptación | Prueba |
|---|---|---|---|---|
| F3-01 | Migrar `estimulos.CLASES`, `CONOCIMIENTO`, `MATERIAL` | F2 | Cada clase tiene `ES-*` y afirmaciones | Golden |
| F3-02 | Migrar `reglas.REGLAS`, `REPARTO_OBJETIVO`, `MINIMOS_OBLIGATORIOS` | F2 | Cada regla tiene `RG-*`, parámetros y métrica | Golden |
| F3-03 | Migrar `RECETAS`, `RECETA_DE_CLASE`, calendario y recuperación | F2 | Cada receta tiene `RE-*`, progresión y regresión | Golden |
| F3-04 | Separar plan escrito (dato del atleta) de conocimiento (reglas) | F3-03 | `plan.py` conserva su API; parámetros fuera | Golden |
| F3-05 | Adaptador de compatibilidad | F3-01..04 | Las funciones actuales siguen funcionando | Suite |
| F3-06 | Eliminar o marcar `DEPRECATED` las constantes viejas | F3-05 | 0 duplicados | Grep + test |
| F3-07 | Firmar o marcar los criterios y los parámetros | F1-06 | Cada `PA-*` tiene procedencia | Validación |
| F3-08 | Golden diff v1 vs v2 con la base real | F3-05 | Diferencias justificadas una a una | Informe |

**Criterio de salida:** el motor lee del TOML; no hay conocimiento duplicado; v1 y v2 producen lo mismo salvo diferencias aprobadas.

---

#### F4 — Estado del atleta

**Objetivo:** una foto única, versionada y con incertidumbre.

**Duración:** 5-7 días.

| Tarea | Entregable | Depende de | Aceptación | Prueba |
|---|---|---|---|---|
| F4-01 | Esquema `EstadoAtleta` | F3 | Documentado | Revisión |
| F4-02 | Métricas de rendimiento y carga | F4-01 | Cálculos reproducibles | Unit test |
| F4-03 | Recuperación, fuerza, restricciones y adherencia | F4-01 | Incluye fuentes y limitaciones | Unit test |
| F4-04 | Respuesta individual por estímulo | F4-02 | No declara causalidad sin datos | Test |
| F4-05 | Incertidumbre y confianza | F4-02 | Cada métrica lleva n/dispersión | Test |
| F4-06 | Snapshot y `estado_id` | F4-01 | Hash estable | Test |
| F4-07 | `cli estado` y tarjeta de panel | F4-06 | Visible y legible | Manual + JS |
| F4-08 | Tests con datos sintéticos y copia real | F4-02..06 | Escenarios de borde cubiertos | Suite |

**Criterio de salida:** cada recomendación puede citar un `estado_id` y explicar la confianza de sus datos.

---

#### F5 — Motor de decisión v2

**Objetivo:** recomendaciones con opciones, prioridad, riesgo y métrica.

**Duración:** 7-10 días.

| Tarea | Entregable | Depende de | Aceptación | Prueba |
|---|---|---|---|---|
| F5-01 | Esquema JSON de recomendación y validación | F4 | Rechaza recomendaciones incompletas | Test de esquema |
| F5-02 | Generación de candidatas | F5-01 | 2-4 opciones por prioridad | Test |
| F5-03 | Restricciones duras | F5-02 | Calendario, recuperación, dolor, material | Test |
| F5-04 | Puntuación y desempate | F5-03 | Score auditable; pesos configurables | Test |
| F5-05 | Explicación determinista | F5-04 | Sin cifras nuevas | Test |
| F5-06 | Tablas y guardado de opciones/versiones | F5-01 | Todo queda registrado | Test DB |
| F5-07 | `dual-run` v1/v2 | F5-06 | Se pueden comparar sin mostrar v2 | Script |
| F5-08 | Seguridad y derivación | F5-03 | Dolor/lesión ⇒ parar | Test |
| F5-09 | Tests de prioridad, mínimo eficaz y alternativas | F5-02..05 | Cobertura de casos | Suite |

**Criterio de salida:** v2 genera una decisión completa y explicable; v1 sigue disponible por flag.

---

#### F6 — Bucle de resultados

**Objetivo:** aprender de lo que se propone, se hace y pasa.

**Duración:** 4-6 días.

| Tarea | Entregable | Depende de | Aceptación | Prueba |
|---|---|---|---|---|
| F6-01 | Enlace recomendación → sesión/parte/apunte | F5 | Integridad referencial | Test |
| F6-02 | Catálogo de métricas por regla | F5 | Cada regla tiene métrica o `sin_datos` | Validación |
| F6-03 | Evaluación antes/después con confounders | F6-01 | Informa de limitaciones | Test |
| F6-04 | Ampliar `verificacion` | F6-03 | Guarda resultado, delta, confianza | Test |
| F6-05 | Informe de aprendizaje | F6-04 | Aciertos/fallos por regla | CLI |
| F6-06 | `cli resultados` y tarjeta de panel | F6-05 | Visible | Manual |
| F6-07 | Tests de aceptada/cambiada/ignorada y resultado | F6-04 | Sin causalidad falsa | Suite |

**Criterio de salida:** una recomendación se puede seguir de principio a fin y decir si funcionó o no.

---

#### F7 — Interfaz

**Objetivo:** que la decisión se entienda en menos de 30 segundos.

**Duración:** 4-6 días.

| Tarea | Entregable | Depende de | Aceptación | Prueba |
|---|---|---|---|---|
| F7-01 | Tarjeta de prioridad/acción | F5 | Una prioridad visible | JS |
| F7-02 | Desplegables de por qué, medición, riesgo, alternativa | F7-01 | No satura | JS |
| F7-03 | Explorador de conocimiento (AF/FU/revisión) | F2 | Se puede auditar | JS |
| F7-04 | “Qué ha cambiado desde la última vez” | F5 | Explica diferencias | JS |
| F7-05 | Historial de recomendaciones y resultados | F6 | Visible | JS |
| F7-06 | Tests Node y accesibilidad básica | F7-01..05 | Sin errores | `comprobar_portal.js` |

**Criterio de salida:** la acción principal se encuentra rápido; el resto no desaparece, se esconde.

---

#### F8 — LLM opcional

**Objetivo:** mejorar explicación y conversación sin comprometer verdad, privacidad ni reproducibilidad.

**Duración:** 5-8 días.

| Tarea | Entregable | Depende de | Aceptación | Prueba |
|---|---|---|---|---|
| F8-01 | ADR de proveedor, privacidad y coste | F7 | Firmado | Revisión |
| F8-02 | `coach_llm.py` con proveedor abstracto | F8-01 | Sin clave en navegador | Test |
| F8-03 | RAG sobre `AF`/`FU` | F2 | Recupera citas correctas | Test |
| F8-04 | Contrato JSON y validadores | F8-03 | Rechaza cifras/citas inválidas | Test |
| F8-05 | UI “explicar”/“preguntar” | F8-04 | Fallback determinista | JS |
| F8-06 | Evaluación baseline vs LLM | F8-05 | Métricas y coste | Informe |
| F8-07 | Tests de privacidad y alucinación | F8-04 | 0 datos crudos; 0 cifras inventadas | Suite |

**Criterio de salida:** el LLM es opcional, seguro y demostrablemente mejor (o se apaga).

---

#### F9 — Despliegue y cierre

**Objetivo:** pasar a producción sin sorpresas.

**Duración:** 3-5 días + 2 semanas de observación.

| Tarea | Entregable | Depende de | Aceptación | Prueba |
|---|---|---|---|---|
| F9-01 | Dual-run 2 semanas | F5/F6 | v1 y v2 comparables | Informe |
| F9-02 | Métricas de éxito | F9-01 | Umbrales cumplidos | Panel |
| F9-03 | Activar v2 por defecto | F9-02 | Rollback probado | Ensayo |
| F9-04 | Documentación | Todas | README, DESPLIEGUE, conocimiento | Revisión |
| F9-05 | Postmortem y backlog | F9-03 | Riesgos residuales | Documento |

**Criterio de salida:** v2 es el motor por defecto; v1 se puede recuperar; el conocimiento es la fuente de verdad.

---

## 12. Estrategia de pruebas

### 12.1. Pirámide

| Nivel | Qué prueba | Dónde |
|---|---|---|
| Unitario | Parser, validación, hash, métricas, scoring | `pruebas/pruebas_basicas.py` o nuevos módulos |
| Integración | Carga TOML + DB + motor | Scripts de prueba |
| Golden | Salidas actuales vs nuevas | `pruebas/golden/` |
| Migración | Base vieja → nueva | Copia de DB |
| Seguridad | Dolor, lesión, contraindicaciones | Tests específicos |
| Privacidad | Payload LLM sin datos crudos | Tests de contrato |
| Rendimiento | `analizar` y recomendación | Medición en Celeron |
| Regresión | Suite completa + Node | CI/local |

### 12.2. Fixtures

- Base sintética mínima: 3 sesiones, 2 semanas, 1 prueba.
- Base real copiada: para golden, nunca para tests que escriban.
- Escenarios:
  - sin datos,
  - datos parciales,
  - dolor,
  - viaje,
  - material,
  - piscina 50,
  - prueba próxima,
  - carga alta,
  - recomendación aceptada/cambiada/ignorada.

### 12.3. Comandos

```bash
# Suite completa
docker compose exec -T entrenador python pruebas/pruebas_basicas.py

# JS del panel
node pruebas/comprobar_portal.js cuadro/panel.html

# Validación del conocimiento
docker compose exec -T entrenador python -m entrenador.cli conocimiento --validar

# Golden
docker compose exec -T entrenador python scripts/golden.py --comparar

# Migración en copia
docker compose exec -T entrenador python scripts/migrar_conocimiento.py --dry-run
```

### 12.4. Definición de “hecho” por tarea

Una tarea solo se cierra si:

1. El código está implementado.
2. Hay test que falla antes y pasa después.
3. Hay evidencia de ejecución.
4. No rompe la suite.
5. Está documentado.
6. Se puede revertir.
7. La matriz de trazabilidad está actualizada.

---

## 13. Migración, compatibilidad y rollback

### 13.1. Esquema

- Todas las tablas nuevas son aditivas.
- Columnas nuevas con `ALTER TABLE ADD COLUMN` en `db.MIGRACIONES`.
- No se renombra ni se borra nada en la misma versión.
- Los índices se crean después de migrar.

### 13.2. Feature flag

```text
MOTOR_CONOCIMIENTO=v1   # por defecto al principio
MOTOR_CONOCIMIENTO=v2   # cuando el piloto esté aprobado
```

La flag se lee en un único sitio y se guarda en la recomendación.

### 13.3. Dual-run

- v1 y v2 generan recomendaciones en paralelo.
- v2 no se muestra hasta que pase el golden y la revisión.
- Se comparan: prioridad, sesión, día, metros, ritmo, explicación.
- Las diferencias se clasifican: mejora, equivalente, regresión, error.

### 13.4. Backfill

- Script `scripts/migrar_conocimiento.py`.
- `--dry-run` por defecto.
- `--apply` requiere backup y confirmación.
- Genera un diff por ID.
- No toca `informes/` original hasta que el diff esté aprobado.

### 13.5. Rollback

1. Cambiar `MOTOR_CONOCIMIENTO=v1`.
2. Reconstruir imagen con el commit anterior.
3. Las tablas nuevas no afectan a v1.
4. Restaurar DB solo si hubo corrupción (no debería).

### 13.6. Copias

- Backup antes de cada migración.
- `sqlite3 .backup`, no copia de fichero a pelo.
- Verificar `PRAGMA integrity_check`.

### 13.7. Rama, commits y tags

- Rama de trabajo: `plan-conocimiento`.
- Un commit por tarea o grupo lógico; el mensaje empieza por el ID (`F1-01: ...`).
- No se mezcla una migración de conocimiento con un cambio de UI en el mismo commit.
- `main` se mantiene desplegable; la rama se integra por fases.
- Tag por fase terminada: `conocimiento-f0`, `conocimiento-f1`, ...
- Cada tag lleva una nota con: tareas hechas, tests ejecutados, `knowledge_version`, riesgos residuales.
- No se hace push al repositorio público si el commit contiene datos personales o rutas con nombres propios.

---

## 14. Trazabilidad

### 14.1. Convención de IDs

| Prefijo | Entidad | Ejemplo |
|---|---|---|
| `FU-` | Fuente | `FU-001` |
| `AF-` | Afirmación | `AF-014` |
| `RG-` | Regla | `RG-002` |
| `PA-` | Parámetro | `PA-001` |
| `ES-` | Estímulo | `ES-003` |
| `RE-` | Receta | `RE-003` |
| `RV-` | Revisión | `RV-2026-10-19-01` |
| `KV-` | Versión de conocimiento | `KV-a1b2c3d4` |
| `F#-` | Fase | `F3` |
| `T#-#` | Tarea | `F3-02` |
| `RQ-` | Requisito | `RQ-03` |
| `D-` | Defecto | `D-01` |

### 14.2. Tablero y estado

- `PLAN_TAREAS.csv` es el tablero de seguimiento (una fila por tarea).
- La columna `estado` empieza en `pendiente` y solo pasa a `en_curso`, `bloqueada`, `hecha` o `descartada`.
- Una tarea no se marca `hecha` sin evidencia y sin actualizar la matriz de la sección 14.3.
- Al cambiar una tarea en este plan, se regenera el CSV con `scripts/exportar_plan_tareas.py`.
- Las tareas descartadas se quedan en el CSV con el motivo, no se borran.

### 14.3. Matriz requisito → tarea → prueba

| Requisito | Tareas | Prueba | Evidencia |
|---|---|---|---|
| RQ-01 Fuente única | F2, F3 | `test_sin_constantes` | Validación |
| RQ-02 Trazabilidad por afirmación | F2, F3 | `test_citas` | Informe de diff |
| RQ-03 Recomendación con opciones | F5 | `test_opciones` | JSON |
| RQ-04 Bucle de resultados | F6 | `test_resultado` | Informe |
| RQ-05 UI útil | F7 | `comprobar_portal.js` | Captura/medida |
| RQ-06 LLM seguro | F8 | `test_llm_guard` | Informe |
| RQ-07 No regresión | F0, F9 | Suite completa | Log |

### 14.4. Evidencia

Cada tarea debe dejar:

- comando ejecutado,
- salida esperada,
- salida real,
- fecha,
- commit,
- versión de conocimiento.

Se guarda en `informes/` (privado) o en `docs/evidencias/` si no contiene datos personales.

### 14.5. Auditoría de recomendación

Cada fila de `recomendacion` debe guardar:

- `knowledge_version`,
- `estado_id`,
- `opciones_json`,
- `elegida`,
- `metrica_exito_json`,
- `revisar_en`,
- `confianza`.

Así se puede responder: “¿por qué el 19/10 se propuso esto?”.

---

## 15. Métricas de éxito

### 15.1. De producto

| Métrica | Baseline | Objetivo |
|---|---|---|
| Tiempo hasta encontrar la acción | > 2 min | < 30 s |
| Recomendaciones con alternativa | 0 % | 100 % |
| Recomendaciones con métrica de éxito | ~0 % | 100 % |
| Citas válidas | No medido | 100 % |
| Recomendaciones evaluadas a 21 días | 0 | ≥ 80 % |
| Reglas con verificación | 1 de 9 | ≥ 80 % |
| Criterios firmados | 0 de 21 | ≥ 80 % |

### 15.2. De calidad

- 0 errores de validación del conocimiento.
- 0 recomendaciones sin `estado_id`.
- 0 parámetros sin procedencia.
- 0 regresiones en la suite.
- 0 datos crudos en payloads de LLM.
- 0 recomendaciones con dolor/lesión sin derivación.

### 15.3. De aprendizaje

- Aciertos/fallos por regla.
- Delta de rendimiento antes/después.
- Adherencia.
- Utilidad percibida (1-5).
- Coste/latencia del LLM.

---

## 16. Riesgos y mitigaciones

| ID | Riesgo | Prob. | Impacto | Mitigación | Disparador |
|---|---|---|---|---|---|
| R-01 | La migración pierde matices | Media | Alto | Dual-run, diff, revisión humana | Cualquier diferencia no explicada |
| R-02 | El plan se eterniza | Alta | Alto | Corte vertical, fases cortas, criterios de salida | Fase > 2 semanas sin entrega |
| R-03 | El LLM alucina | Media | Alto | No núcleo, validadores, citas, fallback | Cifra no trazable |
| R-04 | Fuga de datos personales | Baja | Muy alto | Sin datos crudos, opt-in, retención cero | Payload con FIT/parte |
| R-05 | Corrupción de DB | Baja | Muy alto | Backup, migraciones aditivas, tests | `integrity_check` falla |
| R-06 | Tests frágiles por datos reales | Alta | Medio | Fixtures sintéticos + copia | Test que falla por fecha/dato |
| R-07 | Se duplica conocimiento otra vez | Media | Alto | Test que prohíbe constantes | Grep en CI |
| R-08 | Se sobreajusta al atleta actual | Media | Medio | Reglas + evidencia + revisión | Recomendación que solo vale para un caso |
| R-09 | El atleta no entiende la recomendación | Media | Alto | Tarjeta corta, lenguaje llano, prueba con él | No encuentra la acción |
| R-10 | Cambio de plan/entrenador | Media | Medio | Restricciones y configuración | Días/fechas cambian |
| R-11 | Coste/latencia del LLM | Media | Medio | Cache, límites, solo bajo demanda | > 5 s o coste > umbral |
| R-12 | Dependencia de OpenCode Go | Baja | Medio | Proveedor abstracto, clave propia | Términos o cuota |

---

## 17. Decisiones abiertas

| ID | Decisión | Opciones | Recomendación | Quién decide |
|---|---|---|---|---|
| D-01 | Formato del conocimiento | TOML / JSON / SQLite | TOML + SQLite | Proyecto |
| D-02 | ¿Markdown generado o fuente? | Generado / fuente | Generado | Proyecto |
| D-03 | Alcance inicial | Todo / corte vertical | Corte vertical `R2` | Proyecto |
| D-04 | LLM ahora o después | Ahora / después | Después de F5 | Proyecto |
| D-05 | Proveedor LLM | OpenCode Go / general / local | General con retención cero | Proyecto |
| D-06 | Firma de criterios | Automática / humana | Humana | Entrenador |
| D-07 | Nivel de automatización de extracción | Manual / IA + revisión | IA + revisión | Proyecto |
| D-08 | Ventana de estado | 14 / 28 / 90 / histórico | 7-28-90 + histórico con decaimiento | Proyecto |

Si no hay decisión, se aplican las recomendaciones por defecto y se anotan en el ADR.

---

## 18. Checklist de arranque

### Antes de F0

- [ ] Aprobar este plan.
- [ ] Confirmar que `informes/` sigue siendo privado.
- [ ] Confirmar backup y acceso a la copia.
- [ ] Confirmar que no hay cambios sin commit en los repositorios.
- [ ] Confirmar la versión de Docker/Caddy.

### En cada fase

- [ ] Tareas con ID y dependencia.
- [ ] Test que falla antes.
- [ ] Implementación.
- [ ] Test que pasa.
- [ ] Evidencia guardada.
- [ ] Documentación actualizada.
- [ ] Matriz de trazabilidad actualizada.
- [ ] Rollback probado.
- [ ] Revisión del entrenador si toca firma.

### Antes de producción

- [ ] `conocimiento --validar` sin errores.
- [ ] Suite Python y Node verdes.
- [ ] Golden diff revisado.
- [ ] Backup reciente.
- [ ] `MOTOR_CONOCIMIENTO` configurable.
- [ ] Prueba de rollback.
- [ ] Monitorización de errores.
- [ ] Documentación de usuario.

---

## 19. Anexos

### Anexo A — Mapa de conocimiento hardcodeado

Inventario verificado el 2026-10-19 (F0-02) sobre `estimulos.py`, `reglas.py`, `planificador.py`,
`plan.py`, `plan_vivo.py`, `evaluacion.py`, `decision.py`, `valoracion.py`, `fuerza.py`,
`descanso.py` y `parciales.py`. Una fila por constante **o grupo de constantes** (45 filas para 64
constantes de módulo; algunas filas agrupan varias). `—` = no es conocimiento de natación
(enumeración, nombre o dato del atleta) y no se migra. Los umbrales que no son conocimiento de
entrenamiento se declaran fuera de alcance en el Anexo G.

| Actual | Nuevo | Tarea | Estado |
|---|---|---|---|
| `estimulos.CLASES` | `conocimiento/estimulos.toml` (`ES-*`) | F3-01 | pendiente |
| `estimulos.CONOCIMIENTO` | enlaces `ES-*` → `AF-*` | F3-01 | pendiente |
| `estimulos.MATERIAL` | `conocimiento/estimulos.toml` | F3-01 | pendiente |
| `estimulos.RECETAS` | `conocimiento/recetas.toml` (`RE-*`) | F3-03 | pendiente |
| `estimulos.RECETA_DE_CLASE` | `conocimiento/recetas.toml` | F3-03 | pendiente |
| `estimulos.LENTO_SOBRE_OBJETIVO` (25,0 s/100) | `PA-*` (banda de calentamiento) | F3-02 | pendiente |
| `estimulos.VENTANA_DIAS` (14) | `PA-*` (ventana de decisión) | F4-02 | pendiente |
| `estimulos.DIAS_SIN_PARAR` (7,0) | `PA-*` | F3-02 | pendiente |
| `estimulos.MIN_CONTINUO_M` (1.200 m) | `PA-*` | F3-02 | pendiente |
| `reglas.REGLAS` | `conocimiento/reglas.toml` (`RG-*`) | F3-02 | pendiente |
| `reglas.CONOCIMIENTO` | enlaces `RG-*` → `AF-*`/`PA-*` | F3-02 | pendiente |
| `reglas.REPARTO_OBJETIVO` | `PA-*` + `RG-*` | F3-02 | pendiente |
| `reglas.MINIMOS_OBLIGATORIOS` | `PA-*` | F3-02 | pendiente |
| `reglas.FUENTES` | catálogo `FU-*` (`conocimiento/fuentes.toml`) | F2-01/F3-02 | pendiente |
| `reglas.GRADOS` | enumeración (no es conocimiento) | — | — |
| `planificador.DIAS`, `DIAS_ENTRENADOR`, `DIA_BICI`, `DIAS_PROPIOS`, `DIAS_CALIDAD`, `DIAS_LARGOS` | `conocimiento/calendario.toml` | F3-03 | pendiente |
| `planificador.DURO_H` (24,0) | `PA-*` | F3-02 | pendiente |
| `plan.KILOMETROS_SEMANA` | dato del plan / `PA-*` | F3-04 | pendiente |
| `plan.SEMANAS` / `BLOQUES` | dato del atleta, no conocimiento | F3-04 | pendiente |
| `plan.OBJETIVO_A` / `OBJETIVO_B` / `OBJETIVOS` | dato del atleta (marca objetivo) | F3-04 | pendiente |
| `plan.ENTRENADOR`, `PISCINA`, `REGLAS`, `DECISIONES`, `FASES`, `FASE_POR_DEFECTO`, `DIAS_SEMANA` | dato/mixto del plan escrito | F3-04 | pendiente |
| `plan_vivo.TOPE_SUBIDA_PCT` (10,0) | `PA-*` | F3-02 | pendiente |
| `plan_vivo.UMBRAL_CUMPLIR` (0,7) | `PA-*` | F3-02 | pendiente |
| `plan_vivo.BAJADA_DERIVA` (0,8) | `PA-*` | F3-02 | pendiente |
| `plan_vivo.TOPE_DESCARGA` (0,8) | `PA-*` | F3-02 | pendiente |
| `plan_vivo.REGLAS_DE_CARGA` | `conocimiento/reglas.toml` (`RG-*`) | F3-02 | pendiente |
| `evaluacion.TOLERANCIA_RITMO` (1,5) | `PA-*` | F3-02 | pendiente |
| `evaluacion.MIN_CUMPLE_REPS` (0,8) | `PA-*` | F3-02 | pendiente |
| `evaluacion.DESCANSO_FUSION_S` (15,0) | `PA-*` | F3-02 | pendiente |
| `evaluacion.ESTADOS` | enumeración (no es conocimiento) | — | — |
| `decision.MOTIVA` | `conocimiento/reglas.toml` (regla que motiva) | F3-02 | pendiente |
| `decision.METRICAS` | `conocimiento/reglas.toml` (`metrica_exito`) | F6-02 | pendiente |
| `decision.ESTADOS` | enumeración (no es conocimiento) | — | — |
| `valoracion.AYUDA_MATERIAL` | `conocimiento/estimulos.toml` (descuentos de material) | F3-01 | pendiente |
| `valoracion.DIAS_SEMANA` (7) | `PA-*` (ventanas) | F4-02 | pendiente |
| `valoracion.DIAS_MES` (30) | `PA-*` (ventanas) | F4-02 | pendiente |
| `valoracion.DIAS_FIJOS` (42) | `PA-*` (ventanas) | F4-02 | pendiente |
| `valoracion.PISCINA` | dato del atleta | F3-04 | pendiente |
| `valoracion.INTENSAS` | `PA-*` / configuración de referencias | F3-02 | pendiente |
| `fuerza.DOSIS_POR_DEFECTO` (12 semanas, 2/semana, 5 ejercicios, 12 reps) | `conocimiento/reglas.toml` (dosis preventiva T.7) | F3-02 | pendiente |
| `fuerza.RPE_DURO` (8) | `PA-*` | F3-02 | pendiente |
| `fuerza.PALABRAS_DOLOR` | `conocimiento/reglas.toml` (seguridad T.7: parar y derivar) | F3-02 | pendiente |
| `fuerza.GRUPOS_QUE_CUENTAN` | `PA-*` (qué grupos cuentan como fuerza) | F3-02 | pendiente |
| `descanso.SUENO_CORTO_H` (6,5), `SUENO_REGULAR` (70), `SUENO_CORTO_COMO` (40), `SENSACION_BAJA` (40), `FEEL_BAJO` (25) | `PA-*` (umbrales de recuperación) | F3-02/F4-03 | pendiente |
| `parciales.RITMO_TOPE_400_S` (90) / `RITMO_TOPE_LARGO_S` (93) | `PA-*` (referencias de ritmo) | F3-02 | pendiente |

Nota: además de estas constantes de módulo hay **números sueltos dentro de funciones** (porcentajes,
tolerancias y bandas) que se recogen al migrar cada módulo en F3; no se listan uno a uno aquí porque no
son símbolos con nombre. La verificación de F3-06 (`grep` + test) es la que cierra el inventario.

### Anexo B — Esquema mínimo de recomendación

Ver sección 7.1. Validación obligatoria:

- `id`, `fecha`, `knowledge_version`, `estado_id`.
- `prioridad` 1-3.
- `opciones` ≥ 2.
- `evidencia` ≥ 1.
- `metrica_exito`.
- `revisar_en`.
- `contraindicaciones` (puede ser vacío).

### Anexo C — Contrato LLM

Ver sección 10.3. Reglas:

1. No inventar cifras.
2. No inventar citas.
3. No dar consejo médico.
4. No decidir carga.
5. Si no sabe, lo dice.

### Anexo D — Glosario

| Término | Significado |
|---|---|
| Afirmación | Frase atómica que se puede citar y revisar |
| Regla | Condición → acción ejecutable |
| Parámetro | Número con unidad, procedencia y firma |
| Estímulo | Tipo de entrenamiento y su efecto/coste |
| Receta | Sesión concreta construida con estímulos |
| Estado | Foto versionada de lo que se sabe del atleta |
| Opción | Alternativa de sesión/plan evaluada |
| Verificación | Si la regla acertó con el resultado |
| `KV-*` | Versión del conocimiento |
| `estado_id` | Versión del estado del atleta |

### Anexo E — DDL propuesto (borrador)

El esquema definitivo se valida en F2/F5. Todo es aditivo; las columnas nuevas en tablas existentes van por
`db.MIGRACIONES`, nunca en el `CREATE TABLE IF NOT EXISTS` (una base vieja no las tendría).

```sql
-- Versión del conocimiento usada por una pasada.
CREATE TABLE IF NOT EXISTS conocimiento_version (
  id          TEXT PRIMARY KEY,   -- KV-xxxxxxxx
  creado_en   TEXT NOT NULL,
  hash        TEXT NOT NULL,
  ficheros    TEXT,               -- lista de ficheros y su hash
  notas       TEXT
);

CREATE TABLE IF NOT EXISTS fuente (
  id            TEXT PRIMARY KEY, -- FU-001
  tipo          TEXT NOT NULL,
  titulo        TEXT,
  autores       TEXT,
  anio          INTEGER,
  url           TEXT,
  doi           TEXT,
  cita          TEXT,
  poblacion     TEXT,
  intervencion  TEXT,
  resultado     TEXT,
  limitaciones  TEXT,
  certeza       TEXT,
  revisado_por  TEXT,
  revisado_en   TEXT
);

CREATE TABLE IF NOT EXISTS afirmacion (
  id            TEXT PRIMARY KEY, -- AF-001
  texto         TEXT NOT NULL,
  condiciones   TEXT,
  efecto        TEXT,
  direccion     TEXT,             -- mejora | neutro | empeora | incierto
  tamano        TEXT,
  aplicabilidad TEXT,
  certeza       TEXT,
  estado        TEXT NOT NULL DEFAULT 'propuesta', -- propuesta | revisada | rechazada
  firma_id      TEXT
);

CREATE TABLE IF NOT EXISTS afirmacion_fuente (
  afirmacion_id TEXT NOT NULL REFERENCES afirmacion(id) ON DELETE CASCADE,
  fuente_id     TEXT NOT NULL REFERENCES fuente(id) ON DELETE CASCADE,
  cita_local    TEXT,
  PRIMARY KEY (afirmacion_id, fuente_id)
);

CREATE TABLE IF NOT EXISTS parametro (
  id           TEXT PRIMARY KEY,  -- PA-001
  nombre       TEXT NOT NULL,
  valor        TEXT NOT NULL,
  unidad       TEXT,
  procedencia  TEXT NOT NULL,     -- evidencia | criterio_firmado | historial | pactado
  fuente_id    TEXT REFERENCES fuente(id),
  afirmacion_id TEXT REFERENCES afirmacion(id),
  firmado_por  TEXT,
  firmado_en   TEXT,
  nota         TEXT
);

CREATE TABLE IF NOT EXISTS regla (
  id           TEXT PRIMARY KEY,  -- RG-002
  version      INTEGER NOT NULL DEFAULT 1,
  enunciado    TEXT NOT NULL,
  cuando_json  TEXT NOT NULL,
  entonces_json TEXT NOT NULL,
  confianza    REAL,
  estado       TEXT NOT NULL DEFAULT 'revisada',
  revisar_en_dias INTEGER,
  metrica_exito_json TEXT
);

CREATE TABLE IF NOT EXISTS regla_afirmacion (
  regla_id      TEXT NOT NULL REFERENCES regla(id) ON DELETE CASCADE,
  afirmacion_id TEXT NOT NULL REFERENCES afirmacion(id) ON DELETE CASCADE,
  papel         TEXT,             -- motiva | limita | avisa
  PRIMARY KEY (regla_id, afirmacion_id, papel)
);

CREATE TABLE IF NOT EXISTS regla_parametro (
  regla_id     TEXT NOT NULL REFERENCES regla(id) ON DELETE CASCADE,
  parametro_id TEXT NOT NULL REFERENCES parametro(id) ON DELETE CASCADE,
  PRIMARY KEY (regla_id, parametro_id)
);

CREATE TABLE IF NOT EXISTS estimulo (
  id          TEXT PRIMARY KEY,   -- ES-001
  nombre      TEXT NOT NULL,
  entrena     TEXT,
  no_entrena  TEXT,
  recuperacion_h REAL,
  coste       TEXT,
  papel_400   TEXT,
  papel_3000  TEXT
);

CREATE TABLE IF NOT EXISTS receta (
  id          TEXT PRIMARY KEY,   -- RE-001
  nombre      TEXT NOT NULL,
  sesion      TEXT NOT NULL,
  metros      REAL,
  reps        INTEGER,
  dist_m      REAL,
  ritmo_rel   TEXT,
  descanso_s  REAL,
  salida_s    REAL,
  desde_dia   TEXT,
  porque      TEXT,
  progresion  TEXT,
  regresion   TEXT
);

CREATE TABLE IF NOT EXISTS receta_paso (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  receta_id  TEXT NOT NULL REFERENCES receta(id) ON DELETE CASCADE,
  orden      INTEGER NOT NULL,
  texto      TEXT NOT NULL,
  tipo       TEXT,                -- calentamiento | serie | suelta
  metros     REAL,
  ritmo_100  TEXT,
  descanso_s REAL,
  material   TEXT,
  intensidad TEXT
);

-- Foto versionada del atleta.
CREATE TABLE IF NOT EXISTS estado_atleta (
  id           TEXT PRIMARY KEY,
  fecha        TEXT NOT NULL,
  version_hash TEXT NOT NULL,
  json         TEXT NOT NULL,
  creado_en    TEXT NOT NULL
);

-- Opciones de una recomendación.
CREATE TABLE IF NOT EXISTS recomendacion_opcion (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  recomendacion_id INTEGER NOT NULL REFERENCES recomendacion(id) ON DELETE CASCADE,
  opcion_id        TEXT NOT NULL,   -- A, B, C
  recomendada      INTEGER NOT NULL DEFAULT 0,
  sesion_json      TEXT NOT NULL,
  efecto_esperado  TEXT,
  confianza        REAL,
  riesgo           TEXT,
  coste            TEXT,
  porque           TEXT,
  UNIQUE (recomendacion_id, opcion_id)
);

-- Resultado de una recomendación.
CREATE TABLE IF NOT EXISTS resultado (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  recomendacion_id INTEGER NOT NULL REFERENCES recomendacion(id) ON DELETE CASCADE,
  actividad_id     INTEGER REFERENCES actividad(id),
  metrica          TEXT NOT NULL,
  antes            REAL,
  despues          REAL,
  delta            REAL,
  confianza        TEXT,
  confounders_json TEXT,
  evaluado_en      TEXT
);
```

Columnas nuevas en tablas existentes (por `MIGRACIONES`):

| Tabla | Columna | Tipo | Para qué |
|---|---|---|---|
| `recomendacion` | `knowledge_version` | `TEXT` | Qué conocimiento la produjo |
| `recomendacion` | `estado_id` | `TEXT` | Qué foto del atleta se usó |
| `recomendacion` | `prioridad` | `INTEGER DEFAULT 3` | Orden |
| `recomendacion` | `elegida` | `TEXT` | Opción A/B/C |
| `recomendacion` | `metrica_exito_json` | `TEXT` | Cómo se mide |
| `recomendacion` | `revisar_en` | `TEXT` | Fecha de revisión |
| `recomendacion` | `confianza` | `REAL` | Confianza de la recomendación |
| `verificacion` | `resultado` | `TEXT` | `a_favor`, `en_contra`, `sin_datos`, `no_concluyente` |
| `verificacion` | `delta` | `REAL` | Cambio medido |
| `verificacion` | `confianza` | `TEXT` | Confianza del veredicto |
| `verificacion` | `aprendizaje` | `TEXT` | Qué se aprende |

### Anexo F — Compatibilidad de API

Mientras dura la migración, las funciones actuales se mantienen como envoltorios. No se rompe ningún llamador.

| API actual | Nueva implementación | Envoltorio se elimina en |
|---|---|---|
| `conocimiento.secciones` | `conocimiento.cargar().secciones` | F3 |
| `conocimiento.seccion` | `cargar().seccion` | F3 |
| `conocimiento.fuente_de` | enlaces `RG/AF/PA` | F3 |
| `conocimiento.sin_fuente` | criterios sin firma | F1/F3 |
| `conocimiento.afirmaciones_sin_fuente` | 22 cláusulas (21 líneas marcadas) | F1 |
| `conocimiento.revision` / `marcar_revision` | igual | F3 |
| `conocimiento.cuadro_revision` | igual + versión | F2 |
| `estimulos.CLASES` / `RECETAS` | `ES-*` / `RE-*` | F3 |
| `estimulos.clasificar` / `perfil` / `deficits` / `recetas` | mismo API, leen del conocimiento | F3 |
| `reglas.REGLAS` / `REPARTO_OBJETIVO` / `MINIMOS_OBLIGATORIOS` | `RG-*` / `PA-*` | F3 |
| `reglas.reparto_objetivo` / `cita` / `por_fuente` / `fuente_de` | igual | F3 |
| `planificador.reparto` / `propuesta_semana` | usa conocimiento y estado | F5 |
| `valoracion.discurso` / `texto` / `sesion` | motor + explicación | F5 |
| `decision.registrar` / `proponer_semana` / `verificar` | esquema nuevo | F5/F6 |
| `plan.SEMANAS` / `BLOQUES` | dato del atleta, no conocimiento | — |

Regla: ningún envoltorio se elimina hasta que no queden llamadores en `entrenador/`, `scripts/` ni `pruebas/`.

### Anexo G — Superficie que NO se toca

Para acotar el riesgo, estas partes se consideran congeladas salvo que una tarea lo justifique:

- `entrenador/lector_fit.py`, `entrenador/lector_gpx.py` (lectura de ficheros).
- `entrenador/importar.py` (importación incremental).
- `entrenador/bici.py`, `entrenador/segmentos_gpx.py`, `entrenador/portal.py` (portal de bici).
- `entrenador/competicion.py` (RFEN).
- `entrenador/gimnasio.py` (solo se consumen datos); `entrenador/fuerza.py` se toca solo para migrar su conocimiento de F3-02.
- `entrenador/sueno.py` (solo se consume).
- `docker-compose.yml`, `Dockerfile`, Caddy (solo se toca si una tarea lo pide).

#### Umbrales de proceso fuera del alcance de F3

No son conocimiento de entrenamiento (no prescriben carga): son reglas de reconstrucción,
segmentación, formato o presentación. Se quedan en su módulo y **no se migran** a `conocimiento/` en
F3; si alguna pasa a afectar una decisión, se abre tarea y se justifica.

| Módulo | Constantes | Por qué no se migra |
|---|---|---|
| `series.py` | `DIST_MAX_SERIE_M`, `DESCANSO_MAX_S`, `MIN_REPS_SERIE`, `MIN_REPS_COMPARABLE` | reconstrucción de series desde los laps; `DIST_MAX_SERIE_M` es un tope de parser, no una regla de entrenamiento |
| `series_dia.py` | `COBERTURA_MIN`, `MIN_SERIE_M` | unificar parte y reloj |
| `analitica.py` | `MIN_BLOQUE_M`, `PASO_M`, `TIERS` | segmentación de la analítica |
| `aprendizaje.py` / `concepto.py` | `MARGEN_POR_DEFECTO`, `MIN_REPS`, `DESCANSO_MISMO_BLOQUE_S`, `MIN_BLOQUES_RUIDO`, `MIN_REPS_MARGEN` | umbrales estadísticos de forma y ruido |
| `parciales.py` | `MIN_PASOS_M`, `CADA_M` | desglose y presentación de pasos (los topes de ritmo sí están en el Anexo A) |
| `partes.py` | `DESCANSO_MAX_S`, `PASO_M`, `MIN_CORTES`, `MATERIALES`, `INTENSIDADES`, `ESTILOS_*`, `COMPANIAS` | catálogo de formato y agrupación del parte |
| `competicion.py` | `DIST_MINIMA`, `RITMO_RARO` | validación de marcas RFEN (módulo congelado) |
| `bici.py`, `segmentos_gpx.py`, `portal.py` | `RADIO_M`, `VMAX_M_S`, `CELDA_M`, `PASO_TRAZA_M`, … | portal de bici (congelado) |
| `lector_fit.py`, `lector_gpx.py`, `importar.py` | `DISCIPLINAS`, `EXTENSIONES`, `MIN_METROS`, … | lectura e importación (congelado) |
| `gimnasio.py`, `apuntes.py`, `sueno.py` | `PLANTILLA`, `DIAS`, `TIPOS`, `CAMPOS` | catálogo y datos, no prescripción |
| `panel.py`, `servidor.py`, `db.py` | `ANCHO_PX`, `PUERTO_POR_DEFECTO`, `ESQUEMA`, … | infraestructura |
| `pruebas.py` | `TIPOS`, `MEDIDAS`, `SEGUNDOS_FIJOS` | catálogo de pruebas de medición, no carga |

---

## 20. Primer paso concreto propuesto

Si se aprueba, el orden inmediato es:

1. **F0-01**: backup, tag, inventario y baseline.
2. **F1-01/F1-02**: arreglar `T.9` y el parser de fuentes.
3. **F2-01/F2-02**: esquema TOML y loader.
4. **Corte vertical `R2`**:
   - `AF-*` de ritmo de prueba,
   - `RG-002`,
   - `PA-*` de 400 m y ventana,
   - `RE-003`,
   - estado mínimo,
   - dos opciones,
   - métrica de éxito,
   - recomendación guardada,
   - resultado.

Cuando ese corte funcione, se replica el patrón para el resto.

---

**Fin del plan.**
