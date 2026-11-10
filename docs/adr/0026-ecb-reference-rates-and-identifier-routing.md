---
status: aceptado
date: 2026-11-09
decision-makers: Javier Fernández
---

# El BCE como fuente oficial de divisas y tipos del euro, con enrutado por identificadores

## Contexto y problema

[ADR-0014](0014-currency-conversion-and-risk-free-rate.md) convierte divisas con el símbolo
canónico `EURUSD=X` y usa €STR como tipo libre de riesgo del euro, pero hasta ahora esos datos
solo podían venir de FRED, que necesita clave. El plan fija el orden de fuentes de divisas
«BCE (oficial) → FRED → Yahoo». Al añadir el BCE hay que decidir qué sirve, cómo se fecha la
publicación de cada valor y cómo convive con Yahoo, que también sirve `EURUSD=X`.

## Factores de decisión

* Datos oficiales y sin clave para la conversión de divisas y el tipo libre de riesgo en euros.
* *Point-in-time*: cada valor macro debe llevar el día en que se conoció.
* Nada inventado: un festivo es un hueco.
* Un registro de proveedores que no pregunte a quien no puede responder.

## Opciones consideradas

* Servir con el BCE los pares de divisas y las series de tipos, preferido para `=X` diario.
* Usar el BCE solo para series económicas y dejar las divisas a Yahoo.
* Servir cualquier serie del portal del BCE con la fecha de observación como publicación.

## Decisión

Opción elegida: **el BCE sirve pares de divisas y un catálogo cerrado de tipos**, porque da
*fixings* oficiales a la conversión y €STR sin clave, sin renunciar al *point-in-time*.

`adapters/providers/ecb/` contiene:

* `provider.py`: `EcbProvider`, que implementa los dos puertos.
  * **Barras de pares** del conjunto `EXR` (tipos de referencia de las 14:15 CET,
    publicados hacia las 16:00): `EURUSD=X` directo, `USDEUR=X` como su inverso y los pares
    sin euro (`GBPUSD=X`) como cociente de dos tipos **del mismo día**. Solo cierre; diario y,
    agregado, semanal y superior. Solo las 30 divisas con tipo de referencia.
  * **Series económicas** de un catálogo cerrado (`catalogue.py`): €STR
    (`EST.B.EU000A2X2A25.WT`) y los tipos oficiales (facilidad de depósito, operaciones
    principales y facilidad marginal, `FM.D.U2.EUR.4F.KR.*.LEV`). Cada una declara su regla de
    publicación: €STR se publica el siguiente día hábil TARGET a las 08:00 CET; los tipos
    oficiales se anuncian antes de entrar en vigor, así que se dan por conocidos en su fecha
    (conservador). Una serie sin regla conocida no se sirve.
* `calendar.py`: días hábiles TARGET (fines de semana, 1 de enero, Viernes Santo, Lunes de
  Pascua, 1 de mayo, 25 y 26 de diciembre) con las reglas de festivos de pandas.

Las filas sin valor (`OBS_STATUS=H`, festivos) se descartan y un rango sin datos (el portal
responde un cuerpo vacío) es un `ProviderDataError`. El portal da 504 con frecuencia: el
`HttpClient` lo reintenta.

**Enrutado por identificadores.** `ProviderCapabilities.identifiers` es una expresión regular
de los símbolos y series que sirve un proveedor de universo cerrado. El registro no pregunta
a un proveedor por un identificador que no casa, en barras ni en series económicas. El BCE
declara sus pares y su catálogo, y los ficheros locales su `instruments.toml`. Así una acción
que sirve Yahoo no genera un aviso `bars_provider_failed` de cada proveedor anterior.

**Orden por defecto en el `Toolkit`:** proveedores del usuario → ficheros locales → BCE →
Yahoo. `EURUSD=X` diario sale del BCE (oficial). El intradía y los pares sin tipo de
referencia salen de Yahoo.

**Tipo libre de riesgo del euro:** €STR del BCE → €STR de FRED → depósito del BCE → depósito de
FRED. Cada par de fuentes publica los mismos datos, así que basta con una de ellas.

### Consecuencias

* Positiva: conversión con *fixings* oficiales y tipo libre de riesgo en euros sin claves.
* Positiva: el registro deja de generar avisos por proveedores que no podían responder.
* Negativa: `EURUSD=X` diario es el tipo de referencia (solo cierre), no la última cotización
  de Yahoo. Quien quiera OHLC puede pedir intradía o registrar Yahoo antes.
* Negativa: los cruces sin euro dependen de dos series; un día en que falte una no tiene barra.

### Confirmación

* `tests/unit/adapters/test_ecb.py` con casetes reales: tipo directo, inverso, cruce, festivo
  del 31-12-1999, rango vacío, agregación semanal, €STR alrededor de la Semana Santa de 2026 y
  la bajada del tipo de depósito del 11-06-2025.
* `tests/contract/test_market_data_providers.py` y el nuevo
  `tests/contract/test_economic_providers.py`, que exige `published_at >= observation_date`.
* `tests/unit/test_toolkit.py`: el BCE sirve `EURUSD=X` y el €STR del tipo libre de riesgo.
* `tests/unit/ports/test_market_data.py` y `tests/unit/services/test_registry.py`: enrutado
  por identificadores.

## Pros y contras de las opciones

### BCE para divisas y tipos

* Positivo: fuente oficial, sin clave y con la regla de publicación conocida.
* Negativo: solo cierre diario y 30 divisas.

### BCE solo para series económicas

* Positivo: `EURUSD=X` conserva el OHLC de Yahoo.
* Negativo: la conversión usaría cotizaciones no oficiales, contra el plan y ADR-0014.

### Cualquier serie del portal con publicación igual a la observación

* Positivo: catálogo enorme sin trabajo.
* Negativo: rompe el *point-in-time* en series mensuales que se publican semanas después.

## Más información

* [ADR-0009](0009-point-in-time-economic-series.md), [ADR-0010](0010-multi-provider-ingestion.md),
  [ADR-0014](0014-currency-conversion-and-risk-free-rate.md) y
  [ADR-0025](0025-yahoo-chart-adapter-and-cassettes.md).
* Portal de datos del BCE: `data-api.ecb.europa.eu` (SDMX 2.1, formato `csvdata`).
* Ampliar el catálogo exige documentar la regla de publicación de cada serie.
