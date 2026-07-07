"""PrusaSlicer CLI wrapper — the final printability gate.

"It slices without errors" is itself a strong printability test: the slicer
sees the mesh the way the printer will. The G-code footer additionally gives
print time and filament usage for free, so the agent can report cost metrics
without printing anything.

G-code is only ever produced by the slicer, never by an LLM — that boundary
stays.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_TIME_RE = re.compile(r"; estimated printing time \(normal mode\) = (.+)")
_FILAMENT_MM_RE = re.compile(r"; filament used \[mm\] = ([\d.]+)")
_FILAMENT_CM3_RE = re.compile(r"; filament used \[cm3\] = ([\d.]+)")
_TIME_PART_RE = re.compile(r"(\d+)([dhms])")

_TIME_UNIT_SECONDS = {"d": 86_400, "h": 3_600, "m": 60, "s": 1}

# Sane FDM defaults used only when no profile is supplied.
_DEFAULT_ARGS = [
    "--layer-height", "0.2",
    "--nozzle-diameter", "0.4",
    "--filament-diameter", "1.75",
    "--temperature", "210",
    "--bed-temperature", "60",
]


@dataclass
class SliceReport:
    gcode_path: Path
    print_time: str            # as reported, e.g. "47m 25s"
    print_time_seconds: int
    filament_mm: float
    filament_cm3: float
    stdout: str


def parse_print_time(text: str) -> int:
    """'1h 2m 3s' → seconds."""
    return sum(
        int(value) * _TIME_UNIT_SECONDS[unit]
        for value, unit in _TIME_PART_RE.findall(text)
    )


def locate_slicer(explicit: str | None = None) -> str:
    for candidate in filter(None, (explicit, "prusa-slicer", "prusa-slicer-console", "PrusaSlicer")):
        found = shutil.which(candidate)
        if found:
            return found
    raise RuntimeError(
        "PrusaSlicer not found. Install it (apt install prusa-slicer) or set "
        "PRUSA_SLICER_CMD to the binary path."
    )


def slice_mesh(
    mesh_path: Path,
    gcode_path: Path | None = None,
    *,
    profile: Path | None = None,
    slicer_cmd: str | None = None,
    timeout: int = 300,
) -> SliceReport:
    """Slice a mesh headless and parse the metric footer. Raises RuntimeError on failure."""
    binary = locate_slicer(slicer_cmd)
    gcode = (gcode_path or mesh_path.with_suffix(".gcode")).resolve()

    cmd = [binary, "--export-gcode", "-o", str(gcode)]
    if profile is not None:
        cmd += ["--load", str(profile)]
    else:
        cmd += _DEFAULT_ARGS
    cmd.append(str(mesh_path))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Slicing timed out after {timeout}s") from exc
    if proc.returncode != 0 or not gcode.exists():
        tail = (proc.stderr or proc.stdout)[-1500:]
        raise RuntimeError(f"PrusaSlicer failed (exit {proc.returncode}):\n{tail}")

    # The metric comments sit above PrusaSlicer's long config dump, so scan
    # the whole file rather than a fixed-size tail.
    footer = gcode.read_text(encoding="utf-8", errors="replace")
    time_match = _TIME_RE.search(footer)
    mm_match = _FILAMENT_MM_RE.search(footer)
    cm3_match = _FILAMENT_CM3_RE.search(footer)

    time_text = time_match.group(1).strip() if time_match else ""
    return SliceReport(
        gcode_path=gcode,
        print_time=time_text,
        print_time_seconds=parse_print_time(time_text),
        filament_mm=float(mm_match.group(1)) if mm_match else 0.0,
        filament_cm3=float(cm3_match.group(1)) if cm3_match else 0.0,
        stdout=proc.stdout,
    )


__all__ = ["SliceReport", "locate_slicer", "parse_print_time", "slice_mesh"]
