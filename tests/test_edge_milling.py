"""Tests for Edge Milling, Rim Inscription, Cryptographic Security Stamp, and MCP Tools."""

import hashlib
import json
import math
import pytest

from badge3d_coin_generator.edge_milling import (
    CompoundMillingSpec,
    EdgeInscriptionSpec,
    SecurityStampSpec,
    SegmentedReedingSpec,
    compute_edge_milling_radius,
    derive_crypto_teeth_pattern,
    evaluate_text_rim_distance,
    generate_edge_milling_profile_summary,
)
from badge3d_coin_generator.mesh_engine import CoinMeshEngine, CoinParameters
from badge3d_coin_generator.mcp_server import MCPServer
from badge3d_coin_generator.cli import main


def test_derive_crypto_teeth_pattern():
    pattern1 = derive_crypto_teeth_pattern("CHALLENGE-COIN-2026", count=64)
    pattern2 = derive_crypto_teeth_pattern("CHALLENGE-COIN-2026", count=64)
    pattern3 = derive_crypto_teeth_pattern("DIFFERENT-COIN", count=64)

    assert len(pattern1) == 64
    assert pattern1 == pattern2  # Deterministic
    assert pattern1 != pattern3  # Distinct seeds produce distinct patterns
    assert all(0.0 <= x <= 1.0 for x in pattern1)


def test_evaluate_text_rim_distance():
    # Empty text gives 0
    assert evaluate_text_rim_distance("", 0.5, 0.5) == 0.0

    # Letter 'I' has vertical stroke at center
    # Local coordinate (0.5, 0.5) in char 'I' should have high intensity
    intensity = evaluate_text_rim_distance("I", 0.5, 0.5)
    assert intensity > 0.0


def test_compute_edge_milling_radius_base():
    base_r = 20.0
    spec = CompoundMillingSpec(
        reeding_profile="sinusoidal",
        reed_count=100,
        reed_depth=0.25,
    )
    # Trough
    r_trough = compute_edge_milling_radius(base_r, math.pi / 100, 0.0, 3.0, spec)
    assert r_trough < base_r
    # Crest
    r_crest = compute_edge_milling_radius(base_r, 0.0, 0.0, 3.0, spec)
    assert math.isclose(r_crest, base_r, abs_tol=1e-4)


def test_compute_edge_milling_radius_segmented():
    base_r = 20.0
    spec = CompoundMillingSpec(
        reed_count=0,
        reed_depth=0.0,
        segmented=SegmentedReedingSpec(
            reeded_sectors=4,
            reeds_per_sector=5,
            reed_depth=0.3,
            marker_groove=True,
        ),
    )
    # Sector 0 is reeded, sector 1 is smooth
    # In sector 1 (theta_norm ~ 0.15), should be base_r
    theta_sector_1 = (2.0 * math.pi) * (1.5 / 8.0)
    r_smooth = compute_edge_milling_radius(base_r, theta_sector_1, 0.0, 3.0, spec)
    assert math.isclose(r_smooth, base_r, abs_tol=1e-4)


def test_compute_edge_milling_radius_security_stamp():
    base_r = 20.0
    spec = CompoundMillingSpec(
        reed_count=0,
        reed_depth=0.0,
        security_stamp=SecurityStampSpec(
            seed="PROOF-OF-WORK-COIN",
            num_grooves=32,
            base_depth=0.2,
            depth_variation=0.1,
        ),
    )
    # Mid-height of cylinder should have groove cut
    r_mid = compute_edge_milling_radius(base_r, 0.1, 0.0, 3.0, spec)
    assert r_mid < base_r
    # Near top edge (outside center band), should be base_r
    r_top = compute_edge_milling_radius(base_r, 0.1, 1.4, 3.0, spec)
    assert math.isclose(r_top, base_r, abs_tol=1e-4)


def test_compute_edge_milling_radius_inscription():
    base_r = 20.0
    spec_incuse = CompoundMillingSpec(
        reed_count=0,
        reed_depth=0.0,
        inscription=EdgeInscriptionSpec(
            text="LIBERTY",
            depth=0.3,
            mode="incuse",
            letter_height_ratio=0.7,
        ),
    )
    r_incuse = compute_edge_milling_radius(base_r, 0.0, 0.0, 3.0, spec_incuse)
    assert r_incuse <= base_r

    spec_raised = CompoundMillingSpec(
        reed_count=0,
        reed_depth=0.0,
        inscription=EdgeInscriptionSpec(
            text="LIBERTY",
            depth=0.3,
            mode="raised",
            letter_height_ratio=0.7,
        ),
    )
    r_raised = compute_edge_milling_radius(base_r, 0.0, 0.0, 3.0, spec_raised)
    assert r_raised >= base_r


def test_generate_edge_milling_profile_summary():
    spec = CompoundMillingSpec(
        reeding_profile="trapezoidal",
        reed_count=80,
        reed_depth=0.2,
        inscription=EdgeInscriptionSpec(text="E PLURIBUS UNUM"),
        security_stamp=SecurityStampSpec(seed="SEC-778"),
        segmented=SegmentedReedingSpec(reeded_sectors=6),
    )
    summary = generate_edge_milling_profile_summary(spec)
    assert summary["reeding_profile"] == "trapezoidal"
    assert summary["has_inscription"] is True
    assert summary["inscription"]["text"] == "E PLURIBUS UNUM"
    assert summary["has_security_stamp"] is True
    assert summary["security_stamp"]["seed"] == "SEC-778"
    assert summary["has_segmented_reeding"] is True


def test_coin_mesh_engine_watertight_with_inscription():
    params = CoinParameters(
        radius=15.0,
        thickness=2.5,
        radial_segments=48,
        field_rings=8,
        edge_inscription="GOLD 2026",
        edge_inscription_depth=0.2,
        edge_inscription_mode="incuse",
    )
    engine = CoinMeshEngine(params)
    mesh = engine.generate()
    assert len(mesh.vertices) > 100
    assert len(mesh.faces) > 100
    assert mesh.is_watertight()


def test_coin_mesh_engine_watertight_with_security_stamp():
    params = CoinParameters(
        radius=15.0,
        thickness=2.5,
        radial_segments=48,
        field_rings=8,
        security_stamp_seed="VERIFIED-GENUINE",
        security_stamp_grooves=32,
    )
    engine = CoinMeshEngine(params)
    mesh = engine.generate()
    assert mesh.is_watertight()


def test_mcp_edge_milling_tools():
    server = MCPServer()

    # 1. coin_generate_edge_profile
    req1 = {
        "jsonrpc": "2.0",
        "id": 101,
        "method": "tools/call",
        "params": {
            "name": "coin_generate_edge_profile",
            "arguments": {
                "inscription": "VERITAS",
                "security_seed": "STAMP-101",
            },
        },
    }
    resp1 = server.handle_request(req1)
    assert resp1 is not None
    data1 = json.loads(resp1["result"]["content"][0]["text"])
    assert data1["has_inscription"] is True
    assert data1["has_security_stamp"] is True

    # 2. coin_stamp_crypto_hash
    req2 = {
        "jsonrpc": "2.0",
        "id": 102,
        "method": "tools/call",
        "params": {
            "name": "coin_stamp_crypto_hash",
            "arguments": {
                "seed": "BITCOIN-TOKEN-01",
                "num_grooves": 32,
            },
        },
    }
    resp2 = server.handle_request(req2)
    assert resp2 is not None
    data2 = json.loads(resp2["result"]["content"][0]["text"])
    assert data2["seed"] == "BITCOIN-TOKEN-01"
    assert "parity_verification_checksum" in data2

    # 3. coin_inscribe_edge_text
    req3 = {
        "jsonrpc": "2.0",
        "id": 103,
        "method": "tools/call",
        "params": {
            "name": "coin_inscribe_edge_text",
            "arguments": {
                "text": "IN GOD WE TRUST",
                "diameter": 38.1,
            },
        },
    }
    resp3 = server.handle_request(req3)
    assert resp3 is not None
    data3 = json.loads(resp3["result"]["content"][0]["text"])
    assert data3["text"] == "IN GOD WE TRUST"
    assert data3["circumference_mm"] > 100.0


def test_cli_edge_command(capsys):
    rc = main(["edge", "-i", "DECUS ET TUTAMEN", "-s", "ROYAL-MINT", "--json"])
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["has_inscription"] is True
    assert data["inscription"]["text"] == "DECUS ET TUTAMEN"
    assert data["has_security_stamp"] is True
