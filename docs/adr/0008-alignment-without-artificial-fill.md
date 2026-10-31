---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Alineación de calendarios sin relleno artificial

## Contexto y problema

Una cartera con el IBEX 35 y el S&P 500 combina calendarios bursátiles distintos: Madrid
cierra el Lunes de Pascua y Nueva York no; cada mercado tiene sus festivos. Para calcular
retornos de cartera, correlaciones o la evolución del valor hay que poner las series en un eje
temporal común. Lo habitual es rellenar hacia delante (`ffill`) o interpolar, y eso **inventa
datos**:

* Un festivo rellenado produce un retorno del 0 % que nunca ocurrió.
* Esos ceros bajan la volatilidad y la correlación estimadas.
* El movimiento real del día siguiente se mide mal.

Requisito del usuario: *une todos los datos que puedas, pero no rellenes con valores que no son*.

## Factores de decisión

* No fabricar observaciones (regla de datos del proyecto).
* No perder información disponible.
* La valoración de una cartera necesita un precio en cada fecha.

## Opciones consideradas

1. `ffill` del panel de precios y retornos sobre el panel rellenado (práctica habitual)
2. Intersección de fechas (solo los días en que cotizan todos)
3. **Tres tratamientos según el uso** (retornos, precios observados, valoración)

## Decisión

Opción elegida: **3**. Se implementa en `investinglab.domain.panel` (`align`, `AlignedPanel`).

| Uso | Tratamiento |
|-----|-------------|
| **Retornos** | Se calculan en el calendario propio de cada activo y después se unen. Un festivo es **NaN**, no 0 %. El movimiento que cruza el festivo se asigna a la siguiente sesión observada. |
| **Precios observados** | Unión de fechas (por defecto) con NaN donde no hubo cotización, más una máscara `observed`. |
| **Valoración** (evolución del valor) | Último precio **observado**, como hace el valor liquidativo de un fondo. Cada valor lleva su antigüedad en sesiones (`staleness()`) y nunca se presenta como una observación nueva. |

* La intersección queda disponible como opción explícita (`AlignmentMethod.INTERSECTION`) para
  análisis que necesitan sincronía total.
* Prohibidos `bfill` e interpolación en todo el código.
* Las covarianzas entre activos usan observaciones *pairwise-complete*, reparadas para que la
  matriz sea semidefinida positiva (fase F3). Los informes avisarán del sesgo por *trading* no
  sincrónico (Europa y EE. UU. cierran con horas de diferencia) y ofrecerán la correlación
  semanal como alternativa.
* Los datos macro se unen *as-of* por fecha de publicación
  ([ADR-0009](0009-point-in-time-economic-series.md)).

### Consecuencias

* Positiva: ningún estadístico se calcula sobre datos inventados.
* Positiva: la valoración es correcta y su frescura es visible.
* Negativa: los paneles contienen NaN y cada analítica debe tratarlos explícitamente. Es
  intencionado: el NaN significa "no observado".

### Confirmación

`tests/unit/domain/test_panel.py` verifica, con el Lunes de Pascua de 2024:

* que no hay retorno 0 % en el festivo;
* que el movimiento se asigna a la sesión siguiente;
* la antigüedad de la valoración.
