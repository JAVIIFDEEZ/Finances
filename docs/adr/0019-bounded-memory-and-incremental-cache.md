---
status: aceptado
date: 2026-11-04
decision-makers: Javier Fernández
---

# Memoria acotada en la simulación y caché incremental verificada

## Contexto y problema

La auditoría del 3 de noviembre de 2026 encontró tres problemas de escala:

* **M1. Memoria de la simulación.** El límite `n_paths × horizon ≤ 20 000 000` no contaba
  los activos. Los rendimientos por activo, el array más grande, se generaban en lotes de
  2 000 trayectorias. Con 10 activos, 2 000 trayectorias y 2 520 periodos, el pico llegaba a
  1,65 GB.
* **M2. Bloqueo del bucle de eventos.** `MarketDataService` leía y escribía Parquet dentro de
  sus corrutinas, y `LocalFilesProvider` leía ficheros enteros. Cada acceso a disco paraba
  todas las descargas del lote.
* **M3. Caché sin ampliación.** Una entrada caducada se descargaba entera otra vez. Pedir otro
  rango sustituía lo guardado. [ADR-0011](0011-parquet-duckdb-cache.md) lo dejó como deuda
  técnica.

¿Cómo acotar la memoria y no repetir trabajo sin inventar datos ni mezclar historias
incompatibles?

## Factores de decisión

* Memoria predecible, sin que dependa del número de activos.
* Reproducibilidad: misma semilla, configuración y datos dan el mismo resultado.
* Nunca mezclar precios de procedencias o ajustes distintos
  ([ADR-0006](0006-strict-input-validation.md), [ADR-0008](0008-alignment-without-artificial-fill.md)).
* Descargar lo mínimo: Alpha Vantage tiene cuotas diarias y Yahoo bloquea el abuso.
* No bloquear el bucle de eventos: la API de la fase F6 atenderá muchas peticiones a la vez.

## Opciones consideradas

* Memoria (M1):
  * lotes dimensionados por celdas (trayectorias × horizonte × activos);
  * contar los activos en el límite global;
  * guardar los valores en `float32`.
* Caché (M3):
  * ampliar la entrada con el tramo que falta y verificar un solape;
  * fusionar sin verificar;
  * mantener la sustitución completa.
* Entrada/salida (M2):
  * `asyncio.to_thread` con el puerto síncrono;
  * un puerto de almacenamiento asíncrono.

## Decisión

Opciones elegidas: **lotes por celdas**, **ampliación verificada** y **`asyncio.to_thread`**.
Cada una resuelve su problema sin cambiar los contratos públicos.

### Memoria de la simulación

* `MAX_CHUNK_CELLS = 4 000 000` celdas por lote, unos 32 MB por array `float64`.
* `SimulationConfig.paths_per_chunk(activos)` reduce el lote hasta que
  `trayectorias × horizonte × activos` cabe en ese límite. `chunk_size` pasa a ser un máximo.
* Solo se conservan los valores de la cartera: `n_paths × (horizon + 1)`, como mucho 160 MB por
  `MAX_SIMULATED_POINTS`.
* El drawdown de cada trayectoria se calcula lote a lote.
* Los núcleos trabajan *in place* donde pueden: `expm1`, `cumprod` y la suma de la media.
* Si una sola trayectoria no cabe (`horizon × activos > MAX_CHUNK_CELLS`), se rechaza con
  `DomainError`.
* Con variables antitéticas y varios lotes, el lote es par para que cada trayectoria conserve
  su espejo.

Medido con `tracemalloc` sobre precios sintéticos:

| Simulación | Antes | Después |
|------------|-------|---------|
| 10 activos × 2 000 trayectorias × 2 520 periodos | 1 653 MB, 12,3 s | 136 MB, 1,9 s |
| 40 activos × 2 000 trayectorias × 252 periodos | 649 MB | 100 MB |

### Caché incremental verificada

El servicio decide qué descargar según lo que ya hay en caché:

* **Entrada fresca que cubre la petición**: se sirve recortada, como antes.
* **Entrada caducada o corta por el final**, pero que llega hasta el inicio pedido:
  * se descarga desde las últimas `OVERLAP_BARS = 5` barras guardadas hasta el fin pedido o
    el de la caché, el que sea posterior;
  * las barras del solape, salvo la última (puede ser una barra parcial de la sesión), deben
    coincidir con tolerancia relativa de `1e-6`;
  * además deben coincidir el proveedor, las columnas, la divisa y el ajuste;
  * si todo coincide, se conservan las barras anteriores y se añade lo descargado; desde su
    primera fecha manda la descarga;
  * si no coincide, se descarga todo el rango. Es lo que pasa cuando un dividendo o un
    *split* reajusta la historia, cuando hay una revisión o cuando sirve otro proveedor por
    *fallback*. Nunca se mezclan historias incompatibles;
  * si antes del fin pedido hay menos de tres barras guardadas, se descarga todo el rango: el
    tramo no formaría una serie válida.
* **Petición con historia más antigua que la guardada**: una sola descarga desde el inicio
  pedido hasta el fin de la caché. Es un superconjunto, así que sustituye la entrada sin
  perder nada.
* **`refresh=True`**: descarga exactamente la petición y sustituye la entrada.
* La entrada ampliada lleva la procedencia de la descarga nueva. Su `retrieved_at` es el
  momento de la verificación.
* Las series macro mantienen la sustitución completa: una *vintage* nueva puede revisar
  cualquier observación pasada.

### Entrada/salida fuera del bucle de eventos

* Las lecturas y escrituras de la caché y la lectura de ficheros locales se ejecutan con
  `asyncio.to_thread`.
* El puerto `SeriesStore` sigue siendo síncrono: es más fácil de implementar y de probar, y
  cualquier adaptador se beneficia sin cambios.
* Una entrada ilegible se registra en el log y cuenta como *cache miss*, nunca como error.

### Consecuencias

* Positiva: la memoria de trabajo queda acotada con cualquier número de activos, y la
  simulación es más rápida.
* Positiva: una entrada caducada se renueva con unas pocas barras, así que el uso diario apenas
  consume cuota.
* Positiva: un lote de N series sigue descargando mientras otra serie lee o escribe en disco.
* Negativa: en Student-t, *bootstrap* y antitéticas, el flujo aleatorio depende del lote, y el
  lote ahora también depende del número de activos. Con la misma semilla, esos resultados
  cambian respecto a versiones anteriores. En GBM no cambian.
* Negativa: el solape no detecta revisiones de barras anteriores a las cinco últimas. Para eso
  está `refresh=True`, que fuerza la descarga completa.
* Negativa: cada escritura sigue reescribiendo el fichero completo. Es aceptable en diario; en
  intradía largo se valorará particionar.

### Confirmación

* `tests/unit/domain/test_simulation.py`:
  * tamaño del lote y rechazo de trayectorias que no caben;
  * mismos resultados GBM con lotes forzados;
  * pico de memoria medido con `tracemalloc`.
* `tests/unit/services/test_market_data.py`:
  * descarga del tramo final, barra parcial, historia reajustada y otro proveedor;
  * ampliación del final, historia más antigua y solape anclado al fin pedido;
  * fecha de sesión en intradía;
  * entrada/salida en hilos y caché ilegible.
* `tests/unit/adapters/test_local_files.py`: lectura del fichero en un hilo.

## Pros y contras de las opciones

### Contar los activos en el límite global

* Positivo: una línea de código.
* Negativo: rechazaría simulaciones razonables, como 10 000 trayectorias × 252 periodos × 10
  activos. La memoria la marca el lote, no el total.

### Valores en `float32`

* Positivo: la mitad de memoria para los valores conservados.
* Negativo: no resuelve M1, que venía de los arrays por activo.
* Negativo: acumula error de redondeo en horizontes largos.

### Fusionar sin verificar

* Positivo: es lo más simple.
* Negativo: tras un dividendo, unir precios ajustados en dos fechas distintas crea un salto
  artificial. Sería inventar datos.

### Mantener la sustitución completa

* Negativo: descargas completas a diario y pérdida de los rangos guardados.

### Puerto de almacenamiento asíncrono

* Positivo: encaja con un almacenamiento de objetos (S3/R2).
* Negativo: obliga ya a que todos los adaptadores sean asíncronos. Se reconsiderará con el
  almacenamiento en la nube (fase F14).

## Más información

* Resuelve la deuda técnica de actualización incremental de
  [ADR-0011](0011-parquet-duckdb-cache.md).
* Concreta la sección de memoria de [ADR-0016](0016-monte-carlo-engine.md).
* Origen: hallazgos M1, M2 y M3 de la auditoría del 3 de noviembre de 2026.
