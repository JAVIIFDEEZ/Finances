---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Validación estricta de las series de entrada

## Contexto y problema

El enunciado B1-T1 (§4.5) plantea si el programa debe admitir *cualquier* input que contenga
una serie temporal de precios o si conviene imponer restricciones más estrictas.

Los datos llegan de proveedores heterogéneos (Yahoo, Alpha Vantage, FRED…) y de usuarios
(CSV, DataFrames). Los errores típicos son silenciosos:

* precios en peniques en vez de libras (factor 100);
* splits sin ajustar, que parecen caídas del −75 %;
* zonas horarias que desplazan una sesión al día anterior;
* frecuencias mezcladas;
* NaN que alguien rellena con ceros;
* fechas duplicadas o desordenadas.

Ninguno rompe el programa: todos producen un Sharpe, una volatilidad o una correlación
**falsos** que nadie detecta.

## Factores de decisión

* Un número financiero erróneo es peor que un error explícito: puede llevar a decisiones reales.
* Los objetos del dominio deben ser intercambiables entre proveedores (§4.2): mismas garantías
  vengan de donde vengan.
* Experiencia de uso: quien construye una serie mala debe saber exactamente qué falla.

## Opciones consideradas

1. **Permisiva (*duck typing*)**: aceptar cualquier objeto con índice temporal y números.
2. **Correctiva**: intentar arreglar la entrada (ordenar, deduplicar, rellenar NaN, recortar negativos).
3. **Estricta en el borde**: invariantes estructurales obligatorios; solo transformaciones sin
   pérdida de información; error tipado con *todos* los problemas.

## Decisión

Opción elegida: **3, validación estricta en el borde**.

Una `PriceSeries` solo existe si cumple estos invariantes:

| Invariante | Por qué |
|------------|---------|
| Índice `DatetimeIndex` creciente y sin duplicados | El orden temporal es la base de cualquier retorno |
| Intradía con zona horaria (se normaliza a UTC); diario o superior con etiquetas de sesión sin zona horaria y a medianoche (ADR-0007) | Evita desplazamientos de sesión por zona horaria |
| Separación entre observaciones coherente con la frecuencia declarada | Detecta series diarias etiquetadas como mensuales y al revés |
| Columna `close` obligatoria; solo `open/high/low/close/adj_close/volume` | Contrato homogéneo entre proveedores |
| Precios numéricos, finitos y **estrictamente positivos** | Un precio ≤ 0 o NaN no es un precio; un dato que falta es una fila ausente, no un NaN |
| Volumen finito y ≥ 0 (NaN permitido: "no informado") | Algunos proveedores no publican volumen de índices |
| Al menos 3 observaciones | Mínimo para una desviación típica muestral de retornos |
| Divisa ISO 4217 válida en el instrumento; procedencia (`DataSource`) con fecha de descarga *aware* | Trazabilidad y conversión de divisas correcta |

**Transformaciones permitidas** (sin pérdida): convertir zonas horarias a UTC, convertir
tipos numéricos a `float64` y reordenar columnas. **Nunca** se ordena, deduplica, rellena ni
recorta en silencio.

**Invariante frente a diagnóstico.** Los problemas estructurales impiden crear el objeto.
Los problemas de *calidad* (outliers, OHLC incoherente, precios congelados, huecos frente al
calendario) no lo impiden. Se detectan y se reportan sin borrar nada (fase F3), porque pueden
ser eventos reales de mercado.

**Errores.** `InvalidSeriesError` acumula todos los problemas encontrados
(`error.problems`), con ejemplos de fechas afectadas, y nombra el símbolo.

### Consecuencias

* Positiva: cualquier analítica puede asumir datos limpios, sin defensas repetidas.
* Positiva: los adaptadores de proveedores tienen un contrato claro (lo verifican los tests de contrato).
* Negativa: el usuario debe limpiar sus datos antes de crear la serie. Para importar ficheros
  se ofrecerá un importador que documenta y aplica las correcciones de forma explícita.

### Confirmación

Tests unitarios por invariante (`tests/unit/domain/test_series.py`) y tests de propiedades
con hypothesis.

## Pros y contras de las opciones

### Permisiva

* Positivo: máxima flexibilidad.
* Negativo: traslada la validación a cada función y deja pasar errores silenciosos.

### Correctiva

* Positivo: "funciona" con casi cualquier dato.
* Negativo: inventa información (rellenar NaN, cambiar signos) y oculta problemas de origen.
  Contradice la regla de no fabricar datos ([ADR-0008](0008-alignment-without-artificial-fill.md)).
