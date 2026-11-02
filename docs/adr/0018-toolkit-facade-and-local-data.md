---
status: aceptado
date: 2026-11-02
decision-makers: Javier Fernández
---

# Fachada Toolkit, datos locales y trazabilidad de los módulos

## Contexto y problema

El taller B1-T1 se usa desde un notebook: hace falta una entrada única que monte toda la
plataforma (proveedores, caché, divisas, tipo libre de riesgo, calendarios) sin que quien la
usa tenga que conocer la arquitectura hexagonal.

Además:

* El entorno de desarrollo en la nube no tiene red hacia las APIs de datos. Los proveedores
  remotos (F2b) siguen pendientes y, aun así, la librería tiene que poder usarse con datos
  reales.
* Cada bloque del máster debe poder demostrar qué requisitos cubre, dónde está el código y qué
  tests lo prueban, sin copiar el enunciado (material de clase).
* El notebook de demostración no puede quedarse obsoleto ni publicar resultados que parezcan
  datos de mercado.

## Factores de decisión

* Un único *composition root* para notebooks (ADR-0002): los adaptadores solo se instancian
  ahí y en el `bootstrap` de la API.
* Jupyter ya tiene un bucle de eventos en marcha, así que `asyncio.run` falla dentro de un
  notebook.
* Nunca inventar datos: un fichero de precios no dice su divisa, y adivinarla es inventar.
* La trazabilidad tiene que poder comprobarse automáticamente.

## Decisión

### `Toolkit`, la fachada pública

* `AsyncToolkit.from_settings()` monta el registro de proveedores, la caché Parquet,
  `MarketDataService`, `CurrencyService`, `RiskFreeRateService` y `DataQualityService` con
  `exchange_calendars`.
* Métodos:

  | Método | Qué hace |
  |--------|----------|
  | `series()` | Una serie |
  | `many()` | Descarga simultánea de N series (§4.2) |
  | `portfolio()` | Descarga, convierte a la divisa base y valida |
  | `risk_free()` | Tipo libre de riesgo *point-in-time* |
  | `quality()` | Calidad con el calendario oficial |
  | `report()` | Informe enriquecido (ver abajo) |
  | `load()` y `from_dataframe()` | Importan ficheros y DataFrames |

* `report()` usa el tipo libre de riesgo *point-in-time* de la divisa, salvo que se indique
  uno, y la calidad con calendario oficial. Si no hay fuente de tipos, se registra un aviso y
  el informe lo explica en sus diagnósticos.
* `Toolkit` es la versión síncrona: ejecuta `AsyncToolkit` en un **hilo propio con su bucle de
  eventos**, de modo que funciona igual en un script que dentro de Jupyter. `close()` es
  idempotente y el objeto se usa como gestor de contexto.

### Fuente de ficheros locales

* `SeriesImporter` + `ImportSpec` (Pydantic, en el borde) convierten ficheros CSV/Parquet y
  DataFrames en `PriceSeries` validadas:
  * columnas reconocidas en inglés y español;
  * divisa ISO, con conversión de unidades menores (`GBp` → GBP);
  * mercado e ISIN validados.
* Solo se aceptan transformaciones que no cambian ningún valor:
  * renombrar columnas;
  * ordenar las fechas;
  * quitar filas sin ningún precio.
* Se rechazan, nunca se reparan: duplicados, cierres ausentes y precios no positivos.
* `LocalFilesProvider` sirve una carpeta (`INVESTINGLAB_LOCAL_DATA_DIR`) con un fichero por
  símbolo y un `instruments.toml` **obligatorio** que describe cada uno.
  * Se registra como cualquier proveedor, así que el mismo código funciona con datos
    descargados o locales.
  * Si se le pide otra frecuencia, no la fabrica: responde `UnsupportedRequestError`.

### Registro de módulos y trazabilidad

* `investinglab.modules.registry` define `ModuleInfo` y `Requirement`. En cada requisito, el
  texto es nuestro, bilingüe, y lleva rutas al código, a los tests y su estado (hecho, parcial
  o pendiente).
* `modules/b1_toolkit` declara los requisitos 4.1–4.6 del taller y se registra al importarse.
  La futura API (`GET /modules`) y la web se construirán a partir de este registro.
* `uv run just traceability` genera `docs/modules/<slug>.md`. Un test comprueba tres cosas:
  * que **cada referencia existe** (se importa el símbolo o existe el fichero);
  * que **cada test citado existe**;
  * que la matriz publicada coincide con la generada.

### Notebook de demostración

* `notebooks/b1_toolkit_demo.ipynb` recorre el taller entero con `Toolkit`.
* Se versiona **sin resultados**: lo que se ve al ejecutarlo son los datos de quien lo ejecuta.
* Un test lo ejecuta de principio a fin con ficheros **sintéticos** creados en una carpeta
  temporal (nunca versionados) y comprueba que no tiene resultados guardados. Así el notebook
  no se queda obsoleto.

## Consecuencias

* Positiva: el taller se usa con una línea de configuración y funciona hoy, sin red, con datos
  propios.
* Positiva: la trazabilidad no puede quedar desfasada respecto del código.
* Negativa: hay que mantener `instruments.toml` a mano para los ficheros locales. Es el precio
  de no adivinar divisas ni mercados.
* Negativa: el hilo con su bucle de eventos debe cerrarse (`close()` o `with`). Si no se
  cierra, muere con el proceso, porque es un hilo *daemon*.
* Pendiente:
  * los proveedores remotos se registrarán en `from_settings()` (F2b);
  * la versión `v0.1.0` se etiquetará cuando el requisito 4.2 esté completo.

## Confirmación

Tests:

* `test_importer.py`, `test_local_files.py`.
* `test_toolkit.py`:
  * lotes y carteras con conversión;
  * tipo libre de riesgo *point-in-time* en el informe;
  * funciona dentro de un bucle de eventos en marcha;
  * cierre idempotente.
* `test_modules.py`: cada referencia existe y la matriz publicada está al día.
* `test_notebooks.py`: el notebook se ejecuta de principio a fin y no tiene resultados
  guardados.
