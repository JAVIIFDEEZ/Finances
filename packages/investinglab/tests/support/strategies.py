"""Hypothesis strategies producing synthetic, valid domain inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from hypothesis import strategies as st

from support.factories import make_series

if TYPE_CHECKING:
    from investinglab.domain import PriceSeries

positive_prices = st.lists(
    st.floats(min_value=1e-2, max_value=1e5, allow_nan=False, allow_infinity=False),
    min_size=3,
    max_size=120,
)
"""Lists of strictly positive, finite prices long enough to build a series."""

scale_factors = st.floats(min_value=1e-3, max_value=1e3, allow_nan=False, allow_infinity=False)


@st.composite
def price_series(draw: st.DrawFn) -> PriceSeries:
    """A synthetic daily price series with arbitrary positive prices."""
    return make_series(np.asarray(draw(positive_prices)))
