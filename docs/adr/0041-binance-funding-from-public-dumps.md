---
status: aceptado
date: 2026-11-17
decision-makers: Javier Fernández
---

# Funding de Binance desde sus volcados públicos verificados

## Contexto y problema

G1 pide el *funding* de BTC en tres *venues* y su historia larga. OKX ya lo da por API
([ADR-0032](0032-crypto-venues-on-the-shared-http-client.md)), pero solo guarda unos tres
meses. Binance es el mayor mercado de perpetuos y su API de futuros (`fapi.binance.com`)
rechaza algunos países y este entorno (HTTP 451), así que no se puede grabar ni probar desde
aquí. Binance publica además volcados en `data.binance.vision`: un ZIP por contrato y mes con
el tipo de cada liquidación y su intervalo, cada uno con su SHA-256 en un `.CHECKSUM`, desde
que se listó el contrato.

Dos cosas complican los volcados: un fichero que no existe responde 404 tanto si el mes aún no
se ha publicado como si el contrato no existe, y el mes en curso no se publica hasta que
termina (algunos mercados, como el COIN-M, han dejado de publicarse en junio de 2026).

## Factores de decisión

* Nunca inventar ni ocultar: un dato que falta o que llega tarde se dice.
* Integridad verificable de lo que entra.
* Que el *funding* por defecto siga siendo el más reciente.
* Probarlo sin red, con respuestas reales grabadas.

## Opciones consideradas

1. La API de futuros de Binance, con casetes grabadas desde el equipo del usuario.
2. Los volcados públicos, verificados, dentro del adaptador de Binance.
3. Esperar a otra fuente agregada (CoinGlass, Coinalyze), con clave y licencia.

## Decisión

Opción 2.

* **Listado del *bucket*.** El S3 detrás de `data.binance.vision` lista los ficheros de una
  carpeta. Se pide desde el mes anterior al rango (marcador `marker`) hasta el último mes del
  rango, y se descargan solo esos ficheros. Una carpeta vacía es un contrato que Binance no
  tiene (`SymbolNotFoundError`); un rango sin ficheros dice cuál es el último mes publicado.
  El XML se lee con la biblioteca estándar después de rechazar cualquier documento que
  declare un DTD o entidades.
* **Integridad.** Cada ZIP se compara con el SHA-256 de su `.CHECKSUM` (que debe nombrar ese
  fichero) antes de abrirlo; debe tener un solo CSV, con un límite de tamaño descomprimido.
  Lo que no cuadra se rechaza, nunca se usa.
* **Contratos.** `BTC/USDT:USDT` y `ETH/USDC:USDC` son USDⓈ-M (`BTCUSDT`, `ETHUSDC`);
  `BTC/USD:BTC`, COIN-M (`BTCUSD_PERP`). Cada pago se indexa en el segundo de su cálculo en
  UTC (Binance lo sella unos milisegundos después de la hora). El mes anterior al rango entra
  en la descarga para deducir el intervalo aunque el rango tenga un solo pago.
* **En el proveedor `binance`.** El *venue* es Binance, así que `venue="binance"` lo pide como
  `venue="okx"` pide el de OKX. Para que un mismo proveedor declare pares para las velas y
  perpetuos para el *funding*, `ProviderCapabilities` admite identificadores por conjunto de
  datos (`identifiers_by_dataset`).
* **Orden por defecto.** El registro admite una preferencia de tipos de mantenimiento por
  clase (`prefer_rates`). El Toolkit pide el *funding* primero a OKX (al día) y después a
  Binance (que añade la historia que OKX no guarda): un rango de hace un año va a Binance solo,
  y nadie recibe sin pedirlo una serie que acaba el último día del mes pasado.
* **Casetes binarias.** El grabador guarda en base64 los cuerpos de fichero (`binary/octet-stream`,
  ZIP) y la reproducción los devuelve tal cual.

### Consecuencias

* Buenas: *funding* de Binance con toda su historia, verificado, sin clave y desde cualquier
  país; dos *venues* alineados en las mismas horas; el contrato de proveedores lo cubre.
* Malas: el mes en curso no está hasta que termina, de modo que Binance no sirve para el último
  pago; la web lo dice con la fecha del último pago. El COIN-M dejó de publicarse en junio de
  2026. Leer años enteros son decenas de descargas (cada mes, su fichero y su *checksum*), sin
  caché en disco todavía.

### Confirmación

Casetes reales de un lineal, un inverso, el mes en curso sin publicar, un mercado que dejó de
publicarse y un contrato inexistente; tests de integridad con copias alteradas (un bit
cambiado, un *checksum* de otro fichero, dos CSV, un listado con DTD); el contrato de
proveedores de tipos de mantenimiento con Binance y OKX; y una comprobación con red real: OKX
hasta hoy, Binance hasta el 31 de octubre y un rango de 2025 servido por Binance.

## Pros y contras de las opciones

### API de futuros con casetes desde el equipo del usuario

* Bueno: el mes en curso, al día.
* Malo: no se puede probar ni grabar desde la nube; depende del país desde el que se llama.

### Fuente agregada de pago

* Bueno: varios *venues* en una sola llamada, con OI y ratios.
* Malo: clave, licencia y coste; decisión del usuario (§10.4 del plan).

## Más información

* Pendiente: el *open interest* y los ratios largo/corto de los mismos volcados (`metrics`, cada
  5 minutos) y del histórico de OKX; caché en disco de los ficheros mensuales, que no cambian;
  el tercer *venue* (Bybit, Hyperliquid o Deribit), según lo que responda.
