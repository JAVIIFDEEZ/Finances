"""Block 1, workshop 1: the portfolio-analysis toolkit (B1-T1).

The workshop asks for a library that ingests market data from several sources, models it
as validated objects with automatic statistics, simulates portfolios with Monte Carlo and
writes reports with charts. Everything reusable lives in the core (domain, analytics,
services, reporting, toolkit); this module only declares what the workshop covers and where.
"""

from investinglab.modules.registry import REGISTRY, ModuleInfo, Requirement, RequirementStatus

__all__ = ["MODULE"]

MODULE = REGISTRY.register(
    ModuleInfo(
        slug="b1-toolkit",
        block="B1 · Taller 1",
        title_es="Toolkit de análisis de carteras",
        title_en="Portfolio analysis toolkit",
        summary_es=(
            "Librería para descargar datos de mercado de varias fuentes a la vez, modelarlos "
            "como objetos validados con estadísticos automáticos, analizar y simular carteras "
            "y generar informes con gráficos. Se usa desde un notebook con `Toolkit`."
        ),
        summary_en=(
            "Library to download market data from several sources at once, model it as "
            "validated objects with automatic statistics, analyse and simulate portfolios and "
            "write reports with charts. Used from a notebook through `Toolkit`."
        ),
        requirements=(
            Requirement(
                id="4.1",
                title_es="Documentación y estructura del código en src/",
                title_en="Documentation and source layout under src/",
                code=(
                    "README.md",
                    "packages/investinglab/src/investinglab",
                    "docs/architecture/index.md",
                    "notebooks/b1_toolkit_demo.ipynb",
                ),
                tests=("unit/test_package.py", "unit/test_notebooks.py"),
            ),
            Requirement(
                id="4.2",
                title_es="Ingesta multifuente y descarga simultánea de N series",
                title_en="Multi-source ingestion and concurrent download of N series",
                code=(
                    "investinglab.services.market_data.MarketDataService.get_many_bars",
                    "investinglab.services.registry.ProviderRegistry",
                    "investinglab.adapters.http.client.HttpClient",
                    "investinglab.adapters.storage.parquet.ParquetSeriesStore",
                    "investinglab.adapters.providers.files.LocalFilesProvider",
                    "investinglab.toolkit.Toolkit.many",
                ),
                tests=(
                    "unit/services/test_market_data.py",
                    "unit/services/test_registry.py",
                    "unit/adapters/test_http_client.py",
                    "unit/adapters/test_parquet_store.py",
                    "unit/adapters/test_local_files.py",
                    "unit/test_toolkit.py",
                ),
                status=RequirementStatus.PARTIAL,
                note_es=(
                    "Infraestructura completa (enrutado, reintentos, caché, lotes) y fuente de "
                    "ficheros locales. Faltan los proveedores remotos (Yahoo, Alpha Vantage, "
                    "FRED/ALFRED, BCE: fase F2b), pendientes de acceso a red."
                ),
                note_en=(
                    "Complete infrastructure (routing, retries, cache, batches) and the local "
                    "files source. Remote providers (Yahoo, Alpha Vantage, FRED/ALFRED, ECB: "
                    "phase F2b) await network access."
                ),
            ),
            Requirement(
                id="4.3",
                title_es="Clases de series de precios y carteras con estadísticos automáticos",
                title_en="Price series and portfolio classes with automatic statistics",
                code=(
                    "investinglab.domain.series.PriceSeries",
                    "investinglab.domain.series.SeriesStats",
                    "investinglab.domain.portfolio.Portfolio",
                    "investinglab.domain.metrics.RiskMetrics",
                ),
                tests=(
                    "unit/domain/test_series.py",
                    "unit/domain/test_portfolio.py",
                    "unit/domain/test_metrics.py",
                    "property/test_series_properties.py",
                ),
            ),
            Requirement(
                id="4.4",
                title_es="Monte Carlo como método de la cartera, con visualización",
                title_en="Monte Carlo as a portfolio method, with charts",
                code=(
                    "investinglab.domain.portfolio.Portfolio.monte_carlo",
                    "investinglab.domain.series.PriceSeries.monte_carlo",
                    "investinglab.domain.simulation.SimulationResult.plot",
                    "investinglab.analytics.montecarlo",
                ),
                tests=(
                    "unit/domain/test_simulation.py",
                    "unit/analytics/test_montecarlo.py",
                    "property/test_montecarlo_properties.py",
                    "unit/reporting/test_simulation_figure.py",
                ),
            ),
            Requirement(
                id="4.5",
                title_es="Limpieza y validación, informe report() y gráficos plots_report()",
                title_en="Cleaning and validation, report() and plots_report()",
                code=(
                    "investinglab.domain.series.PriceSeries",
                    "investinglab.domain.quality.assess_quality",
                    "investinglab.domain.fx.FxRates",
                    "investinglab.adapters.files.SeriesImporter",
                    "investinglab.domain.series.PriceSeries.report",
                    "investinglab.domain.portfolio.Portfolio.report",
                    "investinglab.domain.portfolio.Portfolio.plots_report",
                ),
                tests=(
                    "unit/domain/test_series.py",
                    "unit/domain/test_quality.py",
                    "unit/adapters/test_importer.py",
                    "unit/reporting/test_series_report.py",
                    "unit/reporting/test_portfolio_report.py",
                    "unit/reporting/test_charts.py",
                ),
            ),
            Requirement(
                id="4.6",
                title_es="Diagramas: capas, clases, secuencia y flujo de la simulación",
                title_en="Diagrams: layers, classes, sequence and simulation flow",
                code=(
                    "docs/architecture/index.md",
                    "docs/architecture/domain.md",
                    "docs/architecture/workflow.md",
                    "docs/architecture/simulation.md",
                ),
            ),
        ),
    )
)
"""The B1-T1 module and its traceability matrix."""
