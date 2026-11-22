# Añadir una fuente de datos

Una fuente nueva (otro *exchange*, un proveedor de macro, un *broker*) entra con su adaptador,
su registro y sus casetes. El resto de la plataforma (el enrutado, la caché, la API, la web)
no cambia: la encuentra por lo que declara. Esta guía es la lista de comprobación.

## 1. Qué sirve: el puerto

Cada clase de dato tiene su puerto en `ports/market_data.py` y su tipo de dominio:

| Dato | `Dataset` | Puerto (método) | Tipo de dominio |
|---|---|---|---|
| Velas | `BARS` | `MarketDataProvider` (`fetch_bars`) | `PriceSeries` |
| Flujo por vela | `FLOW` | `TradeFlowProvider` (`fetch_flow`) | `FlowSeries` |
| Funding, préstamo, financiación | `HOLDING_RATES` | `HoldingRatesProvider` (`fetch_rates`) | `RateSeries` |
| *Open interest* y ratios largo/corto | `POSITIONING` | `PositioningProvider` (`fetch_positioning`) | `PositioningSeries` |
| Profundidad del libro por bandas | `BOOK_DEPTH` | `BookDepthProvider` (`fetch_book_depth`) | `BookDepthSeries` |
| Tamaño, dominancia y clasificación de un mercado | `REFERENCE` | `ReferenceDataProvider` (`fetch_market_snapshot`, `fetch_market_caps`) | `MarketSnapshot`, `MarketCapRanking` |
| Series económicas | `ECONOMIC` | `EconomicDataProvider` (`fetch_economic_series`) | `EconomicSeries` |

Un adaptador implementa los que sirva; el mismo proveedor puede dar varios (Binance da velas,
flujo, funding y posicionamiento). Si el dato no encaja en ninguno, hace falta un puerto y
un tipo de dominio nuevos, con su ADR: no se meten en uno existente.

## 2. El adaptador

En `adapters/providers/<nombre>/`:

* **Red solo con `HttpClient`** (reintentos, cuotas, redirecciones seguras y errores
  traducidos). Un fichero (ZIP, CSV) se baja con `get_bytes`.
* **Sus `ProviderCapabilities`**: los `datasets` que sirve, las clases de activo, las
  frecuencias, sus cuotas y su notación de símbolos (`identifiers`, una expresión regular).
  Si un dato usa otra notación u otras frecuencias que las velas, se declaran aparte con
  `identifiers_by_dataset` y `frequencies_by_dataset`. Para tipos de mantenimiento,
  `rate_kinds`; para posicionamiento, `positioning_fields`; para la profundidad del libro,
  `book_bands`.
* **Devuelve objetos de dominio validados**, nunca la respuesta cruda. Lo que la fuente no
  publica no existe (una columna ausente, un `NaN`), nunca se rellena.
* **Sus propias reglas, en su docstring**: unidades, zona horaria, cómo etiqueta los periodos,
  cuánto guarda, qué hace con lo que aún no ha terminado.
* **Todo o nada.** Si un rango empieza antes de lo que la fuente guarda, lo dice con un error
  en vez de responder con la cola: así el enrutador pregunta a la siguiente.
* **Errores con su tipo** (`SymbolNotFoundError`, `UnsupportedRequestError`,
  `ProviderDataError`...): el enrutador decide con ellos si prueba otra fuente.
* **Ficheros que no cambian.** Si la fuente publica su historia en ficheros con *checksum* y un
  listado con versiones (como Binance), se guardan con `PublishedFileCache` de
  `adapters/storage` ([ADR-0043](../adr/0043-verified-published-files-cache.md)): cada fichero
  se descarga una vez y se verifica de nuevo cada vez que se lee. El adaptador la recibe en su
  constructor y el Toolkit le da su carpeta, `<caché>/dumps/<nombre>`.

## 3. El registro

En `toolkit.py`, en `_remote_providers`, con su fábrica. El orden de registro es la preferencia
por defecto; para el funding y el posicionamiento hay preferencias propias (`FUNDING_ORDER`,
`POSITIONING_ORDER`): primero la fuente al día, después la que guarda la historia.

Una fuente registrada aparece sola en `tk.venues(símbolo, dataset)` y en la web, que lista
los *venues* que la API dice que sirven cada dato en lugar de tenerlos escritos.

## 4. Las casetes

En `scripts/record_fixtures.py`, una `Recording` por caso: uno normal, uno que pagine si
pagina, uno de símbolo inexistente y uno por cada regla con su error (un mes sin publicar, un
rango fuera de su historia...). Se graban con `uv run just record-fixtures <nombre>` y
**no se editan a mano**. Los cuerpos de fichero se guardan en base64.

Si `detect-secrets` marca cadenas de una casete (cuerpos en base64, rutas largas), se
registran una a una con `uv run detect-secrets scan --baseline .secrets.baseline <ficheros>`,
y se comprueba que el *hook* sigue detectando un secreto nuevo en otro fichero. Nunca una regla
de exclusión.

## 5. Los tests

* **El contrato**: un caso más en el contrato de su dato (`tests/contract/`), con su casete
  buena y la de símbolo inexistente. Es lo que garantiza que se comporta como las demás.
* **Las reglas propias**: un fichero `tests/unit/adapters/test_<nombre>.py` que compare con
  la casete leída por separado y pruebe cada regla con copias alteradas de lo grabado.
* **La descripción**: un test de sus `capabilities`.

## 6. La documentación

Su sección en [Fuentes de datos](data-sources.md), con lo que da y sus límites; y un ADR si
la forma de leerla es una decisión (otra API, volcados, un acuerdo de licencia).
