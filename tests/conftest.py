"""Shared pytest fixtures and test utilities for badge3d-coin-generator."""

from __future__ import annotations

import os
import struct
import tempfile
from pathlib import Path
from typing import Generator, List, Tuple

import pytest

from badge3d_coin_generator.mesh_engine import (
    CoinMeshEngine,
    CoinParameters,
    MeshData,
    Vec3,
)


@pytest.fixture
def sample_coin_params() -> CoinParameters:
    """Return a standard test coin parameters instance."""
    return CoinParameters(
        radius=20.0,
        thickness=3.0,
        rim_width=2.0,
        rim_height=0.5,
        edge_reed_count=60,
        reed_depth=0.25,
        bevel_width=0.4,
        bevel_height=0.4,
        radial_segments=60,
        field_rings=24,
        relief_depth_obverse=0.5,
        relief_depth_reverse=0.5,
        smooth_shading=True,
    )


@pytest.fixture
def sample_mesh(sample_coin_params: CoinParameters) -> MeshData:
    """Generate and return a sample 3D coin mesh."""
    engine = CoinMeshEngine(sample_coin_params)
    return engine.generate()


@pytest.fixture
def simple_cube_mesh() -> MeshData:
    """Return a minimal closed 12-triangle cube mesh for testing."""
    # 8 vertices
    vertices: List[Vec3] = [
        (-1.0, -1.0, -1.0),
        (1.0, -1.0, -1.0),
        (1.0, 1.0, -1.0),
        (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0),
        (1.0, -1.0, 1.0),
        (1.0, 1.0, 1.0),
        (-1.0, 1.0, 1.0),
    ]
    # 12 triangular faces
    faces = [
        (0, 2, 1), (0, 3, 2),  # Bottom (-Z)
        (4, 5, 6), (4, 6, 7),  # Top (+Z)
        (0, 1, 5), (0, 5, 4),  # Front (-Y)
        (2, 3, 7), (2, 7, 6),  # Back (+Y)
        (0, 4, 7), (0, 7, 3),  # Left (-X)
        (1, 2, 6), (1, 6, 5),  # Right (+X)
    ]
    mesh = MeshData(vertices=vertices, faces=faces)
    mesh.compute_normals(smooth=False)
    return mesh


@pytest.fixture
def sample_svg_text() -> str:
    """Return a standard test SVG string containing various geometric and path elements."""
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
  <circle cx="50" cy="50" r="40" fill="#000000" />
  <rect x="25" y="25" width="50" height="50" fill="#ffffff" />
  <path d="M 50 15 L 60 40 L 85 40 L 65 55 L 72 80 L 50 65 L 28 80 L 35 55 L 15 40 L 40 40 Z" fill="#000000" />
</svg>"""


@pytest.fixture
def sample_heightmap_matrix() -> List[List[float]]:
    """Return a 16x16 test elevation heightmap matrix."""
    size = 16
    grid: List[List[float]] = []
    for r in range(size):
        row: List[float] = []
        for c in range(size):
            # Centered circular gradient
            dr = (r - 7.5) / 7.5
            dc = (c - 7.5) / 7.5
            dist = (dr * dr + dc * dc) ** 0.5
            val = max(0.0, 1.0 - dist)
            row.append(val)
        grid.append(row)
    return grid


@pytest.fixture
def temp_output_dir() -> Generator[Path, None, None]:
    """Provide a clean temporary directory for file export testing."""
    with tempfile.TemporaryDirectory(prefix="badge3d_test_") as tmpdir:
        yield Path(tmpdir).resolve()


class BinarySTLValidator:
    """Helper to validate binary STL structure and IEEE-754 binary integrity."""

    @staticmethod
    def validate(stl_bytes: bytes) -> Tuple[bool, int, str]:
        if len(stl_bytes) < 84:
            return False, 0, f"File too small: {len(stl_bytes)} bytes"

        num_triangles = struct.unpack("<I", stl_bytes[80:84])[0]
        expected_size = 84 + num_triangles * 50

        if len(stl_bytes) != expected_size:
            return (
                False,
                num_triangles,
                f"Size mismatch: expected {expected_size} bytes for {num_triangles} triangles, got {len(stl_bytes)} bytes",
            )

        # Check attributes and float sanity for first few triangles
        for i in range(min(num_triangles, 20)):
            offset = 84 + i * 50
            floats = struct.unpack("<12f", stl_bytes[offset : offset + 48])
            for f in floats:
                if f != f or abs(f) > 1e9:  # NaN check
                    return False, num_triangles, f"Invalid float value: {f} at triangle {i}"

            attr = struct.unpack("<H", stl_bytes[offset + 48 : offset + 50])[0]
            if attr != 0:
                return False, num_triangles, f"Non-zero attribute byte count: {attr} at triangle {i}"

        return True, num_triangles, "Valid binary STL"


@pytest.fixture
def stl_validator() -> BinarySTLValidator:
    return BinarySTLValidator()
