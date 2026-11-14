# Guía del Toolkit

`Toolkit` es la puerta de entrada a InvestingLab desde un notebook o un script. Un solo objeto
sirve para:

* descargar varias series a la vez de todas las fuentes configuradas;
* leer el flujo de cada vela (`tk.flow`) y el funding de los perpetuos (`tk.holding_rates`);
* calcular los indicadores técnicos de cualquier instrumento (`tk.technical`), sus patrones
  de precio (`tk.patterns`) y su estructura (`tk.structure`);
* leer series económicas *point-in-time* (`tk.economic`), como el €STR o el índice de miedo y
  codicia cripto;
* construir carteras en una divisa base;
* revisar la calidad de los datos con el calendario oficial de cada mercado;
* escribir informes que ya usan el tipo libre de riesgo *point-in-time*.

```python
from investinglab.toolkit import Toolkit

with Toolkit.from_settings() as tk:
    lote = tk.many(["SAN.MC", "ITX.MC", "IBE.MC"], start="2019-01-01")
    cartera = tk.portfolio("Núcleo", {"SAN.MC": 0.4, "ITX.MC": 0.3, "IBE.MC": 0.3})
    tk.report(cartera).save("informes/nucleo.md")
    cartera.plots_report().save("informes/graficos")
```

La demo completa está en `notebooks/b1_toolkit_demo.ipynb`.

## Fuentes de datos

`Toolkit.from_settings()` lee la configuración (`INVESTINGLAB_*`, ver `.env.example`) y
registra las fuentes disponibles en este orden de prioridad:

1. Los proveedores que le pases en `providers=[...]`.
2. Los **ficheros locales** de `INVESTINGLAB_LOCAL_DATA_DIR`, si está definida.
3. El **BCE** (divisas oficiales y €STR), **Yahoo Finance**, **Binance** (pares cripto y su
   flujo), **OKX** (funding de perpetuos) y **alternative.me** (miedo y codicia cripto), sin
   clave, salvo con `INVESTINGLAB_OFFLINE=true` (ver [Fuentes de datos](data-sources.md)). Alpha Vantage y FRED/ALFRED completan la fase
   F2b cuando haya claves.

Lo descargado se guarda en la caché Parquet (`INVESTINGLAB_DATA_DIR/cache`). Cuando una
entrada caduca, solo se descarga el tramo nuevo y se comprueba que las últimas barras
guardadas no han cambiado. Si un dividendo o un *split* reajustó la historia, se descarga
todo de nuevo. Usa `refresh=True` para ignorar la caché.

### Ficheros locales

Sirven para trabajar sin red, con exportaciones de tu bróker o con datos propios. La carpeta
contiene:

* un fichero por símbolo, `SAN.MC.csv` o `SAN.MC.parquet`;
* un `instruments.toml` que describe cada fichero. Es obligatorio, porque un fichero de precios
  no dice en qué divisa ni en qué mercado están sus cifras, y la plataforma nunca lo adivina.

```toml
["SAN.MC"]
name = "Banco Santander"
currency = "EUR"
exchange = "XMAD"
isin = "ES0113900J37"
adjustment = "splits_and_dividends"

["VOD.L"]
currency = "GBp"          # peniques: los precios se convierten a libras
exchange = "XLON"

["BTC-EUR"]
currency = "EUR"
asset_class = "crypto"
exchange = "CRYPTO"

["SPY.H"]
currency = "USD"
exchange = "XNYS"
frequency = "1h"
timezone = "America/New_York"   # zona de las horas del fichero si no la indican
```

| Campo | Obligatorio | Valores |
|-------|:-----------:|---------|
| `currency` | ✓ | ISO 4217; `GBp`/`GBX`, `ZAc`, `ILA` y `KWF` para unidades menores |
| `name` | | Nombre del instrumento (por defecto, el símbolo) |
| `asset_class` | | `equity`, `etf`, `fund`, `index`, `bond`, `fx`, `crypto`, `commodity`, `future` |
| `exchange` | | MIC del mercado (`XMAD`, `XNYS`, `XETR`…), `CRYPTO` o `FX` |
| `isin` | | Se valida su dígito de control |
| `frequency` | | `1d` por defecto; de `1m` a `1y` |
| `adjustment` | | `raw`, `splits` o `splits_and_dividends` |
| `columns` | | Correspondencias extra de columnas, p. ej. `{ "Cierre ajustado" = "adj_close" }` |
| `timezone` | | Zona horaria de las horas *naive* en datos intradía (UTC por defecto) |

Columnas reconocidas sin configurar nada (en inglés o español):

* `Date`/`Fecha`;
* `Open`/`Apertura`, `High`/`Máximo`, `Low`/`Mínimo`;
* `Close`/`Cierre`/`Último`, `Adj Close`;
* `Volume`/`Volumen`.

La importación es estricta:

* **Se permite:** reordenar las fechas y quitar las filas sin ningún precio (un festivo exportado
  como fila vacía no es una observación).
* **Se rechaza, nunca se repara:** fechas duplicadas, cierres ausentes y precios no positivos.

Un fichero suelto se importa sin carpeta:

```python
san = tk.load("descargas/SAN.csv", symbol="SAN.MC", currency="EUR", exchange="XMAD")
serie = tk.from_dataframe(df, symbol="X", currency="USD")
```

## Indicadores técnicos

`tk.technical` calcula los 26 indicadores del catálogo de CryptoWorld
([ADR-0034](../adr/0034-technical-indicators-in-numpy.md)) sobre las barras de cualquier
símbolo: el mismo RSI para `SAN.MC`, `^GSPC`, `EURUSD=X` o `BTC/USDT`.

```python
tec = tk.technical("SAN.MC", start="2025-01-01", names=["RSI", "MACD_LINE", "ADX"])
tec["RSI"]  # serie con NaN durante el calentamiento, nunca valores inventados
tec.latest()  # valor de cada indicador en la última vela
tec.threshold("RSI")  # rango de umbrales que explora CryptoWorld: (15.0, 85.0)
tec.unavailable  # {} aquí; en una serie sin volumen, {"MFI": ("volume",), …}
```

En barras diarias o más largas descarga también historia anterior a `start` (400 días para
las diarias) para que los indicadores ya estén calentados en esa fecha. Un indicador que
necesita una columna que la serie no tiene (el volumen de un par de divisas) no se calcula con
sustitutos: queda en `unavailable` con las columnas que le faltan.

## Patrones de precio

`tk.patterns` busca los 25 patrones del catálogo
([ADR-0035](../adr/0035-causal-price-patterns.md)) en las velas de cualquier símbolo: velas
japonesas, huecos de valor (FVG), barridas de liquidez, *order blocks*, CRT, *Power of Three*,
la ruptura del rango de apertura y las zonas de Fibonacci.

```python
pat = tk.patterns("SAN.MC", start="2025-01-01")
pat["SWEEP_LOW"]  # una bandera por vela, en la vela que completa el patrón
pat.events()  # cada suceso (time, pattern), del más antiguo al más reciente
pat.last("BULL_ENGULF"), pat.count("BULL_ENGULF")
pat.active()  # lo que marca la última vela (las zonas en las que está el precio)
pat.unavailable  # {"ORB_UP": ("intraday",), ...} con velas diarias
```

Como `tk.technical`, en barras diarias o más largas descarga historia anterior a `start`, así
que un *order block* o un *swing* que se formó antes cuenta después. La ruptura del rango de
apertura necesita barras intradía y toma la sesión del mercado (la fecha local de la bolsa, o
la UTC en los mercados que no cierran). Un patrón que necesita una columna que la serie no
tiene (la apertura de una serie de cierres) no se calcula con sustitutos.

## Estructura de precio

`tk.structure` describe la serie a su última vela
([ADR-0036](../adr/0036-price-structure-with-confirmation-times.md)): soportes y resistencias
por agrupación de pivotes (con cuántas veces y cuándo los tocó el precio), divergencias entre
el cierre y su RSI y los niveles de Fibonacci del último *swing*.

```python
st = tk.structure("SAN.MC", start="2025-06-01")
st.nearest_support, st.nearest_resistance
for d in st.divergences:
    print(d.kind, d.first_at, d.second_at, "confirmada el", d.confirmed_at)
st.fibonacci.levels  # ((0.236, precio), (0.382, precio), …)
st.basis  # "range" con máximos y mínimos; "close" si la serie solo tiene cierres
```

Un pivote necesita `k` velas posteriores (3 por defecto) para confirmarse, así que cada
divergencia dice desde qué vela se sabe, no solo que existe.

## Carteras en varias divisas

```python
from investinglab.domain import RebalancePolicy

cartera = tk.portfolio(
    "Global",
    {"SAN.MC": 0.5, "SPY": 0.5},
    base_currency="EUR",
    rebalance=RebalancePolicy.threshold(0.05),
)
```

Las series en otra divisa se convierten con el último fixing publicado en cada fecha (por
ejemplo, `USDEUR=X`). Sin fixing reciente, la observación se descarta: nunca se rellena. Si los
activos usan divisas distintas, hay que indicar `base_currency`.

## Informes

`tk.report(sujeto, **opciones)` acepta las mismas opciones que `report()`
([Informes y gráficos](../architecture/reporting.md)) y además:

* usa el tipo libre de riesgo *point-in-time* de la divisa (€STR o el tipo de depósito del BCE en
  EUR, T-Bill a 3 meses en USD), salvo que pases `risk_free_rate`;
* convierte cada tipo a TAE según su convención: el €STR cotiza a un día en base ACT/360, así
  que un 3,5 % equivale a un 3,61 % anual compuesto;
* comprueba la calidad de los datos con el calendario oficial de cada mercado.

Si no hay fuente para el tipo libre de riesgo, o si no cubre todo el histórico, el informe lo
indica en sus diagnósticos. Un `risk_free_rate` constante se interpreta como TAE.

## Código asíncrono

`Toolkit` es síncrono y funciona dentro de Jupyter, porque ejecuta las corrutinas en un hilo
con su propio bucle de eventos. Desde código asíncrono, usa `AsyncToolkit` (los mismos métodos,
con `await`) o `tk.asynchronous`.

Si interrumpes una celda (el botón de parar o Ctrl+C), la operación en curso se cancela: no se
queda descargando en segundo plano. Para acotar cuánto puede durar cada llamada, define
`INVESTINGLAB_TOOLKIT_TIMEOUT_SECONDS` o pasa `Toolkit(..., timeout=segundos)`; al agotarse,
la operación se cancela y se lanza `TimeoutError`. Por defecto no hay límite, porque cada
petición HTTP ya tiene el suyo.

Cierra el `Toolkit` al terminar, con `close()` o con un bloque `with`, para liberar las
conexiones de red.
