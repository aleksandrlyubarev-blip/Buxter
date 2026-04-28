from dataclasses import dataclass
from pathlib import Path

MIN_STL_BYTES = 100


class ExportError(RuntimeError):
    pass


@dataclass
class Artifacts:
    stl: Path
    step: Path | None


def validate_artifacts(stl: Path, step: Path) -> Artifacts:
    if not stl.exists():
        raise ExportError(f"STL was not written: {stl}")
    size = stl.stat().st_size
    if size < MIN_STL_BYTES:
        raise ExportError(
            f"STL is suspiciously small ({size} bytes) — model likely empty: {stl}"
        )
    step_out: Path | None = step if step.exists() and step.stat().st_size > 0 else None
    return Artifacts(stl=stl, step=step_out)
