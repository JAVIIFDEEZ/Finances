---
status: aceptado
date: 2026-11-23
decision-makers: Javier Fernández
---

# Trazas con OpenTelemetry, opcionales y apagadas por defecto

## Contexto y problema

G0b cierra con la observabilidad mínima. El plan pide dos cosas para la API y el *worker*:

- Sentry u OpenTelemetry;
- un latido de frescura por fuente de datos.

El latido ya está ([ADR-0047](0047-source-heartbeat.md)); falta saber **qué hizo cada
petición y cada trabajo, y dónde se fue el tiempo**. Hoy hay dos pistas, y ninguna basta:

- el `X-Request-ID` en los logs de una petición;
- el estado de cada trabajo en `jobs`.

Un trabajo cruza procesos: la API lo envía y un *worker* lo ejecuta más tarde, quizá más de una
vez. Una petición lenta puede deberse a la red de un proveedor, a la base de datos o al cálculo.

Antes de los procesos que corren todo el día (G7 y G8) hace falta poder seguir una operación de
principio a fin.

## Factores de decisión

* **Un estándar abierto**, no un proveedor: cualquier *backend* (Jaeger, Tempo, Honeycomb,
  Datadog…) debe servir sin tocar el código.
* **Apagado por defecto y sin coste apagado.** Es una plataforma personal: nadie debe necesitar
  un colector para trabajar.
* **El trabajo como una sola traza**, desde la petición que lo envía hasta cada intento del
  *worker*.
* **Ningún secreto en una traza**, igual que en los logs: claves en la URL (`api_key=`), valores
  de las consultas.
* **El núcleo no se entera.** La librería sigue sin dependencias de observabilidad (regla 3) y
  es usable desde un notebook.
* **Logs y trazas enlazados:** de una línea de log a su traza, y al revés.

## Opciones consideradas

1. **OpenTelemetry** con exportación OTLP, en la API y el *worker*.
2. **Sentry**: errores y rendimiento con su SDK.
3. **Solo logs estructurados** con el `request_id` y el id del trabajo.

## Decisión

Opción 1.

### Encendido

* **Un ajuste.** `INVESTINGLAB_API_TRACING` vale `off` (por defecto), `otlp` o `console`. La API
  y el *worker* lo leen igual.
* **Con `otlp`**, el exportador se configura con las variables estándar de OpenTelemetry:
  * `OTEL_EXPORTER_OTLP_ENDPOINT`, por defecto `http://localhost:4318`;
  * `OTEL_EXPORTER_OTLP_HEADERS`, para un colector con credenciales, que van siempre por entorno;
  * `OTEL_TRACES_SAMPLER`;
  * `OTEL_SERVICE_NAME` y `OTEL_RESOURCE_ATTRIBUTES`.
* **Los servicios** se llaman `investinglab-api` e `investinglab-worker`, en el espacio de
  nombres `investinglab`.
* **Con `console`**, cada *span* sale como JSON por la salida estándar, para mirarlas mientras
  se desarrolla.
* **Jaeger.** `just traces` arranca Jaeger en local (un perfil de `compose.yaml`) y sus trazas
  se ven en `http://localhost:16686`.

### Qué se traza

* **Cada petición**, con su ruta (`http.route`), su estado y su `investinglab.request_id`.
  * Sin un *span* por mensaje ASGI.
  * Las sondas de salud no se trazan, ni nada de lo que hacen. Se piden cada pocos segundos y
    enterrarían el resto.
* **Cada llamada hacia fuera**, dentro de la petición o el trabajo que la hizo:
  * las peticiones HTTP a los proveedores (instrumentación de `httpx`);
  * las sentencias a la base de datos (instrumentación de SQLAlchemy).
* **Cada trabajo**, con las convenciones de mensajería de OpenTelemetry:
  * Al enviarlo, un *span* `send jobs` (productor) dentro de la petición. La entrada de la cola
    lleva su contexto W3C (`traceparent`).
  * Cada intento del *worker* es un *span* `process jobs` (consumidor), hijo de ese envío. Así
    el trabajo, sus reintentos y sus sentencias quedan en la misma traza.
  * Lleva tipo, id, intento y estado final. Un trabajo fallido marca el *span* como error, con
    el código del problema (`invalid-request`…), nunca con datos del dueño.
* **Cada comprobación de las fuentes**: un *span* `check sources` con un evento por fuente.
  Una fuente que falla es un evento, no un fallo de la comprobación.
* **Los logs.** Cada línea escrita dentro de un *span* lleva su `trace_id` y su `span_id`. Es un
  procesador de structlog que la API pasa a `configure_logging`; el núcleo solo ofrece el
  enganche.

### Lo que nunca se graba

* **Credenciales en las URL.** Las de las llamadas hacia fuera se enmascaran con la misma regla
  que los logs (`redact_text`, `api_key=***`). La instrumentación solo oculta el usuario y la
  contraseña; la clave de la *query* habría pasado tal cual.
* **Valores de las consultas.** Las sentencias se graban con sus marcadores (`%(owner_id_1)s`),
  sin los valores.
* **Las cabeceras**, que no se capturan.
* **La descripción de un error** también se enmascara.

### Dónde vive

* **`investinglab_api.telemetry`** es el único módulo que importa OpenTelemetry. El resto de la
  API le pide *spans* y contextos en sus propios términos (`span`, `current_carrier`,
  `annotate`, `untraced`).
* **Dos contratos de `lint-imports` lo vigilan:**
  * ningún otro módulo de la API importa `opentelemetry`;
  * el núcleo no importa ni `opentelemetry` ni `investinglab_api`.
* **El trazado es del proceso y se configura una vez.** Las instrumentaciones de `httpx` y
  SQLAlchemy envuelven las fábricas de clientes y motores, así que lo que se crea después queda
  trazado. Por eso `Database` busca `create_async_engine` al llamarla, no al importarla: con la
  referencia importada, sus sentencias no se trazaban.

### Consecuencias

* Buenas:
  * un trabajo se sigue de la petición al *worker*, con sus reintentos, su red y su base de datos;
  * vale cualquier *backend* compatible con OTLP, sin tocar el código;
  * apagado, no hay exportador ni instrumentación, y las llamadas a `span` no hacen nada;
  * logs y trazas se encuentran entre sí por sus ids.
* Malas:
  * seis dependencias directas más en la API: API, SDK, exportador OTLP/HTTP y las tres
    instrumentaciones;
  * **la instrumentación de SQLAlchemy 0.66b2 declara SQLAlchemy < 2.1** y usamos la 2.1.8. Se
    salta su comprobación de versión (`skip_dep_check`) porque solo usa los eventos estables
    del motor, y un test comprueba que las sentencias de la 2.1 se trazan. Cuando una versión
    declare la 2.1, se quita;
  * las instrumentaciones parchean de forma global (fábricas de `httpx` y de motores); los tests
    las quitan al terminar (`shutdown_tracing`);
  * todavía no hay métricas: van con F14, junto a las alertas.

### Confirmación

* **Tests con un exportador en memoria:**
  * apagado por defecto, sin efectos;
  * cada modo con su procesador y su exportador;
  * `OTEL_SERVICE_NAME` manda;
  * la primera configuración del proceso gana;
  * un *span* continúa el contexto que recibe;
  * los ids llegan a los logs;
  * las URL de `httpx`, síncrono y asíncrono, salen enmascaradas;
  * cada petición es un *span* con ruta e id;
  * las sondas no dejan ningún *span*;
  * un intento fallido es un *span* de error;
  * la comprobación de fuentes tiene un evento por fuente.
* **Integración en PostgreSQL**, de la petición al *worker* real:
  * la entrada de la cola lleva el `traceparent`;
  * `send jobs` es hijo de la petición y `process jobs` del envío, en la misma traza;
  * las sentencias del trabajo son hijas de su intento y no llevan valores;
  * el *worker* traza cuando se le pide y lo apaga al terminar.
* **Comprobación real** (23-11-2026): la API con `INVESTINGLAB_API_TRACING=otlp` envió por
  OTLP/HTTP a un receptor local:
  * la petición, con su ruta y su `X-Request-ID`;
  * la llamada al BCE, dentro de la misma traza;
  * nada de las sondas.

## Pros y contras de las opciones

### Sentry

* Bueno: errores agrupados, alertas y rendimiento listos para usar.
* Malo:
  * es un proveedor concreto; su modelo de trazas va por su SDK, aunque hoy acepte OpenTelemetry;
  * su servicio alojado es la opción natural, y eso implica enviar datos fuera.
  * Puede recibir estas mismas trazas por OTLP si algún día se quiere.

### Solo logs

* Bueno: nada nuevo que instalar.
* Malo:
  * no mide dónde se va el tiempo;
  * no une la petición con el *worker* sin reinventar la propagación de contexto.

## Más información

* [ADR-0046](0046-background-jobs-on-postgresql.md): la cola y el *worker*.
* [ADR-0047](0047-source-heartbeat.md): el latido de las fuentes, la otra mitad de la
  observabilidad mínima.
* [Observabilidad](../guide/observability.md): cómo encenderlo y verlo.
