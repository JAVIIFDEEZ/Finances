---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Registrar las decisiones de arquitectura con MADR

## Contexto y problema

InvestingLab crecerá durante años, módulo a módulo, a medida que avanza el máster. Sin un
registro, el motivo de cada decisión (por qué no se rellenan huecos, por qué la API no sirve
gráficos…) se pierde, y cada sesión de trabajo, humana o asistida por IA, vuelve a discutir lo
ya decidido o, peor, lo contradice sin saberlo.

## Factores de decisión

* Trazabilidad del porqué de cada decisión, no solo del qué.
* Formato ligero, versionado junto al código y revisable en los PR.
* Que lo entiendan tanto personas como asistentes de IA (`CLAUDE.md` remite aquí).

## Opciones consideradas

* MADR 4 en `docs/adr/`
* Formato de Nygard (más escueto)
* Wiki externa o documentos sueltos

## Decisión

Opción elegida: **MADR 4 en `docs/adr/`**, porque su estructura (factores, opciones, pros y
contras, confirmación) obliga a justificar y a decir cómo se verifica la decisión, y vive en el
repositorio, publicado en la web de documentación.

### Consecuencias

* Positiva: cada decisión es revisable en el PR que la implementa.
* Positiva: el historial explica la arquitectura a cualquier lector futuro.
* Negativa: añade algo de trabajo por decisión; se compensa limitándolo a decisiones relevantes.

### Confirmación

La checklist de la plantilla de PR exige añadir o actualizar el ADR cuando hay una decisión de
arquitectura.
