import os
import stat

import pytest

from buxter.bootstrap import FreeCADNotFoundError, locate_freecadcmd


def test_explicit_path_used_when_executable(tmp_path, monkeypatch):
    fake = tmp_path / "freecadcmd"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.delenv("FREECAD_CMD", raising=False)

    assert locate_freecadcmd(str(fake)) == str(fake)


def test_explicit_path_rejected_when_not_executable(tmp_path, monkeypatch):
    bogus = tmp_path / "nope"
    bogus.write_text("")
    monkeypatch.delenv("FREECAD_CMD", raising=False)
    with pytest.raises(FreeCADNotFoundError):
        locate_freecadcmd(str(bogus))


def test_env_fallback(tmp_path, monkeypatch):
    fake = tmp_path / "FreeCADCmd"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("FREECAD_CMD", str(fake))

    assert locate_freecadcmd() == str(fake)


def test_raises_when_missing(monkeypatch):
    monkeypatch.delenv("FREECAD_CMD", raising=False)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(FreeCADNotFoundError):
        locate_freecadcmd()
