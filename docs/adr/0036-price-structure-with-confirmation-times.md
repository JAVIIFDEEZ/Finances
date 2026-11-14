---
status: aceptado
date: 2026-11-14
decision-makers: Javier Fernández
---

# Estructura de precio con su momento de confirmación

## Contexto y problema

G2 trae la estructura de precio de CryptoWorld: niveles de soporte y resistencia por
agrupación de pivotes, divergencias entre el precio y el RSI (`price_structure`) y los
niveles de Fibonacci de su ficha de confluencia (`calculate_fibonacci_levels`). CryptoWorld
devuelve diccionarios con frases en español y cifras redondeadas para la pantalla, y no dice
cuándo se supo cada cosa: un pivote necesita `k` velas posteriores para confirmarse.

## Factores de decisión

* Paridad comprobada con el código de CryptoWorld.
* Ninguna mirada al futuro escondida: lo que necesita velas posteriores lo dice.
* Datos, no frases: la web y los informes los cuentan en su idioma.
* Igual para cualquier clase de activo.

## Decisión

`analytics/structure.py` porta las definiciones con la misma aritmética:

* **Pivote:** máximo (o mínimo) que domina estrictamente las `k` velas a cada lado. Un
  empate no confirma nada. Las últimas `k` velas aún no pueden ser pivotes.
* **Niveles:** pivotes agrupados por precio con una tolerancia relativa (0,6 %). Su fuerza
  es el número de toques; cada nivel es soporte o resistencia según el lado del último
  cierre en que queda.
* **Divergencias:** los dos últimos pivotes del cierre en la ventana, contra el RSI, con un
  punto de diferencia mínima.
* **Fibonacci:** el *swing* entre el máximo y el mínimo de la ventana, medido desde el
  extremo más reciente.

Se devuelven estructuras con **posiciones**: los pivotes de cada nivel, los dos pivotes de
cada divergencia y la vela que la **confirmó** (`k` velas después del segundo), y los
extremos del *swing*. La fachada de dominio las convierte en fechas. Nada se redondea en el
núcleo; el redondeo es cosa de quien presenta.

La paridad se graba ejecutando su código (`just record-parity`) sobre cortes de las dos
casetes reales (cada 20 velas los niveles y Fibonacci, cada 3 las divergencias): 330 casos.

### Consecuencias

* Bien, porque los 330 casos coinciden con CryptoWorld dentro de su propio redondeo.
* Bien, porque los tests de propiedades exigen que cada pivote domine a sus vecinos, que un
  pivote confirmado antes de un corte se encuentre con las velas hasta el corte y que los
  niveles escalen con los precios.
* Bien, porque la pantalla puede decir cuándo se confirmó una divergencia, no solo que existe.
* Mal, porque la tolerancia fija (0,6 %) no se adapta a la volatilidad de cada activo; se
  mantiene por paridad y queda abierta una variante proporcional al ATR.

### Confirmación

* `tests/contract/test_cryptoworld_structure_parity.py`
* `tests/property/test_structure_properties.py`
* `tests/unit/analytics/test_structure.py`
