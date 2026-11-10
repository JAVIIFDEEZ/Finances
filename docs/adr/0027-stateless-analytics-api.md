---
status: aceptado
date: 2026-11-10
decision-makers: Javier Fernández
---

# API REST sin estado sobre el Toolkit, con Problem Details y contrato OpenAPI versionado

## Contexto y problema

La web (fases F8/F9) necesita el núcleo por HTTP: datos de mercado, análisis de carteras,
Monte Carlo, optimización y planes de ahorro. El plan sitúa la API en la fase F6 junto con
Postgres, carteras guardadas y, en F7, autenticación. Hay que decidir qué API se construye ya,
cómo se separa del núcleo y cómo se mantiene sincronizada con su cliente web.

## Factores de decisión

* Regla 4 de CLAUDE.md: cero lógica de negocio en los routers.
* El núcleo ya tiene su composition root (`Toolkit`, ADR-0018); la API no debe duplicarlo.
* Errores útiles para la interfaz, sin filtrar detalles internos.
* Un cliente web tipado que no se desincronice de la API.
* Proteger el servicio de peticiones desmesuradas (miles de símbolos, millones de trayectorias).

## Opciones consideradas

* API sin estado ahora (las carteras viajan en la petición); persistencia después (F6b).
* API con Postgres desde el principio.
* FastAPI frente a Litestar o Django Ninja.

## Decisión

Opción elegida: **API FastAPI sin estado** en `apps/api` (paquete `investinglab-api` del
workspace de uv), porque desbloquea la web ya y deja la persistencia para cuando haya
usuarios (F6b/F7).

* **Composition root.** `create_app()` construye el `AsyncToolkit` desde los ajustes del núcleo
  en el *lifespan* y lo cierra al apagar. Los tests le inyectan uno con proveedores falsos.
* **Capas** (verificadas por `lint-imports`): `app` → `routers` → `use_cases` / `mappers` →
  `schemas`, y la API no importa `investinglab.adapters` ni E/S directa (`httpx`, `duckdb`…).
  * Los *routers* validan (Pydantic, límites), llaman a un caso de uso y mapean.
  * Los *casos de uso* orquestan el Toolkit y los métodos del dominio; no calculan nada.
  * Los *mappers* solo cambian la forma: DataFrames a listas, fechas a ISO 8601, NaN a `null`.
  * El trabajo de CPU (backtests, Monte Carlo, optimización) corre en un hilo para no
    bloquear el bucle de eventos.
* **Endpoints** (`/api/v1`): `market/bars`, `market/compare`, `market/quality`,
  `rates/risk-free`, `portfolios/validate|analytics|report`, `simulations`, `optimizations`,
  `plans`, `providers`, `modules`, más `/health/live` y `/health/ready`. Como aún no hay
  carteras guardadas, el plan `GET /portfolios/{id}/analytics` es por ahora
  `POST /portfolios/analytics` con la cartera en el cuerpo.
* **Errores RFC 9457** (`application/problem+json`): `type` estable que apunta a su sección de
  la [guía de la API](../guide/api.md), `title`, `status`, `detail`, `instance` con el id de la
  petición y extensiones `errors` (validación) y `attempts` (proveedores probados). Los datos
  no encontrados son 404; las fuentes caídas, 503 con `Retry-After` si es reintentable; los
  errores inesperados, 500 sin detalles internos.
* **Trazabilidad.** Cada respuesta lleva `X-Request-ID` (se acepta el del cliente si es
  seguro), ligado a los logs estructurados de la petición.
* **Límites** configurables (`INVESTINGLAB_API_*`): símbolos por petición, trayectorias,
  horizonte y puntos de frontera. Superarlos es un `invalid-request`.
* **CORS** solo para los orígenes de la web (por defecto `localhost:3000`).
* **Contrato.** `apps/api/openapi.json` se versiona (`just openapi`) y un test falla si deja
  de coincidir con la API. La web genera sus tipos desde ese fichero.
* Reglas de validación compartidas con el núcleo: `weight_problems()` (dominio) valida los
  pesos igual que `Portfolio`; `AlignedPanel.correlation()` da la misma correlación que las
  carteras; `AsyncToolkit.metrics()` usa el tipo libre de riesgo *point-in-time*.

### Consecuencias

* Positiva: la web puede construirse ya contra un contrato tipado y estable.
* Positiva: la API no duplica cálculos: cualquier mejora del núcleo llega sola.
* Negativa: sin persistencia, cada petición reconstruye la cartera (la caché de datos lo
  amortigua). Las carteras guardadas llegan con F6b.
* Negativa: sin autenticación, la API solo debe escuchar en local (`127.0.0.1` por defecto)
  hasta F7.

### Confirmación

* `apps/api/tests/`: cada endpoint con datos sintéticos, los Problem Details (404, 422, 503,
  504, 500, 405), CORS, `X-Request-ID`, límites, la CLI y la vigencia de `openapi.json`.
* Contratos de `lint-imports`: «The API reaches the core through the toolkit…» y «API layers…».

## Pros y contras de las opciones

### Sin estado ahora

* Positivo: entrega rápida, sin infraestructura nueva.
* Negativo: los endpoints de carteras cambiarán de forma al llegar la persistencia.

### Con Postgres desde el principio

* Positivo: el diseño final de rutas desde el primer día.
* Negativo: base de datos, migraciones y usuarios antes de tener una sola pantalla.

### FastAPI frente a Litestar o Django Ninja

* Positivo (FastAPI): OpenAPI 3.1 automático, Pydantic v2 nativo y el ecosistema más amplio.
* Negativo: algo menos de rendimiento que Litestar, irrelevante para cálculos dominados por
  NumPy.

## Más información

* Plan maestro, secciones 10 (API) y 13 (fases F6–F7).
* [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457): Problem Details for HTTP APIs.
