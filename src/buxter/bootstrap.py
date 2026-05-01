import os
import platform
import shutil
from pathlib import Path


class FreeCADNotFoundError(RuntimeError):
    pass


class FusionNotFoundError(RuntimeError):
    pass


def locate_freecadcmd(explicit: str | None = None) -> str:
    for candidate in (explicit, os.environ.get("FREECAD_CMD")):
        if candidate:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
            raise FreeCADNotFoundError(
                f"FREECAD_CMD points to '{candidate}', which is not an executable file."
            )
    for name in ("freecadcmd", "FreeCADCmd"):
        found = shutil.which(name)
        if found:
            return found
    raise FreeCADNotFoundError(
        "freecadcmd not found. Install FreeCAD or set FREECAD_CMD to the binary path."
    )


_FUSION_DEFAULT_PATHS: dict[str, tuple[str, ...]] = {
    "Darwin": (
        "/Applications/Autodesk Fusion 360.app/Contents/MacOS/Autodesk Fusion 360",
        "/Applications/Autodesk Fusion.app/Contents/MacOS/Autodesk Fusion",
    ),
    "Windows": (
        r"C:\Users\Public\Autodesk\webdeploy\production\Fusion360.exe",
        r"C:\Program Files\Autodesk\webdeploy\production\Fusion360.exe",
    ),
    "Linux": (),
}


def locate_fusion(explicit: str | None = None) -> str:
    """Locate the Autodesk Fusion 360 executable.

    Resolution order: explicit argument, FUSION_CMD env, platform default paths,
    PATH lookup. Raises FusionNotFoundError if nothing matches.
    """
    for candidate in (explicit, os.environ.get("FUSION_CMD")):
        if candidate:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
            raise FusionNotFoundError(
                f"FUSION_CMD points to '{candidate}', which is not an executable file."
            )

    for path in _FUSION_DEFAULT_PATHS.get(platform.system(), ()):
        if Path(path).is_file():
            return path

    for name in ("Fusion360", "fusion360"):
        found = shutil.which(name)
        if found:
            return found

    raise FusionNotFoundError(
        "Autodesk Fusion 360 executable not found. "
        "Set FUSION_CMD to the binary path, or use FUSION_EXEC_MODE=dryrun "
        "to only emit the script without running it."
    )
