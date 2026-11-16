---
status: aceptado
date: 2026-11-16
decision-makers: Javier Fernández
---

# Espacio de gráficos de precio: paneles sobre las mismas velas

## Contexto y problema

La pantalla de mercados dibujaba el precio en un gráfico y los osciladores en otro, varias
tarjetas más abajo. Para leer un RSI de 28 había que buscar a ojo, en otro eje temporal, qué
hacía el precio ese día. Además:

* El eje de precios estaba a la izquierda, lejos de la última vela, que es la que se mira.
* El volumen y las velas tenían márgenes distintos (cada rejilla se ajustaba a sus propias
  cifras) y no quedaban una sobre otra.
* Un cuadro flotante tapaba las velas que se estaban leyendo.
* Añadir una media reiniciaba el zoom.
* No había escala logarítmica, sin la cual una serie larga o una cripto solo enseñan su
  último tramo.

## Factores de decisión

* Un único cursor y un único eje temporal para todo lo que se calcula sobre las mismas velas.
* Nunca inventar: un mercado cerrado no es un tramo plano ni un hueco que rellenar.
* Reglas de visualización del proyecto: color ligado a la entidad, dirección nunca solo por
  color, el texto no lleva el color de la serie, cifras siempre también fuera del gráfico.
* Móvil: 390 px sin desplazamiento lateral, controles táctiles.

## Opciones consideradas

1. Mantener gráficos separados y enlazar sus cursores.
2. Cambiar ECharts por una librería de gráficos financieros (KLineChart, lightweight-charts).
3. Un solo gráfico de ECharts con paneles apilados, y lo que ECharts no da, hecho aparte en
   funciones puras con tests.

## Decisión

Opción 3. `PriceChart` (`src/components/charts/price.tsx`) es un único lienzo con paneles
apilados: precio, volumen y los osciladores que se elijan. `PriceWorkspace`
(`src/components/markets/workspace.tsx`) guarda lo que el lector elige dibujar.

* **Eje temporal por velas, no por calendario.** Cada vela ocupa un hueco; un fin de semana o
  un festivo no ocupa ninguno, porque ahí no se negoció nada. Las marcas del eje son el
  primer hueco de cada día, semana, mes, trimestre o año, según quepa en lo que hay a la
  vista (`tickUnit`), y se recalculan al ampliar.
* **Todos los paneles comparten margen.** El eje de valores va a la derecha con un ancho
  fijo, el de la cifra más larga: las velas, el volumen y los osciladores quedan en vertical.
* **Lectura fija en lugar de cuadro flotante.** Sobre el gráfico se lee la vela bajo el
  cursor (apertura, máximo, mínimo, cierre, variación frente al cierre anterior, las líneas
  dibujadas y los patrones que completa); sin cursor, la última. Cada panel dice qué es y su
  valor en esa vela. Hace también de leyenda.
* **Último precio en el eje**, con una línea de puntos que cruza el panel.
* **Escala logarítmica propia.** El eje logarítmico de ECharts solo marca potencias de la
  base: entre 30 y 50 no pone ninguna marca. Se dibuja `log10(precio)` en un eje lineal y las
  marcas son precios redondos (`logTicks`: 1-2-5 por década, o pasos iguales si el rango no
  llega a doblarse), recalculados para lo que hay a la vista.
* **El zoom sobrevive a un cambio de opción** mientras las velas sean las mismas (`zoomKey`).
  Hay una barra de rango bajo el gráfico, arrastre para desplazar y Ctrl + rueda para
  ampliar; la rueda sola sigue desplazando la página.
* **Osciladores con su escala.** Los acotados (RSI, estocástico, MFI) conservan 0–100; su
  zona convencional se sombrea y sus cotas son las únicas marcas del eje. El MACD dibuja su
  histograma (línea menos señal, `spread`) tras las dos líneas.
* El volumen se tiñe por la dirección de su vela; la vela dice lo mismo con su forma (hueca
  si sube, llena si baja).

En los demás gráficos: el volumen por vela son barras y no una línea (una línea une importes
que no forman un camino), cada línea lleva su nombre al final mientras quepan (se separan con
`spreadLabels` si dos finales coinciden), la mayor caída se nombra en su punto y la diagonal
de la matriz de correlación queda fuera de la escala de color (un activo consigo mismo es 1
por definición; lo que se mira son los pares).

### Consecuencias

* Buenas: precio, volumen y osciladores se leen con un cursor; el gráfico aguanta de un mes a
  veinte años y de 0,86 a 100 000; lo que decide marcas y distribución son funciones puras
  (`src/lib/util/chart.ts`) con tests de Vitest.
* Malas: la escala logarítmica y las marcas del eje temporal son código propio que mantener;
  `PriceChart` conoce detalles de ECharts (`customValues`, `updateAxisPointer`) que una
  subida de versión mayor puede mover. El test de extremo a extremo del espacio de trabajo
  cubre el cursor, la escala y los paneles.
* El gráfico del oscilador sale de la tarjeta de análisis técnico, que queda como tabla de
  los indicadores por familia.

### Confirmación

Tests de Vitest de `src/lib/util/chart.ts` (distribución de paneles, marcas del eje temporal,
marcas lineales y logarítmicas, separación de nombres) y el test de extremo a extremo «the
price workspace», que mueve el cursor, cambia la escala y el tipo y quita un panel. Revisado
con capturas en escritorio, a 390 px y en los dos temas.

## Pros y contras de las opciones

### Gráficos separados con cursores enlazados

* Bueno: el cambio más pequeño.
* Malo: dos ejes temporales que hay que mantener iguales, y los paneles siguen lejos.

### Otra librería de gráficos financieros

* Bueno: velas, escala logarítmica y cursor vienen hechos.
* Malo: dos librerías de gráficos con dos temas y dos formas de accesibilidad; el resto de la
  web (abanicos, fronteras, mapas de calor) seguiría en ECharts.

## Más información

* [ADR-0028](0028-institutional-web-app.md): la web y sus reglas de visualización.
* [ADR-0034](0034-technical-indicators-in-numpy.md) y
  [ADR-0037](0037-conventional-indicator-readings.md): los indicadores y sus zonas.
* Deuda: guardar por lector lo que elige dibujar; marcas de hora en velas intradía; dibujo a
  mano (líneas de tendencia) si llega a hacer falta.
