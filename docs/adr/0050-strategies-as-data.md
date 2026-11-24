---
status: aceptado
date: 2026-11-24
decision-makers: Javier Fernández
---

# Estrategias como datos: la gramática de CryptoWorld, validada y con paridad

## Contexto y problema

El motor de backtest de G3 ([ADR-0049](0049-backtest-engine.md)) recibe señales. Para que la API
acepte un backtest, para guardar una estrategia y para que el Laboratorio de G4 las busque,
una estrategia tiene que ser **un dato**: algo que se valida, se serializa, se compara y se
identifica, no una función de Python.

CryptoWorld ya lo resolvió con `strategy_spec`:

- bloques de entrada y salida con una a tres condiciones;
- cinco tipos de condición: umbral, cruce, estado, pendiente y patrón;
- negación y confirmación parcial «k de n»;
- dirección (largo, corto o ambos), riesgo, dimensionado y filtro de régimen;
- un compilador causal a señales y un *hash* de definición.

Sus estrategias son diccionarios sin tipo, validados con una función que devuelve `True` o
`False` sin decir por qué, y su compilador dispara durante el calentamiento sobre los valores
que `ta` inventa.

El plan situaba la gramática en G4, junto al algoritmo genético. Pero la API asíncrona de G3
ya necesita estrategias como datos, así que la mitad determinista se adelanta a G3. El
generador aleatorio, la mutación y el espejo se quedan en G4.

## Factores de decisión

* **Que una estrategia signifique lo mismo en las dos plataformas.** Las de CryptoWorld deben
  leerse igual, tener el mismo *hash* y dar las mismas señales aquí.
* **Nunca inventar datos.** Una condición sobre un indicador que aún no tiene valor no puede
  dar señal.
* **Errores que digan dónde.** Quien escribe una estrategia, a mano o desde la web, necesita
  saber qué condición está mal y por qué.
* **Tipos.** `mypy --strict` en todo el núcleo y en los tests.
* **Base para G4.** El Laboratorio compilará miles de estrategias: la gramática debe ser pura,
  determinista y sin I/O.

## Opciones consideradas

1. **Portar la gramática** a *dataclasses* congeladas en `analytics/search/`, con la forma JSON
   de CryptoWorld, y comprobarla contra su propia salida.
2. **Diccionarios validados con un esquema** (Pydantic o JSON Schema) y el compilador de
   CryptoWorld tal cual.
3. **Un lenguaje propio** (expresiones como `RSI(14) < 30 and close > SMA(200)`) con su
   analizador.

## Decisión

Opción 1.

### Dónde vive

* **`analytics/search/grammar.py`:** la gramática. `Leg`, las cinco condiciones (`Threshold`,
  `Cross`, `Compare`, `Slope`, `PatternCondition`), `Block`, `Regime` y `StrategySpec`. Cada
  una se valida al construirse.
* **`analytics/search/compiler.py`:** `compile_sides(spec, bars, sessions)` → `Sides` (las
  señales de los dos lados y la primera vela en que todo se conoce).
* **`analytics/search/classics.py`:** las siete estrategias clásicas de CryptoWorld
  (`seed_specs`), con nombre.
* **`domain/strategy.py`:** la estrategia sobre una `PriceSeries`. `strategy_signals`,
  `backtest_strategy` y `strategy_from_dict` traducen los errores a `DomainError`.
  `series.backtest_strategy(spec)` es el atajo.

### La forma JSON es la de CryptoWorld, y canónica

* `to_dict()` escribe exactamente lo que escribía CryptoWorld. Por eso
  `definition_hash` (los doce primeros dígitos del SHA-1 del JSON con claves ordenadas) es
  su `spec_hash`.
* **Canónica.** Se escriben todos los parámetros, con su tipo (una ventana es entera; un
  umbral, real), y se omite lo que no dice nada: `negate` falso, la dirección larga, un riesgo
  sin barreras o el dimensionado «todo». Así, la misma estrategia tiene siempre el mismo
  *hash*, la escriba quien la escriba, que es lo que permite al Laboratorio contar lo que ha
  probado.
* **Estricta.** Una clave desconocida es un error, no algo que se ignora.

### Qué es legal

* **La estructura de CryptoWorld:**
  * de una a tres condiciones por bloque;
  * «k de n» con `k` entre 2 y `n − 1` (en los extremos es un `O` o un `Y`, y una estrategia
    tendría dos formas);
  * los umbrales, sobre osciladores; los cruces y los estados, entre niveles de precio
    distintos;
  * los cruces no se niegan (un suceso puntual negado es casi siempre cierto);
  * un patrón negado necesita una ventana de al menos tres velas;
  * los bloques cortos, solo en «ambos».
* **El dominio de cada valor,** no el rango de búsqueda:
  * una ventana es un número entero de velas, al menos una;
  * un umbral es cualquier número finito.

  CryptoWorld rechazaba un RSI por debajo de 15 o una SMA de 250 porque sus rangos eran los
  del generador. Aquí esos rangos solo acotan lo que el generador muestrea (G4); una estrategia
  escrita a mano puede salirse de ellos.
* **Los valores del riesgo y del dimensionado** los comprueba `BacktestConfig`, el mismo que
  valida un backtest. `strategy_from_dict` lo hace al leer.
* **Los errores dicen dónde:** `exit.conditions[1].threshold: the threshold must be a finite
  number, got '30'`.

### Una condición desconocida no da señal

* Aquí un indicador vale `NaN` hasta que su ventana está completa (ADR-0034). Una condición que
  lee un `NaN` es desconocida: ni se cumple ni, negada, deja de cumplirse.
* Es lógica de Kleene en lo que importa:
  * un `O` con una condición conocida y cierta se cumple, diga lo que diga la otra;
  * un `Y` con una desconocida no se cumple.
* Un patrón que se ha producido es un hecho siempre. Que no se haya producido solo se sabe
  cuando toda su ventana ha pasado su calentamiento.
* `Sides.ready` (en el dominio, `ready_at`) es la primera vela desde la que todas las
  condiciones se conocen pase lo que pase: sus indicadores tienen valor y sus patrones han
  pasado su calentamiento. No depende de lo que hagan las velas siguientes (un test de
  propiedades lo comprueba truncando la serie). El resultado del backtest la lleva, para que
  el calentamiento no se confunda con una estrategia que no opera.

CryptoWorld negaba también lo desconocido: «RSI no está por debajo de 30» era cierto antes de
que hubiera RSI.

### Lo que lee la estrategia

* Las velas tal como cotizaron, como la ficha del activo: lo que la estrategia ve es lo que
  había en pantalla.
* El backtest opera encima con precios ajustados, así que el resultado sigue siendo un
  retorno total.
* Lo que la serie no tiene no se sustituye:
  * una estrategia que lee la apertura, sobre una serie de cierres, se rechaza;
  * un patrón de sesión, sobre velas diarias, también.

### Paridad

* **Cómo se graba.** `just record-parity` ejecuta el código de CryptoWorld sobre:
  * sus siete estrategias clásicas;
  * sesenta de su propio generador (`random_spec` en modo `auto`, con semilla fijada).

  Las sesenta incluyen las tres direcciones, los cinco tipos de condición, negaciones,
  «k de n», filtros de régimen, riesgo, dimensionado y las cuatro familias de patrones, también
  los de sesión. Se graban su JSON, su `spec_hash` y las señales de su `compile_sides` sobre
  dos casetes de Binance: diaria y horaria.
* **Qué exige el test:**
  * el mismo JSON;
  * el mismo *hash*;
  * las mismas señales desde `ready`, sobre al menos tres cuartas partes de cada serie.
* **El resultado.** Las 67 estrategias coinciden en las dos series: 23 685 señales comparadas.
  Antes de `ready`, 913 velas difieren: son señales de CryptoWorld sobre los valores que `ta`
  inventa en el calentamiento.

### Consecuencias

* Buenas:
  * la API, la web y el Laboratorio comparten un único formato de estrategia, el de
    CryptoWorld;
  * una estrategia de CryptoWorld se importa tal cual, con su *hash*: la migración de G13 no
    tiene que traducir nada;
  * los errores dicen qué condición está mal;
  * ninguna señal se dispara sobre un valor inventado;
  * los tests de propiedades comprueban, sobre estrategias aleatorias, que las señales son
    causales (truncar la serie no cambia las primeras) y que el JSON vuelve a ser la misma
    estrategia.
* Malas:
  * **Dos formas de lo mismo:** las *dataclasses* y el JSON. El JSON es la forma de
    intercambio, y `from_dict(to_dict(s)) == s` lo vigila un test de propiedades.
  * **El límite de tres condiciones por bloque** es de CryptoWorld, pensado contra el
    sobreajuste de la búsqueda. Una estrategia escrita a mano también lo tiene. Se revisará
    con el Laboratorio.
  * **El calentamiento de un patrón** para su negación se toma del catálogo (el del extremo de
    su rango) o de su ventana si es mayor: es conservador, y una negación puede tardar alguna
    vela más de lo estricto en conocerse.
