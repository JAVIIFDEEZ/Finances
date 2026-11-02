# Referencia de la API

Documentación generada automáticamente a partir de los docstrings del paquete
`investinglab` con [mkdocstrings](https://mkdocstrings.github.io/). Cada página corresponde a
un subpaquete público; se irán añadiendo a medida que se implementen las fases.

| Paquete | Contenido |
|---------|-----------|
| [`investinglab.toolkit`](toolkit.md) | Fachada pública: descarga, carteras, calidad e informes desde un notebook |
| [`investinglab.domain`](domain.md) | Modelo de dominio: series, carteras, instrumentos, divisas, tiempo y simulación |
| [`investinglab.analytics`](analytics.md) | Núcleo numérico: retornos, drawdown, momentos, riesgo, covarianza (con Ledoit-Wolf), motor de carteras y núcleos de Monte Carlo |
| [`investinglab.ports`](ports.md) | Contratos de proveedores, caché y errores de proveedor |
| [`investinglab.services`](services.md) | Casos de uso: ingesta multifuente con caché, *fallback* y lotes |
| [`investinglab.reporting`](reporting.md) | Informes Markdown bilingües con diagnósticos, gráficos de series, carteras y simulaciones, tema visual común |
| [`investinglab.adapters`](adapters.md) | Cliente HTTP resiliente, caché Parquet + DuckDB, calendarios oficiales e importación de ficheros propios |
| [`investinglab.modules`](modules.md) | Registro de los módulos del máster y su trazabilidad |
| [`investinglab.config`](config.md) | Configuración validada y logging estructurado |
