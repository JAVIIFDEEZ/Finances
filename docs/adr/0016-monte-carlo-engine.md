---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Motor Monte Carlo vectorizado con rebalanceo dentro de cada trayectoria

## Contexto y problema

El taller B1-T1 (§4.4) exige una simulación de Monte Carlo como **método directo** de la
cartera (`portfolio.monte_carlo(...)`), parametrizable y con visualización. Para ser útil en la
plataforma además debe cumplir:

* **reproducibilidad**: la misma semilla da el mismo resultado;
* **coherencia con el histórico**: la política de rebalanceo de la cartera debe aplicarse
  también en el futuro simulado;
* **memoria acotada**, aunque se pidan cientos de miles de trayectorias;
* **honestidad estadística**: un VaR de Monte Carlo es una estimación y debe llevar su error.

## Factores de decisión

* Vectorizar con NumPy: nada de bucles por trayectoria.
* Las correlaciones entre activos importan más que las distribuciones marginales para el
  riesgo de una cartera.
* Los retornos financieros tienen colas gruesas y agrupamiento de volatilidad.
* El dominio no puede depender de librerías de gráficos (ADR-0002).

## Opciones consideradas

* **Simular el retorno de la cartera como una sola serie** (un GBM univariante). Es sencillo,
  pero ignora la deriva de los pesos y hace imposible aplicar el rebalanceo.
* **Simular los activos conjuntamente y valorar la cartera en cada paso.** Esta es la opción
  elegida.
* **Solo GBM**, frente a **varios modelos de *shocks***. Se eligen varios modelos, porque el
  GBM subestima las colas.

## Decisión

### Calibración (`domain.simulation.calibrate`)

Todo se calibra con **log-retornos por periodo** de la frecuencia de las series. Las opciones
son estas:

| Parámetro | Opciones |
|-----------|----------|
| Deriva (`DriftAssumption`) | `historical` (media muestral), `zero` (martingala), `risk_free` (todos crecen al tipo libre de riesgo) o `assumed` (rentabilidades anuales por activo) |
| Volatilidad (`VolatilityAssumption`) | `historical`, o `assumed`: se reescala la covarianza a las volatilidades anuales dadas **conservando las correlaciones históricas** |
| Covarianza (`CovarianceEstimator`) | `sample`: por pares y reparada a PSD (ADR-0013); o `ledoit_wolf`: contracción hacia `m·I` sobre los periodos con todos los activos observados |
| Ventana | `lookback`: últimos *n* periodos |

Detalles de la calibración:

* Con deriva supuesta, la media del log-retorno es `ln(1 + r_periodo) − σ²/2`. Esa corrección
  de convexidad hace que, bajo el GBM, la **rentabilidad simple esperada** coincida
  exactamente con la supuesta.
* Ledoit-Wolf es la versión de 2004 con objetivo identidad escalada. Coincide con la
  implementación de scikit-learn a precisión de máquina; el test usa sus valores como
  referencia.
* `Calibration` expone los parámetros realmente usados (volatilidad y rentabilidad anuales,
  correlación e intensidad de contracción), para que el informe sea transparente.

### Modelos de *shocks* (`analytics.montecarlo`)

* **GBM multivariante**: los *shocks* son `Z @ Lᵀ`, con `L` el factor de Cholesky.
  * Si la matriz es solo semidefinida (por ejemplo, con activos perfectamente correlacionados),
    se usa una raíz por autovalores.
  * Admite **variables antitéticas** (`Z` y `−Z`), que reducen la varianza del estimador.
* **Student-t multivariante**:
  * la covarianza es la misma que en el GBM, pero las colas conjuntas son más gruesas;
  * la variable de mezcla χ² es **común a todos los activos**, así que los extremos llegan a
    la vez, como en un *crash*;
  * los *shocks* se escalan por `√((ν−2)/W)` para conservar la covarianza.
* ***Bootstrap* estacionario** (Politis y Romano, 1994):
  * remuestrea **filas completas** de periodos históricos, lo que conserva las correlaciones
    y cualquier forma de la distribución;
  * los bloques tienen longitud geométrica (media configurable), lo que conserva el
    agrupamiento de volatilidad a corto plazo;
  * las filas se recentran y reescalan a la deriva y volatilidad calibradas, así que las
    hipótesis de deriva y volatilidad también se aplican aquí.

### Valoración de la cartera dentro de cada trayectoria

* La política de la cartera se traduce a pasos de simulación:
  * `periodic` → cada `round(periodos_año / periodos_año_de_la_frecuencia)` pasos (mensual
    sobre diario → 21);
  * `threshold` → la misma banda;
  * `buy_and_hold` → sin rebalanceo.
* `rebalanced_values` hace el bucle **sobre el tiempo**, vectorizado sobre trayectorias y
  activos.
* En *buy and hold* no hay bucle: el valor es el crecimiento acumulado de cada activo
  ponderado por los pesos iniciales.
* La **ruina es un estado absorbente**: con posiciones cortas, una trayectoria que llega a 0
  se queda en 0.

### Reproducibilidad y memoria

* Se usa `numpy.random.default_rng(seed)`.
* Las trayectorias se generan en **lotes** de `chunk_size`.
* El límite es `n_paths × horizon ≤ 20 000 000`, unos 160 MB de valores en `float64`.
* En el GBM sin antitéticas, el tamaño de lote no cambia el resultado (hay un test).

### Resultados con incertidumbre (`SimulationResult`)

* El VaR y el CVaR se dan como **pérdidas positivas sobre el horizonte completo**, en fracción
  del valor inicial. Ojo: en ADR-0013 son **por periodo**.
* **VaR** con intervalo de confianza del 95 % **sin hipótesis de distribución**, calculado con
  estadísticos de orden (aproximación binomial).
* **CVaR** con intervalo normal (error estándar de la media de la cola).
* Valor esperado con su error estándar de Monte Carlo.
* Además:
  * drawdown máximo de cada trayectoria y *drawdown at risk*;
  * probabilidad de pérdida;
  * percentiles en cada paso (abanico);
  * `summary()`, que resume todo en una tabla.

### Visualización: excepción documentada a las capas

* `SimulationResult.plot()` cumple el requisito de método directo.
* Para no romper la pureza del dominio:
  * importa `investinglab.reporting.simulation` **de forma diferida**, dentro del método;
  * import-linter lo permite con una excepción explícita (`ignore_imports`), limitada a esa
    arista y a la anotación del tipo `Figure`.
* matplotlib es un *extra* opcional (`investinglab[plots]`): el núcleo se instala sin
  dependencias gráficas.
* Diseño de la figura:
  * paleta validada (azul secuencial para las bandas, tintas neutras para el texto) y un único
    eje por gráfico;
  * etiquetas directas de VaR, CVaR y mediana, colocadas para que no se solapen.

## Consecuencias

* Positiva: `portfolio.monte_carlo(SimulationConfig(...))` y `result.plot()` cubren el
  §4.4 del taller.
* Positiva: el riesgo simulado respeta las correlaciones, la deriva de pesos y la política de
  rebalanceo real de la cartera.
* Positiva: cada VaR va con su intervalo, así que es fácil ver si faltan trayectorias.
* Negativa: la corrección `−σ²/2` es exacta solo para *shocks* gaussianos.
  * Con Student-t, `E[eˣ]` no es finita en teoría.
  * Con el *bootstrap*, la rentabilidad simple esperada es aproximada.
  * Con volatilidades diarias el efecto es despreciable, pero no es exacto.
* Negativa: no se modela la **incertidumbre de los parámetros**. La deriva histórica es muy
  ruidosa, por eso `historical` lo advierte y existen `zero`, `risk_free` y `assumed`.
* Negativa: carteras con **calendarios mixtos** (cripto 24/7 y bolsa):
  * se calibran sobre los periodos comunes;
  * el horizonte se mide en periodos de la frecuencia de la cartera;
  * es preferible remuestrear a semanal antes de simular.
* Pendiente:
  * volatilidad condicional (GARCH / *filtered historical simulation*);
  * saltos;
  * aportaciones y retiradas periódicas;
  * simulación del tipo de cambio en carteras multidivisa.

## Confirmación

Tests:

* `test_montecarlo.py` (núcleo):
  * momentos de los *shocks* y simetría antitética;
  * colas de la Student-t;
  * longitud media de bloque del *bootstrap*;
  * rebalanceo exacto en casos pequeños;
  * ruina absorbente.
* `test_covariance.py`: Ledoit-Wolf frente a la referencia de scikit-learn.
* `test_simulation.py` (dominio):
  * la media, la desviación, el VaR (su intervalo cubre el cuantil teórico) y el CVaR
    coinciden con las fórmulas cerradas del GBM lognormal;
  * reproducibilidad;
  * traducción de las políticas de rebalanceo a pasos.
* `test_montecarlo_properties.py`:
  * valores positivos en carteras largas;
  * *buy and hold* y *constant mix* frente a sus fórmulas;
  * invarianza del VaR al importe invertido.
* `test_simulation_figure.py`: la figura se genera con el backend Agg.

## Más información

* Glasserman, P. (2003). *Monte Carlo Methods in Financial Engineering*. Springer.
* Politis, D. N. y Romano, J. P. (1994). The Stationary Bootstrap. *Journal of the American
  Statistical Association*, 89(428).
* Ledoit, O. y Wolf, M. (2004). A well-conditioned estimator for large-dimensional covariance
  matrices. *Journal of Multivariate Analysis*, 88(2).
