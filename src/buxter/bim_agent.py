"""BIM Analysis Agent: a Claude tool-use loop over an indexed drawing set.

Third Buxter layer. The Modeling Agent produces geometry, the Web Operator
ships it — this layer reads construction documentation: it answers quantity
and specification questions over a PDF drawing set using the Relational
Indexing Workflow (see docs/bim-analysis-architecture.md).

The agent never sees raw files. It works through a :class:`DocSession`,
which exposes the indexed set (registry, page text with coordinates, tag
search/counting, tables, page raster for visual confirmation) plus the three
project artifacts. Artifact writes are whitelisted by name — the agent
cannot touch anything else on disk. The loop ends with the ``finish`` tool,
which forces a structured, source-cited answer with an explicit reliability
grade instead of free text.
"""

from __future__ import annotations

import base64
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from anthropic import Anthropic

from .config import Settings, resolve_model
from .pdf_index import (
    ARTIFACT_NAMES,
    DEFAULT_CLUSTER_RADIUS,
    DrawingSetIndex,
    cluster_occurrences,
    exclude_zones,
    find_occurrences,
    index_drawing_set,
)
from .prompts import BIM_SYSTEM_PROMPT

BIM_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_sheets",
        "description": (
            "Return the master registry: every PDF page with its detected "
            "sheet number, revision, discipline and text-layer status."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_page_text",
        "description": (
            "Return the full vector text layer of one PDF page. `file` is the "
            "PDF file name from the registry, `page` is the 1-based PDF page "
            "number (NOT the construction sheet number)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "page": {"type": "integer"},
            },
            "required": ["file", "page"],
        },
    },
    {
        "name": "search_text",
        "description": (
            "Find all occurrences of a tag or text in the vector layer, with "
            "page and x/y coordinates. Optionally restrict to one file/page. "
            "Set regex=true to treat the query as a regular expression."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "file": {"type": "string"},
                "page": {"type": "integer"},
                "regex": {"type": "boolean", "default": False},
            },
            "required": ["query"],
        },
    },
    {
        "name": "count_tag",
        "description": (
            "Count probable instances of a mark/tag: occurrences are grouped "
            "into clusters by proximity (a tag split into fragments counts "
            "once). Returns per-page cluster counts and cluster coordinates. "
            "Legends/notes/schedules are NOT excluded automatically. First "
            "identify them via search_text/render_page, then pass auditable "
            "exclude_regions. A region without coordinates excludes its whole page."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tag": {"type": "string"},
                "file": {"type": "string"},
                "page": {"type": "integer"},
                "regex": {"type": "boolean", "default": False},
                "cluster_radius": {"type": "number"},
                "exclude_regions": {
                    "type": "array",
                    "description": (
                        "Verified non-instance regions in top-left-origin PDF points. "
                        "Provide all four coordinates for a rectangle, or omit all "
                        "four to exclude the entire page. A reason is mandatory."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string"},
                            "page": {"type": "integer"},
                            "x0": {"type": "number"},
                            "top": {"type": "number"},
                            "x1": {"type": "number"},
                            "bottom": {"type": "number"},
                            "reason": {"type": "string"},
                        },
                        "required": ["file", "page", "reason"],
                    },
                },
            },
            "required": ["tag"],
        },
    },
    {
        "name": "extract_tables",
        "description": (
            "Extract tables (schedules, ведомости, экспликации) from one PDF "
            "page as text rows."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "page": {"type": "integer"},
            },
            "required": ["file", "page"],
        },
    },
    {
        "name": "render_page",
        "description": (
            "Rasterize one PDF page to a PNG image for visual confirmation. "
            "Use only when programmatic extraction is insufficient (no text "
            "layer, ambiguous tag, geometry check)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "page": {"type": "integer"},
            },
            "required": ["file", "page"],
        },
    },
    {
        "name": "read_artifact",
        "description": (
            "Read one of the project artifacts: drawings.md, "
            "objects-database.md, specs-wiki.md, notes.md."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "write_artifact",
        "description": (
            "Overwrite one of the project artifacts (same whitelist as "
            "read_artifact) with updated content. Keep prior content you did "
            "not change — read before writing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["name", "content"],
        },
    },
    {
        "name": "finish",
        "description": (
            "End the task with the final answer. `reliability` must be High, "
            "Medium or Low; `sources` must cite sheet/PDF page/table for "
            "every material number in the answer. Use `unresolved` for data "
            "that could not be confirmed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "reliability": {
                    "type": "string",
                    "enum": ["High", "Medium", "Low"],
                },
                "sources": {"type": "array", "items": {"type": "string"}},
                "unresolved": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["answer", "reliability", "sources"],
        },
    },
]


class DocSession:
    """Indexed drawing set + workdir artifacts, as seen by the agent."""

    def __init__(
        self,
        pdf_paths: list[Path],
        workdir: Path,
        *,
        render_dpi: int = 150,
        index: DrawingSetIndex | None = None,
    ) -> None:
        self.pdf_paths = {path.name: path.resolve() for path in pdf_paths}
        self.workdir = workdir
        self.render_dpi = render_dpi
        self.index = index if index is not None else index_drawing_set(list(pdf_paths))

    # -- registry / text ------------------------------------------------------

    def list_sheets(self) -> str:
        if not self.index.sheets:
            return "The drawing set is empty — no pages were indexed."
        lines = ["file | pdf_page | sheet_no | revision | discipline | text_layer"]
        for sheet in self.index.sheets:
            lines.append(
                f"{sheet.file} | {sheet.pdf_page} | {sheet.sheet_no or '-'} | "
                f"{sheet.revision or '-'} | {sheet.discipline or '-'} | "
                f"{'no — OCR/visual candidate' if sheet.needs_ocr else 'yes'}"
            )
        if self.index.errors:
            lines.append("indexing errors: " + "; ".join(self.index.errors))
        return "\n".join(lines)

    def read_page_text(self, file: str, page: int) -> str:
        record = self.index.page(file, page)
        if record is None:
            return f"No indexed page {page} in {file!r}. Check list_sheets."
        if not record.has_text_layer:
            return (
                f"{file} p.{page}: no usable text layer "
                f"({len(record.raw_text.strip())} chars). Use render_page."
            )
        return record.raw_text

    def search_text(
        self,
        query: str,
        file: str | None = None,
        page: int | None = None,
        regex: bool = False,
    ) -> str:
        pages = [
            p
            for p in self.index.pages
            if (file is None or p.file == file) and (page is None or p.pdf_page == page)
        ]
        try:
            hits = find_occurrences(pages, query, regex=regex)
        except re.error as exc:
            return f"Invalid regex {query!r}: {exc}"
        if not hits:
            return f"No occurrences of {query!r} in the selected scope."
        lines = [f"{len(hits)} occurrence(s) of {query!r}:"]
        lines += [
            f"- {occ.file} p.{occ.pdf_page} @({occ.x:.0f},{occ.y:.0f}): {occ.text}"
            for occ in hits[:200]
        ]
        if len(hits) > 200:
            lines.append(f"... and {len(hits) - 200} more; narrow the scope.")
        return "\n".join(lines)

    def count_tag(
        self,
        tag: str,
        file: str | None = None,
        page: int | None = None,
        regex: bool = False,
        cluster_radius: float | None = None,
        exclude_regions: list[dict[str, Any]] | None = None,
    ) -> str:
        pages = [
            p
            for p in self.index.pages
            if (file is None or p.file == file) and (page is None or p.pdf_page == page)
        ]
        try:
            raw_hits = find_occurrences(pages, tag, regex=regex)
        except re.error as exc:
            return f"Invalid regex {tag!r}: {exc}"
        if not raw_hits:
            return f"No occurrences of {tag!r} in the selected scope."

        zones: list[tuple[str, int, float, float, float, float]] = []
        exclusion_labels: list[str] = []
        for number, region in enumerate(exclude_regions or [], start=1):
            region_file = str(region.get("file", ""))
            try:
                region_page = int(region["page"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"exclude_regions[{number}] requires an integer page"
                ) from exc
            reason = str(region.get("reason", "")).strip()
            if not reason:
                raise ValueError(f"exclude_regions[{number}] requires a reason")
            record = self.index.page(region_file, region_page)
            if record is None:
                raise ValueError(
                    f"exclude_regions[{number}] refers to unknown page "
                    f"{region_page} in {region_file!r}"
                )

            coordinate_keys = ("x0", "top", "x1", "bottom")
            supplied = [region.get(key) is not None for key in coordinate_keys]
            if any(supplied) and not all(supplied):
                raise ValueError(
                    f"exclude_regions[{number}] must provide all of "
                    "x0/top/x1/bottom or none"
                )
            if all(supplied):
                x0, top, x1, bottom = (
                    float(region[key]) for key in coordinate_keys
                )
            else:
                x0, top, x1, bottom = 0.0, 0.0, record.width, record.height
            if not all(math.isfinite(value) for value in (x0, top, x1, bottom)):
                raise ValueError(
                    f"exclude_regions[{number}] coordinates must be finite"
                )
            if not (
                0 <= x0 < x1 <= record.width
                and 0 <= top < bottom <= record.height
            ):
                raise ValueError(
                    f"exclude_regions[{number}] is outside {region_file} "
                    f"p.{region_page} bounds ({record.width:g}x{record.height:g})"
                )
            zones.append((region_file, region_page, x0, top, x1, bottom))
            exclusion_labels.append(
                f"- {region_file} p.{region_page} "
                f"@({x0:g},{top:g})-({x1:g},{bottom:g}): {reason}"
            )

        hits = exclude_zones(raw_hits, zones)
        clusters = cluster_occurrences(hits, cluster_radius or DEFAULT_CLUSTER_RADIUS)
        per_page: dict[tuple[str, int], int] = {}
        for cluster in clusters:
            key = (cluster[0].file, cluster[0].pdf_page)
            per_page[key] = per_page.get(key, 0) + 1
        lines = [
            f"{len(clusters)} clustered instance(s) of {tag!r} "
            f"from {len(raw_hits)} raw hit(s)."
        ]
        if zones:
            lines.append(
                f"Excluded {len(raw_hits) - len(hits)} raw hit(s) using "
                f"{len(zones)} declared region(s):"
            )
            lines.extend(exclusion_labels)
        lines.append("Per page:")
        for (hit_file, hit_page), count in sorted(per_page.items()):
            lines.append(f"- {hit_file} p.{hit_page}: {count}")
        lines.append("Cluster anchors:")
        lines += [
            f"- {c[0].file} p.{c[0].pdf_page} @({c[0].x:.0f},{c[0].y:.0f}) "
            f"[{' '.join(sorted({o.text for o in c}))}]"
            for c in clusters[:100]
        ]
        if len(clusters) > 100:
            lines.append(f"... and {len(clusters) - 100} more anchors.")
        return "\n".join(lines)

    # -- heavier extraction ---------------------------------------------------

    def extract_tables(self, file: str, page: int) -> str:
        path = self.pdf_paths.get(file)
        if path is None:
            return f"Unknown file {file!r}. Known: {', '.join(sorted(self.pdf_paths))}"
        try:
            import pdfplumber
        except ImportError:
            return "pdfplumber is not installed. pip install 'buxter[bim]'"
        with pdfplumber.open(path) as pdf:
            if not 1 <= page <= len(pdf.pages):
                return f"{file} has {len(pdf.pages)} pages; page {page} is out of range."
            tables = pdf.pages[page - 1].extract_tables() or []
        if not tables:
            return f"No tables detected on {file} p.{page}."
        lines: list[str] = []
        for table_no, table in enumerate(tables, start=1):
            lines.append(f"Table {table_no} ({len(table)} rows):")
            lines += [
                " | ".join("" if cell is None else str(cell) for cell in row)
                for row in table
            ]
            lines.append("")
        return "\n".join(lines).strip()

    def render_page(self, file: str, page: int) -> bytes:
        path = self.pdf_paths.get(file)
        if path is None:
            raise ValueError(
                f"Unknown file {file!r}. Known: {', '.join(sorted(self.pdf_paths))}"
            )
        try:
            import pypdfium2
        except ImportError as exc:
            raise RuntimeError(
                "pypdfium2 is not installed. pip install 'buxter[bim]'"
            ) from exc
        pdf = pypdfium2.PdfDocument(path)
        try:
            if not 1 <= page <= len(pdf):
                raise ValueError(f"{file} has {len(pdf)} pages; page {page} is out of range.")
            bitmap = pdf[page - 1].render(scale=self.render_dpi / 72.0)
            image = bitmap.to_pil()
        finally:
            pdf.close()
        import io

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    # -- artifacts ------------------------------------------------------------

    def _artifact_path(self, name: str) -> Path | None:
        # Whitelist by exact name: no path traversal, no arbitrary writes.
        if name not in ARTIFACT_NAMES:
            return None
        return self.workdir / name

    def read_artifact(self, name: str) -> str:
        path = self._artifact_path(name)
        if path is None:
            return (
                f"Refused: {name!r} is not a project artifact. "
                f"Allowed: {', '.join(ARTIFACT_NAMES)}"
            )
        if not path.exists():
            return f"{name} does not exist yet."
        return path.read_text(encoding="utf-8")

    def write_artifact(self, name: str, content: str) -> str:
        path = self._artifact_path(name)
        if path is None:
            return (
                f"Refused: {name!r} is not a project artifact. "
                f"Allowed: {', '.join(ARTIFACT_NAMES)}"
            )
        self.workdir.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to {name}."


@dataclass
class BimStep:
    tool: str
    input: dict[str, Any]
    result: str


@dataclass
class BimReport:
    success: bool
    answer: str
    reliability: str = "Low"
    sources: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    steps: list[BimStep] = field(default_factory=list)


def _dispatch(
    session: DocSession, name: str, args: dict[str, Any]
) -> tuple[list[dict[str, Any]] | str, bool]:
    """Run one tool call. Returns (tool_result content, is_error)."""
    try:
        if name == "list_sheets":
            return session.list_sheets(), False
        if name == "read_page_text":
            return session.read_page_text(args["file"], int(args["page"])), False
        if name == "search_text":
            return (
                session.search_text(
                    args["query"],
                    file=args.get("file"),
                    page=int(args["page"]) if args.get("page") is not None else None,
                    regex=bool(args.get("regex", False)),
                ),
                False,
            )
        if name == "count_tag":
            return (
                session.count_tag(
                    args["tag"],
                    file=args.get("file"),
                    page=int(args["page"]) if args.get("page") is not None else None,
                    regex=bool(args.get("regex", False)),
                    cluster_radius=(
                        float(args["cluster_radius"])
                        if args.get("cluster_radius") is not None
                        else None
                    ),
                    exclude_regions=args.get("exclude_regions"),
                ),
                False,
            )
        if name == "extract_tables":
            return session.extract_tables(args["file"], int(args["page"])), False
        if name == "render_page":
            png = session.render_page(args["file"], int(args["page"]))
            return (
                [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.standard_b64encode(png).decode("ascii"),
                        },
                    }
                ],
                False,
            )
        if name == "read_artifact":
            return session.read_artifact(args["name"]), False
        if name == "write_artifact":
            result = session.write_artifact(args["name"], args["content"])
            return result, result.startswith("Refused")
        return f"Unknown tool {name!r}", True
    except Exception as exc:  # surface extraction errors to the model, don't crash
        return f"{type(exc).__name__}: {exc}", True


def _task_message(question: str, session: DocSession) -> str:
    return (
        f"Question:\n{question}\n\n"
        f"Drawing set registry (list_sheets):\n{session.list_sheets()}\n\n"
        f"Workdir artifacts present: "
        + (
            ", ".join(
                name for name in ARTIFACT_NAMES if (session.workdir / name).exists()
            )
            or "(none yet)"
        )
    )


def run_bim_task(
    question: str,
    *,
    settings: Settings,
    session: DocSession,
    client: Anthropic | None = None,
    on_step: Callable[[BimStep], None] | None = None,
) -> BimReport:
    """Drive `session` with Claude until the model calls ``finish``."""
    if not settings.anthropic_api_key and client is None:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    anthropic = client or Anthropic(api_key=settings.anthropic_api_key)
    model_id = resolve_model(settings.model)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _task_message(question, session)}
    ]
    steps: list[BimStep] = []

    for _ in range(settings.bim_max_steps):
        response = anthropic.messages.create(
            model=model_id,
            max_tokens=settings.max_tokens,
            system=BIM_SYSTEM_PROMPT,
            tools=BIM_TOOLS,
            messages=messages,
        )
        tool_uses = [
            block for block in response.content if getattr(block, "type", None) == "tool_use"
        ]
        if not tool_uses:
            text = "".join(
                block.text
                for block in response.content
                if getattr(block, "type", None) == "text"
            )
            return BimReport(
                success=False,
                answer=text.strip() or "Agent stopped without calling finish.",
                steps=steps,
            )

        assistant_content: list[dict[str, Any]] = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif getattr(block, "type", None) == "tool_use":
                assistant_content.append(
                    {"type": "tool_use", "id": block.id, "name": block.name,
                     "input": block.input}
                )
        messages.append({"role": "assistant", "content": assistant_content})

        results: list[dict[str, Any]] = []
        for call in tool_uses:
            args = dict(call.input or {})
            if call.name == "finish":
                step = BimStep(tool="finish", input=args, result="done")
                steps.append(step)
                if on_step:
                    on_step(step)
                return BimReport(
                    success=True,
                    answer=str(args.get("answer", "")),
                    reliability=str(args.get("reliability", "Low")),
                    sources=[str(s) for s in args.get("sources", [])],
                    unresolved=[str(u) for u in args.get("unresolved", [])],
                    steps=steps,
                )
            content, is_error = _dispatch(session, call.name, args)
            snippet = content if isinstance(content, str) else "[page image]"
            step = BimStep(tool=call.name, input=args, result=snippet[:500])
            steps.append(step)
            if on_step:
                on_step(step)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": content,
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": results})

    return BimReport(
        success=False,
        answer=f"Step budget exhausted ({settings.bim_max_steps} model turns).",
        steps=steps,
    )


__all__ = ["BIM_TOOLS", "BimReport", "BimStep", "DocSession", "run_bim_task"]
