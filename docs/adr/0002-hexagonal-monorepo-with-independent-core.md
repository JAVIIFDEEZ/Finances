---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Monorepo con núcleo hexagonal como paquete independiente

## Contexto y problema

La plataforma tiene tres consumidores del mismo conocimiento financiero: notebooks (el
entregable del taller B1-T1 es una librería), una API REST y un frontend web. Además irá
incorporando nuevas fuentes de datos y nuevos bloques del máster. ¿Cómo organizar el código
para que el núcleo sea reutilizable, testeable sin infraestructura y extensible sin tocarlo?

## Factores de decisión

* El núcleo debe funcionar desde un notebook sin levantar API ni base de datos.
* Añadir un proveedor de datos o un bloque del máster no debe modificar el núcleo.
* Las reglas de dependencia deben **verificarse automáticamente**, no confiarse a la disciplina.
* Un único desarrollador: el coste operativo debe ser bajo.

## Opciones consideradas

* Monorepo con workspace `uv`: `packages/investinglab` (núcleo) + `apps/api` + `apps/web`
* Repositorio único `backend/` + `frontend/` con el núcleo dentro del backend
* Varios repositorios (librería, API, web)

## Decisión

Opción elegida: **monorepo con el núcleo como paquete independiente** y arquitectura hexagonal
(puertos y adaptadores) dentro de él.

* `packages/investinglab` contiene `domain`, `ports`, `services`, `analytics`, `reporting`,
  `adapters` y `modules`. No declara FastAPI ni SQLAlchemy como dependencias, así que el
  dominio **no puede** importarlos.
* `apps/api` (FastAPI) y `apps/web` (Next.js) son entregables desplegables que consumen el
  núcleo. Pueden añadirse `apps/worker` o `apps/cli` sin tocarlo.
* Dentro del núcleo, `import-linter` impone las capas:
  `toolkit → modules → services | adapters → reporting → analytics | ports → domain`.
  El dominio no importa I/O, frameworks ni librerías de gráficos; los casos de uso dependen
  de puertos, nunca de adaptadores concretos.

### Consecuencias

* Positiva: el taller se entrega como librería y la plataforma reutiliza exactamente el mismo código.
* Positiva: las violaciones de arquitectura rompen la CI.
* Positiva: un nuevo proveedor es un nuevo adaptador que implementa un puerto y se registra.
* Negativa: un workspace con varios paquetes requiere algo más de configuración inicial.

### Confirmación

`just lint` ejecuta `lint-imports` con los contratos definidos en `pyproject.toml`
(`[tool.importlinter]`), en local, en pre-commit y en CI.

## Pros y contras de las opciones

### `backend/` + `frontend/`

* Positivo: estructura más habitual y sencilla.
* Negativo: el núcleo queda acoplado a las dependencias del backend; nada impide que el dominio
  importe FastAPI.

### Varios repositorios

* Positivo: aislamiento total.
* Negativo: versionado cruzado y PRs coordinados entre repositorios; excesivo para una persona.
