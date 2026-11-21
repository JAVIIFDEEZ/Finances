---
status: aceptado
date: 2026-11-21
decision-makers: Javier Fernández
---

# Profundidad del libro de órdenes por bandas alrededor del precio, con historia

## Contexto y problema

G1 pide la «foto del libro» que CryptoWorld archiva cada 15 minutos: cuánto hay para comprar y
para vender cerca del precio. Sirve para saber cuánto movería el precio una orden de un tamaño
dado, y para ver si el libro se vacía antes de un movimiento. Las APIs de los *exchanges* solo dan
el libro tal como está ahora, nivel a nivel. Para tener historia habría que guardarlo con un
proceso 24/7, que todavía no existe (llega con G0b y G8).

Binance publica desde 2023 un volcado diario `bookDepth` por contrato de futuros, con su
`.CHECKSUM`. Cada 30 segundos trae la cantidad acumulada dentro de ±0,2 %, ±1 %… ±5 % del precio
(negativo para las compras, positivo para las ventas) y su valor. Encaja con lo que ya hay:
volcados verificados ([ADR-0041](0041-binance-funding-from-public-dumps.md)) y caché por versión
([ADR-0043](0043-verified-published-files-cache.md)).

## Factores de decisión

* Historia desde hoy, sin esperar a un proceso que guarde fotos.
* Comparable entre *venues*: un vocabulario que cada uno rellena con lo que publica, como el
  posicionamiento ([ADR-0042](0042-positioning-as-a-dataset.md)).
* Nunca inventar: una banda que no se publica no existe, y un libro incoherente se rechaza.

## Opciones consideradas

1. Guardar el libro nivel a nivel de la API en directo.
2. Un conjunto de datos propio (`Dataset.BOOK_DEPTH`): profundidad acumulada por **bandas**
   alrededor del precio, por lado y medida, con la historia de los volcados de Binance.
3. Meter la profundidad como campos del posicionamiento.

## Decisión

Opción 2.

* **`BookDepthSeries`** (`domain/book_depth.py`):
  * columnas `(medida, lado, banda)`;
  * medida: `quantity`, en el activo base, o `notional`, en `notional_currency`;
  * lado: `bid` o `ask`;
  * banda: la distancia al precio en %.
* **Validación.**
  * La profundidad es **acumulada**: un lado nunca tiene menos en una banda más ancha. Si se
    salta una banda, se compara con la más estrecha que haya.
  * Se validan **todas** las fotos crudas, no solo las que se quedan: una foto incoherente
    indica una fuente dañada.
  * Cantidades finitas y no negativas; `NaN` si falta una foto.
* **Periodos.** Cada fila es la última foto del periodo, entera, etiquetada por su inicio. Nunca
  se toma el último valor de cada columna por separado, porque mezclar instantes podría romper
  la acumulación. Se leen de 5 minutos a un día; el periodo en curso se descarta.
* **Medidas derivadas.**
  * `imbalance(banda)` = (compras − ventas) / (compras + ventas), de −1 a +1, `NaN` si la banda
    está vacía;
  * `liquidity(banda)`: el valor de los dos lados en la divisa del nocional.
* **Binance** (`binance/book_depth.py`):
  * Lineales (USDⓈ-M): cantidad en el activo base y valor en la divisa de cotización.
  * Inversos (COIN-M), que no traen ±0,2 %: su `notional` es la cantidad en el activo base. Su
    `depth` son contratos, y no se calcula un valor en dólares que exigiría el tamaño de cada
    contrato, igual que en el posicionamiento.
  * Exige fecha de inicio y lee como mucho **92 días** por petición: un día pesa unos 560 kB
    comprimido.
* **Precio de referencia.** La documentación de Binance no dice desde qué precio mide las
  distancias. Los ficheros son coherentes con el precio medio: el precio medio de cada banda
  (valor ÷ cantidad) cae dentro de ella en las 34.560 filas de un día comprobado. Se documenta así,
  sin afirmar más.
* **Contrato.** `tests/contract/test_book_depth_providers.py`: un *venue* nuevo es un caso más.
  Un libro en directo (OKX, la API de Binance) podría entrar como otro *venue*, con solo las
  bandas que cubran los niveles leídos.

### Consecuencias

* Buenas: tres años de profundidad del libro sin proceso propio, verificada y guardada en disco.
  Un *venue* nuevo es un adaptador y un caso del contrato.
* Malas: un día pesa ~560 kB, así que las casetes de prueba son grandes (750 kB el lineal y 370 kB
  el inverso, en base64). Por eso se graba un solo día de cada tipo. Las bandas de Binance llegan
  a ±5 %: más lejos no hay datos.
* La cobertura de las bandas anchas depende de cuántos niveles observa Binance, así que una banda
  lejana podría quedarse corta en momentos extremos. No se corrige; se dice.

### Confirmación

* Tests del dominio:
  * acumulación, también con una banda que falta;
  * fotos enteras al cambiar de frecuencia;
  * desequilibrio sin división por cero;
  * validación de cada regla.
* Dos propiedades de Hypothesis: una frecuencia gruesa solo contiene fotos enteras que se
  tomaron, y el desequilibrio queda en [−1, 1].
* El contrato con Binance.
* Tests del adaptador contra sus casetes y con copias alteradas: columnas, filas ilegibles, banda
  sin distancia, foto repetida, foto no acumulada.
* Lectura con red real de los dos tipos de contrato.

## Pros y contras de las opciones

### El libro nivel a nivel en directo

* Bueno: el detalle completo de cada nivel.
* Malo: sin historia hasta que exista un proceso que lo guarde (G8), y los 400 niveles de una API
  apenas cubren unas décimas de punto en BTC.

### Campos del posicionamiento

* Bueno: no hay tipo nuevo.
* Malo: mezcla instantáneas de cosas distintas, con lados y bandas que no son un campo escalar, y
  rompe la regla de acumulación.

## Más información

* [ADR-0042](0042-positioning-as-a-dataset.md): el patrón de conjunto de datos ampliable por *venue*.
* [ADR-0043](0043-verified-published-files-cache.md): la caché de los volcados.
* Pendiente: la API y la pantalla (siguiente PR), un libro en directo como segundo *venue* y la
  profundidad en el pilar de derivados de la ficha.
