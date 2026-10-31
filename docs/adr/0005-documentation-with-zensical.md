---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Documentación con Zensical y mkdocstrings

## Contexto y problema

Necesitamos una web de documentación con guías, ADRs, diagramas Mermaid y referencia de API
generada desde los docstrings.

## Factores de decisión

* Mantenimiento activo de la herramienta.
* Referencia de API automática desde los docstrings (Google style).
* Soporte de Mermaid.

## Opciones consideradas

* Zensical + mkdocstrings-python
* MkDocs + Material for MkDocs + mkdocstrings
* Sphinx

## Decisión

Opción elegida: **Zensical + mkdocstrings-python**. Material for MkDocs está en modo
mantenimiento (la 9.7.0 fue su última versión con novedades) y su equipo desarrolla Zensical
como sucesor. Zensical admite mkdocstrings (de forma preliminar) y entiende la configuración
de MkDocs, así que volver atrás sería trivial.

### Consecuencias

* Positiva: herramienta mantenida por el mismo equipo de Material, con su misma estética.
* Negativa: el soporte de mkdocstrings es preliminar (por ejemplo, sin backlinks). Si bloquea
  algo, la alternativa es MkDocs + Material con la misma configuración.

### Confirmación

El job `docs` de CI construye la web en cada PR (`just docs-build`).

## Más información

* <https://zensical.org/docs/setup/extensions/mkdocstrings/>
