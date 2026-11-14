---
status: aceptado
date: 2026-11-13
decision-makers: Javier Fernández
---

# Indicadores técnicos propios en NumPy y pandas, con las definiciones de `ta`

## Contexto y problema

La fase G2 del [plan de integración](../plan/integracion-cryptoworld.md) trae a InvestingLab el
análisis técnico de CryptoWorld. Su gramática de estrategias (`strategy_spec`) usa 26
indicadores, casi todos calculados con la librería `ta` 0.11.0. Hay que llevarlos al núcleo
para cualquier clase de activo (D8) sin que una estrategia cambie de significado al cambiar
de plataforma: un RSI de 30 tiene que ser el mismo RSI de 30.

Las opciones habituales tienen pegas. `ta` está poco mantenida, es lenta (bucles de Python y
`rolling.apply`) y rellena el calentamiento con valores inventados. TA-Lib es rápida, pero es
una dependencia nativa difícil de instalar en Windows, y sus definiciones difieren de las de
`ta` (su RSI siembra con una media simple, por ejemplo), así que rompería la paridad.

## Factores de decisión

* Paridad numérica con CryptoWorld, comprobada y no supuesta.
* Nunca inventar datos: un valor del calentamiento es un hueco, no un cero.
* Causalidad: ningún valor depende de velas posteriores.
* Sin dependencias nativas nuevas; tipado completo y tests de propiedades.
* Igual para una acción, un índice, una divisa o una cripto.

## Opciones consideradas

* Depender de `ta`.
* Depender de TA-Lib.
* Implementación propia en NumPy y pandas con las definiciones de `ta`.

## Decisión

Implementación propia en `analytics/technical/`: funciones puras sobre series de pandas
(medias, osciladores, tendencia, volatilidad y volumen), sin tipos de dominio ni E/S. Sobre
ellas, `analytics/technical/catalogue.py` ofrece el catálogo de CryptoWorld con sus 26
nombres (`RSI`, `BB_UPPER`, `DONCH_UPPER`…), las columnas de precio que necesita cada uno, sus
parámetros con los rangos de búsqueda y los umbrales de los osciladores. El catálogo replica
también las decisiones de CryptoWorld para estrategias:

* la RSI estocástica en porcentaje;
* el ATR como porcentaje del cierre;
* los niveles de Donchian y de Fibonacci de la vela anterior, para que un cierre pueda romperlos.

Las definiciones son las de `ta`, con sus convenciones: el RSI y su suavizado de Wilder
desde el primer cambio, la desviación de Bollinger poblacional, el Keltner «original», el
ADX de Wilder o el RSI de 100 sin pérdidas. **Una sola diferencia deliberada:** donde `ta`
inventa valores durante el calentamiento, aquí hay `NaN`. En concreto, `ta` pone ceros en el
ATR y el ADX, calcula ventanas parciales en las bandas de Keltner y usa el cierre como
primer SAR parabólico.

La paridad se comprueba con el código de CryptoWorld, nunca con una copia.
`scripts/record_parity.py` (`just record-parity <ruta>`) importa su `strategy_spec` en un
entorno desechable con sus versiones fijadas (`ta` 0.11.0, pandas 2.2.2, NumPy 1.26.4) y
evalúa sus 26 indicadores sobre velas reales grabadas (`binance/btc_usdt_1d_2025`, 396
diarias), con dos juegos de parámetros por indicador. El resultado, en
`tests/fixtures/parity/`, se versiona y no se edita a mano.

### Consecuencias

* Bien, porque los 61 casos de paridad coinciden con CryptoWorld con un error relativo de
  1e-15, y solo difieren en los valores de calentamiento que `ta` inventa.
* Bien, porque los tests de propiedades exigen que ningún indicador mire al futuro (truncar la
  serie no cambia lo anterior), que los osciladores no cambien al reescalar los precios (un
  *split*, otra divisa) y que las medias y bandas escalen con ellos, y que cada oscilador
  quede en su rango.
* Bien, porque son más rápidos que `ta`: ventanas deslizantes de NumPy en lugar de
  `rolling.apply`. Solo los recursivos (ATR, ADX, KAMA, SAR) recorren las velas una a una.
* Mal, porque mantenemos el código de 26 indicadores; la paridad avisa si alguno se desvía.
* Neutral: `ta` no entra en las dependencias; solo el entorno desechable de la paridad la usa.

### Confirmación

* `tests/contract/test_cryptoworld_parity.py`: los 61 casos, con tolerancia relativa de 1e-10.
* `tests/property/test_technical_properties.py`: causalidad, unidades y rangos.
* `tests/unit/analytics/test_technical.py`: casos calculados a mano y bordes (series planas,
  ventanas inválidas, series cortas).

## Pros y contras de las opciones

### Depender de `ta`

* Bien, porque la paridad sería automática.
* Mal, por el calentamiento inventado, la lentitud y el mantenimiento escaso.

### Depender de TA-Lib

* Bien, por la velocidad.
* Mal, porque es una dependencia nativa y sus definiciones rompen la paridad.

### Implementación propia con las definiciones de `ta` (elegida)

* Bien, por lo dicho en las consecuencias.
* Mal, porque es más código propio.

## Más información

* La fachada de dominio (indicadores de una `PriceSeries`), la API y la pantalla de análisis
  técnico llegan en la parte siguiente de G2, junto con los patrones de velas, la estructura
  (pivotes, soportes y resistencias, divergencias) y la confluencia entre marcos.
