from pathlib import Path

from buxter.bim_agent import BimReport, DocSession, run_bim_task
from buxter.pdf_index import DrawingSetIndex, PageText, TextSpan


class _Block:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


def _tool_use(tool: str, tool_id: str, **tool_input) -> _Block:
    return _Block(type="tool_use", id=tool_id, name=tool, input=tool_input)


class FakeClient:
    """Mimics `client.messages.create(...)` with a scripted response queue."""

    def __init__(self, responses) -> None:
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return _Block(content=self._responses.pop(0))


def _span(text: str, x: float, y: float) -> TextSpan:
    return TextSpan(text=text, x0=x, top=y, x1=x + 30, bottom=y + 10)


def _session(tmp_path: Path) -> DocSession:
    index = DrawingSetIndex()
    index.pages = [
        PageText(
            file="set.pdf", pdf_page=1, width=1000, height=700,
            spans=[_span("F1", 100, 100), _span("F1", 400, 400), _span("S-101", 920, 660)],
            raw_text="FOUNDATION PLAN F1 F1 S-101 " + "x" * 40,
        )
    ]
    from buxter.pdf_index import detect_sheet_metadata

    index.sheets = [detect_sheet_metadata(index.pages[0])]
    return DocSession([], tmp_path / "bim", index=index)


def test_happy_path_finish(settings, tmp_path: Path) -> None:
    session = _session(tmp_path)
    client = FakeClient([
        [_tool_use("count_tag", "t1", tag="F1")],
        [_tool_use(
            "finish", "t2",
            answer="2 шт F1", reliability="High",
            sources=["Лист S-101, PDF стр. 1"], unresolved=[],
        )],
    ])

    report = run_bim_task(
        "Сколько фундаментов F1?", settings=settings, session=session, client=client,
    )

    assert isinstance(report, BimReport)
    assert report.success is True
    assert report.reliability == "High"
    assert report.sources == ["Лист S-101, PDF стр. 1"]
    assert [step.tool for step in report.steps] == ["count_tag", "finish"]
    # The tag count made it into the model-visible tool result.
    assert "2 clustered instance(s)" in report.steps[0].result


def test_registry_is_in_the_first_message(settings, tmp_path: Path) -> None:
    session = _session(tmp_path)
    client = FakeClient([
        [_tool_use("finish", "t1", answer="ok", reliability="Low", sources=[])],
    ])
    run_bim_task("q", settings=settings, session=session, client=client)
    first = client.requests[0]["messages"][0]["content"]
    assert "S-101" in first
    assert "set.pdf" in first


def test_artifact_write_outside_whitelist_is_refused(settings, tmp_path: Path) -> None:
    session = _session(tmp_path)
    client = FakeClient([
        [_tool_use("write_artifact", "t1", name="../evil.md", content="pwn")],
        [_tool_use("finish", "t2", answer="stopped", reliability="Low", sources=[])],
    ])

    run_bim_task("q", settings=settings, session=session, client=client)

    assert not (tmp_path / "evil.md").exists()
    tool_results = [
        block
        for message in client.requests[1]["messages"]
        if isinstance(message["content"], list)
        for block in message["content"]
        if block.get("type") == "tool_result"
    ]
    assert tool_results and tool_results[0]["is_error"] is True
    assert "Refused" in tool_results[0]["content"]


def test_artifact_roundtrip(settings, tmp_path: Path) -> None:
    session = _session(tmp_path)
    assert "does not exist" in session.read_artifact("notes.md")
    session.write_artifact("notes.md", "# заметки")
    assert session.read_artifact("notes.md") == "# заметки"


def test_no_text_layer_page_points_to_render(tmp_path: Path) -> None:
    index = DrawingSetIndex()
    index.pages = [PageText(file="scan.pdf", pdf_page=1, width=100, height=100,
                            spans=[], raw_text="")]
    session = DocSession([], tmp_path / "bim", index=index)
    assert "render_page" in session.read_page_text("scan.pdf", 1)
    assert "No indexed page" in session.read_page_text("scan.pdf", 99)


def test_step_budget_exhausted(settings, tmp_path: Path) -> None:
    settings.bim_max_steps = 2
    session = _session(tmp_path)
    client = FakeClient([
        [_tool_use("list_sheets", "t1")],
        [_tool_use("list_sheets", "t2")],
    ])

    report = run_bim_task("loop", settings=settings, session=session, client=client)

    assert report.success is False
    assert "budget" in report.answer.lower()
    assert len(report.steps) == 2
