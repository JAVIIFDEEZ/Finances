"""The modules' traceability must point at code and tests that really exist."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from investinglab.domain import DomainError
from investinglab.modules import REGISTRY, ModuleInfo, RequirementStatus
from investinglab.modules.__main__ import main
from investinglab.modules.b1_toolkit import MODULE
from investinglab.modules.registry import ModuleRegistry, render_traceability

TESTS = Path(__file__).resolve().parents[1]
REPOSITORY = TESTS.parents[2]
REFERENCES = [
    (module.slug, requirement.id, reference)
    for module in REGISTRY
    for requirement in module.requirements
    for reference in requirement.code
]
TEST_FILES = [
    (module.slug, requirement.id, test)
    for module in REGISTRY
    for requirement in module.requirements
    for test in requirement.tests
]


def _resolve(dotted: str) -> object:
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            target: object = importlib.import_module(".".join(parts[:cut]))
        except ModuleNotFoundError:
            continue
        for attribute in parts[cut:]:
            target = getattr(target, attribute)
        return target
    raise ModuleNotFoundError(dotted)


@pytest.mark.parametrize(("slug", "requirement", "reference"), REFERENCES)
def test_every_code_reference_exists(slug: str, requirement: str, reference: str) -> None:
    if "/" in reference or reference.endswith((".md", ".ipynb")):
        assert (REPOSITORY / reference).exists(), f"{slug} {requirement}: {reference}"
    else:
        assert _resolve(reference) is not None


@pytest.mark.parametrize(("slug", "requirement", "test"), TEST_FILES)
def test_every_test_reference_exists(slug: str, requirement: str, test: str) -> None:
    assert (TESTS / test).is_file(), f"{slug} {requirement}: {test}"


def test_b1_toolkit_is_registered() -> None:
    assert REGISTRY.get("b1-toolkit") is MODULE
    assert [r.id for r in MODULE.requirements] == ["4.1", "4.2", "4.3", "4.4", "4.5", "4.6"]
    assert MODULE.title("en") == "Portfolio analysis toolkit"
    assert MODULE.summary("es").startswith("Librería")
    assert MODULE.complete  # Yahoo and the ECB completed the multi-source ingestion (4.2)
    assert MODULE.requirements[1].status is RequirementStatus.DONE


def test_the_published_matrix_is_up_to_date() -> None:
    published = (REPOSITORY / "docs" / "modules" / "b1-toolkit.md").read_text(encoding="utf-8")

    assert published == render_traceability(MODULE), "run `uv run just traceability`"


def test_english_matrix() -> None:
    matrix = render_traceability(MODULE, "en")

    assert matrix.startswith("# Portfolio analysis toolkit · B1 · Taller 1")
    assert "| Done |" in matrix
    assert "| Partial |" not in matrix
    assert "Yahoo Finance and the ECB without a key" in matrix


def test_registry_rules() -> None:
    registry = ModuleRegistry()
    module = ModuleInfo("x", "B0", "X", "X", "", "")

    assert registry.register(module) is module
    assert registry.register(module) is module  # idempotent
    with pytest.raises(DomainError, match="already registered"):
        registry.register(ModuleInfo("x", "B0", "Y", "Y", "", ""))
    assert list(registry) == [module]
    assert len(registry) == 1
    assert module.complete


def test_cli_writes_every_matrix(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 0
    assert (tmp_path / "b1-toolkit.md").read_text(encoding="utf-8") == render_traceability(MODULE)
