---
status: aceptado
date: 2026-11-10
decision-makers: Javier Fernández
---

# Web institucional: Next.js, cliente tipado desde el contrato OpenAPI y gráficos con paleta validada

## Contexto y problema

Las fases F8/F9 piden la interfaz de la plataforma: visión general, explorador de mercados,
constructor y análisis de carteras, simulador Monte Carlo, optimización, planificación y
módulos del máster, con aspecto de terminal financiero, en español e inglés y accesible.
La API sin estado ([ADR-0027](0027-stateless-analytics-api.md)) ya expone todo el núcleo.
Hay que decidir cómo se construye la web para que sea profesional, mantenible y fiel a las
reglas de datos.

## Factores de decisión

* Un único contrato entre API y web, verificado en CI (sin tipos escritos a mano).
* Nada inventado también en pantalla: cifras indefinidas como «—», no como 0.
* Gráficos legibles, accesibles y coherentes en tema claro y oscuro.
* Despliegue simple: un solo origen para el navegador.
* Pruebas de extremo a extremo reproducibles, sin red ni datos de mercado reales.

## Opciones consideradas

* Cliente: `orval` (genera *hooks*) o `openapi-typescript` + `openapi-fetch` (solo tipos).
* Gráficos: Lightweight Charts + ECharts (como decía el plan) o solo ECharts.
* Estado: llamadas al servidor (Server Components) o TanStack Query en el cliente.

## Decisión

* **Next.js 16 (App Router), React 19, TypeScript estricto** (`noUncheckedIndexedAccess`),
  Tailwind CSS 4 con *tokens* en variables CSS, en `apps/web` (pnpm).
* **Contrato.** `apps/api/openapi.json` (versionado) genera `src/lib/api/schema.d.ts` con
  `openapi-typescript`; las llamadas usan `openapi-fetch`. La CI regenera los tipos y falla
  si cambian. Se prefiere a `orval` porque genera solo tipos y deja los *hooks* a la vista
  (`src/lib/api/queries.ts`), sin código generado opaco.
* **Un solo origen.** Next.js reenvía `/api/v1/*` y `/health/*` a la API, así que no hay CORS
  en el navegador, basta un puerto para la vista previa y el *proxy* admite 120 s para
  fuentes lentas (el portal del BCE).
* **Datos en el cliente con TanStack Query**, cacheados por petición. Mientras llega un
  resultado nuevo se mantiene el anterior atenuado: sin parpadeos ni saltos de diseño.
* **Errores.** Los Problem Details se traducen a mensajes accionables y muestran el id de
  la petición.
* **Gráficos con ECharts** (una sola librería: velas, líneas, abanicos, histogramas, mapas de
  calor y dispersión), siguiendo las reglas de visualización:
  * paleta categórica de 8 colores validada con el validador de la guía de visualización en
    ambos temas (los tres primeros, también por todos los pares);
  * líneas de 2 px y áreas al 10 %;
  * rejillas finas y continuas;
  * *tooltip* con todas las series;
  * leyenda a partir de dos series y etiquetas al final solo si no chocan;
  * colores ligados a la entidad, no al orden;
  * correlación divergente azul-gris-rojo;
  * velas huecas al subir y rellenas al bajar, para no depender solo del color;
  * etiquetas de los ejes en el idioma de la interfaz;
  * cada gráfico con su tabla o lista de cifras al lado.
* **Idioma y tema** en *cookies*, para que el servidor pinte la primera respuesta ya
  correcta, sin destellos. Español por defecto y tema oscuro de terminal.
* **Cartera de trabajo** compartida por las pantallas (zustand persistido en el navegador),
  validada en vivo con las mismas reglas que `weight_problems()` del dominio (zod). Las
  carteras guardadas en servidor llegan con F6b.
* **Planificación prudente.** Por defecto, rentabilidad supuesta del 5 % anual con la
  volatilidad histórica, no la deriva de los últimos años proyectada décadas. La API admite
  `expected_return` en `POST /plans`.
* **Pruebas.**
  * Vitest para la lógica: formatos, validación, fechas y errores.
  * Playwright de extremo a extremo con la API real en modo sin red sobre ficheros
    **sintéticos** generados por `e2e/synthetic_data.py`, contra la *build* de producción.
  * Ambas en el *workflow* `Web` de la CI.

### Consecuencias

* Positiva: un cambio incompatible de la API rompe la CI de la web, no la pantalla.
* Positiva: aspecto coherente, accesible y bilingüe en todas las pantallas.
* Negativa: velas con ECharts en lugar de Lightweight Charts. Basta para series diarias;
  si llega el *trading* intradía en tiempo real, se reconsiderará.
* Negativa: sin autenticación (F7), la web y la API deben servirse solo en local.

### Confirmación

* `apps/web/src/lib/__tests__/` (Vitest) y `apps/web/e2e/app.spec.ts` (Playwright): búsqueda
  ⌘K, explorador, comparación, validación en vivo y análisis de cartera, Monte Carlo,
  optimización con «usar estos pesos», plan de ahorro, idioma y tema persistentes.
* *Workflow* `.github/workflows/web.yml`: tipos al día, `lint`, `typecheck`, tests, *build* y
  E2E.

## Pros y contras de las opciones

### `orval`

* Positivo: *hooks* de TanStack Query generados.
* Negativo: mucho código generado y menos control sobre claves y caché.

### Lightweight Charts + ECharts

* Positivo: velas de nivel TradingView.
* Negativo: dos librerías, dos temas y dos modelos de interacción.

### Server Components para los datos

* Positivo: menos JavaScript en el cliente.
* Negativo: los análisis son interactivos (parámetros, recálculo); la caché de cliente y el
  «mantener el marco» encajan mejor.

## Más información

* Plan maestro, sección 11 (frontend) y fases F8–F9.
* Guía: [Cómo ver la web](../guide/web.md).
