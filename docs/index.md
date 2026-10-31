# InvestingLab

Plataforma personal de análisis de mercados financieros, construcción de carteras y
simulación, en la que se incorpora módulo a módulo lo aprendido en el Máster MIAX.

!!! info "Estado"
    Fases **F0** (bootstrap) y **F1** (modelo de dominio) completadas. Consulta la
    [hoja de ruta](plan/plan-maestro.md) para ver las siguientes.

## Componentes

| Componente | Ubicación | Descripción |
|------------|-----------|-------------|
| Núcleo | `packages/investinglab` | Librería Python pura: dominio, ingesta multifuente, analytics, Monte Carlo e informes. Usable desde un notebook. |
| API | `apps/api` *(F6)* | FastAPI versionada (`/api/v1`) que orquesta los casos de uso del núcleo. |
| Web | `apps/web` *(F8)* | Next.js con tema oscuro de terminal financiero. |

## Por dónde empezar

- [Arquitectura](architecture/index.md): capas, reglas de dependencia y cómo se verifican.
- [Decisiones (ADR)](adr/index.md): el porqué de cada elección.
- [Referencia de la API Python](reference/index.md): generada desde los docstrings.
