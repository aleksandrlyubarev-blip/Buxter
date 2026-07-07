"""Shared Anthropic client helpers used by every Buxter agent.

Both the Modeling Agent (vision.py) and the Web Operator Agent (web_agent.py)
talk to the same API; the bootstrap (key check, client construction) and the
common block helpers live here so the two entry points cannot drift apart.
"""

from __future__ import annotations

import base64
from typing import Any

from anthropic import Anthropic

from .config import Settings


def make_client(settings: Settings, client: Anthropic | None = None) -> Anthropic:
    """Return the provided client or build one, failing fast without a key."""
    if client is not None:
        return client
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    return Anthropic(api_key=settings.anthropic_api_key)


def response_text(response: Any) -> str:
    """Concatenate the text blocks of an API response."""
    return "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )


def image_block(data: bytes, media_type: str) -> dict[str, Any]:
    """Build a base64 image content block for the Messages API."""
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
    }


__all__ = ["image_block", "make_client", "response_text"]
