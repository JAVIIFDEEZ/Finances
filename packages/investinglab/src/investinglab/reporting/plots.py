"""Collection of report charts returned by ``plots_report()``."""

from __future__ import annotations

import base64
import html
import io
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from matplotlib.figure import Figure

__all__ = ["PlotsReport"]


class PlotsReport(Mapping[str, "Figure"]):
    """Named matplotlib figures, in display order.

    Behaves as a read-only mapping (``plots["growth"]``), saves every chart with
    :meth:`save` and shows them all, captioned, when it is the result of a notebook cell.
    Figures are created without pyplot, so they are never displayed twice nor kept alive
    by a global registry.

    Args:
        figures: Figures by name, in display order.
        titles: Caption of each figure (defaults to its name).
    """

    __slots__ = ("_figures", "_titles")

    def __init__(
        self, figures: Mapping[str, Figure], titles: Mapping[str, str] | None = None
    ) -> None:
        self._figures = dict(figures)
        captions = dict(titles or {})
        self._titles = {name: captions.get(name, name) for name in self._figures}

    def __getitem__(self, name: str) -> Figure:
        return self._figures[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._figures)

    def __len__(self) -> int:
        return len(self._figures)

    def __repr__(self) -> str:
        return f"PlotsReport({list(self._figures)})"

    @property
    def titles(self) -> Mapping[str, str]:
        """Caption of each figure."""
        return dict(self._titles)

    def save(self, directory: str | Path, *, fmt: str = "png", dpi: int = 150) -> dict[str, Path]:
        """Write every figure to ``directory/<name>.<fmt>`` and return the paths by name."""
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}
        for name, figure in self._figures.items():
            path = target / f"{name}.{fmt}"
            figure.savefig(path, format=fmt, dpi=dpi, facecolor=figure.get_facecolor())
            paths[name] = path
        return paths

    def _repr_html_(self) -> str:
        blocks = []
        for name, figure in self._figures.items():
            buffer = io.BytesIO()
            figure.savefig(buffer, format="png", dpi=100, facecolor=figure.get_facecolor())
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            caption = html.escape(self._titles[name])
            blocks.append(
                f'<figure style="margin:0 0 1.5em 0"><img src="data:image/png;base64,{encoded}"'
                f' alt="{caption}" style="max-width:100%"/>'
                f"<figcaption>{caption}</figcaption></figure>"
            )
        return "\n".join(blocks)
