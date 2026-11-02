from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from investinglab.reporting.markdown import Align, MarkdownBuilder, MarkdownReport, escape_cell

if TYPE_CHECKING:
    from pathlib import Path


def test_blocks_are_separated_by_blank_lines() -> None:
    report = (
        MarkdownBuilder()
        .heading("Title", 1)
        .paragraph("  Some text.  ")
        .bullets(["one", "two  words"])
        .note("first line\nsecond line")
        .build()
    )

    assert report == (
        "# Title\n\nSome text.\n\n- one\n- two words\n\n> first line\n> second line\n"
    )


def test_tables_align_columns_and_escape_cells() -> None:
    report = (
        MarkdownBuilder()
        .table(
            ["Name", "Value"], [("a|b", 1), ("multi\nline", 2.5)], align=[Align.LEFT, Align.RIGHT]
        )
        .build()
    )

    assert report.splitlines() == [
        "| Name | Value |",
        "| :--- | ---: |",
        "| a\\|b | 1 |",
        "| multi line | 2.5 |",
    ]


def test_center_alignment_and_default_left() -> None:
    lines = MarkdownBuilder().table(["A", "B"], [], align=[Align.CENTER, Align.LEFT]).build()
    default = MarkdownBuilder().table(["A"], []).build()

    assert lines.splitlines()[1] == "| :---: | :--- |"
    assert default.splitlines()[1] == "| :--- |"


def test_malformed_tables_are_rejected() -> None:
    with pytest.raises(ValueError, match="row has 1 cells for 2 columns"):
        MarkdownBuilder().table(["A", "B"], [("only one",)])
    with pytest.raises(ValueError, match="align has 1 entries for 2 columns"):
        MarkdownBuilder().table(["A", "B"], [], align=[Align.LEFT])


@pytest.mark.parametrize("level", [0, 7])
def test_heading_levels_are_validated(level: int) -> None:
    with pytest.raises(ValueError, match="Heading level"):
        MarkdownBuilder().heading("x", level)


def test_empty_lists_are_skipped() -> None:
    assert MarkdownBuilder().paragraph("a").bullets([]).build() == "a\n"


def test_reports_are_strings_that_notebooks_render(tmp_path: Path) -> None:
    report = MarkdownBuilder().heading("Hola").build()

    assert isinstance(report, str)
    assert isinstance(report, MarkdownReport)
    assert report._repr_markdown_() == "## Hola\n"
    path = report.save(tmp_path / "nested" / "report.md")
    assert path.read_text(encoding="utf-8") == "## Hola\n"


def test_escape_cell_flattens_whitespace() -> None:
    assert escape_cell("  a \t b\n c ") == "a b c"
    assert escape_cell(3) == "3"


def test_non_breaking_spaces_survive() -> None:
    report = MarkdownBuilder().heading("12,3\u00a0%").table(["A"], [("95\u00a0%",)]).build()

    assert "12,3\u00a0%" in report
    assert "| 95\u00a0% |" in report
