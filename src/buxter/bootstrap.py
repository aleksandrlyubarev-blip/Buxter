import os
import shutil


class FreeCADNotFoundError(RuntimeError):
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
