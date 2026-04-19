import pytest

from buxter.exporter import ExportError, validate_artifacts


def test_missing_stl_raises(tmp_path):
    with pytest.raises(ExportError):
        validate_artifacts(tmp_path / "none.stl", tmp_path / "none.step")


def test_small_stl_raises(tmp_path):
    stl = tmp_path / "x.stl"
    stl.write_bytes(b"x" * 10)
    with pytest.raises(ExportError):
        validate_artifacts(stl, tmp_path / "none.step")


def test_step_optional(tmp_path):
    stl = tmp_path / "x.stl"
    stl.write_bytes(b"x" * 500)
    step = tmp_path / "x.step"

    a = validate_artifacts(stl, step)
    assert a.stl == stl
    assert a.step is None

    step.write_bytes(b"ISO-10303-21;")
    a = validate_artifacts(stl, step)
    assert a.step == step
