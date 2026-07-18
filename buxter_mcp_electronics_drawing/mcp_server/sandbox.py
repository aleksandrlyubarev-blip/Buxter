"""Filesystem sandbox for the drawing MCP server.

Every file the server reads or writes lives in one output directory. Tool
arguments carry *bare file names only*; this module is the single choke
point that turns them into real paths. It rejects, deterministically:

- absolute paths (POSIX and Windows forms);
- any path separator or parent reference (``a/b``, ``..``, ``.``);
- names that escape the sandbox through a symlink planted inside it
  (the resolved real path must stay directly under the sandbox root).

No other module may build a path from tool input.
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath


class PathError(Exception):
    """A file name that violates the sandbox contract."""


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(
        self,
        filename: str,
        *,
        must_exist: bool = False,
        require_suffix: str | None = ".dxf",
    ) -> Path:
        """Validate a bare file name and return its sandboxed path."""
        if not isinstance(filename, str) or not filename.strip():
            raise PathError("empty file name.")
        name = filename.strip()
        if name.startswith(("/", "\\")) or PureWindowsPath(name).is_absolute():
            raise PathError(f"{name!r} is an absolute path; bare file names only.")
        if "/" in name or "\\" in name:
            raise PathError(f"{name!r} contains a path separator; bare file names only.")
        if name in (".", "..") or Path(name).name != name:
            raise PathError(f"{name!r} is not a bare file name.")
        if require_suffix and not name.lower().endswith(require_suffix):
            name += require_suffix

        candidate = self.root / name
        # resolve() follows symlinks: a link planted inside the sandbox that
        # points elsewhere resolves outside and is rejected here.
        resolved = candidate.resolve()
        if resolved.parent != self.root or resolved.name != name:
            raise PathError(f"{name!r} escapes the output sandbox (symlink or traversal).")

        if must_exist and not resolved.is_file():
            raise FileNotFoundError(f"{name!r} does not exist in the output sandbox.")
        return resolved


__all__ = ["PathError", "Sandbox"]
