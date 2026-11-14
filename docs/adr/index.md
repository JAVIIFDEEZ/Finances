# Registro de decisiones de arquitectura (ADR)

Cada decisión de arquitectura relevante se documenta como un ADR en formato
[MADR 4](https://adr.github.io/madr/). Los ADR son **inmutables una vez aceptados**: si una
decisión cambia, se crea un ADR nuevo que la sustituye (`Superseded by ADR-XXXX`) y se
actualiza el estado del antiguo.

| ADR | Título | Estado |
|-----|--------|--------|
| [0001](0001-record-architecture-decisions.md) | Registrar las decisiones de arquitectura con MADR | Aceptado |
| [0002](0002-hexagonal-monorepo-with-independent-core.md) | Monorepo con núcleo hexagonal como paquete independiente | Aceptado |
| [0003](0003-python-quality-toolchain.md) | Toolchain de calidad de Python | Aceptado |
| [0004](0004-language-policy.md) | Política de idioma | Aceptado |
| [0005](0005-documentation-with-zensical.md) | Documentación con Zensical y mkdocstrings | Aceptado |
| [0006](0006-strict-input-validation.md) | Validación estricta de las series de entrada | Aceptado |
| [0007](0007-time-representation.md) | Representación temporal: UTC en intradía y etiquetas de sesión en diario | Aceptado |
| [0008](0008-alignment-without-artificial-fill.md) | Alineación de calendarios sin relleno artificial | Aceptado |
| [0009](0009-point-in-time-economic-series.md) | Series macroeconómicas bitemporales (*point-in-time*) | Aceptado |
| [0010](0010-multi-provider-ingestion.md) | Ingesta multifuente: puertos, registro, routing con *fallback* y lotes | Aceptado, ampliado por [0026](0026-ecb-reference-rates-and-identifier-routing.md) |
| [0011](0011-parquet-duckdb-cache.md) | Caché de datos de mercado en Parquet consultada con DuckDB | Aceptado, ampliado por [0019](0019-bounded-memory-and-incremental-cache.md) |
| [0012](0012-resilient-http-client.md) | Cliente HTTP común: reintentos, cuotas e higiene de secretos | Aceptado, ampliado por [0022](0022-same-origin-redirects-and-error-hygiene.md); su párrafo sobre Yahoo, sustituido por [0025](0025-yahoo-chart-adapter-and-cassettes.md) |
| [0013](0013-risk-metrics-and-portfolio-engine.md) | Métricas de riesgo, correlaciones y motor de valoración de carteras | Aceptado, ampliado por [0021](0021-union-calendar-annualisation-and-portfolio-memo.md) |
| [0014](0014-currency-conversion-and-risk-free-rate.md) | Conversión de divisas *as-of* y tipo libre de riesgo por divisa | Aceptado, ampliado por [0020](0020-risk-free-rate-conventions.md) y [0026](0026-ecb-reference-rates-and-identifier-routing.md) |
| [0015](0015-data-quality-diagnostics.md) | Diagnóstico de calidad de datos con calendarios oficiales | Aceptado |
| [0016](0016-monte-carlo-engine.md) | Motor Monte Carlo vectorizado con rebalanceo dentro de cada trayectoria | Aceptado, ampliado por [0017](0017-bilingual-reports-and-charts.md), [0019](0019-bounded-memory-and-incremental-cache.md) y [0024](0024-goal-based-planning.md) |
| [0017](0017-bilingual-reports-and-charts.md) | Informes Markdown bilingües, gráficos de informe y delegación diferida del dominio | Aceptado |
| [0018](0018-toolkit-facade-and-local-data.md) | Fachada Toolkit, datos locales y trazabilidad de los módulos | Aceptado |
| [0019](0019-bounded-memory-and-incremental-cache.md) | Memoria acotada en la simulación y caché incremental verificada | Aceptado |
| [0020](0020-risk-free-rate-conventions.md) | Tipo libre de riesgo en TAE según la convención de cada serie | Aceptado |
| [0021](0021-union-calendar-annualisation-and-portfolio-memo.md) | Anualización con el calendario unión y memoria del historial de la cartera | Aceptado |
| [0022](0022-same-origin-redirects-and-error-hygiene.md) | Redirecciones dentro del origen y errores sin credenciales | Aceptado |
| [0023](0023-portfolio-optimization.md) | Optimización de carteras: objetivos, estimadores y resolución | Aceptado |
| [0024](0024-goal-based-planning.md) | Planificación por objetivos: planes de ahorro con Monte Carlo mensual | Aceptado |
| [0025](0025-yahoo-chart-adapter-and-cassettes.md) | Yahoo Finance con el endpoint *chart* y pruebas con casetes grabadas | Aceptado |
| [0026](0026-ecb-reference-rates-and-identifier-routing.md) | El BCE como fuente oficial de divisas y tipos del euro, con enrutado por identificadores | Aceptado |
| [0027](0027-stateless-analytics-api.md) | API REST sin estado sobre el Toolkit, con Problem Details y contrato OpenAPI versionado | Aceptado |
| [0028](0028-institutional-web-app.md) | Web institucional: Next.js, cliente tipado desde el contrato OpenAPI y gráficos con paleta validada | Aceptado |
| [0029](0029-relational-persistence-and-owners.md) | Persistencia relacional con propietario en cada tabla y registro *append-only* | Aceptado |
| [0031](0031-flow-holding-rates-and-universes.md) | Flujo por vela, tipos de mantenimiento y universos *point-in-time* como tipos hermanos | Aceptado |
| [0032](0032-crypto-venues-on-the-shared-http-client.md) | *Venues* cripto con adaptadores propios sobre `HttpClient`, sin ccxt para leer datos | Aceptado |
| [0034](0034-technical-indicators-in-numpy.md) | Indicadores técnicos propios en NumPy y pandas, con las definiciones de `ta` | Aceptado |
| [0035](0035-causal-price-patterns.md) | Patrones de precio como sucesos causales, con un solo vocabulario | Aceptado |

## Cómo añadir un ADR

1. Copia [`template.md`](template.md) como `NNNN-titulo-en-kebab-case.md` con el siguiente número.
2. Rellénalo en español; los nombres técnicos se mantienen en inglés.
3. Añádelo a esta tabla y a la navegación de `zensical.toml`.
4. Inclúyelo en el mismo PR que implementa la decisión.
