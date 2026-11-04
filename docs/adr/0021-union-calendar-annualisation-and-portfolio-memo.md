---
status: aceptado
date: 2026-11-04
decision-makers: Javier Fernández
---

# Anualización con el calendario unión y memoria del historial de la cartera

## Contexto y problema

Dos hallazgos de la auditoría del 3 de noviembre de 2026 afectan a `Portfolio`:

* **B2. Anualización.** La cartera se valora en la unión de los calendarios de sus activos
  ([ADR-0008](0008-alignment-without-artificial-fill.md)), pero se anualizaba con el
  calendario del mercado más denso ([ADR-0013](0013-risk-metrics-and-portfolio-engine.md)).
  Madrid y Nueva York cierran en festivos distintos, así que su unión tiene unas 258 sesiones
  al año, no 252. La volatilidad salía alrededor de un 1 % baja, y la rentabilidad anualizada
  también quedaba sesgada.
* **B3. Recálculo.** El informe, los gráficos, `metrics()`, `returns()` y `value_history()`
  recalculaban cada uno la alineación y el motor de rebalanceo.

## Factores de decisión

* Anualizar con el número real de periodos de las rentabilidades que se anualizan.
* No inventar sesiones: el dominio no conoce los calendarios oficiales, que viven en un
  adaptador ([ADR-0015](0015-data-quality-diagnostics.md)).
* Mantener la inmutabilidad de `Portfolio`.

## Opciones consideradas

* Anualización (B2):
  * densidad observada del calendario unión;
  * densidad calculada con los calendarios oficiales;
  * mantener el calendario del mercado más denso.
* Recálculo (B3):
  * memoria interna por método de alineación y valor inicial;
  * `functools.cached_property`;
  * dejar el recálculo.

## Decisión

Opciones elegidas: **densidad observada del calendario unión** y **memoria interna**.

### Anualización

* Se aplica a carteras diarias con activos de varios mercados (bolsa y zona horaria
  distintas) y con al menos `MIN_UNION_YEARS` (un año) de historia común.
* En ese caso, `periods_per_year` es la densidad observada del calendario unión:
  `(fechas - 1) / años`, con años de `CALENDAR_YEAR_DAYS = 365,25` días.
* Nunca baja del calendario del mercado más denso, así que un hueco de datos no la reduce.
* Con un solo mercado, otra frecuencia o menos de un año, se usa el calendario del mercado,
  como antes.
* El informe de cartera lo explica en su nota de metodología.

### Memoria del historial

* `Portfolio` guarda en un diccionario privado, `_memo`, el panel alineado de cada método y
  el backtest de cada combinación de valor inicial y método.
* `_memo` queda fuera de la representación y de la comparación.
* Los accesores siguen devolviendo copias: nadie puede alterar lo guardado.

### Consecuencias

* Positiva: la volatilidad y la rentabilidad anualizadas de una cartera multimercado reflejan
  sus sesiones reales.
* Positiva: el informe, los gráficos y las métricas comparten un único cálculo del historial.
* Negativa: con datos sintéticos sin festivos, una cartera de dos mercados anualiza con unos
  261 periodos, mientras que cada activo por separado usa 252. Con datos reales, la diferencia
  es la que existe de verdad.
* Negativa: lo memorizado vive tanto como la cartera. Es lo esperable en un objeto inmutable.

### Confirmación

* `tests/unit/domain/test_portfolio_analytics.py`:
  * densidad de la unión con festivos distintos en Madrid y Nueva York;
  * un solo mercado, menos de un año de historia y huecos de datos;
  * memoria compartida y copias protegidas.
* `tests/unit/reporting/test_portfolio_report.py`: nota de metodología.

## Pros y contras de las opciones

### Calendarios oficiales

* Positivo: exacto incluso con huecos de datos.
* Negativo: el dominio dependería de `exchange_calendars`, un adaptador, y se romperían las
  capas. Los huecos ya se diagnostican aparte.

### `functools.cached_property`

* Negativo: no funciona con `slots=True` y no admite argumentos (método de alineación, valor
  inicial).

### Dejar el recálculo

* Negativo: cada informe con gráficos repite el motor de rebalanceo varias veces.

## Más información

* Modifica la regla de anualización de [ADR-0013](0013-risk-metrics-and-portfolio-engine.md).
* Origen: hallazgos B2 y B3 de la auditoría del 3 de noviembre de 2026.
