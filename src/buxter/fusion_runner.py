import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .bootstrap import FusionNotFoundError, locate_fusion

FusionExecMode = Literal["dryrun", "subprocess"]


@dataclass
class FusionRunResult:
    returncode: int
    stdout: str
    stderr: str
    script_path: Path
    stl_path: Path
    step_path: Path
    f3d_path: Path | None
    exec_mode: FusionExecMode

    @property
    def ok(self) -> bool:
        if self.exec_mode == "dryrun":
            # Dryrun never produces artifacts; success means the script was emitted.
            return self.script_path.exists()
        return self.returncode == 0 and self.stl_path.exists()


def run_fusion_script(
    script: str,
    out_dir: Path,
    *,
    timeout: int = 300,
    fusion_cmd: str | None = None,
    exec_mode: FusionExecMode = "dryrun",
    emit_f3d: bool = False,
    stl_name: str = "out.stl",
    step_name: str = "out.step",
    f3d_name: str = "out.f3d",
    script_name: str = "_gen_fusion.py",
) -> FusionRunResult:
    """Write the generated Fusion 360 script and (optionally) execute it.

    Fusion 360 is a GUI application without a true headless mode. Two
    execution strategies are supported:

    - ``dryrun`` (default): just persist the script to ``out_dir`` so the user
      can run it manually inside Fusion (Tools → Add-Ins → Scripts) or via the
      MCP connector. No subprocess is started.
    - ``subprocess``: invoke the Fusion 360 binary with ``-ExecuteScript``.
      Requires ``FUSION_CMD`` to be set or the binary to be discoverable.
      Note that the foreground GUI must be allowed to start; use this only on
      a workstation, not in CI.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    script_path = out_dir / script_name
    stl_path = (out_dir / stl_name).resolve()
    step_path = (out_dir / step_name).resolve()
    f3d_path = (out_dir / f3d_name).resolve() if emit_f3d else None

    script_path.write_text(script, encoding="utf-8")

    if exec_mode == "dryrun":
        (out_dir / "run.log").write_text(
            "exec_mode=dryrun — script emitted, not executed.\n"
            f"Run manually in Fusion 360: Utilities → Add-Ins → Scripts → {script_path}\n",
            encoding="utf-8",
        )
        return FusionRunResult(
            returncode=0,
            stdout="",
            stderr="",
            script_path=script_path,
            stl_path=stl_path,
            step_path=step_path,
            f3d_path=f3d_path,
            exec_mode=exec_mode,
        )

    for stale in (stl_path, step_path, f3d_path):
        if stale and stale.exists():
            stale.unlink()

    binary = locate_fusion(fusion_cmd)
    env = {
        **os.environ,
        "BUXTER_STL": str(stl_path),
        "BUXTER_STEP": str(step_path),
    }
    if f3d_path is not None:
        env["BUXTER_F3D"] = str(f3d_path)

    try:
        proc = subprocess.run(
            [binary, f"-ExecuteScript={script_path}"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        (out_dir / "run.log").write_text(
            f"TIMEOUT after {timeout}s\n"
            f"stdout:\n{exc.stdout or ''}\nstderr:\n{exc.stderr or ''}",
            encoding="utf-8",
        )
        return FusionRunResult(
            returncode=124,
            stdout=exc.stdout or "",
            stderr=exc.stderr or f"Timed out after {timeout}s",
            script_path=script_path,
            stl_path=stl_path,
            step_path=step_path,
            f3d_path=f3d_path,
            exec_mode=exec_mode,
        )

    (out_dir / "run.log").write_text(
        f"exit={proc.returncode}\n\nstdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}",
        encoding="utf-8",
    )
    return FusionRunResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        script_path=script_path,
        stl_path=stl_path,
        step_path=step_path,
        f3d_path=f3d_path,
        exec_mode=exec_mode,
    )


__all__ = [
    "FusionExecMode",
    "FusionNotFoundError",
    "FusionRunResult",
    "run_fusion_script",
]
