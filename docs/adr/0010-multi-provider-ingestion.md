---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Ingesta multifuente: puertos, registro, routing con *fallback* y lotes con fallos parciales

## Contexto y problema

El taller B1-T1 (§4.2) exige:

* descargar series de varias APIs y devolver siempre objetos idénticos, sea cual sea la fuente;
* descargar N series a la vez a partir de una lista.

La plataforma añadirá decenas de proveedores (Yahoo, Alpha Vantage, FRED, BCE, Tiingo,
Alpaca, ccxt…) con capacidades, cuotas y fiabilidades distintas. Yahoo, en concreto, no tiene
SLA y limita peticiones con frecuencia. ¿Cómo se integran sin tocar el núcleo, y qué pasa
cuando una fuente falla?

## Factores de decisión

* Añadir un proveedor no debe modificar servicios ni dominio.
* Una fuente caída no debe dejar al usuario sin datos si otra puede servirlos.
* En un lote, el fallo de un activo no debe abortar el resto, y el motivo debe quedar claro.
* Respetar las cuotas de cada proveedor.

## Decisión

**Puertos** (`investinglab.ports`):

* `MarketDataProvider.fetch_bars(BarsRequest) -> PriceSeries` y
  `EconomicDataProvider.fetch_economic_series(EconomicRequest) -> EconomicSeries`.
  Siempre devuelven objetos del dominio validados, nunca *payloads* crudos.
* Cada proveedor declara sus `ProviderCapabilities`:
  * tipos de dato;
  * clases de activo;
  * frecuencias;
  * histórico máximo por frecuencia;
  * si necesita clave;
  * cuotas (`RateLimit`).
* Todos los fallos se traducen a una jerarquía común (`ProviderError` y subclases) que indica
  si un reintento tiene sentido (`retryable`).

**Registro y routing** (`ProviderRegistry`):

* Los proveedores se registran una vez, en el *composition root*.
* `prefer(...)` fija el orden por clase de activo y/o frecuencia. Gana la regla más específica.
* Los demás proveedores capaces quedan detrás como último recurso, en orden de registro.
* Se descartan los que no pueden atender la petición: frecuencia no soportada o histórico
  fuera de su límite.

**Caso de uso** (`MarketDataService`):

1. Caché: si hay una entrada fresca que cubre la petición, se devuelve recortada a las fechas
   pedidas (ADR-0011).
2. Se prueban los candidatos en orden. Cualquier `ProviderError` se registra como
   `FetchAttempt` y se pasa al siguiente. Si un proveedor devuelve otro símbolo u otra
   frecuencia, se rechaza.
3. Si todos fallan, se lanza `DataUnavailableError` con todos los intentos y sus causas.
4. Los lotes (`get_many_bars`, `get_many_economic_series`) se ejecutan concurrentemente con un
   semáforo (`max_concurrency`). Devuelven `BatchResult` con `succeeded` y `failed`
   (`FetchFailure`) y **nunca abortan por un fallo parcial**.

Los reintentos dentro de un mismo proveedor y las cuotas son responsabilidad del adaptador,
a través del cliente HTTP común (ADR-0012). El servicio solo decide entre proveedores.

### Consecuencias

* Positiva: un proveedor nuevo es una clase que cumple un `Protocol` y se registra.
* Positiva: el usuario recibe datos mientras quede una fuente viva, y un diagnóstico preciso
  si no queda ninguna.
* Negativa: distintas fuentes pueden dar series ligeramente distintas para el mismo activo
  (ajustes, horarios). La procedencia queda en `DataSource` y la validación cruzada entre
  fuentes se abordará en la *quality gate*.

### Confirmación

Tests con proveedores falsos (`tests/support/fakes.py`, datos sintéticos) que cubren:

* el orden de preferencia y el filtrado por capacidades;
* el *fallback* entre proveedores;
* los intentos registrados;
* la caché y su TTL;
* los lotes con fallos parciales;
* que la concurrencia se mantiene dentro del límite.
