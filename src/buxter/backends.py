from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from .config import Settings
from .runner import RunResult, run_freecad_script
from .fusion_runner import FusionRunResult, run_fusion_script

BackendName = Literal["freecad", "fusion"]


@dataclass
class BackendArtifacts:
    """Common shape returned by every backend so the CLI can stay backend-agnostic."""

    backend: BackendName
    script_path: Path
    stl_path: Path
    step_path: Path | None
    extra_path: Path | None
    returncode: int
    stdout: str
    stderr: str
    ok: bool
    note: str | None = None


class Backend(Protocol):
    name: BackendName

    def run(self, script: str, out_dir: Path, settings: Settings) -> BackendArtifacts: ...


class FreeCADBackend:
    name: BackendName = "freecad"

    def run(self, script: str, out_dir: Path, settings: Settings) -> BackendArtifacts:
        result: RunResult = run_freecad_script(
            script,
            out_dir,
            timeout=settings.run_timeout,
            freecad_cmd=settings.freecad_cmd,
        )
        return BackendArtifacts(
            backend=self.name,
            script_path=result.script_path,
            stl_path=result.stl_path,
            step_path=result.step_path if result.step_path.exists() else None,
            extra_path=None,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            ok=result.ok,
        )


class FusionBackend:
    name: BackendName = "fusion"

    def run(self, script: str, out_dir: Path, settings: Settings) -> BackendArtifacts:
        result: FusionRunResult = run_fusion_script(
            script,
            out_dir,
            timeout=settings.run_timeout,
            fusion_cmd=settings.fusion_cmd,
            exec_mode=settings.fusion_exec_mode,
            emit_f3d=settings.fusion_emit_f3d,
        )
        note = None
        if result.exec_mode == "dryrun":
            note = (
                "Fusion 360 backend ran in dryrun mode — script emitted, no execution. "
                "Set FUSION_EXEC_MODE=subprocess to invoke Fusion automatically."
            )
        return BackendArtifacts(
            backend=self.name,
            script_path=result.script_path,
            stl_path=result.stl_path,
            step_path=result.step_path if result.step_path.exists() else None,
            extra_path=result.f3d_path if result.f3d_path and result.f3d_path.exists() else None,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            ok=result.ok,
            note=note,
        )


_BACKENDS: dict[BackendName, Backend] = {
    "freecad": FreeCADBackend(),
    "fusion": FusionBackend(),
}


def get_backend(name: BackendName) -> Backend:
    try:
        return _BACKENDS[name]
    except KeyError as exc:
        valid = ", ".join(sorted(_BACKENDS))
        raise ValueError(f"Unknown backend '{name}'. Valid: {valid}") from exc


__all__ = ["Backend", "BackendArtifacts", "BackendName", "get_backend"]
