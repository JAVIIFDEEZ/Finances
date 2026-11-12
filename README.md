# InvestingLab

[![Python](https://github.com/JAVIIFDEEZ/Finances/actions/workflows/python.yml/badge.svg?branch=development)](https://github.com/JAVIIFDEEZ/Finances/actions/workflows/python.yml)

Plataforma personal de análisis de mercados financieros:

* ingesta de datos de mercado desde varias fuentes;
* objetos validados con estadísticos automáticos;
* análisis de carteras y simulación de Monte Carlo;
* informes bilingües con gráficos.

Se amplía módulo a módulo con lo aprendido en el Máster MIAX, con calidad de producto: arquitectura
hexagonal verificada en CI, tipado estricto y tests de propiedades.

> **Estado.** El núcleo del taller B1-T1 está implementado y descarga datos sin clave de
> Yahoo Finance y del BCE (divisas oficiales y €STR), además de tus propios ficheros. Quedan
> Alpha Vantage y FRED/ALFRED, que necesitan clave.
> Detalle por requisito: [matriz de trazabilidad](docs/modules/b1-toolkit.md). Hoja de ruta:
> [plan maestro](docs/plan/plan-maestro.md).

## Qué hace

| Área | Capacidades |
|------|-------------|
| **Datos** | Descarga simultánea de N series. Yahoo Finance (acciones, ETFs, índices, divisas, cripto y futuros, de 1 minuto a 1 año) y BCE (tipos de referencia y €STR *point-in-time*), sin claves, y ficheros propios (CSV/Parquet). Enrutado por capacidades y *fallback* entre proveedores, reintentos y límites de llamadas, caché Parquet + DuckDB. |
| **Calidad** | Validación estricta en los bordes. Detección, sin borrar nada, de outliers, splits sospechosos, precios congelados, OHLC incoherente y huecos frente al calendario oficial de cada mercado. |
| **Series y carteras** | `PriceSeries` y `Portfolio` inmutables con estadísticos al crearse. Rebalanceo periódico, por bandas o comprar y mantener. Conversión de divisas *as-of*. Correlaciones y contribución al riesgo (Euler). |
| **Riesgo** | Sharpe (con su intervalo de confianza), Sortino y Calmar. VaR/CVaR histórico, normal y Cornish-Fisher. Episodios de caída. Tipo libre de riesgo *point-in-time*. |
| **Monte Carlo** | GBM multivariante, t de Student y *bootstrap* estacionario. Variables antitéticas, Ledoit-Wolf, rebalanceo dentro de cada trayectoria y VaR con intervalo de confianza. |
| **Optimización** | Mínima varianza, máximo Sharpe y rentabilidad objetivo con límites por activo; paridad de riesgo, HRP e inversa de la volatilidad. Rentabilidades de equilibrio y vistas de Black-Litterman. Frontera eficiente con gráfico. |
| **Planes de ahorro** | Monte Carlo mensual de un plan con capital inicial, aportaciones (o retiradas) y objetivo en dinero de hoy: probabilidad de éxito, déficit, ruina y aportación necesaria exacta. |
| **Informes** | `report()` en Markdown (español o inglés) con diagnósticos que explican la fiabilidad de las cifras; `plots_report()` con los gráficos. |

Nunca se inventan datos:

* un festivo es un hueco, no un retorno del 0 %;
* no se interpola ni se rellena hacia atrás;
* los outliers se informan, no se borran.

## Instalación

Requisitos: [uv](https://docs.astral.sh/uv/) ≥ 0.9 (instala Python 3.14 automáticamente) y Git.

```bash
git clone https://github.com/JAVIIFDEEZ/Finances.git investinglab
cd investinglab
uv sync --all-groups      # dependencias + toolchain (incluye `just`)
uv run just setup         # hooks de git
cp .env.example .env      # configuración local
```

El núcleo es una librería independiente (`packages/investinglab`). Los gráficos son opcionales:
`investinglab[plots]` añade matplotlib.

## Uso

```python
from investinglab.domain import SimulationConfig
from investinglab.toolkit import Toolkit

with Toolkit.from_settings() as tk:
    lote = tk.many(["SAN.MC", "ITX.MC", "IBE.MC"], start="2019-01-01")  # descarga simultánea
    print(lote.summary())

    cartera = tk.portfolio("Núcleo", {"SAN.MC": 0.4, "ITX.MC": 0.3, "IBE.MC": 0.3})
    simulacion = cartera.monte_carlo(SimulationConfig(n_paths=10_000, horizon=252))

    tk.report(cartera, simulation=simulacion).save("informes/nucleo.md")  # en español
    tk.report(cartera, language="en").save("informes/core.md")
    cartera.plots_report().save("informes/graficos")
```

La demo completa del taller está en
[`notebooks/b1_toolkit_demo.ipynb`](notebooks/b1_toolkit_demo.ipynb).

### Fuentes de datos

Los símbolos siguen el estilo de Yahoo (`SAN.MC`, `VOD.L`, `^GSPC`, `EURUSD=X`, `BTC-USD`) y se
descargan sin clave. Las divisas diarias y el tipo libre de riesgo en euros salen del BCE. Las barras se etiquetan con su fecha de sesión, la sesión en curso no se
incluye y las cotizaciones en peniques se pasan a libras: [fuentes de datos](docs/guide/data-sources.md).
Con `INVESTINGLAB_OFFLINE=true` solo se usan tus ficheros y la caché.

### Datos propios

`INVESTINGLAB_LOCAL_DATA_DIR` apunta a una carpeta con un fichero por símbolo (`SAN.MC.csv`) y un
`instruments.toml` que describe cada uno. Tus ficheros tienen prioridad sobre Yahoo:

```toml
["SAN.MC"]
name = "Banco Santander"
currency = "EUR"
exchange = "XMAD"
adjustment = "splits_and_dividends"
```

Formato completo, columnas reconocidas y opciones: [guía del Toolkit](docs/guide/toolkit.md).

## Web

```bash
uv run just web-install   # una vez (Node 22 y pnpm)
uv run just dev           # API y web: abre http://localhost:3000
```

Interfaz de terminal financiero en español e inglés, con tema oscuro y claro:
* visión general de mercados;
* explorador con velas, calidad de datos y comparación;
* constructor y análisis de carteras;
* Monte Carlo, optimización con frontera eficiente y planes de ahorro.

Guía: [cómo ver la web](docs/guide/web.md).

## API

`uv run just api` arranca la API REST en <http://127.0.0.1:8000/docs>: datos de mercado,
análisis de carteras, Monte Carlo, optimización y planes de ahorro, con errores RFC 9457 y un
contrato OpenAPI versionado en `apps/api/openapi.json`. Detalle: [guía de la API](docs/guide/api.md).

Con una base de datos PostgreSQL (opcional) guarda además tus carteras, con propietario, versión
y registro de auditoría: [guía de persistencia](docs/guide/persistence.md).

## Arquitectura

```
packages/investinglab/src/investinglab/
  analytics/   cálculo numérico puro (retornos, riesgo, Monte Carlo, optimización)   ← capa más interna
  domain/      objetos inmutables y validados, sin I/O
  ports/       contratos que el núcleo espera del exterior
  reporting/   informes Markdown bilingües y gráficos
  services/    casos de uso (ingesta, divisas, tipo libre de riesgo, calidad)
  adapters/    HTTP, caché Parquet/DuckDB, calendarios, ficheros, proveedores
  modules/     un paquete por bloque del máster + matriz de trazabilidad
  toolkit.py   fachada pública para notebooks y scripts
```

Las dependencias apuntan siempre hacia dentro y `import-linter` lo verifica en cada commit. Más
detalle:

* [capas](docs/architecture/index.md);
* [modelo de dominio](docs/architecture/domain.md);
* [flujo completo](docs/architecture/workflow.md);
* [decisiones (ADR)](docs/adr/index.md).

## Desarrollo

```bash
uv run just check         # lint + contratos de arquitectura + mypy --strict + tests (como la CI)
uv run just test-fast     # tests sin cobertura, parando en el primer fallo
uv run just fmt           # autoformatear
uv run just docs          # documentación con recarga en vivo
uv run just traceability  # regenerar las matrices de trazabilidad
```

Convenciones del repositorio (ramas, commits, reglas de datos y de arquitectura):
[`CLAUDE.md`](CLAUDE.md).

| Ruta | Contenido |
|------|-----------|
| `packages/investinglab` | Núcleo: librería Python con arquitectura hexagonal |
| `notebooks/` | Demos ejecutables (se versionan sin resultados) |
| `docs/` | Documentación (Zensical): guías, arquitectura, ADRs, módulos y referencia |
| `apps/api/` | API REST (FastAPI) sobre el núcleo |
| `apps/web/` | Web (Next.js 16) sobre la API |
