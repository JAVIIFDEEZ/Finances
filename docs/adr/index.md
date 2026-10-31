# Registro de decisiones de arquitectura (ADR)

Cada decisión de arquitectura relevante se documenta como un ADR en formato
[MADR 4](https://adr.github.io/madr/). Los ADR son **inmutables una vez aceptados**: si una
decisión cambia, se crea un ADR nuevo que la sustituye (`Superseded by ADR-XXXX`) y se
actualiza el estado del antiguo.

| ADR | Título | Estado |
|-----|--------|--------|
| [0001](0001-record-architecture-decisions.md) | Registrar las decisiones de arquitectura con MADR | Aceptado |
| [0002](0002-hexagonal-monorepo-with-independent-core.md) | Monorepo con núcleo hexagonal como paquete independiente | Aceptado |
| [0003](0003-python-quality-toolchain.md) | Toolchain de calidad de Python | Aceptado |
| [0004](0004-language-policy.md) | Política de idioma | Aceptado |
| [0005](0005-documentation-with-zensical.md) | Documentación con Zensical y mkdocstrings | Aceptado |

## Cómo añadir un ADR

1. Copia [`template.md`](template.md) como `NNNN-titulo-en-kebab-case.md` con el siguiente número.
2. Rellénalo en español; los nombres técnicos se mantienen en inglés.
3. Añádelo a esta tabla y a la navegación de `zensical.toml`.
4. Inclúyelo en el mismo PR que implementa la decisión.
