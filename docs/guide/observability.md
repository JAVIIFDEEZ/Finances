# Observabilidad

Hay tres formas de saber qué hace la plataforma:

- **los logs**: siempre;
- **el latido de cada fuente de datos**, cuando hay base de datos y *worker*;
- **las trazas**, cuando se encienden.

## Logs

La API y el *worker* escriben un log estructurado por la salida de errores. En local va en texto
legible; en un despliegue, en JSON (`INVESTINGLAB_LOG_FORMAT=json`).

* **Cada petición** deja `http_request_served`: método, ruta, estado, milisegundos y su
  `request_id`. Ese id es el mismo que devuelve la cabecera `X-Request-ID` y el que citan los
  errores de la API (`instance`).
* **Cada trabajo** deja `job_started` y `job_finished`.
* **Cada fuente comprobada** deja `source_ok`, o `source_failing` con sus fallos seguidos.
* **Las credenciales se enmascaran** siempre (`api_key=***`), escriba la línea quien la escriba.

## El latido de las fuentes

El *worker* hace una petición de prueba a cada fuente al arrancar y cada cuarto de hora, y
guarda cómo respondió ([ADR-0047](../adr/0047-source-heartbeat.md)).

* **En la web:** la **Visión general** lo muestra junto a cada fuente.
* **En la API:** `GET /api/v1/sources` lo da, y `/health/ready` cuenta los *workers* en marcha.

Más detalle en [Fuentes de datos](data-sources.md#si-una-fuente-responde).

## Trazas

Las trazas muestran, de cada petición y de cada trabajo, qué hizo y dónde se fue el tiempo
([ADR-0048](../adr/0048-tracing-with-opentelemetry.md)): las llamadas a los proveedores, las
sentencias a la base de datos y, en un trabajo, cada intento del *worker*, todo en la misma
traza que la petición que lo envió. Usan OpenTelemetry, así que sirve cualquier *backend*
compatible con OTLP.

Están **apagadas por defecto**: así no hay exportador ni instrumentación.

### Verlas en local, con Jaeger

```bash
uv run just traces    # arranca Jaeger con Docker (en memoria: al pararlo, las olvida)
```

En `.env`:

```bash
INVESTINGLAB_API_TRACING=otlp
```

Después, `uv run just dev` (la API y el *worker* las envían a `http://localhost:4318`). En
`http://localhost:16686` se elige el servicio:

* **`investinglab-api`** tiene las peticiones (`GET /api/v1/market/bars`…) y, dentro, sus
  llamadas y sus sentencias.
* **`investinglab-worker`** tiene cada intento de un trabajo (`process jobs`) y cada
  comprobación de las fuentes (`check sources`).

Un trabajo enviado desde la web aparece como una sola traza:

```
POST /api/v1/jobs/simulations      (investinglab-api) la petición
├── INSERT INTO jobs …             el trabajo
└── send jobs                      su entrada en la cola, con su traceparent
    └── process jobs               (investinglab-worker) un intento
        ├── UPDATE jobs …          lo toma, escribe su progreso y su resultado
        └── GET …                  las llamadas a los proveedores que necesite
```

Para mirarlas sin Jaeger: `INVESTINGLAB_API_TRACING=console` escribe cada *span* como JSON por
la salida estándar.

### Con otro *backend*

Las variables estándar de OpenTelemetry configuran el envío:

| Variable | Para qué |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Dónde está el colector (por defecto `http://localhost:4318`) |
| `OTEL_EXPORTER_OTLP_HEADERS` | Credenciales de un colector alojado: solo por entorno, nunca en el repositorio |
| `OTEL_TRACES_SAMPLER`, `OTEL_TRACES_SAMPLER_ARG` | Qué fracción de trazas guardar (`parentbased_traceidratio` y `0.1`, una de cada diez) |
| `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` | Otro nombre de servicio, o atributos como `deployment.environment=prod` |

### De un log a su traza

Cada línea de log escrita dentro de un *span* lleva `trace_id` y `span_id`. Para encontrar la
traza de una línea, se busca su `trace_id` en Jaeger. Para encontrar los logs de una traza, se
busca su id en los logs.

### Lo que nunca se graba

* **Credenciales en una URL:** las llamadas hacia fuera se graban con `api_key=***`.
* **Valores de las consultas:** las sentencias se guardan con sus marcadores (`%(owner_id_1)s`).
* **Cabeceras.**
* **Las sondas de salud:** no se trazan, ni nada de lo que hacen.

### Para desarrolladores

`investinglab_api.telemetry` es el único módulo que importa OpenTelemetry; dos contratos de
`lint-imports` lo vigilan. Lo que la API traza por su cuenta pasa por ahí:

```python
from investinglab_api import telemetry

with telemetry.span("check sources") as span:
    span.event("source.checked", provider="yahoo", ok=True)
```

El núcleo (`investinglab`) no sabe nada de trazas.
