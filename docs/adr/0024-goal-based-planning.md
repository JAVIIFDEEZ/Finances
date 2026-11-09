---
status: aceptado
date: 2026-11-09
decision-makers: Javier Fernández
---

# Planificación por objetivos: planes de ahorro con Monte Carlo mensual

## Contexto y problema

El Monte Carlo de [ADR-0016](0016-monte-carlo-engine.md) responde a «cuánto puede perder esta
cartera en un año». No responde a la pregunta habitual de un inversor particular: «si aporto
300 € al mes durante 20 años, ¿qué probabilidad tengo de llegar a 150 000 € de hoy?». La
auditoría del 3 de noviembre de 2026 lo incluyó entre las funcionalidades de más valor.

## Factores de decisión

* Horizontes de décadas con la memoria acotada.
* Coherencia con el motor existente: mismos modelos, supuestos y semilla.
* Cifras en dinero de hoy: la inflación cambia la respuesta.
* Responder también a la pregunta inversa: ¿cuánto hay que aportar?

## Opciones consideradas

* Simular la cartera activo a activo, con pasos diarios.
* Simular la cartera como un todo, con pasos mensuales calibrados en sus valores de fin de mes.
* Fórmulas cerradas con una rentabilidad lognormal constante.

## Decisión

Opción elegida: **la cartera como un todo, con pasos mensuales**.

* **Calibración**:
  * se usan los valores de fin de mes de la serie o de la cartera: el último dato real de cada
    mes, sin inventar fechas;
  * el valor de la cartera ya incluye su política de rebalanceo y las correlaciones de sus
    activos, así que no hace falta simular cada activo.
* **Motor**: el de ADR-0016 (GBM, t de Student o *bootstrap*, supuestos de rentabilidad y
  volatilidad, semilla), con 12 periodos al año.
* **Flujos**:
  * aportación al final de cada mes, con revalorización anual opcional;
  * aportaciones negativas para las retiradas;
  * `W_t = max(W_{t-1} · (1 + R_t) + c_t, 0)`: una trayectoria que se queda sin dinero sigue
    en cero.
* **Inflación**: las cifras se expresan en dinero de hoy, deflactadas mes a mes.
* **Aportación necesaria**:
  * con aportaciones no negativas, el patrimonio final es lineal en la aportación en cada
    trayectoria: `W_T = A + C·B`;
  * la aportación que alcanza el objetivo con probabilidad `p` es el cuantil `p` de
    `(objetivo - A) / B`;
  * es exacta respecto a las trayectorias simuladas y no hace falta volver a simular.
* **Resultado**: `PlanResult`, con el patrimonio de cada trayectoria, percentiles,
  probabilidad de éxito, déficit medio, probabilidad de ruina, aportación necesaria,
  `summary()` y un gráfico bilingüe.

### Consecuencias

* Positiva: un plan a 40 años con 10 000 trayectorias son 4,8 millones de puntos. Cabe con
  holgura en los límites de [ADR-0019](0019-bounded-memory-and-incremental-cache.md).
* Positiva: la aportación necesaria es exacta respecto a las trayectorias simuladas.
* Negativa: cada aportación se invierte con los pesos que ya tiene la cartera. Con
  rebalanceo mensual, el valor por defecto, es exacto; en comprar y mantener es una
  aproximación.
* Negativa: con pocos años de historia, la media mensual histórica es muy ruidosa. La guía
  recomienda supuestos explícitos de rentabilidad y volatilidad en horizontes largos.
* Pendiente: impuestos y comisiones, aportaciones irregulares (un calendario de flujos) y
  objetivos intermedios.

### Confirmación

`tests/unit/domain/test_planning.py`:

* fórmula de la anualidad con una rentabilidad cierta;
* identidad lineal `W_T = A + C·B`;
* la aportación necesaria alcanza la probabilidad pedida al volver a simular;
* ruina con retiradas y cifras en dinero de hoy;
* carteras y gráfico en los dos idiomas.

## Pros y contras de las opciones

### Activo a activo, con pasos diarios

* Positivo: cada aportación se invierte exactamente a los pesos objetivo.
* Negativo: 10 000 trayectorias de 20 años con 252 sesiones al año superan con mucho el límite
  de puntos. Habría que pasar a pasos mensuales de todos modos.

### Fórmulas cerradas

* Positivo: son instantáneas.
* Negativo: suponen rentabilidades normales y constantes. No dan colas, ruina ni *bootstrap*.

## Más información

* Amplía [ADR-0016](0016-monte-carlo-engine.md) (motor) y usa los límites de ADR-0019.
* Origen: Monte Carlo por objetivos, propuesto en la auditoría del 3 de noviembre de 2026.
