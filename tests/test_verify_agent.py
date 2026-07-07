import json
from pathlib import Path

import pytest

trimesh = pytest.importorskip("trimesh")
pytest.importorskip("matplotlib")

from buxter.render import render_views
from buxter.verify_agent import verify_model


class _Block:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.requests: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return _Block(content=[_Block(type="text", text=json.dumps(self.payload))])


def _box_stl(tmp_path: Path) -> Path:
    path = tmp_path / "box.stl"
    trimesh.creation.box(extents=[20, 10, 5]).export(path)
    return path


def test_render_views_produces_four_pngs(tmp_path: Path) -> None:
    stl = _box_stl(tmp_path)
    views = render_views(stl, tmp_path / "views")
    assert len(views) == 4
    for png in views:
        assert png.exists()
        assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_verify_model_passes(settings, tmp_path: Path) -> None:
    stl = _box_stl(tmp_path)
    client = FakeClient({
        "questions": [
            {"question": "Is it a rectangular box?", "answer": "yes", "note": "clear"},
        ],
        "passed": True,
        "revision": None,
    })

    report = verify_model(stl, "a 20x10x5 box", settings=settings, client=client)

    assert report.passed is True
    assert report.questions[0].answer == "yes"
    assert report.revision is None
    # Prompt must contain the kernel metrics and 4 rendered images.
    content = client.requests[0]["messages"][0]["content"]
    assert "bbox" in content[0]["text"]
    assert sum(1 for block in content if block.get("type") == "image") == 4


def test_verify_model_fails_with_revision(settings, tmp_path: Path) -> None:
    stl = _box_stl(tmp_path)
    client = FakeClient({
        "questions": [
            {"question": "Are there 4 corner holes?", "answer": "no", "note": "none visible"},
        ],
        "passed": False,
        "revision": "Add four 3.2 mm through-holes at the corners, 5 mm inset.",
    })

    report = verify_model(stl, "plate with 4 corner holes", settings=settings, client=client)

    assert report.passed is False
    assert "3.2 mm" in report.revision


def test_verify_model_rejects_non_json(settings, tmp_path: Path) -> None:
    stl = _box_stl(tmp_path)

    class Chatty(FakeClient):
        def create(self, **kwargs):
            return _Block(content=[_Block(type="text", text="Sure! The model looks fine.")])

    with pytest.raises(ValueError, match="no JSON"):
        verify_model(stl, "a box", settings=settings, client=Chatty({}))
