---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Diagnóstico de calidad de datos con calendarios oficiales

## Contexto y problema

Los datos gratuitos traen errores:

* *ticks* erróneos;
* splits sin ajustar, que parecen una caída del −75 %;
* *feeds* congelados que repiten el mismo precio;
* OHLC incoherentes;
* sesiones que faltan;
* datos en días festivos.

La validación estricta (ADR-0006) rechaza lo **estructuralmente** imposible. Estos casos, en
cambio, pueden ser datos correctos (un crash real, una suspensión de cotización), así que no
deben bloquear ni borrarse: deben **detectarse y explicarse**.

## Factores de decisión

* Regla del proyecto: los outliers se detectan y reportan, nunca se borran.
* Distinguir un festivo de un dato ausente exige el calendario oficial de cada mercado.
* Los umbrales deben ser explícitos y configurables.

## Decisión

**Detectores puros** en `analytics.quality`. Señalan dónde, nunca modifican:

| Detector | Qué busca |
|----------|-----------|
| `robust_zscores` | Log-retornos lejos de la mediana. La escala es la mediana de las desviaciones absolutas (MAD), que los propios extremos no pueden inflar. Si la MAD es 0, se usa la desviación absoluta media. |
| `split_like_jumps` | Ratios de precio cercanos a 1/k o k, con k ∈ {2, 3, 4, 5, 8, 10, 20, 25, 50, 100} |
| `stale_runs` | Rachas de precios idénticos |
| `ohlc_violations` | `high` o `low` incoherentes con `open`/`close` |
| `missing_sessions`, `unexpected_sessions` | Diferencias frente a las sesiones oficiales del mercado |

**Informe** (`DataQualityReport`, dominio):

* Cada incidencia es un `QualityIssue` con tipo, severidad (`info`, `warning` o `critical`),
  mensaje y fechas afectadas, ordenadas de más a menos grave.
* Un salto con forma de split es **crítico** si los precios no están ajustados, y *warning*
  si ya lo están.
* Las sesiones ausentes son *warning* si superan el 1 % y *info* si son menos.
* Un histórico de menos de un año es *warning*: los estadísticos anualizados no son fiables.
* Los umbrales están en `QualityThresholds`.

**Calendarios oficiales** detrás del puerto `TradingCalendar`:

* El adaptador `ExchangeCalendarsAdapter` usa `exchange_calendars`, que contiene las reglas de
  festivos de más de 50 mercados y no hace ninguna llamada de red.
* Equivalencias: Nasdaq → NYSE y CRYPTO → 24/7. FX no tiene calendario.
* `DataQualityService` pide las sesiones si el mercado está soportado. Si no hay calendario,
  degrada sin error: no comprueba las sesiones ausentes.
* La biblioteca aún usa APIs de pandas obsoletas en pandas 3; el adaptador aísla esos avisos.

### Consecuencias

* Positiva: cada serie llega al informe con un diagnóstico razonado (ver ADR-0006).
* Positiva: festivos y sesiones ausentes ya no se confunden.
* Negativa: los umbrales por defecto (z robusto > 8, rachas ≥ 5) pueden no servir para
  activos muy ilíquidos; son configurables.
* Pendiente: *quality gate* de no-regresión que compare una descarga nueva con la caché para
  detectar revisiones inesperadas del histórico.

### Confirmación

Tests en `test_quality.py` (núcleo y dominio), `test_calendars.py`, que comprueba con
calendarios reales el Lunes de Pascua en Madrid y no en Nueva York, y
`test_quality_service.py`.
