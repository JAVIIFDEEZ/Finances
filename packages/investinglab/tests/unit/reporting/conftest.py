"""Charts are rendered off-screen and closed after every test."""

from __future__ import annotations

from typing import TYPE_CHECKING

import matplotlib as mpl
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

mpl.use("Agg")


@pytest.fixture(autouse=True)
def _close_figures() -> Iterator[None]:
    import matplotlib.pyplot as plt  # noqa: PLC0415 - after selecting the backend

    yield
    plt.close("all")
