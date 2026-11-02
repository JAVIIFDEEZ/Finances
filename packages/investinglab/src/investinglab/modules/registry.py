"""Registry of the master's course modules and their traceability (requirement → code → test).

Each block of the master becomes a module that registers a :class:`ModuleInfo`: what it
covers, in both languages, and for every requirement the code that implements it and the
tests that prove it. The API (``GET /modules``) and the web navigation are built from this
registry, and the documentation's traceability matrices are generated from it, so they can
never drift from the code (a test resolves every reference).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from investinglab.domain.errors import DomainError
from investinglab.reporting.i18n import Language
from investinglab.reporting.markdown import Align, MarkdownBuilder

if TYPE_CHECKING:
    from collections.abc import Iterator

    from investinglab.reporting.markdown import MarkdownReport

__all__ = [
    "REGISTRY",
    "ModuleInfo",
    "ModuleRegistry",
    "Requirement",
    "RequirementStatus",
    "render_traceability",
]


class RequirementStatus(StrEnum):
    """How far a requirement is implemented."""

    DONE = "done"
    PARTIAL = "partial"
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class Requirement:
    """One requirement of a module, written in our own words.

    Attributes:
        id: Short identifier (``4.2``).
        title_es: Spanish title.
        title_en: English title.
        code: What implements it: dotted Python paths (``investinglab.domain.Portfolio``) or
            repository paths (``README.md``).
        tests: Test files proving it, relative to the package's ``tests`` folder.
        status: Implementation status.
        note_es: Spanish note (what is missing, caveats).
        note_en: English note.
    """

    id: str
    title_es: str
    title_en: str
    code: tuple[str, ...]
    tests: tuple[str, ...] = ()
    status: RequirementStatus = RequirementStatus.DONE
    note_es: str = ""
    note_en: str = ""

    def title(self, language: Language | str) -> str:
        """Title in ``language``."""
        return self.title_es if Language(language) is Language.ES else self.title_en

    def note(self, language: Language | str) -> str:
        """Note in ``language``."""
        return self.note_es if Language(language) is Language.ES else self.note_en


@dataclass(frozen=True, slots=True)
class ModuleInfo:
    """A module of the platform, usually one block of the master.

    Attributes:
        slug: URL-friendly identifier (``b1-toolkit``).
        block: Course block it comes from.
        title_es: Spanish title.
        title_en: English title.
        summary_es: Spanish summary.
        summary_en: English summary.
        requirements: Traceability of its requirements.
    """

    slug: str
    block: str
    title_es: str
    title_en: str
    summary_es: str
    summary_en: str
    requirements: tuple[Requirement, ...] = field(default=())

    def title(self, language: Language | str) -> str:
        """Title in ``language``."""
        return self.title_es if Language(language) is Language.ES else self.title_en

    def summary(self, language: Language | str) -> str:
        """Summary in ``language``."""
        return self.summary_es if Language(language) is Language.ES else self.summary_en

    @property
    def complete(self) -> bool:
        """Whether every requirement is done."""
        return all(r.status is RequirementStatus.DONE for r in self.requirements)


class ModuleRegistry:
    """Registered modules, in registration order."""

    def __init__(self) -> None:
        self._modules: dict[str, ModuleInfo] = {}

    def register(self, module: ModuleInfo) -> ModuleInfo:
        """Register ``module`` (idempotent for the same object).

        Raises:
            DomainError: If another module already uses the slug.
        """
        existing = self._modules.get(module.slug)
        if existing is not None and existing is not module:
            raise DomainError(f"Module slug {module.slug!r} is already registered")
        self._modules[module.slug] = module
        return module

    def get(self, slug: str) -> ModuleInfo:
        """The module with ``slug``.

        Raises:
            KeyError: If it is not registered.
        """
        return self._modules[slug]

    def __iter__(self) -> Iterator[ModuleInfo]:
        return iter(self._modules.values())

    def __len__(self) -> int:
        return len(self._modules)


REGISTRY = ModuleRegistry()
"""Process-wide registry; each module package registers itself on import."""

_STATUS_LABELS = {
    RequirementStatus.DONE: ("Hecho", "Done"),
    RequirementStatus.PARTIAL: ("Parcial", "Partial"),
    RequirementStatus.PENDING: ("Pendiente", "Pending"),
}
_HEADERS = {
    Language.ES: ("Requisito", "Estado", "Implementación", "Pruebas", "Notas"),
    Language.EN: ("Requirement", "Status", "Implementation", "Tests", "Notes"),
}


def render_traceability(
    module: ModuleInfo, language: Language | str = Language.ES
) -> MarkdownReport:
    """The module's traceability matrix as Markdown (requirement → code → tests)."""
    lang = Language(language)
    index = 0 if lang is Language.ES else 1
    doc = MarkdownBuilder()
    doc.heading(f"{module.title(lang)} · {module.block}", 1)
    doc.paragraph(module.summary(lang))
    doc.table(
        list(_HEADERS[lang]),
        [
            (
                f"**{req.id}** {req.title(lang)}",
                _STATUS_LABELS[req.status][index],
                "<br>".join(f"`{ref}`" for ref in req.code),
                "<br>".join(f"`{ref}`" for ref in req.tests) or "—",
                req.note(lang) or "—",
            )
            for req in module.requirements
        ],
        align=[Align.LEFT, Align.LEFT, Align.LEFT, Align.LEFT, Align.LEFT],
    )
    return doc.build()
