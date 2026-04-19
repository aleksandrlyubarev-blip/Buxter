"""End-to-end smoke test: runs a hardcoded 20 mm cube through real freecadcmd.

Skips automatically when FreeCAD is not installed, so it is safe to run in any CI.
"""
import pytest

from buxter.bootstrap import FreeCADNotFoundError, locate_freecadcmd
from buxter.exporter import validate_artifacts
from buxter.runner import run_freecad_script

CUBE_SCRIPT = """
import os
import FreeCAD
import Part
import Mesh

doc = FreeCAD.newDocument("buxter")
solid = Part.makeBox(20.0, 20.0, 20.0)
obj = doc.addObject("Part::Feature", "Cube")
obj.Shape = solid
doc.recompute()

Part.export([obj], os.environ["BUXTER_STEP"])
Mesh.export([obj], os.environ["BUXTER_STL"])
"""


@pytest.fixture(scope="module")
def freecad_available() -> str:
    try:
        return locate_freecadcmd()
    except FreeCADNotFoundError:
        pytest.skip("freecadcmd not installed; install FreeCAD to run smoke test")


def test_cube_smoke(tmp_path, freecad_available):
    run = run_freecad_script(CUBE_SCRIPT, tmp_path / "out", timeout=90)
    assert run.ok, f"runner failed: exit={run.returncode}\n{run.stderr}"

    artifacts = validate_artifacts(run.stl_path, run.step_path)
    assert artifacts.stl.stat().st_size > 500

    trimesh = pytest.importorskip("trimesh")
    mesh = trimesh.load(artifacts.stl, force="mesh")
    extents = mesh.bounding_box.extents
    for axis in extents:
        assert 19.0 < axis < 21.0, f"cube side out of tolerance: {extents}"
