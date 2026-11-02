---
status: aceptado
date: 2026-11-02
decision-makers: Javier Fernández
---

# Informes Markdown bilingües, gráficos de informe y delegación diferida del dominio

## Contexto y problema

El taller B1-T1 (§4.5) pide que las series y las carteras tengan dos métodos:

* `.report()`, que devuelve un informe en Markdown;
* `.plots_report()`, que devuelve gráficos.

Varias decisiones previas condicionan el diseño:

* Los informes son bilingües, con español por defecto (decisión 7 del plan).
* Los gráficos se hacen con matplotlib y solo en el núcleo (decisión 22).
* El dominio no puede importar nada de presentación (ADR-0002).

Además, un informe profesional no puede limitarse a dar cifras: tiene que decir también hasta
qué punto son fiables.

## Factores de decisión

* Los métodos tienen que estar en los propios objetos (`series.report()`), como pide el
  taller.
* El dominio debe seguir puro y cargar rápido; matplotlib es opcional.
* Cada valor del informe tiene que estar tipado y comprobado por mypy, y el mismo dato debe
  dar siempre el mismo informe (determinismo).
* No puede faltar ninguna traducción.
* Nunca se fabrican cifras: si algo no se puede calcular, se muestra un guion (—).

## Opciones consideradas

* **Plantillas Jinja2**, como se planteó en el plan, frente a un **constructor de Markdown en
  Python tipado**. Se elige el constructor:
  * mypy comprueba cada valor;
  * no hay plantillas sin tipos;
  * es una dependencia menos.
* **gettext/Babel** frente a un **catálogo de pares (es, en)** en código. Se elige el
  catálogo:
  * con dos idiomas basta;
  * es imposible que falte una traducción;
  * un test comprueba que ambas versiones usan los mismos *placeholders*.
* **Funciones sueltas en `reporting`** frente a **métodos del dominio con delegación
  diferida**. Se eligen los métodos con delegación diferida, a través de un único módulo de
  entrada. Así se generaliza la excepción de ADR-0016.

## Decisión

### Uso

| Método | Devuelve |
|--------|----------|
| `PriceSeries.report(options=None, **settings)` y `Portfolio.report(...)` | `MarkdownReport`: un `str` que Jupyter muestra como Markdown y que se guarda con `.save(ruta)` |
| `PriceSeries.plots_report(...)` y `Portfolio.plots_report(...)` | `PlotsReport`: un *mapping* de figuras con nombre, que se guarda con `.save(carpeta)` y se muestra entero en Jupyter |
| `SimulationResult.plot(language=...)` | Figura de Monte Carlo, ahora también bilingüe |

* Las opciones (`ReportOptions`) se validan al construirse y se pueden pasar por nombre
  (`report(language="en", risk_free_rate=0.03)`):
  * idioma y título;
  * tipo libre de riesgo, constante o serie *point-in-time*;
  * niveles de VaR y número de caídas listadas;
  * informes de calidad ya calculados (con el calendario oficial);
  * simulación (configuración o resultado);
  * frecuencia de las correlaciones y ventana de la volatilidad móvil.

### Contenido

**Serie:**

* resumen narrado y recuento de diagnósticos;
* datos y procedencia;
* rentabilidad y riesgo, con el **intervalo de confianza del Sharpe**;
* VaR/CVaR por nivel y método;
* **episodios de caída** (máximo previo, mínimo, recuperación, duración);
* Monte Carlo opcional;
* calidad de datos;
* diagnósticos;
* metodología.

**Cartera:** además de lo anterior,

* composición y concentración;
* **rendimiento comparado sobre el periodo común**;
* correlaciones;
* contribución al riesgo (Euler) con el ratio de diversificación;
* rebalanceo y rotación;
* calendarios y antigüedad de las valoraciones.

### Diagnósticos

Cada regla devuelve gravedad, mensaje con las cifras y recomendación:

| Regla | Condición |
|-------|-----------|
| Calidad | Incidencias de calidad de gravedad advertencia o crítica (ADR-0015) |
| Ajuste de precios | Acción, ETF o fondo sin precio ajustado por dividendos |
| Datos antiguos | La serie termina mucho antes de su descarga (7 días en diario, 45 en mensual…) |
| Sharpe incierto | El intervalo de confianza del Sharpe al 95 % incluye el cero (Mertens, 2002) |
| No normalidad | p-valor de Jarque-Bera < 0,01: el VaR normal infravalora las colas |
| Cola escasa | Menos de 10 observaciones más allá del VaR del mayor nivel |
| Tipo libre de riesgo 0 % | Sharpe y Sortino calculados sin tipo libre de riesgo |
| Histórico truncado | Un activo empieza más de 90 días después que otro |
| Concentración de riesgo | Un activo aporta más del 50 % del riesgo y más de 1,5 veces su peso |
| Cobertura | Contribución al riesgo negativa |
| Correlación alta | Pares por encima de 0,9 |
| Cierres no sincrónicos | Correlaciones semanales automáticas (ver abajo) |
| Valoraciones antiguas | Precios de más de 5 periodos de antigüedad |
| Rotación y apalancamiento | Rotación anual > 100 % (sin costes) o exposición bruta > 100 % |
| Deriva histórica | La simulación usa la media histórica: se informa de su error estándar |
| VaR simulado impreciso | El intervalo del VaR supera el 10 % de su valor |

En la cartera, si el mismo hallazgo afecta a varios activos, aparece en una sola fila con
todos ellos.

### Correlaciones con cierres no sincrónicos

* Si los activos cierran en instantes distintos (distinto desfase UTC) o tienen calendarios
  distintos (cripto 24/7 frente a bolsa), correlaciones y contribuciones usan **retornos
  semanales**, siempre que haya al menos 26 semanas de historia común.
* Si no hay tanta historia, se usa la frecuencia original y se avisa.
* Madrid y Fráncfort tienen el mismo desfase, así que se consideran sincrónicos.

### Gráficos

| Objeto | Gráficos |
|--------|----------|
| Serie | Precio, caída desde máximos, distribución de retornos (con la normal ajustada y el VaR) y volatilidad móvil |
| Cartera | Evolución en base 100 frente a cada activo, caída desde máximos, mapa de correlaciones, peso frente a contribución al riesgo y pesos efectivos frente a objetivos |

Ambos añaden la simulación si se pide. Reglas de diseño (paleta validada de ADR-0016):

* un único eje y por gráfico;
* colores categóricos en orden fijo por activo; a partir del noveno se agrupan en «Otros»;
* correlaciones con una rampa divergente rojo ↔ azul y punto medio gris, con las dos ramas a
  la misma luminosidad OKLab (0,43 y 0,72);
* pesos efectivos como líneas, junto a su objetivo, en lugar de áreas apiladas saturadas;
* fechas en formato numérico, válido en los dos idiomas;
* figuras creadas sin pyplot: no se muestran dos veces en Jupyter ni dependen de estado
  global.

### Arquitectura

* El dominio llama a `investinglab.reporting.entrypoints` **dentro** de cada método. Es la
  única excepción a las capas: tres aristas declaradas en `ignore_imports`, que sustituyen a
  la de ADR-0016.
* Importar `investinglab.domain` no carga ni `reporting` ni matplotlib (hay un test).
* `report()` funciona sin matplotlib. Los gráficos, sin el *extra* `plots`, lanzan un
  `ImportError` que explica cómo instalarlo.
* seaborn sale del *extra* `plots`, porque no se usaba.
* Las incidencias de calidad incluyen `details` (cifras estructuradas) para poder
  traducirlas.
* El informe no incluye la fecha de generación, para que sea determinista. Solo lleva la
  versión de InvestingLab.

### Correcciones incluidas

* **Último periodo parcial:** en frecuencias de calendario, la última barra puede cubrir un
  periodo en curso (el mes actual hasta hoy). Antes, remuestrear a mensual una serie que
  terminaba a mitad de mes fallaba la validación.
* **Pattern matching:** `PriceSeries`, `EconomicSeries` y `FxRates` declaran
  `__match_args__` sin el `InitVar` `data`. Antes, el *pattern matching* y los informes de
  Hypothesis intentaban leer un atributo que no existe.

## Consecuencias

* Positiva: cubre §4.5 del taller con informes que explican sus propias limitaciones.
* Positiva: los mismos datos dan siempre el mismo informe, en los dos idiomas.
* Positiva: los tests de propiedades comprueban que se puede escribir un informe de cualquier
  serie válida; esto destapó los plurales del tipo «1 activos».
* Negativa: cada mensaje nuevo hay que escribirlo en los dos idiomas (lo exige el diseño).
* Negativa: el formato de números cubre español e inglés; un tercer idioma requeriría Babel y
  un ADR.
* Pendiente:
  * exportación a HTML/PDF y endpoint `/reports` (F6);
  * umbrales de los diagnósticos configurables;
  * tamaño de las figuras adaptado a informes largos.

## Confirmación

* `test_i18n.py`: los mismos *placeholders* en los dos idiomas y el formato de números y
  fechas.
* `test_markdown.py`, `test_options.py`.
* `test_diagnostics.py`: cada regla se activa y se calla cuando debe.
* `test_series_report.py` y `test_portfolio_report.py`:
  * secciones y orden;
  * cifras iguales a las del dominio;
  * correlaciones semanales;
  * filas fusionadas.
* `test_charts.py`: claves, títulos, agrupación en «Otros», escala logarítmica y que no se
  usa pyplot.
* `test_entrypoints.py`: dominio sin `reporting` ni matplotlib, y Markdown sin matplotlib.
* `test_reporting_properties.py`.

## Más información

* Mertens, E. (2002). *Comments on Variance of the IID estimator in Lo (2002)*. Documento de
  trabajo, Universidad de Basilea.
* Lo, A. W. (2002). The Statistics of Sharpe Ratios. *Financial Analysts Journal*, 58(4).
* Jarque, C. M. y Bera, A. K. (1980). Efficient tests for normality, homoscedasticity and
  serial independence of regression residuals. *Economics Letters*, 6(3).
