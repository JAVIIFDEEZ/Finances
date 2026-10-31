---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Cliente HTTP común: reintentos, cuotas e higiene de secretos

## Contexto y problema

Cada proveedor con API REST necesita lo mismo:

* *timeouts*;
* reintentos ante fallos transitorios;
* respetar cuotas (FRED 120/min, Alpha Vantage 5/min y 25/día, SEC 10/s…);
* identificarse con un User-Agent;
* no filtrar las claves de API, que muchos proveedores reciben en la URL.

Repetirlo en cada adaptador multiplicaría los errores.

## Factores de decisión

* Asíncrono, para descargar muchas series en paralelo.
* Comportamiento homogéneo y probado una sola vez.
* Ninguna credencial en logs ni en mensajes de error.

## Decisión

**`HttpClient`** (`investinglab.adapters.http`), basado en `httpx.AsyncClient`, `tenacity` y
`aiolimiter`:

* **Reintentos** para fallos transitorios (*timeouts*, errores de conexión, 5xx, 408, 429):
  * *backoff* exponencial con *jitter*;
  * se respeta `Retry-After`, con un tope;
  * número de intentos configurable (`INVESTINGLAB_HTTP_MAX_ATTEMPTS`).
* **Cuotas**: se aplican todas las `RateLimit` declaradas antes de cada llamada.
* **Traducción de errores**:

  | Respuesta | Error |
  |-----------|-------|
  | 401 / 403 | `AuthenticationError` |
  | 404 | `SymbolNotFoundError` |
  | 429 | `RateLimitedError` |
  | 5xx / 408 / red | `ProviderUnavailableError` |
  | Resto de 4xx | `UnsupportedRequestError` |
  | JSON inválido | `ProviderDataError` |

* **Higiene de secretos**, en dos capas:
  1. El cliente registra los parámetros con las credenciales enmascaradas (`redact`).
  2. `configure_logging` añade un procesador que enmascara `api_key=`, `apikey=`, `token=`…
     en **cualquier** línea de log, de cualquier librería. Además sube a WARNING los loggers
     `httpx` y `httpcore`, que imprimen URLs completas en INFO.

  Esta segunda capa nació de un test que detectó que httpx escribía la clave en sus logs.

**Yahoo Finance** no tiene API oficial. Su adaptador (fase F2b) usará `yfinance` en un hilo
(`asyncio.to_thread`) con su propio limitador, en lugar de reimplementar endpoints no
documentados con httpx. Se revisará si aparece una alternativa mejor mantenida.

### Consecuencias

* Positiva: un adaptador nuevo solo implementa la traducción del formato del proveedor al
  dominio.
* Positiva: los reintentos y los errores se prueban una sola vez (`respx`).
* Negativa: los limitadores viven en memoria por proceso. Con varias réplicas de la API, las
  cuotas habrá que coordinarlas con un almacén compartido (fase F13).

### Confirmación

Tests en `tests/unit/adapters/test_http_client.py`:

* reintentos y su límite;
* `Retry-After`;
* traducción de cada código de estado;
* cuotas;
* comprobación de que una clave de prueba **no aparece** en la salida de logs.

También en `tests/unit/config/test_logging.py`.
