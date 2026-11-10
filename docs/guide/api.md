# API REST

La API expone el núcleo por HTTP para la web y para cualquier cliente. Es una capa fina: valida
la petición, llama al núcleo y devuelve JSON ([ADR-0027](../adr/0027-stateless-analytics-api.md)).

```bash
uv run just api                      # http://127.0.0.1:8000/docs (Swagger) y /redoc
curl "http://127.0.0.1:8000/api/v1/market/bars?symbol=SAN.MC&start=2024-01-01"
```

## Endpoints

| Método | Ruta | Qué devuelve |
|--------|------|--------------|
| GET | `/health/live`, `/health/ready` | Estado, versión y proveedores registrados |
| GET | `/api/v1/providers` | Capacidades de cada proveedor (frecuencias, cuotas, historia) |
| GET | `/api/v1/modules`, `/api/v1/modules/{slug}` | Módulos del máster y su trazabilidad (`language=es\|en`) |
| GET | `/api/v1/market/bars` | Barras de un instrumento con metadatos, procedencia y estadísticos |
| POST | `/api/v1/market/compare` | Rendimiento base 100, caídas, métricas y correlación de varios |
| GET | `/api/v1/market/quality` | Diagnóstico de calidad frente al calendario oficial |
| GET | `/api/v1/rates/risk-free` | Tipo libre de riesgo conocido cada día hábil |
| POST | `/api/v1/portfolios/validate` | Validación de pesos sin descargar nada |
| POST | `/api/v1/portfolios/analytics` | Historia, métricas, caídas, correlación y contribución al riesgo |
| POST | `/api/v1/portfolios/report` | Informe Markdown (`language=es\|en`) |
| POST | `/api/v1/simulations` | Monte Carlo: abanico, histograma final, VaR/CVaR con intervalos |
| POST | `/api/v1/optimizations` | Pesos óptimos y frontera eficiente |
| POST | `/api/v1/plans` | Plan de ahorro: probabilidad de éxito y aportación necesaria |

Una cartera se describe en el cuerpo:

```json
{
  "name": "Núcleo",
  "holdings": [
    {"symbol": "SAN.MC", "weight": 0.4},
    {"symbol": "ITX.MC", "weight": 0.3},
    {"symbol": "IBE.MC", "weight": 0.3}
  ],
  "base_currency": "EUR",
  "rebalance": {"kind": "periodic", "frequency": "1mo"},
  "start": "2019-01-01"
}
```

## Convenciones

* **Fechas ISO 8601.** Las barras diarias y superiores llevan la fecha de sesión
  (`2024-03-01`); las intradía, el instante UTC de apertura (`2024-03-04T08:00:00Z`).
* **`null` antes que inventar.** Una cifra indefinida (una columna que el proveedor no da, un
  ratio sin datos suficientes) es `null`, nunca 0.
* **Decimales.** Rentabilidades, volatilidades y tipos van en tanto por uno (`0.05` = 5 %).
* **`X-Request-ID`.** Cada respuesta lo lleva. Envía el tuyo para correlacionar con los logs.
* **Límites** (`INVESTINGLAB_API_*`): 25 instrumentos, 20 000 trayectorias y 2 520 periodos
  de horizonte por petición, por defecto.
* **Contrato.** `apps/api/openapi.json` es el documento OpenAPI versionado. Si cambias la API,
  regenera el fichero con `uv run just openapi`; un test lo exige.

## Errores

Todos los errores siguen [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457)
(`application/problem+json`):

```json
{
  "type": ".../docs/guide/api.md#data-not-found",
  "title": "Data not found",
  "status": 404,
  "detail": "Data unavailable for 'NOPE.XX': every provider failed: ...",
  "instance": "urn:request:3f1c...",
  "attempts": [{"provider": "yahoo", "error": "SymbolNotFoundError", "message": "..."}]
}
```

### invalid-request

`422`. La petición no cumple el esquema (`errors` indica dónde), supera un límite o rompe una
regla del dominio: pesos que no suman 1, fechas invertidas, cartera con divisas mezcladas
sin `base_currency`, restricciones de optimización imposibles…

### not-found

`404`. La ruta o el recurso (por ejemplo, un módulo) no existen.

### data-not-found

`404`. Ningún proveedor tiene el instrumento o la serie pedidos. `attempts` lista cada
proveedor consultado y su respuesta.

### data-unavailable

`503`. Los proveedores capaces de servir los datos fallaron (red, cuota, respuesta
malformada). Si el fallo es transitorio, la respuesta lleva `Retry-After`.

### timeout

`504`. La petición tardó demasiado.

### http-error

Otros errores HTTP, como `405` cuando el método no existe (la cabecera `Allow` indica cuáles
sí).

### internal-error

`500`. Fallo inesperado del servidor. La respuesta no incluye detalles internos; cita su
`instance` al reportarlo.
