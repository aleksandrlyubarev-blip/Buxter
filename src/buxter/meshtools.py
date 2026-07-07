"""Mesh comparison and assembly-fit tools.

Two jobs the retry/assembly loops need:

- ``diff_meshes`` — quantify how two exported meshes differ (symmetric
  Hausdorff distance from surface sampling). Lets the agent verify that a
  revision changed only what was asked: a 0.2 mm Hausdorff after "make the
  hole 0.3 mm bigger" is suspicious, a 15 mm one after "just thicken a wall"
  even more so.
- ``check_fit`` — do two parts interfere, and is the clearance between them
  at least the required gap? Interference via a manifold boolean
  intersection; clearance via bidirectional surface sampling.

Requires the ``validate`` extra (trimesh); ``check_fit`` additionally wants
``manifold3d`` for robust boolean intersection.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .validator import _load_trimesh, load_mesh


@dataclass
class DiffReport:
    hausdorff: float          # max of both directed max distances, mm
    mean_a_to_b: float        # mean sampled distance A→B, mm
    mean_b_to_a: float        # mean sampled distance B→A, mm
    volume_delta: float       # |V(a) − V(b)|, mm³ (0.0 if either is open)
    bbox_a: tuple[float, float, float]
    bbox_b: tuple[float, float, float]


@dataclass
class FitReport:
    interference_volume: float  # mm³ of overlap; 0.0 = no interference
    min_gap: float              # smallest sampled surface-to-surface gap, mm
    required_clearance: float

    @property
    def ok(self) -> bool:
        return self.interference_volume == 0.0 and self.min_gap >= self.required_clearance


def _directed_distances(trimesh_mod, source, target, samples: int, seed: int):
    points, _ = trimesh_mod.sample.sample_surface(source, samples, seed=seed)
    _, distances, _ = trimesh_mod.proximity.closest_point(target, points)
    return distances


def diff_meshes(
    path_a: Path,
    path_b: Path,
    *,
    samples: int = 2000,
    seed: int = 42,
) -> DiffReport:
    """Symmetric sampled Hausdorff distance between two mesh files."""
    trimesh_mod = _load_trimesh()
    mesh_a = load_mesh(path_a)
    mesh_b = load_mesh(path_b)

    a_to_b = _directed_distances(trimesh_mod, mesh_a, mesh_b, samples, seed)
    b_to_a = _directed_distances(trimesh_mod, mesh_b, mesh_a, samples, seed)

    volume_delta = 0.0
    if mesh_a.is_watertight and mesh_b.is_watertight:
        volume_delta = abs(float(mesh_a.volume) - float(mesh_b.volume))

    return DiffReport(
        hausdorff=float(max(a_to_b.max(), b_to_a.max())),
        mean_a_to_b=float(a_to_b.mean()),
        mean_b_to_a=float(b_to_a.mean()),
        volume_delta=volume_delta,
        bbox_a=tuple(float(v) for v in mesh_a.extents),
        bbox_b=tuple(float(v) for v in mesh_b.extents),
    )


def check_fit(
    path_a: Path,
    path_b: Path,
    *,
    clearance: float = 0.0,
    samples: int = 2000,
    seed: int = 42,
) -> FitReport:
    """Check two parts for interference and minimum clearance."""
    trimesh_mod = _load_trimesh()
    mesh_a = load_mesh(path_a)
    mesh_b = load_mesh(path_b)

    interference = 0.0
    try:
        overlap = mesh_a.intersection(mesh_b)
        if overlap is not None and len(getattr(overlap, "faces", ())) > 0:
            interference = abs(float(overlap.volume))
    except Exception as exc:
        raise RuntimeError(
            f"Boolean intersection failed ({exc}); install manifold3d: "
            "pip install manifold3d"
        ) from exc

    a_to_b = _directed_distances(trimesh_mod, mesh_a, mesh_b, samples, seed)
    b_to_a = _directed_distances(trimesh_mod, mesh_b, mesh_a, samples, seed)
    min_gap = 0.0 if interference > 0.0 else float(min(a_to_b.min(), b_to_a.min()))

    return FitReport(
        interference_volume=interference,
        min_gap=min_gap,
        required_clearance=clearance,
    )


__all__ = ["DiffReport", "FitReport", "check_fit", "diff_meshes"]
