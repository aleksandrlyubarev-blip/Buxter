"""Core technical-drawing generator for electronics assembly/inspection.

Fable-phase prototype of the Buxter MCP electronics-drawing layer. Produces
professional 2D CAD files (DXF via ezdxf) from a machine-readable assembly
spec: board outline, holes with tolerances, centerlines, dimensions, GD&T
notes, inspection balloons for critical features and a title block carrying
simulation metadata (Sim ID, RoboQC/RomeoFlexVision, drawing type, revision).

The output opens as an editable drawing in FreeCAD, AutoCAD, SolidWorks,
KiCad and any DXF-capable tool.

Layer model:
    VISIBLE     — part geometry (outline, holes)
    HIDDEN      — hidden edges (reserved)
    CENTER      — centerlines through holes
    DIMENSIONS  — linear dims and diameter callouts
    INSPECTION  — balloons on inspection-critical features
    TITLE_BLOCK — frame, title block, notes

Everything here is deterministic given the spec: no randomness, no network,
the only filesystem write is the requested output path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf.document import Drawing
from ezdxf.layouts import Modelspace

LAYERS: dict[str, dict[str, Any]] = {
    "VISIBLE": {"color": 7},
    "HIDDEN": {"color": 8, "linetype": "HIDDEN"},
    "CENTER": {"color": 1, "linetype": "CENTER"},
    "DIMENSIONS": {"color": 3},
    "INSPECTION": {"color": 5},
    "TITLE_BLOCK": {"color": 7},
}

TEXT_H = 3.0          # base annotation text height, mm
BALLOON_R = 4.0       # inspection balloon radius, mm
DIM_OFFSET = 12.0     # distance of dimension lines from geometry, mm


class SpecError(ValueError):
    """Raised when an assembly spec is structurally invalid."""


class DrawingError(Exception):
    """Raised when an existing DXF cannot be read or annotated."""


@dataclass
class Hole:
    """A drilled/routed hole in the board or fixture plate."""

    x: float
    y: float
    diameter: float
    tolerance: str = ""       # e.g. "+0.05/-0.00", "H7"
    critical: bool = False    # inspection-critical → balloon + position dims
    label: str = ""           # e.g. "4x M3 MOUNTING", "ALIGNMENT PIN"


@dataclass
class BoardSpec:
    width: float
    height: float
    thickness: float


@dataclass
class AssemblySpec:
    """Machine-readable input, typically produced from simulation data."""

    name: str
    simulation_id: str
    board: BoardSpec
    holes: list[Hole] = field(default_factory=list)
    drawing_type: str = "INSPECTION"      # ASSEMBLY / INSPECTION / FIXTURE
    revision: str = "A"
    author: str = "Buxter Drawing Agent"
    source_system: str = "RoboQC / RomeoFlexVision"
    general_tolerance: str = "ISO 2768-mK"
    units: str = "mm"
    gdt_notes: list[str] = field(default_factory=list)
    issue_date: str = ""                  # ISO date; empty → today

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssemblySpec":
        """Validate and build a spec from a JSON-shaped dict (MCP boundary)."""
        try:
            board_raw = data["board"]
            board = BoardSpec(
                width=float(board_raw["width"]),
                height=float(board_raw["height"]),
                thickness=float(board_raw["thickness"]),
            )
            holes = [
                Hole(
                    x=float(h["x"]),
                    y=float(h["y"]),
                    diameter=float(h["diameter"]),
                    tolerance=str(h.get("tolerance", "")),
                    critical=bool(h.get("critical", False)),
                    label=str(h.get("label", "")),
                )
                for h in data.get("holes", [])
            ]
            spec = cls(
                name=str(data["name"]),
                simulation_id=str(data["simulation_id"]),
                board=board,
                holes=holes,
                drawing_type=str(data.get("drawing_type", "INSPECTION")).upper(),
                revision=str(data.get("revision", "A")),
                author=str(data.get("author", cls.author)),
                source_system=str(data.get("source_system", cls.source_system)),
                general_tolerance=str(data.get("general_tolerance", cls.general_tolerance)),
                units=str(data.get("units", "mm")),
                gdt_notes=[str(n) for n in data.get("gdt_notes", [])],
                issue_date=str(data.get("issue_date", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SpecError(f"Invalid assembly spec: {exc!r}") from exc
        spec.validate()
        return spec

    def validate(self) -> None:
        if self.board.width <= 0 or self.board.height <= 0 or self.board.thickness <= 0:
            raise SpecError("Board dimensions must be positive.")
        for hole in self.holes:
            if hole.diameter <= 0:
                raise SpecError(f"Hole at ({hole.x}, {hole.y}) has non-positive diameter.")
            if not (0 <= hole.x <= self.board.width and 0 <= hole.y <= self.board.height):
                raise SpecError(
                    f"Hole at ({hole.x}, {hole.y}) lies outside the board "
                    f"{self.board.width}x{self.board.height}."
                )


# --- drawing pieces ----------------------------------------------------------


def _setup_document() -> Drawing:
    doc = ezdxf.new("R2010", setup=True)  # setup=True loads linetypes + dimstyles
    for name, attribs in LAYERS.items():
        doc.layers.add(name, **attribs)
    return doc


def _draw_outline(msp: Modelspace, spec: AssemblySpec) -> None:
    w, h = spec.board.width, spec.board.height
    msp.add_lwpolyline(
        [(0, 0), (w, 0), (w, h), (0, h)],
        close=True,
        dxfattribs={"layer": "VISIBLE"},
    )


def _draw_hole(msp: Modelspace, hole: Hole) -> None:
    r = hole.diameter / 2.0
    msp.add_circle((hole.x, hole.y), r, dxfattribs={"layer": "VISIBLE"})
    reach = r + 2.0
    msp.add_line((hole.x - reach, hole.y), (hole.x + reach, hole.y),
                 dxfattribs={"layer": "CENTER"})
    msp.add_line((hole.x, hole.y - reach), (hole.x, hole.y + reach),
                 dxfattribs={"layer": "CENTER"})

    callout = f"Ø{hole.diameter:g}"
    if hole.tolerance:
        callout += f" {hole.tolerance}"
    if hole.label:
        callout += f"  {hole.label}"
    msp.add_text(
        callout, height=TEXT_H, dxfattribs={"layer": "DIMENSIONS"},
    ).set_placement((hole.x + reach + 1.0, hole.y + 1.0))


def _draw_inspection_balloon(msp: Modelspace, hole: Hole, number: int) -> None:
    cx = hole.x + hole.diameter / 2.0 + BALLOON_R + 6.0
    cy = hole.y + hole.diameter / 2.0 + BALLOON_R + 6.0
    msp.add_circle((cx, cy), BALLOON_R, dxfattribs={"layer": "INSPECTION"})
    msp.add_text(
        str(number), height=TEXT_H, dxfattribs={"layer": "INSPECTION"},
    ).set_placement((cx - TEXT_H / 3.0, cy - TEXT_H / 2.0))
    # leader from balloon edge toward the hole center
    msp.add_line(
        (cx - BALLOON_R * 0.7, cy - BALLOON_R * 0.7),
        (hole.x + hole.diameter / 2.0 * 0.7, hole.y + hole.diameter / 2.0 * 0.7),
        dxfattribs={"layer": "INSPECTION"},
    )


def _add_overall_dimensions(msp: Modelspace, spec: AssemblySpec) -> None:
    w, h = spec.board.width, spec.board.height
    msp.add_linear_dim(
        base=(0, -DIM_OFFSET), p1=(0, 0), p2=(w, 0),
        dxfattribs={"layer": "DIMENSIONS"},
    ).render()
    msp.add_linear_dim(
        base=(-DIM_OFFSET, 0), p1=(0, 0), p2=(0, h), angle=90,
        dxfattribs={"layer": "DIMENSIONS"},
    ).render()


def _add_critical_position_dims(msp: Modelspace, spec: AssemblySpec) -> None:
    # Position of every inspection-critical hole from the datum corner (0,0).
    for level, hole in enumerate(h for h in spec.holes if h.critical):
        offset = DIM_OFFSET * (2 + level)
        msp.add_linear_dim(
            base=(0, -offset), p1=(0, 0), p2=(hole.x, hole.y),
            dxfattribs={"layer": "DIMENSIONS"},
        ).render()
        msp.add_linear_dim(
            base=(-offset, 0), p1=(0, 0), p2=(hole.x, hole.y), angle=90,
            dxfattribs={"layer": "DIMENSIONS"},
        ).render()


def _add_notes(msp: Modelspace, spec: AssemblySpec) -> None:
    lines = ["NOTES:", f"1. GENERAL TOLERANCES PER {spec.general_tolerance}.",
             f"2. ALL DIMENSIONS IN {spec.units.upper()}.",
             f"3. BOARD THICKNESS {spec.board.thickness:g} {spec.units}."]
    lines += [f"{i}. {note}" for i, note in enumerate(spec.gdt_notes, start=4)]
    y = spec.board.height + 10.0 + TEXT_H * 1.8 * len(lines)
    for line in lines:
        msp.add_text(
            line, height=TEXT_H, dxfattribs={"layer": "TITLE_BLOCK"},
        ).set_placement((0, y))
        y -= TEXT_H * 1.8


def _draw_title_block(msp: Modelspace, spec: AssemblySpec) -> None:
    """ANSI-ish title block anchored to the bottom-right of the sheet area."""
    issued = spec.issue_date or date.today().isoformat()
    rows = [
        ("TITLE", spec.name),
        ("DRAWING TYPE", spec.drawing_type),
        ("SIM ID", spec.simulation_id),
        ("SOURCE", spec.source_system),
        ("AUTHOR", spec.author),
        ("DATE", issued),
        ("REV", spec.revision),
        ("GEN. TOL.", spec.general_tolerance),
        ("UNITS / SCALE", f"{spec.units} / 1:1"),
    ]
    _render_title_block(msp, rows, spec.board.width + DIM_OFFSET + 20.0, -DIM_OFFSET * 3)


def _render_title_block(
    msp: Modelspace, rows: list[tuple[str, str]], x0: float, y0: float
) -> None:
    block_w, row_h, cols = 120.0, 7.0, 2
    total_h = row_h * len(rows)
    msp.add_lwpolyline(
        [(x0, y0), (x0 + block_w, y0), (x0 + block_w, y0 + total_h), (x0, y0 + total_h)],
        close=True, dxfattribs={"layer": "TITLE_BLOCK"},
    )
    label_w = block_w / cols * 0.7
    for i, (label, value) in enumerate(rows):
        ry = y0 + total_h - row_h * (i + 1)
        if i:  # horizontal separator above every row but the top one
            msp.add_line((x0, ry + row_h), (x0 + block_w, ry + row_h),
                         dxfattribs={"layer": "TITLE_BLOCK"})
        msp.add_text(
            label, height=TEXT_H * 0.7, dxfattribs={"layer": "TITLE_BLOCK"},
        ).set_placement((x0 + 1.5, ry + row_h * 0.3))
        msp.add_text(
            value, height=TEXT_H * 0.8, dxfattribs={"layer": "TITLE_BLOCK"},
        ).set_placement((x0 + label_w, ry + row_h * 0.3))
    msp.add_line((x0 + label_w - 2.0, y0), (x0 + label_w - 2.0, y0 + total_h),
                 dxfattribs={"layer": "TITLE_BLOCK"})


# --- entry point -------------------------------------------------------------


def generate_drawing(spec: AssemblySpec, out_path: Path) -> Path:
    """Render the spec to a DXF drawing at `out_path`. Returns the path.

    Inspection balloons and critical-feature position dimensions are drawn
    only for `drawing_type == "INSPECTION"`; an assembly drawing carries
    geometry, overall dimensions, notes and the title block.
    """
    spec.validate()
    inspection = spec.drawing_type == "INSPECTION"
    doc = _setup_document()
    msp = doc.modelspace()

    _draw_outline(msp, spec)
    balloon_no = 0
    for hole in spec.holes:
        _draw_hole(msp, hole)
        if inspection and hole.critical:
            balloon_no += 1
            _draw_inspection_balloon(msp, hole, balloon_no)
    _add_overall_dimensions(msp, spec)
    if inspection:
        _add_critical_position_dims(msp, spec)
    _add_notes(msp, spec)
    _draw_title_block(msp, spec)

    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out_path)
    return out_path


# --- process sheet -----------------------------------------------------------


@dataclass
class ProcessStep:
    """One operation of the assembly process."""

    description: str
    station: str = ""
    tooling: str = ""
    inspection: bool = False
    no: int | None = None  # explicit op number; default: 10, 20, 30, …


@dataclass
class ProcessSheetSpec:
    name: str
    simulation_id: str
    steps: list[ProcessStep]
    revision: str = "A"
    author: str = "Buxter Drawing Agent"
    source_system: str = "RoboQC / RomeoFlexVision"
    issue_date: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProcessSheetSpec":
        try:
            steps = [
                ProcessStep(
                    description=str(s["description"]),
                    station=str(s.get("station", "")),
                    tooling=str(s.get("tooling", "")),
                    inspection=bool(s.get("inspection", False)),
                    no=int(s["no"]) if s.get("no") is not None else None,
                )
                for s in data["steps"]
            ]
            spec = cls(
                name=str(data["name"]),
                simulation_id=str(data["simulation_id"]),
                steps=steps,
                revision=str(data.get("revision", "A")),
                author=str(data.get("author", cls.author)),
                source_system=str(data.get("source_system", cls.source_system)),
                issue_date=str(data.get("issue_date", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SpecError(f"Invalid process sheet spec: {exc!r}") from exc
        spec.validate()
        return spec

    def validate(self) -> None:
        if not self.steps:
            raise SpecError("Process sheet must contain at least one step.")
        for step in self.steps:
            if not step.description.strip():
                raise SpecError("Process step description must not be empty.")


_SHEET_COLS: list[tuple[str, float]] = [
    ("OP", 15.0),
    ("DESCRIPTION", 130.0),
    ("STATION", 45.0),
    ("TOOLING", 45.0),
    ("INSP", 15.0),
]


def generate_process_sheet(sheet: ProcessSheetSpec, out_path: Path) -> Path:
    """Render the operation table + title block to a DXF at `out_path`."""
    sheet.validate()
    doc = _setup_document()
    msp = doc.modelspace()

    row_h = 8.0
    table_w = sum(width for _, width in _SHEET_COLS)
    rows: list[list[str]] = [[label for label, _ in _SHEET_COLS]]
    for index, step in enumerate(sheet.steps):
        op_no = step.no if step.no is not None else (index + 1) * 10
        rows.append([
            str(op_no),
            step.description,
            step.station,
            step.tooling,
            "X" if step.inspection else "",
        ])

    top = row_h * len(rows)
    msp.add_text(
        f"PROCESS SHEET — {sheet.name}", height=TEXT_H * 1.4,
        dxfattribs={"layer": "TITLE_BLOCK"},
    ).set_placement((0, top + 8.0))

    for row_no in range(len(rows) + 1):  # horizontal rules
        y = top - row_h * row_no
        msp.add_line((0, y), (table_w, y), dxfattribs={"layer": "TITLE_BLOCK"})
    x = 0.0
    for _, width in _SHEET_COLS:  # vertical rules
        msp.add_line((x, top), (x, 0), dxfattribs={"layer": "TITLE_BLOCK"})
        x += width
    msp.add_line((table_w, top), (table_w, 0), dxfattribs={"layer": "TITLE_BLOCK"})

    for row_no, row in enumerate(rows):
        y = top - row_h * (row_no + 1) + row_h * 0.3
        x = 0.0
        for (label, width), cell in zip(_SHEET_COLS, row):
            msp.add_text(
                cell, height=TEXT_H * 0.8, dxfattribs={"layer": "TITLE_BLOCK"},
            ).set_placement((x + 1.5, y))
            x += width

    issued = sheet.issue_date or date.today().isoformat()
    _render_title_block(
        msp,
        [
            ("TITLE", sheet.name),
            ("DRAWING TYPE", "PROCESS SHEET"),
            ("SIM ID", sheet.simulation_id),
            ("SOURCE", sheet.source_system),
            ("AUTHOR", sheet.author),
            ("DATE", issued),
            ("REV", sheet.revision),
        ],
        table_w + 20.0,
        0.0,
    )

    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out_path)
    return out_path


# --- annotation / validation of existing drawings ----------------------------


def _open_drawing(path: Path) -> Drawing:
    try:
        return ezdxf.readfile(path)
    except Exception as exc:  # noqa: BLE001 - ezdxf raises several types here
        raise DrawingError(
            f"cannot read {path.name!r}: {type(exc).__name__}: {exc}"
        ) from exc


def annotate_drawing(
    path: Path,
    gdt_notes: list[str],
    dimensions: list[dict[str, Any]],
) -> dict[str, int]:
    """Append GD&T notes and/or aligned dimensions to an existing DXF.

    Notes are stacked above the current drawing extents; dimensions are
    aligned dims between the given points at the given offset distance.
    """
    doc = _open_drawing(path)
    msp = doc.modelspace()
    for layer in ("DIMENSIONS", "TITLE_BLOCK"):
        if layer not in doc.layers:
            doc.layers.add(layer, **LAYERS[layer])

    if gdt_notes:
        from ezdxf import bbox as _bbox

        extents = _bbox.extents(msp, fast=True)
        y = (extents.extmax.y if extents.has_data else 0.0) + 6.0
        for note in gdt_notes:
            y += TEXT_H * 1.8
            msp.add_text(
                note, height=TEXT_H, dxfattribs={"layer": "TITLE_BLOCK"},
            ).set_placement((0, y))

    for dim in dimensions:
        msp.add_aligned_dim(
            p1=(float(dim["p1"]["x"]), float(dim["p1"]["y"])),
            p2=(float(dim["p2"]["x"]), float(dim["p2"]["y"])),
            distance=float(dim.get("offset", DIM_OFFSET)),
            dxfattribs={"layer": "DIMENSIONS"},
        ).render()

    doc.save()
    return {"gdt_notes_added": len(gdt_notes), "dimensions_added": len(dimensions)}


def validate_drawing(path: Path) -> dict[str, Any]:
    """Production-readiness report for a DXF. Never raises for check failures."""
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    try:
        doc = _open_drawing(path)
    except DrawingError as exc:
        check("readable", False, str(exc))
        return {"ok": False, "checks": checks}
    check("readable", True, f"DXF version {doc.dxfversion}")

    msp = doc.modelspace()
    present = {layer.dxf.name for layer in doc.layers}
    missing = sorted(set(LAYERS) - present)
    check("layers", not missing,
          "all standard layers present" if not missing else f"missing: {', '.join(missing)}")

    visible = [e for e in msp if e.dxf.layer == "VISIBLE"]
    check("geometry", bool(visible), f"{len(visible)} entities on VISIBLE")

    dims = msp.query("DIMENSION")
    check("dimensions", bool(dims), f"{len(dims)} dimension entities")

    tb_texts = " ".join(
        e.dxf.text for e in msp.query("TEXT") if e.dxf.layer == "TITLE_BLOCK"
    )
    for required in ("TITLE", "SIM ID", "REV"):
        check(f"title_block:{required}", required in tb_texts,
              "present" if required in tb_texts else "not found on TITLE_BLOCK layer")

    return {"ok": all(c["ok"] for c in checks), "checks": checks}


# --- sync support -------------------------------------------------------------


def spec_to_dict(spec: AssemblySpec) -> dict[str, Any]:
    """Canonical JSON-shaped form of a spec (sidecar format, diff input)."""
    return {
        "name": spec.name,
        "simulation_id": spec.simulation_id,
        "board": {
            "width": spec.board.width,
            "height": spec.board.height,
            "thickness": spec.board.thickness,
        },
        "holes": [
            {
                "x": hole.x,
                "y": hole.y,
                "diameter": hole.diameter,
                "tolerance": hole.tolerance,
                "critical": hole.critical,
                "label": hole.label,
            }
            for hole in spec.holes
        ],
        "drawing_type": spec.drawing_type,
        "revision": spec.revision,
        "author": spec.author,
        "source_system": spec.source_system,
        "general_tolerance": spec.general_tolerance,
        "units": spec.units,
        "gdt_notes": list(spec.gdt_notes),
        "issue_date": spec.issue_date,
    }


def diff_specs(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Stable, human-readable change list between two canonical spec dicts.

    Revision, author and dates are administrative and never counted as
    content changes.
    """
    changes: list[str] = []
    for key in ("name", "drawing_type", "general_tolerance", "units"):
        if old.get(key) != new.get(key):
            changes.append(f"{key}: {old.get(key)!r} -> {new.get(key)!r}")

    old_board, new_board = old.get("board", {}), new.get("board", {})
    for key in ("width", "height", "thickness"):
        if old_board.get(key) != new_board.get(key):
            changes.append(f"board.{key}: {old_board.get(key)} -> {new_board.get(key)}")

    def position(hole: dict[str, Any]) -> tuple[float, float]:
        return (round(float(hole["x"]), 3), round(float(hole["y"]), 3))

    old_holes = {position(h): h for h in old.get("holes", [])}
    new_holes = {position(h): h for h in new.get("holes", [])}
    for pos in sorted(old_holes.keys() - new_holes.keys()):
        changes.append(f"hole removed at ({pos[0]:g}, {pos[1]:g})")
    for pos in sorted(new_holes.keys() - old_holes.keys()):
        changes.append(f"hole added at ({pos[0]:g}, {pos[1]:g})")
    for pos in sorted(old_holes.keys() & new_holes.keys()):
        for key in ("diameter", "tolerance", "critical", "label"):
            if old_holes[pos].get(key) != new_holes[pos].get(key):
                changes.append(
                    f"hole at ({pos[0]:g}, {pos[1]:g}) {key}: "
                    f"{old_holes[pos].get(key)!r} -> {new_holes[pos].get(key)!r}"
                )

    if old.get("gdt_notes", []) != new.get("gdt_notes", []):
        changes.append("gdt_notes changed")
    return changes


def bump_revision(revision: str) -> str:
    """Next revision letter: A→B, …, Z→AA, AZ→BA."""
    if not revision or not revision.isalpha() or not revision.isupper():
        raise SpecError(f"Cannot bump non-letter revision {revision!r}.")
    digits = [ord(ch) - ord("A") for ch in revision]
    for i in range(len(digits) - 1, -1, -1):
        if digits[i] < 25:
            digits[i] += 1
            break
        digits[i] = 0
    else:
        digits.insert(0, 0)
    return "".join(chr(d + ord("A")) for d in digits)


__all__ = [
    "AssemblySpec",
    "BoardSpec",
    "DrawingError",
    "Hole",
    "LAYERS",
    "ProcessSheetSpec",
    "ProcessStep",
    "SpecError",
    "annotate_drawing",
    "bump_revision",
    "diff_specs",
    "generate_drawing",
    "generate_process_sheet",
    "spec_to_dict",
    "validate_drawing",
]
