# Entrenador - gestion de entrenamientos

Aplicacion **local** para gestionar los entrenamientos (natacion, bicicleta, carrera, gimnasio) a partir
de los ficheros del reloj Garmin y de los exports de Strava. Todo se guarda en el equipo del atleta:
**ninguna dato sale a ningun servicio externo**.

Proyecto personal. Los anexos (diagnostico, base de conocimiento y planificacion) se quedan en el
repositorio **privado** del atleta: llevan sus marcas, sus ritmos y sus notas, y este repositorio es publico.

## Lo que no esta en el repositorio

- Los anexos (`informes/`): el diagnostico, el plan y la base de conocimiento. Son personales: viven en el
  repositorio privado del atleta (`SwimTrainer-personal`) y en su equipo.
- Los datos: la base (`data/entrenador.db`), los exports del reloj y de Strava.
- El nombre, el club y el sello del atleta: viven en `entrenador/perfil_local.py`, que no se sube. La aplicacion
  los lee de ahi (`entrenador/perfil.py`); sin ese fichero el portal se pinta sin nombre.
- El entorno (`.venv/`), las dependencias de Node (`node_modules/`) y todo lo generado (`cuadro/`).

## Las dos partes del proyecto

Son **dos portales separados**, cada uno con su pagina:

1. **Entrenamiento** (natacion y gimnasio): reconstruir lo que se ha entrenado, descubrir los segmentos de
   natacion que se repiten (bloques y series) y compararlos entre si. Ver `entrenador/analitica.py` y
   `entrenador/series.py`. Su pagina es **`cuadro/panel.html`**.
2. **Portal de bici, tipo Strava**: comparar los resultados de un mismo tramo entre salidas y encontrar los
   segmentos que se repiten. Los tiempos se miden **sobre las trazas GPS propias**, no se copian de ninguna
   web. Ver `entrenador/bici.py` y `entrenador/segmentos_gpx.py`. Su pagina es **`cuadro/strava/index.html`**
   (pestanas de Actividades y Segmentos, mapa, ficha de cada salida y todos los tiempos de cada segmento).
   El catalogo que se ve en el portal son **3.760 segmentos descubiertos de las trazas** y **105.935
   intentos** medidos (mas los 42 segmentos que ya venian del export de Strava, con sus 1.756 intentos, que se
   conservan por el nombre).

El cuadro de mando (`cuadro/panel.html`) ya no repite la parte de bici: enlaza con el portal de bici.

## Estado

- [x] Auditoria de los datos de origen (1.545 actividades, 854 de natacion) - `scripts/audit_0*.py`
- [x] Base de datos con importacion incremental desde FIT **y GPX** - `entrenador/`
- [x] Reconstruccion de series de natacion y catalogo - `informes/C1_catalogo_series.md`
- [x] Portal 1: cuadro de mando + analitica de segmentos de natacion - `cuadro/panel.html`
- [x] Portal 1: bloque de gimnasio (lo que hay: duracion; lo que falta: ejercicios, series, pesos) - `analitica.gimnasio()`
- [x] Portal 2: segmentos de bici del export, trazas GPS y comparacion de resultados - `entrenador/bici.py`
- [x] Portal 2: **mineria de segmentos propios desde los GPX** (los que no trae el export) - `entrenador/segmentos_gpx.py`
- [x] Marcas oficiales de competicion de la RFEN (historico completo) en la base - `entrenador/competicion.py`
      De ellas, **211 son marcas suyas**, **355 pases** (tramos dentro de otra prueba de la misma jornada) y
      **13 datos raros** (8 corruptas en la federacion + 5 con el tiempo mal puesto). El icono de parcial de la
      federacion no decide solo: el criterio mira la jornada entera (fecha + hora + sede), el ritmo y el estilo
      de la prueba mas larga de ese dia (ver `informes/P_pases_y_pruebas_completas.md`).
- [x] Portal 2: **pagina del portal** con actividades, mapa, ficha de salida y todos los tiempos de cada segmento - `entrenador/portal.py`
- [x] Cuadro de mando rehecho como **aplicacion local** (menu, pestanas, filtros en el navegador) - `entrenador/app/`
- [x] **Gimnasio completo**: pedir trabajo, apuntar la sesion hecha y recibir la que manda el programa - `gimnasio_peticion` / `gimnasio_sesion` / `gimnasio_prescrita`
- [ ] Motor de ritmos de referencia a partir de los tests - pendiente
- [ ] Importacion desde Garmin Connect / Strava API en rutina - pendiente (el importador de carpeta ya funciona)

## Requisitos

Python 3.12 con `fitdecode` y `gpxpy`, en el entorno virtual `.venv` del proyecto:

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/Scripts/python.exe fitdecode gpxpy
```

## Despliegue con Docker

El proyecto se puede servir en red con Docker, sin instalar Python en la maquina: la imagen lleva el
codigo y las dependencias, y `data/`, `informes/` y `cuadro/` se montan desde el disco. El puerto se
publica solo en `127.0.0.1`; delante va Caddy (u otro proxy) con contrasenia. Los pasos completos,
la integracion con Caddy en `/entrenador/` y las copias de seguridad estan en **`DESPLIEGUE.md`**.

```bash
cp .env.example .env          # poner ENTRENADOR_CLAVE
docker compose up -d --build
```

## Uso

```bash
# 1. Crear la base de datos (data/entrenador.db)
.venv/Scripts/python.exe -m entrenador.cli init

# 2. Cargar el historico desde un export de Strava ya descomprimido
.venv/Scripts/python.exe -m entrenador.cli importar-strava data/export_2026-10-11

# 3. Cargar ficheros FIT sueltos (reloj por cable USB o export de Garmin Connect)
.venv/Scripts/python.exe -m entrenador.cli importar "F:/GARMIN/ACTIVITY" --fuente garmin_usb

# 3b. Traerlos de la nube de Garmin Connect (paso a paso, ver informes/Q_garmin_connect.md)
#     El primer login es el .bat de doble clic `conectar-garmin.bat` (la contrasenia se teclea ahi, no se guarda)
.venv/Scripts/python.exe scripts/garmin_conectar.py estado
.venv/Scripts/python.exe scripts/garmin_conectar.py actividades --desde 2026-09-01 --tipo swimming
.venv/Scripts/python.exe scripts/garmin_conectar.py traer --desde 2026-10-10 --tipo swimming
#     ... y sin consola: en el portal, pestana Entrenamientos, boton "Traer lo nuevo del Garmin" (el servidor
#     local hace lo mismo que ese `traer`, mirando las ultimas 3 semanas y todas las disciplinas; puede tardar)

# 4. Ver el cuadro de mando por consola
.venv/Scripts/python.exe -m entrenador.cli resumen

# 5. Etiquetar el material de una sesion (palas, aletas, pull, tabla, brazo_libre)
.venv/Scripts/python.exe -m entrenador.cli etiquetar 21670453554 --material palas

# 6. Listar las mejores series
.venv/Scripts/python.exe -m entrenador.cli series --metros 100 --comparables --top 10

# 7. Rehacer las series tras cambiar un criterio (no vuelve a leer los ficheros del reloj)
.venv/Scripts/python.exe -m entrenador.cli recalcular

# 8. Analitica de segmentos + cuadro de mando (HTML) + informe en texto
.venv/Scripts/python.exe -m entrenador.cli analizar

# 9. Segmentos de bici: importar los tuyos del export y medir cada intento (una vez, o al llegar datos nuevos)
.venv/Scripts/python.exe -m entrenador.cli segmentos

# 10. Ver tus segmentos de bici (los que repites, tus tiempos) y el historial de uno concreto
.venv/Scripts/python.exe -m entrenador.cli bici --top 15
.venv/Scripts/python.exe -m entrenador.cli bici --segmento segmento-ejemplo

# 11. Montar TODOS los segmentos que hay en los GPX (descubrir, nombrar y medir). Tarda varios minutos con un historico largo
.venv/Scripts/python.exe -m entrenador.cli minar

# 12. Ver el catalogo de segmentos descubiertos, o todos los tiempos de uno
.venv/Scripts/python.exe -m entrenador.cli minados --top 20
.venv/Scripts/python.exe -m entrenador.cli minados --segmento segmento-ejemplo

# 13. Escribir el portal de bici (se abre con doble clic: cuadro/strava/index.html)
.venv/Scripts/python.exe -m entrenador.cli portal

# 14. Tus marcas oficiales de competicion (RFEN): bajarlas de la federacion y cargarlas en la base
#     Ojo: la federacion publica los PASES (tramos de otra prueba) y los relevos en la misma tabla, con un icono
#     que no basta para decidir: tambien marca los tramos de relevo, y esos si son marcas suyas. El proyecto
#     clasifica cada fila mirando la jornada entera (ver competicion.clasificar_sesion).
.venv/Scripts/python.exe scripts/rfen_historial.py                 # las baja a data/competicion/
.venv/Scripts/python.exe -m entrenador.cli competicion             # las carga y saca el resumen
.venv/Scripts/python.exe scripts/clasificar_marcas.py              # audita que es marca y que es pase (y por que)
.venv/Scripts/python.exe -m entrenador.cli competicion --estilo libre --distancia 400   # tu historial de 400
.venv/Scripts/python.exe -m entrenador.cli competicion --estilo libre --distancia 400 --comparar
                                                                  # temporada a temporada + tendencia
.venv/Scripts/python.exe -m entrenador.cli competicion --estilo libre --distancia 400 \n    --piscina 25 --temporada 2025/26 --orden marca                # filtros combinables

# 15. El plan de las proximas semanas (objetivos 400 y 3.000), en la consola
.venv/Scripts/python.exe -m entrenador.cli plan                  # la semana en curso, los objetivos y los bloques
.venv/Scripts/python.exe -m entrenador.cli plan --semana S3      # una semana concreta

# 16. Los apuntes y el gimnasio que rellenas en el cuadro de mando (el reloj no los guarda)
.venv/Scripts/python.exe -m entrenador.cli apuntes               # lo que hay en la base
.venv/Scripts/python.exe -m entrenador.cli apuntes --importar    # lee Descargas/partes_entrenador.json
.venv/Scripts/python.exe -m entrenador.cli gimnasio              # lo pedido, lo hecho y lo que manda el programa
.venv/Scripts/python.exe -m entrenador.cli gimnasio --escribir sesion.json   # guarda la sesion que se manda

# 17. Pruebas (incluye ejecutar el JavaScript de la aplicacion con Node si esta instalado)
.venv/Scripts/python.exe pruebas/pruebas_basicas.py
node pruebas/comprobar_portal.js cuadro/panel.html    # a mano: comprueba ids, vistas y que el JS corre

# 18. La base de conocimiento: validarla, ver los criterios pendientes de firma y firmar una seccion
.venv/Scripts/python.exe -m entrenador.cli conocimiento --validar   # 0 = sin errores; !=0 = hay errores
.venv/Scripts/python.exe -m entrenador.cli conocimiento --validar --json
.venv/Scripts/python.exe -m entrenador.cli conocimiento --criterios # 22 clausulas (21 lineas marcadas) y su estado
.venv/Scripts/python.exe -m entrenador.cli conocimiento --criterios --formato md   # tabla Markdown reproducible
.venv/Scripts/python.exe -m entrenador.cli conocimiento --criterios --formato json
.venv/Scripts/python.exe -m entrenador.cli conocimiento --revisar T.8 --quien entrenador

# 19. Base TOML (F2): estructura, version, sincronizacion y exportacion a Markdown
.venv/Scripts/python.exe -m entrenador.cli conocimiento --estructura
.venv/Scripts/python.exe -m entrenador.cli conocimiento --version
.venv/Scripts/python.exe -m entrenador.cli conocimiento --sincronizar
.venv/Scripts/python.exe -m entrenador.cli conocimiento --exportar-md
```

La orden `conocimiento --validar` comprueba el **TOML nuevo** (`conocimiento/*.toml`) y el anexo
Markdown: IDs duplicados o mal formados, afirmaciones sin fuente, reglas con referencias rotas o sin
métrica de éxito, parámetros sin procedencia, recetas incompletas, citas y fuentes. Si el TOML no
existe o está vacío, **falla cerrado** (`sin_conocimiento`). En el anexo Markdown, una cita rota, un ID
duplicado o una fuente duplicada es error; una fuente huérfana o sin cita literal es aviso. El código
de salida es 0 solo si ambos validan.

`--criterios` lista las cláusulas marcadas `[criterio]`, con su estado: `firmada` (solo si firma
`entrenador` o `atleta`), `revisada_por_asistente` (sigue pendiente) o `pendiente`. El anexo tiene 21
líneas marcadas, pero T.5 lleva dos marcas en la misma línea: salen **22 cláusulas**. `--formato md`
imprime una tabla Markdown reproducible (con la fecha de generación) para guardar la lista sin editarla
a mano.


La orden `analizar` deja tres cosas: `cuadro/panel.html` (el cuadro de mando, se abre con doble clic, sin
servidor ni internet), `informes/H_analitica_segmentos.md` (lo mismo en texto) y `data/derived/analitica.json`
(los datos crudos, por si se quieren consultar a mano).

### Snapshots dorados (golden)

Antes de tocar el motor de conocimiento se guarda lo que dice hoy, para poder comparar despues sin
depender de la memoria. `scripts/golden.py` captura la salida de `cli valoracion`, `cli plan
--recalculado`, `cli reglas` y `cli decision --lista`, mas un resumen de los datos de `cuadro/panel.html`
(KPIs, conteos, version del conocimiento y valoracion; no se guarda el HTML entero).

```bash
# antes del cambio: guardar la referencia
docker compose exec -T entrenador python scripts/golden.py --guardar

# despues del cambio: comparar (codigo 0 = igual; 1 = hay diferencias)
docker compose exec -T entrenador python scripts/golden.py --comparar

# otra carpeta, por ejemplo para comparar v1 contra v2
docker compose exec -T entrenador python scripts/golden.py --guardar --dir data/derived/golden/v1
docker compose exec -T entrenador python scripts/golden.py --comparar --dir data/derived/golden/v1
```

Los snapshots llevan datos del atleta y se guardan en `data/derived/golden/`, que **no se versiona**.
El script si es publico. Compara siempre sobre la misma base y el mismo dia: `plan --recalculado` y la
valoracion dependen de la fecha y de los entrenamientos que hay en la base.


El cuadro de mando es una **aplicacion local**: un solo fichero HTML con **menu lateral** (Resumen,
Competicion, Plan, Entrenamientos, Gimnasio, Apuntar, Volumen y el portal de bici) y **pestanas** dentro de
las secciones. Todo (filtros, comparaciones, tendencia y graficos) se calcula en el propio navegador: no
hay servidor, no hay API y no hace falta internet. La direccion lleva la seccion (`panel.html#competicion`).

El diseno vive en `entrenador/app/` (hoja de estilo `app.css`, esqueleto `plantilla.html` y logica `app.js`);
`panel.py` solo los monta en un fichero unico con los datos dentro. Para tocar la aplicacion se tocan esos
tres ficheros y se vuelve a lanzar `analizar`.

Lleva, ademas de la analitica de entrenamiento:

- **Resumen**: los numeros del entrenamiento, el volumen mes a mes, el calendario por dias y la tarjeta
  *como voy*: los dos objetivos con los dias que quedan y la proyeccion de cada prueba con las marcas
  oficiales que hay (con el aviso de que es una referencia, no un pronostico).
- **Competicion**, en cuatro pestanas: *mejores marcas* (cada prueba y piscina, los 400 libres uno a uno
  frente al objetivo configurado y los 3.000), *comparador por temporadas* (mejor marca de cada
  temporada de septiembre a agosto, diferencia en segundos y en porcentaje con la anterior y con la mejor
  de siempre, tendencia en segundos por 100 al ano y un grafico de evolucion con la linea del objetivo), *todas las
  marcas* (las marcas validas con filtros de prueba, piscina, temporada y sede, hechos en el navegador, y donde
  esa prueba tuvo tramos sale un boton para desplegarlos pegados bajo su marca) y *mis pases* (la misma prueba
  competicion a competicion: cada tramo -el primer 100 de cada 400, el 200 de cada 3.000- con su tiempo, su
  ritmo y lo que se aparta del ritmo de la prueba, un grafico del tramo elegido y el desglose de su mejor dia).
  Las piscinas de 25 y 50 m nunca se comparan entre si y se avisa si se estan mezclando.
- **En cualquier tabla del portal el orden se elige pinchando en el titulo de la columna** (la fecha, la marca,
  el tiempo, el ritmo, los metros...): la fecha empieza por lo mas reciente y los numeros por lo mas bajo, y al
  volver a pinchar la misma columna se da la vuelta. Un tramo de una prueba se mueve siempre con su marca.
- **La lista de sesiones se pincha y abre esa sesion** (con su parte): vale igual en *Resumen → Ultimas sesiones*
  y en *Entrenamientos*, y con el teclado (Enter). El oyente es global (`montarFilasPinchables`), asi que
  cualquier tabla que traiga filas con `data-sesion` se comporta igual.
- **Los ritmos van en minutos y segundos** (`1:14,1` por 100 m), no en segundos por 100: se leen de un vistazo y
  se comparan mejor con un tiempo de competicion. En los informes (`informes/*.md`) sigue usandose `s/100` como
  unidad de ritmo.
- **Plan**: los dos objetivos configurados (400 y 3.000), las cinco semanas hasta la prueba con
  sus sesiones, los bloques hasta marzo y las reglas. La semana en curso se marca sola segun la fecha del PC.
  El plan es dato del proyecto (`entrenador/plan.py`): la consola lo imprime con `plan`.
- **Un entrenamiento hecho sin reloj tambien cuenta**: se apunta a mano (pestana *Apuntar*) con sus metros y sus
  series, sale en las listas de sesiones marcado como *sin reloj* y el plan da por hecha esa sesion del dia
  (estado *Apuntada a mano (sin reloj)*). No hace falta el reloj para que la sesion cuente.
- **Lo que vale es lo que se ha nadado**: si en la piscina cambias el entrenamiento y el volumen esta (llega al
  80 % de lo que pedia el plan), la sesion cuenta como hecha (*Hecha a tu manera (cambiaste el plan)*) aunque los
  bloques no coincidan. El detalle de los bloques se sigue enseñando, pero no se suspende por cambiar.
- **Traer lo nuevo del Garmin desde el portal**: en Entrenamientos hay un boton *Traer lo nuevo del Garmin*. El
  portal no habla con la nube: le pide al servidor local (`127.0.0.1:8181`, la ventana de `servir-entrenador.bat`
  tiene que estar abierta) que haga lo mismo que `scripts/garmin_conectar.py traer` — baja los FIT que no esten
  (por dia + disciplina + distancia, **nunca por id**), los mete en la base, rehace el cuadro con lo que entre y
  lo cuenta en el aviso. Ninguna credencial pasa por el navegador: la sesion es el token OAuth que ya dejo
  `conectar-garmin.bat` (`C:\Users\<usuario>\.garminconnect`). Si el aviso pide renovar la sesion, ese `.bat`.
- **Apuntar mis entrenamientos**: un formulario para anotar lo que el reloj no registra (gimnasio, ejercicios,
  material, como de duro fue). Guarda en el propio navegador (nada sale del PC) y deja bajar
  `partes_entrenador.json` a la carpeta de Descargas; `apuntes --importar` lo mete en la tabla `apunte`
  (idempotente: reimportar el mismo fichero no duplica). El portal ensena ademas lo que ya esta en la base.
- **El parte del reloj: el atleta manda.** En la pestana *Entrenamientos*, cada sesion del reloj se abre en
  grupos y cada grupo se marca con su intensidad (`Calentamiento`, `AeLigero`, `AeMedio`, `AeIntenso`,
  `SWOLF (series de 50)` y **`Pies`**, que es pataleo: cuenta metros pero su ritmo no se compara con el plan),
  su material (aletas, palas, pull) y el SWOLF o el **tiempo** de cada repeticion. Escribir el tiempo
  (`5:55`, `5,55` o `355`) es corregirle el crono al reloj: manda el del atleta, y al guardar se lleva al lap,
  se rehacen las series y se recalcula el ritmo del grupo. El material y los tiempos tambien se pueden
  reaplicar a los partes ya guardados: `partes --reaplicar`.
- **El `cada` de cada serie: el intervalo de salida.** La cabecera de un grupo dice *cada 2:55*, que es del
  inicio de una repeticion al inicio de la siguiente (como se canta en la piscina), no el descanso suelto, que
  cambia de una repeticion a otra. Se calcula desde los intervalos del reloj (`partes._cada_de_grupo`) y vive en
  `parte_serie.cada_s`; en un bloque continuo, si no hay `cada`, se enseña el descanso que venga despues.
- **El boton *Evaluar el ultimo entrenamiento*** (Entrenamientos, junto al del Garmin; y *Que lo evalue el
  entrenador* dentro de cada parte): manda la sesion al servidor local (`POST /evaluar`, o `valoracion --sesion
  <id>` por consola) y el entrenador la mira con lo que hay en la base, sin tocar la nube: **los tiempos**
  bloque a bloque (con el material descontado), la **distancia**, el **esfuerzo previo** (lo nadado los 3 dias
  y la semana de antes, y cuantos metros llevaba encima antes de cada serie) y los **descansos** (el `cada` de
  cada serie y que se puede recortar). Termina con **como va el plan** (hechos frente a lo previsto de la
  semana, en que ciclo estas y lo siguiente que toca) y con el bloque de calidad del dia frente al ritmo del
  reto. La media de la sesion **no** se compara con el ritmo del 400: eso no diria nada; el cierre se apoya en
  el bloque que aprieta.
- **El material no se compara con brazo libre**: un 1.000 con aletas o unos 200 con palas y pull no dicen como
  esta el atleta. `analitica.py` marca cada bloque (`material`, `brazo_libre`) y los KPIs (`mejor_400`,
  `mejor_1000`...) y el discurso del entrenador **solo** toman bloques a brazo libre. Cuando un tiempo con
  material se cita, se nombra el material y se descuenta la ayuda (~10 s/100 las aletas, ~6 las palas, ~4 el
  pull), para que no se cuele como marca propia. Se ve en el parrafo *Con que se hizo cada bloque*.
- **Gimnasio**: tres cosas en la misma pestana. *Solicitar trabajo de gimnasio* (objetivo, minutos, donde,
  material que hay a mano, molestias a evitar y notas): la peticion se guarda en el navegador y se sube con
  el mismo `partes_entrenador.json`; `apuntes --importar` la mete en `gimnasio_peticion` y `gimnasio --escribir`
  guarda en `gimnasio_prescrita` la sesion que le manda el programa, que el portal ensena con sus series y sus
  pesos. *Registrar la sesion hecha* (ejercicio, series, reps, kilos, RPE) con el volumen calculado
  (series x reps x kilos) y el historial con lo apuntado y lo que viene del reloj (que solo trae la duracion).

Cualquier orden admite `--bd <ruta>` para trabajar sobre otra base de datos (por ejemplo una copia de
prueba) sin tocar la real: `.venv/Scripts/python.exe -m entrenador.cli --bd copia.db resumen`.

La importacion es **idempotente**: repetirla actualiza lo que ya existe y no duplica nada. La identidad de
una sesion es la **huella (hash) del fichero** y el **identificador de Garmin** (el nombre del FIT), que es
distinto del identificador de Strava; se guardan los dos para cruzar las dos vias de importacion.

## Criterios de analisis (documentados, no implicitos)

1. **Lap activo**: lap con distancia > 0. **Lap de descanso**: lap con distancia = 0.
2. **Serie**: repeticiones consecutivas de la misma distancia separadas por descansos de como maximo
   180 s. Un descanso mayor cierra la serie. Hacen falta **2 repeticiones validas o mas** para hablar de serie.
3. **Repeticion creible**: se descartan las repeticiones con cronometro imposible (fuera de 60-300 s/100 m,
   sintoma de un lap mal disparado por el reloj). La serie que pierde alguna repeticion queda marcada como
   `sospechosa`, y si le quedan menos de 3 validas deja de ser comparable.
4. **Ritmo de repeticion** = tiempo del lap / (distancia / 100). **Ritmo de serie** = media.
5. **Deriva** = ritmo de la ultima repeticion menos el de la primera (positivo = se cansa).
6. **Serie comparable**: 3 repeticiones validas o mas, sin trabajo de tecnica (`drill`) y con ritmo entre 45 y
   400 s/100 m. **Las series con material etiquetado NO son comparables** (no se mezclan con brazo libre).
7. **Distancia de una sesion de piscina** = largos activos x largo de piscina (no se usa el campo del reloj,
   que depende de su configuracion). La diferencia media entre ambos en las 780 sesiones comparables es de
   **0,0 m**, asi que coinciden; el valor calculado es el que manda.
8. **Piscinas de 25 m y 50 m nunca se comparan entre si** (la columna `largo_piscina_m` las separa).
9. **Estilo del lap**: el reloj no lo guarda en el lap, solo en el largo; se asigna el estilo mayoritario de
   los largos que caen dentro del lap.
10. **Bloque continuo**: laps activos consecutivos entre los que no hay ningun lap de descanso, sumados en
    uno solo. Cuenta como bloque a partir de **200 m**. Se guarda tambien que parte de la sesion ocupa: si
    ocupa mas del 90 %, se marca `domina_sesion` porque puede ser una sesion continua o una sesion en la que
    el reloj no registro descansos (no se vende como lo que no es).
11. **Bloque verificado (`fiable`)**: el ritmo tiene que estar entre 60 y 300 s/100 m, las brazadas tienen que
    ser coherentes con la distancia (**entre 0,20 y 0,80 brazadas por metro**: el atleta da 8-11 brazadas por
    largo de 25 m) y un bloque sin ninguna brazada no puede salir a menos de 90 s/100 (un pataleo con tabla no
    baja de ahi). Los bloques no verificados siguen en el catalogo, pero **no pueden fijar una marca**.
12. **Marca de referencia de una distancia** = **mediana de las 3 mejores** veces verificadas (no el minimo
    absoluto), para que un solo lap mal cronometrado no fije un objetivo. El minimo absoluto se guarda aparte
    y se muestra como "mejor registrada".
13. **Segmento**: bloque o serie que se ha hecho **2 veces o mas**, con nombre en castellano ("400 m seguidos",
    "10x100 m") y sufijo cuando hace falta (estilo, piscina de 50 m, aguas abiertas, tecnica).
14. **Peso de un segmento** = veces x distancia / 100. Con esto un bloque largo pesa mas que uno corto que se
    repita lo mismo (peticion del atleta: *cuanto mas largos mejor*). El cuadro de mando deja ordenar tambien
    por numero de veces o por longitud, y quitar el trabajo de tecnica.
15. **Tendencia de un segmento**: se comparan solo las veces hechas en la **misma piscina** (la mas habitual
    del segmento); un 400 m en piscina de 50 m no se puede mezclar con uno de 25 m.

### La valoracion del entrenador (el discurso del Resumen)

El Resumen abre con **"El entrenador dice"**: un discurso cualitativo escrito con los datos de la base, no a
mano. Lo compone `entrenador/valoracion.py` en cada pasada de `analizar` (o sea, **se recalcula solo**), y sale
igual en el portal (pestana Resumen), en el anexo escrito (`informes/H_analitica_segmentos.md`) y por consola
(`cli valoracion`).

El guion, tal como se pidio: **donde estamos** (dias que quedan a los objetivos configurados, con las
referencias), **como va la progresion** (los ultimos 7 dias contra los 7 anteriores, y la mejor serie medida),
**contra hace un mes** (los ultimos 30 dias contra los 30 de antes, con el mejor 400 seguido de cada tramo),
**lo que queda de semana** (las sesiones del plan que siguen pendientes, con su detalle), **como va el ciclo**
(el camino del 400 y el ciclo largo del 3.000) y **que se puede esperar**.

Reglas que sigue el discurso:

- **No inventa un dato.** Cada numero sale de la base (bloques medidos, partes subidos y la evaluacion contra
  el plan). Los numeros que lo sostienen quedan en `valoracion.fuentes`, y las pruebas comprueban que el texto
  cita los mismos metros que ha medido.
- **Si algo no se puede juzgar, lo dice** en vez de rellenarlo: sesiones sin parte, sesiones apuntadas a mano
  (cuentan como hechas, pero sin laps no se mide el ritmo bloque a bloque) y lo que no tiene medida.
- **No promete un crono.** Dice a que distancia esta el ritmo (s/100) y que medida dira si el objetivo esta al
  alcance; la marca del dia es una consecuencia, no una promesa.
- Respeta lo decidido antes: **sin taper largo** y **sin otra carrera detras** del 400.
- Un entrenamiento **sin reloj** cuenta como la sesion del dia, y una sesion **cambiada en la piscina** cuenta
  como hecha si el volumen llega: **manda la decision del atleta**.

Los **tiempos de entrenamiento para el reto** (la tabla de dianas del Resumen) se derivan del objetivo del plan
(400 libre; la marca y el ritmo objetivo viven en la configuracion privada del atleta) con un criterio explicito:

| Serie | Diana | Por que |
|---|---|---|
| 50 m a tope (velocidad) | ritmo de prueba menos un margen | La salida del 400 se defiende con la velocidad del 50: hay que hacerlo a ritmo de prueba y con margen. |
| 8x100 con salida cada 2:00 | ritmo objetivo +/- 1-2 s/100 | Es el bloque que mas se parece al 400: si la ultima no se cae de la primera, el ritmo esta puesto. |
| 4x400 con 45 s | ritmo objetivo + 1-2 s/100 cada 400 | A 1-2 s/100 del objetivo: la diana realista de entrenamiento. |
| 400 seguido (control) | ritmo objetivo +/- 1 s/100 | El control mas honesto: a 0-1 s/100 del objetivo, unas semanas antes. |
| El dia de la prueba | la marca objetivo de la configuracion privada | El plan busca el objetivo pactado; el crono sale solo con la salida y la serie. |

Son **dianas de entrenamiento, no promesas**: el discurso las cambia si los datos cambian (el plan sube o baja
los kilometros, la evaluacion propone bajar tras una deriva, aparece un test que mide de verdad).

### Bici (portal tipo Strava)

16. **Traza GPS**: se guardan las coordenadas de cada salida (de los GPX del export y de los FIT que las
    traen) comprimidas en la base, con los puntos que aportan algo (separados por 2,5 m o 5 s): parado en un
    semaforo no se guardan 200 puntos en el mismo sitio.
17. **Segmento de bici**: los que trae el export de Strava (`segments.csv`), que son **los que el atleta ya ha
    hecho**, con su nombre. El export solo da el punto de inicio y el de fin: **ni distancia ni desnivel**.
18. **Intentos (esfuerzos)**: se recorre la traza y se busca un punto cerca del inicio (radio 60 m) y despues
    otro cerca del fin. Se exige que lo recorrido se parezca a la linea recta (entre 0,85 y 3 veces) y que la
    velocidad implicada sea de bici (menos de 144 km/h): si no, son dos puntos mal enganchados por el GPS.
    De cada salida se guarda **el mejor intento**, como Strava.
18b. **Dos pasadas**: la primera mide sin saber nada y sirve para descubrir la **distancia tipica** de cada
    segmento (mediana de lo medido, con 3 intentos o mas); la segunda vuelve a medir exigiendo que el intento
    **sea el mismo recorrido**: no se puede apartar mas de un **6 % de esa distancia**, o de **60 m** en los
    tramos cortos (por debajo de un kilometro manda el suelo, porque la distancia de un tramo corto se mide entre
    los centros de las celdas del minero, de 30 m). Antes el
    margen era del 30 % y por ahi se colaban los de otro camino: en una ruta larga (18 km) entraban intentos
    de 20 km que suben por la otra carretera, y con ellos el "mejor tiempo" y la mediana eran de otro
    recorrido. Con el 6 % se quedan los del recorrido largo y los de la otra carretera dejan de contar. Sin
    ningun margen, una vuelta larga que pasa cerca del principio y del final por **otro camino** contaba como
    intento (salieron "records" de 20 km en 25 minutos) — con el 30 % tampoco se libraba, que era el problema.
18c. **Distancia tipica por grupos, no por mediana**: una misma pareja de puntos (inicio y fin del segmento) se
    puede cruzar por caminos distintos: un dia 13,1 km y otro 25,4 km, porque las trazas pasan cerca de los dos
    puntos pero por otro sitio. Con la mediana simple, el numero cae en medio de los dos caminos y no vale para
    nada. Se **agrupan** las distancias (mismo largo con un 5 % o 150 m de margen) y manda **el grupo mayor**.
    Si el segundo grupo se le parece mucho (mas de dos tercios del mayor), el segmento se marca **dudoso**: se
    sigue midiendo con el camino mas habitual, pero se avisa con un `*` en el cuadro de mando y en el informe,
    en vez de mezclar tiempos de recorridos distintos.
19. **Sentido del recorrido**: si un segmento tiene desnivel claro (mas de 20 m de mediana) y un intento va al
    reves (bajando lo que se sube), no cuenta: no es comparable y falsearia la marca.
20. **Distancia y desnivel del segmento**: se miden sobre las trazas reales del atleta y se guarda la
    **mediana** de sus intentos. El desnivel cuenta solo los tramos de mas de 3 m (el altimetro del GPS tiembla
    1 m: sumando punto a punto saldrian cientos de metros donde hay 80).
21. **Peso de un segmento de bici** = veces x distancia, igual que en natacion (los largos primero).

#### Los segmentos propios, sacados de las trazas (minero)

22. **Por que hay que sacarlos**: el export solo trae los segmentos que el atleta ya habia hecho, y solo con
    el punto de inicio y el de fin. El catalogo completo (los tramos que repite sin saberlo) se descubre de sus
    trazas: lo que se repite en 3 salidas o mas es un segmento.
23. **Rejilla de celdas** de 30 m y **ancla de 3 celdas seguidas** (90 m). El GPS tiembla entre salidas: con
    celdas mas finas o ventanas mas largas, la misma carretera no ancla.
24. **Un tramo vale si alguna de sus propias salidas lo recorre entero** (`_verificar`). Al pegar trozos
    (cruces y rotondas parten una carretera en cachos) es facil encadenar un camino que nadie ha hecho seguido.
    Es la comprobacion mas importante del minero.
25. **Copias del mismo camino**: se funden (`_fundir_iguales`), y **sobre la traza de verdad**, no sobre la
    union de trozos: la union deja listas de celdas sucias y dos copias del mismo camino no se reconocen. Se
    juzga por la forma: misma distancia (15 %) y **cada punto de un tramo a menos de 60 m de algun punto del
    otro** (`_mismo_camino`, en metros llanos, mirando en los dos sentidos). El mismo camino pasado unos metros
    al lado (o apuntado con la mitad de puntos) se funde; otro camino que sale y llega al mismo sitio (una
    carretera y el sendero que la bordea) no.
26. **Un intento solo vale si es el mismo recorrido**: al medir, lo que ha recorrido la salida tiene que
    parecerse a la distancia del segmento (el mismo criterio que en los segmentos de Strava: 6 %, o 60 m en los
    tramos cortos; `bici.distancia_encaja`). Antes se admitia de todo entre el 80 % y el 125 %, y en un tramo de
    18 km se colaban los que suben por otra carretera: el "mejor tiempo" salia de un recorrido mas largo.
27. **Numero de salidas de un segmento**: es el de los intentos que aguantan la prueba de verdad, que lo fija
    la medida (`medir`), no el que conto el descubrimiento.
28. **Nombres**: se ponen con los pueblos y aldeas del entorno (OpenStreetMap, una consulta que se guarda: 487
    en La Rioja). Si una consulta falla, los tramos se quedan numerados y no pasa nada: nombrar es cosmetico.
29. **Los tramos que no ha hecho nadie** (0 intentos medidos) se borran: no sirven para compararse.
30. **La mineria rehace el catalogo entero** cada vez (borra y vuelve a montar): es larga pero idempotente. Un
    `minar --limite N` (para pruebas) tambien borra el catalogo, asi que **nunca** se lanza sobre la base real.

## Lo que el reloj NO registra (y por tanto no se puede inventar)

- **Material** (palas, aletas, pull, tabla): no existe ese campo en el FIT. Se etiqueta por el nombre de la
  actividad en Garmin Connect (`palas`, `aletas`, `pull`, `tabla`) o a mano con `etiquetar`.
- **Ejercicios de gimnasio**: el reloj no los guarda, asi que se apuntan a mano en la pestana *Gimnasio* y se
  importan a `gimnasio_sesion` (ejercicio, series, reps, kilos y RPE). Lo que manda el programa va aparte, en
  `gimnasio_prescrita`, escrito con `gimnasio --escribir`.
- **Umbrales** de frecuencia cardiaca o de ritmo: no hay tests previos, por eso se hacen en el bloque 0.

## Estructura

```
entrenador/          codigo de la aplicacion
  db.py              esquema SQLite y conexion
  lector_fit.py      lectura pura de FIT (sesion, laps, largos y traza GPS)
  lector_gpx.py      lectura de GPX (coordenadas, altitud y hora) + compresion de la traza
  series.py          reconstruccion de series y material por palabra clave
  importar.py        importacion incremental (carpeta / export de Strava)
  analitica.py       bloques continuos, catalogo de segmentos, volumen, mejores marcas
  competicion.py     marcas oficiales de la RFEN (tabla competicion), bajadas con scripts/rfen_historial.py
  bici.py            segmentos de bici: medir los intentos y comparar resultados
  panel.py           monta el cuadro de mando (app/ + datos) + informe en texto
  apuntes.py         apuntes, peticiones y sesiones de gimnasio desde el cuadro de mando
  plan.py            plan de natacion hacia los objetivos configurados (400 y 3.000)
  app/               la aplicacion local: app.css (estilo), plantilla.html (esqueleto) y app.js (logica)
  cli.py             linea de ordenes
pruebas/             pruebas ejecutables (pruebas_basicas.py y comprobar_portal.js, que ejecuta el JS con Node)
cuadro/              cuadro de mando (panel.html)
scripts/             scripts de auditoria (solo lectura sobre los datos de origen)
data/                export original, datos derivados y entrenador.db
informes/            informes de diagnostico, catalogo de series, planificacion y analitica
```
