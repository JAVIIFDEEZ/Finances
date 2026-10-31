# InvestingLab

[![Python](https://github.com/JAVIIFDEEZ/Finances/actions/workflows/python.yml/badge.svg?branch=development)](https://github.com/JAVIIFDEEZ/Finances/actions/workflows/python.yml)

Plataforma personal de análisis de mercados financieros: ingesta multifuente de datos de
mercado, construcción y análisis de carteras, simulación Monte Carlo e informes. Se amplía
módulo a módulo con lo aprendido en el Máster MIAX.

> **Estado:** fase F0 (bootstrap). La hoja de ruta completa está en
> [`docs/plan/plan-maestro.md`](docs/plan/plan-maestro.md). Este README se completará en la
> fase F5 con la guía de uso como librería, API y frontend.

## Requisitos

- [uv](https://docs.astral.sh/uv/) ≥ 0.9 (instala Python 3.14 automáticamente)
- Git

## Puesta en marcha

```bash
git clone https://github.com/JAVIIFDEEZ/Finances.git investinglab
cd investinglab
uv sync --all-groups      # dependencias + toolchain (incluye `just`)
uv run just setup         # hooks de git
uv run just check         # lint + typecheck + tests
cp .env.example .env      # configuración local (opcional)
```

## Estructura

| Ruta | Contenido |
|------|-----------|
| `packages/investinglab` | Núcleo: librería Python pura con arquitectura hexagonal |
| `apps/` | API (FastAPI) y web (Next.js), a partir de las fases F6 y F8 |
| `docs/` | Documentación (Zensical): arquitectura, ADRs, referencia |

## Documentación

```bash
uv run just docs          # http://localhost:8000
```

- [Arquitectura](docs/architecture/index.md)
- [Decisiones de arquitectura (ADR)](docs/adr/index.md)
- [Convenciones del repositorio](CLAUDE.md)
