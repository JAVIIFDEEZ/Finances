"""Visual identity of static charts (matplotlib).

Colours come from a validated data-visualisation palette (light mode, for notebooks and
PDF/HTML reports): one sequential blue ramp for magnitudes and bands, fixed-order
categorical hues for series identity, neutral inks for text and annotations, and a
recessive grid. Text never wears a series colour.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

__all__ = [
    "CATEGORICAL",
    "GRID",
    "SEQUENTIAL_BLUE",
    "SURFACE",
    "TEXT_PRIMARY",
    "TEXT_SECONDARY",
    "style_axes",
    "style_figure",
]

SURFACE: Final = "#fcfcfb"
TEXT_PRIMARY: Final = "#0b0b0b"
TEXT_SECONDARY: Final = "#52514e"
GRID: Final = "#e4e3df"

CATEGORICAL: Final = (
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#6250d6",  # violet
    "#e34948",  # red
)
"""Series colours, always assigned in this order (never cycled past eight)."""

SEQUENTIAL_BLUE: Final = {
    150: "#b7d3f6",
    250: "#86b6ef",
    300: "#6da7ec",
    450: "#2a78d6",
    600: "#184f95",
}
"""Steps of the single-hue sequential ramp (light → dark)."""


def style_figure(figure: Figure) -> None:
    """Apply the surface colour to a figure."""
    figure.patch.set_facecolor(SURFACE)


def style_axes(axes: Axes, *, title: str | None = None) -> None:
    """Recessive axes: surface background, light grid, neutral ink, no top/right spines."""
    axes.set_facecolor(SURFACE)
    axes.grid(color=GRID, linewidth=0.8)
    axes.set_axisbelow(True)
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axes.spines[side].set_color(GRID)
    axes.tick_params(colors=TEXT_SECONDARY, labelsize=9)
    axes.xaxis.label.set_color(TEXT_SECONDARY)
    axes.yaxis.label.set_color(TEXT_SECONDARY)
    if title:
        axes.set_title(title, color=TEXT_PRIMARY, fontsize=11, loc="left")
