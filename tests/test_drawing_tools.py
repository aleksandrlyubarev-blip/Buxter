import sys
from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "buxter_mcp_electronics_drawing"))

from mcp_server.drawing_generator import (  # noqa: E402
    AssemblySpec,
    BoardSpec,
    Hole,
    ProcessSheetSpec,
    SpecError,
    annotate_drawing,
    bump_revision,
    diff_specs,
    generate_drawing,
    generate_process_sheet,
    spec_to_dict,
    validate_drawing,
)


def _spec(drawing_type: str = "INSPECTION") -> AssemblySpec:
    return AssemblySpec(
        name="TEST BOARD",
        simulation_id="SIM-1",
        drawing_type=drawing_type,
        board=BoardSpec(width=60, height=40, thickness=1.6),
        holes=[
            Hole(x=5, y=5, diameter=3.2, label="M3"),
            Hole(x=30, y=20, diameter=2.0, tolerance="H7", critical=True),
        ],
        issue_date="2026-07-18",
    )


# --- assembly vs inspection ---------------------------------------------------

def test_assembly_drawing_has_no_inspection_marks(tmp_path: Path) -> None:
    out = generate_drawing(_spec("ASSEMBLY"), tmp_path / "asm.dxf")
    msp = ezdxf.readfile(out).modelspace()
    assert not [e for e in msp if e.dxf.layer == "INSPECTION"]
    assert len(msp.query("DIMENSION")) == 2  # overall W/H only


def test_inspection_drawing_has_balloons_and_critical_dims(tmp_path: Path) -> None:
    out = generate_drawing(_spec("INSPECTION"), tmp_path / "insp.dxf")
    msp = ezdxf.readfile(out).modelspace()
    assert [e for e in msp if e.dxf.layer == "INSPECTION"]
    assert len(msp.query("DIMENSION")) == 4  # overall + X/Y of the critical hole


# --- process sheet ------------------------------------------------------------

def test_process_sheet_roundtrip(tmp_path: Path) -> None:
    sheet = ProcessSheetSpec.from_dict({
        "name": "PI5 CARRIER ASSEMBLY",
        "simulation_id": "SIM-9",
        "issue_date": "2026-07-18",
        "steps": [
            {"description": "Place PCB on fixture", "station": "ST-1"},
            {"description": "Torque 4x M3", "tooling": "TQ-0.6", "inspection": True},
            {"no": 55, "description": "AOI scan", "inspection": True},
        ],
    })
    out = generate_process_sheet(sheet, tmp_path / "process.dxf")
    msp = ezdxf.readfile(out).modelspace()
    texts = [t.dxf.text for t in msp.query("TEXT")]
    joined = " ".join(texts)
    assert "PROCESS SHEET" in joined
    assert "10" in texts and "20" in texts and "55" in texts  # default + explicit op no
    assert "Torque 4x M3" in texts
    assert "SIM-9" in texts


def test_process_sheet_requires_steps() -> None:
    with pytest.raises(SpecError, match="at least one step"):
        ProcessSheetSpec.from_dict({"name": "X", "simulation_id": "S", "steps": []})


# --- annotate -----------------------------------------------------------------

def test_annotate_adds_notes_and_dimensions(tmp_path: Path) -> None:
    out = generate_drawing(_spec(), tmp_path / "a.dxf")
    before = len(ezdxf.readfile(out).modelspace().query("DIMENSION"))

    result = annotate_drawing(
        out,
        ["FLATNESS 0.1 OVER FIXTURE AREA"],
        [{"p1": {"x": 5, "y": 5}, "p2": {"x": 30, "y": 20}, "offset": 8}],
    )

    assert result == {"gdt_notes_added": 1, "dimensions_added": 1}
    msp = ezdxf.readfile(out).modelspace()
    assert len(msp.query("DIMENSION")) == before + 1
    assert any("FLATNESS 0.1" in t.dxf.text for t in msp.query("TEXT"))


# --- validate -----------------------------------------------------------------

def test_validate_passes_generated_drawing(tmp_path: Path) -> None:
    out = generate_drawing(_spec(), tmp_path / "ok.dxf")
    report = validate_drawing(out)
    assert report["ok"] is True
    assert all(check["ok"] for check in report["checks"])


def test_validate_flags_bare_dxf(tmp_path: Path) -> None:
    bare = tmp_path / "bare.dxf"
    ezdxf.new("R2010").saveas(bare)
    report = validate_drawing(bare)
    assert report["ok"] is False
    failed = {check["name"] for check in report["checks"] if not check["ok"]}
    assert {"layers", "geometry", "dimensions"} <= failed


def test_validate_reports_unreadable_file(tmp_path: Path) -> None:
    garbage = tmp_path / "garbage.dxf"
    garbage.write_text("this is not a dxf")
    report = validate_drawing(garbage)
    assert report["ok"] is False
    assert report["checks"][0]["name"] == "readable"
    assert report["checks"][0]["ok"] is False


# --- diff / revision ----------------------------------------------------------

def test_diff_specs_ignores_administrative_fields() -> None:
    old = spec_to_dict(_spec())
    new = dict(old, revision="C", issue_date="2030-01-01", author="someone")
    assert diff_specs(old, new) == []


def test_diff_specs_reports_content_changes() -> None:
    old = spec_to_dict(_spec())
    new_spec = _spec()
    new_spec.board.width = 65.0
    new_spec.holes[1].diameter = 2.5
    new_spec.holes.append(Hole(x=50, y=30, diameter=1.0))
    new = spec_to_dict(new_spec)

    changes = diff_specs(old, new)
    assert "board.width: 60 -> 65.0" in changes
    assert "hole added at (50, 30)" in changes
    assert any("diameter: 2.0 -> 2.5" in change for change in changes)


@pytest.mark.parametrize(("current", "expected"), [
    ("A", "B"), ("Y", "Z"), ("Z", "AA"), ("AZ", "BA"), ("ZZ", "AAA"),
])
def test_bump_revision(current: str, expected: str) -> None:
    assert bump_revision(current) == expected


def test_bump_revision_rejects_non_letters() -> None:
    with pytest.raises(SpecError):
        bump_revision("1")
