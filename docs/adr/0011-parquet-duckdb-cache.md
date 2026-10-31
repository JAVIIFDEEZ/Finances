---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Caché de datos de mercado en Parquet consultada con DuckDB

## Contexto y problema

Las APIs gratuitas tienen cuotas muy bajas (Alpha Vantage: 25 peticiones al día) y Yahoo
bloquea peticiones masivas. Repetir descargas es lento, frágil y consume cuota. Hace falta una
caché local:

* utilizable desde un notebook sin servidor de base de datos;
* con caducidad (los precios del día cambian);
* inspeccionable;
* que en la nube pueda vivir en almacenamiento de objetos.

## Factores de decisión

* Sin servicios externos: la librería debe funcionar sola.
* Formato columnar y eficiente para series temporales.
* Ficheros autodescriptivos y consultables con SQL.
* Robustez ante ficheros corruptos o de versiones antiguas.

## Opciones consideradas

* **Parquet + DuckDB**
* SQLite
* PostgreSQL / TimescaleDB
* Pickle o CSV

## Decisión

Opción elegida: **Parquet + DuckDB**, implementada en `ParquetSeriesStore` (puerto `SeriesStore`).

* **Organización**: `<cache>/bars/<frecuencia>/<símbolo codificado>.parquet` y
  `<cache>/economic/<serie>.parquet`. La clave no depende del proveedor; la procedencia va en
  los metadatos.
* **Metadatos**: cada fichero guarda en su metadata clave-valor de Parquet:
  * instrumento completo, incluido un mercado desconocido;
  * procedencia;
  * ajuste;
  * **cobertura** (la petición para la que se descargó);
  * fecha de almacenamiento;
  * número de filas, inicio y fin;
  * versión de esquema.
* **Lectura** con DuckDB (`read_parquet`) en sesión UTC. `catalog()` lista la caché leyendo
  solo esos metadatos con `parquet_kv_metadata`, sin tocar los datos.
* **Validez de una entrada**: que la cobertura contenga la petición (`BarsRequest.covers`) y
  que no haya caducado. TTL por defecto: 15 min en intradía, 12 h en diario, 24 h en semanal
  o inferior y 24 h en macro (`CachePolicy`).
* **Robustez**:
  * escritura atómica (fichero temporal y renombrado);
  * un fichero corrupto, de otra versión de esquema o que no supera la validación del dominio
    se registra en el log y se trata como *cache miss*, nunca como un error para quien llama;
  * un fallo al escribir en la caché nunca hace perder los datos ya descargados.

### Consecuencias

* Positiva: cero infraestructura y consultas SQL ad hoc sobre la caché.
* Positiva: los ficheros son portables y los entiende cualquier herramienta (pandas, Polars,
  Spark).
* Negativa: cada refresco reescribe el fichero completo. La actualización incremental
  (descargar solo el tramo nuevo) queda como mejora: es deuda técnica registrada.
* Pendiente: almacenamiento de objetos (S3/R2) mediante `fsspec` para el despliegue en la
  nube (fase F14).

### Confirmación

Tests en `tests/unit/adapters/test_parquet_store.py`:

* ida y vuelta diaria, intradía (UTC) y macro con *vintages*;
* ficheros corruptos y versiones antiguas;
* escritura atómica;
* catálogo;
* integración con el servicio.
