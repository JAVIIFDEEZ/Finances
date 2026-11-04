---
status: aceptado
date: 2026-11-04
decision-makers: Javier Fernández
---

# Redirecciones dentro del origen y errores sin credenciales

## Contexto y problema

Los proveedores reciben la clave en la *query string* (FRED `api_key`, Alpha Vantage
`apikey`). [ADR-0012](0012-resilient-http-client.md) protege los logs en dos capas, pero la
auditoría del 3 de noviembre de 2026 encontró dos vías de fuga:

* `HttpClient` seguía cualquier redirección. httpx conserva la *query string* al seguirla,
  así que una redirección a otro host, o de HTTPS a HTTP, entregaría la clave a terceros.
* Los errores traducidos encadenaban la excepción de httpx (`raise … from error`), que guarda
  la petición con la URL completa. Además, el texto de una traza (`log.exception`) se genera
  después del procesador que enmascara secretos, así que no se limpiaba.

## Factores de decisión

* Una clave nunca debe salir del proveedor que la emitió.
* Las redirecciones legítimas (barra final, paso a HTTPS) deben seguir funcionando.
* Los errores deben conservar lo útil para depurar: tipo de fallo y ruta, nunca la URL
  completa.

## Opciones consideradas

* Seguir solo las redirecciones dentro del origen, con un *hook* de respuesta de httpx.
* No seguir ninguna redirección.
* Seguirlas todas y confiar en los proveedores.

## Decisión

Opción elegida: **redirecciones dentro del origen**, con una tercera capa de higiene de
secretos.

* Un *hook* de respuesta de httpx revisa cada redirección **antes** de seguirla:
  * se sigue si mantiene esquema, host y puerto, o si pasa de HTTP a HTTPS en el mismo host;
  * cualquier otra se rechaza con `ProviderDataError`, que no se reintenta, y el mensaje solo
    nombra la ruta de origen y el host de destino.
* Como mucho se siguen `MAX_REDIRECTS = 5` saltos; un bucle se traduce a `ProviderDataError`.
* Los *timeouts* y los errores de conexión se traducen sin encadenar la excepción de httpx
  (`from None`). El tipo de la excepción sigue en el mensaje.
* `configure_logging` vuelve a enmascarar credenciales después de `format_exc_info`, cuando
  ya existe el texto de la traza.

### Consecuencias

* Positiva: ninguna redirección puede entregar la clave a otro host ni enviarla sin cifrar.
* Positiva: ni las trazas ni los mensajes de error contienen la URL completa.
* Negativa: si un proveedor se muda de dominio con una redirección permanente, el adaptador
  falla hasta que se actualice su `base_url`. Es preferible a seguirla a ciegas.
* Negativa: la causa original de un *timeout* ya no aparece encadenada en la traza; el tipo
  queda en el mensaje.

### Confirmación

* `tests/unit/adapters/test_http_client.py`:
  * redirecciones en el mismo origen y paso a HTTPS;
  * redirecciones rechazadas: otro host, paso a HTTP y otro puerto;
  * bucles de redirección;
  * errores sin cadena y sin la clave.
* `tests/unit/config/test_logging.py`: la clave no aparece en la traza registrada.

## Pros y contras de las opciones

### No seguir ninguna redirección

* Positivo: lo más simple y seguro.
* Negativo: rompe redirecciones legítimas dentro del propio proveedor.

### Seguirlas todas

* Negativo: delega la seguridad de la clave en la configuración de terceros.

## Más información

* Amplía la higiene de secretos de [ADR-0012](0012-resilient-http-client.md).
* Origen: hallazgo B5 de la auditoría del 3 de noviembre de 2026.
