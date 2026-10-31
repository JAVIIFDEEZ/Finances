---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Representación temporal: UTC en intradía y etiquetas de sesión en diario

## Contexto y problema

La plataforma combina mercados de distintas zonas horarias (Madrid, Nueva York, Tokio, cripto
24/7) y frecuencias desde 1 minuto hasta anual. ¿Cómo representamos el tiempo para que las
series se puedan alinear sin errores?

## Factores de decisión

* Una sesión diaria de Madrid es "el 15 de marzo" para cualquier observador. Convertida a
  Nueva York o a UTC, no puede acabar en el día 14.
* Las barras intradía de distintos mercados deben compararse en un instante absoluto.
* El enfoque debe ser simple y verificable.

## Opciones consideradas

1. Todo en UTC con hora (incluidas las barras diarias, con la hora de cierre)
2. Todo con hora local del mercado
3. **Mixto**: intradía en UTC; diario o superior con etiquetas de sesión (fechas sin zona horaria)

## Decisión

Opción elegida: **3**.

* **Intradía** (`1m` … `4h`): `DatetimeIndex` con zona horaria y normalizado a **UTC**. El
  timestamp es la hora de **apertura** de la barra.
* **Diario y superior**: `DatetimeIndex` **sin zona horaria**, a medianoche. Cada valor es la
  fecha de la sesión en la zona horaria del mercado, que se guarda como metadato del
  instrumento (`Instrument.exchange.timezone`).
* Al remuestrear de intradía a diario, la fecha de sesión se calcula en la zona del mercado.
  Por ejemplo, 00:00 UTC en Tokio es la sesión de ese mismo día.
* Al remuestrear a semanal, mensual o anual, cada periodo se etiqueta con la **última sesión
  observada**, nunca con una fecha de calendario inventada.
* La anualización depende del mercado y la frecuencia: 252 sesiones al año en renta variable,
  365 en cripto, 260 en FX, y barras por sesión × sesiones en intradía (`MarketSchedule`).

### Consecuencias

* Positiva: alinear series diarias de distintos mercados es una unión de fechas, sin
  desplazamientos.
* Positiva: el intradía se compara en instantes absolutos.
* Negativa: dos convenciones en lugar de una. Se compensa porque la validación de
  `PriceSeries` impone la correcta según la frecuencia.
* Negativa: el diario no captura el desfase de cierres (Europa cierra horas antes que EE. UU.).
  Se trata como sesgo de *trading* no sincrónico en el análisis
  ([ADR-0008](0008-alignment-without-artificial-fill.md)).

### Confirmación

`PriceSeries` rechaza índices diarios con zona horaria y los intradía sin ella. Los tests
de remuestreo (`test_series_resample.py`) verifican las fechas de sesión en la zona del
mercado.
