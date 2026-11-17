---
status: aceptado
date: 2026-11-16
decision-makers: Javier Fernández
---

# Ficha de activo: pilares por clase de activo, sin veredicto fusionado

## Contexto y problema

La *Confluence Card* de CryptoWorld reúne en una ficha la tendencia de fondo, los soportes y
resistencias, Fibonacci y el resumen de indicadores, y termina en un veredicto con «nivel de
confianza». Su fusión 360° suma además ML, on-chain y noticias con pesos aprendidos del
historial de aciertos. G2 tiene que llevarla a cualquier instrumento (D8): la misma ficha para
`SAN.MC`, `^GSPC`, `EURUSD=X` y `BTC/USDT`.

Dos cosas no se pueden portar tal cual:

* Una acción no tiene *funding* ni on-chain; una cripto no tiene fundamentales. La ficha tiene
  que saber qué evidencias tiene cada clase de activo y decir cuáles no tiene.
* Un veredicto que fusiona pilares necesita pesos. Los de CryptoWorld salen de un historial
  de aciertos que pide semanas de muestra, y su interfaz no enseña cuánta hay detrás de cada
  peso. Una «confianza» que no es una probabilidad no debe mostrarse como tal.

## Factores de decisión

* Describir, no recomendar: la ficha es una lectura, no un consejo.
* Nunca inventar: un pilar sin datos lo dice; una cifra que no se puede calcular es `None`.
* Que añadir un pilar (macro, fundamentales, ML en G4) sea añadir una entrada y su lector.
* Datos y no frases en la API, para que cada interfaz los diga en su idioma.

## Opciones consideradas

1. Portar la ficha de CryptoWorld con su veredicto y su confianza.
2. Un registro de pilares por clase de activo, cada uno con sus cifras, y sin fusionarlos.
3. Fusionar con pesos fijos (iguales) hasta tener pesos aprendidos.

## Decisión

Opción 2 (`domain/card.py`, `tk.card`, `GET /api/v1/market/card`).

* **Registro** `PILLARS`: cada `PillarSpec` dice su pilar, a qué clases de activo se aplica
  (`applies_to`) y si es **direccional**. Hoy: técnico (todos), riesgo (todos), derivados
  (cripto) y calidad de datos (todos). Una ficha trae los pilares de su clase en ese orden y
  nombra los que no tiene (`not_applicable`).
* **Técnico**, el único direccional: su *score* en [−1, 1] es la alineación de los marcos
  diario, semanal y mensual ([ADR-0038](0038-signal-panel-and-timeframe-confluence.md)), con
  el veredicto, el acuerdo, la tendencia de fondo, las reglas al alza y a la baja y la
  distancia al soporte y la resistencia más cercanos.
* **Riesgo**: volatilidad anualizada, máxima caída, caída actual, VaR 95 % diario y
  rentabilidad, sobre tres años de velas diarias. Describe; no tiene *score*.
* **Derivados**: el *funding* del perpetuo lineal del par (`BTC/USDT` → `BTC/USDT:USDT`) en
  los últimos 90 días: el último y el medio anualizados y la parte de pagos positivos. Dice
  quién paga por mantener la posición, no hacia dónde va el precio. Un símbolo que no nombra
  su moneda de cotización (`BTC-USD`) no dice cuál es su perpetuo: el pilar queda sin leer.
* **Calidad de datos**: el informe de calidad de las mismas velas que leen los demás.
* Cada pilar es una lista de `Fact` (clave, valor, unidad: `ratio`, `number`, `count`,
  `code`, `date`). La web elige las palabras y el formato.
* Un pilar que se aplica pero no se puede leer va con `issue = no_data`; el resto se lee
  igual. Solo falla la ficha entera si no hay velas diarias.
* **No hay veredicto global.** Los pesos entre pilares se aprenderán en G4 a partir de
  lecturas resueltas, con su muestra y su intervalo a la vista; hasta entonces cada pilar
  dice lo suyo.

### Consecuencias

* Buenas: la misma ficha para cualquier clase de activo; un pilar nuevo (macro, fundamentales,
  ML) es una entrada del registro y su lector; la API no lleva frases.
* Malas: sin veredicto, la ficha pide leer cuatro bloques en lugar de una palabra. Es a
  propósito: una palabra sin pesos validados daría una precisión que no hay.
* La ficha repite cálculos que ya hacen otros paneles de la pantalla (confluencia, calidad);
  la caché de series evita repetir las descargas.

### Confirmación

Tests de dominio (`test_card.py`) con series y *funding* sintéticos: los pilares de cada clase,
el *score* técnico igual a la alineación, cifras sin `NaN`, un pilar sin datos. Tests del
Toolkit con proveedores falsos (una cripto con su perpetuo, un par sin perpetuo, un activo
joven) y de la API. Prueba de extremo a extremo con una acción y una cripto sintéticas.

## Pros y contras de las opciones

### Portar el veredicto con confianza

* Bueno: una sola palabra que leer.
* Malo: la confianza no es una probabilidad, y los pesos no tienen muestra validada.

### Pesos iguales hasta tener los aprendidos

* Bueno: un número único desde hoy.
* Malo: suma cosas en escalas distintas (una alineación de reglas y un *funding*) y el
  número parecería una medida que no es.

## Más información

* [ADR-0038](0038-signal-panel-and-timeframe-confluence.md): la confluencia que lee el pilar técnico.
* [ADR-0031](0031-flow-holding-rates-and-universes.md): el *funding* de los perpetuos como tipo de mantenimiento.
* Pendiente: pilar macro para acciones e índices, fundamentales (F11), ML y pesos aprendidos
  con su muestra (G4), y la ficha como pantalla propia por instrumento.
