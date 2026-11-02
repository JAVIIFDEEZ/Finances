# InvestingLab

Plataforma personal de análisis de mercados financieros, construcción de carteras y
simulación, en la que se incorpora módulo a módulo lo aprendido en el Máster MIAX.

!!! info "Estado"
    El taller B1-T1 está implementado como librería y se usa desde un notebook con datos
    propios (fases F0–F5). Los proveedores remotos (F2b) esperan acceso de red: el detalle por
    requisito está en la [matriz de trazabilidad](modules/b1-toolkit.md). Consulta la
    [hoja de ruta](plan/plan-maestro.md).

## Componentes

| Componente | Ubicación | Descripción |
|------------|-----------|-------------|
| Núcleo | `packages/investinglab` | Librería Python pura: dominio, ingesta multifuente, analytics, Monte Carlo e informes. Usable desde un notebook. |
| API | `apps/api` *(F6)* | FastAPI versionada (`/api/v1`) que orquesta los casos de uso del núcleo. |
| Web | `apps/web` *(F8)* | Next.js con tema oscuro de terminal financiero. |

## Por dónde empezar

- [Guía del Toolkit](guide/toolkit.md): usar la librería desde un notebook, con tus datos.
- [Arquitectura](architecture/index.md): capas, reglas de dependencia y cómo se verifican.
- [Decisiones (ADR)](adr/index.md): el porqué de cada elección.
- [Referencia de la API Python](reference/index.md): generada desde los docstrings.
