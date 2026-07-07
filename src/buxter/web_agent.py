"""Web Operator Agent: a Claude tool-use loop that drives a BrowserSession.

This is the second Buxter layer, complementing the Modeling Agent: it takes
artifacts produced by the CAD layer (STL/STEP paths passed as *attachments*)
plus a natural-language task, and operates a real web application — upload,
parameter entry, launching a computation — until it calls ``finish``.

State handoff between the layers is file-based and explicit: the agent may
only upload files from the attachments whitelist, and it must report the
outcome through the ``finish`` tool so callers get a structured
:class:`WebTaskReport` instead of free text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from anthropic import Anthropic

from .browser import BrowserSession, PageDigest
from .config import Settings, resolve_model
from .llm import image_block, make_client, response_text
from .prompts import WEB_SYSTEM_PROMPT

_STALE_PLACEHOLDER = "[stale observation elided — call read_page/screenshot again if needed]"

WEB_TOOLS: list[dict[str, Any]] = [
    {
        "name": "goto",
        "description": "Navigate the browser to a URL.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "read_page",
        "description": (
            "Return the current page digest: URL, title, visible text and the "
            "list of interactive elements with their ids. Element ids are only "
            "valid until the next navigation — re-read after goto/click."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "click",
        "description": "Click an interactive element by id from the last read_page.",
        "input_schema": {
            "type": "object",
            "properties": {"element_id": {"type": "integer"}},
            "required": ["element_id"],
        },
    },
    {
        "name": "fill",
        "description": "Type a value into an input/textarea element by id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "integer"},
                "value": {"type": "string"},
                "press_enter": {"type": "boolean", "default": False},
            },
            "required": ["element_id", "value"],
        },
    },
    {
        "name": "select_option",
        "description": "Select an option (by value or label) in a <select> element.",
        "input_schema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "integer"},
                "value": {"type": "string"},
            },
            "required": ["element_id", "value"],
        },
    },
    {
        "name": "upload_file",
        "description": (
            "Upload one of the whitelisted attachments into a file input. "
            "`attachment` must be a file name from the task's attachment list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "integer"},
                "attachment": {"type": "string"},
            },
            "required": ["element_id", "attachment"],
        },
    },
    {
        "name": "screenshot",
        "description": "Take a PNG screenshot of the current viewport.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "wait",
        "description": "Wait up to 15 seconds (e.g. for a computation to finish).",
        "input_schema": {
            "type": "object",
            "properties": {"seconds": {"type": "number"}},
            "required": ["seconds"],
        },
    },
    {
        "name": "finish",
        "description": (
            "End the task. Set success=true only if the goal was actually "
            "achieved; the summary must state what happened and quote any "
            "result values visible on the page."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "summary": {"type": "string"},
            },
            "required": ["success", "summary"],
        },
    },
]


@dataclass
class WebStep:
    tool: str
    input: dict[str, Any]
    result: str


@dataclass
class WebTaskReport:
    success: bool
    summary: str
    steps: list[WebStep] = field(default_factory=list)


def _dispatch(
    session: BrowserSession,
    name: str,
    args: dict[str, Any],
    attachments: dict[str, Path],
) -> tuple[list[dict[str, Any]] | str, bool]:
    """Run one tool call. Returns (tool_result content, is_error)."""
    try:
        if name == "goto":
            return session.goto(args["url"]), False
        if name == "read_page":
            digest: PageDigest = session.read_page()
            return digest.render(), False
        if name == "click":
            return session.click(int(args["element_id"])), False
        if name == "fill":
            return (
                session.fill(
                    int(args["element_id"]),
                    args["value"],
                    press_enter=bool(args.get("press_enter", False)),
                ),
                False,
            )
        if name == "select_option":
            return session.select_option(int(args["element_id"]), args["value"]), False
        if name == "upload_file":
            attachment = args["attachment"]
            path = attachments.get(attachment)
            if path is None:
                allowed = ", ".join(sorted(attachments)) or "(none)"
                return (
                    f"Refused: {attachment!r} is not a whitelisted attachment. "
                    f"Allowed: {allowed}",
                    True,
                )
            return session.upload_file(int(args["element_id"]), path), False
        if name == "screenshot":
            return [image_block(session.screenshot(), "image/png")], False
        if name == "wait":
            return session.wait(float(args["seconds"])), False
        return f"Unknown tool {name!r}", True
    except Exception as exc:  # surface browser errors to the model, don't crash
        return f"{type(exc).__name__}: {exc}", True


def _attachment_names(attachments: tuple[Path, ...] | list[Path]) -> dict[str, Path]:
    """Map unique upload names to resolved paths.

    Keyed by basename, but same-named files from different directories get a
    numeric suffix instead of silently shadowing each other.
    """
    allowed: dict[str, Path] = {}
    for raw in attachments:
        path = Path(raw).resolve()
        name = path.name
        if allowed.get(name) == path:
            continue
        if name in allowed:
            index = 2
            while f"{path.stem}-{index}{path.suffix}" in allowed:
                index += 1
            name = f"{path.stem}-{index}{path.suffix}"
        allowed[name] = path
    return allowed


def _elide_stale_observations(messages: list[dict[str, Any]]) -> None:
    """Blank all but the newest page digest and newest screenshot in-place.

    Element ids from older digests are stale by contract and screenshots of
    left-behind pages are dead weight; resending them makes input tokens grow
    quadratically over a run.
    """
    digests: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") != "user" or not isinstance(message.get("content"), list):
            continue
        for block in message["content"]:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            payload = block.get("content")
            if isinstance(payload, list) and any(
                isinstance(item, dict) and item.get("type") == "image" for item in payload
            ):
                images.append(block)
            elif isinstance(payload, str) and payload.startswith("url: "):
                digests.append(block)
    for stale in digests[:-1] + images[:-1]:
        stale["content"] = _STALE_PLACEHOLDER


def _task_message(task: str, attachments: dict[str, Path], start_url: str | None) -> str:
    parts = [f"Task:\n{task}"]
    if start_url:
        parts.append(f"Start URL: {start_url}")
    if attachments:
        listing = "\n".join(f"- {name}" for name in sorted(attachments))
        parts.append(f"Attachments you may upload (by name):\n{listing}")
    else:
        parts.append("No attachments are available for upload.")
    return "\n\n".join(parts)


def run_web_task(
    task: str,
    *,
    settings: Settings,
    session: BrowserSession,
    attachments: tuple[Path, ...] | list[Path] = (),
    start_url: str | None = None,
    client: Anthropic | None = None,
    on_step: Callable[[WebStep], None] | None = None,
) -> WebTaskReport:
    """Drive `session` with Claude until the model calls ``finish``."""
    anthropic = make_client(settings, client)
    model_id = resolve_model(settings.model)
    allowed = _attachment_names(attachments)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _task_message(task, allowed, start_url)}
    ]
    # cache_control on the static prefix (system + tools) makes every turn
    # after the first a cache read instead of a full-price re-parse.
    system = [
        {"type": "text", "text": WEB_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]
    tools = [*WEB_TOOLS[:-1], {**WEB_TOOLS[-1], "cache_control": {"type": "ephemeral"}}]
    steps: list[WebStep] = []

    for _ in range(settings.web_max_steps):
        _elide_stale_observations(messages)
        response = anthropic.messages.create(
            model=model_id,
            max_tokens=settings.max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )
        tool_uses = [
            block for block in response.content if getattr(block, "type", None) == "tool_use"
        ]
        if not tool_uses:
            text = response_text(response)
            return WebTaskReport(
                success=False,
                summary=text.strip() or "Agent stopped without calling finish.",
                steps=steps,
            )

        # Echo the response content back verbatim: hand-rebuilding it would
        # silently drop block types the loop doesn't know about (thinking,
        # server_tool_use, …) and break the next request.
        messages.append({"role": "assistant", "content": list(response.content)})

        results: list[dict[str, Any]] = []
        for call in tool_uses:
            args = dict(call.input or {})
            if call.name == "finish":
                step = WebStep(tool="finish", input=args, result="done")
                steps.append(step)
                if on_step:
                    on_step(step)
                return WebTaskReport(
                    success=bool(args.get("success", False)),
                    summary=str(args.get("summary", "")),
                    steps=steps,
                )
            content, is_error = _dispatch(session, call.name, args, allowed)
            snippet = content if isinstance(content, str) else "[screenshot]"
            step = WebStep(tool=call.name, input=args, result=snippet[:500])
            steps.append(step)
            if on_step:
                on_step(step)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": content,
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": results})

    return WebTaskReport(
        success=False,
        summary=f"Step budget exhausted ({settings.web_max_steps} model turns).",
        steps=steps,
    )


__all__ = ["WEB_TOOLS", "WebStep", "WebTaskReport", "run_web_task"]
