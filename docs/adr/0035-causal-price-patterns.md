---
status: aceptado
date: 2026-11-14
decision-makers: Javier Fernández
---

# Patrones de precio como sucesos causales, con un solo vocabulario

## Contexto y problema

La fase G2 del [plan de integración](../plan/integracion-cryptoworld.md) trae a InvestingLab
los patrones de precio de CryptoWorld para cualquier clase de activo (D8). CryptoWorld tiene
**dos** vocabularios que no coinciden:

* `price_patterns.PATTERNS`, los 20 patrones de su gramática de estrategias: velas japonesas,
  *Fair Value Gaps*, barridas de liquidez, *order blocks*, CRT, *Power of Three*, ruptura del
  rango de apertura (ORB) y zonas de Fibonacci. Cada detector devuelve una bandera por vela y
  es causal por diseño.
* `detect_candle_patterns`, las 12 velas de su pantalla. Solo mira las cinco últimas velas,
  define el martillo, el doji, la estrella fugaz y las envolventes de otra manera que la
  gramática y adjunta a cada patrón una «fiabilidad» (ALTA, MEDIA) que nada respalda.

Además, sus patrones de sesión cortan el día a medianoche UTC, que no es la apertura de
ningún mercado con horario, y el detector rellena con el cierre la apertura, el máximo y el
mínimo que falten.

## Factores de decisión

* Que una estrategia de CryptoWorld conserve su significado al cambiar de plataforma
  (paridad comprobada, no supuesta).
* Causalidad estricta: una bandera no depende de ninguna vela posterior.
* Nunca inventar datos: ni columnas sustitutas ni afirmaciones sin medir.
* Igual para una acción, un índice, una divisa o una cripto, con su propia sesión.

## Decisión

`analytics/patterns/` implementa los patrones como funciones puras sobre series de pandas
que devuelven una bandera por vela: velas (`candles`), estructura y liquidez (`liquidity`),
sesiones (`sessions`) y zonas (`zones`). `catalogue.py` los nombra como la gramática de
CryptoWorld, con sus parámetros y rangos de búsqueda, su familia, su dirección y las
columnas que necesita cada uno.

* **Un solo vocabulario.** Los 20 patrones de la gramática conservan nombre, parámetros y
  definición. Las cinco velas que solo tenía la pantalla (martillo invertido, estrellas de la
  mañana y de la tarde, tres soldados y tres cuervos) se añaden con nombres del mismo estilo.
  Donde la pantalla y la gramática definían la misma vela de dos maneras, se queda la de la
  gramática: es con la que se encontraron las estrategias.
* **Sin «fiabilidad».** Cada patrón dice qué hicieron las velas y en qué dirección apunta su
  definición (los patrones espejo tienen direcciones opuestas). Si anticipa algo, lo dirá la
  validación de una estrategia en G3, no una etiqueta.
* **La bandera va en la vela que completa el patrón.** Un FVG se marca en la tercera vela,
  un *order block* cuando el precio vuelve a él, nunca en la vela donde suele dibujarse.
* **Sesiones del mercado.** Los patrones de sesión reciben la sesión de cada vela: la fecha
  de negociación en la zona horaria del mercado para una bolsa y la fecha UTC para los
  mercados que no cierran, que reproduce los valores de CryptoWorld.
* **Sin columnas sustitutas.** Un patrón que necesita la apertura no se calcula sobre una
  serie de cierres: queda fuera, con las columnas que le faltan.
* **Una corrección deliberada.** Los *order blocks* de CryptoWorld no devolvían ninguna
  bandera en series de menos de `impulse + 2` velas, así que la última vela de una serie de
  `impulse + 1` dependía de las velas que vinieran después. Sin esa guarda el detector es
  causal; en series reales no cambia nada (la paridad lo comprueba).

La paridad se comprueba con el código de CryptoWorld, nunca con una copia:
`scripts/record_parity.py` (`just record-parity <ruta>`) ejecuta sus detectores sobre dos
casetes reales de Binance, 396 velas diarias y 336 horarias (la casete horaria es nueva, para
el ORB), con dos juegos de parámetros por patrón. La pantalla solo mira cinco velas, así que
se evalúa en una ventana de cinco que termina en cada vela.

### Consecuencias

* Bien, porque los 76 casos de paridad marcan exactamente las mismas velas que CryptoWorld.
* Bien, porque los tests de propiedades exigen que ningún patrón mire al futuro, que
  reescalar los precios no cambie ninguna bandera y que, con los precios dados la vuelta,
  cada patrón se convierta en su espejo (y los simétricos, como el doji o el CRT, sigan
  igual): las definiciones tratan igual ambas direcciones.
* Bien, porque la misma vela, la misma barrida y el mismo ORB sirven para `SAN.MC`, `^GSPC`,
  `EURUSD=X` y `BTC/USDT`, cada uno con su sesión.
* Mal, porque mantenemos el código de 25 patrones; la paridad avisa si alguno se desvía.
* Neutral: la pantalla de CryptoWorld deja de tener definiciones propias.

### Confirmación

* `tests/contract/test_cryptoworld_pattern_parity.py`: los 76 casos, igualdad exacta.
* `tests/property/test_pattern_properties.py`: causalidad, unidades y espejo.
* `tests/unit/analytics/test_patterns.py`: casos calculados a mano y errores del catálogo.

## Pros y contras de las opciones

### Portar los dos vocabularios tal cual

* Bien, por la paridad trivial con ambos.
* Mal, porque dos «martillos» distintos confunden y la pantalla mira solo cinco velas.

### Usar una librería de patrones (TA-Lib)

* Bien, por la velocidad.
* Mal, porque es una dependencia nativa, no tiene FVG, barridas ni *order blocks* y rompe
  la paridad.

### Un vocabulario propio con las definiciones de la gramática (elegida)

* Bien, por lo dicho en las consecuencias.
* Mal, porque es más código propio.

## Más información

* [ADR-0034](0034-technical-indicators-in-numpy.md): los indicadores, con la misma estrategia
  de paridad.
* La fachada de dominio (`domain.patterns`, `price_patterns`), `tk.patterns`, el endpoint
  `/api/v1/market/patterns` y el panel de patrones de la pantalla de mercados llegaron en la
  parte siguiente de G2. Quedan la estructura (pivotes, soportes y resistencias,
  divergencias) y la confluencia entre marcos.
