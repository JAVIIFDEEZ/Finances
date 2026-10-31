# Arquitectura

InvestingLab sigue una **arquitectura hexagonal** (puertos y adaptadores) dentro de un
monorepo ([ADR-0002](../adr/0002-hexagonal-monorepo-with-independent-core.md)). Las
dependencias apuntan siempre hacia el dominio: el dominio no conoce ni las APIs externas, ni
FastAPI, ni la base de datos.

## Capas del núcleo (`packages/investinglab`)

```mermaid
flowchart TB
    TOOLKIT[toolkit · fachada pública y composition root]
    MODULES[modules · bloques del máster]
    SERVICES[services · casos de uso]
    ADAPTERS[adapters · providers, storage, http]
    REPORTING[reporting · Markdown y gráficos]
    PORTS[ports · Protocols]
    DOMAIN[domain · dataclasses inmutables]
    ANALYTICS[analytics · núcleo numérico puro]

    TOOLKIT --> MODULES
    TOOLKIT --> ADAPTERS
    MODULES --> SERVICES
    SERVICES --> REPORTING
    SERVICES --> PORTS
    REPORTING --> DOMAIN
    PORTS --> DOMAIN
    DOMAIN --> ANALYTICS
    ADAPTERS -.implementa.-> PORTS
```

| Capa | Responsabilidad | Puede importar |
|------|-----------------|----------------|
| `analytics` | Núcleo funcional: cálculo numérico puro sobre arrays/series (retornos, riesgo, simulación). No conoce el dominio | NumPy, pandas, SciPy |
| `domain` | Value objects y entidades inmutables (`frozen=True`, `slots=True`), invariantes y métodos de negocio | `analytics`, Pydantic |
| `ports` | Interfaces (`Protocol`) que el núcleo espera del exterior | `domain` |
| `reporting` | Informes Markdown y gráficos estáticos | `domain`, `analytics` |
| `services` | Casos de uso que orquestan puertos, dominio y reporting | capas internas |
| `adapters` | Implementaciones concretas de los puertos (HTTP, Parquet, DuckDB) | `ports`, `domain`, `config` |
| `modules` | Contenido específico de cada bloque del máster | `services` y capas internas |
| `toolkit` | Fachada pública y composition root para notebooks | todo |

`config` (settings y logging) es transversal y lo usan los adaptadores y las aplicaciones;
el dominio tiene prohibido importarlo.

## Cómo se verifica

Las reglas no dependen de la disciplina: `import-linter` las comprueba en cada commit
(pre-commit) y en CI. Los contratos están en `pyproject.toml`, sección `[tool.importlinter]`:

- capas en el orden de la tabla (una capa externa puede importar una interna, nunca al revés);
- el dominio no importa I/O, frameworks, gráficos ni configuración;
- analytics es un núcleo numérico puro: sin I/O, sin gráficos, sin configuración y sin
  importar el dominio;
- casos de uso y puertos no importan infraestructura concreta.

- [Modelo de dominio y diagrama de clases](domain.md)

El diagrama de secuencia (ingesta → cartera → simulación → reporte) se añadirá con las fases F2–F5.
