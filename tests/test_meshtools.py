from pathlib import Path

import pytest

trimesh = pytest.importorskip("trimesh")
pytest.importorskip("manifold3d")

from buxter.meshtools import check_fit, diff_meshes


def _export(tmp_path: Path, name: str, extents, translate=None) -> Path:
    mesh = trimesh.creation.box(extents=extents)
    if translate is not None:
        mesh.apply_translation(translate)
    path = tmp_path / name
    mesh.export(path)
    return path


def test_diff_identical_meshes_is_zero(tmp_path: Path) -> None:
    a = _export(tmp_path, "a.stl", [10, 10, 10])
    b = _export(tmp_path, "b.stl", [10, 10, 10])
    report = diff_meshes(a, b, samples=500)
    assert report.hausdorff == pytest.approx(0.0, abs=1e-6)
    assert report.volume_delta == pytest.approx(0.0, abs=1e-6)


def test_diff_detects_size_change(tmp_path: Path) -> None:
    a = _export(tmp_path, "a.stl", [10, 10, 10])
    b = _export(tmp_path, "b.stl", [10, 10, 14])  # 2 mm taller on each side
    report = diff_meshes(a, b, samples=500)
    assert report.hausdorff == pytest.approx(2.0, abs=0.3)
    assert report.volume_delta == pytest.approx(400.0, rel=0.01)


def test_fit_detects_interference(tmp_path: Path) -> None:
    a = _export(tmp_path, "a.stl", [10, 10, 10])
    b = _export(tmp_path, "b.stl", [10, 10, 10], translate=[5, 0, 0])  # 5 mm overlap
    report = check_fit(a, b, clearance=0.3, samples=500)
    assert report.interference_volume == pytest.approx(500.0, rel=0.02)
    assert not report.ok


def test_fit_passes_with_gap(tmp_path: Path) -> None:
    a = _export(tmp_path, "a.stl", [10, 10, 10])
    b = _export(tmp_path, "b.stl", [10, 10, 10], translate=[12, 0, 0])  # 2 mm gap
    report = check_fit(a, b, clearance=0.3, samples=500)
    assert report.interference_volume == 0.0
    assert report.min_gap == pytest.approx(2.0, abs=0.2)
    assert report.ok


def test_fit_fails_on_tight_gap(tmp_path: Path) -> None:
    a = _export(tmp_path, "a.stl", [10, 10, 10])
    b = _export(tmp_path, "b.stl", [10, 10, 10], translate=[10.1, 0, 0])  # 0.1 mm gap
    report = check_fit(a, b, clearance=0.3, samples=500)
    assert report.interference_volume == 0.0
    assert not report.ok
