---
status: propuesto
date: 2026-11-23
decision-makers: Javier Fernández
---

# Código y dependencias de terceros: licencias permitidas, atribución y librerías externas como oráculo de los tests

## Contexto y problema

La ampliación H1-H6 ([Referencias externas](../plan/referencias-externas.md)) se apoya en tres
proyectos con situaciones de licencia muy distintas:

- FinceptTerminal es AGPL-3.0.
- Machine Learning for Trading y sus librerías `ml4t-*` son MIT.
- awesome-quant es un índice en el que conviven licencias permisivas, copyleft (backtesting.py
  AGPL, FinancePy GPL), *Commons Clause* (vectorbt) y licencias de código disponible solo para uso
  no comercial (rateslib).

Hasta ahora el repositorio no tenía una regla escrita. Copiar un fragmento AGPL obligaría a
distribuir InvestingLab entero bajo AGPL, también si solo se sirve por red, y G12 contempla un
modo SaaS. Además, varias fases nuevas quieren comparar sus cifras con librerías maduras (QuantLib,
empyrical-reloaded, alphalens-reloaded), y hay que decidir si eso las convierte en dependencias.

¿Qué código de terceros se puede copiar, qué dependencias se pueden añadir y cómo se usan las
librerías de referencia sin que entren en el núcleo?

## Factores de decisión

* No contaminar la licencia del proyecto: el núcleo, la API, la web y el futuro `apps/mcp` deben
  poder distribuirse o servirse sin obligaciones copyleft.
* Mantener las reglas de arquitectura: el núcleo calcula con NumPy y pandas propios
  ([ADR-0034](0034-technical-indicators-in-numpy.md)) y la red pasa por `HttpClient`
  ([ADR-0012](0012-resilient-http-client.md), [ADR-0032](0032-crypto-venues-on-the-shared-http-client.md)).
* Comprobar las cifras propias contra implementaciones independientes, como ya se hace con la
  paridad de CryptoWorld.
* Que la regla se pueda verificar en la CI, no solo en revisión.

## Opciones consideradas

1. Sin política: se decide en cada PR.
2. Prohibir cualquier código o dependencia externa nueva.
3. Política por papeles: dependencias de ejecución solo permisivas; código copiado solo permisivo
   y con atribución; librerías de referencia como oráculo de tests en un grupo aparte; copyleft y
   licencias restringidas, solo como fuente de ideas.

## Decisión

Opción elegida: **3**, porque protege la licencia del proyecto sin renunciar a comprobar las
cifras con implementaciones maduras.

* **Dependencias de ejecución** (lo que instalan `investinglab`, sus *extras*, `apps/api`,
  `apps/web` y `apps/mcp`): solo licencias permisivas: MIT, BSD-2/3-Clause, Apache-2.0, ISC,
  PSF, NCSA y Zlib. MPL-2.0 y LGPL solo como dependencia sin modificar, con un ADR propio. GPL,
  AGPL, *Commons Clause*, licencias no comerciales y de código disponible: prohibidas.
* **Código copiado:** solo de proyectos con licencia permisiva. Lleva un comentario con el origen
  (proyecto, versión o *commit*, licencia) y una entrada en `THIRD_PARTY_NOTICES.md` en la raíz,
  que se crea con la primera copia. Se conserva el aviso de copyright que exija la licencia.
* **Copyleft o licencias restringidas** (FinceptTerminal, backtesting.py, FinancePy, vectorbt,
  rateslib…): solo ideas y alcance funcional. Las fórmulas se implementan desde fuentes primarias
  (artículos, notas técnicas de los bancos centrales, manuales de referencia), nunca a partir de su
  código.
* **Oráculos de tests:** las librerías de referencia (QuantLib, empyrical-reloaded, quantstats,
  alphalens-reloaded, skfolio, arch, ruptures, pykalman, MAPIE, edgartools…) van en un grupo de
  dependencias `oracles`. Solo las importan los tests, para comparar cifras. Un contrato de
  `import-linter` prohíbe importarlas desde `src/`.
* **Librerías de datos que hacen su propia red** (edgartools, cot-reports, pmxt…): referencia u
  oráculo de la lectura, nunca adaptador. El adaptador se escribe sobre `HttpClient`.

### Consecuencias

* Positiva: InvestingLab puede servirse o distribuirse sin obligaciones copyleft, también en el
  modo SaaS de G12.
* Positiva: las cifras nuevas (bonos, métricas relativas, IC) se comparan con implementaciones
  independientes y maduras sin que entren en el núcleo.
* Negativa: hay que reescribir lo que en un proyecto AGPL ya está hecho; más trabajo en H1 y H5.
* Negativa: el grupo `oracles` alarga la instalación de desarrollo (QuantLib pesa decenas de MB).

### Confirmación

* La CI comprueba las licencias de las dependencias de ejecución contra la lista permitida, con
  una herramienta que se elige al implementarlo.
* Contrato de `import-linter`: ningún módulo de `src/` importa un paquete del grupo `oracles`.
* Revisión: un PR que copia código añade su entrada a `THIRD_PARTY_NOTICES.md`.
* El ADR pasa a **aceptado** cuando la comprobación de licencias y el contrato de `import-linter`
  estén en la CI, a más tardar con la primera fase que añada un oráculo (H1).

## Pros y contras de las opciones

### Sin política

* Positivo: nada que mantener.
* Negativo: un fragmento AGPL copiado por error, por una persona o por un asistente de código,
  cambia la licencia de todo el proyecto, y nadie lo detecta.

### Prohibir todo lo externo

* Positivo: máxima simplicidad.
* Negativo: sin oráculos, las cifras nuevas solo se comprueban contra sí mismas; y se renuncia a
  código MIT útil, como los cuadernos de ML4T.

### Política por papeles

* Positivo: separa lo que se distribuye de lo que solo sirve para comprobar.
* Negativo: exige una lista de licencias y un contrato de `import-linter` más.

## Más información

* [Referencias externas](../plan/referencias-externas.md), §2: licencias comprobadas en PyPI el
  22-11-2026 y papel de cada librería.
* [Integración de CryptoWorld](../plan/integracion-cryptoworld.md), §11.3: licencias de datos,
  que son otro asunto.
* Revisar este ADR si el proyecto cambia de licencia o si se activa el modo SaaS.
