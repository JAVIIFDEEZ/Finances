---
status: aceptado
date: 2026-11-17
decision-makers: Javier Fernández
---

# Posicionamiento en derivados como conjunto de datos propio, ampliable por *venue*

## Contexto y problema

G1 pide el *open interest* y los ratios largo/corto de los perpetuos. Cada *venue* los
publica a su manera: Binance cada 5 minutos en volcados diarios, con seis cifras; OKX por API,
cada 5 minutos, hora o día, con otras cinco, el valor en dólares y sus días empezando a las
16:00 UTC; Bybit, Deribit o Hyperliquid, de otra forma. Habrá más fuentes, y el usuario pidió
expresamente que añadirlas sea sencillo.

## Factores de decisión

* Una fuente nueva no debe tocar el enrutador, la caché, la API ni la web.
* Nunca inventar: un campo que una fuente no publica no existe; un hueco no se rellena.
* Comparables entre *venues*: mismas unidades y mismas reglas de periodos.
* Causalidad: el valor de un periodo se conoce cuando el periodo termina.

## Opciones consideradas

1. Meterlo como columnas de `FlowSeries` o como series económicas.
2. Un conjunto de datos propio (`Dataset.POSITIONING`) con su tipo y su puerto, y un
   vocabulario común de campos que cada fuente rellena con lo que tenga.
3. Un tipo por *venue*.

## Decisión

Opción 2.

* **`PositioningSeries`**: instantáneas de un derivado en un *venue*, con los campos de
  `PositioningField` que publique (interés abierto en el activo base, su valor con su divisa,
  ratio de cuentas, de cuentas y de posiciones de los *top traders* y comprador/vendedor del
  agresor). Cantidades y ratios no negativos; un campo ausente no se crea.
* **Periodos**: cada fila se etiqueta con el inicio de su periodo y vale la última instantánea
  dentro de él (la misma convención que usa OKX). Pasar a una frecuencia más gruesa toma la
  última de cada periodo y un periodo vacío no aparece; nunca a una más fina. `finished(now)`
  deja fuera el periodo en curso, como una vela sin cerrar.
* **Puerto y rutas**: `PositioningProvider.fetch_positioning(PositioningRequest)`, con *venue*,
  fechas y frecuencia. El registro elige por capacidades y preferencia (`prefer_positioning`);
  un *venue* nombrado solo va a ese proveedor.
* **Capacidades por conjunto de datos**: `identifiers_by_dataset` y `frequencies_by_dataset`
  permiten que un proveedor sirva velas de pares y posicionamiento de perpetuos a otras
  frecuencias; `positioning_fields` dice qué campos da.
* **Todo o nada**: una fuente que no llega al inicio pedido lo dice, y el enrutador pregunta a
  la siguiente (OKX guarda 5 minutos unos tres días; Binance, desde 2021).
* **Fuentes**: Binance (volcados `metrics`, verificados como en el ADR-0041; inversos con el
  interés en el activo base y sin valor en dólares, porque necesitaría el tamaño de cada
  contrato) y OKX (cuatro estadísticas de su API, leyendo primero el interés abierto: un
  perpetuo inexistente se sabe con una llamada).
* **Descubrimiento**: `tk.venues(símbolo, dataset)` dice qué *venues* sirven el funding o el
  posicionamiento de un símbolo, en el orden en que se preguntan. Las interfaces lo usan en
  lugar de listas fijas.
* **Un contrato por conjunto de datos** (`tests/contract/test_positioning_providers.py`): una
  fuente nueva es un caso más. La guía [Añadir una fuente de datos](../guide/adding-a-source.md)
  recoge el procedimiento.

### Consecuencias

* Buenas: un *venue* nuevo es su adaptador, su registro, sus casetes y un caso del contrato.
  Binance y OKX dan las mismas cifras con los mismos nombres y unidades.
* Malas: los días de OKX no son días UTC; no se mueven para no cambiar lo que mide cada
  periodo, así que comparar diarios entre *venues* exige saberlo (está en su docstring y en la
  guía). El valor en dólares de los inversos de Binance no se da.

### Confirmación

Tests del dominio (validación, periodos, huecos) y una propiedad de Hypothesis (ninguna
frecuencia gruesa contiene un valor que no se publicara); el contrato con los dos *venues*;
tests de cada adaptador contra sus casetes y con copias alteradas; y lectura con red real de
las dos fuentes, con el paso automático a Binance cuando OKX no llega.

## Más información

* [ADR-0031](0031-flow-holding-rates-and-universes.md), tipos hermanos: flujo y tipos de
  mantenimiento. [ADR-0041](0041-binance-funding-from-public-dumps.md), los volcados de Binance.
* Hecho después: la API (`/market/positioning`, `/market/venues`), la tarjeta de Mercados y
  el pilar de derivados de la ficha con el cambio del interés abierto
  ([ADR-0040](0040-asset-card-with-pillars.md)).
* Pendiente: más *venues* cuando respondan.
