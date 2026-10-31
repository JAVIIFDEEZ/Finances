from __future__ import annotations

import re

import investinglab


def test_version_is_pep440_like() -> None:
    assert re.match(r"^\d+\.\d+\.\d+", investinglab.__version__)
