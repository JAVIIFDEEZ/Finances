---
status: aceptado
date: 2026-11-21
decision-makers: Javier Fernández
---

# Caché en disco de los ficheros publicados con su *checksum*, por versión y verificada al leer

## Contexto y problema

El *funding* de Binance sale de un fichero por mes y su posicionamiento de un fichero por día
([ADR-0041](0041-binance-funding-from-public-dumps.md),
[ADR-0042](0042-positioning-as-a-dataset.md)), cada uno con su `.CHECKSUM`. Leer 90 días de
posicionamiento son 180 descargas (el fichero y su *checksum*), y la siguiente vez son las
mismas 180: un día publicado no cambia. La caché Parquet guarda series ya validadas, pero no
sirve aquí: la serie que se pide cambia de rango y de frecuencia, mientras que lo que de verdad
se repite es cada fichero.

Guardar en disco lo que publica un tercero tiene sus riesgos. El fichero puede corromperse en
disco. Binance podría volver a publicar un fichero corregido. Y las claves vienen de un listado
remoto: una clave maliciosa no debe escribir fuera de la carpeta de la caché.

## Factores de decisión

* No se relaja la integridad: todo fichero se comprueba con su SHA-256 publicado antes de leerlo,
  venga de la red o del disco.
* Una republicación se nota sin llamadas extra.
* La caché es una optimización: nunca hace fallar una petición.
* Nada se escribe fuera de su carpeta, y borrarla siempre es seguro.

## Opciones consideradas

1. Guardar en Parquet la serie de posicionamiento ya leída y fusionar rangos, como las velas.
2. Guardar cada fichero tal como se publicó, con su *checksum* y la versión que da el listado
   (el `ETag` de S3), y verificarlo de nuevo al leerlo.
3. Guardar el CSV ya descomprimido, sin versión.

## Decisión

Opción 2: `adapters/storage/published.py` (`PublishedFileCache`), usada por
`binance/dumps.py`.

* **Qué se guarda.** El ZIP y su `.CHECKSUM` exactamente como se publicaron, junto con
  `<clave>.entry.json`, que guarda la versión y el formato. La entrada se escribe la última y
  cada fichero se escribe en uno temporal que luego se renombra encima, así que nunca se sirve
  un fichero a medio escribir.
* **Versión.** El listado del *bucket* trae el `ETag` de cada fichero. Una entrada solo sirve la
  versión con la que se guardó; si el listado da otra, se descarga de nuevo. Si el listado no da
  versión, no se guarda nada. El listado se sigue pidiendo siempre (una llamada): es lo que dice
  qué ficheros existen.
* **Verificación al leer.** La copia del disco pasa por la misma comprobación que una descarga.
  Si no cuadra, se descarta, se registra un aviso y se descarga otra vez.
* **Claves seguras.** Solo se aceptan rutas relativas simples (letras, cifras, `._-` y `/`, sin
  `..`, sin barra inicial y de 512 caracteres como mucho); cualquier otra es `UnsafeKeyError`.
* **Dónde.** `<cache_dir>/dumps/binance/` (`INVESTINGLAB_DATA_DIR/cache` por defecto). El
  Toolkit la activa con `cache=True` (como la caché Parquet); con `cache=False` no se guarda
  nada.
* **Disco.** La lectura y la escritura van a un hilo (`asyncio.to_thread`), fuera del bucle de
  eventos. Un error de disco al leer cuenta como fallo de caché, y uno al escribir se registra.

### Consecuencias

* Buenas: lo ya leído cuesta una llamada (el listado). Los ficheros guardados siguen siendo
  verificables contra el SHA-256 de Binance, porque son los mismos bytes. Sirve para cualquier
  fuente que publique ficheros con *checksum* y un listado con versiones.
* Malas: el disco crece con lo consultado (un mes de funding ocupa alrededor de 1 kB comprimido y
  un día de métricas unos 12 kB: cinco años diarios de un contrato rondan 21 MB). No se purga
  sola; se borra la carpeta y listo.
* Sin red, las fuentes remotas no se registran (`INVESTINGLAB_OFFLINE`), así que estos ficheros no
  se leen sin conexión: el listado hace falta para saber qué existe.

### Confirmación

* Tests de la caché: versiones, entradas ilegibles o descartadas, un disco que no se puede
  escribir y claves que intentan salir de la carpeta.
* Tests de Binance contra sus casetes:
  * la segunda lectura no descarga ningún fichero;
  * un mes republicado (otro `ETag`) se descarga otra vez;
  * una copia dañada en disco no se lee;
  * sin versión en el listado no se guarda nada;
  * los días de posicionamiento se descargan una sola vez.
* Test del Toolkit: los ficheros acaban en `<cache_dir>/dumps/binance` solo con `cache=True`.

## Pros y contras de las opciones

### La serie en Parquet

* Bueno: reutiliza la caché que ya hay.
* Malo: la serie depende de la frecuencia y del rango pedidos, se pierde la verificación contra
  el SHA-256 publicado y una republicación no se notaría.

### El CSV sin versión

* Bueno: no hay que descomprimir al leer.
* Malo: ya no se puede verificar contra el *checksum* publicado, y un fichero republicado se
  quedaría viejo para siempre.

## Más información

* [ADR-0041](0041-binance-funding-from-public-dumps.md) y
  [ADR-0042](0042-positioning-as-a-dataset.md): los volcados que se guardan.
* Pendiente: otras fuentes de ficheros con *checksum* cuando lleguen (la caché no es exclusiva de
  Binance).
