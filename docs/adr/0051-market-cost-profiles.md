---
status: aceptado
date: 2026-11-24
decision-makers: Javier Fernández
---

# Perfiles de costes por mercado, con sus fuentes, sus fechas y lo que suponen

## Contexto y problema

El motor de backtest ([ADR-0049](0049-backtest-engine.md)) sabe cobrar:

- una comisión con su mínimo;
- un deslizamiento;
- un impuesto sobre las compras;
- el préstamo de un corto;
- el *funding* de un perpetuo.

Pero alguien tiene que decirle cuánto. Hasta ahora, quien llamaba al motor escribía las cifras
a mano, y el plan exige otra cosa: un backtest de una acción española y de BTC «con costes
reales».

Hay tres dificultades:

- **Los impuestos cambian con el tiempo.** La TTF francesa pasó del 0,2 % al 0,3 % en 2017 y al
  0,4 % el 1 de abril de 2025. El ITF español no existía antes del 16 de enero de 2021. Un
  backtest de 2015 a 2026 con el tipo de hoy cobra de más los años sin impuesto.
- **Siguen al emisor, no a la bolsa.** Una empresa neerlandesa que cotiza en Madrid no paga ITF.
  Una pequeña, por debajo del umbral, tampoco.
- **La comisión depende del *bróker*,** que InvestingLab no conoce.

## Factores de decisión

* **Nada optimista por construcción.** Sin datos, el supuesto debe ser prudente y decir que lo es.
* **Point-in-time** también en los costes que tienen fecha: los impuestos.
* **Nunca inventar datos.** Un *funding* que no se ha publicado no es un *funding* cero.
* **Fuentes citables.** Cada cifra publicada, con su enlace y la fecha en que se leyó.
* **Que tus cifras manden.** Tu comisión sustituye a la supuesta.

## Opciones consideradas

1. **Perfiles en el dominio** (`domain/costs.py`): uno por bolsa (su MIC) y uno por producto de
   cada plataforma cripto, con impuestos fechados, fuentes y supuestos marcados.
2. **Un fichero de configuración** (TOML) con las cifras, que el usuario edita.
3. **Sin perfiles:** que cada backtest dé sus costes.

## Decisión

Opción 1. Las cifras son datos de referencia con fuente y fecha; viven junto al código que las
usa, se prueban y se revisan en un PR. Un fichero editable las separaría de sus tests y de sus
fuentes.

### Qué hay

* **`TransactionTax`:** un impuesto sobre las compras, por el país del emisor, con sus tipos en
  el tiempo (`TaxRate(since, bps)`), lo que grava y sus fuentes:

  | Impuesto | País | Tipos | Fuentes |
  | --- | --- | --- | --- |
  | ITF | ES | 0,2 % desde el 16-01-2021 | Ley 5/2020 (BOE) y la lista anual de la AEAT |
  | TTF | FR | 0,2 % desde el 01-08-2012; 0,3 % desde 2017; 0,4 % desde el 01-04-2025 | BOFiP BOI-ANNX-000467 |
  | IFTT | IT | 0,1 % en mercado regulado desde 2014; 0,2 % desde 2026 | Cleary Gottlieb (2013) y LuxCSD (2026) |
  | SDRT | GB | 0,5 % desde el 27-10-1986 | HMRC y LSE (exenciones: AIM, nuevas cotizaciones) |

* **`CostProfile`:** comisión, deslizamiento, mínimo, impuesto, producto, si admite cortos,
  préstamo, fuentes, fecha de lectura, **qué cifras son supuestos** (`assumed`) y **qué costes
  deja fuera** (`unmodelled`):
  * **Bolsas** (los 17 MIC del registro): comisión **supuesta** del 0,10 %, deslizamiento
    **supuesto** del 0,05 % y préstamo de un corto **supuesto** del 0,50 % anual.
  * **Plataformas cripto,** con su comisión *taker* publicada (las órdenes del backtest son de
    mercado a la apertura siguiente):

    | Perfil | Comisión | Fuente |
    | --- | --- | --- |
    | `binance-spot` | 0,10 % | tabla de Binance, nivel regular |
    | `binance-usdm` | 0,05 % | FAQ de futuros de Binance |
    | `kraken-spot` | 0,80 % | nivel 1, desde el 09-07-2026 |
    | `coinbase-spot` | 0,50 % | nivel de entrada en la UE, desde el 16-09-2026 |

    El deslizamiento de las plataformas es el **supuesto** del 0,05 %.
* **`market_costs(series, profile, taxable=…, commission_bps=…)`:** los costes de una serie
  bajo un perfil, el de donde cotiza por defecto. Da:
  * el impuesto vela a vela, con el tipo en vigor en la fecha de la sesión;
  * el préstamo vela a vela, por días naturales hasta la vela siguiente;
  * si el impuesto se ha **presumido**.
* **`funding_per_bar(rates, series)`:** el *funding* publicado, repartido por velas.
* **`Toolkit.backtest(symbol, strategy, start=…, profile=…)`:**
  * descarga la serie con un año de historia previa, para que los indicadores lleguen calientes
    al inicio;
  * elige el perfil y, si es un perpetuo, descarga su *funding* de la plataforma del perfil;
  * opera desde `start`.

### Quién paga un impuesto

* Con ISIN, decide su país: los dos primeros caracteres.
* Sin ISIN (Yahoo no lo da), una acción de la bolsa del impuesto se **presume** sujeta. Así se
  cobra de más a las pequeñas por debajo del umbral, el lado prudente. `taxable=False` lo
  corrige, y el resultado dice que fue una presunción.
* Los ETF y los fondos quedan fuera.

Los umbrales de capitalización (1.000 M€ en España y Francia, 500 M€ en Italia) no se
comprueban: sus listas anuales son PDF oficiales, todavía sin adaptador.

### *Funding* por vela

* Una posición abierta al cierre de una vela paga cada liquidación de esa vela, también la de
  su último instante: una vela diaria de cripto paga las de las 08:00, las 16:00 y las 00:00 del
  día siguiente.
* Una vela que el *funding* publicado no cubre (antes de la primera liquidación o después de la
  última) es `NaN`, desconocida.
* El backtest rechaza un *funding*, un préstamo o un impuesto desconocidos en cualquier vela que
  opera: no los toma como cero.
* `Toolkit.backtest` acaba en la última vela con *funding* liquidado, la de ayer si la de hoy no
  ha terminado.
* El perpetuo se opera con los precios del par al contado (Binance no sirve velas de sus
  perpetuos al contenedor). La base queda fuera y el perfil lo dice.

### Lo que no se modela, y por qué

* El impuesto belga (TOB) depende de la residencia del inversor.
* El *stamp duty* de Hong Kong grava las dos partes, y el motor solo grava compras.
* El timbre suizo depende del intermediario.
* La tasa de la SEC sobre las ventas es de 0,2 puntos básicos.
* El IFTT italiano de marzo a diciembre de 2013: sus primeros tipos no se han podido contrastar
  con una fuente.

### Consecuencias

* Buenas:
  * un backtest de SAN.MC paga el ITF desde 2021 y no antes;
  * uno de una francesa paga el 0,3 % o el 0,4 % según el día de cada compra;
  * uno de BTC en perpetuo paga el *funding* que hubo;
  * cada cifra tiene fuente y fecha, y lo que es supuesto lo dice;
  * tus cifras sustituyen a las supuestas.
* Malas:
  * **Las comisiones son las de hoy** (`as_of`) para todo el histórico: su historia no se
    registra. Kraken y Coinbase las subieron en 2026, así que un backtest de años anteriores paga
    de más, el lado prudente.
  * **Los perfiles envejecen.** Una plataforma cambia sus tarifas sin avisar. `as_of` lo hace
    visible, pero hay que revisarlas.
  * **La presunción sin ISIN** cobra de más a las empresas pequeñas.
