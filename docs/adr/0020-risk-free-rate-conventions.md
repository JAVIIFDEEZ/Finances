---
status: aceptado
date: 2026-11-04
decision-makers: Javier Fernández
---

# Tipo libre de riesgo en TAE según la convención de cada serie

## Contexto y problema

Las métricas (`RiskMetrics`) tratan el tipo libre de riesgo anual como un tipo **compuesto**,
una TAE: lo pasan a tipo por periodo con `(1 + r) ^ (1 / periodos) - 1`. Pero las series que
lo alimentan ([ADR-0014](0014-currency-conversion-and-risk-free-rate.md)) son cotizaciones del
mercado monetario:

* el €STR y el tipo de la facilidad de depósito del BCE son tipos a un día, simples, en base
  ACT/360;
* `DGS3MO` es el rendimiento de la letra del Tesoro a 3 meses en base inversión
  (*bond-equivalent*): simple, ACT/365, sobre unos 91 días.

Usar la cotización tal cual infravaloraba el tipo. Con un €STR del 3,5 %, la TAE es del
3,61 %: unos 11 puntos básicos al año.

Además, cuando la serie de tipos empezaba después que las rentabilidades, el Sharpe y el
Sortino descartaban esos periodos sin avisar.

## Factores de decisión

* Exactitud financiera: cada tipo con su convención.
* Mantener el contrato de `RiskMetrics`: sigue recibiendo un tipo anual compuesto, constante o
  en serie.
* Nunca inventar datos: un periodo sin tipo publicado no se rellena.
* Transparencia: el informe dice con qué muestra se calculan los ratios.

## Opciones consideradas

* Convertir cada serie a TAE en el servicio, con su convención.
* Devengar cada periodo por días naturales (`r × días / 360`) y pasar a las métricas
  rentabilidades sin riesgo por periodo.
* Mantener el tipo cotizado y documentar el sesgo.

## Decisión

Opción elegida: **convertir a TAE en el servicio**. Corrige el sesgo donde se conoce la
convención y deja intacto el contrato de las métricas.

* `RateConvention(day_count, term_days)`, en el dominio, calcula
  `TAE = (1 + r × plazo / base) ^ (365 / plazo) - 1`:
  * `OVERNIGHT_ACT_360`, con plazo de un día, para el €STR, el tipo de depósito del BCE y el
    SOFR;
  * ACT/365 y 91 días para las letras a 3 meses.
* `RiskFreeSource(series_id, convention)`: cada serie configurada declara su convención, y
  `RiskFreeRateService.annual_rates()` devuelve TAE.
* Un tipo constante que pase el usuario (`risk_free_rate=0.03`) se interpreta como TAE, igual
  que antes.
* `RiskMetrics.risk_free_periods` cuenta las rentabilidades con tipo conocido:
  * es la muestra del Sharpe y del Sortino;
  * es la que usa el error estándar del Sharpe;
  * si es menor que `periods`, el informe muestra una advertencia.
* El informe etiqueta la media como «Tipo libre de riesgo medio (TAE)».

### Consecuencias

* Positiva: los ratios descuentan lo que de verdad habría rendido el efectivo.
* Positiva: los periodos sin tipo quedan a la vista en vez de reducir la muestra en silencio.
* Negativa: la media del informe ya no coincide con la cotización publicada (3,61 % frente a
  3,50 %). La etiqueta TAE lo aclara.
* Negativa: la capitalización diaria supone reinvertir cada día natural. Frente al devengo
  real por días hábiles, la diferencia ronda una centésima de punto básico.

### Confirmación

* `tests/unit/domain/test_rates.py`: valores de referencia del €STR y de las letras, y tipos
  negativos y ausentes.
* `tests/unit/services/test_risk_free.py`: cada serie con su convención.
* `tests/unit/domain/test_metrics.py`: periodos sin tipo y error estándar con la muestra real.
* `tests/unit/reporting/test_series_report.py`: la advertencia en español y en inglés.

## Pros y contras de las opciones

### Devengo por días naturales en cada periodo

* Positivo: exacto periodo a periodo; por ejemplo, el lunes devenga tres días.
* Negativo: cambia el contrato de `RiskMetrics` y de los informes (rentabilidades sin riesgo
  por periodo en vez de tipos anuales) por una diferencia despreciable en métricas
  anualizadas.

### Mantener el tipo cotizado

* Negativo: sesgo sistemático de unos 11 puntos básicos al año en todos los Sharpe y Sortino
  en euros.

## Más información

* Amplía [ADR-0014](0014-currency-conversion-and-risk-free-rate.md).
* Origen: hallazgo B1 de la auditoría del 3 de noviembre de 2026.
