# InvestingLab

[![Python](https://github.com/JAVIIFDEEZ/Finances/actions/workflows/python.yml/badge.svg?branch=development)](https://github.com/JAVIIFDEEZ/Finances/actions/workflows/python.yml)

Plataforma personal de análisis de mercados financieros:

* ingesta de datos de mercado desde varias fuentes;
* objetos validados con estadísticos automáticos;
* análisis de carteras y simulación de Monte Carlo;
* informes bilingües con gráficos.

Se amplía módulo a módulo con lo aprendido en el Máster MIAX, con calidad de producto: arquitectura
hexagonal verificada en CI, tipado estricto y tests de propiedades.

> **Estado.** El núcleo del taller B1-T1 está implementado y se usa desde un notebook con datos
> propios. Quedan pendientes los proveedores remotos (Yahoo, Alpha Vantage, FRED/ALFRED, BCE),
> que esperan acceso a red en el entorno de desarrollo. Detalle por requisito:
> [matriz de trazabilidad](docs/modules/b1-toolkit.md). Hoja de ruta:
> [plan maestro](docs/plan/plan-maestro.md).

## Qué hace

| Área | Capacidades |
|------|-------------|
| **Datos** | Descarga simultánea de N series. Enrutado por capacidades y *fallback* entre proveedores, reintentos y límites de llamadas, caché Parquet + DuckDB. Fuente de ficheros propios (CSV/Parquet) con importación estricta. |
| **Calidad** | Validación estricta en los bordes. Detección, sin borrar nada, de outliers, splits sospechosos, precios congelados, OHLC incoherente y huecos frente al calendario oficial de cada mercado. |
| **Series y carteras** | `PriceSeries` y `Portfolio` inmutables con estadísticos al crearse. Rebalanceo periódico, por bandas o comprar y mantener. Conversión de divisas *as-of*. Correlaciones y contribución al riesgo (Euler). |
| **Riesgo** | Sharpe (con su intervalo de confianza), Sortino y Calmar. VaR/CVaR histórico, normal y Cornish-Fisher. Episodios de caída. Tipo libre de riesgo *point-in-time*. |
| **Monte Carlo** | GBM multivariante, t de Student y *bootstrap* estacionario. Variables antitéticas, Ledoit-Wolf, rebalanceo dentro de cada trayectoria y VaR con intervalo de confianza. |
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

### Datos propios

Mientras no estén conectados los proveedores remotos, `INVESTINGLAB_LOCAL_DATA_DIR` apunta a una
carpeta con un fichero por símbolo (`SAN.MC.csv`) y un `instruments.toml` que describe cada
uno:

```toml
["SAN.MC"]
name = "Banco Santander"
currency = "EUR"
exchange = "XMAD"
adjustment = "splits_and_dividends"
```

Formato completo, columnas reconocidas y opciones: [guía del Toolkit](docs/guide/toolkit.md).

## Arquitectura

```
packages/investinglab/src/investinglab/
  analytics/   cálculo numérico puro (retornos, riesgo, Monte Carlo)   ← capa más interna
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
| `apps/` | API (FastAPI) y web (Next.js), a partir de las fases F6 y F8 |
