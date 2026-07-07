"""Runner for build123d scripts — the fully pip-installable headless backend.

Unlike FreeCAD (external binary) and Fusion 360 (GUI), build123d runs in a
plain Python subprocess: `pip install buxter[build123d]` is the whole setup,
which makes this the CI-friendly path. The generated script reads BUXTER_STL
and BUXTER_STEP from the environment, exactly like the FreeCAD contract.
"""

import os
import subprocess
import sys
from pathlib import Path

from .runner import RunResult


def run_build123d_script(
    script: str,
    out_dir: Path,
    *,
    timeout: int = 120,
    stl_name: str = "out.stl",
    step_name: str = "out.step",
    script_name: str = "_gen_b123d.py",
) -> RunResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    script_path = out_dir / script_name
    stl_path = (out_dir / stl_name).resolve()
    step_path = (out_dir / step_name).resolve()

    script_path.write_text(script, encoding="utf-8")
    for stale in (stl_path, step_path):
        if stale.exists():
            stale.unlink()

    env = {
        **os.environ,
        "BUXTER_STL": str(stl_path),
        "BUXTER_STEP": str(step_path),
    }

    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        (out_dir / "run.log").write_text(
            f"TIMEOUT after {timeout}s\nstdout:\n{exc.stdout or ''}\nstderr:\n{exc.stderr or ''}",
            encoding="utf-8",
        )
        return RunResult(
            returncode=124,
            stdout=exc.stdout or "",
            stderr=exc.stderr or f"Timed out after {timeout}s",
            script_path=script_path,
            stl_path=stl_path,
            step_path=step_path,
        )

    (out_dir / "run.log").write_text(
        f"exit={proc.returncode}\n\nstdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}",
        encoding="utf-8",
    )
    return RunResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        script_path=script_path,
        stl_path=stl_path,
        step_path=step_path,
    )
