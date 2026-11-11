"""Remove caches and build artefacts (``just clean``), the same on every operating system."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTEFACTS = (
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".hypothesis",
    ".coverage",
    "coverage.xml",
    "htmlcov",
    "site",
    "dist",
    "apps/web/.next",
    "apps/web/playwright-report",
    "apps/web/test-results",
)
#: Folders never walked into: dependencies and history are not ours to clean (and are big).
SKIPPED = frozenset({".git", ".venv", "node_modules"})


def caches(root: Path) -> list[Path]:
    """Every ``__pycache__`` folder under ``root``, outside the skipped folders."""
    found: list[Path] = []
    for directory, subdirectories, _ in root.walk():
        if directory.name == "__pycache__":
            found.append(directory)
            subdirectories.clear()
        else:
            subdirectories[:] = [name for name in subdirectories if name not in SKIPPED]
    return found


def main() -> int:
    """Remove the build artefacts and the Python caches of the repository."""
    removed = 0
    for path in [ROOT / name for name in ARTEFACTS] + caches(ROOT):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        else:
            continue
        removed += 1
    print(f"Removed {removed} caches and build artefacts.")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
