import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "buxter_mcp_electronics_drawing"))

from mcp_server.sandbox import PathError, Sandbox  # noqa: E402


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path / "out")


def test_bare_name_resolves_inside_root(sandbox: Sandbox) -> None:
    path = sandbox.resolve("part.dxf")
    assert path.parent == sandbox.root
    assert path.name == "part.dxf"


def test_suffix_is_appended(sandbox: Sandbox) -> None:
    assert sandbox.resolve("part").name == "part.dxf"
    assert sandbox.resolve("part.spec.json", require_suffix=None).name == "part.spec.json"


@pytest.mark.parametrize("bad", [
    "", "  ", ".", "..", "/etc/passwd", "\\\\host\\share\\x.dxf",
    "C:\\x.dxf", "a/b.dxf", "a\\b.dxf", "../escape.dxf", "..\\escape.dxf",
])
def test_bad_names_are_refused(sandbox: Sandbox, bad: str) -> None:
    with pytest.raises(PathError):
        sandbox.resolve(bad)


def test_symlink_escape_is_refused(sandbox: Sandbox, tmp_path: Path) -> None:
    secret = tmp_path / "secret.dxf"
    secret.write_text("outside")
    link = sandbox.root / "evil.dxf"
    link.symlink_to(secret)
    with pytest.raises(PathError, match="escapes"):
        sandbox.resolve("evil.dxf")


def test_symlink_inside_root_is_allowed(sandbox: Sandbox) -> None:
    real = sandbox.root / "real.dxf"
    real.write_text("x")
    # a link that stays inside the sandbox but under a different name still
    # resolves to a different bare name → refused (names must be literal)
    (sandbox.root / "alias.dxf").symlink_to(real)
    with pytest.raises(PathError):
        sandbox.resolve("alias.dxf")
    assert sandbox.resolve("real.dxf", must_exist=True) == real


def test_must_exist(sandbox: Sandbox) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        sandbox.resolve("missing.dxf", must_exist=True)


def test_error_messages_are_deterministic(sandbox: Sandbox) -> None:
    def message(name: str) -> str:
        with pytest.raises(PathError) as excinfo:
            sandbox.resolve(name)
        return str(excinfo.value)

    assert message("../x.dxf") == message("../x.dxf")
    assert message("/abs/x.dxf") == message("/abs/x.dxf")
