from pathlib import Path

from buxter.browser import PageDigest
from buxter.web_agent import WebTaskReport, run_web_task


class FakeSession:
    """BrowserSession stand-in that records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def goto(self, url: str) -> str:
        self.calls.append(("goto", url))
        return f"navigated to {url}"

    def read_page(self) -> PageDigest:
        self.calls.append(("read_page",))
        return PageDigest(
            url="https://tool.example/upload",
            title="Upload",
            text="Drop your STL here",
            elements=[{"id": 1, "tag": "input", "type": "file", "text": "",
                       "name": "part", "placeholder": "", "href": ""}],
        )

    def click(self, element_id: int) -> str:
        self.calls.append(("click", element_id))
        return f"clicked element {element_id}"

    def fill(self, element_id: int, value: str, press_enter: bool = False) -> str:
        self.calls.append(("fill", element_id, value, press_enter))
        return f"filled element {element_id}"

    def select_option(self, element_id: int, value: str) -> str:
        self.calls.append(("select_option", element_id, value))
        return f"selected {value!r}"

    def upload_file(self, element_id: int, path: Path) -> str:
        self.calls.append(("upload_file", element_id, path))
        return f"uploaded {path.name}"

    def screenshot(self) -> bytes:
        self.calls.append(("screenshot",))
        return b"\x89PNG fake"

    def wait(self, seconds: float) -> str:
        self.calls.append(("wait", seconds))
        return f"waited {seconds}"

    def close(self) -> None:
        self.calls.append(("close",))


class _Block:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


def _tool_use(name: str, tool_id: str, **tool_input) -> _Block:
    return _Block(type="tool_use", id=tool_id, name=name, input=tool_input)


class FakeClient:
    """Mimics `client.messages.create(...)` with a scripted response queue."""

    def __init__(self, responses) -> None:
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return _Block(content=self._responses.pop(0))


def test_happy_path_finish(settings, tmp_path: Path) -> None:
    stl = tmp_path / "out.stl"
    stl.write_bytes(b"solid")
    session = FakeSession()
    client = FakeClient([
        [_tool_use("goto", "t1", url="https://tool.example")],
        [_tool_use("read_page", "t2")],
        [_tool_use("upload_file", "t3", element_id=1, attachment="out.stl")],
        [_tool_use("finish", "t4", success=True, summary="Uploaded, job #42 started.")],
    ])

    report = run_web_task(
        "Upload the STL and start the job.",
        settings=settings,
        session=session,
        attachments=[stl],
        client=client,
    )

    assert isinstance(report, WebTaskReport)
    assert report.success is True
    assert "job #42" in report.summary
    assert ("goto", "https://tool.example") in session.calls
    assert ("upload_file", 1, stl.resolve()) in session.calls
    assert [step.tool for step in report.steps] == [
        "goto", "read_page", "upload_file", "finish",
    ]


def test_upload_outside_whitelist_is_refused(settings, tmp_path: Path) -> None:
    stl = tmp_path / "out.stl"
    stl.write_bytes(b"solid")
    session = FakeSession()
    client = FakeClient([
        [_tool_use("upload_file", "t1", element_id=1, attachment="/etc/passwd")],
        [_tool_use("finish", "t2", success=False, summary="Refused upload.")],
    ])

    report = run_web_task(
        "Upload something.",
        settings=settings,
        session=session,
        attachments=[stl],
        client=client,
    )

    assert report.success is False
    assert not any(call[0] == "upload_file" for call in session.calls)
    refused_step = report.steps[0]
    assert "Refused" in refused_step.result
    # The refusal is fed back to the model as an error tool_result.
    tool_results = [
        block
        for message in client.requests[1]["messages"]
        if isinstance(message["content"], list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert tool_results and tool_results[0]["is_error"] is True


def test_no_tool_use_stops_without_success(settings) -> None:
    session = FakeSession()
    client = FakeClient([
        [_Block(type="text", text="I cannot do this.")],
    ])

    report = run_web_task(
        "Do the impossible.", settings=settings, session=session, client=client,
    )

    assert report.success is False
    assert report.summary == "I cannot do this."
    assert session.calls == []


def test_step_budget_exhausted(settings) -> None:
    settings.web_max_steps = 2
    session = FakeSession()
    client = FakeClient([
        [_tool_use("read_page", "t1")],
        [_tool_use("read_page", "t2")],
    ])

    report = run_web_task(
        "Loop forever.", settings=settings, session=session, client=client,
    )

    assert report.success is False
    assert "budget" in report.summary.lower()
    assert len(report.steps) == 2


def test_duplicate_attachment_names_are_disambiguated(settings, tmp_path: Path) -> None:
    v1 = tmp_path / "v1" / "part.stl"
    v2 = tmp_path / "v2" / "part.stl"
    for path in (v1, v2):
        path.parent.mkdir()
        path.write_bytes(b"solid")
    session = FakeSession()
    client = FakeClient([
        [_tool_use("upload_file", "t1", element_id=1, attachment="part-2.stl")],
        [_tool_use("finish", "t2", success=True, summary="done")],
    ])

    report = run_web_task(
        "Upload both versions.",
        settings=settings,
        session=session,
        attachments=[v1, v2],
        client=client,
    )

    task_text = client.requests[0]["messages"][0]["content"]
    assert "part.stl" in task_text and "part-2.stl" in task_text
    assert ("upload_file", 1, v2.resolve()) in session.calls
    assert report.success is True


def test_stale_observations_are_elided(settings) -> None:
    session = FakeSession()
    client = FakeClient([
        [_tool_use("read_page", "t1")],
        [_tool_use("read_page", "t2")],
        [_tool_use("finish", "t3", success=True, summary="done")],
    ])

    run_web_task("Look around.", settings=settings, session=session, client=client)

    # At the third request, the first digest must be elided, the second kept.
    digests = [
        block
        for message in client.requests[2]["messages"]
        if isinstance(message["content"], list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert len(digests) == 2
    assert "elided" in digests[0]["content"]
    assert digests[1]["content"].startswith("url: ")


def test_assistant_content_is_passed_through(settings) -> None:
    session = FakeSession()
    thinking = _Block(type="thinking", thinking="hmm", signature="sig")
    client = FakeClient([
        [thinking, _tool_use("read_page", "t1")],
        [_tool_use("finish", "t2", success=True, summary="done")],
    ])

    run_web_task("Look.", settings=settings, session=session, client=client)

    assistant = client.requests[1]["messages"][1]
    assert assistant["role"] == "assistant"
    assert thinking in assistant["content"]  # unknown block types are preserved


def test_page_digest_render_lists_elements() -> None:
    digest = PageDigest(
        url="https://x.test",
        title="T",
        text="hello",
        elements=[{"id": 3, "tag": "button", "type": "", "text": "Run ADMS",
                   "name": "", "placeholder": "", "href": ""}],
    )
    rendered = digest.render()
    assert "[3] <button" in rendered
    assert "Run ADMS" in rendered
