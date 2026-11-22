# Referencias externas: FinceptTerminal, awesome-quant y Machine Learning for Trading

> Estado: **propuesta incorporada al plan** (23-11-2026) como ampliación H1-H6 del
> [plan maestro](plan-maestro.md) (§13).
>
> Revisé el código de los tres repositorios en estas versiones: FinceptTerminal `914134d`
> (19-11-2026), awesome-quant `c285428` (14-11-2026) y machine-learning-for-trading `13b75a8`
> (22-11-2026, tercera edición). Las licencias de las librerías las comprobé en PyPI el
> 22-11-2026; pueden cambiar, así que se vuelven a mirar al añadir cada dependencia.

**Para qué sirve este documento.** Decide qué funcionalidades de estos tres proyectos suben el
nivel de InvestingLab, en qué fase entran y con qué condiciones de licencia. No duplica lo que ya
existe ni lo que llega de CryptoWorld en G3-G5 ([Integración de CryptoWorld](integracion-cryptoworld.md)).

---

## 0. Resumen

- **Casi todo lo «cuant» de estas referencias ya está hecho o planificado:** optimización,
  Monte Carlo, riesgo e indicadores están hechos. El backtest con validación, el Laboratorio y la
  volatilidad llegan de CryptoWorld. El valor está en seis huecos reales y en usar librerías
  maduras como **oráculos de los tests**, igual que la paridad con CryptoWorld.
- **Seis fases nuevas (H1-H6):**
  - H1: renta fija y curvas de tipos (módulo B2 del máster);
  - H2: cartera frente a un índice de referencia, y estrés;
  - H3: servidor MCP local de solo lectura;
  - H4: evaluación de señales antes del backtest;
  - H5: posicionamiento institucional (COT) y calendario de eventos;
  - H6: cribado y listas de seguimiento.
- **Ampliaciones** de F11, G3, G4, G5, G6, G7, G8, G10 y G12, y una comprobación de licencias en
  la CI (§5).
- **Licencias.** FinceptTerminal es AGPL-3.0: de él solo se toman ideas. ML4T es MIT. Cada
  librería de awesome-quant tiene la suya. La política está en
  [ADR-0046](../adr/0046-third-party-code-and-dependency-licenses.md) (propuesto).
- **Esfuerzo de H1-H6:** 10-14 semanas a 25-30 h/semana. Es una estimación mía, como las de
  G0-G13, no una medición.

---

## 1. Qué es cada repositorio

| | FinceptTerminal | awesome-quant | Machine Learning for Trading (3.ª ed.) |
|---|---|---|---|
| Qué es | Terminal financiero de escritorio en C++20 y Qt 6, con más de 40 pantallas y más de 1.100 scripts Python que reciben argumentos JSON y devuelven JSON | Lista curada de unos 760 proyectos de finanzas cuantitativas, en 19 categorías y varios lenguajes | El código del libro de Stefan Jansen: 27 capítulos y 9 casos de estudio, de los datos a la ejecución en vivo |
| Licencia | AGPL-3.0. Hay además una edición Enterprise cerrada, que es la que el equipo desarrolla a diario | La de cada proyecto listado | MIT, igual que sus librerías `ml4t-data`, `ml4t-engineer`, `ml4t-models`, `ml4t-diagnostic`, `ml4t-backtest` y `ml4t-live` |
| Qué aprovechamos | Su catálogo de funciones, como lista de comprobación | La elección de dependencias y oráculos | Recetas metodológicas y cuadernos |
| Qué no | Su código ni su arquitectura | Las librerías con licencias restringidas | *Deep learning*, aprendizaje por refuerzo y datos sintéticos con GAN, por ahora |

### 1.1 FinceptTerminal

Cada script de `fincept-qt/scripts/` es una herramienta de línea de comandos: Qt la lanza con un
*runner* de Python y lee el JSON que imprime. Muchos envuelven otras librerías (QuantLib,
PyPortfolioOpt, quantstats, ffn, statsmodels…). Otros son portes: la exposición gamma viene de
OpenAlgo y las estrategias, de QuantConnect LEAN (Apache-2.0).

| Área | Qué hace | Qué tomamos | Fase |
|---|---|---|---|
| Renta fija (`Analytics/fixedIncome`, 13 scripts) | Precio de bonos, curva (*bootstrapping*, Nelson-Siegel, Svensson), duración y convexidad, Z-spread, cartera de bonos, crédito, tipo flotante | El alcance funcional del módulo de renta fija | H1 |
| Opciones (`Analytics/options`) | Sonrisa y superficie de volatilidad implícita, exposición gamma (GEX) por *strike* con Black-76, simulador de *straddle* | Sonrisa, superficie y GEX sobre las opciones de Deribit | G5 |
| Cartera (`screens/portfolio`) | Operaciones, libro, mapa de calor, sectores, vista de rendimiento con ffn y estrés por escenarios con *shocks* por clase de activo | Estrés hipotético por clase de activo y vistas de rendimiento frente a un índice | H2, G6 |
| Cribado (`screener_data.py`) | Filtros sobre la API de cribado de Yahoo, que no es oficial | La idea, aplicada a universos propios | H6 |
| Lista de seguimiento (`screens/watchlist`) | Listas de símbolos con cotización | Listas guardadas por usuario | H6 |
| Calendario económico (`economic_calendar.py`) | JSON semanal público de Forex Factory: hora, país, impacto, previsión y dato anterior. Solo la semana en curso y sin el dato publicado | La fuente, guardada como fotos fechadas | H5 |
| COT (`cftc_data.py`) | Informes de posicionamiento de la CFTC desde su Public Reporting Environment | El dato, dentro del conjunto de posicionamiento | H5 |
| Mercados de predicción (`prediction_polymarket.py`, `prediction_kalshi.py`) | Mercados, precios e historia de Polymarket y Kalshi | Probabilidades implícitas de eventos macro como dato alternativo | H5 |
| Servidores MCP (`fincept_mcp`, pantalla `mcp_servers`) | Herramientas para modelos de lenguaje sobre sus datos | Un servidor MCP propio, local y de solo lectura | H3 |
| Finanzas corporativas (`corporateFinance`) | DCF, LBO, fusiones, valoración de *startups* | Valoración por DCF y múltiplos comparables, cuando haya fundamentales | F11 (después) |
| Custodia de claves | Almacén cifrado con AES-256-GCM | Confirma la decisión abierta 7 de la integración | G7 |
| Agentes de IA | 37 agentes que imitan el estilo de inversores conocidos; Alpha Arena, una competición de modelos de lenguaje operando | Nada | — |
| Herramientas de escritorio | Editor de nodos, editor de código, notas, Excel, gestor de ficheros | Nada: fuera del alcance | — |
| Datos exóticos | Tráfico marítimo, geopolítica, mapa de relaciones, AkShare, mercados asiáticos | Nada | — |
| Ejecución | 16 *brokers*, *trading* cripto, monedero | Nada: la ejecución se decide en G7 | — |
| DataHub | Publicación y suscripción, con una descarga por tema para todos los suscriptores | Nada: la web ya deduplica con TanStack Query y el servicio de datos cachea | — |

**Por qué no su código.** Con la AGPL, copiar una parte obliga a distribuir InvestingLab entero
bajo AGPL, también si solo se sirve por red, y G12 contempla un modo SaaS. Además son scripts
sueltos, sin las garantías de aquí: validación estricta, tipos, casetes y *point-in-time*. Si
alguna pieza que Fincept portó de un proyecto permisivo interesa, se va al original.

### 1.2 awesome-quant

Es un índice, no código. Lo útil son las categorías *Financial Instruments & Pricing*,
*Trading & Backtesting*, *Portfolio Optimization & Risk Analysis*, *Factor Analysis*, *Time
Series Analysis*, *Market Data & Data Sources*, *Prediction Markets* y *Reproducing Works,
Training & Books*. De ahí sale la lista corta de §2, con
la licencia y el papel de cada librería. Dos avisos:

- Varias de las librerías más citadas no son permisivas: backtesting.py (AGPL-3.0), vectorbt
  (Apache-2.0 con *Commons Clause*), FinancePy (GPL-3.0) y rateslib (código disponible, solo
  para uso no comercial).
- Muchas librerías de datos (edgartools, cot-reports, pmxt) hacen su propia red. Las reglas del
  repositorio exigen `HttpClient` para la red ([ADR-0012](../adr/0012-resilient-http-client.md),
  [ADR-0032](../adr/0032-crypto-venues-on-the-shared-http-client.md)). Por eso sirven como
  referencia u oráculo, no como adaptador.

### 1.3 Machine Learning for Trading, tercera edición

El libro recorre un único proceso de principio a fin. Separa con una «frontera de evidencia» lo
que se ajusta de lo que se evalúa, valida siempre con *walk-forward* y trata el sobreajuste con
el *Deflated Sharpe Ratio* y el *Reality Check* de White. Encaja con el rigor que ya exige este
repositorio. Lo que más aporta:

| Capítulo y cuaderno | Qué aporta | Fase |
|---|---|---|
| 1 · `macro_regimes`, `factor_regimes` | Regímenes por agrupamiento (mezcla gaussiana) sobre macro de FRED: paro, tipo oficial, pendiente de la curva, inflación. Se validan contra el mercado | G5 |
| 7 · `05_signal_evaluation`, `06_ic_inference` | IC con errores HAC y *block bootstrap* | H4 |
| 7 · `04_maximum_favorable_adverse_excursion`; 19 · `03_position_sizing_mae_mfe` | Máxima excursión favorable y adversa (MAE/MFE) por operación | G3 |
| 9 · `02_structural_breaks`, `04_kalman_filter` | Rupturas estructurales (ya previstas) y filtro de Kalman (nuevo) | G5 |
| 11 · `05_shap_analysis`, `06_conformal_prediction` | Explicación con SHAP y predicción conformal | G4 |
| 14 · `03_yield_curve_decomposition` | PCA de la curva: nivel, pendiente y curvatura | H1 |
| 16 · `06_framework_parity` | La misma estrategia con pesos × retornos y con un motor por eventos, con resultados iguales | G3 |
| 17 · `03_robust_optimization`, `04_kelly_criterion` | Optimización robusta; Kelly y por qué no se usa tal cual | F5c, G4 |
| 18 · `02_spread_estimation`, `03_market_impact_calibration`, `05_almgren_chriss_optimal_execution` | *Spread* de Roll y de Corwin-Schultz desde velas diarias; impacto; ejecución de Almgren-Chriss | G3, G7 |
| 19 · `04_factor_exposure`, `06_stress_testing` | Exposición a CAPM, Fama-French 3 y 5; repetición de 2008, 2020 y 2022 sobre carteras de referencia | G6, H2 |
| 20 · `06_cost_survival` | Coste de equilibrio y caída del Sharpe de bruto a neto | G3 |
| 22-24 | RAG sobre informes de la SEC, agentes con contratos de herramientas | G10, H3 |
| 26 · `01_drift_monitoring`, `04_circuit_breakers` | Deriva de modelos y *circuit breakers* como máquina de estados | G7, G8 |
| Casos de estudio FX, CME y cripto *perps* | Carry y momentum en divisas, *roll yield* en futuros, funding en perpetuos | G5 (mesa de carry) |
| 5, 13, 21, 23 | Datos sintéticos con GAN y difusión, *deep learning* de series, aprendizaje por refuerzo, grafos con Neo4j | No, por ahora: traen `torch` y servicios nuevos a un núcleo NumPy y pandas |

El libro usa Polars. Aquí la interfaz pública es pandas (plan maestro, §0), así que los cuadernos
se leen como método, no como código que pegar.

---

## 2. Licencias y papel de cada librería

[ADR-0046](../adr/0046-third-party-code-and-dependency-licenses.md) (propuesto) fija cuatro
papeles:

- **Dependencia de ejecución.** Forma parte de `investinglab`, de un *extra*, de `apps/api`, de
  `apps/web` o de `apps/mcp`. Solo licencias permisivas.
- **Oráculo de tests.** Va en el grupo de dependencias `oracles` y solo lo importan los tests,
  para comparar cifras, como la paridad con CryptoWorld. Nunca se importa desde `src/`.
- **Referencia.** Se lee para entender un método; no se instala.
- **Prohibida.** Ni su código ni la dependencia.

| Librería | Licencia (PyPI, 22-11-2026) | Papel | Dónde |
|---|---|---|---|
| QuantLib | BSD-3-Clause | Oráculo | H1 (bonos y curvas), G5 (opciones) |
| empyrical-reloaded | Apache-2.0 | Oráculo | H2 |
| quantstats | Apache-2.0 | Oráculo | H2 |
| alphalens-reloaded | Apache-2.0 | Oráculo | H4 |
| skfolio | BSD-3-Clause | Oráculo | F5c (con efecto retroactivo) y optimización robusta |
| PyPortfolioOpt | MIT | Referencia | Su HRP en la 1.6.0 usa una parte privada de scipy que desapareció en la 1.18 (lo documenta ML4T), y aquí se exige scipy ≥ 1.18: no sirve de oráculo |
| Riskfolio-Lib | BSD-3-Clause | Referencia | Medidas de riesgo para F5c |
| arch | NCSA | Oráculo | G5 (HAR, GARCH) y la FHS prevista en Monte Carlo |
| ruptures | BSD-2-Clause | Oráculo | G5 (rupturas) |
| pykalman | BSD | Oráculo | G5 (Kalman) |
| hmmlearn | BSD | Referencia | G5 (regímenes) |
| MAPIE | BSD-3-Clause | Oráculo | G4 (conformal) |
| shap | MIT | Dependencia del *extra* `ml` | G4 |
| edgartools | MIT | Oráculo | F11 (XBRL) |
| cot-reports | MIT | Referencia | H5 |
| pmxt | MIT | Referencia | H5 |
| `ml4t-*` | MIT | Referencia; posible oráculo | G3, H4. Son versiones 0.x muy recientes |
| `mcp` (SDK oficial de MCP) | MIT | Dependencia de `apps/mcp` | H3 |
| nautilus_trader | LGPL-3.0 | Descartada por ahora | La ejecución de G7 va con ccxt |
| backtesting.py | AGPL-3.0 | Prohibida | — |
| vectorbt | Apache-2.0 + *Commons Clause* | Prohibida | — |
| FinancePy | GPL-3.0 | Prohibida | — |
| rateslib | Código disponible, no comercial | Prohibida | — |
| FinceptTerminal | AGPL-3.0 | Solo ideas | — |

---

## 3. Lo que ya está hecho o planificado

Para no portar dos veces lo mismo:

| En las referencias | En InvestingLab |
|---|---|
| Optimización (PyPortfolioOpt, Riskfolio, skfolio; el *wrapper* de Fincept) | F5c ✅, propia: mínima varianza, máximo Sharpe, rentabilidad objetivo, paridad de riesgo, HRP, Black-Litterman, frontera eficiente |
| Monte Carlo y *bootstrap* | F4 ✅: GBM, Student-t, *bootstrap* estacionario, antitéticas |
| VaR y CVaR (Cornish-Fisher), Sharpe con su error estándar, *drawdown* por episodios | F3 ✅ |
| Diagnóstico de datos (ML4T 7) | F3 ✅ (`DataQualityReport`) |
| Indicadores técnicos (TA-Lib, ta, pandas-ta; ML4T 8) | G2 ✅: 26 indicadores con paridad ([ADR-0034](../adr/0034-technical-indicators-in-numpy.md)) |
| Planificación financiera (`portfolio_planning` de Fincept) | F5d ✅ |
| Funding y posicionamiento cripto (caso cripto *perps* de ML4T) | G1 ✅ (datos); G5 (mesa de carry) |
| Triple barrera, validación cruzada purgada, DSR, PBO, conformal (ML4T 6, 7 y 11) | G3 y G4, desde CryptoWorld |
| HAR, rupturas, estacionalidad, estudio de eventos | G5, desde CryptoWorld |
| Fama-French, q-factors, Goyal-Welch, XBRL de la SEC | F11 |
| Macro de FRED (ML4T 4) | F2b, a la espera de la clave |
| *Trading* en vivo con Alpaca o Interactive Brokers (ML4T 25) | G7: decisión abierta 4 de la integración (ninguno hasta que una estrategia supere el nulo) |
| Paleta de comandos | Web ✅ (`⌘K`) |

---

## 4. Fases nuevas H1-H6

Cada fase sigue las reglas de siempre: rama desde `development`, ADR en el mismo PR, `just check`
en verde, resumen de cierre y nota de metodología por cada cifra propia (G3).

### H1 · Renta fija y curvas de tipos (módulo B2 del máster)

**Por qué.** El bloque 2 del máster es de renta fija y está en curso. El plan solo tenía la renta
fija como clase de activo y las curvas del BCE como dato, sin analítica. El plan de integración ya
pedía hacer coincidir una fase con el bloque del máster cuando lo hubiera, para que el módulo use
el núcleo en lugar de duplicarlo.

**Alcance.** Lo marcan el temario del bloque (requisitos redactados por nosotros, sin subir
material de clase), el catálogo de renta fija de Fincept y ML4T 14.

- **Dominio.**
  - `Bond`: ISIN, emisor, divisa, nominal, cupón fijo, frecuencia, fechas (emisión, primer cupón,
    vencimiento, *call*), base de cálculo, prelación, rating, tamaño de la emisión y sector.
  - `CashFlowSchedule`.
  - `YieldCurve`: fecha, nodos o modelo paramétrico, tipo (*spot*, *forward* o par),
    capitalización y procedencia.
  - `BondQuote`: precio limpio y fecha valor.
- **Núcleo numérico (`analytics/fixed_income/`).**
  - Convenciones de días: ACT/ACT ICMA, ACT/365F, ACT/360, 30/360 y 30E/360.
  - Calendario de flujos, cupón corrido, precio sucio y limpio, TIR.
  - Descuento con una curva más un *spread*.
  - *Spreads*: de rentabilidad, frente a un bono de referencia, G-spread, I-spread (frente a
    €STR) y Z-spread.
  - Duraciones: Macaulay, modificada, efectiva (con un choque de curva) y por tramos (*key-rate*);
    *money duration* y PVBP/DV01.
  - Convexidad, analítica y efectiva.
  - Cartera: duración y TIR ponderadas; contribución por emisor, sector y rating.
  - Curvas: Nelson-Siegel y Svensson (evaluación y ajuste), *bootstrapping*, forwards implícitos.
    La interpolación es explícita y declarada; nunca se extrapola en silencio.
  - PCA de los cambios diarios (nivel, pendiente y curvatura) con la varianza explicada.
  - *Carry* y *roll-down*.
- **Cobertura.**
  - Número de contratos de futuros sobre deuda para llevar la duración a un objetivo, igualando
    DV01 con la duración del contrato como dato de entrada.
  - Cobertura de crédito con un índice de CDS, dada su sensibilidad al punto básico.
- **Cartera por mandato.** El optimizador de F5c gana restricciones lineales:
  - duración máxima;
  - peso máximo por emisión y por emisor;
  - cuota máxima de *high yield*;
  - exclusión de deuda subordinada;
  - tamaño mínimo de emisión;
  - número máximo de bonos (la cardinalidad es entera; ver §7).
- **Datos.**
  - Curvas del área euro del BCE (*dataset* `YC`): diarias, con tipos *spot*, *forward* y par por
    vencimiento y los parámetros Svensson, para la deuda AAA y para todas las emisiones. Es una
    capacidad nueva del adaptador del BCE que ya existe.
  - Curva par del Tesoro de EE. UU. (F11).
  - El universo de bonos y sus precios llegan de ficheros locales del usuario
    ([ADR-0018](../adr/0018-toolkit-facade-and-local-data.md)), que no se versionan. Los tests
    usan bonos sintéticos etiquetados.
- **Módulo** `modules/b2_fixed_income`, con su `ModuleInfo` y su matriz de trazabilidad.
- **API.** `GET /api/v1/rates/curves`, `POST /api/v1/fixed-income/bonds/analytics` y
  `POST /api/v1/fixed-income/portfolios/hedge`.
- **Web.** Pantalla «Renta fija»:
  - curva del día (*spot*, *forward*, par), con su tabla;
  - historia de los nodos a 2, 5, 10 y 30 años;
  - pendientes 10-2 años y 10 años-3 meses;
  - factores del PCA;
  - calculadora de bonos;
  - análisis y cobertura de una cartera de bonos.

**Oráculo.** QuantLib, para precio, TIR, duración, convexidad y Z-spread. Prueba dorada: los tipos
*spot* que publica el BCE se reconstruyen con sus parámetros Svensson publicados (casetes reales),
a la precisión de la publicación.

**Terminado cuando:**

- la curva del BCE del día se reconstruye desde sus parámetros;
- un bono a tipo fijo sale igual que con QuantLib en todas las convenciones de días;
- una cartera por mandato cumple todas sus restricciones (con un test por restricción);
- la cobertura con futuros deja la duración de la cartera en el objetivo.

**ADR previsto:** tipos de renta fija y curvas, convenciones de días y resolución de mandatos.
**Esfuerzo:** 3-4 semanas.

### H2 · Cartera frente a un índice de referencia, y estrés

**Por qué.** El análisis de carteras ya tiene `beta`, pero no las métricas relativas que exige
cualquier comparación con un índice de referencia. Las dos prácticas del máster lo piden: un
índice de crédito *total return* en renta fija y el S&P 500 con y sin dividendos en datos
alternativos. El estrés estaba en G6, sobre el libro de operaciones. Sobre carteras modelo, que ya
existen, se puede adelantar.

- **Métricas relativas.**
  - Rentabilidad activa, *tracking error* e *information ratio*.
  - Alfa de Jensen y beta con errores HAC.
  - Captura al alza y a la baja; aciertos mensuales.
  - Omega y *tail ratio*.
- **Métricas móviles.** Volatilidad, Sharpe, beta y correlación, con la ventana y el mínimo de
  observaciones declarados (NaN hasta llenarse).
- **Tablas.** Rentabilidad mensual y anual; peores episodios de *drawdown* (con
  `drawdown_episodes`, que ya existe).
- **Índice de referencia.** Cualquier `PriceSeries` o cesta, convertida a la divisa base con FX
  *as-of*. El informe avisa si se compara un índice de precio con una cartera de retorno total.
- **Estrés histórico.** Repetir con precios reales las ventanas de 2008-09 (crisis financiera),
  2011-12 (deuda del euro), febrero-marzo de 2020 (COVID) y 2022 (subidas de tipos) sobre los pesos
  actuales. Un activo sin historia en la ventana sale como «sin cobertura», con el porcentaje de la
  cartera que sí está cubierto. Nunca se usa un sustituto implícito: solo si el usuario lo declara,
  y entonces se etiqueta.
- **Estrés hipotético.** *Shocks* declarados por clase de activo o factor: renta variable, tipos
  (vía la duración de H1), crédito, divisa y cripto.
- **Estrés inverso.** El *shock* que lleva la cartera a una pérdida dada, con el Monte Carlo que
  ya existe.
- **Salidas.** Secciones nuevas en `report()` y `plots_report()`. La API amplía
  `POST /api/v1/portfolios/analytics` con `benchmark` y añade `POST /api/v1/portfolios/stress`. La
  web gana dos pestañas en Cartera.

**Oráculo.** empyrical-reloaded y quantstats.

**Terminado cuando:**

- una cartera 60/40 frente a un índice de retorno total da las mismas métricas relativas que el
  oráculo;
- la repetición de 2020 coincide con la evolución real de los precios de la cartera;
- un activo sin historia en una ventana aparece como no cubierto, sin cifra inventada.

**ADR previsto:** índice de referencia y estrés sin sustitutos implícitos. **Esfuerzo:** 1-2
semanas. G6 aplicará lo mismo al libro.

### H3 · Servidor MCP local de solo lectura

**Por qué.** Estaba en G12 (P3) como parte del modo SaaS. Una versión local no necesita nada de
G12: el `Toolkit` y los modelos de la API ya existen, y deja a Claude (Code o Desktop) consultar
InvestingLab directamente.

- **`apps/mcp`** (paquete `investinglab_mcp`, miembro del *workspace*) con el SDK oficial de MCP.
  Habla con el núcleo solo a través del `Toolkit`, como la API, y por *stdio*.
- **Herramientas de solo lectura:**
  - mercado: ficha, técnico, patrones, estructura, confluencia, flujo, funding, posicionamiento,
    profundidad, comparación y calidad;
  - carteras descritas en la propia llamada: análisis, optimización, Monte Carlo y planes;
  - curvas (H1);
  - carteras guardadas, solo lectura.
- **Contratos.**
  - Los esquemas salen de los mismos modelos Pydantic de la API: una sola fuente.
  - Cada respuesta lleva unidades, fecha *as-of*, procedencia y la nota de metodología.
  - Los errores son Problem Details.
- **Seguridad.**
  - Ninguna herramienta escribe; un test falla si aparece una herramienta que no está en la lista
    de solo lectura.
  - Límites de tamaño, como en la API.
  - Respeta `INVESTINGLAB_OFFLINE`.
- **Tests.** El contrato de cada herramienta, con casetes.

G12 conserva la versión publicada, con autenticación.

**Terminado cuando:** Claude lista las herramientas y responde, sin red y con casetes, a «¿qué
dice la ficha de `SAN.MC`?» y a «optimiza esta cartera de tres ETF».

**ADR previsto:** servidor MCP sobre el `Toolkit`. **Esfuerzo:** 1 semana.

### H4 · Evaluación de señales

**Por qué.** Antes de gastar un backtest, hay que saber si una señal tiene relación con los
retornos futuros. El plan no lo incluía. ML4T 7 lo convierte en un paso de cribado con
inferencia correcta.

- **`analytics/signals/`.**
  - IC de Pearson y de rangos por horizonte (1, 5 y 21 sesiones), en serie temporal (un activo) y
    transversal (un universo *point-in-time*).
  - Errores HAC (Newey-West, con el rezago que imponen los horizontes solapados) e intervalos por
    *block bootstrap*.
  - Decaimiento del IC por horizonte, rentabilidad por cuantiles y diferencial largo-corto.
  - Rotación de la señal y tasa de aciertos.
  - Corrección de Benjamini-Hochberg al evaluar el catálogo entero.
- **Etiquetas sin *look-ahead*.** La señal en *t* usa información hasta *t*; el retorno empieza
  donde se ejecutaría (apertura siguiente, como en G3).
- **Aplicación.** Los 26 indicadores y las reglas del panel de G2, sobre universos
  ([ADR-0031](../adr/0031-flow-holding-rates-and-universes.md)). El Laboratorio de G4 recibe las
  señales ya cribadas.
- **Salidas.** `GET /api/v1/signals/evaluation` y una vista en el Laboratorio.

**Oráculo.** alphalens-reloaded.

**Terminado cuando:**

- la tabla de IC del catálogo sale con su p-valor ajustado;
- una señal aleatoria resulta no significativa en al menos el 95 % de las semillas (test de
  propiedades).

**ADR previsto:** evaluación de señales con inferencia HAC. **Esfuerzo:** 1-2 semanas.

### H5 · Posicionamiento institucional y calendario de eventos

**Por qué.** Tres datos alternativos que encajan en tipos que ya existen y que sirven para lo que
operas: oro y divisas.

- **COT de la CFTC.**
  - Informes *legacy*, desagregado (materias primas) y TFF (financieros), semanales.
  - Los datos del martes se publican el viernes: se indexan por fecha de publicación
    (*point-in-time*).
  - Entran en el conjunto de posicionamiento
    ([ADR-0042](../adr/0042-positioning-as-a-dataset.md)) como *venue* `CFTC`. Llevan las
    categorías de cada informe (comerciales y no comerciales; *managed money*, *swap dealers*,
    *leveraged funds*…), largos, cortos, neto e interés abierto.
  - Lectura convencional: percentil del neto en tres años.
  - Una tabla relaciona cada instrumento con su código de contrato de la CFTC.
  - Alimenta el pilar de derivados de la ficha para oro, divisas, bonos e índices.
- **Calendario económico.**
  - Eventos programados (hora, país, impacto, previsión y dato anterior) del JSON semanal de
    Forex Factory.
  - Solo cubre la semana en curso y no trae el dato publicado, así que se guarda como fotos
    fechadas ([ADR-0045](../adr/0045-market-reference-snapshots.md)). El dato publicado sale de su
    fuente oficial (FRED/ALFRED, BCE, Eurostat, INE).
  - Usos: filtro de eventos de alto impacto en los backtests de G3 y en la ficha, y el estudio de
    eventos de G5.
- **Mercados de predicción.**
  - Probabilidades implícitas de eventos macro (reuniones de la Fed y del BCE, recesión, IPC) de
    Polymarket y Kalshi, como series fechadas con su volumen y su liquidez.
  - Adaptadores propios sobre `HttpClient` (coherente con ADR-0032); pmxt queda como referencia.
  - Solo mercados por encima de un volumen mínimo declarado. Nunca se presentan como predicción
    propia.

**Terminado cuando:**

- el pilar de derivados del oro muestra el neto de los no comerciales con su fecha de publicación;
- un backtest de G3 puede excluir las ventanas de eventos de alto impacto;
- la probabilidad implícita de la próxima reunión de la Fed aparece como serie, con su volumen.

**Depende de:** G0b, para ir guardando las fotos del calendario y los mercados.
**ADR previsto:** amplía ADR-0042 (COT) y ADR-0045 (calendario); uno nuevo para los mercados de
predicción. **Esfuerzo:** 2-3 semanas.

### H6 · Cribado y listas de seguimiento

**Por qué.** No hay forma de buscar activos por sus características. Fincept usa la API no
oficial de Yahoo. Aquí se criba sobre universos propios con los cálculos propios.

- **Cribado sobre un `Universe` *point-in-time*.**
  - Filtros sobre los pilares de la ficha, las lecturas técnicas, la confluencia, el riesgo, la
    rentabilidad, la liquidez (volumen medio, *spread* estimado de G3) y los fundamentales cuando
    entre F11.
  - Orden y columnas a elegir.
  - Cada resultado lleva su fecha *as-of*; lo que no se pudo calcular sale como «—».
- **Cribados guardados y listas de seguimiento.** Tablas con `owner_id`
  ([ADR-0029](../adr/0029-relational-persistence-and-owners.md)) y versión optimista. Son la base
  de las alertas de G8.
- **API y web.** `POST /api/v1/screens`, `GET`/`POST /api/v1/watchlists` y una pantalla
  «Cribado». La lista de seguimiento aparece en Inicio.

**Terminado cuando:** un cribado como «acciones de un universo con tendencia semanal alcista y
RSI diario por debajo de 30» devuelve sus resultados con fecha, se guarda y se reabre igual; la
lista de seguimiento aparece en Inicio.

**Depende de:** G0c (acceso con usuario). **Esfuerzo:** 2 semanas.

---

## 5. Ampliaciones de fases existentes

| Fase | Ampliación | Origen |
|---|---|---|
| **F11** | Operaciones de directivos (Form 4 de la SEC) como conjunto de eventos. XBRL con adaptador propio y edgartools como oráculo de su lectura. Ratios de crédito (deuda/EBITDA, FFO/deuda, cobertura de intereses) para el análisis de crédito de H1. Más tarde, valoración por DCF y múltiplos comparables | ML4T 4; Fincept `corporateFinance`; temario de renta fija |
| **G3** | *Spread* de Roll y de Corwin-Schultz desde velas diarias para el `CostModel` de mercados sin cotizaciones (BME), contrastado con SIX Market Signal donde lo haya. Coste de equilibrio y caída del Sharpe de bruto a neto en el informe. MAE/MFE por operación. Test de paridad entre pesos × retornos y el motor por eventos | ML4T 7, 16, 18, 19 y 20 |
| **G4** | Kelly fraccional con la incertidumbre de la estimación (nunca Kelly completo). SHAP para explicar los modelos (*extra* `ml`). Optimización robusta como alternativa en F5c | ML4T 11 y 17 |
| **G5** | Regímenes macro por agrupamiento sobre macro *point-in-time*, validados contra el mercado. Filtro de Kalman para beta y ratio de cobertura dinámicos. Indicador de recesión con la pendiente de la curva (EE. UU. y área euro con H1), con probit evaluado fuera de muestra. Opciones de Deribit: sonrisa, superficie y exposición gamma por *strike* | ML4T 1 y 9; cuaderno del máster sobre la curva y las recesiones; Fincept `options` |
| **G6** | Atribución con Fama-French 3 y 5 más momentum, con betas móviles y errores HAC. El estrés de H2, aplicado al libro | ML4T 19 |
| **G7** | Un *circuit breaker* como máquina de estados única (activo, pausado, en prueba, activo), con reglas de parada: pérdida diaria, *drawdown*, datos obsoletos, deriva del modelo y anomalía de ejecución. Calibración de impacto y Almgren-Chriss para el TCA | ML4T 18 y 26 |
| **G8** | Alertas de deriva de *features* y predicciones del Laboratorio (PSI y KS) | ML4T 26 |
| **G10** | RAG sobre informes (10-K, comunicados del BCE) con cita de la fuente y evaluación; agentes de investigación sobre las herramientas de H3 | ML4T 22 y 24 |
| **G12** | El MCP local pasa a H3. G12 conserva el publicado, con autenticación | Fincept `fincept_mcp` |
| **CI** | Comprobación de licencias de las dependencias de ejecución y `THIRD_PARTY_NOTICES.md` ([ADR-0046](../adr/0046-third-party-code-and-dependency-licenses.md)) | §2 |

---

## 6. Orden de trabajo

Se intercala con el orden acordado para G0-G13 (D6 de la integración) sin saltarse ningún
requisito:

| Paso | Contenido | Por qué ahí |
|---|---|---|
| 1 | Lo que queda de G1 y G2 | En curso |
| 2 | **H1** Renta fija y curvas | Coincide con el bloque 2 del máster; no necesita cola ni usuario |
| 3 | **H2** Cartera frente a un índice, y estrés | Sin estado; usa H1 para el *shock* de tipos |
| 4 | **H3** MCP local | Expone lo anterior; una semana |
| 5 | G0b | Trabajos en segundo plano |
| 6 | **H4** Evaluación de señales, y después G3, G4 y G5 con sus ampliaciones | H4 criba lo que entra en el backtest y en el Laboratorio |
| 7 | **H5** Posicionamiento y calendario | Necesita G0b para guardar fotos; alimenta el estudio de eventos de G5 |
| 8 | G0c | Acceso con usuario |
| 9 | **H6** Cribado y listas | Estado por usuario; base de las alertas de G8 |
| 10 | G6-G13 | Como estaba |

---

## 7. Decisiones abiertas

Como en la integración, cada una se cierra con un ADR al empezar su fase. Doy mi recomendación,
pero no la doy por hecha.

1. **Oráculos (H1).** Un grupo `oracles` en el *workspace* o un proyecto de tests aparte, porque
   QuantLib pesa decenas de MB. *Recomiendo* el grupo, con un contrato de `import-linter` que
   impida importarlo desde `src/`.
2. **MCP (H3).** Proceso propio sobre el `Toolkit` o cliente de la API por HTTP. *Recomiendo* el
   `Toolkit`, como los notebooks; el cliente HTTP solo tendría sentido para el MCP publicado de
   G12.
3. **COT (H5).** La API del Public Reporting Environment (sin clave) o los ficheros históricos
   comprimidos de `cftc.gov`. *Recomiendo* la API para lo reciente y los ficheros para la carga
   inicial, los dos con casetes.
4. **Calendario (H5).** El JSON de Forex Factory no es una API documentada. Hay que revisar sus
   términos antes de depender de él. La alternativa oficial (calendarios de publicación de FRED y
   del BCE) no trae la previsión de consenso.
5. **Mercados de predicción (H5).** Revisar los términos de uso de Polymarket y Kalshi, y sus
   restricciones por jurisdicción, antes de grabar casetes. Si no encajan, se quedan fuera.
6. **Cardinalidad en los mandatos (H1).** «Como mucho N bonos» es una restricción entera.
   `scipy.optimize.milp` (HiGHS, ya incluido en scipy) o una heurística. *Recomiendo* MILP,
   declarado en el ADR.
7. **Librerías `ml4t-*`.** *Recomiendo* no adoptarlas como dependencias: son 0.x y muy recientes.
   Sirven como referencia y, si conviene, como oráculo.

---

## 8. Riesgos y licencias de datos

*No soy abogado: es un mapa para validar antes de abrir nada a terceros, igual que §11 de la
integración.*

- **CFTC, SEC y FRED:** datos públicos de organismos de EE. UU.
- **BCE:** sus estadísticas se reutilizan citando la fuente.
- **Forex Factory:** fuente no documentada y frágil; puede cambiar o cerrarse sin aviso.
- **Polymarket y Kalshi:** términos propios y restricciones geográficas. Kalshi es un mercado
  regulado por la CFTC.
- **Código:** [ADR-0046](../adr/0046-third-party-code-and-dependency-licenses.md). Ningún
  fragmento de FinceptTerminal ni de otro proyecto con copyleft o licencia restringida.
- **Señales publicadas:** el cribado (H6) y las respuestas del MCP (H3) son lecturas privadas. Si
  algún día se publican, aplican las reglas de §11.2 de la integración.

---

## 9. Prompts listos para Claude Code

**P-H1 · Renta fija y curvas**
> Lee `CLAUDE.md`, `docs/plan/referencias-externas.md` (§4, H1) y ADR-0018 y ADR-0026.
> Implementa `domain/fixed_income.py` (`Bond`, `CashFlowSchedule`, `YieldCurve`, `BondQuote`,
> inmutables y validados) y `analytics/fixed_income/`: convenciones de días ACT/ACT ICMA,
> ACT/365F, ACT/360, 30/360 y 30E/360; flujos, cupón corrido, precio sucio y limpio, TIR;
> descuento con curva más *spread*; G-, I- y Z-spread; duración de Macaulay, modificada, efectiva
> y por tramos; *money duration*, PVBP y convexidad; Nelson-Siegel y Svensson; *bootstrapping*;
> forwards; PCA de la curva. Amplía el adaptador del BCE con el *dataset* `YC` (*spot*, *forward*,
> par y parámetros Svensson) y graba sus casetes. Añade el grupo `oracles` con QuantLib, más un
> contrato de `import-linter` que impida importarlo desde `src/`, y tests que comparen con
> QuantLib. Prueba dorada: reconstruir los tipos *spot* publicados con los parámetros publicados.
> Bonos sintéticos etiquetados en `tests/support/`. Módulo `modules/b2_fixed_income` con
> requisitos redactados por nosotros (nunca material de clase). ADR con la decisión.

**P-H2 · Cartera frente a un índice, y estrés**
> Añade a `analytics` las métricas relativas (rentabilidad activa, *tracking error*, *information
> ratio*, alfa y beta con HAC, captura al alza y a la baja, Omega, *tail ratio*), las métricas
> móviles con ventana y mínimo de observaciones, y las tablas mensual y anual. Añade el estrés
> histórico por ventanas con la cobertura de cada activo (nunca sustitutos implícitos), el
> hipotético por factor y el inverso con el Monte Carlo existente. Integra el índice de referencia
> en `Portfolio`, `report()`, `plots_report()`, `POST /api/v1/portfolios/analytics` (`benchmark`)
> y un `POST /api/v1/portfolios/stress` nuevo, con dos pestañas en Cartera. Oráculos:
> empyrical-reloaded y quantstats en el grupo `oracles`. Ejecuta `just openapi` y añade las
> pantallas nuevas a `SCREENS` de `e2e/mobile.spec.ts`.

**P-H3 · MCP local**
> Crea `apps/mcp` (paquete `investinglab_mcp`) con el SDK oficial de MCP para Python, transporte
> *stdio* y solo herramientas de lectura sobre el `Toolkit`. Los esquemas salen de los modelos
> Pydantic de `apps/api`. Cada respuesta lleva unidades, *as-of*, procedencia y nota de
> metodología; los errores, Problem Details. Un test enumera las herramientas y falla si alguna no
> está en la lista de solo lectura. Tests de contrato con casetes y `INVESTINGLAB_OFFLINE=true`.
> Documenta en `docs/guide/` cómo conectarlo a Claude Code y a Claude Desktop. ADR con la decisión.

**P-H4 · Evaluación de señales**
> Implementa `analytics/signals/` con IC de Pearson y de rangos por horizonte, en serie temporal y
> transversal, errores HAC de Newey-West con el rezago de los horizontes solapados, *block
> bootstrap*, decaimiento, rentabilidad por cuantiles, rotación y corrección de
> Benjamini-Hochberg. Etiquetas sin *look-ahead* con la ejecución a la apertura siguiente. Aplícalo
> a los 26 indicadores sobre un `Universe`. Oráculo: alphalens-reloaded. Test de propiedades: una
> señal aleatoria no es significativa en al menos el 95 % de las semillas. Endpoint
> `GET /api/v1/signals/evaluation`.
