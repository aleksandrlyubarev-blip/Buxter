"""Headless mesh → PNG rendering for the vision self-check loop.

Renders four canonical views (azimuth 0/90/180/270°) of an exported mesh so a
multimodal model can compare the actual geometry against the design intent —
the CADCodeVerify pattern. Two strategies:

- `f3d` binary if available (best quality, also reads STEP);
- matplotlib fallback (pure pip, works on any headless box).

Requires the ``verify`` extra for the fallback: trimesh + matplotlib.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .validator import load_mesh

_AZIMUTHS = (45, 135, 225, 315)
_ELEVATION = 25.0


def render_views(
    mesh_path: Path,
    out_dir: Path,
    *,
    f3d_cmd: str | None = None,
    size: int = 640,
) -> list[Path]:
    """Render the canonical views to PNG files, returning their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    f3d = f3d_cmd or shutil.which("f3d")
    if f3d:
        return _render_f3d(f3d, mesh_path, out_dir, size)
    return _render_matplotlib(mesh_path, out_dir, size)


def _render_f3d(f3d: str, mesh_path: Path, out_dir: Path, size: int) -> list[Path]:
    paths: list[Path] = []
    for azimuth in _AZIMUTHS:
        png = out_dir / f"view_{azimuth:03d}.png"
        subprocess.run(
            [
                f3d, str(mesh_path),
                "--output", str(png),
                f"--resolution={size},{size}",
                f"--camera-azimuth-angle={azimuth}",
                f"--camera-elevation-angle={_ELEVATION}",
                "--axis", "--grid",
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        paths.append(png)
    return paths


def _render_matplotlib(mesh_path: Path, out_dir: Path, size: int) -> list[Path]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "matplotlib is not installed and no f3d binary was found. "
            "Run: pip install 'buxter[verify]'"
        ) from exc

    mesh = load_mesh(mesh_path)
    if len(getattr(mesh, "faces", ())) == 0:
        raise RuntimeError(f"{mesh_path} has no triangles to render.")

    triangles = mesh.triangles
    # Simple lambert shading from a fixed light — enough depth cue for a VLM.
    light = np.array([0.4, 0.3, 0.85])
    light = light / np.linalg.norm(light)
    shade = 0.25 + 0.75 * np.clip(mesh.face_normals @ light, 0.0, 1.0)
    colors = np.column_stack([shade * 0.55, shade * 0.7, shade * 0.9, np.ones_like(shade)])

    lo, hi = mesh.bounds
    center = (lo + hi) / 2.0
    radius = float(max(hi - lo)) / 2.0 or 1.0

    paths: list[Path] = []
    dpi = 100
    for azimuth in _AZIMUTHS:
        fig = plt.figure(figsize=(size / dpi, size / dpi), dpi=dpi)
        ax = fig.add_subplot(111, projection="3d")
        collection = Poly3DCollection(triangles, facecolors=colors, edgecolors="none")
        ax.add_collection3d(collection)
        for axis, mid in zip("xyz", center):
            getattr(ax, f"set_{axis}lim")(mid - radius, mid + radius)
        ax.view_init(elev=_ELEVATION, azim=azimuth)
        ax.set_box_aspect((1, 1, 1))
        ax.set_xlabel("X mm"), ax.set_ylabel("Y mm"), ax.set_zlabel("Z mm")
        ax.set_title(f"azimuth {azimuth}°")
        png = out_dir / f"view_{azimuth:03d}.png"
        fig.savefig(png, bbox_inches="tight")
        plt.close(fig)
        paths.append(png)
    return paths


__all__ = ["render_views"]
