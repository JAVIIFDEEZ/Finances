---
status: aceptado
date: 2026-11-09
decision-makers: Javier Fernández
---

# Yahoo Finance con el endpoint *chart* y pruebas con casetes grabadas

## Contexto y problema

[ADR-0012](0012-resilient-http-client.md) previó un adaptador de Yahoo Finance basado en
`yfinance`, ejecutado en un hilo. Al implementarlo en la fase F2b hay que decidir cómo se
obtienen los datos de Yahoo, que no tiene API oficial, y cómo se prueban los adaptadores sin
red y sin inventar datos (CLAUDE.md: «HTTP se mockea con `respx` usando respuestas reales
grabadas»).

## Factores de decisión

* Las reglas de datos: nada inventado, sesiones con su fecha de mercado, solo barras cerradas.
* Un único cliente HTTP con reintentos, cuotas, traducción de errores e higiene de secretos.
* Pocas dependencias y control sobre lo que se pide y se recibe.
* Pruebas reproducibles, sin red, con respuestas reales.

## Opciones consideradas

* `yfinance` en un hilo (`asyncio.to_thread`).
* El endpoint público `/v8/finance/chart/{símbolo}` con el `HttpClient` común.
* Solo proveedores con API oficial (Alpha Vantage, Tiingo…), sin Yahoo.

## Decisión

Opción elegida: **el endpoint `chart` con el `HttpClient` común**, porque es el único que
respeta todas las reglas de datos sin parches y reutiliza la infraestructura ya probada.

El adaptador (`adapters/providers/yahoo/`) se compone de:

* `payload.py`: modelos Pydantic del documento JSON, validado en el borde. Un cambio de
  formato produce un `ProviderDataError` claro, no un `KeyError`.
* `venues.py`: códigos de mercado de Yahoo (`MCE`, `NMS`, `LSE`…) → MIC ISO 10383, y
  `instrumentType` → `AssetClass`. Un mercado no listado queda desconocido; no se adivina.
* `provider.py`: `YahooFinanceProvider`, sin clave, registrado por defecto en el `Toolkit`
  detrás de los ficheros del usuario (salvo `INVESTINGLAB_OFFLINE=true`).

Reglas que aplica, además de la validación del dominio:

| Regla | Motivo |
|-------|--------|
| Barras diarias etiquetadas con la fecha de sesión en la zona del mercado (`exchangeTimezoneName`) | Una sesión de Sídney empieza el día UTC anterior; EUR/USD cierra a medianoche de Londres |
| Se descarta la barra de la sesión en curso (`currentTradingPeriod`) y toda barra intradía sin cerrar | Una barra parcial no es un cierre |
| Se descarta la barra «instantánea» que Yahoo añade fuera de la rejilla del intervalo | No es una barra del intervalo pedido |
| Una barra sin cierre es una observación ausente; si falta algún `open/high/low`, esas columnas no se incluyen | Nunca se rellenan precios |
| `GBp`, `ZAc`, `ILA` → divisa principal con `parse_quote_currency` | Error clásico de escala ×100 |
| OHLC ajustado por *splits*; `adj_close` por *splits* y dividendos (`PriceAdjustment.SPLITS`) | Es lo que publica el endpoint |
| Semanal, mensual, trimestral y anual se agregan desde el diario con `PriceSeries.resample` | Etiquetas por última sesión observada, como el resto de la plataforma |
| Ventanas de petición con un día de margen a cada lado y recorte posterior por fecha de sesión | Cubre mercados al otro lado de la línea de cambio de fecha |
| Profundidad intradía: 1m → 30 días (peticiones de 7 días), 5m/15m/30m → 60, 1h/4h → 730 | Límites observados; las capacidades anuncian un día menos |
| Cuotas propias: 4 peticiones/s y 1 500/h; `User-Agent` que identifica InvestingLab | Yahoo no publica cuotas y responde 429 a clientes que no parecen navegadores |

**Casetes.** `just record-fixtures` (`scripts/record_fixtures.py`) ejecuta el adaptador real
con un transporte que graba cada intercambio en
`tests/fixtures/cassettes/<proveedor>/<nombre>.json`: petición exacta, respuesta, hora de
grabación y propósito. `support.cassettes` los reproduce con `respx` comparando la URL y los
parámetros **exactos**, de modo que un cambio en lo que envía el adaptador rompe el test. Son
extractos breves (≈ 90 KB en total) para probar el análisis sintáctico, no un conjunto de
datos. Los tests de robustez alteran una *copia* de una respuesta grabada y lo indican.

**Contrato común.** `tests/contract/test_market_data_providers.py` comprueba que todo
proveedor cumple el puerto (nombre, capacidades, símbolo y frecuencia pedidos, procedencia,
`SymbolNotFoundError`). Un proveedor nuevo se añade con un caso.

### Consecuencias

* Positiva: sin dependencias nuevas; Yahoo pasa por los mismos reintentos, cuotas y errores.
* Positiva: las fechas de sesión y las barras cerradas son correctas por construcción.
* Positiva: los tests usan respuestas reales y fallan si cambia la petición.
* Negativa: el endpoint no está documentado y puede cambiar. Mitigación: validación del
  documento en el borde, casetes que se regraban con un comando y *fallback* a otros
  proveedores en el registro.
* Negativa: los dividendos y *splits* (`events`) aún no se exponen como datos propios.

### Confirmación

* `tests/unit/adapters/test_yahoo.py` (casetes reales de Madrid, Londres en peniques,
  EUR/USD, Sídney, el *split* de NVDA, el S&P 500 agregado a mensual, BTC con la sesión
  abierta y barras horarias con la instantánea).
* `tests/contract/test_market_data_providers.py`.
* `tests/unit/test_toolkit.py`: Yahoo se registra por defecto, detrás de los ficheros
  locales, y no se registra en modo `offline`; los tests siempre se ejecutan sin red.

## Pros y contras de las opciones

### `yfinance` en un hilo

* Positivo: mantenida por la comunidad; cubre fundamentales, opciones y noticias.
* Negativo: arrastra muchas dependencias y E/S bloqueante; su propia caché y su propio
  manejo de errores quedan fuera del `HttpClient`.
* Negativo: por defecto ajusta y «repara» precios, lo que choca con «nunca inventar datos».

### Endpoint `chart` con el `HttpClient` común

* Positivo: un endpoint, control total de fechas, ajustes y barras incompletas.
* Negativo: hay que seguir los cambios del formato (mitigado arriba).

### Sin Yahoo

* Positivo: solo APIs oficiales.
* Negativo: sin datos sin clave para índices, ETFs europeos, divisas y cripto.

## Más información

* Sustituye el párrafo sobre Yahoo de [ADR-0012](0012-resilient-http-client.md).
* Plan maestro, sección 10 (fuentes de datos) y fase F2b.
* Revisar si Yahoo publica cuotas o un endpoint oficial, o si `events` se convierte en un
  conjunto de datos de acciones corporativas.
