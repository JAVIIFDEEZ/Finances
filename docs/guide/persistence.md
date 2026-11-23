# Persistencia

Casi toda la plataforma funciona sin base de datos: mercados, análisis de carteras, Monte
Carlo, optimización y planes. La base de datos hace falta para lo que se **guarda**: las
carteras ([ADR-0029](../adr/0029-relational-persistence-and-owners.md)) y los trabajos en
segundo plano, con su cola ([ADR-0046](../adr/0046-background-jobs-on-postgresql.md)).

## Ponerla en marcha

Necesitas PostgreSQL 16. Con Docker:

```bash
uv run just db-up          # arranca PostgreSQL (compose.yaml) y espera a que responda
```

Sin Docker, instala PostgreSQL (en Windows, `winget install PostgreSQL.PostgreSQL.16`) y crea
una base de datos y un usuario.

Después, indica la URL en tu `.env` (está ignorado por git) y crea el esquema:

```bash
# .env: usuario, contraseña, máquina, puerto y base de datos de tu PostgreSQL
INVESTINGLAB_API_DATABASE_URL=postgresql+psycopg://…
```

```bash
uv run just db-upgrade     # crea o actualiza las tablas
uv run just dev            # también aplica las migraciones pendientes y arranca el worker
```

Si la base de datos no responde, `db upgrade` (y con él `just dev`) se rinde a los
10 segundos con un mensaje que dice dónde la buscó, sin mostrar la contraseña.

El ejemplo completo de la URL para la base de datos de `just db-up` está en `.env.example`.
En la web, la pantalla **Cartera** muestra entonces «Carteras guardadas».

## Qué se guarda y con qué garantías

| Tabla | Contenido | Garantías |
|-------|-----------|-----------|
| `portfolios` | Definición de cada cartera guardada (activos, pesos, divisa, rebalanceo, fechas), con su versión | Cada fila tiene propietario; la base de datos solo deja ver y escribir las propias |
| `jobs` | Cada trabajo en segundo plano: tipo, estado, parámetros, progreso, resultado o error | Propietario como `portfolios`; las reglas de su ciclo de vida son restricciones (resultado solo si terminó bien, error solo si falló) |
| `procrastinate_*` | La cola de la que los *workers* toman los trabajos (Procrastinate): solo el id del trabajo y su dueño | Global; se escribe en la misma transacción que la fila de `jobs` |
| `source_heartbeats` | La última comprobación de cada fuente de datos: si respondió, en cuánto, su último dato, el error, cuándo respondió por última vez y cuántas veces seguidas ha fallado | Global (es igual para todos); sus reglas son restricciones y la aplicación no puede borrar filas |
| `audit_log` | Una entrada por cada cartera creada, cambiada o borrada, y por cada trabajo enviado, terminado o borrado (con el SHA-256 de su resultado) | Solo se puede añadir: ni la aplicación ni el dueño de la tabla pueden cambiarla o borrarla; cada entrada encadena el *hash* de la anterior |

* **Propietario.** Mientras no haya acceso con usuario (fase F7), todo pertenece a
  `INVESTINGLAB_API_LOCAL_OWNER` (por defecto, `local`). No expongas la API fuera de tu
  máquina.
* **Versiones.** Cada cartera guardada tiene una versión. Si la cambias en dos sitios a la
  vez, el segundo guardado se rechaza en lugar de pisar al primero.
* **Auditoría.** `AuditLog.verify("portfolios")` recorre la cadena y dice en qué entrada se
  rompe, si alguien la hubiera alterado por debajo.

## Trabajos en segundo plano

Lo que no cabe en una petición (hoy, un Monte Carlo grande; en G3, los backtests) se envía a
la API como trabajo y lo ejecuta un *worker*: otro proceso con el mismo código, que espera en
la cola de PostgreSQL ([guía de la API](api.md#trabajos-en-segundo-plano)).

```bash
uv run just dev            # con base de datos, arranca el worker junto a la API y la web
uv run just worker         # o solo el worker; Ctrl+C para pararlo
```

En la web, la pantalla **Trabajos** los lista con su progreso y muestra el resultado de cada
uno; en **Simulación**, «En segundo plano» envía una de hasta 200 000 trayectorias.

* **Varios a la vez.** Ejecuta `INVESTINGLAB_API_WORKER_CONCURRENCY` trabajos a la vez (2 por
  defecto). Para más, arranca más *workers*.
* **Progreso y cancelación.** Cada segundo escribe el progreso y mira si pediste cancelar.
* **Si un *worker* se pierde** (se cierra el portátil, se mata el proceso), deja de enviar su
  latido. En un minuto su trabajo vuelve a la cola y otro lo retoma desde el principio. Tras tres
  intentos perdidos, el trabajo termina como `job-interrupted`.
* **Al pararlo con Ctrl+C**, los trabajos en marcha tienen 30 segundos para acabar. Los que no
  acaban quedan como `job-interrupted`.
* **Sin *worker*** los trabajos esperan en la cola (`queued`) hasta que arranque uno. La
  disponibilidad de la API (`/health/ready`) dice cuántos hay en marcha (`workers`), y la
  pantalla de un trabajo en cola avisa en cuanto no queda ninguno.
* **Las fuentes de datos.** Al arrancar, y después cada cuarto de hora, el *worker* hace a cada
  fuente su pregunta de prueba (su canario) y guarda cómo respondió en `source_heartbeats`
  ([ADR-0047](../adr/0047-source-heartbeat.md)). La **Visión general** lo muestra junto a
  cada fuente, y los logs del *worker* dicen `source_failing` cuando una falla.

## Migraciones

| Comando | Qué hace |
|---------|----------|
| `uv run just db-upgrade` | Lleva la base de datos al esquema de esta versión |
| `uv run investinglab-api db current` | Dice en qué revisión está |
| `uv run just db-revision "qué cambia"` | Borrador de migración a partir de los modelos |

Las tablas, tipos y funciones de la cola (`procrastinate_*`) los crea la migración 0002 desde
una copia del SQL de Procrastinate 3.11.0. Las comparaciones de esquema y los borradores de
Alembic no las tocan. Si una versión nueva de Procrastinate cambia su esquema, un test falla
hasta que una migración aplique sus ficheros de `sql/migrations` (ver
`persistence/queue.py`).

Una migración nueva se revisa siempre a mano: Alembic no ve la seguridad a nivel de fila,
los *triggers* ni los permisos. Toda tabla con datos de usuario lleva
`ddl.owner_isolation("tabla")` y `ddl.grant_to_app(…)`; un test falla si falta.

## Producción: dos roles

Las migraciones crean el rol de grupo `investinglab_app` con los permisos justos. Lo correcto
es que la aplicación se conecte con un usuario que pertenezca a ese grupo y que no sea
superusuario ni dueño de las tablas (un superusuario se salta la seguridad a nivel de fila):

```sql
CREATE ROLE investinglab_api LOGIN PASSWORD '…' IN ROLE investinglab_app;
```

Las migraciones se ejecutan con el usuario dueño de la base de datos; la API, con el otro.

## Tests

Los tests de base de datos crean y borran su propia base de datos en el servidor que indique
`INVESTINGLAB_TEST_DATABASE_URL` (un usuario que pueda crear bases de datos y roles). Sin esa
variable se saltan; en la CI, que falte es un error.

```bash
# .env no se usa aquí: es una variable del terminal donde lanzas los tests
uv run just test
```

Los tests de extremo a extremo de la web usan `INVESTINGLAB_E2E_DATABASE_URL` del mismo modo.

## Problemas frecuentes

* **`just db-up` no consigue descargar la imagen** (`failed to copy: httpReadSeeker`, `EOF`,
  `TLS handshake timeout`, `connection reset`): la conexión con los servidores de descarga
  de Docker Hub se cortó. Es la red, no el proyecto. `db-up` reintenta (Docker conserva las
  capas terminadas, así que cada intento descarga menos) y, si Docker Hub sigue fallando,
  descarga la misma imagen de sus copias: `mirror.gcr.io` (Google) y
  `public.ecr.aws/docker/library` (Amazon). Las tres publican la imagen oficial con el
  mismo *digest*, byte a byte; `db-up` le pone su nombre de siempre (`postgres:16`) para
  que Compose la use. Si fallan las tres:
    * vuelve a lanzarlo más tarde o desde otra red (las redes de la universidad o de la
      oficina, las VPN y los antivirus que inspeccionan HTTPS suelen cortar descargas;
      un punto de acceso del móvil sirve de prueba rápida);
    * reinicia Docker Desktop (icono de la ballena → *Restart*);
    * en Docker Desktop → *Settings* → *General*, desactiva *Use containerd for pulling and
      storing images*: el almacén de imágenes clásico reintenta cada capa por su cuenta;
    * detrás de un proxy, configúralo en Docker Desktop → *Settings* → *Resources* →
      *Proxies*;
    * o prescinde de Docker: instala PostgreSQL 16 (`winget install
      PostgreSQL.PostgreSQL.16`) y apunta `INVESTINGLAB_API_DATABASE_URL` a él.

  Todo funciona sin base de datos salvo las carteras guardadas.
* **`just db-up` dice que Docker no está en marcha**: abre Docker Desktop, espera a que
  indique que está funcionando y repite.
* **`just db-up` dice `port is already allocated`** (puerto 5432): otro PostgreSQL ocupa el
  puerto, por ejemplo el de **CryptoWorld**, que publica `5432:5432`. Para o ese contenedor
  (`docker stop cryptoworld_db`) o usa otro puerto: `INVESTINGLAB_POSTGRES_PORT=5433` en `.env`
  y el mismo puerto en `INVESTINGLAB_API_DATABASE_URL` (`…@127.0.0.1:5433/investinglab`).
* **«Para guardar carteras hace falta una base de datos»**: la API arrancó sin
  `INVESTINGLAB_API_DATABASE_URL`. Añádela a `.env` y reinicia.
* **`/health/ready` dice `migrations_pending`**: ejecuta `uv run just db-upgrade`.
* **`/health/ready` dice `unavailable`**: PostgreSQL no responde en esa URL (¿está arrancado?,
  ¿el puerto es el correcto?).
