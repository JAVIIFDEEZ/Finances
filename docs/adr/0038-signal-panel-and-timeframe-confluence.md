---
status: aceptado
date: 2026-11-15
decision-makers: Javier Fernández
---

# Panel de reglas por estilo y confluencia entre marcos temporales

## Contexto y problema

G2 trae de CryptoWorld su panel de señales (once reglas de manual con un veredicto), la
tendencia de fondo de su ficha de confluencia y la confluencia entre marcos temporales: una
lectura vale más cuando varios marcos apuntan en la misma dirección. Hay que llevarlo a
cualquier clase de activo (D8) y con tres exigencias que el original no cumple del todo:

* Las once reglas mezclan dos filosofías opuestas. Seis **siguen** el movimiento (el precio
  sobre una media, el MACD sobre su señal, +DI sobre −DI con ADX alto) y cinco **apuestan
  por su giro** (un RSI de 75 apunta a la baja). En una tendencia fuerte se contradicen por
  construcción, y un único neto lo esconde.
* La agregación entre marcos necesita que el neto de cada marco esté en una escala conocida
  para que sus umbrales signifiquen algo.
* Una «confianza» en porcentaje que no es una probabilidad no debe mostrarse como tal.

## Factores de decisión

* Paridad comprobada con el código de CryptoWorld donde su resultado es el que queremos.
* Describir, no recomendar: lo que dice una regla no es una previsión.
* Nunca inventar: una regla sin valor se omite y se nombra; un marco sin datos no opina.
* Igual para una acción, un índice, una divisa o una cripto.

## Decisión

`analytics/technical/signals.py` tiene tres piezas puras:

**El panel de reglas.** Las once reglas del panel de CryptoWorld, con sus mismos parámetros y
umbrales, cada una etiquetada como de **tendencia** o de **giro**. El panel da el recuento
al alza, neutral y a la baja, el neto del conjunto y el neto de cada estilo por separado. El
neto es la media de las reglas (+1 al alza, −1 a la baja), en [−1, 1]: ±1 significa que todas
coinciden. El veredicto es fuerte por encima de ±0,5.

* Una regla que no puede calcularse (sin máximos ni mínimos; pocas velas; un precio que no
  se mueve) se omite y se dice cuál y por qué. Nunca se calcula con sustitutos.
* Un empate exacto es neutral.

**La tendencia de fondo.** El cierre frente a su media simple de 200 velas y la pendiente
de su media exponencial de 50 en las últimas diez (más de un 0,3 % cuenta). Las series
cortas usan medias más cortas, y el resultado dice cuáles.

**La confluencia.** Media de los netos de cada marco, ponderada por su rango: el marco más
fino pesa 1 y cada uno más largo, uno más, porque la tendencia de fondo manda sobre el ruido.

* Sin dirección si la alineación es menor de 0,15 en valor absoluto.
* **Alineados** si además tres cuartos de los marcos leídos apuntan como el conjunto.
* **En conflicto** si la dirección domina pero no la comparten suficientes marcos.
* **Insuficiente** con menos de dos marcos legibles: una opinión no es un consenso.

No se porta la «confianza» en porcentaje de la ficha de CryptoWorld: se dan los recuentos y
si la tendencia acompaña, que es lo que de verdad se sabe.

**Los marcos.** Diario, semanal y mensual por defecto, porque cualquier fuente sirve velas
diarias. Los tres salen de **una sola descarga** de velas diarias: el semanal y el mensual se
agregan de ella (`PriceSeries.resample`), así comparten fuente y ajuste. La última vela de
un marco agregado puede ser un periodo en curso; solo usa lo ocurrido hasta la fecha. Los
marcos intradía (15 min, 30 min, 1 h, 4 h) se piden a las fuentes; un marco que nadie sirve,
o sin velas en las fechas leídas, se informa con su motivo y no cuenta ni pesa. Un marco
necesita 50 velas (la media más larga del panel).

La paridad se graba ejecutando el código de CryptoWorld (`just record-parity`) sobre cortes
de las dos casetes reales: su panel (106 cortes) y su tendencia (116).

### Consecuencias

* Bien, porque en los 222 casos cada regla apunta igual que en CryptoWorld, con las mismas
  cifras, y los recuentos, el neto y el veredicto del panel coinciden.
* Bien, porque la pantalla enseña por separado las reglas de tendencia y las de giro: «seis
  de seis siguen la subida, tres de cinco la ven agotada» dice más que un +0,27.
* Bien, porque los tests de propiedades exigen que reescalar los precios no cambie ninguna
  regla, que toda regla se lea o se omita, que la alineación sea una media ponderada y que
  dar la vuelta a todos los netos dé la vuelta al veredicto.
* Neutral: la agregación entre marcos se define aquí sobre el neto en [−1, 1]; no se compara
  con CryptoWorld, cuya escala es otra.
* Mal, porque los umbrales (0,3 % de pendiente, 0,15 de alineación) son fijos y no se
  adaptan a la volatilidad de cada activo. Se mantienen por paridad; queda abierta una
  variante proporcional al ATR.

### Confirmación

* `tests/contract/test_cryptoworld_signals_parity.py`
* `tests/property/test_signals_properties.py`
* `tests/unit/analytics/test_signals.py`, `tests/unit/domain/test_confluence.py`

## Más información

* [ADR-0037](0037-conventional-indicator-readings.md): las lecturas de cada indicador.
* Si alguna de estas reglas anticipa algo es una pregunta para la validación de estrategias
  de G3 (backtest con costes, corrección por pruebas múltiples), no para este panel.
