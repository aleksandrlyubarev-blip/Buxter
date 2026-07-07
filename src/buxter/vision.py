import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from anthropic import Anthropic

from .config import Settings, resolve_model
from .llm import image_block, make_client, response_text
from .prompts import (
    FUSION_RETRY_TEMPLATE,
    FUSION_SYSTEM_PROMPT,
    FUSION_USER_TEMPLATE_NO_PHOTO,
    FUSION_USER_TEMPLATE_WITH_PHOTO,
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

BackendName = Literal["freecad", "fusion"]

_PROMPT_BUNDLE: dict[BackendName, dict[str, str]] = {
    "freecad": {
        "system": SYSTEM_PROMPT,
        "no_photo": USER_TEMPLATE_NO_PHOTO,
        "with_photo": USER_TEMPLATE_WITH_PHOTO,
        "retry": RETRY_TEMPLATE,
    },
    "fusion": {
        "system": FUSION_SYSTEM_PROMPT,
        "no_photo": FUSION_USER_TEMPLATE_NO_PHOTO,
        "with_photo": FUSION_USER_TEMPLATE_WITH_PHOTO,
        "retry": FUSION_RETRY_TEMPLATE,
    },
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
    return image_block(photo.read_bytes(), _MEDIA_TYPES[suffix])


def _build_messages(
    description: str,
    photo: Path | None,
    prior_script: str | None,
    stderr: str | None,
    backend: BackendName,
) -> list[dict[str, Any]]:
    bundle = _PROMPT_BUNDLE[backend]
    if prior_script is not None:
        stderr_section = ""
        if stderr:
            stderr_section = (
                "The previous script failed with this stderr (last lines):\n"
                f"```\n{stderr[-2000:]}\n```\n\n"
            )
        user_text = bundle["retry"].format(
            prior_script=prior_script,
            stderr_section=stderr_section,
            description=description,
        )
    elif photo is not None:
        user_text = bundle["with_photo"].format(description=description)
    else:
        user_text = bundle["no_photo"].format(description=description)

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
    backend: BackendName = "freecad",
) -> GenerationResult:
    anthropic = make_client(settings, client)
    model_id = resolve_model(settings.model)
    messages = _build_messages(description, photo, prior_script, stderr, backend)

    response = anthropic.messages.create(
        model=model_id,
        max_tokens=settings.max_tokens,
        system=_PROMPT_BUNDLE[backend]["system"],
        messages=messages,
    )

    raw = response_text(response)
    return GenerationResult(script=extract_script(raw), raw_text=raw, model=model_id)
