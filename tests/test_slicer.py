import shutil
from pathlib import Path

import pytest

from buxter.slicer import parse_print_time


def test_parse_print_time_variants() -> None:
    assert parse_print_time("47m 25s") == 47 * 60 + 25
    assert parse_print_time("1h 2m 3s") == 3723
    assert parse_print_time("2d 1h") == 2 * 86_400 + 3_600
    assert parse_print_time("") == 0


@pytest.mark.skipif(
    shutil.which("prusa-slicer") is None, reason="prusa-slicer not installed"
)
def test_slice_mesh_produces_gcode_and_metrics(tmp_path: Path) -> None:
    trimesh = pytest.importorskip("trimesh")
    from buxter.slicer import slice_mesh

    stl = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(stl)

    report = slice_mesh(stl, tmp_path / "cube.gcode")

    assert report.gcode_path.exists()
    assert report.print_time_seconds > 0
    assert report.filament_mm > 0


@pytest.mark.skipif(
    shutil.which("prusa-slicer") is None, reason="prusa-slicer not installed"
)
def test_slice_mesh_fails_on_broken_input(tmp_path: Path) -> None:
    from buxter.slicer import slice_mesh

    bad = tmp_path / "bad.stl"
    bad.write_bytes(b"this is not an stl")
    with pytest.raises(RuntimeError):
        slice_mesh(bad, tmp_path / "bad.gcode")
