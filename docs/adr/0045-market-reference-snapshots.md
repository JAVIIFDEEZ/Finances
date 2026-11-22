---
status: aceptado
date: 2026-11-22
decision-makers: Javier Fernández
---

# Datos de referencia de un mercado como fotos fechadas, no como series

## Contexto y problema

G1 pide CoinGecko para lo que en CryptoWorld hacen `get_assets` y `get_market_overview`: cuánto
vale el mercado cripto, qué parte es bitcoin (la «dominancia») y cuáles son los mayores activos.
No es una serie de un instrumento, como las velas o el funding: es el estado de un mercado
entero en un momento.

CoinGecko lo da sin clave en dos llamadas: `/global` (capitalización total, volumen de 24 horas,
cambio de 24 horas en dólares, cuántos activos sigue y la cuota de los diez mayores) y
`/coins/markets` (la clasificación por capitalización). Las dos son **instantáneas**: CoinGecko
las recalcula cada pocos minutos y no guarda su historia en el plan gratuito. La historia de la
dominancia o del total exige el plan de pago.

## Factores de decisión

* Nunca inventar: una foto de hoy no dice nada de ayer.
* Que lo que no da la fuente no se presente como si lo diera: el cambio de 24 horas en dólares no
  es el cambio en euros.
* Un puerto genérico (cualquier clase de activo, cualquier fuente), como pide el plan
  (`ReferenceDataProvider`).

## Opciones consideradas

1. Tratarlo como una serie económica más (como el Fear & Greed), con una observación por llamada.
2. Un conjunto de datos propio (`Dataset.REFERENCE`) con tipos de foto fechada: el mercado entero
   y la clasificación.
3. Reconstruir la historia de la dominancia con la capitalización histórica de cada activo.

## Decisión

Opción 2.

* **`MarketSnapshot`** (`domain/market_reference.py`): clase de activo, divisa, el instante que
  describe (`as_of`, el `updated_at` de la fuente), la capitalización total, y si los da, el
  volumen y el cambio de 24 horas y el número de activos. La dominancia va como `MarketShare` de
  0 a 1, de mayor a menor; `others` es lo que queda fuera. Las cuotas no pueden sumar más que el
  todo. Lo que la fuente no publica es `None`, nunca cero (`share_of("SOL")` es `None` si no está
  entre las publicadas).
* **`MarketCapRanking`**: los activos por capitalización, cada uno con su id en la fuente, su
  ticker en mayúsculas, precio, capitalización, volumen, oferta en circulación y máxima, y cuándo
  se actualizó. El puesto es la posición en el orden de la fuente. `as_of` es la actualización más
  reciente.
* **Puerto** `ReferenceDataProvider` (`ports/reference.py`) con `fetch_market_snapshot` y
  `fetch_market_caps`. El servicio pide al primer proveedor que cubre esa clase de activo,
  comprueba que la respuesta es de ese mercado, en esa divisa y no más larga de lo pedido, y la
  recuerda 5 minutos. `tk.market_snapshot()` y `tk.market_caps(top)`.
* **CoinGecko** (`adapters/providers/coingecko/`):
  * Cambio de 24 horas: solo en dólares. En otra divisa queda en `None`.
  * Capitalización: CoinGecko pone 0 cuando no la conoce, y aquí queda en `None`.
  * Clasificación: hasta 250 activos por llamada.
  * Divisas: una que CoinGecko no valora se rechaza con su motivo.
* **Cuota.** Sin clave CoinGecko admite entre 5 y 15 llamadas por minuto según su carga, y se
  declara el mínimo. Una clave *demo* gratuita (`INVESTINGLAB_COINGECKO_API_KEY`) la sube a 30. Va
  en una cabecera, nunca en la URL, así que no aparece ni en los logs ni en las casetes. Las claves
  *demo* son de uso personal (plan, §16).

### Consecuencias

* Buenas: el tamaño y la dominancia del mercado cripto y su clasificación, sin clave, con su
  fecha y sin rellenar nada. Otra fuente (o el mercado de otra clase de activo) es un adaptador y un
  caso del contrato.
* Malas: no hay historia de la dominancia. Para estudiarla en el tiempo hay que ir guardando las
  fotos (con la cola de trabajos de G0b y el tiempo real de G8). La clasificación de hoy no es un
  universo *point-in-time*: usarla hacia atrás sería sesgo de supervivencia, que es justo lo que
  evita `Universe` (ADR-0031).

### Confirmación

* Tests del dominio: cuotas, orden, validación, huecos.
* Tests del puerto, del registro y del servicio, con un proveedor falso: caché de 5 minutos,
  respuesta de otra divisa o más larga de lo pedido.
* El contrato de los proveedores de referencia con CoinGecko.
* Tests del adaptador contra casetes reales: en dólares, en euros (sin cambio de 24 horas), una
  divisa que no valora, la clasificación y copias alteradas. La clave va en la cabecera.
* Lectura con red real.

## Pros y contras de las opciones

### Una serie económica

* Bueno: no hay tipo nuevo.
* Malo: una llamada no es una observación de una serie publicada en una fecha. Y una «serie» con
  un solo punto invita a pensar que hay historia.

### Reconstruir la dominancia

* Bueno: daría historia.
* Malo: necesita la capitalización histórica de miles de activos (de pago a partir de 365 días),
  y los que dejaron de existir faltarían: una dominancia inventada.

## Más información

* [ADR-0031](0031-flow-holding-rates-and-universes.md): los universos *point-in-time*.
* Pendiente: la API y la pantalla (siguiente PR), y guardar las fotos en el tiempo cuando exista
  la cola de trabajos.
