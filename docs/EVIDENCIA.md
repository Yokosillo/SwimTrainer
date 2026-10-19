# Protocolo de evidencia

**Estado:** vigente desde 2026-10-19 (F0-06)
**Alcance:** todas las tareas de `PLAN_MEJORA_CONOCIMIENTO.md` y su tablero `PLAN_TAREAS.csv`.

## 1. Para qué

El plan exige que cada tarea deje **comando + salida + fecha + commit** (INV-12) y que una tarea no se
marque `hecha` sin prueba (INV-12 y §12.4). Este documento dice exactamente qué se guarda, dónde y con
qué formato, para que otra persona (o el revisor) pueda repetirlo sin preguntar.

Regla corta: **si no está la evidencia, la tarea no está hecha.**

## 2. Qué se guarda por tarea

Por cada tarea, como mínimo:

| Campo | Qué |
|---|---|
| ID | `F0-01`, `F1-02`… (el mismo del plan y del CSV) |
| Fecha | ISO 8601 con zona, `2026-10-19T17:35:11+02:00` |
| Commit | Hash del repo público (y del privado, si aplica) |
| Comando | La orden exacta, copiable |
| Salida | La salida real (recortada si es larga, sin perder el veredicto) |
| Resultado | `ok` / `fallo` / `bloqueada`, y por qué |
| Prueba | El test o script que cubre la tarea |
| Riesgos | Lo que queda abierto o se ha decidido de otra forma |

Cuando la tarea produce un fichero (informe, snapshot, lista), se guarda **el fichero** además del
comando.

## 3. Dónde se guarda

| Contenido | Sitio | ¿Git? |
|---|---|---|
| Evidencia **sin** datos del atleta (comandos, salidas de tests, diffs de código) | `docs/evidencias/` | Sí (repo público) |
| Evidencia **con** datos del atleta (conteos de sesiones, marcas, planes, snapshots) | `informes/` del repo privado (`SwimTrainer-personal`) | Sí (repo privado) |
| Salidas grandes o regenerables (golden, JSON de analítica, copias de la base) | `data/derived/` | No (`gitignore`) |
| Copias de seguridad de la base | `data/derived/copias/` | No (`gitignore`) |

**Nunca** se copian datos personales a `docs/evidencias/`, al README ni a ningún fichero trackeado del
repo público. En caso de duda, va al privado.

## 4. Formato

Un fichero Markdown por fase o por tarea, en `docs/evidencias/` o `informes/`:

```markdown
# Evidencia — F1-02

- **Fecha:** 2026-10-19T17:40:00+02:00
- **Commit:** `abc1234` (público) / `def5678` (privado, si aplica)
- **Resultado:** ok
- **Prueba:** `pruebas/pruebas_basicas.py` → `pruebas_conocimiento_fuentes`

## Comando

```bash
docker compose exec -T entrenador python -m entrenador.cli conocimiento --validar
```

## Salida

```text
Anexo T: 10 secciones, 22 fuentes, 0 errores, 1 aviso.
  [!] [24] definida y no citada
```

## Notas

- La cita `[24]` es un aviso, no un error: no invalida el documento.
- Se comprobó también con `--json` (código de salida 0).
```

## 5. Evidencia de pruebas

Las pruebas obligatorias se pegan **literalmente** al final de la entrega de la fase:

```bash
cd <ruta-del-proyecto>/SwimTrainer
docker compose up -d --build
docker compose exec -T entrenador python pruebas/pruebas_basicas.py
docker compose exec -T entrenador python -m entrenador.cli conocimiento --validar
node pruebas/comprobar_portal.js cuadro/panel.html
python scripts/exportar_plan_tareas.py
```

De cada una se guarda: comando, código de salida y la última línea (o el bloque de fallo si lo hay).
Los *golden* se guardan y comparan con `scripts/golden.py` (ver README): un cambio de salida sin
justificar es un fallo, no una actualización automática.

## 6. Códigos de salida

| Código | Significado |
|---|---|
| `0` | Todo correcto |
| `1` | Hay errores de validación, diferencias golden o tests en rojo |
| `2` | Uso incorrecto de un comando (argparse) |

Un comando que no se puede ejecutar (falta la base, falta el contenedor) **no** es un `0`: se anota
como bloqueo con el error real.

## 7. Relación con el tablero

1. Se ejecuta la tarea y se guarda la evidencia.
2. Se actualiza `estado` en `PLAN_TAREAS.csv` (`pendiente`, `en_curso`, `bloqueada`, `hecha`,
   `descartada`). Solo `hecha` si hay evidencia y la prueba pasa.
3. `python scripts/exportar_plan_tareas.py` regenera el CSV conservando los estados.
4. Se hace el commit con el ID al principio del mensaje (`F1-02: ...`).

## 8. Retención y limpieza

- Las copias de la base se conservan mientras dure la migración; se borran cuando haya una copia
  verificada posterior y el entrenador lo autorice.
- Los golden se regeneran cuando cambia el comportamiento **a propósito**; el cambio se justifica en
  el mensaje del commit y en la evidencia.
- La evidencia no se reescribe para que quede bonita: se añade una nota con la corrección.
