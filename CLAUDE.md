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
- Proyecto hermano a migrar progresivamente: CryptoWorld. Programa por fases G0-G13, mapa pieza a
  pieza y matriz de paridad: `docs/plan/integracion-cryptoworld.md`

## Estructura

```
packages/investinglab/   núcleo: librería Python pura (usable desde un notebook)
  src/investinglab/
    analytics/   núcleo funcional: cálculo numérico puro       ← capa más interna
    domain/      dataclasses frozen+slots, sin I/O (usa analytics)
    ports/       Protocols que el núcleo espera del exterior
    reporting/   informes Markdown bilingües (es/en) + gráficos matplotlib
    services/    casos de uso (orquestan puertos/analytics/reporting)
    adapters/    http/, providers/<proveedor>/, storage/, calendars/, files/ (implementan puertos)
    modules/     un subpaquete por bloque del máster + registro y trazabilidad
    config/      Settings (pydantic-settings) y logging (structlog)
    toolkit.py   fachada pública y composition root para notebooks (ADR-0018)
  tests/         unit/, property/, contract/, integration/, fixtures/, support/
notebooks/       demos ejecutables, versionadas SIN resultados
scripts/         utilidades de desarrollo: casetes, arranque de API y web (`dev.py`), limpieza
apps/api/        API REST FastAPI (ADR-0027): app → routers → use_cases/mappers → schemas;
                 persistence/ (PostgreSQL, SQLAlchemy, migraciones Alembic; ADR-0029)
compose.yaml     servicios locales con Docker (por ahora, PostgreSQL)
apps/web/        web Next.js 16 + TypeScript estricto (ADR-0028): src/app (pantallas), src/components,
                 src/lib/api (cliente generado de apps/api/openapi.json), e2e/ (Playwright)
docs/            Zensical: guide/, adr/, architecture/, plan/, reference/, modules/
```

## Reglas de arquitectura (verificadas por `lint-imports`)

1. Dependencias siempre hacia dentro: `toolkit → modules → services | adapters → reporting |
   ports → domain → analytics`. `analytics` trabaja con arrays/series y no conoce el dominio.
2. `domain` no importa I/O, frameworks, gráficos ni `config`. Única excepción, declarada en
   `ignore_imports` ([ADR-0017](docs/adr/0017-bilingual-reports-and-charts.md)): `report()`,
   `plots_report()` y `plot()` importan `investinglab.reporting.entrypoints` de forma diferida,
   dentro del método. matplotlib es el *extra* opcional `plots`; los informes Markdown no lo
   necesitan.
3. `services` y `ports` dependen de abstracciones, nunca de `httpx`, `duckdb`, `yfinance`…
4. Cero lógica de negocio en routers de la API: validar → llamar caso de uso → mapear schema.
   La API solo habla con el núcleo a través del `Toolkit` (nunca con `adapters`) y sus
   errores son Problem Details (RFC 9457) con un `type` documentado en `docs/guide/api.md`.
5. Estado de usuario ([ADR-0029](docs/adr/0029-relational-persistence-and-owners.md)): los
   repositorios son `Protocol` en `ports/` y se implementan en `apps/api/persistence/`; solo
   ese paquete y `app.py` importan SQLAlchemy. Toda tabla nueva lleva `owner_id` con
   `ddl.owner_isolation()` en su migración (o se declara en `GLOBAL_TABLES`), todo método de
   repositorio recibe el propietario y lo ajeno responde 404. Lo que no debe reescribirse
   (experimentos, ejecución, auditoría) va al `AuditLog`, en la misma transacción que el cambio.
6. Nuevo proveedor = nuevo adaptador en `adapters/providers/<nombre>/` que implementa
   `MarketDataProvider` y/o `EconomicDataProvider`, declara sus `ProviderCapabilities`, usa
   `HttpClient` para la red y se registra en `ProviderRegistry`. Nada más cambia.
7. Nuevo bloque del máster = nuevo paquete en `modules/` que se registra con su `ModuleInfo`:
   requisitos redactados por nosotros → código → tests (un test exige que todo exista; la
   matriz de `docs/modules/` se regenera con `just traceability`). Lo reutilizable va al
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
- Textos de informes y gráficos: pares `(español, inglés)` en `reporting/i18n.py`; cifras con
  `Translator.percent/number/date`, nunca con f-strings sueltas.

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
uv run just traceability      # regenerar docs/modules/ desde el registro de módulos
uv run just record-fixtures   # regrabar las casetes de los proveedores (necesita red)
uv run just record-parity ../CryptoWorld  # regrabar la paridad de indicadores con CryptoWorld
uv run just web-install       # instalar las dependencias de la web (pnpm; `just dev` lo hace si faltan)
uv run just dev               # API (:8000, o INVESTINGLAB_API_PORT) y web (:3000) a la vez
uv run just preview           # igual, con la build de producción de la web (sin recarga)
uv run just mobile            # como preview, y accesible desde el móvil en la misma Wi-Fi (sin login: solo en casa)
uv run just api               # solo la API, en http://127.0.0.1:8000/docs, con recarga
uv run just db-up             # PostgreSQL local con Docker (compose.yaml)
uv run just db-upgrade        # llevar la base de datos al esquema de esta versión
uv run just db-revision "…"   # borrador de migración desde los modelos (revisarlo a mano)
uv run just openapi           # regenerar el contrato de la API y los tipos de la web (CI lo exige)
uv run just web-check         # lint + typecheck + Vitest + build de la web
uv run just web-e2e           # Playwright con la API sin red sobre datos sintéticos
```

Las recetas de `just` corren con bash en Linux y macOS y con PowerShell en Windows: cada línea
es un comando simple que entienden ambos (nada de `&&`, `cd`, variables en línea ni scripts de
bash). Lo que necesite más lógica va a un script de Python en `scripts/`, tipado y con tests.

## Tests

- Ningún test hace llamadas reales a red: el `conftest` fija `INVESTINGLAB_OFFLINE=true`. HTTP
  se mockea con `respx` usando **casetes**, respuestas reales grabadas en
  `tests/fixtures/cassettes/<proveedor>/` con `just record-fixtures` y reproducidas con
  `support.cassettes` (URL y parámetros exactos). No se editan a mano.
- Todo proveedor nuevo se añade como caso del contrato `tests/contract/`.
- Paridad con CryptoWorld: `tests/fixtures/parity/` guarda lo que calcula el propio código de
  CryptoWorld (`just record-parity`); no se edita a mano. Un indicador nuevo del catálogo
  entra en la paridad si CryptoWorld lo tiene.
- Web: Vitest para la lógica (`src/lib/__tests__/`) y Playwright de extremo a extremo con
  la API real sin red sobre ficheros **sintéticos** (`e2e/synthetic_data.py`).
- Móvil: toda pantalla nueva entra en `SCREENS` de `e2e/mobile.spec.ts` (sin desplazamiento
  lateral a 390 px); las rejillas llevan `grid-cols-1` de base y los controles usan los
  componentes de `ui.tsx`, que ya crecen en pantallas táctiles.
- Gráficos de la web: ECharts con la paleta validada de `src/lib/theme/tokens.ts`; colores
  ligados a la entidad, una tabla o lista de cifras junto a cada gráfico, nunca NaN en
  pantalla («—»).
- Los datos sintéticos (p. ej. GBM con semilla) van en una carpeta aparte y se nombran como
  sintéticos. Nunca se presentan como datos de mercado reales.
- Factorías y estrategias de Hypothesis en `tests/support/` (importables como `support.*`):
  generan datos **sintéticos** con proveedor `synthetic`.
- Property-based testing con `hypothesis` para estadísticos y Monte Carlo.
- Marcadores: `integration` (BD, filesystem pesado) y `network` (nunca en CI).
- Base de datos: los tests crean su propia base de datos en el servidor de
  `INVESTINGLAB_TEST_DATABASE_URL` y se conectan con un rol sin privilegios. Sin la variable
  se saltan; en la CI, que falte es un error. Cada repositorio pasa el mismo contrato en
  memoria (`support.repositories`) y en PostgreSQL (`test_repository_contract.py`).
- Los notebooks se versionan sin resultados y un test los ejecuta de principio a fin con
  ficheros sintéticos temporales (`tests/unit/test_notebooks.py`).

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
- `api.binance.com`, `fapi.binance.com` y `api.bybit.com` rechazan el contenedor (HTTP 451 y
  403) aunque estén permitidos: sus casetes se graban desde un equipo propio. Las velas *spot*
  de Binance salen de `data-api.binance.vision`, que sí responde.
- No hay daemon de Docker: las imágenes se validan en GitHub Actions.
