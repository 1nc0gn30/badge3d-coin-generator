"""Tests for Model Context Protocol (MCP) JSON-RPC 2.0 Server."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from badge3d_coin_generator.mcp_server import (
    MCP_PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    TOOLS_DEFINITIONS,
    MCPServer,
)


@pytest.fixture
def mcp_server() -> MCPServer:
    return MCPServer()


def test_mcp_initialize(mcp_server: MCPServer) -> None:
    """Verify MCP initialize handshake returns serverInfo and tools capability."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        },
    }
    resp = mcp_server.handle_request(req)
    assert resp is not None
    assert resp["id"] == 1
    assert "result" in resp
    res = resp["result"]
    assert res["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert res["serverInfo"]["name"] == SERVER_NAME
    assert "tools" in res["capabilities"]


def test_mcp_ping(mcp_server: MCPServer) -> None:
    """Verify MCP ping method."""
    req = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
    resp = mcp_server.handle_request(req)
    assert resp is not None
    assert resp["id"] == 2
    assert resp["result"] == {}


def test_mcp_tools_list(mcp_server: MCPServer) -> None:
    """Verify MCP tools/list returns complete registered tool list."""
    req = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
    resp = mcp_server.handle_request(req)
    assert resp is not None
    tools = resp["result"]["tools"]
    tool_names = {t["name"] for t in tools}

    assert "coin_generate" in tool_names
    assert "coin_export_stl" in tool_names
    assert "coin_export_obj" in tool_names
    assert "coin_presets" in tool_names
    assert "coin_diagnostics" in tool_names


def test_mcp_tool_coin_presets(mcp_server: MCPServer) -> None:
    """Verify tools/call for coin_presets."""
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "coin_presets", "arguments": {}},
    }
    resp = mcp_server.handle_request(req)
    assert resp is not None
    assert "result" in resp
    content = resp["result"]["content"][0]["text"]
    assert "commemorative_gold" in content or "challenge_coin" in content


def test_mcp_tool_coin_generate(mcp_server: MCPServer) -> None:
    """Verify tools/call for coin_generate."""
    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "coin_generate",
            "arguments": {
                "radius": 18.0,
                "thickness": 2.8,
                "rim_width": 1.5,
                "serrations": 40,
                "resolution": 40,
            },
        },
    }
    resp = mcp_server.handle_request(req)
    assert resp is not None
    assert "result" in resp
    text = resp["result"]["content"][0]["text"]
    assert "3D Coin Generated Successfully" in text or "Volume" in text


def test_mcp_tool_coin_export_stl(mcp_server: MCPServer, temp_output_dir: Path, stl_validator) -> None:
    """Verify tools/call for coin_export_stl exports a valid STL."""
    out_file = temp_output_dir / "mcp_coin.stl"
    req = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "coin_export_stl",
            "arguments": {
                "output_path": str(out_file),
                "binary": True,
                "radius": 15.0,
                "thickness": 2.5,
                "resolution": 36,
            },
        },
    }
    resp = mcp_server.handle_request(req)
    assert resp is not None
    assert "result" in resp
    assert out_file.exists()

    file_bytes = out_file.read_bytes()
    is_valid, num_triangles, msg = stl_validator.validate(file_bytes)
    assert is_valid is True, msg


def test_mcp_tool_coin_export_obj(mcp_server: MCPServer, temp_output_dir: Path) -> None:
    """Verify tools/call for coin_export_obj exports a valid OBJ."""
    out_file = temp_output_dir / "mcp_coin.obj"
    req = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "coin_export_obj",
            "arguments": {
                "output_path": str(out_file),
                "radius": 15.0,
                "thickness": 2.5,
                "resolution": 36,
            },
        },
    }
    resp = mcp_server.handle_request(req)
    assert resp is not None
    assert "result" in resp
    assert out_file.exists()
    assert "v " in out_file.read_text(encoding="utf-8")


def test_mcp_tool_coin_diagnostics(mcp_server: MCPServer) -> None:
    """Verify tools/call for coin_diagnostics."""
    req = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {"name": "coin_diagnostics", "arguments": {}},
    }
    resp = mcp_server.handle_request(req)
    assert resp is not None
    text = resp["result"]["content"][0]["text"]
    assert "Python Version" in text or "Platform" in text


def test_mcp_unknown_method_and_tool(mcp_server: MCPServer) -> None:
    """Verify error responses for unknown methods and tool names."""
    # Unknown method
    req_bad_method = {"jsonrpc": "2.0", "id": 9, "method": "invalid/method"}
    resp = mcp_server.handle_request(req_bad_method)
    assert resp is not None
    assert "error" in resp
    assert resp["error"]["code"] == -32601

    # Unknown tool
    req_bad_tool = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {"name": "non_existent_tool", "arguments": {}},
    }
    resp = mcp_server.handle_request(req_bad_tool)
    assert resp is not None
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_mcp_stdio_stream_execution(mcp_server: MCPServer) -> None:
    """Verify executing MCP requests over in-memory text streams."""
    input_str = json.dumps({"jsonrpc": "2.0", "id": 100, "method": "ping"}) + "\n"
    in_stream = io.StringIO(input_str)
    out_stream = io.StringIO()

    mcp_server.run_stdio(in_stream=in_stream, out_stream=out_stream)

    output_lines = out_stream.getvalue().strip().split("\n")
    assert len(output_lines) >= 1
    resp = json.loads(output_lines[0])
    assert resp["id"] == 100
    assert resp["result"] == {}
