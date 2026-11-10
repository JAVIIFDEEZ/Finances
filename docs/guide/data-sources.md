# Fuentes de datos

InvestingLab descarga datos de varias fuentes con la misma interfaz: pides un símbolo, unas
fechas y una frecuencia, y recibes una `PriceSeries` validada. El `Toolkit` prueba las fuentes
en orden de prioridad y pasa a la siguiente si una falla (ver [Guía del Toolkit](toolkit.md)).

| Orden | Fuente | Clave | Qué sirve |
|-------|--------|-------|-----------|
| 1 | Ficheros locales | No | Lo que haya en tu carpeta (sin red; ver la guía del Toolkit) |
| 2 | **BCE** | No | Tipos de referencia del euro (divisas, diario) y €STR y tipos oficiales |
| 3 | **Yahoo Finance** | No | Acciones, ETFs, fondos, índices, divisas, cripto y futuros |

Cada fuente declara qué símbolos sirve, así que una acción va directa a Yahoo y `EURUSD=X`
diario al BCE.

## Yahoo Finance

```python
from investinglab.toolkit import Toolkit

with Toolkit.from_settings() as tk:
    santander = tk.series("SAN.MC", start="2015-01-01")
    vodafone = tk.series("VOD.L", start="2020-01-01")  # en GBP, no en peniques
    sp500 = tk.series("^GSPC", start="2000-01-01", frequency="1mo")
    eurusd = tk.series("EURUSD=X", start="2024-01-01")
    bitcoin = tk.series("BTC-USD", start="2024-01-01")
    horas = tk.series("SAN.MC", start="2026-10-01", frequency="1h")
```

### Símbolos

Los símbolos de InvestingLab siguen el estilo de Yahoo:

| Tipo | Ejemplos |
|------|----------|
| Acciones españolas, alemanas, británicas… | `SAN.MC`, `SAP.DE`, `VOD.L`, `MC.PA`, `7203.T` |
| Acciones y ETFs de EE. UU. | `AAPL`, `NVDA`, `SPY` |
| Índices | `^GSPC` (S&P 500), `^IBEX`, `^STOXX50E` |
| Divisas | `EURUSD=X` (dólares por euro) |
| Cripto | `BTC-USD`, `ETH-EUR` |
| Futuros | `ES=F`, `CL=F` |

### Frecuencias y profundidad

| Frecuencia | Origen | Historia disponible |
|------------|--------|---------------------|
| `1m` | Yahoo | Últimos 30 días (se pide en tramos de 7 días) |
| `5m`, `15m`, `30m` | Yahoo | Últimos 60 días |
| `1h`, `4h` | Yahoo | Últimos 730 días |
| `1d` | Yahoo | Toda la historia |
| `1w`, `1mo`, `1q`, `1y` | Agregadas desde `1d` | Toda la historia |

Para datos intradía hay que indicar `start`: sin él, el registro no elige Yahoo.

### Qué garantiza el adaptador

* **Fechas de sesión correctas.** Cada barra diaria lleva la fecha de su sesión en la zona del
  mercado: la sesión del lunes en Sídney empieza el domingo en UTC y sigue siendo «lunes».
* **Solo barras cerradas.** La sesión en curso y la barra intradía sin terminar no se incluyen:
  una barra parcial no es un cierre. Vuelve a pedir la serie al cierre del mercado.
* **Nada inventado.** Una barra sin cierre es un hueco. Si a alguna barra le falta la apertura,
  el máximo o el mínimo, esas columnas no se incluyen en la serie; nunca se rellenan.
* **Divisa principal.** Las cotizaciones en peniques (`GBp`) se convierten a libras (`GBP`).
* **Ajustes.** Apertura, máximo, mínimo y cierre están ajustados por *splits*; `adj_close`
  (diario y superior) también por dividendos, y es la columna que usan las estadísticas.
* **Agregación coherente.** Semanal y superiores se etiquetan con la última sesión observada
  de cada periodo, como en el resto de la plataforma.

Yahoo no tiene API oficial ni publica cuotas. El adaptador se limita a 4 peticiones por
segundo y 1 500 por hora, reintenta los errores transitorios y respeta `Retry-After`.

## Banco Central Europeo

```python
with Toolkit.from_settings() as tk:
    eurusd = tk.series("EURUSD=X", start="2020-01-01")  # dólares por euro, oficial
    usdeur = tk.series("USDEUR=X", start="2020-01-01")  # su inverso
    gbpusd = tk.series("GBPUSD=X", start="2020-01-01")  # cruce: dos tipos del mismo día
    tipos = tk.risk_free("EUR", eurusd.bars.index)  # €STR conocido en cada fecha
```

* **Divisas.** Los tipos de referencia de las 14:15 CET, publicados hacia las 16:00, de las
  30 divisas que publica el BCE. Cada barra lleva solo el cierre y la fecha del *fixing*; los
  festivos TARGET no tienen barra. Los pares sin euro se calculan con los dos tipos del mismo
  día. Para intradía, o para un par sin tipo de referencia, responde Yahoo.
* **Tipos de interés.** €STR (`EST.B.EU000A2X2A25.WT`) y los tipos oficiales del BCE
  (`FM.D.U2.EUR.4F.KR.DFR.LEV`, `…MRR_FR…`, `…MLFR…`). Cada valor lleva el día en que se
  conoció: €STR, el siguiente día hábil TARGET; los tipos oficiales, su propia fecha. Son la
  fuente por defecto del tipo libre de riesgo en euros, sin necesidad de clave de FRED.

## Trabajar sin red

Con `INVESTINGLAB_OFFLINE=true` no se registra ninguna fuente remota: solo se usan tus
ficheros locales y la caché. Es útil para demos reproducibles y es el modo en el que se
ejecutan siempre los tests.

## Para desarrolladores: casetes

Los tests de los adaptadores no usan la red. Reproducen respuestas **reales** grabadas en
`packages/investinglab/tests/fixtures/cassettes/` con:

```bash
uv run just record-fixtures            # todas las casetes
uv run just record-fixtures yahoo/btc  # solo las que contienen el texto
```

Cada casete guarda la petición exacta, la respuesta, la hora de grabación y su propósito.
Los tests comparan la URL y los parámetros exactos, así que un cambio en lo que envía el
adaptador rompe el test. Revisa el diff antes de hacer commit. Los detalles están en
[ADR-0025](../adr/0025-yahoo-chart-adapter-and-cassettes.md).
