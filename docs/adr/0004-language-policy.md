---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Política de idioma

## Contexto y problema

El proyecto es personal y en español, pero el código y las herramientas del sector están en
inglés. ¿En qué idioma escribimos cada artefacto?

## Factores de decisión

* Coherencia con el ecosistema (librerías, APIs, nombres financieros estándar).
* Comodidad de lectura de la documentación y la interfaz para el usuario principal.
* Posibilidad de abrir la plataforma a otros usuarios en el futuro.

## Decisión

| Artefacto | Idioma |
|-----------|--------|
| Código, identificadores, docstrings, comentarios | Inglés |
| Mensajes de commit y títulos de PR | Inglés (Conventional Commits) |
| Contrato de la API (rutas, campos, errores) | Inglés |
| README, documentación, ADRs, `CLAUDE.md` | Español (términos técnicos en inglés) |
| Interfaz web | Bilingüe: español por defecto, inglés disponible (i18n) |
| `Portfolio.report()` | Bilingüe: `lang="es"` por defecto, `lang="en"` disponible |

### Consecuencias

* Positiva: el código sigue las convenciones del ecosistema y se entiende fuera de España.
* Positiva: la documentación y la UI son cómodas para el usuario principal.
* Negativa: los textos de usuario requieren catálogos de traducción desde el principio.

### Confirmación

Revisión en PR; los textos de UI e informes viven en catálogos (`messages/{es,en}.json` y
plantillas por idioma), nunca hardcodeados.
