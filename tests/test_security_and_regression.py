"""Comprehensive Security, Protocol Hygiene & Functional Regression Suite (v2.6.0).

Covers every P0/P1/P2 finding from Whiteboard Audit #019:
- Static path traversal closure (../, %2e%2e, null bytes, symlink escapes)
- Strict loopback Host & Origin allowlists, Vary: Origin, zero wildcard CORS
- Security headers (X-Content-Type-Options, Referrer-Policy, CSP frame-ancestors)
- Request body 1 MiB cap (413), invalid Content-Length (400), malformed/non-dict JSON (400)
- HEAD / /health /api/health (200, 0 B), unknown /api/* (404 JSON), /terms /privacy /support (200)
- Finite numeric bounds & geometry/slicer DoS caps (NaN, Inf, negative, layer_height=0 -> 400)
- Unified preset resolution (Studio + Legacy IDs) across REST, CLI & MCP
- SVG rasterizer safety (<!DOCTYPE, <!ENTITY, <script>, on*=, non-<svg>, bad viewBox/hex)
- MCP JSON-RPC 2.0 resilience (-32600 non-dict/empty batch, -32602 params:null/bad args, traceback redaction, export path containment)
- G-code perimeter extrusion math accuracy (emitted E matches total_filament_mm within 2%)
"""

from __future__ import annotations

import http.client
import io
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Generator, Tuple

import pytest

from badge3d_coin_generator import (
    COIN_PRESETS,
    STUDIO_PRESET_MAP,
    CoinGenerator,
    SlicingConfig,
    __version__,
    resolve_preset,
    slice_coin,
)
from badge3d_coin_generator.mcp_server import MCPServer
from badge3d_coin_generator.svg_rasterizer import SVGRasterizer
from badge3d_coin_generator.ui_server import MAX_BODY_BYTES, create_ui_server


@pytest.fixture(scope="module")
def hardened_server() -> Generator[Tuple[str, int], None, None]:
    server = create_ui_server(host="127.0.0.1", port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    yield f"http://127.0.0.1:{port}", port
    server.shutdown()
    server.server_close()
    thread.join(timeout=2.0)


def _raw_http(port: int, raw_request: bytes) -> Tuple[int, dict, bytes]:
    with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
        sock.sendall(raw_request)
        sock.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
    raw = b"".join(chunks)
    header_blob, _, body = raw.partition(b"\r\n\r\n")
    lines = header_blob.decode("iso-8859-1", errors="replace").split("\r\n")
    status = int(lines[0].split(" ", 2)[1])
    headers = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return status, headers, body


# ---------------------------------------------------------------------------
# 1. Static Path Traversal & Symlink Containment
# ---------------------------------------------------------------------------

def test_static_path_traversal_blocked(hardened_server: Tuple[str, int]) -> None:
    _, port = hardened_server
    for target in (
        "/../server.py",
        "/../pyproject.toml",
        "/%2e%2e/pyproject.toml",
        "/%252e%252e/server.py",
        "/../../etc/passwd",
        "/assets/../../server.py",
        "/index.html%00.png",
    ):
        req = f"GET {target} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode()
        status, headers, body = _raw_http(port, req)
        assert status in (400, 403, 404), f"Expected block for {target}, got {status}"
        assert b"Badge3D Coin Generator" not in body or status == 403
        assert b"[project]" not in body
        assert b"start_ui_server" not in body


def test_symlink_escape_blocked(tmp_path: Path) -> None:
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("TOP_SECRET_VALUE", encoding="utf-8")
    pub_dir = tmp_path / "public"
    pub_dir.mkdir()
    (pub_dir / "index.html").write_text("<h1>OK</h1>", encoding="utf-8")
    escape_link = pub_dir / "leak.txt"
    escape_link.symlink_to(secret_file)

    server = create_ui_server(host="127.0.0.1", port=0, public_dir=pub_dir)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.05)
    try:
        req = f"GET /leak.txt HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode()
        status, _, body = _raw_http(port, req)
        assert status == 403
        assert b"TOP_SECRET_VALUE" not in body
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=2.0)


# ---------------------------------------------------------------------------
# 2. Host Allowlist, Origin Allowlist, Vary: Origin & Security Headers
# ---------------------------------------------------------------------------

def test_untrusted_host_rejected(hardened_server: Tuple[str, int]) -> None:
    _, port = hardened_server
    for method in ("GET", "HEAD", "POST", "OPTIONS"):
        req = f"{method} /api/health HTTP/1.1\r\nHost: evil.example.invalid\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode()
        status, headers, _ = _raw_http(port, req)
        assert status == 403, f"{method} with evil Host returned {status}"
        assert "access-control-allow-origin" not in headers


def test_origin_allowlist_and_no_wildcard_cors(hardened_server: Tuple[str, int]) -> None:
    _, port = hardened_server

    # Allowed origin reflects exact match (never '*')
    allowed_origin = "http://127.0.0.1:3000"
    req_ok = (
        f"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
        f"Origin: {allowed_origin}\r\nConnection: close\r\n\r\n"
    ).encode()
    status, headers, _ = _raw_http(port, req_ok)
    assert status == 200
    assert headers.get("access-control-allow-origin") == allowed_origin
    assert headers.get("access-control-allow-origin") != "*"
    assert "origin" in headers.get("vary", "").lower()

    # Untrusted & spoofed origins denied with 403 and zero ACAO
    for bad_origin in (
        "https://evil.example.invalid",
        f"http://127.0.0.1:{port}.example.invalid",
        "http://127.0.0.1:8084.evil.test",
    ):
        for method in ("GET", "POST", "OPTIONS"):
            req_bad = (
                f"{method} /api/presets HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                f"Origin: {bad_origin}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            ).encode()
            st, hdrs, _ = _raw_http(port, req_bad)
            assert st == 403, f"{method} with Origin {bad_origin} got {st}"
            assert "access-control-allow-origin" not in hdrs
            assert "origin" in hdrs.get("vary", "").lower()


def test_security_headers_present(hardened_server: Tuple[str, int]) -> None:
    _, port = hardened_server
    for path in ("/", "/api/health", "/terms", "/privacy", "/support"):
        req = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode()
        status, headers, _ = _raw_http(port, req)
        assert status == 200, f"GET {path} returned {status}"
        assert headers.get("x-content-type-options") == "nosniff"
        assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        csp = headers.get("content-security-policy", "")
        assert "frame-ancestors" in csp
        assert "http://127.0.0.1:3000" in csp
        assert "origin" in headers.get("vary", "").lower()


# ---------------------------------------------------------------------------
# 3. Body Cap (413), Invalid Content-Length (400), JSON Validation, HEAD & 404
# ---------------------------------------------------------------------------

def test_body_cap_and_malformed_json(hardened_server: Tuple[str, int]) -> None:
    _, port = hardened_server

    # > 1 MiB returns 413 without reading entire oversized payload
    oversized = MAX_BODY_BYTES + 1024
    req_413 = (
        f"POST /api/generate HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
        f"Content-Type: application/json\r\nContent-Length: {oversized}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()
    status, _, body = _raw_http(port, req_413)
    assert status == 413
    assert "error" in json.loads(body.decode("utf-8"))

    # Invalid Content-Length returns 400 cleanly
    req_bad_cl = (
        f"POST /api/generate HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
        f"Content-Type: application/json\r\nContent-Length: abc\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()
    status, _, body = _raw_http(port, req_bad_cl)
    assert status == 400
    assert "error" in json.loads(body.decode("utf-8"))

    # Malformed & non-dict JSON return 400
    for payload in (b"{broken", b"[]", b"null", b"123", b'"str"'):
        req_json = (
            f"POST /api/generate HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(payload)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode() + payload
        st, _, b = _raw_http(port, req_json)
        assert st == 400, f"Payload {payload!r} returned {st}"
        assert "error" in json.loads(b.decode("utf-8"))


def test_head_and_unknown_api_404_json(hardened_server: Tuple[str, int]) -> None:
    _, port = hardened_server
    for path in ("/", "/health", "/api/health"):
        req = f"HEAD {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode()
        st, hdrs, body = _raw_http(port, req)
        assert st == 200
        assert body == b""

    req_404 = f"GET /api/nonexistent-endpoint HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode()
    st, hdrs, body = _raw_http(port, req_404)
    assert st == 404
    assert "application/json" in hdrs.get("content-type", "")
    assert "error" in json.loads(body.decode("utf-8"))


# ---------------------------------------------------------------------------
# 4. Finite Numeric Bounds & Unified Presets
# ---------------------------------------------------------------------------

def test_numeric_bounds_and_dos_caps(hardened_server: Tuple[str, int]) -> None:
    base_url, port = hardened_server
    for qs in (
        "radius=abc",
        "radius=nan",
        "radius=inf",
        "radius=-10&thickness=-5",
        "radius=5000",
    ):
        req = f"GET /api/stats?{qs} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode()
        st, _, body = _raw_http(port, req)
        assert st == 400, f"Query {qs} returned {st}: {body!r}"
        assert "error" in json.loads(body.decode("utf-8"))

    # layer_height=0 and oversized radial_segments rejected with 400
    for ep, payload in (
        ("/api/slice-gcode", {"radius": 15, "thickness": 2, "layer_height": 0}),
        ("/api/slice-gcode", {"radius": 15, "thickness": 2, "layer_height": 0.0001}),
        ("/api/generate", {"radius": 20, "radial_segments": 50000}),
        ("/api/edge/crypto-stamp", {"seed": "TEST", "num_grooves": 99999}),
    ):
        raw = json.dumps(payload).encode("utf-8")
        req = (
            f"POST {ep} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(raw)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode() + raw
        st, _, body = _raw_http(port, req)
        assert st == 400, f"POST {ep} {payload} returned {st}"


def test_unified_presets_rest_and_mcp(hardened_server: Tuple[str, int]) -> None:
    _, port = hardened_server
    all_preset_ids = list(STUDIO_PRESET_MAP.keys()) + list(COIN_PRESETS.keys())
    for pid in all_preset_ids:
        assert resolve_preset(pid) is not None, f"Preset {pid} failed resolve_preset"

    # REST /api/slice-gcode with studio preset crypto_token
    raw = json.dumps({
        "preset": "crypto_token",
        "layer_height": 0.4,
        "infill_density": 0.2,
        "format": "gcode",
    }).encode("utf-8")
    req = (
        f"POST /api/slice-gcode HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
        f"Content-Type: application/json\r\nContent-Length: {len(raw)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode() + raw
    st, hdrs, body = _raw_http(port, req)
    assert st == 200
    assert "text/x-gcode" in hdrs.get("content-type", "")
    assert b"G28" in body

    # MCP coin_slice_gcode with studio preset crypto_token
    mcp = MCPServer()
    resp = mcp.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "coin_slice_gcode",
            "arguments": {"preset": "crypto_token", "layer_height": 0.5, "format": "json"},
        },
    })
    assert resp is not None
    assert resp["result"]["isError"] is False


# ---------------------------------------------------------------------------
# 5. SVG Rasterizer Hardening
# ---------------------------------------------------------------------------

def test_svg_rasterizer_security_and_edge_cases() -> None:
    with pytest.raises(ValueError):
        SVGRasterizer(target_width=4, target_height=64)
    with pytest.raises(ValueError):
        SVGRasterizer(target_width=4096, target_height=64)

    rast = SVGRasterizer(target_width=64, target_height=64)
    for bad_svg in (
        '<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><svg viewBox="0 0 100 100"/>',
        '<svg viewBox="0 0 100 100"><script>alert(1)</script></svg>',
        '<svg viewBox="0 0 100 100" onload="alert(1)"><circle cx="50" cy="50" r="20"/></svg>',
        '<svg viewBox="0 0 100 100"><a href="javascript:alert(1)"><circle cx="50" cy="50" r="20"/></a></svg>',
        '<html><body>not svg</body></html>',
        '<svg viewBox="0 0 100"><circle cx="50" cy="50" r="20"/></svg>',
    ):
        with pytest.raises(ValueError):
            rast.rasterize_svg_string(bad_svg, bevel_relief=False)

    # Empty width/height & bad hex color must not crash
    hm = rast.rasterize_svg_string('<svg width="" height=""><circle cx="32" cy="32" r="12" fill="#ZZZZZZ"/></svg>', bevel_relief=False)
    assert hm.width == 64 and hm.height == 64


# ---------------------------------------------------------------------------
# 6. MCP JSON-RPC 2.0 Hardening & Export Path Containment
# ---------------------------------------------------------------------------

def test_mcp_resilience_and_path_containment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mcp = MCPServer()
    # Non-dict JSON, empty batch, null params, bad arguments — server MUST survive all and respond to final ping!
    lines = [
        "null",
        "42",
        '"hello"',
        "[]",
        json.dumps({"jsonrpc": "2.0", "id": 10, "method": "initialize", "params": None}),
        json.dumps({"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": None}),
        json.dumps({"jsonrpc": "2.0", "id": 12, "method": "tools/call", "params": {"name": "coin_generate", "arguments": "not-a-dict"}}),
        json.dumps({"jsonrpc": "2.0", "id": 13, "method": "ping"}),
    ]
    in_s = io.StringIO("\n".join(lines) + "\n")
    out_s = io.StringIO()
    mcp.run_stdio(in_stream=in_s, out_stream=out_s)
    responses = [json.loads(ln) for ln in out_s.getvalue().strip().splitlines()]
    assert len(responses) == 8
    assert responses[0]["error"]["code"] == -32600
    assert responses[1]["error"]["code"] == -32600
    assert responses[2]["error"]["code"] == -32600
    assert responses[3]["error"]["code"] == -32600
    assert responses[4]["error"]["code"] == -32602
    assert responses[5]["error"]["code"] == -32602
    assert responses[6]["error"]["code"] == -32602
    assert responses[7]["id"] == 13 and responses[7]["result"] == {}

    # Export path containment via BADGE3D_EXPORT_DIR
    export_dir = tmp_path / "safe_exports"
    export_dir.mkdir()
    monkeypatch.setenv("BADGE3D_EXPORT_DIR", str(export_dir))

    # Escape attempt must fail cleanly without traceback
    escape_resp = mcp.handle_request({
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {
            "name": "coin_export_stl",
            "arguments": {"output_path": "../escape.stl", "radius": 15, "thickness": 2, "resolution": 32},
        },
    })
    assert escape_resp is not None
    assert escape_resp["result"]["isError"] is True
    err_text = escape_resp["result"]["content"][0]["text"]
    assert "Traceback" not in err_text
    assert not (tmp_path / "escape.stl").exists()


# ---------------------------------------------------------------------------
# 7. G-Code Perimeter Extrusion Math Accuracy (Closes 21.3x Over-Extrusion Bug)
# ---------------------------------------------------------------------------

def test_gcode_extrusion_matches_computed_filament_within_2_percent() -> None:
    gen = CoinGenerator(radius=15.0, thickness=2.0, resolution=32)
    cfg = SlicingConfig(layer_height=0.5, infill_density=0.25)
    result = slice_coin(gen, config=cfg)
    gcode = result.to_gcode()

    # Extract final positive extrusion value E after G92 E0 reset
    e_values = []
    after_reset = False
    for line in gcode.splitlines():
        if line.startswith("G92 E0"):
            after_reset = True
            e_values.clear()
            continue
        if after_reset and line.startswith("G1 "):
            m = re.search(r"\bE([0-9]+\.[0-9]+)", line)
            if m:
                e_values.append(float(m.group(1)))

    assert e_values, "Expected G1 extrusion lines in synthesized G-code"
    final_e = e_values[-1]
    assert result.total_filament_mm > 0.0
    rel_err = abs(final_e - result.total_filament_mm) / result.total_filament_mm
    assert rel_err < 0.02, f"Final G-code E={final_e:.4f} diverged from total_filament_mm={result.total_filament_mm:.4f} (rel_err={rel_err:.4%})"


def test_version_is_2_6_0() -> None:
    assert __version__ == "2.6.0"
