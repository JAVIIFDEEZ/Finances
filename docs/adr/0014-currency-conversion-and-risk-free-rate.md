---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Conversión de divisas *as-of* y tipo libre de riesgo por divisa

## Contexto y problema

Una cartera de un inversor en euros mezcla activos en EUR (SAN.MC), USD (SPY) o GBP (VOD.L).
`Portfolio` exige que todas sus series estén en la divisa base (ADR-0008), así que hay que
convertirlas antes. Además, el Sharpe y el Sortino necesitan el tipo libre de riesgo de esa
divisa base. ¿Cómo se hace sin *look-ahead* y sin inventar datos?

## Factores de decisión

* No usar un tipo de cambio publicado después del precio que convierte.
* No rellenar con tipos inexistentes.
* El riesgo divisa es riesgo real para el inversor: debe verse en los retornos y explicarse.
* El tipo libre de riesgo debe ser el conocido en cada fecha (ADR-0009).

## Decisión

**`FxRates`** (dominio) representa los *fixings* de un par validados: positivos, ordenados,
diarios a medianoche o UTC intradía.

**Conversión *as-of*** (`FxRates.convert`):

* Cada precio usa el **último fixing disponible en su momento** (`merge_asof` hacia atrás).
  * Un fixing diario del día *d* convierte la sesión *d*. El BCE publica hacia las 16:00 CET,
    antes de los cierres de Madrid y Nueva York.
  * Para barras intradía, un fixing diario solo se usa desde *d + 1*. Es una regla
    conservadora: ninguna barra usa un tipo publicado después.
* Un precio sin fixing con antigüedad menor o igual a `max_staleness` (7 días por defecto)
  se **elimina**, no se rellena.
* Los precios en la divisa base del par se multiplican y los de la divisa cotizada se dividen.
  El volumen no cambia.
* La procedencia (`DataSource.dataset`) deja constancia de la conversión y del proveedor
  de los tipos.

**Atribución** (`currency_attribution`): separa el retorno convertido en retorno local y
retorno divisa, con `(1 + total) = (1 + local) · (1 + divisa)`.

**`CurrencyService`**:

* Obtiene los *fixings* a través de `MarketDataService`, con el símbolo canónico `EURUSD=X`.
  Así cualquier proveedor de FX registrado (BCE, FRED, Yahoo) sirve.
* Convierte varias series pidiendo **cada par una sola vez**.

**`RiskFreeRateService`**:

* Para cada divisa hay una lista de series FRED/ALFRED por orden de preferencia:
  * EUR: €STR (`ECBESTRVOLWGTTRMDMNRT`) y, como respaldo, el tipo de depósito del BCE
    (`ECBDFR`);
  * USD: T-Bill a 3 meses (`DGS3MO`).
* En cada fecha se usa el valor **ya publicado** (`known_values_at`), convertido de porcentaje
  a decimal.
* Si la serie preferida aún no existía (el €STR empieza en octubre de 2019), se toma la
  siguiente. Nunca se interpola.
* Se aceptan unidades en porcentaje; otras unidades provocan un error explícito.

### Consecuencias

* Positiva: los retornos en divisa base incluyen el riesgo divisa real, y la atribución lo
  hace visible en el informe.
* Positiva: ni los tipos de cambio ni los tipos libres de riesgo introducen información
  futura.
* Negativa: los mercados que cierran antes del fixing del BCE (Tokio) usan el fixing de su
  misma fecha, publicado horas después de su cierre. Para análisis diarios es un desfase
  aceptado y documentado; para un rigor total se puede convertir con el fixing anterior.
* Pendiente:
  * cobertura de divisa (retornos *hedged* con el diferencial de tipos);
  * tipo libre de riesgo para GBP y CHF.

### Confirmación

Tests en `test_fx.py`, `test_fx_service.py` y `test_risk_free.py`. Propiedades verificadas
con hypothesis:

* ida y vuelta de conversión con el par inverso;
* identidad de la atribución.
