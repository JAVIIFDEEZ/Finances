---
status: aceptado
date: 2026-10-31
decision-makers: Javier Fernández
---

# Toolchain de calidad de Python

## Contexto y problema

Queremos calidad de repositorio profesional: estilo uniforme, tipado estricto, arquitectura
verificada y tests con cobertura, con los mismos resultados en local, en los hooks y en CI.

## Factores de decisión

* Reproducibilidad: misma versión de cada herramienta en todos los entornos.
* Velocidad del ciclo de feedback.
* Pocas herramientas, bien integradas.

## Opciones consideradas

* uv + ruff + mypy strict + import-linter + pytest/hypothesis + just + pre-commit con hooks locales
* pip/poetry + black/isort/flake8 + pyright + make + pre-commit con repositorios remotos

## Decisión

Opción elegida: la primera.

| Herramienta | Uso |
|-------------|-----|
| **uv** | Gestión de Python, dependencias, workspace y lockfile (`uv.lock`) |
| **ruff** | Lint (reglas amplias, incluidas seguridad, docstrings Google y fechas con zona horaria) y formato |
| **mypy `--strict`** | Tipado estricto con el plugin de Pydantic y `pandas-stubs`; los tests también se tipan |
| **import-linter** | Contratos de arquitectura (ver ADR-0002) |
| **pytest** + **pytest-cov** + **hypothesis** + **respx** | Tests unitarios, de propiedades y de HTTP; cobertura mínima del 90 % |
| **just** | Comandos del proyecto (`just check`, `just test`…), instalado vía `rust-just` en el lockfile |
| **pre-commit** | Hooks **locales** que llaman a `uv run --frozen`: no clonan repositorios remotos y usan las versiones de `uv.lock` |
| **detect-secrets** | Detección de secretos en cada commit, con baseline versionada |
| **conventional-pre-commit** | Valida mensajes Conventional Commits |

### Consecuencias

* Positiva: `uv.lock` es la única fuente de verdad de versiones; local, hooks y CI coinciden.
* Positiva: ruff sustituye a cinco herramientas y es muy rápido.
* Negativa: mypy en modo estricto exige anotar también los tests; se acepta por la seguridad que aporta.

### Confirmación

El workflow `python.yml` ejecuta `just lint`, `just typecheck` y `just test` en Python 3.13 y
3.14, además de todos los hooks de pre-commit.

## Más información

* Python 3.14 para desarrollo (`.python-version`) con `requires-python >= 3.13`.
* mypy frente a pyright: mypy tiene plugin oficial de Pydantic y mejor soporte de los stubs de pandas.
