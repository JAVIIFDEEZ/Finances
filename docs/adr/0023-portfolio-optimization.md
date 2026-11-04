---
status: aceptado
date: 2026-11-04
decision-makers: Javier Fernández
---

# Optimización de carteras: objetivos, estimadores y resolución

## Contexto y problema

La plataforma analizaba carteras con pesos dados, pero no ayudaba a elegirlos. La auditoría
del 3 de noviembre de 2026 situó la optimización como la funcionalidad de más valor.

Hacen falta los métodos de la gestión profesional sin caer en sus trampas conocidas:

* las medias históricas son muy ruidosas;
* las covarianzas muestrales son inestables;
* las soluciones de media-varianza tienden a ser extremas.

## Factores de decisión

* Rigor: resultados verificables frente a soluciones cerradas.
* Robustez fuera de muestra.
* Sin dependencias pesadas nuevas (cvxpy, *solvers* comerciales).
* Coherencia con el dominio: el resultado es otra `Portfolio`, con su informe y su Monte
  Carlo.

## Opciones consideradas

* Resolución:
  * núcleos propios sobre SciPy;
  * cvxpy con OSQP o Clarabel;
  * PyPortfolioOpt o Riskfolio-Lib.
* Covarianza por defecto:
  * Ledoit-Wolf;
  * muestral.

## Decisión

Opción elegida: **núcleos propios sobre SciPy** en `analytics.optimization`, envueltos por
`Portfolio.optimize()` y `Portfolio.efficient_frontier()`, con **Ledoit-Wolf** por defecto.

### Objetivos

| Objetivo | Método |
|----------|--------|
| `min_variance` | Programa cuadrático convexo, resuelto con SLSQP |
| `max_sharpe` | Programa homogeneizado de Cornuejols y Tütüncü, también convexo: `min y'Σy` con `(μ - r)'y = 1` |
| `target_return` | Programa cuadrático con la rentabilidad como restricción |
| `risk_parity` | Spinu (2013), por el método de Newton, con presupuestos de riesgo opcionales |
| `hrp` | López de Prado (2016): distancia entre correlaciones, enlace simple y bisección recursiva |
| `inverse_volatility`, `equal_weight` | Referencias robustas |

* Los objetivos de media-varianza admiten límites por activo: mínimo y máximo, negativos para
  posiciones cortas. En los objetivos de riesgo no aplican y se rechazan.
* La covarianza y las rentabilidades se escalan internamente, para que el *solver* trabaje con
  magnitudes del orden de 1.
* Cada solución se comprueba: o cumple las restricciones, o se lanza un `DomainError` que
  explica el motivo.

### Estimadores

* **Datos**:
  * rentabilidades simples desde que cotizan todos los activos, sin rellenar huecos;
  * con la frecuencia y la ventana elegidas;
  * anualizadas con el calendario de los mercados.
* **Rentabilidades esperadas**:
  * históricas, de equilibrio (`r + δΣw` con los pesos actuales) o supuestas;
  * opcionalmente, combinadas con vistas de Black-Litterman, con la incertidumbre de He y
    Litterman o una explícita.
* **Covarianza**: Ledoit-Wolf por defecto; la muestral por pares queda como alternativa.

### Resultado

* `OptimizationResult`:
  * la cartera optimizada, con los mismos activos, divisa y política de rebalanceo;
  * cifras ex ante, contribuciones al riesgo y número efectivo de activos;
  * las estimaciones utilizadas.
* `EfficientFrontier`:
  * tabla de puntos y carteras de mínima varianza y de máximo Sharpe;
  * gráfico bilingüe con la línea del mercado de capitales.

### Consecuencias

* Positiva: la cartera optimizada se analiza, se simula y se documenta con las herramientas
  existentes.
* Positiva: los resultados se contrastan con fórmulas cerradas y propiedades aleatorias.
* Negativa: todo se estima en muestra. Unos pesos optimizados sobre un histórico parecen
  mejores en ese histórico de lo que serán después; la guía lo advierte.
* Negativa: SLSQP escala bien hasta un par de centenares de activos. Para universos mayores
  habría que pasar a un *solver* cuadrático dedicado (OSQP).
* Pendiente:
  * costes de transacción y rotación máxima;
  * restricciones por grupos, como sectores o divisas;
  * validación fuera de muestra (*walk-forward*) de las estrategias de optimización.

### Confirmación

* `tests/unit/analytics/test_optimization.py`:
  * soluciones cerradas sin restricciones (mínima varianza y cartera tangente);
  * comparación con miles de carteras aleatorias;
  * HRP sobre activos incorrelados igual a varianza inversa;
  * identidades de Black-Litterman.
* `tests/property/test_optimization_properties.py`: propiedades con hypothesis sobre
  covarianzas aleatorias.
* `tests/unit/domain/test_optimization.py`: estimaciones, objetivos, límites, vistas, frontera
  y gráfico.

## Pros y contras de las opciones

### cvxpy

* Positivo: modelado declarativo y *solvers* robustos.
* Negativo: dependencia pesada, con varios *solvers* binarios, para problemas pequeños que
  SciPy resuelve con precisión.

### PyPortfolioOpt o Riskfolio-Lib

* Positivo: muchos métodos listos.
* Negativo: APIs ajenas al dominio, sin procedencia ni la política de huecos de InvestingLab.
* Negativo: mantenimiento irregular y menos control para verificar los resultados.

### Covarianza muestral por defecto

* Negativo: con pocos datos por activo produce pesos extremos e inestables.

## Más información

* Markowitz (1952); Black y Litterman (1992); He y Litterman (1999); Ledoit y Wolf (2004);
  Cornuejols y Tütüncü (2007); Spinu (2013); López de Prado (2016).
* Origen: prioridad 1 de la auditoría del 3 de noviembre de 2026.
