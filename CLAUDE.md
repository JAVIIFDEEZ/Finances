# CLAUDE.md — InvestingLab

Guía de trabajo y convenciones del repositorio (también la leen los asistentes de código).
Léela entera antes de cambiar nada. Si una regla de aquí entra en conflicto con lo que pide
el usuario, pregunta.

## Qué es

**InvestingLab** es la plataforma financiera personal de Javier: ingesta multifuente de datos
de mercado, carteras, analytics de riesgo, Monte Carlo e informes. Se amplía módulo a módulo
con lo aprendido en el Máster MIAX. Objetivo de calidad: repositorio profesional de fintech.

- Hoja de ruta y fases: `docs/plan/plan-maestro.md`
- Decisiones de arquitectura: `docs/adr/` (MADR 4)
- Proyecto hermano a migrar progresivamente: CryptoWorld (ver plan, sección 9)

## Estructura

```
packages/investinglab/   núcleo: librería Python pura (usable desde un notebook)
  src/investinglab/
    analytics/   núcleo funcional: cálculo numérico puro       ← capa más interna
    domain/      dataclasses frozen+slots, sin I/O (usa analytics)
    ports/       Protocols que el núcleo espera del exterior
    reporting/   Markdown + matplotlib/seaborn
    services/    casos de uso (orquestan puertos/analytics/reporting)
    adapters/    http/, providers/<proveedor>/, storage/ (implementan puertos)
    modules/     un subpaquete por bloque del máster + registro
    config/      Settings (pydantic-settings) y logging (structlog)
  tests/         unit/, property/, contract/, integration/, fixtures/
apps/api/        FastAPI (fase F6)        apps/web/   Next.js (fase F8)
docs/            Zensical: adr/, architecture/, plan/, reference/, modules/
```

## Reglas de arquitectura (verificadas por `lint-imports`)

1. Dependencias siempre hacia dentro: `toolkit → modules → services | adapters → reporting |
   ports → domain → analytics`. `analytics` trabaja con arrays/series y no conoce el dominio.
2. `domain` no importa I/O, frameworks, gráficos ni `config`.
3. `services` y `ports` dependen de abstracciones, nunca de `httpx`, `duckdb`, `yfinance`…
4. Cero lógica de negocio en routers de la API: validar → llamar caso de uso → mapear schema.
5. Nuevo proveedor = nuevo adaptador en `adapters/providers/<nombre>/` que implementa
   `MarketDataProvider` y/o `EconomicDataProvider`, declara sus `ProviderCapabilities`, usa
   `HttpClient` para la red y se registra en `ProviderRegistry`. Nada más cambia.
6. Nuevo bloque del máster = nuevo paquete en `modules/` que se registra. Lo reutilizable va al
   núcleo (`analytics`, `services`…), no se queda atrapado dentro del módulo.

## Reglas de datos (no negociables)

- **Nunca inventar datos.** Prohibidos `bfill` e interpolación. Un festivo es un hueco (NaN), no
  un retorno de 0 %. La valoración usa el último precio observado y expone su antigüedad.
- **Point-in-time.** La macro se une por fecha de publicación (FRED en modo ALFRED). Los
  fundamentales se indexan por fecha de presentación.
- **Validación estricta** en los bordes: una serie de precios exige índice temporal monótono y
  sin duplicados, precios finitos > 0, divisa ISO, frecuencia y procedencia.
- Outliers: se detectan y se reportan (`DataQualityReport`); nunca se borran automáticamente.
- Divisas: conversión *as-of* con `FxRates` (el último fixing publicado); sin fixing → la
  observación se descarta, nunca se rellena.
- Fechas siempre con zona horaria (`DTZ` de ruff lo vigila).

## Convenciones de código

- Python ≥ 3.13 (desarrollo en 3.14). Tipado completo; `mypy --strict` también en tests.
- Dominio con `@dataclass(frozen=True, slots=True)`; Pydantic v2 solo en los bordes (entradas,
  API, configuración).
- pandas y NumPy en la interfaz pública.
- Docstrings estilo Google en todo lo público. Imports absolutos (`ban-relative-imports`).
- Nada de `print`: usa `investinglab.config.get_logger(__name__)`. Los logs enmascaran
  credenciales (`api_key=`, `token=`…) automáticamente; aun así, nunca registres secretos.
- Idioma ([ADR-0004](docs/adr/0004-language-policy.md)): código, docstrings, commits y API en
  inglés; docs, ADRs y este fichero en español; UI e informes bilingües.

## Comandos

```bash
uv sync --all-groups          # instalar todo (incluye just, ruff, mypy, pytest…)
uv run just setup             # + instalar hooks de git
uv run just check             # lint + typecheck + tests (lo mismo que la CI)
uv run just lint              # ruff check + ruff format --check + lint-imports
uv run just fmt               # autoformatear
uv run just typecheck         # mypy --strict
uv run just test [args]       # pytest con cobertura (umbral 90 %)
uv run just test-fast [args]  # pytest -x sin cobertura
uv run just docs              # web de documentación con recarga en vivo
```

## Tests

- Ningún test hace llamadas reales a red. HTTP se mockea con `respx` usando respuestas
  **reales grabadas** en `tests/fixtures/` (`just record-fixtures` a partir de F2).
- Los datos sintéticos (p. ej. GBM con semilla) van en una carpeta aparte y se nombran como
  sintéticos. Nunca se presentan como datos de mercado reales.
- Factorías y estrategias de Hypothesis en `tests/support/` (importables como `support.*`):
  generan datos **sintéticos** con proveedor `synthetic`.
- Property-based testing con `hypothesis` para estadísticos y Monte Carlo.
- Marcadores: `integration` (BD, filesystem pesado) y `network` (nunca en CI).

## Flujo de trabajo

- Ramas: `feat/*`, `fix/*`, `chore/*`, `docs/*` desde `development` → PR a `development`.
  `main` solo recibe releases etiquetadas.
- Conventional Commits pequeños y atómicos (lo valida un hook `commit-msg`).
- Cada fase termina con `just check` en verde y un resumen: hecho, pendiente, deuda técnica.
- Los PR se mergean a `development` cuando la CI está en verde.
- Sin etiquetas de autoría automáticas: nada de trailers `Co-Authored-By`, pies tipo
  "Generated with…" ni enlaces de sesión en commits, PR o documentación.
- Decisión de arquitectura relevante → ADR en el mismo PR.
- Si cambian comandos, convenciones o estructura → actualizar este fichero.

## Seguridad

- Nunca commitear secretos: `.env` está ignorado; `detect-secrets` corre en cada commit.
- Credenciales de proveedores solo por entorno (`INVESTINGLAB_FRED_API_KEY`,
  `INVESTINGLAB_ALPHAVANTAGE_API_KEY`…) como `SecretStr`. Nunca en código, tests ni chat.
  Si aparece un falso positivo, actualiza `.secrets.baseline` con
  `uv run detect-secrets scan --baseline .secrets.baseline`.
- Nunca commitear material de clase: `docs/enunciados/` está ignorado.

## Entorno de ejecución en la nube

- La red del contenedor bloquea por defecto las APIs de datos (Yahoo, FRED, Alpha Vantage…).
  Las listas de dominios a permitir están en el plan (sección 16). Sin red, se trabaja con
  fixtures grabadas; no se fabrican datos.
- No hay daemon de Docker: las imágenes se validan en GitHub Actions.
