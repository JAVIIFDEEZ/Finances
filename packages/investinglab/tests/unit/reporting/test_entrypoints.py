"""The domain loads reporting (and matplotlib) only when a report or chart is requested."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parents[2]


def _run(code: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(TESTS), os.environ.get("PYTHONPATH", "")]),
    }
    return subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=120,
    )


def test_importing_the_domain_loads_neither_reporting_nor_matplotlib() -> None:
    result = _run(
        """
        import sys
        import investinglab.domain
        prefixes = ("investinglab.reporting", "matplotlib")
        loaded = sorted(m for m in sys.modules if m.startswith(prefixes))
        print(loaded)
        assert not loaded, loaded
        """
    )

    assert result.returncode == 0, result.stderr


BLOCK_MATPLOTLIB = """
    import sys
    from importlib.abc import MetaPathFinder

    class Blocker(MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name == "matplotlib" or name.startswith("matplotlib."):
                raise ModuleNotFoundError(f"No module named {name!r}")
            return None

    sys.meta_path.insert(0, Blocker())
    from support.factories import gbm_prices, make_series
    series = make_series(gbm_prices(60))
"""


def test_markdown_reports_work_without_matplotlib() -> None:
    result = _run(
        BLOCK_MATPLOTLIB
        + """
    report = series.report(language="en")
    assert report.startswith("# TEST.MC")
    assert "matplotlib" not in sys.modules
    """
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("call", ["series.plots_report()", "series.monte_carlo().plot()"])
def test_charts_without_matplotlib_explain_the_extra(call: str) -> None:
    result = _run(
        BLOCK_MATPLOTLIB
        + f"""
    try:
        {call}
    except ImportError as error:
        assert "investinglab[plots]" in str(error), error
    else:
        raise AssertionError("charts should need matplotlib")
    """
    )

    assert result.returncode == 0, result.stderr
