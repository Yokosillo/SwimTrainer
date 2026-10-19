# Reescritura del historial público (R-01)

**Fecha:** 2026-10-19  
**Motivo:** el historial de `Yokosillo/SwimTrainer` contenía `informes/` y otros datos personales
(nombres, club, sedes y marcas) en commits antiguos. El árbol actual estaba limpio, pero Git y GitHub
conservaban esos objetos.

## Qué se hizo

1. Copia espejo completa del repositorio antes de tocar nada, en
   `/tmp/opencode/backup-entrenador/` (fuera del repositorio).
2. `git filter-repo` en tres pasadas:
   - fuera `informes/` de todo el historial;
   - sustitución de nombres, club y sedes por valores genéricos;
   - fuera `entrenador/plan.py` del historial (contenía marcas, fechas y semanas personales) y
     sustitución de marcas y fechas en los blobs antiguos.
3. El `entrenador/plan.py` actual es genérico; el plan real vive en
   `entrenador/plan_local.py`, ignorado por git y guardado en el repo privado.
4. `git push --force` de `main`, `plan-conocimiento` y del tag `conocimiento-f0-base`.
5. Verificación: no quedan rutas `informes/`, ni nombres, club, sedes o marcas personales en
   ningún commit del historial publicado.

## Consecuencias

- Los hashes de commit anteriores a la reescritura **ya no existen**. La documentación usa los
  hashes nuevos; la referencia estable es el mensaje de commit y el ID de tarea.
- Cualquier clon antiguo debe descartarse y volver a clonar.
- GitHub puede conservar objetos antiguos en caché hasta que los purgue. No había forks.
  Si se quiere eliminación completa, hay que abrir una petición a GitHub Support.
- La imagen Docker local contiene `plan_local.py`; **no se publica**. `perfil_local.py` es opcional y, si no existe, el panel se pinta sin nombre.

## Verificación reproducible

```bash
git log --all --oneline -- informes
git log --all --oneline -- entrenador/plan.py
git rev-list --all --objects | grep ' informes/'
```

La búsqueda de identificadores concretos se hace con el patrón privado que vive en el repositorio
privado, no en esta documentación pública. El resultado esperado es vacío (salvo el prefijo
histórico de la migración de `localStorage`, que no identifica a nadie).
