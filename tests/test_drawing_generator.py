import sys
from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "buxter_mcp_electronics_drawing"))

from mcp_server.drawing_generator import (  # noqa: E402
    AssemblySpec,
    BoardSpec,
    Hole,
    SpecError,
    generate_drawing,
)


def _spec(**overrides) -> AssemblySpec:
    base = dict(
        name="TEST BOARD",
        simulation_id="SIM-1",
        board=BoardSpec(width=60, height=40, thickness=1.6),
        holes=[
            Hole(x=5, y=5, diameter=3.2, label="M3"),
            Hole(x=30, y=20, diameter=2.0, tolerance="H7", critical=True),
        ],
        issue_date="2026-07-18",
    )
    base.update(overrides)
    return AssemblySpec(**base)


def test_generate_writes_readable_dxf(tmp_path: Path) -> None:
    out = generate_drawing(_spec(), tmp_path / "test.dxf")
    doc = ezdxf.readfile(out)
    msp = doc.modelspace()
    layers = {entity.dxf.layer for entity in msp}
    # geometry, centerlines, dims, one balloon, title block — all present
    assert {"VISIBLE", "CENTER", "DIMENSIONS", "INSPECTION", "TITLE_BLOCK"} <= layers
    # 2 holes + 1 inspection balloon
    assert len(msp.query("CIRCLE")) == 3
    # overall W/H + X/Y position dims for the one critical hole
    assert len(msp.query("DIMENSION")) == 4
    texts = " ".join(t.dxf.text for t in msp.query("TEXT"))
    assert "SIM-1" in texts
    assert "H7" in texts


def test_from_dict_roundtrip_and_defaults() -> None:
    spec = AssemblySpec.from_dict({
        "name": "X", "simulation_id": "S",
        "board": {"width": 10, "height": 10, "thickness": 1},
        "holes": [{"x": 1, "y": 1, "diameter": 0.5}],
    })
    assert spec.drawing_type == "INSPECTION"
    assert spec.holes[0].critical is False


def test_hole_outside_board_is_rejected() -> None:
    with pytest.raises(SpecError, match="outside the board"):
        AssemblySpec.from_dict({
            "name": "X", "simulation_id": "S",
            "board": {"width": 10, "height": 10, "thickness": 1},
            "holes": [{"x": 50, "y": 1, "diameter": 0.5}],
        })


def test_missing_field_is_a_spec_error() -> None:
    with pytest.raises(SpecError):
        AssemblySpec.from_dict({"name": "X", "board": {"width": 1}})
