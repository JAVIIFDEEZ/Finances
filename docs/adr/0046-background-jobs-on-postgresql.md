---
status: aceptado
date: 2026-11-23
decision-makers: Javier Fernández
---

# Trabajos en segundo plano con Procrastinate sobre el mismo PostgreSQL

## Contexto y problema

G0b pide trabajos en segundo plano (F13): los backtests de G3 y el Laboratorio de G4 no caben en
una petición HTTP. CryptoWorld ya lo resuelve con el patrón `202 + Location`: el cliente envía el
trabajo, recibe dónde consultarlo y lo lee hasta que termina.

El plan dejó abierta la cola (§10.2 de la integración): Procrastinate, sobre PostgreSQL y sin
Redis, o Taskiq con Redis. Hace falta decidirla antes de G3, junto con:

- cómo se guarda el estado de cada trabajo y cómo se respeta el propietario (ADR-0029);
- qué ocurre si se pierde un *worker*;
- cómo se informa del progreso;
- cómo se cancela un trabajo.

## Factores de decisión

* **Una pieza menos que operar.** PostgreSQL ya está (G0a); Redis sería otro servicio en
  desarrollo, en la CI y en producción.
* **Atomicidad con el estado.** Un trabajo y su sitio en la cola tienen que escribirse juntos:
  ni trabajos que nadie ejecutará, ni ejecuciones sin su trabajo. Además, el registro de
  auditoría va en la misma transacción que el cambio (regla 5).
* **El propietario manda.** Lo que ve cada dueño (parámetros, progreso, resultado) vive en una
  tabla con `owner_id` y seguridad a nivel de fila, como las carteras.
* **Python 3.14, asíncrono, con psycopg 3:** el mismo controlador que ya usa la API.
* **Tareas periódicas**, que harán falta en G8 (alertas) y en los refrescos programados.

## Opciones consideradas

1. **Procrastinate** sobre el mismo PostgreSQL.
2. **Taskiq con Redis.**
3. **Una cola propia** sobre la tabla `jobs` (`SELECT … FOR UPDATE SKIP LOCKED` y
   `LISTEN/NOTIFY`).
4. **Celery o arq** (Redis o RabbitMQ).

## Decisión

Opción 1, porque cumple todos los factores. El estado que ve el dueño queda en una tabla
nuestra; la cola solo transporta qué trabajo ejecutar.

### Las dos tablas

* **`jobs`** (migración 0002): una fila por trabajo.
  * Contiene tipo, estado, parámetros, progreso, etapa, resultado o error, intentos e instantes.
  * Lleva `owner_id` con RLS forzada (`ddl.owner_isolation`).
  * Las reglas de su ciclo de vida también son `CHECK` en la base de datos: resultado solo si
    terminó bien, error solo si falló, instante de fin solo si terminó.
* **Las tablas de Procrastinate** (`procrastinate_*`).
  * Su entrada lleva solo `job_id` y `owner_id`.
  * Son globales: no son modelos, y las comparaciones de esquema y Alembic las ignoran.

### Envío

`SqlJobRepository.submit` hace tres cosas en **una transacción**:

1. Inserta la fila en `jobs`.
2. La encola con la API pública de Procrastinate sobre la conexión psycopg de esa misma
   transacción (`configure_task(…, connection=…)`, *atomic deferral*).
3. Añade la entrada `job.submitted` al registro de auditoría.

Si falla cualquiera de los tres, no queda nada.

### Ciclo de vida

```
queued ──> running ──> succeeded | failed | cancelled
   └─────────────────────────────────────> cancelled
```

* **Transiciones condicionales.** Cada cambio es un `UPDATE … WHERE status = …`, así que dos
  *workers* (o un *worker* y una cancelación) no pueden ganar los dos.
* **Trabajos ya cerrados.** Un trabajo terminado o cancelado no vuelve a ejecutarse: el *worker*
  que lo recibe lo salta.

### *Worker*

* Es **un proceso del mismo paquete**: `investinglab-api worker` (`just worker`).
* Comparte ajustes, núcleo, persistencia y tipos de trabajo con la API, pero espera en la cola
  en lugar de responder peticiones.
* Ejecuta `INVESTINGLAB_API_WORKER_CONCURRENCY` trabajos a la vez (2 por defecto).
* Borra de la cola las entradas que terminaron bien. Nuestra tarea nunca lanza: anota cualquier
  fallo en `jobs`.

### Progreso y cancelación

* **Progreso.** El trabajo informa con `Progress.update(fracción, etapa)`, también desde un hilo
  (el Monte Carlo informa tras cada bloque). Cada segundo el *runner* escribe el último dato y lee
  si el dueño pidió cancelar.
* **Cancelar un trabajo en cola** lo termina al momento.
* **Cancelar uno en marcha** marca `cancel_requested`:
  * un trabajo que espera red se interrumpe enseguida;
  * uno que calcula en un hilo se para en su siguiente aviso de progreso.

### *Worker* perdido

* Los *workers* envían un latido. Cada minuto, una tarea periódica de mantenimiento devuelve a
  la cola los trabajos de un *worker* que dejó de enviarlo.
* El siguiente arranque cuenta como otro intento. A partir del cuarto, el trabajo termina como
  `job-interrupted`.
* Al parar el *worker* (Ctrl+C o `SIGTERM`), los trabajos en marcha tienen 30 segundos. Los que
  no acaban quedan como `job-interrupted`.

### API

* `POST /api/v1/jobs/simulations` responde `202` con `Location` y `Retry-After`. Ese mismo
  `Retry-After` acompaña a `GET /api/v1/jobs/{id}` mientras el trabajo no termina.
* Hay un *endpoint* tipado por tipo de trabajo. Sus parámetros son el cuerpo de la petición
  síncrona, y su resultado, lo que esta respondería. Un tipo nuevo (el backtest de G3) es un
  *handler* y un *endpoint*.
* Los límites y las reglas del dominio se comprueban **al enviar**, no en el *worker*. La
  simulación en segundo plano admite hasta 200 000 trayectorias (`max_job_paths`), frente a las
  20 000 de la síncrona; el límite de memoria del dominio sigue mandando.
* El error de un trabajo usa el vocabulario de Problem Details de la API: `data-not-found`,
  `invalid-request`, `job-interrupted`…
* Cancelar algo terminado o borrar algo sin terminar responde `409 job-state`.

### Auditoría

* Entradas `job.submitted`, `job.succeeded`, `job.failed`, `job.cancelled` y `job.removed`.
* El registro guarda el SHA-256 del resultado, no el resultado: prueba más tarde que el
  resultado guardado es el que produjo el trabajo.

### El esquema de Procrastinate

* La migración 0002 crea el esquema desde una **copia** de su SQL de la 3.11.0
  (`migrations/sql/`), para que una migración publicada no cambie al actualizar el paquete.
* Una versión con cambios de esquema necesita una migración nueva que ejecute sus ficheros. Un
  test (`pending_schema_migrations`) falla hasta que exista.

### Consecuencias

* Buenas:
  * los trabajos largos funcionan sin ningún servicio nuevo;
  * el estado de cada trabajo tiene propietario, auditoría y reglas en la base de datos;
  * la cola y el trabajo nunca se desincronizan;
  * G3 y G4 solo añaden tipos de trabajo.
* Malas:
  * PostgreSQL carga también con la cola: suficiente a esta escala, a revisar con muchos
    *workers*;
  * el orderflow en vivo de G11 probablemente necesite Redis para la difusión (ya previsto en el
    plan);
  * hay que arrancar el *worker* aparte. G0b-2 lo añade a `just dev`.
  * Dependemos de la función SQL versionada de encolado de Procrastinate. La mitigan el test del
    esquema y las pruebas de integración con un *worker* real.

### Confirmación

* **Contrato del repositorio de trabajos**, el mismo en memoria y en PostgreSQL (rol sin
  privilegios): envío, validación, ciclo de vida, cancelación, borrado, propietario, paginación
  y auditoría.
* **Integración con un *worker* real de Procrastinate:**
  * la API envía, el *worker* ejecuta y la API lee el resultado, igual al de la petición
    síncrona con la misma semilla;
  * el encolado va en la misma transacción y se deshace con ella;
  * un trabajo de un *worker* muerto vuelve a la cola.
* **Tests del *runner*:**
  * mapeo de errores;
  * cancelación en un hilo y esperando red;
  * parada del *worker*;
  * tipo desconocido y demasiados intentos;
  * resultado que no es JSON.
* **Reglas de `lint-imports`.** Solo `persistence`, `app` y `worker` conocen SQLAlchemy y
  Procrastinate; los trabajos son una capa entre los *routers* y los casos de uso.

## Pros y contras de las opciones

### Taskiq con Redis

* Bueno: rápido y con difusión en vivo, útil para G11.
* Malo: otro servicio que operar. Además, el trabajo y su entrada en la cola viven en sistemas
  distintos, así que la atomicidad exige un *outbox* y un reconciliador.

### Cola propia sobre `jobs`

* Bueno: sin dependencias; la tabla del dueño es la cola.
* Malo: reescribir lo que Procrastinate ya resuelve y prueba: latidos, trabajos atascados,
  tareas periódicas, apagado ordenado y `LISTEN/NOTIFY`.

### Celery o arq

* Bueno: muy conocidos.
* Malo: Redis o RabbitMQ, y el mismo problema de atomicidad que Taskiq. Celery, además, no es
  asíncrono.

## Más información

* **Desviación del plan:** el plan hablaba de `apps/worker` como paquete aparte. El *worker*
  necesita los casos de uso, los *mappers* y la persistencia de la API, así que es un proceso del
  mismo paquete (como `db upgrade`). Una imagen con dos órdenes encaja igual en Compose (F10).
* [ADR-0029](0029-relational-persistence-and-owners.md): propietarios, RLS y auditoría.
* Pendiente en G0b:
  * los trabajos en la web y el *worker* dentro de `just dev` (G0b-2);
  * observabilidad mínima: trazas y latido de frescura de cada fuente (G0b-3).
