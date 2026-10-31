---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Métricas de riesgo, correlaciones y motor de valoración de carteras

## Contexto y problema

El informe de cartera (B1-T1 §4.5) y la plataforma necesitan:

* rentabilidad, volatilidad, Sharpe, Sortino, drawdown y VaR/CVaR;
* correlaciones y contribución al riesgo;
* evolución histórica de la cartera con su política de rebalanceo.

Hay que fijar convenciones inequívocas y que los cálculos sigan siendo correctos con
calendarios distintos y colas gruesas.

## Decisión

**Convenciones** (`investinglab.analytics.risk`, `RiskMetrics`):

* Retornos simples por periodo.
* Ratios anualizados con el factor del mercado y la frecuencia (ADR-0007).
* **Tipo libre de riesgo**:
  * se recibe **anual** en decimal, como constante o como serie *point-in-time*;
  * se convierte a tasa por periodo compuesta: `(1 + r)^(1/n) − 1`.
* **VaR y CVaR**:
  * se expresan como **pérdidas positivas por periodo** (`0.023` = −2,3 %);
  * hay tres métodos: histórico, normal y **Cornish-Fisher** (corrige por asimetría y curtosis);
  * en Cornish-Fisher los cuantiles se **reordenan para que sean monótonos** (Chernozhukov et
    al., 2010). Fuera de su dominio de validez la expansión deja de ser monótona y daría un
    CVaR menor que el VaR. Ese fallo lo encontró un test de propiedades.
* **Sortino**: la desviación a la baja usa todos los periodos en el denominador.

**Covarianza y correlación** (`analytics.covariance`):

* Se calculan con observaciones **por pares** (*pairwise-complete*): ningún festivo se rellena
  (ADR-0008).
* Si la matriz resultante no es semidefinida positiva, se repara a la **matriz PSD más
  cercana**:
  * se recortan los autovalores negativos;
  * se conserva la diagonal, para que cada activo mantenga su volatilidad.
* La correlación se deriva de esa covarianza, así que ambas son coherentes.
* `Portfolio.correlation("1w")` usa retornos semanales para atenuar el sesgo de **cierres no
  sincrónicos** entre Europa y EE. UU.

**Motor de cartera** (`analytics.portfolio.rebalanced_path`, `Portfolio.backtest()`):

* Cada periodo los pesos derivan con los retornos.
* Vuelven a los objetivos en estos casos:
  * en la última sesión de cada periodo de calendario (`periodic`);
  * cuando algún peso se desvía más que la banda (`threshold`);
  * nunca, en `buy_and_hold`.
* Un retorno no observado significa que la posición se valora al último precio observado
  (como el valor liquidativo de un fondo). El movimiento se contabiliza al reabrir el mercado.
  `PortfolioBacktest.staleness` expone la antigüedad de cada valoración.
* La historia empieza cuando todos los activos se han observado al menos una vez.
* Se registra la rotación (*turnover*). Si la cartera pierde todo (posible con cortos o
  apalancamiento), la trayectoria termina.
* **Anualización de una cartera multimercado**: se usa el factor del activo con el calendario
  más denso, porque el calendario unión es al menos igual de denso.

**Contribución al riesgo**: descomposición de Euler de la volatilidad. Las contribuciones
suman la volatilidad y las cuotas suman 1.

### Consecuencias

* Positiva: las mismas funciones sirven para activos, carteras, simulaciones e informes.
* Positiva: las propiedades financieras (CVaR ≥ VaR, matrices PSD, cuotas que suman 1,
  *buy-and-hold* igual al crecimiento ponderado) se verifican con hypothesis.
* Negativa: la valoración diaria de carteras multimercado incluye días con una posición a
  precio antiguo. Es visible en `staleness`, y el informe lo advertirá.
* Pendiente: costes de transacción en el rebalanceo, *tracking error* y ratio de información
  frente a un *benchmark*.

### Confirmación

* `tests/unit/analytics/test_risk.py`, `test_covariance.py` y `test_portfolio_engine.py`.
* `tests/unit/domain/test_portfolio_analytics.py` y `test_metrics.py`.
* `tests/property/test_risk_properties.py`.
