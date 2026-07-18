"""Fable-phase MCP server stub for the electronics drawing generator.

Minimal JSON-RPC 2.0 loop over stdio implementing just enough of the MCP
contract for a client to discover and call the generator:

    initialize → tools/list → tools/call(generate_inspection_drawing)

Deliberately a stub: no sessions, no streaming, no cancellation, no
notifications. The Codex phase replaces this with a full production MCP
server (official SDK, complete error taxonomy, validation, safety layer);
the tool schemas below are the contract it must keep.

Safety already enforced here:
- output is confined to OUTPUT_DIR (env DRAWING_MCP_OUTPUT_DIR or ./out);
- the filename is a bare name — separators and traversal are rejected;
- spec validation errors come back as tool errors, never as crashes.

Run:  python -m mcp_server.drawing_mcp
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .drawing_generator import AssemblySpec, SpecError, generate_drawing

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "buxter-electronics-drawing", "version": "0.1.0-fable"}

OUTPUT_DIR = Path(os.environ.get("DRAWING_MCP_OUTPUT_DIR", "./out")).resolve()

SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "simulation_id": {"type": "string"},
        "board": {
            "type": "object",
            "properties": {
                "width": {"type": "number"},
                "height": {"type": "number"},
                "thickness": {"type": "number"},
            },
            "required": ["width", "height", "thickness"],
        },
        "holes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "diameter": {"type": "number"},
                    "tolerance": {"type": "string"},
                    "critical": {"type": "boolean"},
                    "label": {"type": "string"},
                },
                "required": ["x", "y", "diameter"],
            },
        },
        "drawing_type": {"type": "string", "enum": ["ASSEMBLY", "INSPECTION", "FIXTURE"]},
        "revision": {"type": "string"},
        "general_tolerance": {"type": "string"},
        "gdt_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "simulation_id", "board"],
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "generate_inspection_drawing",
        "description": (
            "Generate a DXF inspection/assembly drawing for an electronics "
            "board or fixture from a machine-readable spec. Returns the "
            "path of the written DXF inside the sandboxed output directory."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": SPEC_SCHEMA,
                "filename": {
                    "type": "string",
                    "description": "Bare output file name, e.g. 'assembly_a.dxf'.",
                },
            },
            "required": ["spec", "filename"],
        },
    },
]


def _safe_output_path(filename: str) -> Path:
    name = Path(filename).name
    if name != filename or name in ("", ".", ".."):
        raise SpecError(f"Invalid filename {filename!r}: bare file names only.")
    if not name.lower().endswith(".dxf"):
        name += ".dxf"
    return OUTPUT_DIR / name


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name != "generate_inspection_drawing":
        return _tool_error(f"Unknown tool {name!r}")
    try:
        spec = AssemblySpec.from_dict(arguments["spec"])
        path = generate_drawing(spec, _safe_output_path(arguments["filename"]))
    except (SpecError, KeyError) as exc:
        return _tool_error(str(exc))
    return {
        "content": [{"type": "text", "text": f"DXF written: {path}"}],
        "isError": False,
    }


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _handle(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method", "")
    request_id = request.get("id")
    if request_id is None:  # notification — nothing to answer in the stub
        return None

    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = request.get("params") or {}
        result = _call_tool(params.get("name", ""), params.get("arguments") or {})
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response: dict[str, Any] | None = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        else:
            response = _handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
