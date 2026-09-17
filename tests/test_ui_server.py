"""Tests for Google 3D Coin Studio UI Server and REST API endpoints."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Generator, Tuple

import pytest

from badge3d_coin_generator.mesh_engine import CoinParameters
from badge3d_coin_generator.ui_server import (
    STUDIO_PRESETS,
    compute_physical_statistics,
    create_ui_server,
    parse_coin_params_from_dict,
)


# ---------------------------------------------------------------------------
# Unit Tests for Helper Functions
# ---------------------------------------------------------------------------

def test_parse_coin_params_from_dict_defaults() -> None:
    """Verify default parameter parsing when empty dict provided."""
    params = parse_coin_params_from_dict({})
    assert isinstance(params, CoinParameters)
    assert params.radius == 20.0
    assert params.thickness == 3.0
    assert params.rim_width == 1.8


def test_parse_coin_params_from_preset() -> None:
    """Verify loading base parameters from a preset key."""
    params = parse_coin_params_from_dict({"preset": "challenge_coin", "radius": 22.0})
    assert params.radius == 22.0  # Overridden
    assert params.edge_reed_count == 80  # From preset
    assert params.thickness == 3.5  # From preset


def test_parse_coin_params_camel_case() -> None:
    """Verify camelCase frontend parameter keys are properly mapped."""
    data = {
        "rimWidth": 2.5,
        "rimHeight": 0.9,
        "rimBevel": 0.5,
        "serrations": 96,
        "serrationDepth": 0.4,
        "reliefDepth": 0.7,
    }
    params = parse_coin_params_from_dict(data)
    assert params.rim_width == 2.5
    assert params.rim_height == 0.9
    assert params.bevel_width == 0.5
    assert params.edge_reed_count == 96
    assert params.reed_depth == 0.4
    assert params.relief_depth_obverse == 0.7


def test_compute_physical_statistics(sample_mesh) -> None:
    """Verify physical volume, metal mass, and slicing calculations."""
    params = CoinParameters(radius=20.0, thickness=3.0, rim_width=2.0, rim_height=0.5)
    stats = compute_physical_statistics(params, mesh=sample_mesh)

    assert "dimensions_mm" in stats
    assert stats["dimensions_mm"]["diameter"] == 40.0
    assert "volume_cm3" in stats
    assert stats["volume_cm3"] > 0.0

    # Weights
    weights = stats["weights_grams"]
    assert "gold_24k" in weights
    assert "silver_925" in weights
    assert "bronze_c932" in weights
    assert "titanium_gr5" in weights
    assert "pla_filament" in weights
    assert weights["gold_24k"] > weights["silver_925"] > weights["pla_filament"]

    # Mesh stats
    assert "mesh" in stats
    assert stats["mesh"]["triangle_count"] == sample_mesh.triangle_count
    assert stats["mesh"]["is_watertight"] is True


# ---------------------------------------------------------------------------
# Integration Tests for Live HTTP Server & REST Endpoints
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live_server() -> Generator[str, None, None]:
    """Start a real ThreadingHTTPServer on an ephemeral port in a background thread."""
    # Port 0 selects an available dynamic port
    server = create_ui_server(host="127.0.0.1", port=0)
    assigned_port = server.server_address[1]
    base_url = f"http://127.0.0.1:{assigned_port}"

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.1)  # Brief warm-up

    yield base_url

    server.shutdown()
    server.server_close()
    server_thread.join(timeout=2.0)


def test_http_get_health(live_server: str) -> None:
    """Test GET /health and /api/health."""
    req = urllib.request.Request(f"{live_server}/api/health")
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data.get("status") == "ok"
        assert data.get("service") == "badge3d-coin-generator"


def test_http_get_presets(live_server: str) -> None:
    """Test GET /api/presets."""
    req = urllib.request.Request(f"{live_server}/api/presets")
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "presets" in data
        assert "challenge_coin" in data["presets"]
        assert "crypto_token" in data["presets"]


def test_http_get_stats_query(live_server: str) -> None:
    """Test GET /api/stats with query parameters."""
    req = urllib.request.Request(f"{live_server}/api/stats?radius=20.0&thickness=3.0")
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["dimensions_mm"]["diameter"] == 40.0
        assert data["volume_cm3"] > 0.0


def test_http_get_root_index_html(live_server: str) -> None:
    """Test GET / serves Google 3D Coin Studio UI HTML."""
    req = urllib.request.Request(f"{live_server}/")
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        assert resp.status == 200
        content = resp.read().decode("utf-8")
        assert "Google 3D Coin Studio" in content or "Badge3D" in content


def test_http_post_generate_mesh(live_server: str) -> None:
    """Test POST /api/generate mesh calculation."""
    payload = json.dumps({
        "radius": 18.0,
        "thickness": 2.8,
        "rim_width": 1.5,
        "rim_height": 0.5,
        "radial_segments": 40,
        "field_rings": 12,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{live_server}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data.get("status") == "success"
        assert "statistics" in data
        assert data["statistics"]["mesh"]["triangle_count"] > 100


def test_http_post_export_stl(live_server: str, stl_validator) -> None:
    """Test POST /api/export-stl returns valid binary STL bytes."""
    payload = json.dumps({
        "radius": 15.0,
        "thickness": 2.5,
        "radial_segments": 40,
        "field_rings": 12,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{live_server}/api/export-stl",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        assert resp.status == 200
        assert resp.headers.get("Content-Type") == "application/sla"
        stl_bytes = resp.read()

        is_valid, num_triangles, msg = stl_validator.validate(stl_bytes)
        assert is_valid is True, msg
        assert num_triangles > 50


def test_http_post_export_obj(live_server: str) -> None:
    """Test POST /api/export-obj returns valid Wavefront OBJ text."""
    payload = json.dumps({
        "radius": 15.0,
        "thickness": 2.5,
        "radial_segments": 40,
        "field_rings": 12,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{live_server}/api/export-obj",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        assert resp.status == 200
        assert "text/plain" in resp.headers.get("Content-Type", "")
        obj_text = resp.read().decode("utf-8")
        assert "v " in obj_text
        assert "f " in obj_text
