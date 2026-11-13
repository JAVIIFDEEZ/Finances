# Casetes: respuestas reales grabadas

Cada fichero `<proveedor>/<nombre>.json` guarda los intercambios HTTP reales que hizo un
adaptador para una petición de la plataforma: la URL y los parámetros exactos, el estado, el
cuerpo de la respuesta, la hora de grabación (`recorded_at`) y el propósito de la casete.

* Se generan con `uv run just record-fixtures` (`scripts/record_fixtures.py`); no se editan a
  mano.
* Son **extractos breves** para probar el análisis de cada formato (fechas de sesión, unidades
  menores, *splits*, barras sin cerrar…), no un conjunto de datos de mercado.
* Los tests las reproducen con `support.cassettes` y `respx`, sin red.
* Las casetes con rango relativo al día de grabación (`*_live`) solo son válidas con el reloj
  fijado en `recorded_at`, que los helpers de test aplican.
* Las casetes `*_paged` se graban con páginas más pequeñas que las del proveedor (`page_size`)
  para probar la paginación con pocos datos; los tests usan el mismo tamaño.

Ver [ADR-0025](../../../../../docs/adr/0025-yahoo-chart-adapter-and-cassettes.md) y
[ADR-0032](../../../../../docs/adr/0032-crypto-venues-on-the-shared-http-client.md).
