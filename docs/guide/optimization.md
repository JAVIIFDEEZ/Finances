# Optimización de carteras

`Portfolio.optimize()` busca los pesos que mejor cumplen un objetivo a partir del histórico de
los activos. Devuelve la cartera optimizada, sus cifras ex ante y las estimaciones que hay
detrás ([ADR-0023](../adr/0023-portfolio-optimization.md)).

```python
resultado = cartera.optimize(objective="max_sharpe", max_weight=0.4, risk_free_rate=0.03)

resultado.weights  # pesos optimizados
resultado.summary()  # pesos antes y después, rentabilidad, volatilidad y riesgo
resultado.sharpe_ratio  # Sharpe ex ante
resultado.portfolio.report()  # la cartera optimizada, con su informe completo
```

`resultado.portfolio` es una `Portfolio` normal: mismos activos, divisa y política de
rebalanceo. Puedes hacerle un informe, un backtest o un Monte Carlo como a cualquier otra.

La demo completa está en `notebooks/portfolio_optimization_demo.ipynb`.

## Objetivos

| `objective` | Qué busca | Usa rentabilidades esperadas |
|-------------|-----------|:---:|
| `min_variance` (por defecto) | La menor volatilidad | No |
| `max_sharpe` | La mayor rentabilidad por unidad de riesgo (cartera tangente) | Sí |
| `target_return` | La menor volatilidad que espera `target_return` | Sí |
| `risk_parity` | Que cada activo aporte el mismo riesgo, o el de `risk_budgets` | No |
| `hrp` | Repartir el riesgo entre grupos de activos correlacionados (López de Prado) | No |
| `inverse_volatility` | Pesos proporcionales a `1 / volatilidad` | No |
| `equal_weight` | El mismo peso para todos: una referencia difícil de batir | No |

Los tres primeros admiten límites por activo:

```python
cartera.optimize(min_weight=0.05, max_weight=0.35)
cartera.optimize(objective="max_sharpe", max_weight={"SAN.MC": 0.2})  # solo un activo
cartera.optimize(objective="max_sharpe", min_weight=-0.3)  # con cortos
```

```python
cartera.optimize(
    objective="risk_parity",
    risk_budgets={"SAN.MC": 0.4, "ITX.MC": 0.3, "IBE.MC": 0.3},
)
```

## Rentabilidades esperadas

Las medias históricas son el punto débil de la optimización: cambian mucho con unos pocos años
más o menos de datos, y el optimizador las amplifica. Hay tres alternativas:

* `expected_returns="historical"` (por defecto): media de las rentabilidades, anualizada.
* `expected_returns="equilibrium"`: las rentabilidades que harían óptimos los pesos actuales
  (`r + δ·Σ·w`). Es un punto de partida neutral.
* Un diccionario con tus propias estimaciones anuales: `{"SAN.MC": 0.07, ...}`.

### Vistas (Black-Litterman)

Las vistas combinan esas rentabilidades con tus opiniones, cada una con su grado de confianza:

```python
from investinglab.domain import View

cartera.optimize(
    objective="max_sharpe",
    expected_returns="equilibrium",
    views=[
        View.absolute("IBE.MC", 0.08),  # IBE rentará un 8 %
        View.relative("ITX.MC", "SAN.MC", 0.02, uncertainty=0.0004),
    ],
)
```

Sin `uncertainty`, la confianza en cada vista es proporcional a la del punto de partida (He y
Litterman). Cuanto menor es la incertidumbre (una varianza), más pesa la vista.

## Covarianza y datos

* `covariance="ledoit_wolf"` (por defecto) encoge la covarianza muestral hacia una estructura
  sencilla. Es más estable fuera de muestra. `covariance="sample"` usa la muestral por pares.
* `frequency="1w"` estima con rentabilidades semanales. Conviene con mercados que cierran a
  horas distintas (Europa y Estados Unidos).
* `lookback=756` usa solo los últimos 756 periodos (unos tres años diarios).

Las estimaciones empiezan cuando cotizan todos los activos y nunca se rellenan huecos.
`resultado.estimates` muestra exactamente qué se usó.

## Frontera eficiente

```python
frontera = cartera.efficient_frontier(points=40, risk_free_rate=0.03, max_weight=0.5)

frontera.points  # rentabilidad, volatilidad, Sharpe y pesos de cada punto
frontera.minimum_variance  # cartera de mínima varianza
frontera.maximum_sharpe  # cartera tangente (None si nada bate al tipo libre de riesgo)
frontera.plot()  # gráfico en español; plot(language="en") en inglés
```

El gráfico muestra la frontera, cada activo, las dos carteras óptimas y la línea del mercado
de capitales. Necesita el *extra* `plots`.

## Antes de fiarte del resultado

* **Todo es en muestra.** Unos pesos optimizados sobre un histórico parecen mejores en ese
  mismo histórico de lo que serán después.
* **Las cifras son ex ante.** La rentabilidad y la volatilidad esperadas dependen de las
  estimaciones; `resultado.portfolio.metrics()` da las realizadas.
* **Sin costes.** Pasar de los pesos actuales a los optimizados tiene costes de transacción y,
  si vendes con plusvalías, impuestos.
* Para no depender de las medias, empieza por `min_variance`, `risk_parity` o `hrp`, o usa
  rentabilidades de equilibrio con vistas.
