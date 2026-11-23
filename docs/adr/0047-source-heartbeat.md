---
status: aceptado
date: 2026-11-23
decision-makers: Javier Fernández
---

# Latido de las fuentes de datos

## Contexto y problema

G0b incluye una observabilidad mínima. El plan de integración pide dos cosas: trazas en la API y
en el *worker*, y un latido (*heartbeat*) de frescura por fuente de datos. Este ADR decide el
latido; las trazas van aparte.

Una fuente puede dejar de responder por varias causas:

- cambia su API;
- la red la bloquea;
- se agota la cuota;
- caduca la clave.

Hoy eso solo se nota cuando falla una pantalla, y a veces ni así:

- **La caché lo tapa:** una serie guardada sigue mostrándose aunque la fuente esté muerta.
- **El enrutado también:** si una fuente no responde, se pregunta a la siguiente.

Antes de los procesos que corren todo el día (el *paper trading* de G7 y las alertas de G8) hay
que saber, de cada fuente, si responde y lo fresco que es su dato.

## Factores de decisión

* **Preguntar a la propia fuente**, sin caché ni recurso a otra: si no, una fuente muerta queda
  oculta detrás de la siguiente.
* **Barato.** Una petición pequeña por fuente, dentro de cualquier cuota. CoinGecko, la más
  estricta, da 10 000 llamadas al mes a una clave *demo*.
* **No depender de que alguien abra la web.**
* **Nunca inventar datos.** La frescura es el instante de la última observación que la fuente
  devolvió de verdad. Su antigüedad es información, no un veredicto: la bolsa cierra el fin de
  semana y una serie mensual tiene un mes por diseño.
* **Una fuente callada no esconde a las demás.**
* **Historia.** Desde cuándo falla, y cuándo respondió por última vez.
* **Sin base de datos, nada se rompe.**

## Opciones consideradas

1. **Un canario por proveedor**, declarado en sus capacidades. El *worker* lo pregunta
   periódicamente y guarda el estado en una tabla global.
2. **Medida pasiva**, desde el tráfico real (aciertos y fallos del enrutado).
3. **Un monitor externo de disponibilidad** (Uptime Kuma, healthchecks.io…).
4. **Comprobar a demanda** cuando alguien pide el estado a la API.

## Decisión

Opción 1.

### El canario

* `Canary(dataset, symbol)` vive en `ProviderCapabilities.canary`. Es una petición pequeña que
  prueba que el proveedor responde y muestra lo fresco que es su dato.
* Puede pedir barras, una serie económica, *funding* o una foto de mercado.
* `ProviderCapabilities` rechaza un canario que el proveedor no sirve, por dato o por
  identificador.
* Los ficheros propios no tienen canario: no se comprueban.

| Proveedor | Canario |
|---|---|
| `yahoo` | barras diarias de `^GSPC` |
| `ecb` | barras diarias de `EURUSD=X` (el *fixing* del BCE) |
| `binance` | barras diarias de `BTC/USDT` |
| `kraken` | barras diarias de `BTC/USD` |
| `coinbase` | barras diarias de `BTC/USD` |
| `okx` | *funding* de `BTC/USDT:USDT` |
| `deribit` | *funding* de `BTC/USD:BTC` |
| `alternative_me` | el índice Fear & Greed (`FNG`) |
| `coingecko` | la foto del mercado cripto |

### La comprobación

* **Dónde vive.** En el núcleo: `services.check_sources`, que también ofrece
  `Toolkit.check_sources()`.
* **A quién pregunta.** A cada proveedor directamente: sin caché, sin enrutado y sin recurso a
  otro.
* **Cómo.** A todos a la vez, con 30 segundos cada uno (`CHECK_TIMEOUT`).
* **Qué historia pide.** La justa para tener varias observaciones aunque haya fines de semana o
  festivos: 10 días de barras, 120 de una serie económica y 7 de *funding*.
* **La última observación** es el final de la respuesta. El de una barra diaria es su fecha, a
  las 00:00 UTC.
* **Un fallo es un latido que lo dice**, nunca una excepción. Guarda el tipo de error y el
  principio del mensaje (300 caracteres como mucho).

### El *worker*

* **Cuándo.** Una tarea periódica, `investinglab.check_sources`, cada cuarto de hora
  (`*/15 * * * *`) en la cola de mantenimiento, y una vez al arrancar el *worker*.
* **Sin duplicados.** Su `queueing_lock` evita dos comprobaciones en cola. Con varios *workers*,
  Procrastinate encola cada instante periódico una sola vez.
* **Los logs** cuentan la historia sin abrir la web:
  * `source_ok`, en nivel *info*;
  * `source_failing`, en nivel *warning*, con los fallos seguidos.

### Lo que se guarda

* **`source_heartbeats` es una tabla global** (`GLOBAL_TABLES`): el estado de una fuente es el
  mismo para todos los dueños y no contiene nada de ninguno.
* **Una fila por fuente.** El `INSERT … ON CONFLICT` lleva la historia en la propia base de
  datos:
  * una respuesta pone los fallos a cero y mueve `last_ok_at`;
  * un fallo suma uno.
* **Las reglas también son `CHECK`:**
  * hay error exactamente cuando falló;
  * un fallo no tiene última observación;
  * una respuesta implica cero fallos y `last_ok_at = checked_at`. Esta usa
    `IS NOT DISTINCT FROM`, porque una comparación con `NULL` no es falsa sino desconocida, y un
    `CHECK` desconocido pasa.
* **Permisos.** La aplicación puede leer, insertar y actualizar, pero no borrar: una fuente no
  se olvida.
* **No va al registro de auditoría.** Es estado operativo que se sobrescribe, no un hecho que
  haya que conservar. La historia completa queda en los logs.

### API y web

* **`GET /api/v1/sources`** da el estado de cada fuente: última comprobación, latencia, última
  observación, error, última respuesta y fallos seguidos. Sin base de datos responde
  `503 persistence-not-configured`.
* **`GET /api/v1/providers`** añade el `canary` de cada proveedor.
* **`/health/ready`** añade `workers`: los *workers* con latido en los últimos 30 segundos.
  Vale `null` sin base de datos o sin migrar.
* **Visión general, «Fuentes de datos».** Cada fuente aparece en uno de estos estados:
  * responde, con su latencia y la antigüedad de su último dato;
  * falla, con cuántas veces seguidas y desde cuándo;
  * sin comprobar: la última comprobación tiene más de 45 minutos (tres ciclos), luego el
    *worker* no está comprobando;
  * pendiente de la primera comprobación;
  * ficheros propios.
* **«Trabajos».** Con `workers = 0`, el aviso de que no hay *worker* sale al momento, sin
  esperar.

### Consecuencias

* Buenas:
  * se sabe cuándo una fuente deja de responder o de moverse, antes de que falle una pantalla y
    antes de los procesos 24/7;
  * añadir una fuente es también declarar su canario (está en la lista de comprobación);
  * es una petición por fuente cada 15 minutos: 2 880 al mes para CoinGecko, dentro de las
    10 000 de su cuota *demo*.
* Malas:
  * hay llamadas aunque nadie use la aplicación;
  * la antigüedad no es un veredicto: la pantalla la muestra, pero no juzga si es demasiada para
    esa fuente;
  * un canario cuyo instrumento deja de cotizar se verá como fallo, hasta cambiarlo;
  * todavía no avisa a nadie: las alertas de G8 leerán esta tabla.

### Confirmación

* **Dominio:** validación de latidos y estados, y su historia (`first`, `after`).
* **Puerto:** un canario no admite otro tipo de dato, ni lo que su proveedor no sirve.
* **Servicio**, con proveedores falsos:
  * cada tipo de dato;
  * fallo, tiempo agotado y texto de error largo;
  * un canario imposible de responder;
  * todas a la vez: una cita que solo se cumple si las comprobaciones son simultáneas.
* **Toolkit:** cada fuente remota por defecto tiene canario, y se pregunta sin pasar por la
  caché.
* **Contrato del almacén**, el mismo en memoria y en PostgreSQL con el rol sin privilegios.
* **Persistencia:**
  * la base de datos rechaza ocho latidos contradictorios;
  * la aplicación no puede borrar;
  * el recuento de *workers* vivos.
* **Worker:** la tarea periódica, su encolado al arrancar y sus logs.
* **API:** `/api/v1/sources`, `workers` en la disponibilidad y `canary` en los proveedores.
* **Web:** Vitest para el estado de cada fuente y para el aviso de *worker*; Playwright con y
  sin base de datos.
* **Comprobación real** (23-11-2026): las nueve fuentes respondieron, en entre 0,4 y 1,1 s.

## Pros y contras de las opciones

### Medida pasiva

* Bueno: ninguna llamada extra.
* Malo: sin tráfico no hay información, y la caché y el enrutado ocultan justo lo que se busca.

### Monitor externo

* Bueno: herramientas maduras, con alertas.
* Malo:
  * es otro servicio que operar;
  * comprueba una URL, no el adaptador (análisis de la respuesta, símbolos, divisas);
  * no sabe nada de la frescura del dato.

### Comprobar a demanda

* Bueno: sin tareas periódicas.
* Malo:
  * una petición de hasta 30 segundos;
  * cada persona que mira multiplica las llamadas;
  * sin historia si no se guarda.

## Más información

* [ADR-0046](0046-background-jobs-on-postgresql.md): el *worker* y sus tareas periódicas.
* [ADR-0029](0029-relational-persistence-and-owners.md): tablas globales frente a tablas con
  propietario.
* **Pendiente en G0b:** las trazas con OpenTelemetry en la API y el *worker*.
