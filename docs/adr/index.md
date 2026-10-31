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
| [0010](0010-multi-provider-ingestion.md) | Ingesta multifuente: puertos, registro, routing con *fallback* y lotes | Aceptado |
| [0011](0011-parquet-duckdb-cache.md) | Caché de datos de mercado en Parquet consultada con DuckDB | Aceptado |
| [0012](0012-resilient-http-client.md) | Cliente HTTP común: reintentos, cuotas e higiene de secretos | Aceptado |
| [0013](0013-risk-metrics-and-portfolio-engine.md) | Métricas de riesgo, correlaciones y motor de valoración de carteras | Aceptado |
| [0014](0014-currency-conversion-and-risk-free-rate.md) | Conversión de divisas *as-of* y tipo libre de riesgo por divisa | Aceptado |
| [0015](0015-data-quality-diagnostics.md) | Diagnóstico de calidad de datos con calendarios oficiales | Aceptado |
| [0016](0016-monte-carlo-engine.md) | Motor Monte Carlo vectorizado con rebalanceo dentro de cada trayectoria | Aceptado |

## Cómo añadir un ADR

1. Copia [`template.md`](template.md) como `NNNN-titulo-en-kebab-case.md` con el siguiente número.
2. Rellénalo en español; los nombres técnicos se mantienen en inglés.
3. Añádelo a esta tabla y a la navegación de `zensical.toml`.
4. Inclúyelo en el mismo PR que implementa la decisión.
