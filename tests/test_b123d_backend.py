from pathlib import Path

import pytest

from buxter.backends import get_backend

build123d = pytest.importorskip("build123d")

SCRIPT = """
import os
from build123d import *

size = 12.0
with BuildPart() as part:
    Box(size, size, size)

export_stl(part.part, os.environ["BUXTER_STL"])
export_step(part.part, os.environ["BUXTER_STEP"])
"""

BROKEN_SCRIPT = "import os\nraise RuntimeError('boom')\n"


def test_build123d_backend_exports_stl_and_step(settings, tmp_out_dir: Path) -> None:
    backend = get_backend("build123d")
    artifacts = backend.run(SCRIPT, tmp_out_dir, settings)

    assert artifacts.ok
    assert artifacts.backend == "build123d"
    assert artifacts.stl_path.exists() and artifacts.stl_path.stat().st_size > 0
    assert artifacts.step_path is not None and artifacts.step_path.stat().st_size > 0
    assert artifacts.script_path.name == "_gen_b123d.py"


def test_build123d_backend_surfaces_script_errors(settings, tmp_out_dir: Path) -> None:
    backend = get_backend("build123d")
    artifacts = backend.run(BROKEN_SCRIPT, tmp_out_dir, settings)

    assert not artifacts.ok
    assert artifacts.returncode != 0
    assert "boom" in artifacts.stderr
    assert (tmp_out_dir / "run.log").exists()
