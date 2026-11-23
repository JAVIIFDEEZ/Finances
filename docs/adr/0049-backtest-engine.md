---
status: aceptado
date: 2026-11-24
decision-makers: Javier Fernández
---

# Motor de backtest: relleno a la apertura siguiente, costes por mercado y paridad con CryptoWorld

## Contexto y problema

G3 empieza por el motor de backtest: señales → operaciones → *equity*. Sobre él irán:

- la validación (purga, CPCV, DSR, PBO…);
- los mundos nulos;
- el informe con veredicto;
- el Laboratorio de G4.

CryptoWorld ya tiene uno (`backtest_execution.simulate`), afinado durante decenas de versiones:

- relleno desplazado;
- barreras dentro de la vela;
- cortos y *funding*;
- dimensionado por convicción.

Pero piensa en cripto:

- comisión y deslizamiento en puntos básicos, sin mínimos ni impuestos;
- 365 velas por año para todo;
- porcentajes en vez de fracciones;
- precios sin ajustar.

Hay que decidir si se porta o se escribe otro, cómo se garantiza que una estrategia significa
lo mismo en las dos plataformas y qué se añade para acciones.

## Factores de decisión

* **Que una estrategia valga lo mismo al cambiar de plataforma.** Las de CryptoWorld deben dar
  las mismas operaciones aquí (la misma exigencia que los indicadores, ADR-0034).
* **Nada optimista por construcción.** Ninguna orden se rellena a un precio ya visto.
* **Costes de verdad para acciones.**
  * La comisión mínima de un *broker*.
  * El impuesto sobre transacciones financieras: España, 0,2 %; Francia, sobre las grandes
    cotizadas.
  * El coste de préstamo de un corto.
  * Los dividendos.
* **El calendario de cada mercado** en las métricas: 252 sesiones para una acción española,
  365 días para bitcoin.
* **Base para G4.** El Laboratorio simulará miles de estrategias: el motor debe ser puro y
  determinista.

## Opciones consideradas

1. **Portar el motor de CryptoWorld** a `analytics/backtest/`, comprobado contra su propia
   salida, y generalizar sus costes.
2. **Un motor vectorizado nuevo** (posiciones como serie y retornos por producto).
3. **Una librería** (vectorbt, backtrader, zipline-reloaded).

## Decisión

Opción 1.

### Dónde vive

* **`analytics/backtest/`:** el motor, sobre *arrays*, sin dominio (`simulate`).
  * Sus modelos: `CostModel`, `RiskModel` y `SizingModel`.
  * Su resultado: `Simulation` y `Trade`.
* **`domain/backtest.py`:**
  * valida la configuración (`BacktestConfig`);
  * da al motor las velas de una `PriceSeries`;
  * convierte lo que hizo en un `BacktestResult`: *equity* fechada, operaciones con sus fechas
    y costes, estadísticas, y métricas con `RiskMetrics`;
  * `PriceSeries.backtest(signals)` es el atajo.

### Las convenciones (las de CryptoWorld)

* **Señales como eventos.** `1` abre, `-1` cierra y `0` mantiene. Una señal que falta es un
  error, no un «mantener» inventado.
* **Relleno a la apertura siguiente.** La señal de la vela `i` se calcula con su cierre y se
  rellena en la apertura de `i + 1`. Las velas son sesiones del mercado, así que la siguiente
  a un viernes es la del lunes, o la del martes si el lunes es festivo. La señal de la última
  vela no se ejecuta.
* **Barreras dentro de la vela,** a su propio precio, desde la vela siguiente a la entrada:
  * *stop*, objetivo, *trailing*, y *stop* y objetivo en ATR (ATR de 14 medido en la entrada);
  * si una vela toca *stop* y objetivo, gana el *stop*.
  * La salida por tiempo se rellena a la apertura.
* **Cortos** con su contabilidad propia: se vende primero, el *stop* va por encima, el
  *funding* positivo es ingreso y una vela que dice «cierra» y «abre el otro lado» solo cierra.
* **Una posición cada vez.**
* **Dimensionado:** todo, una fracción, por riesgo (lo que se pierde si salta el *stop*, sin
  apalancamiento) o por convicción.
* **La convicción** se da en la vela de la señal, que es cuando se conoce. El dominio la lleva
  a la vela en que rellena, la misma traducción que hace `meta_sizing` en CryptoWorld.

### Lo que añade Finances

* **Comisión mínima por orden** en la divisa del instrumento. Una orden que la comisión se
  comería entera no se envía.
* **Impuesto sobre las compras** (`transaction_tax_bps`): la entrada de un largo y la recompra
  de un corto; las ventas no lo pagan. La base es lo comprado, y el impuesto va aparte.
* **Préstamo de un corto** por vela, sobre su valor al cierre.
* ***Funding* de un perpetuo** por vela, con signo (positivo: pagan los largos).
* **Deslizamiento** por lado, que incluye medio *spread* y el impacto: el que compra paga más
  y el que vende recibe menos.
* **Desglose de costes:** comisión, impuesto, deslizamiento, *funding* y préstamo, por separado,
  porque crecen con cosas distintas (número de órdenes, tiempo en mercado, tamaño frente a la
  liquidez).
* **Precios ajustados.** Si la serie tiene `adj_close`, se opera con apertura, máximo y mínimo
  escalados como el cierre: el resultado es un retorno total, con dividendos reinvertidos y
  *splits* deshechos.
* **Fracciones, no porcentajes,** y dinero en la divisa del instrumento.
* **Métricas con el calendario del mercado**, mediante `RiskMetrics`: no se duplican Sharpe,
  Sortino ni VaR.
* **La *equity* termina después de cerrar.** Una posición abierta al final se cierra al último
  cierre, y el último valor de la *equity* ya incluye esos costes. Así el retorno total y las
  métricas cuadran.

### Paridad

* **Cómo se graba.** `just record-parity` ejecuta el `simulate` de CryptoWorld (versiones
  fijadas, entorno desechable) en diez escenarios sobre las velas diarias grabadas de
  BTC/USDT. Juntos recorren todos sus caminos:
  * costes;
  * relleno a la apertura y al cierre;
  * *stops*, objetivos, *trailing* y triple barrera en ATR;
  * salida por tiempo;
  * cortos con *funding*;
  * los tres dimensionados.
* **Qué se graba.** También las entradas que recibió (señales, ATR, *funding* y convicción),
  para que el test alimente igual al motor de aquí.
* **Qué exige el test:**
  * la *equity* de cada vela a 1e-10;
  * cada operación: entrada, salida, lado, motivo, precio y *funding*;
  * los totales.
* **Una diferencia, a propósito.** El `pnl_pct` de un corto en CryptoWorld no resta la comisión
  de la venta que lo abre; su caja sí. Aquí el resultado de un corto la incluye, y el test lo
  compensa de forma explícita.

### Consecuencias

* Buenas:
  * una estrategia de CryptoWorld da aquí las mismas operaciones, comprobado en cada CI;
  * los costes de una acción española o francesa son los suyos;
  * el resultado incluye dividendos;
  * las métricas usan el calendario de su mercado;
  * el motor es puro y determinista: sirve tal cual a la validación, a los mundos nulos y al
    Laboratorio.
* Malas:
  * **Un bucle por vela en Python.** Con decenas de miles de velas sigue siendo rápido, pero
    el Laboratorio (miles de estrategias) puede necesitar compilarlo (Numba) o vectorizar los
    casos sin barreras. Se medirá en G4.
  * **El *trailing* asume que el máximo llegó antes que el mínimo.** Actualiza el mejor precio
    con el máximo de la misma vela antes de mirar su mínimo, y eso es ligeramente optimista.
    Es la convención de CryptoWorld y se mantiene por paridad. La validación de G3 dirá si
    hace falta una variante conservadora.
  * **Los dividendos van dentro del precio ajustado**, no como cobros en caja. Bien para el
    retorno; para la fiscalidad del libro (G6) harán falta como flujos.
  * **Los costes por mercado no tienen todavía valores por defecto.** Se configuran a mano; los
    perfiles por mercado (Bolsa de Madrid, Xetra, Binance…) llegan con la API.

### Confirmación

* **Paridad:** 10 escenarios y 142 operaciones idénticas a CryptoWorld.
* **Tests del motor, con cifras calculadas a mano:**
  * relleno, cierre al final y relleno al cierre;
  * comisión y deslizamiento de un viaje de ida y vuelta;
  * comisión mínima y una orden que se comería;
  * impuesto solo en las compras;
  * préstamo y *funding* de un corto;
  * *stop* antes que objetivo;
  * *trailing*, ATR y salida por tiempo;
  * cada dimensionado;
  * una posición cada vez.
* **Propiedades** sobre caminos y señales aleatorios:
  * la caja cuadra con las operaciones;
  * los costes nunca ayudan, con las mismas operaciones;
  * un largo sin apalancamiento nunca pierde más de lo que puso.
* **Dominio:**
  * validación de la configuración;
  * señales sobre exactamente las velas;
  * precios ajustados (el dividendo está en el resultado);
  * métricas con 252 o 365;
  * convicción en la vela de la señal;
  * estadísticas.

## Pros y contras de las opciones

### Un motor vectorizado nuevo

* Bueno: rápido, y natural para carteras.
* Malo:
  * las barreras dentro de la vela dependen del camino y no se vectorizan sin aproximar;
  * se perdería la paridad: las estrategias de CryptoWorld darían otras operaciones.

### Una librería

* Bueno: mucho hecho.
* Malo:
  * convenciones propias de relleno y de costes, sin paridad con CryptoWorld;
  * algunas, sin mantenimiento o sin Python 3.14;
  * el núcleo quedaría atado a ellas.

## Más información

* [Integración de CryptoWorld](../plan/integracion-cryptoworld.md), §4.7 y fase G3.
* [ADR-0034](0034-technical-indicators-in-numpy.md): indicadores y su paridad.
* Siguen en G3:
  * la API asíncrona `/api/v1/backtests` con perfiles de costes por mercado;
  * la validación anti-sobreajuste;
  * los mundos nulos;
  * el informe con veredicto;
  * la metodología.
