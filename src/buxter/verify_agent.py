"""Vision self-check: does the exported geometry match the design intent?

Implements the CADCodeVerify pattern (arXiv:2410.05340): render canonical
views of the exported mesh, have the model derive binary yes/no questions
from the original description, answer them from the renders, and emit a
verdict plus a concrete revision when something is off. Exact kernel metrics
(bbox/volume/watertight from the validator) are included in the prompt so
dimensional errors a VLM cannot see are caught numerically (CADSmith).

The judge is deliberately separated from the generator: this module never
writes CAD code, it only critiques geometry.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from .config import Settings, resolve_model
from .llm import image_block, make_client, response_text
from .prompts import VERIFY_SYSTEM_PROMPT
from .render import render_views
from .validator import validate_mesh

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

# Diminishing returns after the second refinement round (CADCodeVerify).
MAX_SELF_CHECK_ROUNDS = 2


@dataclass
class VerifyQuestion:
    question: str
    answer: str  # "yes" | "no" | "unclear"
    note: str = ""


@dataclass
class VerifyReport:
    passed: bool
    questions: list[VerifyQuestion] = field(default_factory=list)
    revision: str | None = None
    metrics: str = ""


def _kernel_metrics(mesh_path: Path) -> str:
    report = validate_mesh(mesh_path)
    lines = [f"- {check.name}: {'OK' if check.ok else 'FAIL'} ({check.detail})"
             for check in report.checks]
    lines.append(
        f"- bbox: {report.bbox[0]:.2f} × {report.bbox[1]:.2f} × {report.bbox[2]:.2f} mm"
    )
    return "\n".join(lines)


def _parse_report(raw: str, metrics: str) -> VerifyReport:
    match = _JSON_RE.search(raw)
    if not match:
        raise ValueError(f"Verifier returned no JSON object:\n{raw[:500]}")
    data: dict[str, Any] = json.loads(match.group(0))
    questions = [
        VerifyQuestion(
            question=str(item.get("question", "")),
            answer=str(item.get("answer", "unclear")).lower(),
            note=str(item.get("note", "")),
        )
        for item in data.get("questions", [])
    ]
    revision = data.get("revision")
    return VerifyReport(
        passed=bool(data.get("passed", False)),
        questions=questions,
        revision=str(revision) if revision else None,
        metrics=metrics,
    )


def verify_model(
    mesh_path: Path,
    description: str,
    *,
    settings: Settings,
    client: Anthropic | None = None,
    render_dir: Path | None = None,
) -> VerifyReport:
    """Render the mesh and judge it against the description. One API call."""
    anthropic = make_client(settings, client)
    model_id = resolve_model(settings.model)

    metrics = _kernel_metrics(mesh_path)
    views = render_views(mesh_path, render_dir or mesh_path.parent / "_views")

    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Design description:\n{description}\n\n"
                f"Exact kernel measurements of the exported mesh:\n{metrics}\n\n"
                f"Attached: {len(views)} renders of the SAME mesh from azimuths "
                "45/135/225/315°, elevation 25°. Judge the geometry now."
            ),
        }
    ]
    for png in views:
        content.append(image_block(png.read_bytes(), "image/png"))

    response = anthropic.messages.create(
        model=model_id,
        max_tokens=settings.max_tokens,
        system=VERIFY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    return _parse_report(response_text(response), metrics)


__all__ = [
    "MAX_SELF_CHECK_ROUNDS",
    "VerifyQuestion",
    "VerifyReport",
    "verify_model",
]
