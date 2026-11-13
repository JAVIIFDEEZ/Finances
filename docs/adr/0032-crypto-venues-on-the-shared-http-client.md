---
status: aceptado
date: 2026-11-13
decision-makers: Javier Fernández
---

# *Venues* cripto con adaptadores propios sobre `HttpClient`, sin ccxt para leer datos

## Contexto y problema

La fase G1 del [plan de integración](../plan/integracion-cryptoworld.md) pide velas, flujo por
vela y funding de los *exchanges* cripto. El plan proponía un adaptador único sobre **ccxt**,
la librería que unifica más de cien *exchanges*, para sustituir los clientes propios de
CryptoWorld.

Al diseñarlo aparecen dos choques con las reglas del repositorio:

* La regla 6 de `CLAUDE.md` exige que todo proveedor use `HttpClient` para la red: reintentos,
  cuotas, traducción de errores al puerto y higiene de credenciales
  ([ADR-0012](0012-resilient-http-client.md)).
* Los tests no tocan la red: reproducen **casetes** de respuestas reales con `respx`, que
  intercepta `httpx` ([ADR-0025](0025-yahoo-chart-adapter-and-cassettes.md)). ccxt usa `aiohttp`
  en modo asíncrono y `requests` en modo síncrono: ni sus peticiones pasan por `HttpClient` ni
  `respx` las ve.

Además, para *leer* datos ccxt aporta poco que no esté ya en la plataforma: cada *exchange*
expone sus velas y su funding en uno o dos *endpoints* públicos sin clave, y lo difícil
(paginación, barras sin cerrar, etiquetas de sesión, validación) es nuestro de todas formas.

## Factores de decisión

* Una sola infraestructura de red, con las mismas garantías para todos los proveedores.
* Tests sin red sobre respuestas reales grabadas, que fallen si cambia lo que se envía.
* Datos completos del *exchange*: Binance da por vela el lado agresor, que ccxt descarta al
  normalizar a OHLCV.
* Pocas dependencias pesadas en el núcleo (ccxt arrastra ~100 módulos de *exchange*).
* Poder añadir un *venue* en una tarde.

## Opciones consideradas

* **ccxt** para todos los *venues*, envuelto en un adaptador.
* **Adaptadores propios por *venue*** sobre `HttpClient`, uno por proveedor.
* ccxt con un transporte `httpx` propio inyectado.

## Decisión

Adaptadores propios por *venue*, cada uno en `adapters/providers/<venue>/`, sobre `HttpClient`
y con casetes:

* **Binance** (`binance`): velas y flujo de los pares *spot* desde `data-api.binance.vision`,
  el espejo público de los *endpoints* de mercado que responde desde cualquier país
  (`api.binance.com` devuelve HTTP 451 en algunos). Una sola llamada (`/api/v3/klines`) da la
  vela y su flujo completo: unidades y valor negociados, operaciones y compra agresora.
* **OKX** (`okx`): funding de los perpetuos (`/api/v5/public/funding-rate-history`), el tipo
  realmente liquidado (`realizedRate`).
* **Yahoo** sirve además el volumen de sus barras como flujo sin lado agresor, para que el panel
  de flujo exista también para acciones, ETF e índices (D8).

Notación de símbolos, que decide el enrutado sin preguntar a nadie (`identifiers` de
`ProviderCapabilities`):

| Notación | Ejemplo | Quién la sirve |
|---|---|---|
| Símbolo de Yahoo (sin `/` ni `:`) | `SAN.MC`, `^GSPC`, `BTC-USD` | Yahoo |
| Par *spot* `BASE/QUOTE` | `BTC/USDT`, `ETH/BTC` | Binance |
| Perpetuo `BASE/QUOTE:SETTLE` | `BTC/USDT:USDT`, `BTC/USD:BTC` | OKX |

Es la notación unificada de ccxt, así que pasar a ccxt más adelante no cambiaría ningún símbolo.

Para que cada *venue* traduzca sus propios documentos de error (Binance responde HTTP 400 con el
código −1121 a un par desconocido; OKX, HTTP 200 con el código 51001), `HttpClient` acepta una
función `explain` que lee la respuesta antes de la traducción genérica por estado. Un baneo por
exceso de peticiones (HTTP 418 de Binance) es un `BannedError`, que **no** se reintenta: cada
reintento durante el baneo lo alarga.

### Consecuencias

* Bien, porque todos los proveedores comparten reintentos, cuotas, errores y registros, y sus
  tests reproducen respuestas reales sin red.
* Bien, porque el flujo de Binance llega completo: *delta* y CVD con la historia del par.
* Bien, porque un *venue* nuevo es un fichero de unas 300 líneas y una casete, sin dependencias.
* Mal, porque cada *venue* es código nuestro que mantener si cambia su API; las casetes lo
  detectan al regrabar (`just record-fixtures`).
* Neutral: ccxt sigue siendo la opción para **ejecutar** órdenes en G7, donde firmar peticiones
  de muchos *exchanges* sí justifica la dependencia. Esa decisión tendrá su propio ADR.

### Confirmación

* `tests/contract/` exige a Binance el contrato de velas, a Binance y Yahoo el de flujo y a OKX
  el de tipos de mantenimiento, sobre casetes grabadas.
* `test_binance.py` y `test_okx.py` prueban paginación, barras sin cerrar, errores y baneos.
* Ninguna dependencia nueva en `pyproject.toml`.

## Pros y contras de las opciones

### ccxt para todos los *venues*

* Bien, porque un mismo código sirve para muchos *exchanges*.
* Mal, porque salta `HttpClient` y las casetes con `respx` no funcionan: habría que mockear a
  mano o grabar con otra herramienta.
* Mal, porque normaliza a OHLCV y pierde el flujo de Binance, que es lo que G1 quiere.

### Adaptadores propios sobre `HttpClient` (elegida)

* Bien, por lo dicho en las consecuencias.
* Mal, porque son más líneas propias que una llamada a ccxt.

### ccxt con transporte `httpx` inyectado

* Mal, porque ccxt no admite inyectar un cliente `httpx`: habría que parchear su capa de red y
  depender de detalles internos que cambian entre versiones.

## Más información

* Lo que falta de G1 (otros *venues* de respaldo, funding de Binance y Bybit, interés abierto,
  CoinGecko, alternative.me, volcados de `data.binance.vision`, API y web) sigue este mismo
  patrón; ver el estado en el [plan maestro](../plan/plan-maestro.md).
* `api.binance.com`, `fapi.binance.com` y `api.bybit.com` rechazan las peticiones desde el
  contenedor de desarrollo en la nube (HTTP 451 y 403): sus casetes se graban desde un equipo
  que sí pueda llegar.
