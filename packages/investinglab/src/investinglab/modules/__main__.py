"""Write every module's traceability matrix: ``python -m investinglab.modules docs/modules``."""

from __future__ import annotations

import sys
from pathlib import Path

from investinglab.modules import REGISTRY
from investinglab.modules.registry import render_traceability


def main(argv: list[str] | None = None) -> int:
    """Render ``<slug>.md`` for every registered module into the given folder."""
    arguments = sys.argv[1:] if argv is None else argv
    target = Path(arguments[0] if arguments else "docs/modules")
    for module in REGISTRY:
        render_traceability(module).save(target / f"{module.slug}.md")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
