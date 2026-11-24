# Guía del Toolkit

`Toolkit` es la puerta de entrada a InvestingLab desde un notebook o un script. Un solo objeto
sirve para:

* descargar varias series a la vez de todas las fuentes configuradas;
* leer el flujo de cada vela (`tk.flow`), el funding de los perpetuos (`tk.holding_rates`) y su
  interés abierto y ratios largo/corto (`tk.positioning`) y la profundidad de su libro por
  bandas (`tk.book_depth`), en el *venue* que se quiera (`tk.venues` dice cuáles lo sirven);
* calcular los indicadores técnicos de cualquier instrumento (`tk.technical`), sus patrones
  de precio (`tk.patterns`), su estructura (`tk.structure`), la confluencia entre marcos
  temporales (`tk.confluence`) y su ficha por pilares (`tk.card`);
* leer series económicas *point-in-time* (`tk.economic`), como el €STR o el índice de miedo y
  codicia cripto, y la foto del mercado cripto: su tamaño y dominancia (`tk.market_snapshot`) y
  sus mayores activos (`tk.market_caps`);
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

## Confluencia entre marcos temporales

`tk.confluence` lee en varios marcos el panel de once reglas de manual y la tendencia de
fondo, y dice si coinciden ([ADR-0038](../adr/0038-signal-panel-and-timeframe-confluence.md)).

```python
conf = tk.confluence("SAN.MC")  # diario, semanal y mensual, de una sola descarga
conf.summary.verdict, conf.summary.alignment, conf.summary.agreement
semanal = conf.frame("1w")
semanal.trend.direction  # up, down o sideways
semanal.panel.bullish, semanal.panel.neutral, semanal.panel.bearish
semanal.panel.trend_score, semanal.panel.reversal_score  # los dos estilos, por separado
tk.confluence("BTC/USDT", frames=["15m", "1h", "4h", "1d"])  # intradía, si la fuente lo sirve
```

Las reglas de **tendencia** siguen el movimiento y las de **giro** apuestan por su
agotamiento: en una tendencia fuerte se contradicen por construcción, y por eso se cuentan
aparte. Un marco que ninguna fuente sirve, o con menos de 50 velas, se informa con su motivo
(`issue`) y no cuenta; con menos de dos marcos legibles el veredicto es `insufficient`. Lo
que dice una regla no es una previsión: si alguna anticipa algo se medirá al validar
estrategias.

## Ficha de activo

`tk.card` reúne lo que dice cada pilar de evidencia sobre un instrumento, según su clase de
activo ([ADR-0040](../adr/0040-asset-card-with-pillars.md)).

```python
from investinglab.domain import Pillar

ficha = tk.card("BTC/USDT")
[p.pillar.value for p in ficha.pillars]  # technical, risk, derivatives, quality
ficha.pillar(Pillar.TECHNICAL).score  # la alineación de los marcos, en [-1, 1]
ficha.pillar(Pillar.RISK).fact("volatility").value
ficha.pillar(Pillar.DERIVATIVES).fact("funding_mean").value  # su perpetuo, anualizado
ficha.pillar(Pillar.DERIVATIVES).fact("open_interest_change").value  # contratos, 30 días
tk.card("SAN.MC").not_applicable  # (Pillar.DERIVATIVES,): una acción no tiene perpetuo
```

Solo el pilar técnico es direccional; los demás describen. Un pilar que se aplica pero cuyos
datos no sirve ninguna fuente va con `issue` y los demás se leen igual. No hay veredicto que
los fusione: los pesos entre pilares se aprenderán en G4, con su muestra a la vista.

## Backtest

`series.backtest(signals)` opera una serie con unas señales y devuelve sus operaciones, su
*equity* y sus métricas ([ADR-0049](../adr/0049-backtest-engine.md)). El motor es el de
CryptoWorld, con paridad comprobada: la misma estrategia da las mismas operaciones en las dos
plataformas.

```python
from investinglab.domain import BacktestConfig, CostModel, RiskModel

san = tk.series("SAN.MC", start="2020-01-01")
rapida, lenta = san.prices.rolling(10).mean(), san.prices.rolling(30).mean()
cruce = (rapida > lenta).astype(int).diff().fillna(0)  # 1 abre, -1 cierra, 0 mantiene

config = BacktestConfig(
    costs=CostModel(
        commission_bps=10,  # 0,1 % por orden...
        minimum_commission=4,  # ...con un mínimo de 4 € (el de tu broker)
        slippage_bps=5,  # medio spread más el impacto
        transaction_tax_bps=20,  # el ITF: 0,2 % de cada compra de una gran cotizada española
    ),
    risk=RiskModel(stop_loss_pct=0.08, trailing_stop_pct=0.05),
)
r = san.backtest(cruce, config=config)
r.total_return, r.buy_and_hold  # la estrategia frente a mantener
r.metrics().sharpe_ratio  # anualizado con 252 sesiones: el calendario de la Bolsa de Madrid
r.statistics.win_rate, r.statistics.profit_factor
r.costs  # comisión, impuesto, deslizamiento, funding y préstamo, por separado
r.trades[0].exit_reason  # signal, stop_loss, trailing_stop, take_profit, time_exit…
```

* **Cuándo se rellena una orden.** La señal de una vela se rellena a la apertura de la
  siguiente: nunca al cierre que la originó. La siguiente a un viernes es la del lunes, o la
  del martes si el lunes es festivo.
* **Barreras.** Los *stops* y los objetivos saltan dentro de la vela, a su precio. Si una vela
  toca los dos, gana el *stop*.
* **Cortos.** `short_signals` abre y cierra el lado corto. `borrow`, por vela, es el coste de
  préstamo del corto. `funding`, por vela, es el de un perpetuo: positivo, pagan los largos.
* **Dividendos.** Con precios ajustados (Yahoo los da), el resultado es un retorno total.
* **Tamaño.** `SizingModel` decide cuánto de la *equity* entra:
  * todo;
  * una fracción;
  * por riesgo, lo que se pierde si salta el *stop*;
  * por convicción, una fracción por señal.

### Estrategias como datos

Una estrategia también puede escribirse como dato, con la gramática de CryptoWorld
([ADR-0050](../adr/0050-strategies-as-data.md)): bloques de entrada y salida con condiciones
sobre los indicadores y los patrones del catálogo. Se valida, se guarda en JSON y tiene un
*hash* que la identifica.

```python
import json

from investinglab.analytics.search import (
    CLASSICS,
    Block,
    Compare,
    Leg,
    Operator,
    StrategySpec,
    Threshold,
)
from investinglab.domain import RiskModel

precio, rsi = Leg("PRICE"), Leg("RSI", {"window": 14})
retroceso = StrategySpec(
    entry=Block(
        (
            Threshold(rsi, Operator.LT, 40),  # RSI barato…
            Compare(precio, Leg("SMA", {"window": 150}), Operator.ABOVE),  # …en tendencia
        )
    ),
    exit=Block((Threshold(rsi, Operator.GT, 65),)),
    risk=RiskModel(stop_loss_pct=0.08),
)
r = san.backtest_strategy(retroceso, costs=config.costs)
r.ready_at  # desde cuándo se conocen todas sus condiciones: antes, sus indicadores calientan
r.strategy.definition_hash  # el mismo que en CryptoWorld

san.backtest_strategy(CLASSICS["donchian_breakout"])  # las siete clásicas, con nombre
StrategySpec.from_dict(
    json.loads(texto)
)  # la forma JSON de CryptoWorld, con errores que dicen dónde
```

* **Cinco condiciones:**
  * umbral, un oscilador por encima o por debajo de un valor;
  * cruce entre dos niveles, en la vela en que ocurre;
  * estado, un nivel por encima o por debajo de otro mientras dure;
  * pendiente, cualquier indicador al alza o a la baja frente a hace `bars` velas;
  * patrón, en esta vela o en alguna de las `lookback − 1` anteriores.
* **Bloques:** de una a tres condiciones con `AND`, `OR` o «al menos `k`» (`K_OF_N`). Todas
  menos el cruce admiten `negate`.
* **Dirección:** `long`, `short` (los mismos bloques abren cortos) o `both` (con
  `short_entry` y `short_exit` propios).
* **Riesgo y tamaño** viajan con la estrategia; los costes y el capital son del mercado y se
  pasan al backtest.
* **Lo que no se conoce no da señal.** Mientras un indicador calienta, la condición que lo lee
  no se cumple, ni negada.

### Con los costes de su mercado

`tk.backtest` descarga la serie, opera una estrategia con los costes del mercado donde cotiza y,
si es un perpetuo, con el *funding* que hubo ([ADR-0051](../adr/0051-market-cost-profiles.md)):

```python
r = tk.backtest("SAN.MC", "sma_crossover", start="2021-01-01")
r.market.profile.key  # "XMAD": la Bolsa de Madrid
r.market.tax_presumed  # True: sin ISIN, se presume una gran empresa española (ITF)
r.costs.tax  # el ITF de cada compra, desde el 16 de enero de 2021

tk.backtest("SAN.MC", retroceso, commission_bps=5, minimum_commission=3)  # tu bróker
tk.backtest("BTC/USDT", "ema_trend", start="2025-06-01")  # Binance al contado: 0,10 %
tk.backtest("BTC/USDT", corta, profile="binance-usdm")  # el perpetuo, con su funding
```

* **Calentamiento.** Se descarga un año de historia antes de `start`: los indicadores llegan
  calientes y la estrategia opera desde `start`.
* **Perfiles** (`COST_PROFILES`): uno por bolsa, por su MIC, y uno por producto de cada
  plataforma cripto (`binance-spot`, `binance-usdm`, `kraken-spot`, `coinbase-spot`). Cada uno
  lleva:
  * sus fuentes y la fecha en que se leyeron (`as_of`);
  * qué cifras son supuestos (`assumed`): en una bolsa, la comisión del 0,10 %, el
    deslizamiento del 0,05 % y el préstamo de un corto del 0,50 % anual;
  * qué costes deja fuera (`unmodelled`).
* **Impuestos con fecha.** El ITF (España), la TTF (Francia), el IFTT (Italia) y el *stamp duty*
  (Reino Unido) se cobran al tipo en vigor el día de cada compra, y nada antes de que
  existieran. Siguen al emisor: con ISIN, decide su país; sin él, se presume. Los ETF no los
  pagan.
* **Cortos.** Una acción paga su préstamo por días naturales. Un mercado al contado de cripto
  no se puede vender en corto: la estrategia que lo hace necesita el perpetuo.
* ***Funding*.** Se reparte por velas: una vela paga las liquidaciones que caen en ella. Uno que
  no se ha publicado no es cero, así que el backtest acaba en la última vela liquidada.

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
