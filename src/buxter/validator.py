"""Geometric printability validation for exported meshes.

This is the validation gate between the CAD layer and downstream consumers
(slicer, `buxter web` upload): a mesh that compiles and exports is not yet a
mesh that prints. Checks cover the failure modes LLM-generated CAD code is
known for — non-watertight topology, degenerate volume, wrong overall size,
walls thinner than the FDM process can produce.

Requires the ``validate`` extra: ``pip install 'buxter[validate]'``
(trimesh + rtree). Wall thickness is measured by ray casting from sampled
surface points along inward normals, so it reflects the actual exported
mesh, not the CAD intent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_BBOX_RE = re.compile(r"^\s*([\d.]+)\s*[x×]\s*([\d.]+)\s*[x×]\s*([\d.]+)\s*$")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class MeshReport:
    path: Path
    checks: list[Check] = field(default_factory=list)
    bbox: tuple[float, float, float] = (0.0, 0.0, 0.0)
    volume: float | None = None
    min_thickness: float | None = None

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks)


def parse_bbox(spec: str) -> tuple[float, float, float]:
    """Parse '60x40x8' / '60×40×8' into extents (mm)."""
    match = _BBOX_RE.match(spec)
    if not match:
        raise ValueError(f"Cannot parse bbox spec {spec!r}; expected 'XxYxZ' in mm.")
    return tuple(float(group) for group in match.groups())  # type: ignore[return-value]


def _load_trimesh():
    try:
        import trimesh
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "trimesh is not installed. Run: pip install 'buxter[validate]'"
        ) from exc
    return trimesh


def load_mesh(path: Path):
    """Load a mesh file with consistent errors (RuntimeError, never a traceback)."""
    trimesh = _load_trimesh()
    try:
        return trimesh.load(path, force="mesh")
    except Exception as exc:
        raise RuntimeError(f"Cannot load mesh {path}: {exc}") from exc


def validate_mesh(
    path: Path,
    *,
    min_wall: float | None = None,
    expect_bbox: tuple[float, float, float] | None = None,
    bbox_tol: float = 0.5,
    wall_samples: int = 300,
    seed: int = 42,
) -> MeshReport:
    """Run printability checks on an exported mesh file (STL/3MF/OBJ)."""
    trimesh = _load_trimesh()

    checks: list[Check] = []
    mesh = load_mesh(path)

    # Order matters: an empty mesh has bounds=None, so every geometric property
    # is read only behind the non_empty guard.
    non_empty = len(getattr(mesh, "faces", ())) > 0
    checks.append(
        Check("non-empty", non_empty, f"{len(mesh.faces) if non_empty else 0} triangles")
    )
    bbox = tuple(float(v) for v in mesh.extents) if non_empty else (0.0, 0.0, 0.0)

    watertight = bool(mesh.is_watertight) if non_empty else False
    checks.append(
        Check(
            "watertight",
            watertight,
            "closed manifold" if watertight else "open edges — slicer may misread it",
        )
    )
    winding = bool(mesh.is_winding_consistent) if non_empty else False
    checks.append(
        Check(
            "winding",
            winding,
            "normals consistent" if winding else "flipped normals present",
        )
    )

    volume: float | None = None
    if watertight:
        volume = float(mesh.volume)
        checks.append(
            Check("volume", volume > 0.0, f"{volume:.2f} mm³")
        )
    else:
        checks.append(
            Check("volume", False, "skipped: not watertight, volume unreliable")
        )

    if expect_bbox is not None:
        # Order-insensitive: exported orientation may differ from the spec.
        got = sorted(bbox)
        want = sorted(expect_bbox)
        deltas = [abs(g - w) for g, w in zip(got, want)]
        ok = all(delta <= bbox_tol for delta in deltas)
        checks.append(
            Check(
                "bbox",
                ok,
                f"got {bbox[0]:.2f}×{bbox[1]:.2f}×{bbox[2]:.2f} mm, "
                f"expected {expect_bbox[0]:g}×{expect_bbox[1]:g}×{expect_bbox[2]:g} "
                f"±{bbox_tol:g} mm",
            )
        )

    min_thickness: float | None = None
    if min_wall is not None:
        if watertight and non_empty:
            points, face_idx = trimesh.sample.sample_surface(
                mesh, wall_samples, seed=seed
            )
            thickness = trimesh.proximity.thickness(
                mesh, points, normals=mesh.face_normals[face_idx], method="ray"
            )
            min_thickness = float(thickness.min())
            checks.append(
                Check(
                    "min-wall",
                    min_thickness >= min_wall,
                    f"thinnest sampled wall {min_thickness:.2f} mm "
                    f"(required ≥ {min_wall:g} mm, {wall_samples} samples)",
                )
            )
        else:
            reason = "mesh is empty" if not non_empty else "mesh not watertight"
            checks.append(Check("min-wall", False, f"skipped: {reason}"))

    return MeshReport(
        path=path,
        checks=checks,
        bbox=bbox,  # type: ignore[arg-type]
        volume=volume,
        min_thickness=min_thickness,
    )


__all__ = ["Check", "MeshReport", "load_mesh", "parse_bbox", "validate_mesh"]
