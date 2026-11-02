"""A small, typed Markdown builder and the report text type.

Reports are assembled from blocks (headings, paragraphs, tables, lists, notes) instead of
templates, so every value is formatted and type-checked in Python. The result is a
:class:`MarkdownReport`: an ordinary ``str`` that Jupyter renders as formatted Markdown.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = ["Align", "MarkdownBuilder", "MarkdownReport", "escape_cell"]


class MarkdownReport(str):
    """Markdown text of a report.

    It is a plain ``str`` (print it, write it, compare it), rendered as formatted Markdown
    when it is the result of a notebook cell.
    """

    __slots__ = ()

    def _repr_markdown_(self) -> str:
        return str(self)

    def save(self, path: str | Path, *, encoding: str = "utf-8") -> Path:
        """Write the report to ``path`` (parent directories are created)."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(self), encoding=encoding)
        return target


class Align(StrEnum):
    """Column alignment in a table."""

    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"


_RULES = {Align.LEFT: ":---", Align.RIGHT: "---:", Align.CENTER: ":---:"}
# Only ordinary whitespace is collapsed: non-breaking spaces (``12,3 %``) must survive.
_WHITESPACE = re.compile(r"[ \t\r\n\f\v]+")


def _one_line(text: object) -> str:
    return _WHITESPACE.sub(" ", str(text)).strip()


def escape_cell(text: object) -> str:
    """Make any value safe inside a table cell (pipes escaped, one line)."""
    return _one_line(text).replace("|", r"\|")


class MarkdownBuilder:
    """Accumulates Markdown blocks separated by blank lines."""

    __slots__ = ("_blocks",)

    def __init__(self) -> None:
        self._blocks: list[str] = []

    def heading(self, text: str, level: int = 2) -> Self:
        """A heading of ``level`` 1 to 6.

        Raises:
            ValueError: If the level is out of range.
        """
        if not 1 <= level <= 6:  # noqa: PLR2004
            raise ValueError(f"Heading level must be 1-6, got {level}")
        self._blocks.append(f"{'#' * level} {_one_line(text)}")
        return self

    def paragraph(self, text: str) -> Self:
        """A paragraph."""
        self._blocks.append(text.strip())
        return self

    def bullets(self, items: Iterable[str]) -> Self:
        """An unordered list (skipped when empty)."""
        lines = [f"- {_one_line(item)}" for item in items]
        if lines:
            self._blocks.append("\n".join(lines))
        return self

    def note(self, text: str) -> Self:
        """A block quote, used for notes and caveats."""
        self._blocks.append("\n".join(f"> {line}" for line in text.strip().splitlines()))
        return self

    def table(
        self,
        headers: Sequence[str],
        rows: Iterable[Sequence[object]],
        *,
        align: Sequence[Align] | None = None,
    ) -> Self:
        """A pipe table.

        Args:
            headers: Column titles.
            rows: Cell values (converted with ``str`` and escaped).
            align: One alignment per column (left by default).

        Raises:
            ValueError: If a row or ``align`` does not have one entry per column.
        """
        width = len(headers)
        alignment = list(align) if align is not None else [Align.LEFT] * width
        if len(alignment) != width:
            raise ValueError(f"align has {len(alignment)} entries for {width} columns")
        lines = [
            "| " + " | ".join(escape_cell(h) for h in headers) + " |",
            "| " + " | ".join(_RULES[a] for a in alignment) + " |",
        ]
        for row in rows:
            if len(row) != width:
                raise ValueError(f"row has {len(row)} cells for {width} columns: {row!r}")
            lines.append("| " + " | ".join(escape_cell(cell) for cell in row) + " |")
        self._blocks.append("\n".join(lines))
        return self

    def build(self) -> MarkdownReport:
        """The document, ending with a newline."""
        return MarkdownReport("\n\n".join(self._blocks) + "\n")
