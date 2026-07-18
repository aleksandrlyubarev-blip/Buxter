"""Relational indexing of construction PDF drawing sets.

Data layer of the BIM Analysis Agent (see docs/bim-analysis-architecture.md).
Instead of treating the set as a pile of images, every page is indexed once:
the vector text layer is extracted with coordinates, title-block metadata
(sheet number, title, revision, discipline) is detected, and the result is
persisted as the three project artifacts — ``drawings.md`` (master registry),
``objects-database.md`` and ``specs-wiki.md`` — that the agent then queries.

Extraction priority (highest first): vector text with coordinates via
pdfplumber → page flagged as an OCR / visual-check candidate. Nothing here
guesses: pages without a text layer are recorded as such, never skipped
silently, and no metadata field is filled with a default when detection
fails — it stays ``None``.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# A page whose whole text layer is shorter than this is treated as having no
# usable text layer (typical for scanned sheets with a vector stamp only).
MIN_TEXT_CHARS = 40

# Fraction of the page reserved for the title-block scan: bottom strip and
# right strip, where title blocks live in both ANSI/ISO and ГОСТ framing.
TITLE_BLOCK_BOTTOM_FRACTION = 0.18
TITLE_BLOCK_RIGHT_FRACTION = 0.15

# Default clustering radius for tag instance grouping, in PDF points.
DEFAULT_CLUSTER_RADIUS = 18.0

ARTIFACT_NAMES = ("drawings.md", "objects-database.md", "specs-wiki.md", "notes.md")
MANIFEST_NAME = "set-manifest.json"

# --- sheet metadata patterns -------------------------------------------------

# Western sheet numbers: S-101, A-201.1, FP-102, also compact A101 for the
# usual single-letter disciplines. The hyphenated form is preferred.
_SHEET_HYPHEN_RE = re.compile(r"\b([A-Z]{1,3})-(\d{2,4}(?:\.\d{1,2})?)\b")
_SHEET_COMPACT_RE = re.compile(r"\b([ASMEPC])(\d{3}(?:\.\d{1,2})?)\b")

# ГОСТ marks (марка комплекта) + "Лист N".
_GOST_MARK_RE = re.compile(
    r"\b(АР|АС|АИ|КЖ|КМ|КМД|КД|ОВ|ВК|НВК|ЭОМ|ЭС|ЭГ|СС|ТХ|ГП|ПОС|АУПТ|ПС)\b"
)
_GOST_SHEET_RE = re.compile(r"\bЛист\s*[:№]?\s*(\d+)\b", re.IGNORECASE)

_REVISION_RE = re.compile(
    r"\b(?:REV(?:ISION)?\.?|Изм\.?)\s*[:#№]?\s*([A-ZА-Я0-9]{1,3})\b", re.IGNORECASE
)

_DISCIPLINE_BY_PREFIX = {
    "G": "General",
    "A": "Architectural",
    "S": "Structural",
    "C": "Civil",
    "M": "Mechanical",
    "E": "Electrical",
    "P": "Plumbing",
    "FP": "Fire Protection",
    "LS": "Life Safety",
    "T": "Telecom",
}

_DISCIPLINE_BY_MARK = {
    "АР": "Архитектурные решения",
    "АС": "Архитектурно-строительные решения",
    "АИ": "Интерьеры",
    "КЖ": "Конструкции железобетонные",
    "КМ": "Конструкции металлические",
    "КМД": "Конструкции металлические деталировочные",
    "КД": "Конструкции деревянные",
    "ОВ": "Отопление и вентиляция",
    "ВК": "Водоснабжение и канализация",
    "НВК": "Наружные сети ВК",
    "ЭОМ": "Электрооборудование и освещение",
    "ЭС": "Электроснабжение",
    "ЭГ": "Молниезащита и заземление",
    "СС": "Сети связи",
    "ТХ": "Технология производства",
    "ГП": "Генеральный план",
    "ПОС": "Организация строительства",
    "АУПТ": "Автоматическое пожаротушение",
    "ПС": "Пожарная сигнализация",
}


@dataclass
class TextSpan:
    """One word/fragment of the vector text layer with its bounding box."""

    text: str
    x0: float
    top: float
    x1: float
    bottom: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass
class PageText:
    """Extracted content of a single PDF page."""

    file: str
    pdf_page: int  # 1-based, PDF page — NOT the construction sheet number
    width: float
    height: float
    spans: list[TextSpan] = field(default_factory=list)
    raw_text: str = ""

    @property
    def has_text_layer(self) -> bool:
        return len(self.raw_text.strip()) >= MIN_TEXT_CHARS


@dataclass
class SheetRecord:
    """One row of the master drawing registry."""

    file: str
    pdf_page: int
    sheet_no: str | None
    title: str | None
    revision: str | None
    discipline: str | None
    has_text_layer: bool

    @property
    def needs_ocr(self) -> bool:
        return not self.has_text_layer


@dataclass
class Occurrence:
    """A tag/text hit on a page, with the click point for de-duplication."""

    text: str
    file: str
    pdf_page: int
    x: float
    y: float


@dataclass
class DrawingSetIndex:
    sheets: list[SheetRecord] = field(default_factory=list)
    pages: list[PageText] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def page(self, file: str, pdf_page: int) -> PageText | None:
        for page in self.pages:
            if page.file == file and page.pdf_page == pdf_page:
                return page
        return None


# --- extraction --------------------------------------------------------------


def load_pages(pdf_path: Path) -> list[PageText]:
    """Extract the vector text layer of every page with coordinates."""
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            "pdfplumber is not installed. pip install 'buxter[bim]'"
        ) from exc

    pages: list[PageText] = []
    with pdfplumber.open(pdf_path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            words = page.extract_words() or []
            spans = [
                TextSpan(
                    text=word["text"],
                    x0=float(word["x0"]),
                    top=float(word["top"]),
                    x1=float(word["x1"]),
                    bottom=float(word["bottom"]),
                )
                for word in words
            ]
            pages.append(
                PageText(
                    file=pdf_path.name,
                    pdf_page=number,
                    width=float(page.width),
                    height=float(page.height),
                    spans=spans,
                    raw_text=page.extract_text() or "",
                )
            )
    return pages


def title_block_spans(page: PageText) -> list[TextSpan]:
    """Spans inside the probable title-block area (bottom or right strip)."""
    bottom_edge = page.height * (1.0 - TITLE_BLOCK_BOTTOM_FRACTION)
    right_edge = page.width * (1.0 - TITLE_BLOCK_RIGHT_FRACTION)
    return [s for s in page.spans if s.cy >= bottom_edge or s.cx >= right_edge]


def detect_sheet_metadata(page: PageText) -> SheetRecord:
    """Detect sheet number / revision / discipline for one page.

    The title-block zone is scanned first so that cross-references in the
    drawing body ("SEE S-201") never win over the sheet's own number. A field
    that cannot be detected stays ``None`` — no defaults.
    """
    zones: list[list[TextSpan]] = [title_block_spans(page), page.spans]
    sheet_no: str | None = None
    discipline: str | None = None

    for zone in zones:
        text = " ".join(s.text for s in zone)
        match = _SHEET_HYPHEN_RE.search(text)
        if match:
            sheet_no = f"{match.group(1)}-{match.group(2)}"
            discipline = _DISCIPLINE_BY_PREFIX.get(match.group(1))
            break
        match = _SHEET_COMPACT_RE.search(text)
        if match:
            sheet_no = f"{match.group(1)}{match.group(2)}"
            discipline = _DISCIPLINE_BY_PREFIX.get(match.group(1))
            break
        mark = _GOST_MARK_RE.search(text)
        gost_sheet = _GOST_SHEET_RE.search(text)
        if mark and gost_sheet:
            sheet_no = f"{mark.group(1)}, лист {gost_sheet.group(1)}"
            discipline = _DISCIPLINE_BY_MARK.get(mark.group(1))
            break
        if mark and discipline is None:
            discipline = _DISCIPLINE_BY_MARK.get(mark.group(1))

    revision: str | None = None
    for zone in zones:
        text = " ".join(s.text for s in zone)
        match = _REVISION_RE.search(text)
        if match:
            revision = match.group(1)
            break

    return SheetRecord(
        file=page.file,
        pdf_page=page.pdf_page,
        sheet_no=sheet_no,
        title=None,  # titles are free text; the agent fills them in review
        revision=revision,
        discipline=discipline,
        has_text_layer=page.has_text_layer,
    )


def index_drawing_set(paths: Iterable[Path]) -> DrawingSetIndex:
    """Build the registry for a whole set. Per-file failures are recorded."""
    index = DrawingSetIndex()
    for path in paths:
        try:
            pages = load_pages(path)
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad file must not kill the set
            index.errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
            continue
        index.pages.extend(pages)
        index.sheets.extend(detect_sheet_metadata(page) for page in pages)
    return index


# --- tag search & counting ---------------------------------------------------


def find_occurrences(
    pages: Iterable[PageText], query: str, *, regex: bool = False
) -> list[Occurrence]:
    """All hits of a tag/text in the vector layer, with coordinates."""
    pattern = re.compile(query if regex else re.escape(query), re.IGNORECASE)
    hits: list[Occurrence] = []
    for page in pages:
        for span in page.spans:
            if pattern.search(span.text):
                hits.append(
                    Occurrence(
                        text=span.text,
                        file=page.file,
                        pdf_page=page.pdf_page,
                        x=span.cx,
                        y=span.cy,
                    )
                )
    return hits


def cluster_occurrences(
    occurrences: list[Occurrence], radius: float = DEFAULT_CLUSTER_RADIUS
) -> list[list[Occurrence]]:
    """Group hits that sit within `radius` of each other on the same page.

    A leader-tag split across fragments ("W1" + "2x") must count as one
    instance, so the count of *clusters*, not raw hits, approximates the
    instance count. Single-linkage on a per-page basis; O(n²) per page is
    fine at drawing scale.
    """
    by_page: dict[tuple[str, int], list[Occurrence]] = {}
    for occ in occurrences:
        by_page.setdefault((occ.file, occ.pdf_page), []).append(occ)

    clusters: list[list[Occurrence]] = []
    for page_hits in by_page.values():
        remaining = list(page_hits)
        while remaining:
            seed = remaining.pop(0)
            group = [seed]
            changed = True
            while changed:
                changed = False
                for occ in list(remaining):
                    if any(
                        math.hypot(occ.x - member.x, occ.y - member.y) <= radius
                        for member in group
                    ):
                        group.append(occ)
                        remaining.remove(occ)
                        changed = True
            clusters.append(group)
    return clusters


def exclude_zones(
    occurrences: list[Occurrence],
    zones: list[tuple[str, int, float, float, float, float]],
) -> list[Occurrence]:
    """Drop hits inside exclusion boxes (legends, notes, typical details).

    Each zone is ``(file, pdf_page, x0, y0, x1, y1)`` in page coordinates.
    """
    def inside(occ: Occurrence) -> bool:
        return any(
            occ.file == file
            and occ.pdf_page == page
            and x0 <= occ.x <= x1
            and y0 <= occ.y <= y1
            for file, page, x0, y0, x1, y1 in zones
        )

    return [occ for occ in occurrences if not inside(occ)]


# --- artifacts ---------------------------------------------------------------


def render_drawings_md(index: DrawingSetIndex) -> str:
    """Master registry (`drawings.md`) in the Buxter artifact format."""
    lines = [
        "# Drawings — мастер-реестр комплекта",
        "",
        "Автоматическая индексация текстового слоя. `Лист`, `Ревизия` и",
        "`Дисциплина` извлечены из зоны штампа; `—` означает «не обнаружено",
        "программно», а не «отсутствует на листе». Поля `Название`,",
        "`Содержимое` и `Связанные листы` заполняет агент по мере анализа.",
        "",
        "| Файл | PDF-страница | Лист | Название | Ревизия | Дисциплина | Содержимое | Связанные листы | Статус |",
        "|---|---:|---|---|---|---|---|---|---|",
    ]
    for sheet in index.sheets:
        status = "OCR/визуальная проверка" if sheet.needs_ocr else "текстовый слой OK"
        lines.append(
            "| {file} | {page} | {no} | {title} | {rev} | {disc} |  |  | {status} |".format(
                file=sheet.file,
                page=sheet.pdf_page,
                no=sheet.sheet_no or "—",
                title=sheet.title or "",
                rev=sheet.revision or "—",
                disc=sheet.discipline or "—",
                status=status,
            )
        )
    if index.errors:
        lines += ["", "## Ошибки индексации", ""]
        lines += [f"- {error}" for error in index.errors]
    lines.append("")
    return "\n".join(lines)


OBJECTS_DB_TEMPLATE = """# Objects Database — объектная база комплекта

Информация организована по физическим объектам, не по страницам.
Статусы данных: `Extracted` / `Calculated` / `Estimated` / `Unresolved`.
Reliability: `High` / `Medium` / `Low` — низкую надёжность нельзя скрывать.

| Объект | Марка | Количество | Размеры | Материал | Источники | Метод | Надёжность |
|---|---|---:|---|---|---|---|---|

## Нерешённые вопросы

(нет)
"""

SPECS_WIKI_TEMPLATE = """# Specs Wiki — база спецификаций и общих требований

Каждое правило: краткое содержание → точная ссылка на источник → область
применения → связанные объекты → исключения. Разные требования не
объединяются в одно правило без подтверждения.

## Общие примечания

## Применимые нормы

## Материалы, марки и классы

## Требования к монтажу и допуски

## Защитные слои и соединения

## Противоречия между документами

(нет зафиксированных)
"""


def write_artifacts(index: DrawingSetIndex, workdir: Path, pdf_paths: list[Path]) -> list[Path]:
    """Write drawings.md + artifact skeletons + the set manifest.

    Existing ``objects-database.md`` / ``specs-wiki.md`` are preserved — they
    accumulate agent findings across sessions; only the auto-generated
    registry is refreshed.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    drawings = workdir / "drawings.md"
    drawings.write_text(render_drawings_md(index), encoding="utf-8")
    written.append(drawings)

    for name, template in (
        ("objects-database.md", OBJECTS_DB_TEMPLATE),
        ("specs-wiki.md", SPECS_WIKI_TEMPLATE),
    ):
        target = workdir / name
        if not target.exists():
            target.write_text(template, encoding="utf-8")
            written.append(target)

    manifest = workdir / MANIFEST_NAME
    manifest.write_text(
        json.dumps(
            {"pdfs": [str(path.resolve()) for path in pdf_paths]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    written.append(manifest)
    return written


def load_manifest(workdir: Path) -> list[Path]:
    manifest = workdir / MANIFEST_NAME
    if not manifest.exists():
        return []
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return [Path(entry) for entry in data.get("pdfs", [])]


__all__ = [
    "ARTIFACT_NAMES",
    "DEFAULT_CLUSTER_RADIUS",
    "DrawingSetIndex",
    "Occurrence",
    "PageText",
    "SheetRecord",
    "TextSpan",
    "cluster_occurrences",
    "detect_sheet_metadata",
    "exclude_zones",
    "find_occurrences",
    "index_drawing_set",
    "load_manifest",
    "load_pages",
    "render_drawings_md",
    "title_block_spans",
    "write_artifacts",
]
