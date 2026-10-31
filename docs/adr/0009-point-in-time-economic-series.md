---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Series macroeconómicas bitemporales (point-in-time)

## Contexto y problema

Los datos macro, como el paro, el PIB o el IPC, se publican **después** del periodo que miden
y se **revisan** más tarde. FRED devuelve por defecto la última versión revisada. Usarla en un
análisis histórico mete información del futuro (*look-ahead bias*): el dato revisado de
enero de 2020 no lo conocía nadie en enero de 2020.

## Factores de decisión

* Los backtests y análisis históricos no pueden usar información futura.
* FRED/ALFRED ofrece las versiones históricas (*vintages*) con su fecha de publicación
  (`realtime_start`), con la misma API y la misma clave.
* Para exploración rápida basta con la última versión.

## Opciones consideradas

1. Guardar solo la última versión (FRED por defecto)
2. Guardar solo la primera publicación con su fecha
3. **Modelo bitemporal**: todas las versiones con fecha de observación y fecha de publicación

## Decisión

Opción elegida: **3**. `EconomicSeries` guarda observaciones en formato largo
(`observation_date`, `published_at`, `value`) y ofrece:

| Método | Devuelve |
|--------|----------|
| `first_release()` | Lo que el mercado vio primero |
| `latest()` | La versión más revisada (solo para exploración; no es point-in-time) |
| `as_of(fecha)` | La serie tal y como se podía descargar ese día |
| `known_values_at(fechas)` | Para cada fecha, el valor de la última observación ya publicada, en su versión vigente. Es el que se usa para unir macro con precios diarios. |

El adaptador de FRED (fase F2) usará **ALFRED por defecto**: descarga las versiones con su
`realtime_start` y, si se pide solo la primera publicación, `output_type=4`.

### Consecuencias

* Positiva: ningún análisis histórico usa datos que no se conocían en su momento.
* Positiva: se puede estudiar el impacto de las revisiones.
* Negativa: más volumen de datos por serie. Es asumible: las series macro son pequeñas.

### Confirmación

* Test unitario con un dato revisado: la revisión no se usa antes de su publicación.
* Test de propiedades con hypothesis: para cualquier conjunto de versiones y fechas,
  `known_values_at` solo devuelve valores ya publicados, y siempre la versión vigente.
