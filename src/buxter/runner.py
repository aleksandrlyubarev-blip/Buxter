import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .bootstrap import locate_freecadcmd


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    script_path: Path
    stl_path: Path
    step_path: Path

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.stl_path.exists()


def run_freecad_script(
    script: str,
    out_dir: Path,
    *,
    timeout: int = 120,
    freecad_cmd: str | None = None,
    stl_name: str = "out.stl",
    step_name: str = "out.step",
    script_name: str = "_gen.py",
) -> RunResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    script_path = out_dir / script_name
    stl_path = (out_dir / stl_name).resolve()
    step_path = (out_dir / step_name).resolve()

    script_path.write_text(script, encoding="utf-8")
    for stale in (stl_path, step_path):
        if stale.exists():
            stale.unlink()

    binary = locate_freecadcmd(freecad_cmd)
    env = {
        **os.environ,
        "BUXTER_STL": str(stl_path),
        "BUXTER_STEP": str(step_path),
    }

    try:
        proc = subprocess.run(
            [binary, "-c", str(script_path)],
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
