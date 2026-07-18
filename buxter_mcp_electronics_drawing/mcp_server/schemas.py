"""Strict JSON Schemas for every MCP tool of the drawing server.

These schemas ARE the public contract: `additionalProperties: false`
everywhere, explicit bounds, enums and patterns. The server validates every
`tools/call` against them before any code runs and reports violations as
deterministic `SCHEMA_ERROR:` messages.
"""

from __future__ import annotations

from typing import Any

_POSITIVE = {"type": "number", "exclusiveMinimum": 0}
_COORD = {"type": "number", "minimum": -100000, "maximum": 100000}
_NAME = {"type": "string", "minLength": 1, "maxLength": 200}
_FILENAME = {
    "type": "string",
    "minLength": 1,
    "maxLength": 128,
    "description": "Bare output file name inside the sandbox, e.g. 'board_a.dxf'.",
}
_REVISION = {"type": "string", "pattern": "^[A-Z]{1,2}$"}

HOLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "x": _COORD,
        "y": _COORD,
        "diameter": _POSITIVE,
        "tolerance": {"type": "string", "maxLength": 40},
        "critical": {"type": "boolean"},
        "label": {"type": "string", "maxLength": 80},
    },
    "required": ["x", "y", "diameter"],
    "additionalProperties": False,
}

BOARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "width": _POSITIVE,
        "height": _POSITIVE,
        "thickness": _POSITIVE,
    },
    "required": ["width", "height", "thickness"],
    "additionalProperties": False,
}

ASSEMBLY_SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": _NAME,
        "simulation_id": _NAME,
        "board": BOARD_SCHEMA,
        "holes": {"type": "array", "items": HOLE_SCHEMA, "maxItems": 500},
        "revision": _REVISION,
        "author": {"type": "string", "maxLength": 80},
        "source_system": {"type": "string", "maxLength": 80},
        "general_tolerance": {"type": "string", "maxLength": 40},
        "units": {"type": "string", "enum": ["mm", "inch"]},
        "gdt_notes": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 200},
            "maxItems": 50,
        },
        "issue_date": {
            "type": "string",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
        },
    },
    "required": ["name", "simulation_id", "board"],
    "additionalProperties": False,
}

PROCESS_STEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "no": {"type": "integer", "minimum": 1},
        "description": {"type": "string", "minLength": 1, "maxLength": 200},
        "station": {"type": "string", "maxLength": 60},
        "tooling": {"type": "string", "maxLength": 60},
        "inspection": {"type": "boolean"},
    },
    "required": ["description"],
    "additionalProperties": False,
}

PROCESS_SHEET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": _NAME,
        "simulation_id": _NAME,
        "steps": {
            "type": "array",
            "items": PROCESS_STEP_SCHEMA,
            "minItems": 1,
            "maxItems": 200,
        },
        "revision": _REVISION,
        "author": {"type": "string", "maxLength": 80},
        "source_system": {"type": "string", "maxLength": 80},
        "issue_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
    },
    "required": ["name", "simulation_id", "steps"],
    "additionalProperties": False,
}

_POINT = {
    "type": "object",
    "properties": {"x": _COORD, "y": _COORD},
    "required": ["x", "y"],
    "additionalProperties": False,
}

DIMENSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "p1": _POINT,
        "p2": _POINT,
        "offset": {"type": "number", "minimum": 1, "maximum": 200},
    },
    "required": ["p1", "p2"],
    "additionalProperties": False,
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "generate_assembly_drawing",
        "description": (
            "Generate a DXF assembly drawing (geometry, centerlines, overall "
            "dimensions, notes, title block) for an electronics board or "
            "fixture from a machine-readable spec. Writes <filename>.dxf and "
            "a <filename>.spec.json sidecar into the output sandbox."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"spec": ASSEMBLY_SPEC_SCHEMA, "filename": _FILENAME},
            "required": ["spec", "filename"],
            "additionalProperties": False,
        },
    },
    {
        "name": "generate_inspection_drawing",
        "description": (
            "Generate a DXF inspection drawing: everything the assembly "
            "drawing has, plus numbered inspection balloons on critical "
            "holes and their position dimensions from the datum corner."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"spec": ASSEMBLY_SPEC_SCHEMA, "filename": _FILENAME},
            "required": ["spec", "filename"],
            "additionalProperties": False,
        },
    },
    {
        "name": "generate_process_sheet",
        "description": (
            "Generate a DXF process/operation sheet for an assembly: a "
            "numbered operation table (description, station, tooling, "
            "inspection flag) with a title block."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"sheet": PROCESS_SHEET_SCHEMA, "filename": _FILENAME},
            "required": ["sheet", "filename"],
            "additionalProperties": False,
        },
    },
    {
        "name": "add_gdt_and_dimensions",
        "description": (
            "Annotate an existing DXF in the sandbox: append GD&T/general "
            "notes and/or aligned dimensions between explicit points. At "
            "least one of gdt_notes / dimensions must be provided."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": _FILENAME,
                "gdt_notes": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 200},
                    "minItems": 1,
                    "maxItems": 50,
                },
                "dimensions": {
                    "type": "array",
                    "items": DIMENSION_SCHEMA,
                    "minItems": 1,
                    "maxItems": 100,
                },
            },
            "required": ["filename"],
            "anyOf": [{"required": ["gdt_notes"]}, {"required": ["dimensions"]}],
            "additionalProperties": False,
        },
    },
    {
        "name": "validate_drawing_for_production",
        "description": (
            "Run production-readiness checks on a DXF in the sandbox: "
            "readability, required layers, visible geometry, at least one "
            "dimension, complete title block. Returns a structured report; "
            "a failing check is a normal result, not a tool error."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"filename": _FILENAME},
            "required": ["filename"],
            "additionalProperties": False,
        },
    },
    {
        "name": "sync_with_simulation",
        "description": (
            "Update an existing drawing from fresh simulation data. Compares "
            "the new spec with the drawing's .spec.json sidecar; if anything "
            "changed, bumps the revision (A→B), regenerates the DXF in place "
            "and reports the change list. No changes → no regeneration."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"spec": ASSEMBLY_SPEC_SCHEMA, "filename": _FILENAME},
            "required": ["spec", "filename"],
            "additionalProperties": False,
        },
    },
]

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    tool["name"]: tool["input_schema"] for tool in TOOL_DEFINITIONS
}

__all__ = [
    "ASSEMBLY_SPEC_SCHEMA",
    "BOARD_SCHEMA",
    "DIMENSION_SCHEMA",
    "HOLE_SCHEMA",
    "PROCESS_SHEET_SCHEMA",
    "PROCESS_STEP_SCHEMA",
    "TOOL_DEFINITIONS",
    "TOOL_SCHEMAS",
]
