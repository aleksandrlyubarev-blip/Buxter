"""Integration tests: real MCP stdio sessions against the drawing server.

Each test spawns `python -m mcp_server.drawing_mcp` as a subprocess and
speaks the official MCP protocol through the SDK client (initialize →
tools/list → tools/call). Generated DXF files are read back with ezdxf in
the test process.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")
ezdxf = pytest.importorskip("ezdxf")
pytest.importorskip("jsonschema")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

SUBPROJECT = Path(__file__).resolve().parents[1] / "buxter_mcp_electronics_drawing"

SPEC = {
    "name": "PI5 CARRIER BOARD",
    "simulation_id": "SIM-2026-0718-004",
    "board": {"width": 160.0, "height": 100.0, "thickness": 1.6},
    "holes": [
        {"x": 5, "y": 5, "diameter": 3.2, "tolerance": "+0.1/-0.0", "label": "M3"},
        {"x": 30, "y": 50, "diameter": 2.0, "tolerance": "H7", "critical": True,
         "label": "ALIGNMENT PIN"},
    ],
    "gdt_notes": ["CRITICAL FEATURES PER IPC-A-610 CLASS 3."],
    "issue_date": "2026-07-18",
}


def run_scenario(out_dir: Path, scenario):
    """Run an async callable against a fresh stdio server session."""

    async def runner():
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SUBPROJECT)
        env["DRAWING_MCP_OUTPUT_DIR"] = str(out_dir)
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "mcp_server.drawing_mcp"], env=env,
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await scenario(session)

    return asyncio.run(runner())


def _text(result) -> str:
    return result.content[0].text


def _payload(result) -> dict:
    assert result.isError is False, _text(result)
    return json.loads(_text(result))


def test_tools_list_contract(tmp_path: Path) -> None:
    async def scenario(session: ClientSession):
        return await session.list_tools()

    listing = run_scenario(tmp_path, scenario)
    names = [tool.name for tool in listing.tools]
    assert names == [
        "generate_assembly_drawing",
        "generate_inspection_drawing",
        "generate_process_sheet",
        "add_gdt_and_dimensions",
        "validate_drawing_for_production",
        "sync_with_simulation",
    ]
    for tool in listing.tools:
        assert tool.inputSchema["additionalProperties"] is False
        assert tool.description


def test_full_drawing_lifecycle(tmp_path: Path) -> None:
    async def scenario(session: ClientSession):
        results = {}
        results["inspection"] = _payload(await session.call_tool(
            "generate_inspection_drawing", {"spec": SPEC, "filename": "flow.dxf"},
        ))
        results["assembly"] = _payload(await session.call_tool(
            "generate_assembly_drawing", {"spec": SPEC, "filename": "asm.dxf"},
        ))
        results["validate"] = _payload(await session.call_tool(
            "validate_drawing_for_production", {"filename": "flow.dxf"},
        ))
        results["annotate"] = _payload(await session.call_tool(
            "add_gdt_and_dimensions",
            {"filename": "flow.dxf",
             "gdt_notes": ["FLATNESS 0.1 OVER FIXTURE AREA"],
             "dimensions": [{"p1": {"x": 5, "y": 5}, "p2": {"x": 30, "y": 50}}]},
        ))
        changed = json.loads(json.dumps(SPEC))
        changed["holes"][1]["diameter"] = 2.5
        results["sync"] = _payload(await session.call_tool(
            "sync_with_simulation", {"spec": changed, "filename": "flow.dxf"},
        ))
        results["sync_again"] = _payload(await session.call_tool(
            "sync_with_simulation", {"spec": changed, "filename": "flow.dxf"},
        ))
        results["process"] = _payload(await session.call_tool(
            "generate_process_sheet",
            {"sheet": {"name": "PI5 ASSEMBLY", "simulation_id": "SIM-9",
                       "steps": [{"description": "Place PCB", "station": "ST-1"},
                                 {"description": "AOI scan", "inspection": True}]},
             "filename": "process.dxf"},
        ))
        return results

    results = run_scenario(tmp_path, scenario)

    assert results["inspection"] == {
        "file": "flow.dxf", "sidecar": "flow.spec.json",
        "drawing_type": "INSPECTION", "revision": "A", "holes": 2,
    }
    assert results["assembly"]["drawing_type"] == "ASSEMBLY"
    assert results["validate"]["ok"] is True
    assert results["annotate"] == {
        "file": "flow.dxf", "gdt_notes_added": 1, "dimensions_added": 1,
    }
    assert results["sync"]["regenerated"] is True
    assert results["sync"]["previous_revision"] == "A"
    assert results["sync"]["revision"] == "B"
    assert any("diameter: 2.0 -> 2.5" in c for c in results["sync"]["changes"])
    # idempotent second sync: nothing changed, no revision churn
    assert results["sync_again"] == {
        "file": "flow.dxf", "revision": "B", "changes": [], "regenerated": False,
    }
    assert results["process"] == {"file": "process.dxf", "steps": 2, "revision": "A"}

    # ezdxf roundtrip of everything the server wrote
    for name in ("flow.dxf", "asm.dxf", "process.dxf"):
        doc = ezdxf.readfile(tmp_path / name)
        assert doc.dxfversion
    flow = ezdxf.readfile(tmp_path / "flow.dxf").modelspace()
    asm = ezdxf.readfile(tmp_path / "asm.dxf").modelspace()
    assert [e for e in flow if e.dxf.layer == "INSPECTION"]      # balloons present
    assert not [e for e in asm if e.dxf.layer == "INSPECTION"]   # assembly is clean
    sidecar = json.loads((tmp_path / "flow.spec.json").read_text())
    assert sidecar["revision"] == "B"
    assert sidecar["holes"][1]["diameter"] == 2.5


def test_deterministic_errors(tmp_path: Path) -> None:
    async def scenario(session: ClientSession):
        async def error_text(tool: str, args: dict) -> str:
            result = await session.call_tool(tool, args)
            assert result.isError is True, _text(result)
            return _text(result)

        errors = {}
        errors["unknown"] = await error_text("no_such_tool", {})
        errors["schema_1"] = await error_text(
            "generate_inspection_drawing",
            {"spec": {"name": "X", "simulation_id": "S"}, "filename": "x.dxf"},
        )
        errors["schema_2"] = await error_text(
            "generate_inspection_drawing",
            {"spec": {"name": "X", "simulation_id": "S"}, "filename": "x.dxf"},
        )
        errors["extra_prop"] = await error_text(
            "validate_drawing_for_production",
            {"filename": "x.dxf", "surprise": True},
        )
        errors["traversal"] = await error_text(
            "generate_inspection_drawing",
            {"spec": SPEC, "filename": "../escape.dxf"},
        )
        errors["absolute"] = await error_text(
            "generate_inspection_drawing",
            {"spec": SPEC, "filename": "/tmp/escape.dxf"},
        )
        errors["missing"] = await error_text(
            "validate_drawing_for_production", {"filename": "nope.dxf"},
        )
        errors["spec_semantic"] = await error_text(
            "generate_inspection_drawing",
            {"spec": {"name": "X", "simulation_id": "S",
                      "board": {"width": 10, "height": 10, "thickness": 1},
                      "holes": [{"x": 99, "y": 1, "diameter": 1}]},
             "filename": "x.dxf"},
        )
        return errors

    errors = run_scenario(tmp_path, scenario)
    assert errors["unknown"].startswith("UNKNOWN_TOOL:")
    assert errors["schema_1"].startswith("SCHEMA_ERROR: spec:")
    assert errors["schema_1"] == errors["schema_2"]  # deterministic
    assert errors["extra_prop"].startswith("SCHEMA_ERROR:")
    assert errors["traversal"].startswith("PATH_ERROR:")
    assert errors["absolute"].startswith("PATH_ERROR:")
    assert errors["missing"].startswith("FILE_NOT_FOUND:")
    assert errors["spec_semantic"].startswith("SPEC_ERROR:")
    assert "outside the board" in errors["spec_semantic"]
    # nothing escaped the sandbox
    assert not (tmp_path.parent / "escape.dxf").exists()
    assert not Path("/tmp/escape.dxf").exists()


def test_symlink_escape_is_blocked_over_stdio(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    secret = tmp_path / "secret.dxf"
    secret.write_text("outside the sandbox")
    (out_dir / "evil.dxf").symlink_to(secret)

    async def scenario(session: ClientSession):
        return await session.call_tool(
            "add_gdt_and_dimensions",
            {"filename": "evil.dxf", "gdt_notes": ["pwn"]},
        )

    result = run_scenario(out_dir, scenario)
    assert result.isError is True
    assert _text(result).startswith("PATH_ERROR:")
    assert secret.read_text() == "outside the sandbox"  # untouched
