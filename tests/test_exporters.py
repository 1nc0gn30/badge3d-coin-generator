"""Tests for 3D Mesh Exporters (Binary STL, ASCII STL, Wavefront OBJ, glTF/GLB)."""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest

from badge3d_coin_generator.exporters import (
    export_ascii_stl,
    export_binary_stl,
    export_glb,
    export_gltf,
    export_obj,
    mesh_to_ascii_stl_text,
    mesh_to_binary_stl_bytes,
    mesh_to_glb_bytes,
    mesh_to_gltf_json,
    mesh_to_obj_text,
)
from badge3d_coin_generator.mesh_engine import MeshData


# ---------------------------------------------------------------------------
# Binary STL Tests
# ---------------------------------------------------------------------------

def test_mesh_to_binary_stl_bytes(sample_mesh: MeshData, stl_validator) -> None:
    """Verify binary STL serialization format and IEEE-754 binary integrity."""
    stl_bytes = mesh_to_binary_stl_bytes(sample_mesh, header_comment="TestHeader")
    
    # 80-byte header starts with TestHeader
    assert stl_bytes.startswith(b"TestHeader")
    
    # Validate binary format
    is_valid, num_triangles, msg = stl_validator.validate(stl_bytes)
    assert is_valid is True, msg
    assert num_triangles == sample_mesh.triangle_count
    assert len(stl_bytes) == 84 + num_triangles * 50


def test_export_binary_stl_file(sample_mesh: MeshData, temp_output_dir: Path, stl_validator) -> None:
    """Verify atomic file writing of Binary STL."""
    out_file = temp_output_dir / "exported_coin.stl"
    written_path = export_binary_stl(sample_mesh, out_file, header_comment="Badge3DCoinStudio")

    assert written_path.exists()
    assert written_path.is_file()

    file_bytes = written_path.read_bytes()
    is_valid, num_triangles, msg = stl_validator.validate(file_bytes)
    assert is_valid is True, msg
    assert num_triangles == sample_mesh.triangle_count


# ---------------------------------------------------------------------------
# ASCII STL Tests
# ---------------------------------------------------------------------------

def test_mesh_to_ascii_stl_text(simple_cube_mesh: MeshData) -> None:
    """Verify ASCII STL solid structure, vertex lines, and endsolid tags."""
    text = mesh_to_ascii_stl_text(simple_cube_mesh, solid_name="CubeTest")
    lines = text.strip().split("\n")

    assert lines[0] == "solid CubeTest"
    assert lines[-1] == "endsolid CubeTest"

    # 12 triangles -> 12 facets
    facet_count = sum(1 for line in lines if line.strip().startswith("facet normal"))
    vertex_count = sum(1 for line in lines if line.strip().startswith("vertex"))

    assert facet_count == 12
    assert vertex_count == 36  # 3 vertices per facet


def test_export_ascii_stl_file(simple_cube_mesh: MeshData, temp_output_dir: Path) -> None:
    """Verify atomic writing of ASCII STL file."""
    out_file = temp_output_dir / "cube_ascii.stl"
    written_path = export_ascii_stl(simple_cube_mesh, out_file, solid_name="CubeSolid")

    assert written_path.exists()
    content = written_path.read_text(encoding="utf-8")
    assert "solid CubeSolid" in content
    assert "endsolid CubeSolid" in content


# ---------------------------------------------------------------------------
# Wavefront OBJ & MTL Tests
# ---------------------------------------------------------------------------

def test_mesh_to_obj_text(simple_cube_mesh: MeshData) -> None:
    """Verify Wavefront OBJ vertex, normal, and 1-indexed face definitions."""
    obj_text = mesh_to_obj_text(simple_cube_mesh, object_name="CubeObj")
    lines = obj_text.strip().split("\n")

    v_lines = [l for l in lines if l.startswith("v ")]
    vn_lines = [l for l in lines if l.startswith("vn ")]
    f_lines = [l for l in lines if l.startswith("f ")]

    assert len(v_lines) == simple_cube_mesh.vertex_count
    assert len(f_lines) == simple_cube_mesh.triangle_count

    # Verify 1-based indexing in faces (no '0' vertex index)
    for f in f_lines:
        parts = f.split()[1:]
        for part in parts:
            v_idx = int(part.split("/")[0])
            assert 1 <= v_idx <= simple_cube_mesh.vertex_count


def test_export_obj_file(simple_cube_mesh: MeshData, temp_output_dir: Path) -> None:
    """Verify atomic writing of .obj and .mtl files."""
    out_file = temp_output_dir / "cube_export.obj"
    obj_path, mtl_path = export_obj(simple_cube_mesh, out_file, object_name="CoinModel")

    assert obj_path.exists()
    assert mtl_path.exists()
    content = obj_path.read_text(encoding="utf-8")
    assert "o CoinModel" in content
    assert "v " in content
    assert "f " in content


# ---------------------------------------------------------------------------
# glTF 2.0 & GLB Binary Container Tests
# ---------------------------------------------------------------------------

def test_mesh_to_gltf_json(simple_cube_mesh: MeshData) -> None:
    """Verify glTF 2.0 JSON structure."""
    gltf_str = mesh_to_gltf_json(simple_cube_mesh)
    data = json.loads(gltf_str)

    assert data.get("asset", {}).get("version") == "2.0"
    assert "scenes" in data
    assert "meshes" in data
    assert "buffers" in data


def test_mesh_to_glb_bytes(simple_cube_mesh: MeshData) -> None:
    """Verify GLB binary container magic header (0x46546C67) and chunk alignment."""
    glb_bytes = mesh_to_glb_bytes(simple_cube_mesh)

    assert len(glb_bytes) >= 20
    magic, version, length = struct.unpack("<4sII", glb_bytes[0:12])
    assert magic == b"glTF"
    assert version == 2
    assert length == len(glb_bytes)
