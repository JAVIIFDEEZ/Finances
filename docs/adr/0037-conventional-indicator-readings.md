---
status: aceptado
date: 2026-11-14
decision-makers: Javier Fernández
---

# Lecturas convencionales de los indicadores

## Contexto y problema

La pantalla de análisis técnico mostraba 31 valores sin interpretar: un RSI de 63,48 no dice
nada a quien no conoce sus zonas. El catálogo trae de CryptoWorld un `threshold` por
oscilador, pero es el **rango de búsqueda** de umbrales de su gramática de estrategias (RSI
15-85), no una zona de lectura, y dibujarlo como sobrecompra y sobreventa engañaría
([ADR-0035](0035-causal-price-patterns.md), deuda anotada en G2).

## Factores de decisión

* Describir dónde está cada indicador, nunca predecir.
* Ninguna cifra sin fuente: zonas con autor, o el propio historial de la serie.
* Lo mismo en la API, la web y los informes: la lectura vive en el núcleo.

## Decisión

`analytics/technical/readings.py` da a cada indicador del catálogo una **familia**
(tendencia, momento, volatilidad, volumen, precio) y una **regla de lectura**:

| Regla | Indicadores | Lectura |
|-------|-------------|---------|
| Zonas de sus autores | RSI 30/70 (Wilder, 1978); estocástico 20/80 (Lane); RSI estocástico 20/80 (Chande y Kroll, 1994); Williams %R −80/−20; CCI ±100 (Lambert, 1980); MFI 20/80 (Quong y Soudack, 1989); ADX 20/25 (Wilder: sin tendencia por debajo de 20, tendencia por encima de 25); oscilador Aroon ±50 (Chande, 1995); CMF ±0,05 (Chaikin) | `low`, `neutral`, `high` |
| Línea cero | ROC, TRIX, líneas del MACD | `below`, `above` |
| Nivel en precio | medias, bandas, canales, SAR parabólico, Ichimoku, Fibonacci | el cierre `above` o `below` del nivel |
| Su propio historial | ATR en % del precio, ratio de volumen | percentil en las velas dadas; `high` en el quinto superior, `low` en el inferior |

El precio en sí no tiene lectura. Mientras un indicador se calienta, tampoco. Estar en un
borde exacto no es estar más allá.

Además, una columna de volumen toda a cero cuenta como **volumen que no se publica**: Yahoo
da ceros en los índices, y un MFI calculado sobre ceros no es un dato.

### Consecuencias

* Bien, porque la pantalla puede decir «RSI 63: neutral», sombrear las zonas de cada oscilador
  y resumir tendencia, momento, volatilidad y volumen sin inventar umbrales.
* Bien, porque el ATR y el volumen se juzgan contra la propia serie: un 1,4 % es mucho para un
  bono y poco para una cripto.
* Neutral: las zonas son convenciones; no dicen que el precio vaya a girar en ellas. La web lo
  advierte.
* Mal, porque el percentil depende del periodo elegido; la web dice sobre qué velas se mide.

### Confirmación

* `tests/unit/analytics/test_readings.py`: toda entrada del catálogo tiene familia y regla.
* `tests/unit/domain/test_technical.py`: lecturas en la última vela y volumen a cero.
