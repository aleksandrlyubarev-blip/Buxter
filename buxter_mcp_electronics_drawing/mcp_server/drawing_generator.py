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
    block_w, row_h, cols = 120.0, 7.0, 2
    x0 = spec.board.width + DIM_OFFSET + 20.0
    y0 = -DIM_OFFSET * 3

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
    """Render the spec to a DXF drawing at `out_path`. Returns the path."""
    spec.validate()
    doc = _setup_document()
    msp = doc.modelspace()

    _draw_outline(msp, spec)
    balloon_no = 0
    for hole in spec.holes:
        _draw_hole(msp, hole)
        if hole.critical:
            balloon_no += 1
            _draw_inspection_balloon(msp, hole, balloon_no)
    _add_overall_dimensions(msp, spec)
    _add_critical_position_dims(msp, spec)
    _add_notes(msp, spec)
    _draw_title_block(msp, spec)

    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out_path)
    return out_path


__all__ = [
    "AssemblySpec",
    "BoardSpec",
    "Hole",
    "LAYERS",
    "SpecError",
    "generate_drawing",
]
