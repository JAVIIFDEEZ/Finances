# CryptoWorld → Finances (InvestingLab): funcionalidades, mejoras y plan para elevar Finances

**Fecha:** 11 de noviembre de 2026
**Repositorios analizados (clon limpio, lectura de código):**

| Proyecto | Rama | Commit | Versión |
|---|---|---|---|
| CryptoWorld (`JAVIIFDEEZ/CryptoWorld`) | `develop` | `28b17ff` (2-oct-2026) | 1.346.1 |
| Finances / InvestingLab (`JAVIIFDEEZ/Finances`) | `development` | `8712760` (PR #22, nov-2026) | pre-`v0.1.0` |

**Material cruzado:** `info/Motor_Cuantitativo.md` e `info/Auditoria_Institucional.md` de CryptoWorld, las auditorías internas de agosto y octubre de 2026 (test de hipótesis nula, edge/carry/fragilidad y orderflow) y `docs/plan/plan-maestro.md` + los 28 ADR de Finances.

**Qué no se hizo:** no se ejecutaron las suites de tests de ninguno de los dos repos (CryptoWorld necesita PostgreSQL; Finances necesita `uv` y Python 3.14) ni se consultó el estado de GitHub Actions. Las cifras de tests son recuentos de funciones `test_` en el código.

**Relación con el plan maestro:** este documento detalla la sección 9 del [plan maestro](plan-maestro.md) y sustituye a su fase F12. Los defectos que CryptoWorld tenga abiertos no se listan aquí (este repositorio es público): cuando uno condiciona el diseño, aparece como requisito de la pieza correspondiente en «Al llevarlo a Finances».

**Índice:** 0 Decisiones · 1 Resumen ejecutivo · 2 Los dos proyectos lado a lado · 3 Cómo leer el inventario · 4 Inventario funcional de CryptoWorld (19 módulos) · 5 Inventario de Finances · 6 Arquitectura destino · 7 Mapa de correspondencia módulo a módulo · 8 Plan por fases G0-G13 · 9 Matriz de paridad · 10 Decisiones abiertas · 11 Riesgos, regulación y licencias · 12 Prompts para Claude Code · 13 Cambios en la documentación de Finances

---

## 0. Decisiones fijadas

| # | Pregunta | Tu respuesta | Cómo se aplica en el documento |
|---|---|---|---|
| D1 | Ejecución con dinero real | **Paper + real, solo en tu cuenta** | Se porta el OMS a Finances como proceso aparte (`apps/trader`), **apagado por defecto**, de un único propietario, y con el camino de la orden rediseñado con las garantías de §4.11. Nunca se ejecuta por cuenta de terceros. |
| D2 | Generador genético + ML | **"Impórtalo como creas que es mejor y mejóralo"** | Se porta como **Laboratorio de investigación** con el banco de mundos nulos como puerta obligatoria, el registro de experimentos como fuente del N de la deflación y un reenfoque de objetivos hacia volatilidad y carry, además de dirección (§4.8, §4.9 y fase G4). |
| D3 | Piezas comerciales (landing SEO, academia, registro público, push, monetización) | **Personal, preparado para SaaS** | El núcleo y la API se diseñan multiusuario desde el primer modelo de datos (`owner_id` en todo), pero lo comercial va a una fase final opcional (G12) con sus restricciones de licencia de datos y regulatorias. |
| D4 | Formato | **Markdown en tu carpeta + Proyecto** | Este fichero. |
| D5 | Publicación del documento (11-nov-2026) | **En el repositorio, sin los fallos abiertos de CryptoWorld** | Este fichero: los defectos abiertos de CryptoWorld quedan como requisitos de diseño para Finances, sin cifras, ficheros ni líneas. |
| D6 | Orden de trabajo (11-nov-2026) | **Intercalado** | Persistencia (G0a) → G1 → G2 → trabajos en segundo plano (G0b) → G3 → G4 → G5 → acceso con usuario y contenedores (G0c) → G6 en adelante. Detalle en §8. |
| D8 | Alcance (12-nov-2026) | **Todo, para cualquier clase de activo** | Cada pieza que se porta se diseña para acciones, índices, ETF, divisas, materias primas, renta fija y cripto a la vez; no se entrega una versión «solo cripto» para generalizarla después. Lo que solo existe en un mercado (funding, on-chain, opciones de Deribit) queda tras un puerto que declara a qué clases de activo aplica, y cada pantalla dice por qué no hay dato cuando no aplica. |
| D7 | Decisiones abiertas de §10 (11-nov-2026) | **Aplicar la recomendación, con ADR** | Cada decisión técnica se cierra con la recomendación de §10 y su ADR al empezar la fase que la necesita. Se consultan antes las que tocan dinero real, claves, despliegue o el archivo de CryptoWorld (§10.4, §10.7, §10.8 y §10.10). |

---

## 1. Resumen ejecutivo

1. **Los dos proyectos son complementarios, no redundantes.** CryptoWorld tiene la **amplitud funcional y el rigor estadístico** (60 módulos de servicios de dominio, 97 casos de uso, 127 rutas de API, backtest con costes y funding, CPCV, DSR con el N real, PBO, PSR/MinTRL, mundos nulos, HAR, carry, factores, opciones, on-chain forense, paper trading y ejecución real). Finances tiene la **calidad de ingeniería y el modelo de datos multiactivo** (dominio inmutable y validado, *point-in-time*, divisas *as-of*, calendarios oficiales, `mypy --strict`, `import-linter`, tests de propiedades, contrato OpenAPI, 28 ADR). Elevar Finances significa traer la amplitud de CryptoWorld **sin perder** esa calidad.

2. **Finances no puede absorber hoy casi nada con estado.** Su API es deliberadamente sin estado (ADR-0027): no hay base de datos, ni autenticación, ni cola de trabajos, ni tiempo real. Paper trading, alertas, carteras guardadas, registro de experimentos, generador nocturno y ejecución real dependen de las fases F6 (persistencia), F7 (auth) y F13 (jobs) del plan maestro. **Esas tres fases son el camino crítico de toda la integración** (fase G0 de este documento).

3. **Lo que sí se puede portar ya, sin estado,** es lo más valioso: análisis técnico generalizado a cualquier `PriceSeries`, motor de backtest, suite de validación anti-sobreajuste, volatilidad (HAR), estudio de eventos, estacionalidad, rupturas estructurales, factores y significancia. Son funciones puras en CryptoWorld y encajan en `analytics/` y `domain/` de Finances casi uno a uno.

4. **Hay solapamiento, y en él gana Finances.** HRP, VaR/CVaR, contribución al riesgo (Euler), correlaciones, calidad de datos, divisas y Monte Carlo existen en los dos. Las versiones de Finances están mejor validadas (Cornish-Fisher, intervalos de confianza, reparación PSD, Ledoit-Wolf, calendario unión). **No se porta el código de CryptoWorld de esas piezas**: se porta lo que le falta a Finances (estrés histórico, atribución por factores, PSR/MinTRL) y se borra el duplicado.

5. **El plan maestro de Finances infravalora CryptoWorld.** Su sección 9 describe «unas 25k líneas» y «un motor de análisis técnico de unas 900 líneas». El `develop` real tiene unas 77k líneas de backend (49k de código y 28k de tests) y 36k de frontend, y la parte más valiosa (todo lo de la v1.298 a la v1.346) ni siquiera aparece. La fase F12 «Integración CryptoWorld» es en realidad **un programa de 10-12 fases**, no una.

6. **Una parte del mejor trabajo de CryptoWorld no tiene ni API ni pantalla.** Carry, factores, estacionalidad, calendario y estudio de eventos, vigilancia de correlaciones, superficie de opciones y `edge_test` (v1.328-1.346) existen solo como comandos de `manage.py`. Al portarlos a Finances deben convertirse en servicios con endpoint y pantalla: es la mejora más barata de todo el documento.

7. **Generalizar a multiactivo no es copiar.** Muchas piezas de CryptoWorld asumen cripto: 365 días, mercado 24/7, sin dividendos, sin *splits*, sin divisa distinta de USD/USDT, funding en vez de coste de préstamo, universo sin quiebras declaradas. Cada pieza portada tiene que pasar por el `Instrument`, el `TradingCalendar`, el `PriceAdjustment` y la divisa base de Finances. El documento señala, pieza a pieza, qué cambia.

8. **El dinero real se porta, pero detrás de cuatro llaves.** (1) Patrón *outbox* con `clientOrderId`, posición movida solo por lo ejecutado y estado `unknown` reconciliable; (2) `Decimal` en todo lo que es dinero; (3) puerta PSR ≥ 0,95 + MinTRL + incubación ya implementada en la 1.346; (4) proceso `apps/trader` separado con *feature flag* apagado por defecto y un único propietario fijado en la configuración. En modo SaaS, la ejecución queda **desactivada en código**, no por configuración (perímetro CASP de MiCA).

9. **Orden recomendado (detalle en §8):** G0 plataforma con estado → G1 datos cripto y derivados → G2 análisis técnico multiactivo → G3 backtest y validación → G4 Laboratorio (generador + ML mejorados) → G5 volatilidad, fragilidad y carry → G6 carteras de usuario y riesgo → G7 paper + ejecución propia → G8 alertas y tiempo real → G9 on-chain → G10 noticias → G11 orderflow → G12 preparado para SaaS → G13 retirada de CryptoWorld. Calculo unos 6-8 meses a 25-30 h/semana hasta la paridad en lo esencial (G0-G8) y 10-13 meses con todo; es una estimación, no una medición.

---

## 2. Los dos proyectos, lado a lado

### 2.1 Cifras

| | CryptoWorld `develop` 1.346.1 | Finances `development` |
|---|---|---|
| Propósito | Análisis cuantitativo de cripto, TFG escalado a producto | Plataforma financiera personal multiactivo, módulo a módulo con el Máster MIAX |
| Backend | Django 5 + DRF + SimpleJWT + Celery/Redis + Channels (ASGI) | Núcleo Python puro (`packages/investinglab`) + FastAPI sin estado (`apps/api`) |
| Persistencia | PostgreSQL 16, 32 modelos ORM | Ninguna (caché Parquet + DuckDB para series) |
| Frontend | React 18 + Vite + TS 5.5 + Tailwind 3 + KLineChart v9 + recharts + three.js + TanStack Query + i18next | Next.js 16 + React 19 + TS estricto + Tailwind 4 + ECharts 6 + TanStack Query + zustand + zod + `openapi-fetch` |
| Código backend | ~48.900 líneas (sin migraciones ni tests) | Núcleo ~15.600 + API ~2.400 |
| Tests backend | ~27.700 líneas, **2.121** funciones `test_` | Núcleo ~11.200 + API ~870 líneas, **787** funciones `test_` |
| Frontend | ~35.600 líneas, 25 páginas, 99 componentes, 48 ficheros de test | ~6.900 líneas, 7 pantallas, Vitest + Playwright |
| Umbral de cobertura | 75 % | 90 % |
| Tipado | Sin `mypy` | `mypy --strict` también en tests |
| Reglas de capas | Clean Architecture por convención | Hexagonal **verificada en CI** con `import-linter` |
| Decisiones registradas | Mensajes de commit largos y `info/Motor_Cuantitativo.md` | 28 ADR (MADR 4) |
| Proveedores de datos | Binance, KuCoin, CoinGecko, CryptoCompare, alternative.me, Blockchain.com, Blockchair, Blockscout, Deribit, ccxt | Yahoo Finance (`chart`), BCE (SDMX), ficheros locales; previstos FRED/ALFRED y Alpha Vantage |
| Tiempo real | WebSockets (Channels): precios y notificaciones | Ninguno (previsto SSE en F13) |
| Trabajos asíncronos | 34 tareas Celery, 24 en el *beat* | Ninguno (previsto en F13) |
| Auth | Registro, verificación de email, reset, cambio de email, 2FA TOTP + códigos de recuperación, JWT en `localStorage` | Ninguna (previsto Better Auth + passkeys + TOTP + JWKS en F7) |
| Despliegue | Railway (ASGI) + Vercel | Local (`just dev`); previsto Docker Compose y nube en F10/F14 |
| Seguridad de la cadena de suministro | `pip-audit` y `npm audit` en CI | Dependabot, `detect-secrets`, *pre-commit*; versiones al día |

### 2.2 Qué hace bien cada uno

**Finances es mejor en:**

- **Modelo de dominio.** `PriceSeries`, `Portfolio`, `AlignedPanel`, `EconomicSeries` bitemporal, `Instrument` con `AssetClass` y `Exchange`, `Currency` ISO 4217 con unidades menores (GBp), `Frequency` de 1 minuto a 1 año. Todo inmutable (`frozen=True, slots=True`), validado en `__post_init__` y con arrays de solo lectura.
- **Reglas de datos.** Nunca se inventan datos: sin `bfill`, sin interpolación, festivos como hueco, valoración con el último precio observado y su antigüedad, divisas *as-of*, macro unida por fecha de publicación.
- **Multiactivo de verdad.** Calendarios oficiales por mercado (`exchange_calendars`), anualización según calendario y frecuencia (sin 252 cableado), FX con el BCE y triangulación, tipo libre de riesgo *point-in-time* (€STR y tipo de depósito del BCE).
- **Analítica de cartera.** Optimización (mínima varianza, máximo Sharpe, rentabilidad objetivo, paridad de riesgo, HRP, inversa de la volatilidad, Black-Litterman, frontera eficiente), Monte Carlo multivariante (GBM, t de Student, *bootstrap* estacionario, antitéticas, Ledoit-Wolf, rebalanceo dentro de la trayectoria, VaR con IC) y planes de ahorro.
- **Ingeniería.** Proveedores tras puertos con `ProviderCapabilities` y enrutado por capacidades, cliente HTTP resiliente con redirecciones solo dentro del origen y sin credenciales en las trazas, casetes grabadas y contrato común de proveedores, informes bilingües, contrato OpenAPI que regenera los tipos de la web, errores RFC 9457.

**CryptoWorld es mejor en:**

- **Amplitud.** Análisis técnico completo, Confluence Card, terminal cuant, régimen, lead-lag, derivados, carry, opciones, on-chain forense, noticias, alertas cuantitativas, paper trading y ejecución real.
- **Honestidad estadística.** Es lo que de verdad lo distingue: control de multiplicidad con el N real de pruebas (G1), registro de experimentos (G8), CPCV purgada (G2), relleno a la apertura siguiente (G4.1), cascada de retests y SPP (G5), triple barrera y meta-etiquetado (G3), significancia junto a cada métrica (G9), potencia estadística en el *fitness*, «un control que no puede medir no puede aprobar», MDA fuera de muestra, banda neutral conformal, puerta de dinero real por PSR/MinTRL.
- **Producto con estado.** Usuarios, carteras con largos y cortos, *watchlists*, alertas con disparo por flanco, notificaciones en la app, por WebSocket, por email y por Web Push, digests diarios, PWA, academia, paleta de comandos y *onboarding*.
- **Metodología como código.** `methodology.py` guarda junto al código qué significa cada cifra propia y dónde deja de valer, y lo publica en `/metodologia`.

### 2.3 Lo que el plan maestro de Finances dice de CryptoWorld, y lo que hay de verdad

| El plan maestro (§9) dice | `develop` 1.346.1 tiene |
|---|---|
| «Unas 25k líneas» | ~77k de backend (49k de código + 28k de tests) y ~36k de frontend |
| «Clientes para Binance, KuCoin y CoinGecko con cadena de *fallback*» | 9 clientes, incluido `ccxt_broker` para órdenes reales, Deribit para opciones y Blockscout para cuatro cadenas |
| «Motor de análisis técnico de unas 900 líneas» | `technical_analysis_service.py` (1.359) + `price_patterns.py` (618, con FVG, *order blocks*, barridas de liquidez, CRT, AMD, ORB) + `price_structure.py` + `confluence_service.py` + `confluence_fusion.py` |
| «Predicción con Random Forest y *backtesting*» | Conjunto RF + HistGradientBoosting + regresión logística con CV purgada, Platt, conformal, `PredictionRecord` con etiqueta diferida y deriva; backtest con costes, deslizamiento, funding, cortos, relleno a la apertura siguiente y una suite de robustez completa |
| (no aparece) | Generador genético + NSGA-II sobre una gramática de estrategias, registro de pruebas, deflación, CPCV, meta-modelo, incubación, reoptimización nocturna |
| (no aparece) | Paper trading, OMS con límites de pérdida diaria, concentración y *kill-switch*, ejecución real ccxt, TCA, auditoría de ejecución, puerta PSR/MinTRL |
| (no aparece) | HAR, carry, factores cripto, opciones, rupturas estructurales, calendario económico + estudio de eventos, estacionalidad 168 casillas, ventana de ejecución |
| «Predicción ML y *backtesting* se reescriben con un protocolo anti-*look-ahead* (*walk-forward*)» | Ya está hecho en CryptoWorld, y mejor que un *walk-forward* simple: CPCV con purga y embargo |

**Consecuencia:** la sección 9 y la fase F12 del plan maestro deben reescribirse con este documento. Si no, F12 se planificará como «añadir ccxt y portar 900 líneas de indicadores» y se perderá lo que más vale.

---

## 3. Cómo leer el inventario

Cada módulo de CryptoWorld (§4) y de Finances (§5) se describe con la misma plantilla:

- **Qué hace**: la funcionalidad, con los ficheros que la implementan.
- **Estado**: qué está bien y qué está roto o a medias, con evidencia.
- **Mejoras**: lo que habría que hacer aunque no existiera Finances.
- **Al llevarlo a Finances**: destino en la arquitectura hexagonal, qué cambia para que valga con cualquier activo y qué pieza de Finances lo sustituye si ya existe.

El apartado **Estado** describe qué se puede reutilizar y qué tiene que cambiar. No es una auditoría de CryptoWorld: sus defectos abiertos se llevan en su propio repositorio y aquí solo aparecen convertidos en requisitos.

Acción propuesta para cada pieza: **Portar** (se traduce casi tal cual), **Generalizar** (se porta cambiando supuestos de cripto), **Reescribir** (la idea vale, el código no), **Sustituir** (Finances ya lo tiene mejor), **Dejar** (no se porta).

---

## 4. Inventario funcional de CryptoWorld

### 4.1 Ingesta, almacén de velas y calidad de datos

**Qué hace.**
- Clientes HTTP propios: `binance_client.py` (velas spot y USDⓈ-M, `premiumIndex`, `openInterest`, profundidad `/fapi/v1/depth`), `kucoin_client.py` (velas de respaldo), `coingecko_client.py` (catálogo, capitalización, dominancia, OHLC de respaldo), `cryptocompare_client.py` (noticias) y alternative.me (Fear & Greed).
- Almacén propio de velas: `OhlcvCandle` + `ohlcv_fetcher.py` (paginación y cadena Binance → KuCoin → CoinGecko), `ohlcv_store.py`, tareas `sync_ohlcv_history` y `backfill_ohlcv`.
- Salud del almacén: `ohlcv_health.py` + `data_quality.py` (cobertura frente a velas esperadas y frescura), expuesta en `/api/data/health/` y en `DataHealthPanel`.
- Universo *point-in-time*: `universe.py` + `sync_asset_lifecycle` (quién existía en cada fecha, para no medir solo sobre supervivientes).
- Sincronización de precios rápida y del catálogo (`sync_prices_quick`, `sync_market_prices`), *sparklines* y conversión a otras divisas (`get_fx_rates`).

**Estado.**
- La cadena de respaldo y la paginación funcionan y tienen tests.
- El almacén descarta cuatro columnas que Binance entrega con cada vela: `quote_volume`, `num_trades`, `taker_buy_base` y `taker_buy_quote`. Son el delta y el CVD por vela con historia desde 2017, gratis.
- La calidad se mide solo como cobertura y frescura. No detecta *outliers*, precios congelados, OHLC incoherente ni huecos frente a un calendario.
- Precios y volúmenes en `FloatField` (correcto para analítica).
- El universo PIT existe, pero solo para cripto.

**Mejoras.** Guardar las cuatro columnas de flujo (F0 de orderflow). Añadir a la salud la reconciliación entre fuentes. Sustituir los clientes propios de exchange por ccxt para lectura.

**Al llevarlo a Finances.**
- **Sustituir** los clientes de Binance y KuCoin por un adaptador `adapters/providers/ccxt/` que implemente `MarketDataProvider` y declare `ProviderCapabilities` (cripto, 1m-1mo, histórico por *exchange*). Es lo que ya decide el plan maestro.
- **Sustituir** la calidad de CryptoWorld por `services/quality.py` + `analytics/quality.py` de Finances, que ya detectan *outliers* con MAD, *splits* sospechosos, precios congelados, OHLC incoherente y huecos frente al calendario oficial. Para cripto, el calendario es 24/7 (`MarketSchedule` ya lo distingue por `AssetClass`).
- **Generalizar** `universe.py` a `domain/universe.py`: un `Universe` *point-in-time* con fecha de alta y de baja por instrumento. Vale igual para acciones deslistadas (sesgo de supervivencia del IBEX o del S&P) que para monedas muertas.
- **Nuevo tipo** para el flujo por vela: `PriceSeries` solo admite `open/high/low/close/adj_close/volume` (`domain/series.py:307`). El delta y el CVD no son precios: deben ir en un tipo hermano (`FlowSeries` o `BarFlow`) alineado por índice, para no abrir la validación estricta de `PriceSeries`.
- CoinGecko y alternative.me pasan a adaptadores de nuevos puertos (`ReferenceDataProvider` para metadatos y capitalización, `SentimentProvider` para Fear & Greed).

### 4.2 Análisis técnico, patrones y estructura de precio

**Qué hace.**
- `technical_analysis_service.py`: indicadores individuales (RSI, MACD, SMA, EMA, Bollinger…), panel de señales con 11 indicadores y veredicto (`calculate_signals_dashboard`), 12 patrones de velas japonesas (`detect_candle_patterns`), las 5 estrategias clásicas y el motor de backtest heredado.
- `price_patterns.py`: acción del precio como sucesos con estructura: envolventes, *Fair Value Gaps*, *order blocks*, barridas de liquidez, CRT, AMD/Power of Three, ORB, zonas de Fibonacci.
- `price_structure.py`: soportes y resistencias por agrupación de pivotes y divergencias.
- `get_mtf_confluence.py`: confluencia multi-marco temporal. `/analysis/levels/` y `/analysis/mtf/`.
- Frontend: `TechnicalAnalysisPage`, `OhlcvChart` sobre KLineChart (velas, 20+ indicadores, herramientas de dibujo), `IndicatorsRadar`, `AnalysisPanel`.

**Estado.**
- Indicadores calculados con la librería `ta` 0.11, sin mantenimiento.
- `price_patterns` está bien diseñado (definiciones parametrizadas y versionables) y es vocabulario del generador.
- El veredicto del panel de 11 indicadores es un voto sin validar: no lleva insignia de evidencia, a diferencia de lo que se exige al resto del motor.

**Mejoras.** Retirar `ta`. Que cada patrón y cada veredicto lleven la misma insignia de evidencia que propone la auditoría para el orderflow («magnitud ✓/✗ · dirección ✓/✗ · n»), calculada con el estudio de eventos.

**Al llevarlo a Finances.**
- **Generalizar** a `analytics/technical/` (indicadores vectorizados con NumPy sobre arrays, sin dominio) y `analytics/patterns/` (sucesos). La fachada en `domain/` sería un método o servicio que recibe una `PriceSeries` y devuelve un tipo `IndicatorSet` / `PatternEvents` inmutable. Así el RSI de `SAN.MC` y el de `BTC-USD` salen del mismo código.
- La decisión entre NumPy propio y TA-Lib ya está prevista como ADR en el plan maestro. Recomiendo NumPy propio para los ~25 indicadores del catálogo de `strategy_spec`: menos dependencias nativas, tipado completo y tests de propiedades.
- **Tests de paridad** obligatorios: para cada indicador, una casete con la salida de CryptoWorld sobre las mismas velas y tolerancia numérica fijada. Es la única forma de saber que el porte no ha cambiado ningún resultado.
- **Cambios multiactivo:** los patrones de sesión (ORB, AMD) necesitan la sesión del mercado, no medianoche UTC; deben leerla del `TradingCalendar`. En acciones, los huecos de apertura son reales y no deben confundirse con *Fair Value Gaps* intradía.

### 4.3 Confluence Card y fusión 360°

**Qué hace.**
- `confluence_service.py`: ficha técnica por activo (tendencia de fondo, soportes y resistencias, Fibonacci, resumen multi-indicador y veredicto con nivel de confianza).
- `confluence_fusion.py`: fusiona técnica, ML, on-chain y noticias en un *score* ∈ [-1, +1] con **pesos aprendidos** por el historial de aciertos (`ConfluenceSnapshot`, `ConfluenceSignalEvent`, tareas `evaluate_confluence` y `resolve_confluence_snapshots`).
- Landing SEO renderizada en servidor: `/cripto/<slug>`, `sitemap.xml`, `robots.txt` y JSON-LD (`interfaces/web/views.py`, plantilla `landing/crypto_card.html`).

**Estado.** Es la pieza 1 del plan comercial y está hecha. Los pesos aprendidos son una buena idea, pero el historial de aciertos necesita semanas de muestra antes de significar algo, y la UI no enseña cuánta muestra hay detrás de cada peso.

**Mejoras.** Mostrar el n y el intervalo de Wilson de cada peso. Añadir el pilar de orderflow solo cuando pase el estudio de evidencias.

**Al llevarlo a Finances.**
- **Generalizar** a una «Ficha de activo» para cualquier instrumento. Los pilares dependen de la clase de activo: técnica y ML para todos; on-chain y derivados solo para cripto; fundamentales (F11) y macro para acciones e índices. El diseño debe ser un registro de pilares con `applies_to: frozenset[AssetClass]`.
- El registro de lecturas y su resolución necesitan persistencia y jobs (G0).
- La landing SEO va a G12 (SaaS) y sería una ruta SSR de Next.js, no una plantilla de Django.

### 4.4 Terminal cuant, régimen y relaciones entre activos

**Qué hace.**
- `quant_metrics.py` (`/analysis/quant/`, `QuantTerminal`): volatilidad realizada, ATR, retornos multi-horizonte con *z-score*, Sharpe/Sortino del activo, *drawdown*, posición en el rango.
- `regime.py` y `market_regime.py` (`/market/regime/`): régimen de volatilidad y tendencia, correlación media de la cesta.
- `lead_lag.py` (`/market/lead-lag/`): correlación cruzada con desfases y ranking de liderazgo.
- `correlation_heatmap.py` (`/market/correlation-map/`): mapa de correlaciones ordenado por agrupamiento, con incertidumbre y marcas de cambio acompañadas de su tasa de falsos.
- `structural_break.py` + `correlation_watch.py` (solo comando `correlation_watch`): rupturas de correlación con umbral calibrado y tratamiento de contrastes múltiples.
- `seasonality.py` (solo comando `seasonality`): rejilla de 168 casillas hora × día con nulo por permutación y corrección por multiplicidad.
- `economic_calendar.py` + `event_study.py` (solo comando `calendar_study`): eventos programados (FOMC, IPC, nóminas…) y estudio de eventos con controles emparejados por casilla del calendario.

**Estado.** Calidad metodológica alta: cada módulo documenta los defectos que encontró la calibración. **El problema es la exposición:** estacionalidad, rupturas, calendario y estudio de eventos no tienen endpoint ni pantalla.

**Mejoras.** Exponer los cuatro módulos que solo existen como comando, con su resultado versionado y su nota de metodología.

**Al llevarlo a Finances.**
- **Portar** a `analytics/` (funciones puras): `regime`, `lead_lag`, `structural_break`, `seasonality`, `event_study`. Son de lo más reutilizable del proyecto y funcionan igual con acciones.
- **Sustituir** la matriz de correlación por la de Finances (`domain/panel.py`, *pairwise-complete* con reparación PSD), y **portar** encima lo que CryptoWorld añade: ordenación por agrupamiento, incertidumbre por celda y marcas de cambio con su FDR.
- **Generalizar** la estacionalidad: en cripto son 168 casillas (24 × 7); en acciones son las sesiones del calendario (apertura, mediodía, cierre, día de la semana, vencimientos), que salen del `TradingCalendar`.
- **Mejorar** el calendario económico: CryptoWorld deriva fechas sin red; Finances ya tiene el BCE y tendrá FRED/ALFRED con **fecha de publicación**, que es exactamente lo que necesita un estudio de eventos. Es un caso en que el porte sale mejor que el original.
- El aviso de *trading* no sincrónico que Finances ya da para carteras Europa + EE. UU. debe aplicarse también a lead-lag entre mercados con cierres distintos.

### 4.5 Volatilidad y opciones

**Qué hace.**
- `volatility_forecast.py`: HAR-RV con R² fuera de muestra, Diebold-Mariano contra persistencia y cálculo de potencia («cuántas observaciones hacen falta»). Corregido en la 1.340.
- `option_moments.py` + `option_surface.py` + `deribit_client.py` (tarea `sync_option_surface` y comando `option_surface`): momentos implícitos de la superficie de opciones de Deribit (volatilidad implícita, *skew*, curtosis) como predictor de magnitud.
- `conformal.py`: sustituye la banda neutral fija (0,45-0,55) del clasificador por predicción conformal con tasa de error controlada (1.338).
- `edge_test.py` (comando `edge_test`): decide a qué pregunta (dirección o magnitud) alcanza la muestra.

**Estado.** Es el reencuadre de agosto (dirección → volatilidad) llevado a código. Sin pantalla salvo lo que se cuela en el terminal.

**Mejoras.** El **Índice de Fragilidad** es el paso natural: un HAR-X con funding, OI, basis, profundidad y RV multiescala. Sus datos llevan archivándose desde el 19-sep y el índice no existe.

**Al llevarlo a Finances.**
- **Portar** HAR, Diebold-Mariano, potencia y conformal a `analytics/volatility/` y `analytics/conformal.py`. Sirven para cualquier serie; en acciones, con RV diaria y sin intradía de pago, el HAR diario ya bate a la persistencia en la literatura.
- Opciones: el adaptador de Deribit es solo cripto. Para índices, el VIX y los índices de Cboe ya están en la fase F11 del plan; la «superficie» de acciones exige datos de pago. El diseño debe separar el puerto (`OptionsDataProvider` → `VolSurface`) del proveedor.
- El Índice de Fragilidad se construye directamente en Finances (fase G5): no tiene sentido construirlo primero en CryptoWorld.

### 4.6 Derivados, funding y carry

**Qué hace.**
- `derivatives_metrics.py` (`/analysis/derivatives/`, `DerivativesPanel`): funding anualizado, basis y OI con veredicto.
- `funding_store.py` + `FundingRateRecord` (tarea `sync_funding_history`), `derivatives_store.py` + `DerivativeMetricPoint` (tarea `sync_derivative_metrics`, programada desde la 1.337): archivo de funding, OI, ratio L/S, taker ratio y foto del libro ±2 % cada 15 minutos.
- `funding.py`: coste del funding dentro del backtest de perpetuos.
- `carry.py` + `carry_test.py` (solo comando `carry_test`): cosecha de funding delta-neutral (spot largo + perpetuo corto), precio de liquidación de la pata corta, probabilidad de tocar margen ante un *shock*, distribución nula y veredicto.

**Estado.** Es el «edge A» de agosto, el más plausible de los analizados. Solo hay un *venue* (Binance) y la foto del libro es de 15 minutos, lo que deja fuera la dislocación de funding entre *exchanges*.

**Mejoras.** Funding de Bybit y OKX, *term structure* de funding, carry neto de costes a tu tamaño expuesto en una pantalla («Mesa de carry»).

**Al llevarlo a Finances.**
- Nuevos `Dataset` en `ports/market_data.py`: `FUNDING`, `OPEN_INTEREST`, `ORDER_BOOK_SNAPSHOT`, `LONG_SHORT_RATIO`. El adaptador ccxt los sirve para varios *venues* con la misma interfaz, lo que resuelve de paso la limitación a un solo *venue*.
- El funding es una serie de **tipos**, no de precios: encaja mejor en un tipo hermano de `EconomicSeries` (`RateSeries` por instrumento y *venue*) que en `PriceSeries`. Recomiendo un ADR.
- **Portar** `carry.py` a `analytics/carry.py`. Generalizarlo a «coste de mantener la posición»: funding en perpetuos, coste de préstamo de títulos en cortos de acciones, *roll yield* en futuros. El backtest de Finances debe tener un único concepto `CarryCost` con implementaciones por clase de activo.

### 4.7 Backtest y suite de robustez

**Qué hace.**
- `backtest_execution.py` (544): simulación con comisión y deslizamiento en pb, relleno a la apertura de la vela siguiente (G4.1), cortos (1.316-1.318), funding, dimensionado por convicción.
- `backtest_metrics.py`, `backtest_bias.py` (*look-ahead* y recursividad), `backtest_robustness.py` (Optuna, *walk-forward*, Monte Carlo, DSR, PBO/CSCV), `backtest_report.py` (puntuación 0-100 y veredicto ROBUSTA / FRÁGIL / SOBREAJUSTADA en español, sin LLM).
- `purged_cv.py` (purga y embargo), CPCV (G2), `significance.py` (IC del Sharpe, PSR, MinTRL, Wilson, `edge_significance`, Benjamini-Hochberg, McNemar).
- `market_impact.py` (impacto y capacidad de una estrategia), `crypto_factors.py` (modelo de tres factores de cripto con Newey-West, «medir alfa, no Sharpe»).
- Casos de uso asíncronos: `run_robust_backtest`, `compare_strategies`, `run_spec_robustness`. Frontend: `RobustnessPanel`, `WalkForwardMatrixCard`, `CpcvDistributionCard`, `MultipleTestingCard`, `CapacityCard`.

**Estado.**
- Es el corazón del proyecto y está a nivel de investigación seria tras G1-G9.
- Quedan dos herencias de la v1.138: la suite de las 5 estrategias clásicas en `technical_analysis_service.py` (`backtest_signals`) convive con el motor nuevo.
- El banco de mundos nulos no está en la CI: los tests solo incluyen un paseo aleatorio con una semilla. Tras G1 y la 1.325, la tasa de falsos positivos debería estar por debajo del 5 % por ejecución, pero no hay evidencia en el repositorio de que se volviera a medir.

**Mejoras.** Mundos nulos como test nocturno que rompe la build si la tasa supera el 5 %. Retirar el motor heredado.

**Al llevarlo a Finances.**
- **Portar** a `analytics/backtest/` (motor vectorizado, sin dominio) + `analytics/validation/` (purga, CPCV, DSR, PBO, PSR, MinTRL, Wilson, BH, McNemar) + `domain/backtest.py` (`BacktestConfig`, `BacktestResult`, `Trade`, `CostModel` inmutables y validados).
- **Unificar** con Finances: `sharpe_ratio_standard_error` ya existe en `analytics/risk.py`; `significance.py` se funde ahí y no se duplica. El Monte Carlo de robustez reutiliza `analytics/montecarlo.py` (el *bootstrap* estacionario de Finances es justo lo que necesita el MC de una curva de *equity*).
- **Generalizar** el modelo de costes: comisión por *broker* y mercado (no solo pb), *spread* según liquidez, impuesto de transacciones financieras en España y Francia, coste de préstamo en cortos, dividendos (retorno total) y *splits* (precio ajustado de Finances). El relleno a la apertura siguiente debe respetar el calendario: la apertura siguiente de un viernes es el lunes, o el martes si el lunes es festivo.
- **Generalizar** los factores: cripto con su modelo de tres factores; acciones con Fama-French y q-factors (Kenneth French y global-q ya están en F11). Es otra pieza que sale mejor en Finances que en el original.
- La capacidad y el impacto (`market_impact.py`) usan volumen en USD; en Finances deben usar el volumen en la divisa del instrumento y convertir *as-of*.

### 4.8 Generador de estrategias

**Qué hace.**
- `strategy_spec.py` (1.557): gramática componible: bloques de entrada y salida con 1-3 condiciones de cinco tipos (umbral, cruce, estado, pendiente y patrón), negación y confirmación parcial «k de n», sobre ~25 indicadores y el vocabulario de `price_patterns`. Un compilador causal la traduce a señales.
- `strategy_generator.py` (GA con torneo, cruce, mutación, elitismo, inyección aleatoria) y `strategy_nsga.py` (NSGA-II con frontera de Pareto).
- `strategy_evaluation.py` (1.365): puente entre el spec y la suite de robustez, con gating.
- `block_sampling.py`: búsqueda en dos fases sobre años de datos sin años de cómputo. **Su comprobación de validez dio negativo** y el propio módulo lo documenta.
- `generation_power.py`: distingue «no hay edge» de «no había muestra para juzgar».
- Registro de pruebas y deflación por el N real (G1), N efectivo por agrupamiento, curva E[máx SR₀] frente a N, registro de experimentos (`StrategyExperimentRun`, G8).
- `labeling.py` (triple barrera y meta-etiquetado), `meta_model.py` y `meta_sizing.py` (de la señal a la convicción y al tamaño), triple barrera como política de salida.
- Cascada de retests (G5) y SPP, `incubation.py` (puerta antes del capital real), `hrp.py` y `strategy_portfolio.py` (cartera de estrategias), `reoptimize_strategies` y `fill_strategy_stable` (nocturnas), `monitor_strategies`, dossier por estrategia, comparador.
- Presets `fast`, `balanced` y `thorough` (el antiguo `deep` ya no existe).
- Frontend: `StrategyGeneratorPage` (1.084 líneas) con tablero de evolución en vivo, frontera de Pareto 2D y 3D, ADN de la estrategia en 3D, variantes, «casi aprobadas», desglose por lado, `StrategyDossierPage`.

**Estado.**
- El experimento del 6-ago demostró que el motor de entonces aprobaba estrategias sobre paseos aleatorios (25 % de las ejecuciones con al menos un falso positivo; 23-90 % según el preset). Desde entonces se corrigió casi todo lo que señalaba aquel informe: N real, purga, potencia en el *fitness*, retirada de `deep`, «un control que no puede medir no puede aprobar».
- **Lo que falta es volver a medirlo**. Hasta que el banco de mundos nulos diga que la tasa es < 5 %, ninguna estrategia del generador debería mostrarse como «validada».
- La 1.323 hizo que nada de lo visto durante la evolución desaparezca sin explicación: buena práctica para la auditoría de experimentos.

**Mejoras (por qué y cómo, en §4.8 bis y en la fase G4).**

**Al llevarlo a Finances.** Ver §4.8 bis: es la pieza en la que me pediste que decidiera yo.

### 4.8 bis Cómo propongo importar y mejorar el generador y el ML

Me pediste que lo importara como creyera mejor y lo mejorara. Esta es la propuesta, con las razones:

**1. Se importa como «Laboratorio de estrategias», no como «Generador de señales».** El producto es el instrumento de medida, no la estrategia que sale. Las estrategias que produce son hipótesis con su probabilidad de ser ruido, no recomendaciones. Esto también importa para el modo SaaS: una herramienta de investigación está fuera del perímetro de MiCA; una señal publicada como recomendación puede no estarlo.

**2. El banco de mundos nulos pasa a ser parte del sistema, no un experimento.**
- `analytics/validation/null_worlds.py`: generadores de mundos sin alfa por construcción (paseo aleatorio con la volatilidad del activo, *bootstrap* estacionario de los retornos reales con la media restada, permutación de bloques).
- Cada preset tiene su **tasa de falsos positivos medida y publicada** («este preset aprueba algo en el 3,1 % de los mundos sin señal, n = 500»).
- Un test `slow` nocturno en CI rompe la build si algún preset supera el 5 %.
- Cualquier cambio del vocabulario o del *gating* vuelve a medir la tasa antes de mergearse.

**3. El N de la deflación sale del registro, siempre.** Cada evaluación del GA, de NSGA-II, de los reinicios y de la reoptimización nocturna se escribe en un registro de experimentos *append-only* (tabla con `hash` encadenado, ver G0). El DSR y el PBO leen el N de ahí, no de un parámetro. La reoptimización nocturna **acumula** pruebas: la séptima noche deflacta por las siete.

**4. Objetivos de investigación más allá de la dirección.** El cálculo de potencia de agosto mostró que con cientos de observaciones fuera de muestra solo se detectaría un edge direccional ≥ 6 %, que no existe en mercados líquidos, mientras que efectos sobre volatilidad de ρ = 0,30-0,45 se detectan con 36-85. Por eso el Laboratorio admite tres tipos de objetivo, y cada uno con su propia métrica y su propio nulo:
- **Dirección** (lo actual): Sharpe deflactado, PSR, retorno neto de costes.
- **Magnitud / riesgo**: estrategias que ajustan exposición según la volatilidad prevista (HAR, fragilidad); se miden por reducción de *drawdown* y de CVaR a igual retorno.
- **Carry**: estrategias delta-neutrales o de *roll*; se miden por rendimiento neto frente a la probabilidad de margen.

**5. Multiactivo, con cuidado con la multiplicidad.** El Laboratorio corre sobre cualquier `PriceSeries` o sobre un `Universe` PIT. Validar sobre varios activos (`cross_check_assets` ya existe) es más evidencia; buscar sobre muchos activos y quedarse con el mejor es más multiplicidad, y cuenta en el N.

**6. Variables exógenas *point-in-time* de Finances.** CryptoWorld solo dispone de exógenas de cripto (funding, OI, L/S, *netflow*, profundidad). Finances aporta macro con fecha de publicación (BCE ya; FRED/ALFRED en F2b), tipos sin riesgo y FX. Entran por el mismo módulo `exogenous_features` con su disciplina PIT, y se juzgan con la MDA fuera de muestra de la 1.330.

**7. Lo que no se porta del generador.**
- `block_sampling` como búsqueda en dos fases: su comprobación dio negativo. Se porta el código con la bandera apagada y su resultado documentado, o no se porta; recomiendo lo segundo.
- La visualización 3D del ADN y del paisaje evolutivo (`StrategyDNAHelix3D`, `EvolutionLandscape3D`, `RobustnessUniverse3D`): vistosa, pero no ayuda a decidir y añade three.js al *bundle*. Se sustituye por la frontera de Pareto 2D, la curva E[máx SR] frente a N y la distribución nula con la estrategia marcada.

**8. ML predictivo dentro del Laboratorio.** El conjunto RF + HistGradientBoosting + regresión logística con CV purgada, Platt, conformal, `PredictionRecord` y deriva se porta como un «modelo» más del Laboratorio con un **baseline ingenuo obligatorio** (persistencia y clase mayoritaria) y *champion-challenger*: un modelo solo sustituye al anterior si le gana fuera de muestra con McNemar (que ya existe en `significance.py`).

**9. Criterio de abandono escrito antes de empezar.** Si, con el banco de nulos en verde, ninguna estrategia direccional supera el percentil 95 de su nulo tras costes en el universo de prueba, se publica como resultado negativo en `/metodologia` y el Laboratorio queda como herramienta de validación de estrategias propias (las del trader pentacampeón, las tuyas en Pine Script). Ese es, de hecho, su uso más valioso.

### 4.9 Predicción ML y seguimiento de predicciones

**Qué hace.** `predict_price.py` (`/analysis/predict/`), `track_predictions.py` + `PredictionRecord` (etiqueta diferida, tareas `warm_ml_predictions` y `resolve_predictions`), `/analysis/predictions/monitoring/` y `PredictionMonitoringPanel` (deriva y acierto real), `feature_importance.py` (MDA fuera de muestra desde la 1.330, antes MDI dentro de muestra), `exogenous_features.py`, `feature_study.py`, `feature_store.py`.

**Estado.** Honesto tras la 1.326 (purga y embargo) y la 1.330. La predicción de dirección sigue siendo la pregunta a la que la muestra no alcanza (`edge_test`).

**Al llevarlo a Finances.** Dentro del Laboratorio (§4.8 bis, punto 8). `scikit-learn` como dependencia de un *extra* opcional del núcleo (`investinglab[ml]`), igual que `plots` para matplotlib, para no cargar el núcleo de quien solo quiere carteras.

### 4.10 Carteras del usuario y riesgo del libro

**Qué hace.**
- `PortfolioAsset`, `Position` (largos y cortos), `TradeHistory`; casos de uso `add_trade`, `open_position`, `scale_position`, `close_position`, `delete_trade`, `get_portfolio`, `get_positions`, `get_trade_history`, `export_reports` (CSV).
- `portfolio_risk.py` (`/portfolio/risk/`): exposición firmada, VaR/CVaR por simulación histórica y **estrés con escenarios observados** (el peor movimiento de k días de cada activo, «todo lo malo a la vez»).
- `risk_attribution.py` (`/portfolio/risk/attribution/`): por componentes (Euler sobre el CVaR 95 %) y por factor.
- `send_risk_digest` (resumen diario por email), `PortfolioPage` (948 líneas) con `RiskPanel`, `RiskAttributionPanel`, `PortfolioInsights` y visualizaciones 2D/3D de riesgo-retorno y correlación.

**Estado.** Funcional y útil. Todo en USD, en `float`, sin lotes fiscales ni divisa base.

**Al llevarlo a Finances.**
- **Sustituir** el cálculo de riesgo por el de Finances (`domain/portfolio.py` + `analytics/risk.py`: VaR histórico, normal y Cornish-Fisher con IC; Euler; Ledoit-Wolf).
- **Portar** lo que a Finances le falta: estrés con escenarios observados y atribución por factor.
- **Reescribir** el modelo de posiciones: hoy Finances solo tiene `Portfolio` con **pesos** objetivo. Para el libro real hace falta `Ledger` → `Transaction` (compra, venta, dividendo, comisión, *split*, transferencia) → `Lot` → `Holding` con cantidades, en la divisa del instrumento y valorado en la divisa base con FX *as-of*. De ahí salen los pesos reales, el P&L realizado y no realizado y, más tarde, la fiscalidad (FIFO para el IRPF, Modelo 720 para valores en el extranjero y 721 para cripto en custodios extranjeros).
- La fiscalidad (pieza 4 del plan comercial) encaja mucho mejor en Finances que en CryptoWorld, porque una declaración no se hace solo con cripto.

### 4.11 Paper trading, OMS y ejecución real

**Qué hace.**
- `paper_trading.py` (676): cuentas de paper por estrategia (`PaperTradingAccount`, `PaperTrade`, `PaperEquitySnapshot`), evaluación periódica (`evaluate_paper_trading`), detección de decaimiento, promoción de paper a real con tope.
- `ccxt_broker.py` + `ExchangeConnection` (claves cifradas con `MultiFernet` y rotación en `CREDENTIALS_ENCRYPTION_KEYS`) + `broker_trading.py`: saldo, órdenes y cancelación (`/trading/connections/...`).
- OMS: `LiveRiskPolicy` (límite de pérdida diaria y de concentración), *kill-switch*, controles *fail-closed* desde la 1.331.
- Puerta del dinero real (1.346): PSR ≥ 0,95 sobre la curva de patrimonio diaria y MinTRL como plazo, *fail-closed* y con el «no» explicado.
- `tca.py` (deslizamiento contra el precio de la señal), `execution_audit.py` (rastro de cada intento: enviada, fallida, bloqueada), `execution_cost.py` (coste a tu tamaño desde la profundidad), `execution_window.py` (1.345: ¿ahora o espero?), `reconcile_live_positions`.
- Frontend: `TradingPage`, `PaperTradingPanel`, `TcaPanel`, `ExecutionAuditPanel`, `ExecutionCostPanel`, `ExecutionWindowPanel`.

**Estado.** El *paper trading*, la puerta del dinero real, el TCA y la auditoría de ejecución se conservan como idea. El camino de la orden real no se porta: en Finances se rediseña desde cero, y estas garantías son requisitos, no mejoras opcionales:
- Una orden nunca se envía al *exchange* dentro de una transacción de base de datos: si la transacción revierte, la orden no puede haber salido ya.
- Toda orden lleva un identificador de cliente propio, para que un reintento tras un *timeout* no pueda duplicarla.
- La posición se mueve solo con lo ejecutado (*fills*), nunca con lo pedido.
- Un *timeout* no es un fallo: es un estado desconocido que el reconciliador resuelve consultando por el identificador de cliente.
- La cuenta se bloquea mientras se validan los límites, para que dos procesos no puedan gastar el mismo saldo.
- Todo lo que es dinero va en `Decimal`.
- El *paper* rellena con el mismo simulador que el backtest (apertura siguiente con deslizamiento), no al cierre de la misma vela.

**Al llevarlo a Finances (D1: paper + real solo en tu cuenta).**
- **Reescribir**, no portar: el dominio de la orden debe nacer correcto.
  - `domain/trading/`: `Order` (máquina de estados `NEW → PENDING_SUBMIT → SUBMITTED → PARTIALLY_FILLED → FILLED | CANCELLED | REJECTED | UNKNOWN`), `Fill`, `Position`, `RiskPolicy`, `KillSwitch`, todos con `Decimal` y con cantidades redondeadas a los `stepSize`/`tickSize` del mercado.
  - `ports/execution.py`: `ExecutionVenue` (enviar con `client_order_id`, consultar por `client_order_id`, cancelar, saldo, mercados) y `OrderRepository` con bloqueo.
  - Patrón *outbox*: (1) transacción corta con bloqueo de la cuenta (`SELECT … FOR UPDATE`) → validar límites → crear la orden `PENDING_SUBMIT` con `client_order_id = uuid4` → *commit*; (2) envío **fuera** de la transacción; (3) transacción corta que guarda `filled`, `average` y estado; (4) *timeout* → `UNKNOWN`, y el reconciliador consulta por `client_order_id`. La posición se mueve **solo** con *fills*.
  - Tests obligatorios: *rollback* tras orden enviada, *timeout* con orden ejecutada, *fill* parcial, dos *workers* concurrentes y reinicio del proceso con órdenes en vuelo.
- **Proceso aparte** `apps/trader` (ver §6.3): la API nunca envía órdenes; publica intenciones que el *trader* consume. Así un fallo de la web no puede mandar una orden y la superficie con claves es mínima.
- **Cuatro llaves**: `INVESTINGLAB_LIVE_TRADING=false` por defecto; un único `INVESTINGLAB_LIVE_OWNER` fijado; puerta PSR/MinTRL + incubación para cada estrategia; *kill-switch* que corta en el *trader* y no en la web.
- **Claves**: solo permisos de *trade* (nunca de retirada), lista de IP permitidas en el *exchange*, cifradas en reposo (se mantiene `MultiFernet` con rotación o se pasa a un gestor de secretos en F14), nunca en logs (Finances ya enmascara `api_key=` y `token=`).
- **Paper honesto**: rellenos contra el libro grabado cuando exista; mientras, a la apertura siguiente con el deslizamiento del modelo de costes, igual que el backtest. El paper y el backtest deben compartir **el mismo** simulador de ejecución.
- **Rastro WORM**: el registro de ejecución como tabla *append-only* con *hash* encadenado.
- **Multiactivo**: ccxt cubre cripto. Para acciones y ETF hace falta otro `ExecutionVenue` (Interactive Brokers o Alpaca, por ejemplo); queda como decisión abierta (§10).

### 4.12 On-chain y forense

**Qué hace.**
- Clientes: `blockchain_dot_com_client.py`, `blockchair_client.py`, `blockscout_client.py` (cuatro redes).
- Mercado on-chain: `get_onchain_metrics`, `get_multichain_stats`, `chain_metrics_store` (+ `sync_chain_metrics`, `prune_chain_metrics`), `get_chain_health`, `onchain_market_pulse`, `onchain_pressure`.
- Ballenas y dinero inteligente: `get_whale_movements` + `scan_whale_movements`, `get_smart_money` + `smart_money.py`, `onchain_flow.py` (flujos hacia y desde *exchanges*).
- Carteras y direcciones: `get_wallet_overview`, `wallet_dossier`, `get_address_dossier` (`AddressDossierPage`), *watchlist* de direcciones con alertas (`WatchedAddress`, `AddressAlert`, `monitor_watched_addresses`).
- Forense: `onchain_forensics.py` (árbol de flujo, concentración, huella de conducta), `onchain_risk.py` (puntuación de riesgo de dirección, aprobaciones, grafo de entidad), `token_safety.py` (*rug-pull* y *honeypot*), `wash_trading.py` (transferencias circulares).
- Frontend: `BlockchainPage` con `ForensicsPanel`, `WhaleMovementsPanel`, `SmartMoneyPanel`, `OnChainPressurePanel`, `NetworkHealthPanel`, `WalletExplorerPanel`, `MultiChainCompare` 2D/3D.

**Estado.** Muy completo para un proyecto individual. Las etiquetas de riesgo (sanciones, *mixers*) dependen de listas que hay que mantener; la puntuación de riesgo de una dirección es una heurística, y la UI debe decirlo.

**Al llevarlo a Finances.**
- **Portar** como sección «Cripto · On-chain» (fase G9) con un puerto `OnChainDataProvider` y adaptadores por fuente. Es la parte menos reutilizable fuera de cripto y la de menor prioridad para una plataforma personal multiactivo.
- Lenguaje: nada de «spoofing», «lavado» ni imputaciones en la UI. «Patrón compatible con…», con la heurística y su tasa de error.
- En modo SaaS, los dosieres de direcciones de terceros tocan datos personales (RGPD: una dirección vinculada a una persona es un dato personal). Queda fuera del alcance personal, pero hay que anotarlo para G12.

### 4.13 Noticias y sentimiento

**Qué hace.** `get_news_feed` (CryptoCompare), `news_geography.py` + `get_news_globe` (marcadores por región y categoría de evento, ES/EN), `NewsPage` con `NewsGlobe3D` y `GeoNews2D`, Fear & Greed en `get_market_overview`.

**Estado.** Clasificación por palabras clave; útil como vista, sin evidencia de que aporte a ninguna predicción.

**Al llevarlo a Finances.** Fase G10, con un puerto `NewsProvider` (CryptoCompare para cripto; GDELT y Finnhub ya están en el *backlog* del plan maestro) y el léxico de Loughran-McDonald que ya aparece en los notebooks del máster. El globo 3D se puede dejar.

### 4.14 Alertas, notificaciones y digests

**Qué hace.**
- Alertas de precio (`PriceAlert`, `manage_alerts`, `check_price_alerts` cada 2 minutos).
- Alertas cuantitativas (`QuantAlert`, `QuantAlertFiring`, `quant_alert_rules.py` con **disparo por flanco**, `quant_alert_providers.py`, `evaluate_quant_alerts`) sobre un registro de métricas: RSI, ADX, StochRSI, histograma MACD, volatilidad realizada, ATR %, posición en el rango, precio, cambio 24 h, *score* de confluencia, flujo neto on-chain, presión on-chain, VaR y CVaR de la cartera, concentración y exposición.
- Notificaciones: *feed* en la app (`notifications.py`, `NotificationBell`), WebSocket (`NotificationConsumer`), Web Push (VAPID, `PushSubscription`, `web_push.py`), email (SendGrid) y digests diarios de mercado y de riesgo.

**Estado.** Bien diseñado: el disparo por flanco evita la avalancha de avisos repetidos. Faltan Telegram y *webhooks*.

**Al llevarlo a Finances.** Fase G8. `domain/alerts.py` (regla, condición, flanco, cooldown) + registro de métricas abierto a cualquier activo (añadir *drawdown* de cartera, desviación de pesos objetivo para avisar de rebalanceo, frescura de datos). Canales tras un puerto `Notifier`: en la app, email, Web Push, Telegram y *webhook* firmado con HMAC. El plan maestro prevé SSE para el tiempo real; vale para notificaciones, pero no para orderflow (§10).

### 4.15 Usuarios, autenticación y administración

**Qué hace.** Registro, verificación de email con token HMAC, recuperación y cambio de contraseña, cambio de email con confirmación, borrado de cuenta, 2FA TOTP con QR y códigos de recuperación, JWT con *refresh* y *blacklist*, panel de administración (usuarios, reenvío de verificación, sincronización de mercado), `AdminDashboardPage`.

**Estado.** Completo. Guarda los JWT en `localStorage`, una decisión documentada en su `SECURITY.md` que Finances no hereda.

**Al llevarlo a Finances.** **Dejar.** Finances ya decidió algo mejor (F7): Better Auth con *passkeys* y TOTP obligatorio, sesiones en cookies `HttpOnly`, verificación JWKS en la API y *Personal Access Tokens* con *scopes* para notebooks. El registro público queda desactivado (personal) y se activa con una bandera en G12.

### 4.16 Tiempo real

**Qué hace.** `PriceConsumer` (`/ws/prices/`, `usePriceStream`) y `NotificationConsumer` (`/ws/notifications/`) sobre Channels con Redis; `broadcast.py`.

**Al llevarlo a Finances.** SSE para notificaciones y precios agregados (más sencillo, pasa por cualquier proxy). WebSocket solo si llega el orderflow en vivo (G11). Decisión abierta (§10).

### 4.17 Frontend y experiencia de uso

**Qué hace.** 25 páginas: *landing*, *login*, registro, verificación, recuperación, 2FA, *dashboard* con disposición configurable (`useDashboardLayout`), mercado (*treemap* 2D y universo 3D, régimen, correlaciones, lead-lag, ventana de ejecución, *ticker*), detalle de activo, análisis técnico, generador, dosier de estrategia, *blockchain*, dosier de dirección, cartera, *trading*, noticias, alertas, ajustes (con salud de datos), administración, **academia** (`LearnPage`: lecciones, fichas de cadenas y grafo de *blockchains* 2D/3D), **metodología**. Paleta de comandos, *tour* de bienvenida, temas, i18n ES/EN, PWA (`manifest.webmanifest`, `sw.js`), modo de movimiento reducido, conmutador 2D/3D en cada visualización con *fallback* si no hay WebGL.

**Estado.** Rica y cuidada. Peso: three.js y `@react-three/*` para visualizaciones que casi siempre tienen una versión 2D equivalente.

**Al llevarlo a Finances.**
- **Reescribir** sobre Next.js + ECharts + el sistema de diseño de Finances (`theme/tokens.ts`, paleta validada, «—» en vez de NaN, tabla junto a cada gráfico). La paleta de comandos ya existe en Finances (`cmdk`).
- **Gráfico de velas:** el plan maestro prevé Lightweight Charts, pero la web actual solo usa ECharts. CryptoWorld usa KLineChart por sus herramientas de dibujo e indicadores personalizados. Decisión abierta (§10).
- Las visualizaciones 3D no se portan salvo que alguna demuestre que ayuda a decidir; la versión 2D de cada una sí.
- Academia y *tour* van a G12 (SaaS). La página de metodología se porta pronto (ver 4.18).

### 4.18 Metodología como código

**Qué hace.** `methodology.py` (513) mantiene, junto al código, qué significa cada cifra propia, cómo se calcula y dónde deja de valer; `/api/methodology/` y `MethodologyPage` lo publican.

**Al llevarlo a Finances.** **Portar la idea pronto** (G3): cada servicio que produce una cifra propia declara su nota de metodología (en `reporting/i18n.py`, bilingüe) y un test exige que exista, como ya se hace con la matriz de trazabilidad de los módulos. Encaja con los diagnósticos de fiabilidad que ya genera `report()`.

### 4.19 Plataforma: CI, despliegue y observabilidad

**Qué hace.** GitHub Actions (`ci.yml`) con `pip-audit --strict`, `npm audit`, ruff, eslint, Vitest, cobertura 75 %, `makemigrations --check`, `check --deploy`. Docker Compose de desarrollo y producción, Nginx, Railway (roles `web`, `worker`, `beat` por `SERVICE_ROLE`) y Vercel.

**Estado.** La CI reúne auditoría de dependencias, *linters*, tests y comprobaciones de despliegue. Las vistas, las tareas y los modelos viven en ficheros muy grandes, y no hay monitorización de errores ni de rendimiento.

**Al llevarlo a Finances.** Nada de esto se porta: Finances ya tiene una CI mejor (matriz 3.13/3.14, `mypy --strict`, `import-linter`, *pre-commit* completo, build de documentación, contrato OpenAPI, Playwright). Sí hay que añadirle lo que la integración exige: Postgres en CI (F6), observabilidad (OpenTelemetry + Sentry, F14) **antes** de cualquier proceso 24/7 (`apps/trader`, `apps/collector`), y el test nocturno de mundos nulos.

**Mientras CryptoWorld siga desplegado** (lo estará durante la migración), su mantenimiento de seguridad se lleva en su propio repositorio y no forma parte de este plan.

---

## 5. Inventario de Finances (InvestingLab)

Finances está organizado por **capas**, no por funcionalidades. Las dependencias apuntan siempre hacia dentro y `import-linter` lo verifica: `toolkit → modules → services | adapters → reporting | ports → domain → analytics`.

### 5.1 `analytics/` — núcleo numérico puro (~1.700 líneas)

**Qué hay.** `returns` (simples, logarítmicos, acumulados), `descriptive` (momentos, anualización, CAGR, Jarque-Bera), `drawdown` (serie, máximo, episodios), `risk` (Sharpe con error estándar, Sortino, Calmar, VaR y CVaR histórico/normal/Cornish-Fisher, beta, Herfindahl, número efectivo de activos), `covariance` (muestral, Ledoit-Wolf, reparación PSD), `portfolio` (trayectoria rebalanceada, contribuciones de Euler), `montecarlo` (Cholesky, normal y t multivariantes, *bootstrap* estacionario, valores rebalanceados, *drawdown* por trayectoria), `optimization` (mínima varianza, rentabilidad objetivo, máximo Sharpe, frontera, inversa de la volatilidad, presupuesto de riesgo, HRP, rentabilidades implícitas, Black-Litterman), `quality` (*z-score* robusto, saltos tipo *split*, rachas congeladas, violaciones OHLC, sesiones que faltan o sobran).

**Qué le falta para estar al nivel de CryptoWorld.** Todo lo de §4.2 a §4.9: indicadores técnicos, patrones, backtest, validación anti-sobreajuste (purga, CPCV, DSR, PBO, PSR, MinTRL, BH), volatilidad (HAR), conformal, estudio de eventos, estacionalidad, rupturas estructurales, lead-lag, régimen, factores, carry, impacto de mercado.

### 5.2 `domain/` — objetos inmutables y validados (~4.900 líneas)

**Qué hay.** `instruments` (`Instrument`, `AssetClass` con nueve clases incluida `CRYPTO`, `Exchange`, identificadores), `money` (`Currency` ISO, unidades menores), `time` (`Frequency` 1m-1y, `MarketSchedule`, base de anualización), `series` (`PriceSeries`, `ReturnSeries`, `SeriesStats`, `resample`), `panel` (`AlignedPanel` con máscara de observado y antigüedad, correlación), `portfolio` (`Portfolio`, `Holding`, pesos, `RebalancePolicy`, métricas, `weight_problems()`), `economic` (bitemporal), `fx`, `rates`, `metrics`, `quality`, `simulation`, `optimization`, `planning`, `errors`.

**Qué le falta.** Tipos para todo lo que tiene estado o no es un precio: `FlowSeries` (delta, CVD), `RateSeries` (funding), `Universe` PIT, `IndicatorSet`, `PatternEvents`, `Strategy`/`StrategySpec`, `BacktestConfig`/`BacktestResult`/`Trade`/`CostModel`, `ExperimentRun`/`Trial`, `Ledger`/`Transaction`/`Lot`, `Order`/`Fill`/`Position`/`RiskPolicy`, `AlertRule`, entidades on-chain.

### 5.3 `ports/` — contratos (~460 líneas)

**Qué hay.** `MarketDataProvider`, `EconomicDataProvider`, `ProviderCapabilities` (conjuntos de datos, clases de activo, frecuencias, histórico máximo, clave, cuotas, identificadores que sirve), `BarsRequest`, `EconomicRequest` con `VintageMode`, `SeriesStore`, `TradingCalendar`, jerarquía de errores de proveedor.

**Qué le falta.** `Dataset` nuevos (funding, OI, libro, L/S, opciones), y puertos nuevos: `ReferenceDataProvider`, `SentimentProvider`, `NewsProvider`, `OnChainDataProvider`, `OptionsDataProvider`, `ExecutionVenue`, repositorios (`PortfolioRepository` ya previsto, más `LedgerRepository`, `StrategyRepository`, `ExperimentRepository`, `PaperAccountRepository`, `OrderRepository`, `AlertRepository`), `Notifier`, `JobQueue`, `Clock` (previsto).

### 5.4 `services/` — casos de uso (~900 líneas)

**Qué hay.** `market_data` (caché primero, enrutado por capacidades, *fallback*, descarga concurrente con `BatchResult`, detección de revisiones), `registry` de proveedores, `fx` (conversión *as-of*), `risk_free` (tipo libre de riesgo PIT por divisa), `quality`.

**Qué le falta.** Servicios de backtest, investigación (Laboratorio), seguimiento de predicciones, carteras persistidas, *paper*, OMS, alertas, notificaciones, on-chain, noticias.

### 5.5 `adapters/` — infraestructura (~2.200 líneas)

**Qué hay.** Cliente HTTP (httpx + reintentos + límites de llamadas + redirecciones en el mismo origen + higiene de errores), proveedores Yahoo (`chart`, sedes, peniques → libras, sesión en curso excluida), BCE (tipos de referencia, €STR, calendario TARGET) y ficheros locales (CSV/Parquet + `instruments.toml`), almacén Parquet + DuckDB con caché incremental y memoria acotada, calendarios de `exchange_calendars`, importador de ficheros con Pydantic.

**Qué le falta.** ccxt (lectura de mercado y, aparte, ejecución), CoinGecko, Deribit, alternative.me, CryptoCompare, Blockscout, Blockchair, Blockchain.com, data.binance.vision (volcados históricos), y la persistencia relacional (SQLAlchemy) que hoy no existe.

### 5.6 `reporting/` (~3.900 líneas)

**Qué hay.** `report()` en Markdown bilingüe con diagnósticos que explican la fiabilidad de las cifras, `plots_report()` con matplotlib, informes de serie, cartera, simulación, optimización y planificación, `i18n.py` con pares (es, en) y formateo de cifras.

**Qué le falta.** Informes de backtest (el veredicto ROBUSTA/FRÁGIL/SOBREAJUSTADA de `backtest_report.py` encaja aquí, en bilingüe), dosier de estrategia, informe de *paper*, de riesgo del libro y de carry, y las notas de metodología.

### 5.7 `modules/` + `toolkit.py`

**Qué hay.** Registro de módulos del máster con `ModuleInfo`, requisitos redactados por vosotros y matriz de trazabilidad generada (`just traceability`); `b1_toolkit`. `Toolkit` es la fachada pública síncrona y asíncrona y el *composition root* para notebooks.

**Qué le falta.** Los módulos de CryptoWorld no son bloques del máster. Propuesta en §6.2.

### 5.8 `apps/api` — FastAPI sin estado (~2.400 líneas, 15 rutas)

**Qué hay.** `/health/live|ready`, `/api/v1/providers`, `/modules`, `/modules/{slug}`, `/market/bars`, `/market/compare`, `/market/quality`, `/rates/risk-free`, `/portfolios/validate`, `/portfolios/analytics`, `/portfolios/report`, `/simulations`, `/optimizations`, `/plans`. RFC 9457 con `type` documentado, `X-Request-ID`, CORS, límites, contrato OpenAPI versionado que regenera los tipos de la web y que la CI exige.

**Qué le falta.** Persistencia, auth, trabajos asíncronos (los backtests y el Laboratorio no caben en una petición síncrona), y todos los routers de las fases G1-G11.

### 5.9 `apps/web` — Next.js 16 (~6.900 líneas, 7 pantallas)

**Qué hay.** Visión general, mercados (explorador con velas, calidad, comparación), cartera (constructor con validación en vivo y análisis), Monte Carlo, optimización con frontera, planificación, módulos del máster. ES/EN, tema oscuro y claro, cliente tipado desde OpenAPI, Vitest y Playwright con datos sintéticos.

**Qué le falta.** Comparado con las 25 páginas de CryptoWorld: ficha de activo, análisis técnico, Laboratorio, dosier de estrategia, *paper*/*trading*, cripto (derivados, carry, on-chain), alertas y notificaciones, noticias, metodología, ajustes con seguridad y salud de datos.

### 5.10 Calidad y documentación

**Qué hay.** 28 ADR, guías (Toolkit, fuentes, API, web, optimización, planificación), arquitectura (capas, dominio, ingesta, informes, simulación, flujo), referencia generada, notebooks que un test ejecuta de principio a fin, casetes de proveedores, contrato común de proveedores, `detect-secrets`, *Conventional Commits* validados por *hook*.

**Esto es lo que no se negocia al portar.** Todo lo que venga de CryptoWorld entra con tipos completos, docstrings, tests de propiedades donde haya invariantes, casetes para cada proveedor nuevo, ADR para cada decisión y su entrada en `CLAUDE.md` si cambia una convención.

---

## 6. Arquitectura destino en Finances

### 6.1 Dónde va cada cosa, por capa

```
packages/investinglab/src/investinglab/
  analytics/
    technical/        indicadores vectorizados (sustituye a `ta`)                 ← §4.2
    patterns/         sucesos de acción del precio (FVG, OB, barridas, CRT, ORB…) ← §4.2
    structure.py      pivotes, S/R, divergencias                                 ← §4.2
    backtest/         motor: señales → operaciones → equity, costes, carry, cortos ← §4.7
    validation/       purged_cv, cpcv, deflated_sharpe, pbo, psr_mintrl, wilson,
                      benjamini_hochberg, mcnemar, null_worlds, power           ← §4.7, §4.8 bis
    volatility/       realized, har, diebold_mariano, fragility (HAR-X)          ← §4.5
    conformal.py                                                                 ← §4.5
    events.py         estudio de eventos con controles emparejados                ← §4.4
    seasonality.py    rejilla de calendario con nulo por permutación              ← §4.4
    structural_break.py, lead_lag.py, regime.py                                  ← §4.4
    factors.py        regresión con Newey-West; factores cripto y Fama-French     ← §4.7
    carry.py          funding / préstamo / roll como coste o rendimiento          ← §4.6
    impact.py         impacto de mercado y capacidad                              ← §4.7
    labeling.py       triple barrera, meta-etiquetado                             ← §4.8
    search/           gramática de estrategias, compilador, GA, NSGA-II           ← §4.8
    (ya existen: returns, descriptive, drawdown, risk, covariance, portfolio,
     montecarlo, optimization, quality)
  domain/
    flow.py, rates_series.py (funding), universe.py, indicators.py
    strategy.py       StrategySpec validado, hash de definición
    backtest.py       BacktestConfig, CostModel, BacktestResult, Trade, veredicto
    research.py       ExperimentRun, Trial, Preset con su tasa de falsos positivos medida
    ledger.py         Ledger, Transaction, Lot, Holding (cantidades)
    trading/          Order (máquina de estados), Fill, Position, RiskPolicy, KillSwitch (Decimal)
    alerts.py         AlertRule, Condition, flanco, cooldown
    onchain.py        Address, Transfer, FlowTree, RiskScore (G9)
  ports/
    market_data.py    + Dataset.FUNDING/OPEN_INTEREST/ORDER_BOOK/LONG_SHORT/OPTIONS
    reference.py, sentiment.py, news.py, onchain.py, options.py
    execution.py      ExecutionVenue
    repositories.py   Ledger/Strategy/Experiment/Paper/Order/Alert repositories
    notifier.py, jobs.py, clock.py
  services/
    research.py, backtest.py, predictions.py, ledger.py, paper.py, oms.py,
    alerts.py, notifications.py, carry.py, fragility.py, onchain.py, news.py
  adapters/providers/
    ccxt/, coingecko/, deribit/, alternative_me/, cryptocompare/,
    blockscout/, blockchair/, blockchain_com/, binance_vision/
  reporting/
    backtest_report.py, strategy_dossier.py, ledger_report.py, carry_report.py,
    methodology.py (notas bilingües, con test que exige que existan)
apps/
  api/        + persistence/ (SQLAlchemy 2 async + Alembic), security/ (JWKS, PAT),
              routers v1: assets, technical, research, backtests, ledger, paper,
              trading (solo lectura e intenciones), alerts, crypto, onchain, news, methodology
  worker/     jobs: refrescos, backtests largos, Laboratorio, resolución de predicciones,
              evaluación de alertas, digests, reconciliación nocturna, mundos nulos   (F13)
  trader/     NUEVO · proceso de ejecución propia: consume intenciones, OMS, outbox,
              reconciliador, kill-switch. Solo existe si INVESTINGLAB_LIVE_TRADING=true
  collector/  NUEVO · WebSockets de exchanges para orderflow (G11)
  web/        + pantallas de §5.9
```

Dos reglas para que esto no rompa la arquitectura actual:

1. **`analytics/` sigue sin conocer el dominio.** El motor de backtest recibe arrays de señales, precios y costes; `domain/backtest.py` es quien lo envuelve con `PriceSeries`, `Instrument` y calendario. Es la misma división que ya existe entre `analytics/montecarlo.py` y `domain/simulation.py`.
2. **Nada de Django ni de SQLAlchemy en el núcleo.** Los repositorios son `Protocol` en `ports/` y se implementan en `apps/api/persistence/`. El paper y el OMS se pueden probar con repositorios en memoria (`tests/support/fakes.py` ya sigue ese patrón).

### 6.2 Módulos del máster y módulos de producto

El registro de `modules/` hoy significa «bloque del máster». Lo que viene de CryptoWorld son funcionalidades de producto, no bloques. Propongo (a confirmar en un ADR):

- Mantener `modules/` para el máster, con su trazabilidad.
- Registrar las funcionalidades de producto en un **registro de capacidades** (`capabilities/` o una sección del mismo registro con `kind = "product"`), con el mismo mecanismo: requisito redactado → código → tests → matriz. La matriz de paridad con CryptoWorld (§9) se genera de ahí.
- Cuando un bloque del máster cubra lo mismo que una pieza portada (por ejemplo, el bloque de *backtesting* o el de ML), el bloque **usa** el núcleo y su matriz enlaza a los mismos tests, sin duplicar código.

### 6.3 Por qué `apps/trader` es un proceso aparte

- **Aislamiento de fallos:** si la API o la web caen, no se envía ninguna orden por accidente, y si el *trader* cae, la web sigue sirviendo análisis.
- **Superficie de claves mínima:** solo el *trader* descifra las claves del *exchange*.
- **Desactivado en código para SaaS:** en el modo multiusuario, `apps/trader` simplemente no se despliega y la API no tiene ruta que envíe órdenes (solo registra intenciones de *paper*). La frontera regulatoria se ve en el árbol de carpetas.
- **Un solo escritor:** igual que el *collector* de orderflow, el *trader* corre con un bloqueo de instancia única para que nunca haya dos procesos enviando órdenes de la misma cuenta.

### 6.4 Persistencia y almacén

- **PostgreSQL** (F6) para todo lo transaccional: usuarios, carteras y libro, estrategias, experimentos, *paper*, órdenes, alertas, notificaciones.
- **Parquet + DuckDB** (ya existe, ADR-0011) para series: velas, flujo por vela, funding, OI, métricas on-chain, *footprint* agregado. La auditoría de orderflow proponía guardar el *footprint* en `ArrayField` de Postgres; en Finances encaja mejor como Parquet particionado por `dataset/provider/symbol/year`, que es justo lo que DuckDB lee rápido.
- **Registros *append-only*** (experimentos, ejecución, auditoría de seguridad): tabla sin `UPDATE` ni `DELETE` para el rol de la aplicación, con `hash` encadenado. Es la base de la reproducibilidad del Laboratorio y del rastro WORM del OMS.
- **Multiusuario desde el primer modelo (D3):** toda tabla de usuario lleva `owner_id`, todas las consultas pasan por un filtro de propietario y los tests lo comprueban. Es barato al principio y carísimo de añadir después.

---

## 7. Mapa de correspondencia módulo a módulo

**Acción:** Portar · Generalizar · Reescribir · Sustituir (Finances ya lo tiene mejor) · Dejar.
**Prioridad:** P1 imprescindible para tener el mismo nivel, P2 importante, P3 opcional.

| # | Módulo de CryptoWorld | Ficheros principales | Destino en Finances | Acción | Fase | Prio |
|---|---|---|---|---|---|---|
| 1 | Clientes de exchange (lectura) | `binance_client`, `kucoin_client`, `ohlcv_fetcher` | `adapters/providers/ccxt/` | Reescribir (ccxt) | G1 | P1 |
| 2 | Catálogo y capitalización | `coingecko_client`, `get_assets`, `get_market_overview` | `ports/reference.py` + `adapters/providers/coingecko/` | Portar | G1 | P2 |
| 3 | Almacén de velas | `OhlcvCandle`, `ohlcv_store`, `backfill_ohlcv` | `adapters/storage/parquet.py` (ya existe) | Sustituir | — | — |
| 4 | Flujo por vela (delta, CVD) | columnas de flujo que `ohlcv_fetcher` descarta | `domain/flow.py` + ccxt/Binance | Nuevo | G1 | P1 |
| 5 | Calidad de datos | `data_quality`, `ohlcv_health` | `services/quality.py` | Sustituir (+ reconciliación entre fuentes) | G1 | P2 |
| 6 | Universo *point-in-time* | `universe`, `sync_asset_lifecycle` | `domain/universe.py` | Generalizar | G1 | P1 |
| 7 | Divisas | `get_fx_rates` | `services/fx.py` (BCE, *as-of*) | Sustituir | — | — |
| 8 | Indicadores y panel de señales | `technical_analysis_service` | `analytics/technical/` | Generalizar (sin `ta`) | G2 | P1 |
| 9 | Patrones de velas y acción del precio | `price_patterns`, `detect_candle_patterns` | `analytics/patterns/` | Generalizar (sesión del calendario) | G2 | P1 |
| 10 | Estructura de precio, MTF, Fibonacci | `price_structure`, `get_mtf_confluence` | `analytics/structure.py` | Portar | G2 | P2 |
| 11 | Confluence Card y fusión | `confluence_service`, `confluence_fusion` | Ficha de activo con pilares por clase | Generalizar | G2 (+G0) | P2 |
| 12 | Terminal cuant | `quant_metrics` | `domain` + `analytics/risk` | Generalizar | G2 | P2 |
| 13 | Régimen, lead-lag | `regime`, `market_regime`, `lead_lag` | `analytics/regime.py`, `lead_lag.py` | Portar | G5 | P2 |
| 14 | Mapa de correlaciones | `correlation_heatmap` | `domain/panel.py` + capa de incertidumbre | Sustituir + portar mejoras | G5 | P2 |
| 15 | Rupturas estructurales | `structural_break`, `correlation_watch` | `analytics/structural_break.py` | Portar + exponer | G5 | P2 |
| 16 | Estacionalidad | `seasonality` | `analytics/seasonality.py` | Generalizar + exponer | G5 | P3 |
| 17 | Calendario y estudio de eventos | `economic_calendar`, `event_study` | `analytics/events.py` + macro PIT | Generalizar + exponer | G5 | P2 |
| 18 | HAR y potencia | `volatility_forecast` | `analytics/volatility/` | Portar | G5 | P1 |
| 19 | Índice de Fragilidad | (no existe; datos sí) | `services/fragility.py` | Nuevo | G5 | P1 |
| 20 | Opciones | `option_moments`, `deribit_client` | `ports/options.py` + Deribit | Portar | G5 | P3 |
| 21 | Conformal | `conformal` | `analytics/conformal.py` | Portar | G4 | P2 |
| 22 | Derivados (funding, basis, OI) | `derivatives_metrics`, `funding_store`, `derivatives_store` | nuevos `Dataset` + `RateSeries` | Generalizar (multi-*venue*) | G1 | P1 |
| 23 | Carry | `carry`, `carry_test`, `funding` | `analytics/carry.py` + Mesa de carry | Generalizar + exponer | G5 | P1 |
| 24 | Motor de backtest | `backtest_execution`, `backtest_metrics` | `analytics/backtest/` + `domain/backtest.py` | Generalizar (costes, calendario, dividendos) | G3 | P1 |
| 25 | Sesgos y robustez | `backtest_bias`, `backtest_robustness`, `backtest_report` | `analytics/validation/` + `reporting/backtest_report.py` | Portar | G3 | P1 |
| 26 | Validación cruzada purgada, CPCV | `purged_cv`, `backtest_robustness` | `analytics/validation/` | Portar | G3 | P1 |
| 27 | Significancia | `significance` | fundir en `analytics/risk.py` + `validation/` | Portar sin duplicar | G3 | P1 |
| 28 | Impacto y capacidad | `market_impact` | `analytics/impact.py` | Generalizar (divisa) | G3 | P2 |
| 29 | Factores | `crypto_factors`, `factor_study` | `analytics/factors.py` | Generalizar (+ Fama-French) | G3 | P2 |
| 30 | Gramática de estrategias | `strategy_spec` | `analytics/search/` + `domain/strategy.py` | Portar | G4 | P1 |
| 31 | GA y NSGA-II | `strategy_generator`, `strategy_nsga` | `analytics/search/` | Portar | G4 | P1 |
| 32 | Evaluación y *gating* | `strategy_evaluation`, `generation_power` | `services/research.py` | Reescribir (más pequeño, N del registro) | G4 | P1 |
| 33 | Búsqueda en dos fases | `block_sampling` | — | Dejar (comprobación negativa) | — | — |
| 34 | Triple barrera, meta-modelo | `labeling`, `meta_model`, `meta_sizing` | `analytics/labeling.py` | Portar | G4 | P2 |
| 35 | Retests, SPP, incubación | `strategy_evaluation`, `incubation` | `services/research.py` | Portar | G4 | P1 |
| 36 | Registro de experimentos | `StrategyExperimentRun` | `domain/research.py` + tabla *append-only* | Reescribir | G0/G4 | P1 |
| 37 | Mundos nulos | `nullexp.py` (fuera del repo) | `analytics/validation/null_worlds.py` + CI | Nuevo | G3 | P1 |
| 38 | Cartera de estrategias | `strategy_portfolio`, `hrp`, `portfolio_analysis` | `analytics/optimization.py` (HRP ya existe) | Sustituir HRP + portar el resto | G4 | P2 |
| 39 | Reoptimización nocturna, monitorización | `reoptimize_strategies`, `monitor_strategies` | `apps/worker` | Portar (acumula N) | G4 | P2 |
| 40 | Predicción ML | `predict_price_direction`, `track_predictions` | Laboratorio (`investinglab[ml]`) | Portar + baseline + *champion-challenger* | G4 | P2 |
| 41 | Exógenas y MDA | `exogenous_features`, `feature_importance`, `feature_study` | Laboratorio + macro PIT | Generalizar | G4 | P2 |
| 42 | `edge_test` | `edge_test` | `analytics/validation/power.py` | Portar + exponer | G3 | P1 |
| 43 | Posiciones y operaciones | `Position`, `TradeHistory`, `*_position`, `add_trade` | `domain/ledger.py` | Reescribir (libro con lotes y divisas) | G6 | P1 |
| 44 | Riesgo del libro | `portfolio_risk`, `risk_attribution` | `domain/portfolio.py` (riesgo ya existe) | Sustituir + portar estrés y factor | G6 | P1 |
| 45 | Exportación | `export_reports` | `reporting/` (MD, CSV; PDF previsto) | Portar | G6 | P3 |
| 46 | Paper trading | `paper_trading` | `services/paper.py` | Reescribir (simulador común con backtest) | G7 | P1 |
| 47 | OMS y ejecución real | `ccxt_broker`, `broker_trading`, `LiveRiskPolicy` | `domain/trading/` + `apps/trader` | Reescribir (outbox, `Decimal`) | G7 | P1 |
| 48 | Puerta del dinero real | `paper_trading` (1.346) | `services/oms.py` | Portar | G7 | P1 |
| 49 | TCA, auditoría, coste y ventana de ejecución | `tca`, `execution_audit`, `execution_cost`, `execution_window` | `analytics/impact.py` + `services/oms.py` | Portar | G7 | P2 |
| 50 | Cifrado de claves | `security/crypto.py` (`MultiFernet`) | `apps/trader` + gestor de secretos | Portar | G7 | P1 |
| 51 | Alertas de precio y cuant | `manage_alerts`, `quant_alert_rules`, `evaluate_quant_alerts` | `domain/alerts.py` + `apps/worker` | Generalizar | G8 | P1 |
| 52 | Notificaciones y digests | `notifications`, `web_push`, `send_*_digest` | `ports/notifier.py` + canales | Portar (+ Telegram, *webhooks*) | G8 | P2 |
| 53 | Tiempo real | `ws/consumers` | SSE (F13) | Reescribir | G8 | P2 |
| 54 | On-chain y forense | 12 casos de uso, 6 servicios, 3 clientes | `ports/onchain.py` + sección Cripto | Portar | G9 | P3 |
| 55 | Noticias | `get_news_feed`, `news_geography` | `ports/news.py` | Portar | G10 | P3 |
| 56 | Auth y usuarios | rutas `auth/*`, 2FA y códigos de recuperación | Better Auth + JWKS (F7) | Sustituir | G0 | P1 |
| 57 | Administración | `admin_views`, `AdminDashboardPage` | Panel mínimo (proveedores, jobs, cuotas) | Reescribir | G0 | P3 |
| 58 | Metodología | `methodology`, `MethodologyPage` | `reporting/methodology.py` + `/methodology` | Portar | G3 | P1 |
| 59 | Landing SEO | `interfaces/web/views.py` | Next.js SSR | Reescribir | G12 | P3 |
| 60 | Academia, *tour*, PWA, push | `LearnPage`, `OnboardingTour`, `sw.js` | web | Portar | G12 | P3 |
| 61 | Visualizaciones 3D | `viz3d/`, `*3D.tsx` | — | Dejar (salvo prueba de utilidad) | — | — |
| 62 | Orderflow | (apenas existe) | `apps/collector` + `analytics/orderflow/` | Nuevo | G11 | P2 |

---

## 8. Plan por fases para elevar Finances

Las fases G0-G13 sustituyen a la fase F12 del plan maestro y se apoyan en F6, F7, F10, F13 y F14, que ya estaban previstas. Cada fase va en su rama `feat/*` desde `development`, con *Conventional Commits* en inglés, ADR en el mismo PR, `just check` en verde y el resumen de cierre (hecho, pendiente, deuda) que exige `CLAUDE.md`.

**Esfuerzo:** semanas a 25-30 h/semana. Son estimaciones mías a partir del tamaño del código de origen, no mediciones.

| Fase | Contenido | Semanas | Acumulado |
|---|---|---|---|
| G0 | Plataforma con estado (F6 + F7 + F13 + F10) | 4-6 | 4-6 |
| G1 | Datos cripto y derivados | 2-3 | 6-9 |
| G2 | Análisis técnico multiactivo y ficha de activo | 2-3 | 8-12 |
| G3 | Backtest, validación, mundos nulos y metodología | 3-4 | 11-16 |
| G4 | Laboratorio de estrategias (generador + ML mejorados) | 4-6 | 15-22 |
| G5 | Volatilidad, fragilidad, carry y relaciones entre activos | 3-4 | 18-26 |
| G6 | Libro de operaciones y riesgo del usuario | 3-4 | 21-30 |
| G7 | Paper trading y ejecución propia | 3-4 | 24-34 |
| G8 | Alertas, notificaciones y tiempo real | 2 | **26-36: mismo nivel funcional que CryptoWorld en lo esencial** |
| G9 | On-chain y forense | 3 | 29-39 |
| G10 | Noticias y sentimiento | 1 | 30-40 |
| G11 | Orderflow | 7-10 | 37-50 |
| G12 | Preparado para SaaS | 3-5 | 40-55 |
| G13 | Retirada de CryptoWorld | 1 | 41-56 |

Es decir: **unos 6-8 meses hasta la paridad en lo esencial (G0-G8)** y unos 10-13 meses con todo. G9-G12 son P2-P3 y se pueden reordenar o recortar sin afectar al resto. Si el máster introduce un bloque que cubra algo de esto (*backtesting*, ML), conviene hacer coincidir la fase con el bloque para que el módulo del máster use el núcleo en lugar de duplicarlo.

**Orden acordado (D6, 11-nov-2026).** G0 se reparte en tres partes y se intercala con las fases que no dependen de toda ella, sin saltarse ningún requisito:

| Paso | Contenido | Por qué ahí |
|---|---|---|
| G0a | Persistencia (F6): PostgreSQL, propietario en todas las tablas, registro *append-only*, carteras guardadas | Base de todo lo que tiene estado |
| G1, G2 | Datos cripto y derivados; análisis técnico y ficha de activo | No necesitan cola de trabajos ni usuario |
| G0b | Trabajos en segundo plano (F13) y observabilidad mínima | Los backtests y el Laboratorio no caben en una petición |
| G3, G4, G5 | Backtest y validación; Laboratorio; volatilidad, fragilidad, carry y relaciones entre activos | Usan la cola y el registro de experimentos |
| G0c | Acceso con usuario (F7) y contenedores (F10) | Antes de guardar el libro de operaciones de nadie |
| G6-G13 | Libro y riesgo, *paper* y ejecución propia, alertas, on-chain, noticias, orderflow, SaaS y retirada | Igual que en la tabla anterior |

### G0 — Plataforma con estado

**Por qué primero:** sin base de datos, sin usuario y sin cola de trabajos no se puede portar nada de lo que tiene estado (más de la mitad de §7).

**Contenido.**
- F6: PostgreSQL + SQLAlchemy 2 asíncrono + Alembic en `apps/api/persistence/`; repositorios como `Protocol` en `ports/`; `owner_id` en todas las tablas de usuario con un filtro obligatorio y tests que lo prueban; Postgres como servicio en la CI; carteras persistidas (`PortfolioRepository`) como primer caso.
- Tabla *append-only* genérica con *hash* encadenado (experimentos, ejecución, auditoría de seguridad), y un test que verifica que la aplicación no puede hacer `UPDATE` ni `DELETE` sobre ella.
- F7: Better Auth (contraseña, *passkeys*, TOTP obligatorio, códigos de recuperación), sesiones en cookie `HttpOnly`, verificación JWKS en la API detrás de `TokenVerifier`, PATs con *scopes*, *rate limiting*, cabeceras de seguridad. Registro público desactivado; primer usuario por CLI.
- F13: `apps/worker` con la cola elegida en el ADR (§10.2), trabajos con id, estado, progreso y resultado, y endpoints `202 + Location` para trabajos largos (el patrón que ya usa CryptoWorld para el generador y los backtests robustos).
- F10: Dockerfiles multi-etapa sin root y Compose (api, web, worker, postgres).
- Observabilidad mínima (adelantar parte de F14): Sentry u OpenTelemetry en API y *worker*, y un *heartbeat* de frescura por fuente de datos. Es requisito de cualquier proceso 24/7 posterior.

**Terminado cuando:** una cartera se guarda, se lista y se borra con usuario autenticado; un trabajo largo se lanza, se consulta y termina; Playwright cubre *login* con TOTP; la CI levanta Postgres y pasa.

### G1 — Datos cripto y derivados

**Contenido.**
- `adapters/providers/ccxt/`: velas (con paginación e histórico por *exchange*) para Binance, Bybit, OKX, Kraken y Coinbase; funding, OI, foto del libro y ratio L/S para los que tienen perpetuos (Binance, Bybit, OKX). Declara `ProviderCapabilities` (cripto, 1m-1mo) y entra en el contrato común de proveedores con casetes grabadas.
- Política de enrutado para cripto: ccxt (Binance) → ccxt (Kraken) → Yahoo (`BTC-USD`) como último recurso, configurable.
- `domain/flow.py` (`FlowSeries`: `quote_volume`, `num_trades`, `taker_buy_base`, `taker_buy_quote`, delta, CVD) alineado por índice con su `PriceSeries`. Es la F0 de orderflow: delta y CVD con historia desde 2017.
- `RateSeries` para funding por instrumento y *venue* (ADR).
- `domain/universe.py` (PIT) con fechas de alta y baja, aplicable a cualquier clase de activo.
- CoinGecko (metadatos, capitalización, dominancia) y alternative.me (Fear & Greed) tras sus puertos.
- `adapters/providers/binance_vision/` para volcados históricos (velas y, en G11, `aggTrades`).

**Terminado cuando:** `tk.series("BTC/USDT", venue="binance", frequency="1h")` devuelve una `PriceSeries` validada con su `FlowSeries`; el funding de BTC en tres *venues* sale alineado; los tests de contrato pasan para ccxt sin red.

**Decisión al implementarla (13-11-2026):** en lugar de ccxt, un adaptador por *venue* sobre `HttpClient`, con casetes ([ADR-0032](../adr/0032-crypto-venues-on-the-shared-http-client.md)): ccxt salta la capa de red común y sus peticiones no se pueden reproducir con `respx`. La notación de símbolos es la de ccxt (`BTC/USDT`, `BTC/USDT:USDT`) y el enrutado la reconoce sola, así que `tk.series("BTC/USDT", frequency="1h")` va a Binance sin indicar el *venue*. Hechos: Binance *spot* (velas y flujo), funding de OKX, volumen de Yahoo como flujo. Pendientes: el resto de la lista.

### G2 — Análisis técnico multiactivo y ficha de activo

**Contenido.**
- `analytics/technical/` con los ~25 indicadores del catálogo de `strategy_spec` vectorizados en NumPy; `analytics/patterns/` con el vocabulario de `price_patterns` y las 12 velas japonesas; `analytics/structure.py` (pivotes, S/R, divergencias, Fibonacci); confluencia multimarco.
- Tests de paridad con CryptoWorld: casetes con su salida sobre las mismas velas, tolerancia fijada; tests de propiedades (escalar precios no cambia el RSI; los indicadores no miran al futuro: truncar la serie no cambia los valores pasados).
- Ficha de activo multiactivo con registro de pilares por `AssetClass` (técnica para todos; derivados y on-chain para cripto; macro y, más tarde, fundamentales para acciones). El pilar ML y los pesos aprendidos llegan en G4.
- API `/api/v1/assets/{id}/technical`, `/patterns`, `/levels`, `/card`; pantallas de ficha de activo y de análisis técnico.

**Terminado cuando:** la misma ficha funciona con `SAN.MC`, `^GSPC`, `EURUSD=X` y `BTC/USDT`, y los tests de paridad pasan.

**Avance (13-11-2026):** los 26 indicadores del catálogo de `strategy_spec` ya están en `analytics/technical/` con las definiciones de `ta` ([ADR-0034](../adr/0034-technical-indicators-in-numpy.md)). La paridad se graba ejecutando el código de CryptoWorld (`just record-parity`): 61 casos sobre 396 velas reales, que coinciden salvo en el calentamiento que `ta` inventa.

### G3 — Backtest, validación, mundos nulos y metodología

**Contenido.**
- `analytics/backtest/`: señales → operaciones → *equity*, con relleno a la apertura siguiente según el calendario, largos y cortos, comisión por mercado, *spread*, deslizamiento, `CarryCost` (funding, préstamo de títulos, *roll*), dividendos vía precio ajustado o retorno total, impuesto de transacciones financieras donde aplique, dimensionado por convicción.
- `analytics/validation/`: purga y embargo, CPCV, DSR con el N del registro, PBO con las pruebas reales, PSR y MinTRL, Wilson, BH, McNemar, potencia (`edge_test`), detectores de *look-ahead* y recursividad. `significance.py` se funde con lo que ya hay en `analytics/risk.py`.
- **Banco de mundos nulos** (`null_worlds.py`) como test nocturno de CI con umbral del 5 % por *preset*.
- Factores: cripto (tres factores) y, cuando entre F11, Fama-French y q-factors.
- `reporting/backtest_report.py`: veredicto ROBUSTA/FRÁGIL/SOBREAJUSTADA bilingüe, con la incertidumbre de cada cifra y el N de configuraciones probadas al lado de cada Sharpe.
- `reporting/methodology.py` + `/api/v1/methodology` + pantalla de metodología, con un test que exige una nota por cada cifra propia.
- API asíncrona `/api/v1/backtests` (202 + trabajo).

**Terminado cuando:** un backtest de una estrategia sobre una acción española y sobre BTC sale con costes reales y veredicto; el test nocturno de mundos nulos está en verde y publica su tasa.

### G4 — Laboratorio de estrategias

Es la propuesta de §4.8 bis llevada a fase.

**Contenido.**
- Gramática (`StrategySpec` validado y con *hash* de definición), compilador causal, GA, NSGA-II, *gating* con N del registro, cascada de retests, SPP, incubación, triple barrera, meta-modelo y *sizing* por convicción.
- Tres tipos de objetivo (dirección, magnitud/riesgo, carry) con su métrica y su nulo.
- *Presets* con su tasa de falsos positivos medida y mostrada.
- ML como modelo del Laboratorio (`investinglab[ml]`), con baseline ingenuo, *champion-challenger* por McNemar, conformal, `PredictionRecord` con resolución diferida en el *worker* y deriva.
- Exógenas PIT de cripto y de macro (BCE ya, FRED/ALFRED cuando estén).
- Reoptimización nocturna que acumula N.
- Pantallas: Laboratorio (frontera de Pareto 2D, curva E[máx SR] frente a N, distribución nula con la estrategia marcada, «casi aprobadas» con su motivo), dosier de estrategia, comparador, cartera de estrategias.

**Terminado cuando:** repetir el experimento del 6-ago sobre Finances da < 5 % de ejecuciones con falsos positivos en todos los *presets*, y una estrategia propia (por ejemplo, tu TCP en versión Python) sale con su percentil frente al nulo.

### G5 — Volatilidad, fragilidad, carry y relaciones entre activos

**Contenido.**
- HAR, Diebold-Mariano, potencia, conformal; **Índice de Fragilidad** (HAR-X con funding, OI, basis, profundidad, RV multiescala; descomposición por componente; criterio de abandono si no bate a la persistencia fuera de muestra con purga).
- **Mesa de carry** multi-*venue*: rendimiento neto de costes a tu tamaño, distancia a liquidación, probabilidad de margen, distribución nula, dislocación entre *venues*.
- Régimen, lead-lag (con aviso de *trading* no sincrónico), mapa de correlaciones con incertidumbre, rupturas estructurales con FDR, estacionalidad por calendario del mercado, calendario económico con fechas de publicación y estudio de eventos.
- Todo con endpoint y pantalla: aquí se cierra el hueco de §1.6.

**Terminado cuando:** las siete investigaciones que en CryptoWorld solo eran comandos tienen API, pantalla y nota de metodología, y el Índice de Fragilidad publica su R² fuera de muestra (sea bueno o malo).

### G6 — Libro de operaciones y riesgo del usuario

**Contenido.**
- `Ledger` → `Transaction` → `Lot` → `Holding` en `Decimal`, multidivisa con FX *as-of*, largos y cortos, comisiones, dividendos, *splits*, transferencias entre cuentas.
- Importación de extractos (CSV de *brokers* y *exchanges*), con el importador estricto que Finances ya tiene.
- P&L realizado y no realizado en divisa base; pesos reales frente a pesos objetivo (y aviso de rebalanceo en G8).
- Riesgo del libro con el motor de Finances + estrés con escenarios observados + atribución por factor.
- Digest diario de riesgo.
- Base para fiscalidad (FIFO por lote): el módulo fiscal en sí (IRPF, 720, 721) queda como fase propia posterior, porque necesita revisión normativa cuidadosa.

**Terminado cuando:** una cartera real mixta (acciones en EUR, un ETF en USD y BTC) muestra valor, P&L y riesgo coherentes en euros, con la antigüedad de cada precio.

### G7 — Paper trading y ejecución propia

**Contenido.** Todo lo de §4.11 «Al llevarlo a Finances»: dominio de órdenes con máquina de estados y `Decimal`, *outbox* con `client_order_id`, posición por *fills*, estado `UNKNOWN` reconciliable, bloqueo de cuenta, `apps/trader` como proceso único, *paper* con el mismo simulador que el backtest, puerta PSR/MinTRL + incubación, *kill-switch*, límites de pérdida diaria y concentración, TCA contra el precio de llegada, rastro *append-only*, coste a tu tamaño y ventana de ejecución, claves solo de *trade* con lista de IP.

**Terminado cuando:** pasan los cinco tests de fallo (*rollback* tras envío, *timeout* con orden ejecutada, *fill* parcial, dos *workers*, reinicio con órdenes en vuelo) contra un *exchange* falso, y una orden real mínima en tu cuenta sale, se reconcilia y aparece en la auditoría. Con `INVESTINGLAB_LIVE_TRADING=false`, ninguna ruta del sistema puede enviar una orden: un test lo comprueba.

### G8 — Alertas, notificaciones y tiempo real

**Contenido.** Reglas de alerta con flanco y *cooldown* sobre un registro de métricas multiactivo (las 16 de CryptoWorld + *drawdown* de cartera, desviación de pesos, frescura de datos, eventos del Laboratorio y de la fragilidad); canales en la app, email, Web Push, Telegram y *webhook* firmado con HMAC; SSE para notificaciones y precios; digests de mercado y de riesgo.

**Terminado cuando:** una alerta de RSI en `ITX.MC` y otra de funding en BTC llegan por Telegram una sola vez por cruce.

### G9 — On-chain y forense (P3)

Puerto `OnChainDataProvider` y adaptadores (Blockscout, Blockchair, Blockchain.com); ballenas, dinero inteligente, flujos a *exchanges*, presión, salud de red, dosier de dirección, *watchlist* de direcciones con alertas, forense (árbol de flujo, concentración, huella, riesgo, aprobaciones, grafo de entidad), seguridad de token, *wash trading*. Sección «Cripto · On-chain». Lenguaje sin imputaciones.

### G10 — Noticias y sentimiento (P3)

`NewsProvider` (CryptoCompare; GDELT o Finnhub para el resto), clasificación geográfica y temática, léxico Loughran-McDonald, Fear & Greed. Sin promesas predictivas salvo que el estudio de eventos las respalde.

### G11 — Orderflow (P2)

La propuesta de orderflow en cuatro pasos (F0-F3), adaptada a Finances: la F0 ya entra en G1; `apps/collector` como proceso único con bloqueo; normalización por *venue* (con el test de la inversión de lado de Coinbase); *footprint* 1m, perfil de volumen (POC, VA, HVN/LVN), VWAP, *big trades* por percentil, liquidaciones reales (Bybit completo, Binance como cota inferior), VPIN, OBI/OFI, *heatmap* de liquidez, absorción confirmada con libro; agregados en **Parquet** en vez de `ArrayField`; reconciliación nocturna *footprint* = vela; estudio de evidencias con BH e insignia en cada indicador. Necesita WebSocket hacia la web (§10.3).

### G12 — Preparado para SaaS (P3, opcional)

Bandera de registro público, planes y *feature flags* por nivel, *landing* SSR por activo con `sitemap` y JSON-LD, academia y *tour*, PWA y Web Push para todos, servidor MCP de solo lectura (ficha, fragilidad, carry, test nulo), página pública de salud de datos. **Antes de activarlo:** licencias de datos comerciales (§11.3), revisión regulatoria (§11.1-11.2), RGPD, y `apps/trader` fuera del despliegue SaaS.

### G13 — Retirada de CryptoWorld

Cuando la matriz de paridad (§9) esté completa: etiquetar el último `develop`, archivar el repositorio en modo solo lectura y redirigir el dominio. **Mientras el TFG siga abierto, CryptoWorld no se archiva**, y mientras siga desplegado, su mantenimiento de seguridad se lleva en su propio repositorio.

---

## 9. Matriz de paridad (criterio para retirar CryptoWorld)

| Capacidad de CryptoWorld | Criterio de «hecho» en Finances | Fase |
|---|---|---|
| Velas cripto multi-*exchange* con respaldo | ccxt en el contrato de proveedores, enrutado con *fallback* | G1 |
| Delta y CVD por vela | `FlowSeries` con test dorado `delta = 2·taker_buy_base − volume` | G1 |
| Funding, basis, OI | `RateSeries` y nuevos `Dataset`, tres *venues* | G1 |
| Universo PIT | `Universe` con altas y bajas, usado por el Laboratorio | G1 |
| Indicadores, patrones, niveles, MTF | Tests de paridad numérica con CryptoWorld | G2 |
| Confluence Card | Ficha de activo con pilares por clase de activo | G2/G4 |
| Terminal cuant | Métricas por activo en la ficha | G2 |
| Backtest con costes, cortos, funding, apertura siguiente | Mismo resultado que CryptoWorld en tres estrategias de referencia, salvo diferencias explicadas por calendario o costes | G3 |
| Suite de robustez y veredicto | `backtest_report` bilingüe con N y significancia | G3 |
| Mundos nulos | Test nocturno en verde y tasa publicada por *preset* | G3 |
| Metodología | Nota por cada cifra propia, test que lo exige | G3 |
| Generador GA y NSGA-II | Laboratorio con registro de experimentos y deflación | G4 |
| ML y seguimiento de predicciones | Modelo del Laboratorio con baseline y *champion-challenger* | G4 |
| HAR, opciones, conformal, `edge_test` | Con endpoint y pantalla | G5 |
| Carry | Mesa de carry multi-*venue* | G5 |
| Régimen, lead-lag, correlaciones, rupturas, estacionalidad, eventos | Con endpoint y pantalla | G5 |
| Posiciones, operaciones, exportación | Libro con lotes, multidivisa | G6 |
| VaR/CVaR, estrés, atribución | Motor de Finances + estrés observado + factor | G6 |
| Paper trading | Mismo simulador que el backtest | G7 |
| Ejecución real, OMS, puerta, TCA, auditoría | Cinco tests de fallo en verde; orden real mínima reconciliada | G7 |
| Alertas de precio y cuant | Flanco, *cooldown*, multiactivo | G8 |
| Notificaciones en la app, push, email, digests | Canales tras `Notifier` | G8 |
| Tiempo real de precios y notificaciones | SSE | G8 |
| On-chain y forense | Sección Cripto · On-chain | G9 |
| Noticias, globo, Fear & Greed | `NewsProvider` y `SentimentProvider` | G10 |
| Auth completa con 2FA | Better Auth (mejor que el original) | G0 |
| Landing SEO, academia, PWA | Solo si se activa el modo SaaS | G12 |

---

## 10. Decisiones abiertas

Son decisiones que este documento no puede tomar por ti. Cada una debería cerrarse con un ADR al empezar la fase que la necesita. Doy mi recomendación, pero no la he dado por hecha en el plan.

1. **Gráfico de velas (G2).** El plan maestro dice Lightweight Charts; la web actual solo usa ECharts; CryptoWorld usa KLineChart por sus herramientas de dibujo e indicadores personalizados. *Recomiendo* Lightweight Charts para el gráfico principal (rendimiento con muchas velas y sistema de *plugins*; ojo, su licencia exige atribución a TradingView) y ECharts para todo lo demás. Si las herramientas de dibujo son imprescindibles para ti, KLineChart es la alternativa.
2. **Cola de trabajos (G0).** Procrastinate (sobre Postgres, sin Redis) o Taskiq + Redis. *Recomiendo* Procrastinate: una pieza menos que operar. Revisarlo en G11, porque el *collector* de orderflow probablemente necesite Redis para la difusión en vivo.
3. **Tiempo real (G8/G11).** SSE basta para notificaciones y precios agregados; el orderflow en vivo (*heatmap*, cinta) necesita WebSocket. *Recomiendo* SSE en G8 y WebSocket solo en `apps/collector` cuando llegue G11.
4. **Ejecución fuera de cripto (G7).** ccxt cubre cripto. Para acciones y ETF, ¿Interactive Brokers, Alpaca o ninguno por ahora? *Recomiendo* ninguno hasta que el Laboratorio tenga una estrategia de acciones que supere el nulo: el riesgo operativo no se justifica antes.
5. **Tipos nuevos (G1).** `FlowSeries` y `RateSeries` como tipos hermanos de `PriceSeries` y `EconomicSeries`, o una `PriceSeries` con columnas opcionales. *Recomiendo* tipos hermanos para no relajar la validación estricta (ADR-0006).
6. **Registro de capacidades de producto (G0).** Ampliar `modules/` con `kind = "product"` o crear un registro aparte (§6.2).
7. **Custodia de claves del *exchange* (G7).** `MultiFernet` con rotación en la base de datos (lo de CryptoWorld), un fichero cifrado con `age`/`sops` en el servidor del *trader*, o un KMS en la nube cuando se decida F14.
8. **Despliegue (F14).** El plan lo deja abierto (Railway, Fly.io o VPS + Caddy). CryptoWorld ya corre en Railway con roles por `SERVICE_ROLE`; esa experiencia es reutilizable, pero un proceso de ejecución con dinero real merece una máquina que controles.
9. **Indicadores (G2).** NumPy propio o TA-Lib; el ADR ya estaba previsto en el plan maestro. *Recomiendo* NumPy propio.
10. **Cuándo archivar CryptoWorld (G13).** Depende del calendario del TFG.

---

## 11. Riesgos, regulación y licencias

*No soy abogado. Esto es un mapa de riesgos para que lo valides con quien corresponda antes de abrir nada a terceros.*

### 11.1 Ejecución (MiCA)

Operar con tu propio dinero y tus propias claves no es prestar un servicio. Ejecutar, transmitir órdenes o gestionar carteras por cuenta de otros usuarios sí entra en el perímetro de proveedor de servicios de criptoactivos (CASP) de MiCA, y en España el periodo transitorio terminó el 30-jun-2026. Por eso el diseño de §6.3: en modo SaaS, `apps/trader` no se despliega y no existe ninguna ruta que envíe órdenes de otro usuario.

### 11.2 Señales publicadas

Una ficha pública que dice «COMPRA» sobre un activo concreto se acerca a una recomendación de inversión. MAR (abuso de mercado) y la supervisión de los *finfluencers* aplican a lo que se publica, no a lo que se usa en privado. En modo SaaS: lenguaje descriptivo («lectura técnica», «evidencia: dirección ✗»), sin personalización, con la metodología enlazada y sin posiciones propias sin declarar en los activos que se comentan.

### 11.3 Licencias de datos

Es la restricción más fácil de olvidar en el modo SaaS. Yahoo Finance no tiene API oficial y sus términos son de uso personal; la licencia gratuita de Tiingo es de uso personal; las claves *demo* de CoinGecko no son comerciales; el plan gratuito de Alpaca bloquea los últimos 15 minutos. Para uso personal todo esto vale. Para servir datos a terceros hace falta revisar cada fuente y, probablemente, pagar licencias. Recomiendo que cada `ProviderCapabilities` declare su licencia (el plan maestro ya lo prevé) y que el modo SaaS solo active proveedores con licencia de redistribución.

### 11.4 Datos personales

Libro de operaciones, claves de *exchange*, dosieres de direcciones *on-chain* y, en SaaS, cuentas de usuario: RGPD (base legal, minimización, derecho de supresión, registro de tratamientos). El borrado de cuenta de CryptoWorld es un buen punto de partida.

### 11.5 Fiscalidad

Un módulo fiscal (IRPF, Modelo 720, Modelo 721) debe presentarse como cálculo informativo y no como asesoramiento, y validarse con casos revisados por un profesional antes de usarlo para una declaración real.

### 11.6 Técnicos

| Riesgo | Mitigación |
|---|---|
| El porte cambia resultados sin que nadie lo note | Tests de paridad numérica con CryptoWorld en G2-G4 |
| El generador vuelve a aprobar ruido al ampliar vocabulario o activos | Mundos nulos como test nocturno; ningún cambio de vocabulario sin volver a medir |
| Orden real duplicada o huérfana | *Outbox*, `client_order_id`, `UNKNOWN` reconciliable, cinco tests de fallo |
| Procesos 24/7 que corrompen datos en silencio | Observabilidad y *heartbeat* de frescura antes de cualquier *collector* o *trader* |
| Dos plataformas a mantener durante meses | Congelar funcionalidad nueva en CryptoWorld: lo nuevo se construye en Finances (salvo correcciones de seguridad y lo que pida el TFG) |
| El alcance crece sin fin | La matriz de §9 es el criterio de terminado; lo que no está en ella va al *backlog* |

---

## 12. Prompts listos para Claude Code (sobre Finances)

Todos parten de `development`, en su rama `feat/*`, respetan `CLAUDE.md` (inglés en código y commits, sin *trailers* de autoría, ADR en el mismo PR, `just check` en verde, `CLAUDE.md` actualizado si cambian convenciones) y terminan con el resumen de hecho, pendiente y deuda.

**P-G0a · Persistencia**
> Lee `CLAUDE.md`, `docs/plan/plan-maestro.md` (secciones 8, 10 y 13) y `docs/plan/integracion-cryptoworld.md` (§6.4 y G0). Implementa F6: PostgreSQL con SQLAlchemy 2 asíncrono y Alembic en `apps/api/persistence/`, repositorios como `Protocol` en `packages/investinglab/src/investinglab/ports/repositories.py`, `owner_id` obligatorio en toda tabla de usuario con un filtro central y tests que prueban que un usuario no ve datos de otro, y una tabla *append-only* con *hash* encadenado y un test que demuestra que la aplicación no puede modificarla. Primer caso de uso: carteras guardadas (`GET/POST /api/v1/portfolios`, `GET/PUT/DELETE /api/v1/portfolios/{id}` con versión optimista). Postgres como servicio en la CI. ADR-0029 con la decisión. No toques el núcleo salvo para añadir puertos.

**P-G1 · ccxt y flujo por vela**
> Añade `adapters/providers/ccxt/` implementando `MarketDataProvider` para velas de Binance, Bybit, OKX, Kraken y Coinbase, con `ProviderCapabilities` (cripto, 1m-1mo, histórico por *exchange*), paginación y límites de llamadas del cliente HTTP común. Graba casetes con `just record-fixtures` y añade el proveedor al contrato de `tests/contract/`. Crea `domain/flow.py` con `FlowSeries` (inmutable, validada, alineada por índice con su `PriceSeries`) que guarda `quote_volume`, `num_trades`, `taker_buy_base` y `taker_buy_quote` y calcula delta y CVD; test dorado `delta = 2·taker_buy_base − volume` y tests de propiedades (`ΣΔ = ΔCVD`). Nuevos `Dataset.FUNDING` y `Dataset.OPEN_INTEREST` y un `RateSeries` para funding por *venue*. ADR con la decisión de tipos hermanos frente a columnas opcionales. Actualiza `docs/guide/data-sources.md` y la sección 16 del plan con los dominios nuevos.

**P-G2 · Análisis técnico**
> Porta a `analytics/technical/` los indicadores del catálogo de `backend/src/core/domain/services/strategy_spec.py` de CryptoWorld (RSI, StochRSI, estocástico, CCI, Williams %R, ADX, MFI, CMF, ROC, ATR %, Aroon, TRIX, ratio de volumen, SMA/EMA/WMA/Hull/KAMA, Bollinger, MACD, Ichimoku, PSAR, Donchian, Keltner) en NumPy, sin `ta`, y a `analytics/patterns/` el vocabulario de `price_patterns.py` y las 12 velas de `detect_candle_patterns`. Los patrones de sesión leen la sesión del `TradingCalendar`. Tests de paridad: casetes con la salida de CryptoWorld sobre las mismas velas (genera las casetes ejecutando el código de CryptoWorld en un script aparte, nunca a mano) y tests de propiedades (invarianza a escala, causalidad por truncado). Fachada en `domain/indicators.py` y endpoints `/api/v1/assets/{id}/technical` y `/patterns`.

**P-G3 · Backtest, validación y mundos nulos**
> Porta `backtest_execution.py`, `backtest_metrics.py`, `backtest_bias.py`, `backtest_robustness.py`, `backtest_report.py`, `purged_cv.py` y `significance.py` de CryptoWorld a `analytics/backtest/`, `analytics/validation/` y `reporting/backtest_report.py`, sin duplicar lo que ya hay en `analytics/risk.py` y `analytics/montecarlo.py`. Generaliza los costes en un `CostModel` por mercado y un `CarryCost` (funding, préstamo de títulos, *roll*); el relleno a la apertura siguiente usa el calendario. Crea `analytics/validation/null_worlds.py` portando la idea de `nullexp.py` (paseo aleatorio con la volatilidad del activo, *bootstrap* estacionario con la media restada, permutación de bloques) y un test marcado `slow` que corre cada noche y falla si la tasa de falsos positivos por ejecución supera el 5 %. Añade `reporting/methodology.py` con una nota bilingüe por cada cifra propia y un test que la exija.

**P-G7 · OMS con *outbox***
> Implementa `domain/trading/` (`Order` con máquina de estados `NEW → PENDING_SUBMIT → SUBMITTED → PARTIALLY_FILLED → FILLED | CANCELLED | REJECTED | UNKNOWN`, `Fill`, `Position`, `RiskPolicy`, `KillSwitch`, todo en `Decimal` con redondeo a `stepSize`/`tickSize`), `ports/execution.py` (`ExecutionVenue` con `client_order_id`) y `apps/trader` como proceso único con bloqueo. Patrón *outbox*: transacción corta con bloqueo de la cuenta → validar límites → orden `PENDING_SUBMIT` → *commit*; envío fuera de la transacción; transacción corta con `filled`/`average`/estado; *timeout* → `UNKNOWN` y reconciliación por `client_order_id`. La posición solo se mueve con *fills*. `INVESTINGLAB_LIVE_TRADING=false` por defecto y un test que demuestra que, así, ninguna ruta puede enviar órdenes. Tests contra un *exchange* falso: *rollback* tras envío, *timeout* con orden ejecutada, *fill* parcial, dos *workers* concurrentes y reinicio con órdenes en vuelo. Porta la puerta PSR ≥ 0,95 + MinTRL de la 1.346 de CryptoWorld.

---

## 13. Cambios que hay que hacer en la documentación de Finances

1. **`docs/plan/plan-maestro.md` §9:** sustituir la descripción de CryptoWorld por §2.3 de este documento y enlazarlo.
2. **§13 (fases):** sustituir F12 por G0-G13 (o enlazar este documento) y marcar que G0 = F6 + F7 + F13 + F10.
3. **§4 (fuentes):** añadir Bybit y OKX (vía ccxt), Deribit, Blockscout, data.binance.vision.
4. **§16 (dominios):** añadir los de esos proveedores (por ejemplo `api.bybit.com`, `www.okx.com`, `www.deribit.com`, `data.binance.vision` y las instancias de Blockscout que se usen).
5. **`CLAUDE.md`:** tres reglas nuevas cuando lleguen sus fases: (a) ninguna cifra propia sin nota de metodología; (b) ningún cambio del Laboratorio sin volver a pasar los mundos nulos; (c) dinero real: solo `apps/trader`, *outbox* obligatorio, `Decimal`, bandera apagada por defecto.
6. **ADR previstos:** 0029 persistencia y multiusuario; 0030 cola de trabajos; 0031 tipos `FlowSeries`/`RateSeries`; 0032 *venues* cripto sobre `HttpClient` (escrito); 0033 registro de capacidades de producto; 0034 indicadores en NumPy (escrito); 0035 gráfico de velas; 0036 motor de backtest y modelo de costes; 0037 mundos nulos como puerta; 0038 `apps/trader` y *outbox*; 0039 custodia de claves; 0040 tiempo real.
