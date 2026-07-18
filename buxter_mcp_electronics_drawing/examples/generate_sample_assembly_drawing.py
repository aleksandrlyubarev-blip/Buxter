"""Generate a sample electronics-assembly inspection drawing.

Run from the subproject root:

    python examples/generate_sample_assembly_drawing.py

Output: sample_electronics_assembly_inspection.dxf — opens in FreeCAD,
AutoCAD, SolidWorks, KiCad, LibreCAD, …
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_server.drawing_generator import (  # noqa: E402
    AssemblySpec,
    BoardSpec,
    Hole,
    generate_drawing,
)

SAMPLE_SPEC = AssemblySpec(
    name="PI5 CARRIER BOARD — FIXTURE INSPECTION",
    simulation_id="SIM-2026-0718-004",
    drawing_type="INSPECTION",
    board=BoardSpec(width=160.0, height=100.0, thickness=1.6),
    holes=[
        # 4x M3 mounting holes, 5 mm inset from each corner
        Hole(x=5, y=5, diameter=3.2, tolerance="+0.1/-0.0", label="M3 MOUNTING"),
        Hole(x=155, y=5, diameter=3.2, tolerance="+0.1/-0.0", label="M3 MOUNTING"),
        Hole(x=155, y=95, diameter=3.2, tolerance="+0.1/-0.0", label="M3 MOUNTING"),
        Hole(x=5, y=95, diameter=3.2, tolerance="+0.1/-0.0", label="M3 MOUNTING"),
        # 2x alignment pins — inspection-critical
        Hole(x=30, y=50, diameter=2.0, tolerance="H7", critical=True,
             label="ALIGNMENT PIN"),
        Hole(x=130, y=50, diameter=2.0, tolerance="H7", critical=True,
             label="ALIGNMENT PIN"),
    ],
    general_tolerance="ISO 2768-mK",
    gdt_notes=[
        "ALIGNMENT PIN HOLES: POSITION TOL Ø0.05 (M) TO DATUM CORNER A.",
        "CRITICAL FEATURES (BALLOONED) PER IPC-A-610 CLASS 3 INSPECTION.",
        "DEBURR AND BREAK SHARP EDGES 0.2 MAX.",
    ],
    revision="A",
    issue_date="2026-07-18",  # pinned so the sample output is reproducible
)


if __name__ == "__main__":
    out = generate_drawing(
        SAMPLE_SPEC,
        Path(__file__).resolve().parents[1] / "sample_electronics_assembly_inspection.dxf",
    )
    print(f"DXF written: {out}")
