import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from .config import Settings, resolve_model
from .prompts import (
    RETRY_TEMPLATE,
    SYSTEM_PROMPT,
    USER_TEMPLATE_NO_PHOTO,
    USER_TEMPLATE_WITH_PHOTO,
)

_CODE_FENCE_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)

_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


class ScriptExtractionError(ValueError):
    pass


@dataclass
class GenerationResult:
    script: str
    raw_text: str
    model: str


def extract_script(text: str) -> str:
    match = _CODE_FENCE_RE.search(text)
    if not match:
        stripped = text.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            return stripped
        raise ScriptExtractionError(
            "No ```python fenced block found in model output."
        )
    return match.group(1).rstrip() + "\n"


def _image_block(photo: Path) -> dict[str, Any]:
    suffix = photo.suffix.lower()
    if suffix not in _MEDIA_TYPES:
        raise ValueError(f"Unsupported image type: {suffix}")
    data = base64.standard_b64encode(photo.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": _MEDIA_TYPES[suffix],
            "data": data,
        },
    }


def _build_messages(
    description: str,
    photo: Path | None,
    prior_script: str | None,
    stderr: str | None,
) -> list[dict[str, Any]]:
    if prior_script is not None:
        stderr_section = ""
        if stderr:
            stderr_section = (
                "The previous script failed with this stderr (last lines):\n"
                f"```\n{stderr[-2000:]}\n```\n\n"
            )
        user_text = RETRY_TEMPLATE.format(
            prior_script=prior_script,
            stderr_section=stderr_section,
            description=description,
        )
    elif photo is not None:
        user_text = USER_TEMPLATE_WITH_PHOTO.format(description=description)
    else:
        user_text = USER_TEMPLATE_NO_PHOTO.format(description=description)

    content: list[dict[str, Any]] = []
    if photo is not None:
        content.append(_image_block(photo))
    content.append({"type": "text", "text": user_text})
    return [{"role": "user", "content": content}]


def generate_script(
    description: str,
    photo: Path | None = None,
    *,
    settings: Settings,
    prior_script: str | None = None,
    stderr: str | None = None,
    client: Anthropic | None = None,
) -> GenerationResult:
    if not settings.anthropic_api_key and client is None:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    model_id = resolve_model(settings.model)
    anthropic = client or Anthropic(api_key=settings.anthropic_api_key)
    messages = _build_messages(description, photo, prior_script, stderr)

    response = anthropic.messages.create(
        model=model_id,
        max_tokens=settings.max_tokens,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    raw = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )
    return GenerationResult(script=extract_script(raw), raw_text=raw, model=model_id)
