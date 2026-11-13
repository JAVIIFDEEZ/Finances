---
status: aceptado
date: 2026-11-13
decision-makers: Javier Fernández
---

# Flujo por vela, tipos de mantenimiento y universos *point-in-time* como tipos hermanos

## Contexto y problema

La fase G1 del [plan de integración](../plan/integracion-cryptoworld.md) trae tres clases de
dato que CryptoWorld usa y Finances no puede representar:

* el **flujo por vela** (volumen en divisa, número de operaciones y lado agresor), del que salen
  el *delta* y el CVD;
* el **funding** de los perpetuos, que se cobra o se paga cada pocas horas;
* el **universo** de activos de cada fecha, sin el que cualquier estudio sufre sesgo de
  supervivencia.

En CryptoWorld solo existen para cripto. La decisión D8 exige diseñarlas para cualquier clase
de activo. Además, `PriceSeries` solo admite columnas de precio con validación estricta
([ADR-0006](0006-strict-input-validation.md)): el flujo no es un precio y el funding es negativo
a menudo.

## Factores de decisión

* No relajar la validación de `PriceSeries`: precios finitos y positivos.
* Lo mismo para una acción, un ETF, un futuro o una cripto.
* Cada dato con su procedencia y sus reglas: un hueco es un hueco, nunca un cero.
* Que el *backtest* (G3) y la mesa de *carry* (G5) usen un solo concepto de coste de mantener una
  posición, venga de donde venga.

## Opciones consideradas

* Columnas opcionales en `PriceSeries` (`buy_volume`, `funding`…).
* Tipos hermanos, alineados por índice con la serie de precios.
* Funding como `EconomicSeries` (serie macro).

## Decisión

**Tipos hermanos en `domain/`, inmutables y validados, y un puerto por clase de dato.**

* **`FlowSeries`** (`domain/flow.py`): `volume` obligatorio y, si la fuente los da,
  `quote_volume`, `trades`, `buy_volume` y `buy_quote_volume`.
  * Mismas reglas de índice que `PriceSeries` (función común `validate_time_index`).
  * Valores finitos y no negativos; la compra agresora nunca supera el volumen; las
    operaciones son enteras. Una vela sin flujo es una fila ausente, no un cero.
  * Calcula `delta = 2·buy_volume − volume`, `cvd`, `buy_ratio`, `vwap` y tamaño medio de
    operación. Sin lado agresor no hay *delta*: lo dice con un error claro en lugar de
    inventarlo.
  * `aligned_with(prices)` lo une a las velas de su `PriceSeries`.
* **`RateSeries`** (`domain/rate_series.py`) para lo que cuesta o rinde **mantener** una
  posición, con tres clases (`RateKind`):
  * `FUNDING` de perpetuos: positivo, pagan los largos y cobran los cortos.
  * `BORROW`, el préstamo de títulos para vender en corto: paga el corto a un tercero.
  * `FINANCING`, la financiación de un largo apalancado: paga el largo a un tercero.

  Cada serie lleva instrumento, *venue* y periodo de devengo, con instantes en UTC. Rechaza
  tipos no finitos y los de un 100 % o más por periodo (casi siempre un porcentaje pasado
  como decimal). `cashflow(side)` da lo que cobra o paga cada lado: solo el *funding* pasa
  de un lado al otro.
* **`Universe`** (`domain/universe.py`): estancias de cada instrumento (alta y baja, con
  reentradas) y una fecha `as_of` más allá de la cual no se sabe nada. Da los miembros de cada
  fecha, una máscara para filtrar señales y la supervivencia entre dos fechas. `Universe.fixed`
  construye la lista de hoy proyectada hacia atrás, marcada como **no** *point-in-time*.
* **Puertos**: `Dataset.FLOW` con `TradeFlowProvider.fetch_flow(BarsRequest)` y
  `Dataset.HOLDING_RATES` con `HoldingRatesProvider.fetch_rates(RatesRequest)`. Cualquier
  proveedor de cualquier clase de activo puede implementarlos; el enrutado por capacidades
  sigue igual.

### Consecuencias

* Positiva: `PriceSeries` no cambia, y su validación tampoco.
* Positiva: el mismo código sirve para el flujo de un futuro o de una acción con
  clasificación de operaciones, y para el coste de un corto en el IBEX o del *funding* de BTC.
* Negativa: un estudio que use precio y flujo debe alinearlos (`aligned_with`); no vienen
  juntos.
* Negativa: el CVD depende del inicio de la serie; solo sus cambios son comparables entre
  ventanas, y la documentación lo dice.

### Confirmación

* `tests/unit/domain/test_flow.py`, `test_rate_series.py` y `test_universe.py`.
* `tests/property/test_flow_properties.py`: el CVD cambia en el *delta* de cada vela, el
  *delta* nunca supera el volumen, truncar la serie no cambia el pasado y el *funding* suma
  cero entre largos y cortos.

## Pros y contras de las opciones

### Columnas opcionales en `PriceSeries`

* Positivo: un solo objeto.
* Negativo: abre la validación estricta a valores negativos y columnas que no son precios, y
  cada cálculo de precio tendría que ignorarlas.

### Funding como `EconomicSeries`

* Positivo: el tipo ya existe.
* Negativo: una serie macro no pertenece a un instrumento ni a un *venue*, y su modelo
  bitemporal (fecha de publicación) no aplica a un pago que se liquida en un instante.

## Más información

* [Integración de CryptoWorld](../plan/integracion-cryptoworld.md), §4.1, §4.6 y G1.
