# Planes de ahorro

`savings_plan()` simula un plan de ahorro sobre un activo o una cartera. Combina un capital
inicial, una aportación mensual y un objetivo en dinero de hoy, y responde a dos preguntas:
qué probabilidad hay de llegar y cuánto habría que aportar para llegar con la seguridad que
quieras ([ADR-0024](../adr/0024-goal-based-planning.md)).

```python
from investinglab.domain import SavingsPlan, SimulationConfig

plan = SavingsPlan(
    years=20,
    initial=10_000,
    contribution=300,  # al final de cada mes
    contribution_growth=0.02,  # la aportación sube un 2 % al año
    goal=150_000,  # en dinero de hoy
    inflation=0.02,
)
resultado = cartera.savings_plan(plan, SimulationConfig(n_paths=10_000))

resultado.probability_of_success  # probabilidad de alcanzar el objetivo
resultado.required_contribution(0.9)  # aportación para alcanzarlo en el 90 % de los casos
resultado.summary()  # cifras clave, en dinero de hoy
resultado.plot()  # abanico del patrimonio, dinero aportado y objetivo
```

`PriceSeries.savings_plan()` funciona igual con un solo activo, por ejemplo un fondo indexado.
La demo completa está en `notebooks/savings_plan_demo.ipynb`.

## Cómo se simula

* La cartera se simula entera, mes a mes, a partir de sus valores de fin de mes. Su política
  de rebalanceo y las correlaciones de sus activos ya están dentro de esas rentabilidades.
* Cada trayectoria suma la aportación al final de cada mes:
  `W_t = W_{t-1} · (1 + R_t) + c_t`.
* `SimulationConfig` elige el modelo (GBM, t de Student o *bootstrap*), el número de
  trayectorias, la semilla y los supuestos. El horizonte lo fija el plan.

## Dinero de hoy

Todas las cifras de `PlanResult` se expresan en dinero de hoy, deflactadas con `inflation`. Un
objetivo de 150 000 € a 20 años con una inflación del 2 % equivale a unos 223 000 € nominales.
`wealth(real=False)` y `terminal_wealth(real=False)` devuelven las cifras nominales.

## ¿Cuánto hay que aportar?

`required_contribution(p)` da la primera aportación mensual que alcanza el objetivo en una
proporción `p` de las trayectorias, con la misma revalorización anual que el plan. Es exacta:
con aportaciones no negativas, el patrimonio final de cada trayectoria crece en línea recta con
la aportación, así que no hace falta volver a simular.

## Retiradas

Una aportación negativa es una retirada mensual: sirve para estudiar cuánto dura un capital.

```python
jubilacion = SavingsPlan(years=30, initial=400_000, contribution=-1_800, inflation=0.02)
resultado = cartera.savings_plan(jubilacion)

resultado.probability_of_ruin  # trayectorias que se quedan sin dinero antes de 30 años
```

Una trayectoria que se queda sin dinero sigue en cero hasta el final.

## Supuestos explícitos

Con pocos años de historia, la rentabilidad media mensual es muy ruidosa y domina el
resultado a 20 o 30 años. Para planificar conviene fijarla:

```python
from investinglab.domain import DriftAssumption, VolatilityAssumption

prudente = SimulationConfig(
    n_paths=10_000,
    drift=DriftAssumption.ASSUMED,
    expected_returns=0.05,  # rentabilidad anual esperada
    volatility=VolatilityAssumption.ASSUMED,
    volatilities=0.15,  # volatilidad anual
)
cartera.savings_plan(plan, prudente).probability_of_success
```

## Limitaciones

* No hay impuestos ni comisiones.
* Las aportaciones se invierten con los pesos que ya tiene la cartera. Con el rebalanceo
  mensual por defecto es exacto; en comprar y mantener es una aproximación.
* Las aportaciones son regulares; no hay calendario de flujos ni objetivos intermedios.
