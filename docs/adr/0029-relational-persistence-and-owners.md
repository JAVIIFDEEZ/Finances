---
status: aceptado
date: 2026-11-12
decision-makers: Javier Fernández
---

# Persistencia relacional con propietario en cada tabla y registro *append-only*

## Contexto y problema

La API era deliberadamente sin estado ([ADR-0027](0027-stateless-analytics-api.md)). Casi
todo lo que queda por traer de CryptoWorld tiene estado: carteras guardadas, registro de
experimentos del Laboratorio, *paper trading*, órdenes y alertas
([plan de integración](../plan/integracion-cryptoworld.md), fase G0). Hace falta decidir
dónde vive ese estado y qué garantías tiene desde la primera tabla, porque añadirlas después
es muy caro.

## Factores de decisión

* El núcleo no puede conocer la base de datos: debe seguir usándose desde un notebook.
* La plataforma es personal hoy, pero el modelo de datos debe valer para varios usuarios.
* Experimentos, ejecución y auditoría necesitan un registro que nadie pueda reescribir.
* Dos pestañas, o la web y un notebook, no deben pisarse los cambios en silencio.
* Quien solo quiere analizar no debería tener que instalar una base de datos.

## Opciones consideradas

* Base de datos: PostgreSQL, o SQLite en local y PostgreSQL en producción.
* Aislamiento entre usuarios: filtro en cada consulta, o además seguridad a nivel de fila.
* Registro inmutable: solo permisos, solo *triggers*, o ambos con *hash* encadenado.
* Concurrencia: versión en el cuerpo de la petición, o `ETag` e `If-Match`.

## Decisión

* **PostgreSQL 16, SQLAlchemy 2 asíncrono y Alembic**, con psycopg 3 como único *driver*
  (aplicación, migraciones y, más adelante, la cola de trabajos). Sin SQLite: la seguridad
  a nivel de fila, los bloqueos de fila y los *triggers* no tienen equivalente fiable, y
  dos dialectos acaban divergiendo.
* **Repositorios como puertos.** `investinglab.ports` define `PortfolioRepository` y
  `AuditLog`; `investinglab_api.persistence` los implementa. Un contrato de `import-linter`
  impide que routers, casos de uso, esquemas o el núcleo importen SQLAlchemy.
* **Todo tiene propietario, y lo comprueban dos mecanismos independientes:**
  * Cada método de un repositorio recibe el propietario y filtra por él. Un registro ajeno
    «no existe»: la respuesta es 404, nunca 403.
  * La base de datos aplica **seguridad a nivel de fila forzada**. Cada transacción declara
    su propietario (`set_config('investinglab.owner_id', …, true)`) y solo ve y escribe sus
    filas, aunque una consulta olvide el filtro. Sin propietario declarado no se ve ninguna.
  * Un test exige que toda tabla tenga `owner_id` o esté declarada como global, y otro que
    toda tabla con propietario tenga la política activa en la base de datos real.
* **Registro *append-only* con *hash* encadenado** (`audit_log`), genérico por *streams*:
  * *Triggers* rechazan `UPDATE`, `DELETE` y `TRUNCATE` para cualquier rol, también el
    dueño de la tabla; el rol de la aplicación solo tiene `SELECT` e `INSERT`.
  * Cada entrada lleva el *hash* de la anterior de su *stream*. `verify_chain` localiza una
    entrada cambiada, borrada o reordenada.
  * Se guarda el JSON canónico que se firmó, así la verificación no depende de cómo
    reserialice un valor la base de datos.
  * Los escritores de un mismo *stream* se serializan con un bloqueo consultivo: la cadena
    no se bifurca.
  * Cada cambio de una cartera y su entrada de auditoría se confirman en la misma
    transacción.
* **Dos roles.** Las migraciones crean el rol de grupo `investinglab_app` y le conceden lo
  justo. Los tests de base de datos se conectan con un rol que no es superusuario ni dueño
  de las tablas, como debe hacerlo la aplicación en producción.
* **Concurrencia optimista con HTTP estándar.** Cada registro tiene una versión, que viaja
  como `ETag`. Cambiar o borrar exige `If-Match`: `412` si el registro cambió, `428` si falta
  la cabecera.
* **La base de datos es opcional.** Sin `INVESTINGLAB_API_DATABASE_URL`, la API funciona
  como antes y solo los endpoints que guardan datos responden `persistence-not-configured`.
  `/health/ready` informa del estado (`not_configured`, `ok`, `migrations_pending`,
  `unavailable`) sin dejar de responder 200.
* **Migraciones a propósito**, no al arrancar la API: `investinglab-api db upgrade`
  (`just db-upgrade`). `just dev` las aplica antes de arrancar si hay base de datos.
* **Propietario local hasta que haya autenticación.** Mientras no llegue F7, el propietario
  es `INVESTINGLAB_API_LOCAL_OWNER` y la API debe escuchar solo en esta máquina (avisa en
  el arranque si no es así).

### Consecuencias

* Positiva: las fases con estado (Laboratorio, libro de operaciones, *paper*, alertas)
  heredan propietario, auditoría y versiones sin rediseñar nada.
* Positiva: el mismo contrato de tests corre contra el repositorio en memoria y contra
  PostgreSQL, así que los casos de uso se prueban sin base de datos.
* Negativa: los tests de base de datos necesitan PostgreSQL. En local se saltan si no hay;
  en la CI su ausencia es un error.
* Negativa: la cadena de *hashes* detecta manipulaciones, no las impide. Quien controle la
  base de datos puede reconstruirla desde la entrada alterada o cortar su final; guardar
  fuera la cabeza de cada *stream* lo detectaría, y queda para cuando haya dinero real (G7).
* Negativa: los trabajos en segundo plano que recorran datos de varios propietarios (G0b)
  tendrán que declarar el propietario en cada transacción o usar un rol propio.

### Confirmación

* `apps/api/tests/test_repository_contract.py`: el mismo contrato para memoria y PostgreSQL.
* `apps/api/tests/test_persistence.py`: esquema igual a los modelos, seguridad a nivel de
  fila frente a consultas sin filtro, registro inmutable para aplicación y dueño, escritores
  concurrentes, manipulación detectada y estado de la base de datos.
* `apps/api/tests/test_saved_portfolios.py`: versiones, conflictos, propietarios y API sin
  base de datos.
* `packages/investinglab/tests/unit/test_audit_log.py`: propiedades de la cadena.

## Pros y contras de las opciones

### SQLite en local

* Positivo: nada que instalar.
* Negativo: sin seguridad a nivel de fila ni bloqueos de fila; lo probado en local no sería
  lo desplegado.

### Solo el filtro en la aplicación

* Positivo: menos piezas.
* Negativo: una consulta que olvide el filtro expone datos de otro propietario sin que
  ningún test lo note.

### Versión en el cuerpo

* Positivo: más simple para un cliente escrito a mano.
* Negativo: reinventa lo que HTTP ya define y los clientes y *proxies* entienden.

## Más información

* [Guía de persistencia](../guide/persistence.md) y [guía de la API](../guide/api.md).
* [Integración de CryptoWorld](../plan/integracion-cryptoworld.md), secciones 6.4 y G0.
