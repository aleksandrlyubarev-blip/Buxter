from pathlib import Path

import pytest

trimesh = pytest.importorskip("trimesh")

from buxter.validator import parse_bbox, validate_mesh


def _export_box(tmp_path: Path, extents, name="box.stl") -> Path:
    path = tmp_path / name
    trimesh.creation.box(extents=extents).export(path)
    return path


def _check(report, name):
    return next(check for check in report.checks if check.name == name)


def test_good_box_passes_all(tmp_path: Path) -> None:
    stl = _export_box(tmp_path, [20, 20, 20])
    report = validate_mesh(
        stl, min_wall=1.6, expect_bbox=(20, 20, 20), bbox_tol=0.5
    )
    assert report.ok
    assert report.volume == pytest.approx(8000.0, rel=1e-3)
    assert report.min_thickness == pytest.approx(20.0, rel=1e-3)
    assert sorted(report.bbox) == pytest.approx([20, 20, 20], rel=1e-6)


def test_thin_wall_fails(tmp_path: Path) -> None:
    stl = _export_box(tmp_path, [30, 30, 1.0])
    report = validate_mesh(stl, min_wall=1.6)
    assert not report.ok
    wall = _check(report, "min-wall")
    assert not wall.ok
    assert report.min_thickness == pytest.approx(1.0, rel=1e-3)


def test_bbox_mismatch_fails(tmp_path: Path) -> None:
    stl = _export_box(tmp_path, [20, 20, 20])
    report = validate_mesh(stl, expect_bbox=(60, 40, 8), bbox_tol=0.5)
    assert not report.ok
    assert not _check(report, "bbox").ok


def test_bbox_is_order_insensitive(tmp_path: Path) -> None:
    stl = _export_box(tmp_path, [8, 60, 40])
    report = validate_mesh(stl, expect_bbox=(60, 40, 8), bbox_tol=0.5)
    assert _check(report, "bbox").ok


def test_open_mesh_fails_watertight_and_skips_wall(tmp_path: Path) -> None:
    box = trimesh.creation.box(extents=[10, 10, 10])
    open_mesh = trimesh.Trimesh(
        vertices=box.vertices, faces=box.faces[:-2], process=False
    )
    path = tmp_path / "open.stl"
    open_mesh.export(path)

    report = validate_mesh(path, min_wall=1.6)
    assert not report.ok
    assert not _check(report, "watertight").ok
    wall = _check(report, "min-wall")
    assert not wall.ok
    assert "skipped" in wall.detail
    assert "skipped" in _check(report, "volume").detail


def test_parse_bbox_variants() -> None:
    assert parse_bbox("60x40x8") == (60.0, 40.0, 8.0)
    assert parse_bbox("60 × 40 × 8.5") == (60.0, 40.0, 8.5)
    with pytest.raises(ValueError):
        parse_bbox("60x40")
