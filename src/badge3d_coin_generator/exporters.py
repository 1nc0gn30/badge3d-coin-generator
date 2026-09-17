"""Pure Python 3D Mesh Exporters for badge3d-coin-generator.

Supports exporting MeshData into:
1. Binary STL (.stl) - Standard IEEE 754 32-bit Little-Endian for 3D slicing software (Cura, PrusaSlicer, Bambu Studio).
2. ASCII STL (.stl) - Text-based STL solid format.
3. Wavefront OBJ (.obj & .mtl) - Full 3D geometry with normals, UVs, and PBR/Blinn-Phong material properties.
4. glTF 2.0 (.gltf) - WebGL JSON format with embedded base64 buffer.
5. GLB Binary Container (.glb) - Standard single-file binary container for WebGL, Three.js, Babylon.js, Model-Viewer.

Zero external dependencies (100% Python Standard Library).
"""

from __future__ import annotations

import base64
import json
import os
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .compat import PathLike, atomic_write_bytes, atomic_write_text, ensure_parent_dir, safe_path
from .mesh_engine import MeshData, triangle_normal, vec3_cross, vec3_normalize, vec3_sub


# ---------------------------------------------------------------------------
# 1. Binary STL Exporter
# ---------------------------------------------------------------------------

def mesh_to_binary_stl_bytes(mesh: MeshData, header_comment: str = "badge3d-coin-generator") -> bytes:
    """Serialize a MeshData instance into binary STL format bytes.

    Specification:
    - 80-byte header
    - 4-byte uint32 (number of triangles, little-endian)
    - For each triangle (50 bytes):
      - 3 x 4-byte float32: Normal vector (nx, ny, nz)
      - 3 x 4-byte float32: Vertex 1 (x, y, z)
      - 3 x 4-byte float32: Vertex 2 (x, y, z)
      - 3 x 4-byte float32: Vertex 3 (x, y, z)
      - 2-byte uint16: Attribute byte count (0)
    """
    # 80-byte header
    header_bytes = header_comment.encode("ascii", errors="replace")[:80]
    header = header_bytes.ljust(80, b"\x00")

    num_triangles = len(mesh.faces)
    buffer = bytearray(80 + 4 + num_triangles * 50)
    buffer[0:80] = header
    struct.pack_into("<I", buffer, 80, num_triangles)

    offset = 84
    has_precomputed_normals = len(mesh.normals) == len(mesh.vertices)

    for i0, i1, i2 in mesh.faces:
        v0 = mesh.vertices[i0]
        v1 = mesh.vertices[i1]
        v2 = mesh.vertices[i2]

        # Calculate face geometric normal
        if has_precomputed_normals:
            # Average the 3 vertex normals or compute geometric face normal
            fn = triangle_normal(v0, v1, v2)
        else:
            fn = triangle_normal(v0, v1, v2)

        # Pack normal + 3 vertices + attribute byte count (50 bytes)
        struct.pack_into(
            "<3f3f3f3fH",
            buffer,
            offset,
            fn[0], fn[1], fn[2],
            v0[0], v0[1], v0[2],
            v1[0], v1[1], v1[2],
            v2[0], v2[1], v2[2],
            0,
        )
        offset += 50

    return bytes(buffer)


def export_binary_stl(
    mesh: MeshData,
    filepath: PathLike,
    header_comment: str = "badge3d-coin-generator",
) -> Path:
    """Export a MeshData instance as a Binary STL file atomically."""
    raw_bytes = mesh_to_binary_stl_bytes(mesh, header_comment=header_comment)
    return atomic_write_bytes(filepath, raw_bytes)


# ---------------------------------------------------------------------------
# 2. ASCII STL Exporter
# ---------------------------------------------------------------------------

def mesh_to_ascii_stl_text(mesh: MeshData, solid_name: str = "coin") -> str:
    """Serialize a MeshData instance into ASCII STL format text."""
    lines: List[str] = [f"solid {solid_name}"]

    for i0, i1, i2 in mesh.faces:
        v0 = mesh.vertices[i0]
        v1 = mesh.vertices[i1]
        v2 = mesh.vertices[i2]
        fn = triangle_normal(v0, v1, v2)

        lines.append(f"  facet normal {fn[0]:.6e} {fn[1]:.6e} {fn[2]:.6e}")
        lines.append("    outer loop")
        lines.append(f"      vertex {v0[0]:.6e} {v0[1]:.6e} {v0[2]:.6e}")
        lines.append(f"      vertex {v1[0]:.6e} {v1[1]:.6e} {v1[2]:.6e}")
        lines.append(f"      vertex {v2[0]:.6e} {v2[1]:.6e} {v2[2]:.6e}")
        lines.append("    endloop")
        lines.append("  endfacet")

    lines.append(f"endsolid {solid_name}\n")
    return "\n".join(lines)


def export_ascii_stl(
    mesh: MeshData,
    filepath: PathLike,
    solid_name: str = "coin",
) -> Path:
    """Export a MeshData instance as an ASCII STL file atomically."""
    text = mesh_to_ascii_stl_text(mesh, solid_name=solid_name)
    return atomic_write_text(filepath, text, encoding="utf-8")


# ---------------------------------------------------------------------------
# 3. Wavefront OBJ & MTL Exporter
# ---------------------------------------------------------------------------

def generate_mtl_text(
    material_name: str = "CoinGold",
    ambient: Tuple[float, float, float] = (0.2, 0.2, 0.2),
    diffuse: Tuple[float, float, float] = (0.85, 0.65, 0.13),
    specular: Tuple[float, float, float] = (0.95, 0.90, 0.70),
    shininess: float = 128.0,
    opacity: float = 1.0,
) -> str:
    """Generate Wavefront Material (.mtl) file content."""
    lines = [
        f"# Material generated by badge3d-coin-generator",
        f"newmtl {material_name}",
        f"Ka {ambient[0]:.4f} {ambient[1]:.4f} {ambient[2]:.4f}",
        f"Kd {diffuse[0]:.4f} {diffuse[1]:.4f} {diffuse[2]:.4f}",
        f"Ks {specular[0]:.4f} {specular[1]:.4f} {specular[2]:.4f}",
        f"Ns {shininess:.2f}",
        f"d {opacity:.4f}",
        f"illum 2\n",
    ]
    return "\n".join(lines)


def mesh_to_obj_text(
    mesh: MeshData,
    object_name: str = "coin",
    mtl_filename: Optional[str] = None,
    material_name: Optional[str] = "CoinGold",
) -> str:
    """Serialize a MeshData instance into Wavefront OBJ format text."""
    lines: List[str] = [
        f"# Wavefront OBJ exported by badge3d-coin-generator",
        f"o {object_name}",
    ]

    if mtl_filename:
        lines.append(f"mtllib {mtl_filename}")

    # Write vertex positions
    for x, y, z in mesh.vertices:
        lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")

    # Write texture coordinates (UVs)
    has_uvs = len(mesh.uvs) == len(mesh.vertices)
    if has_uvs:
        for u, v in mesh.uvs:
            lines.append(f"vt {u:.6f} {v:.6f}")

    # Write normals
    has_normals = len(mesh.normals) == len(mesh.vertices)
    if has_normals:
        for nx, ny, nz in mesh.normals:
            lines.append(f"vn {nx:.6f} {ny:.6f} {nz:.6f}")

    if material_name:
        lines.append(f"usemtl {material_name}")
    lines.append("s 1")

    # Write faces (1-indexed in OBJ)
    for i0, i1, i2 in mesh.faces:
        idx0 = i0 + 1
        idx1 = i1 + 1
        idx2 = i2 + 1
        if has_uvs and has_normals:
            lines.append(f"f {idx0}/{idx0}/{idx0} {idx1}/{idx1}/{idx1} {idx2}/{idx2}/{idx2}")
        elif has_normals:
            lines.append(f"f {idx0}//{idx0} {idx1}//{idx1} {idx2}//{idx2}")
        elif has_uvs:
            lines.append(f"f {idx0}/{idx0} {idx1}/{idx1} {idx2}/{idx2}")
        else:
            lines.append(f"f {idx0} {idx1} {idx2}")

    lines.append("")
    return "\n".join(lines)


def export_obj(
    mesh: MeshData,
    filepath: PathLike,
    object_name: str = "coin",
    material_name: str = "CoinGold",
    write_mtl: bool = True,
    mtl_diffuse: Tuple[float, float, float] = (0.85, 0.65, 0.13),
) -> Tuple[Path, Optional[Path]]:
    """Export a MeshData instance as OBJ and optional MTL material file atomically."""
    dest_path = safe_path(filepath)
    mtl_path: Optional[Path] = None
    mtl_name: Optional[str] = None

    if write_mtl:
        mtl_path = dest_path.with_suffix(".mtl")
        mtl_name = mtl_path.name
        mtl_text = generate_mtl_text(material_name=material_name, diffuse=mtl_diffuse)
        atomic_write_text(mtl_path, mtl_text)

    obj_text = mesh_to_obj_text(
        mesh,
        object_name=object_name,
        mtl_filename=mtl_name,
        material_name=material_name if write_mtl else None,
    )
    written_obj = atomic_write_text(dest_path, obj_text)
    return (written_obj, mtl_path)


# ---------------------------------------------------------------------------
# 4. GLTF 2.0 & GLB Binary Container Exporters
# ---------------------------------------------------------------------------

def _build_gltf_binary_payload(
    mesh: MeshData,
) -> Tuple[bytes, Dict[str, Any]]:
    """Construct packed binary buffers and GLTF 2.0 descriptor dictionary."""
    num_verts = len(mesh.vertices)
    num_faces = len(mesh.faces)
    num_indices = num_faces * 3

    # Ensure normals and UVs match vertex count
    normals = mesh.normals if len(mesh.normals) == num_verts else [(0.0, 0.0, 1.0)] * num_verts
    uvs = mesh.uvs if len(mesh.uvs) == num_verts else [(0.0, 0.0)] * num_verts

    # Calculate bounding box for POSITION accessor
    min_pt, max_pt = mesh.get_bounding_box()

    # 1. Position buffer (Vec3 float32 = 12 bytes per vertex)
    pos_bytes = bytearray(num_verts * 12)
    for i, (x, y, z) in enumerate(mesh.vertices):
        struct.pack_into("<3f", pos_bytes, i * 12, x, y, z)

    # 2. Normal buffer (Vec3 float32 = 12 bytes per vertex)
    norm_bytes = bytearray(num_verts * 12)
    for i, (nx, ny, nz) in enumerate(normals):
        struct.pack_into("<3f", norm_bytes, i * 12, nx, ny, nz)

    # 3. UV buffer (Vec2 float32 = 8 bytes per vertex)
    uv_bytes = bytearray(num_verts * 8)
    for i, (u, v) in enumerate(uvs):
        struct.pack_into("<2f", uv_bytes, i * 8, u, v)

    # 4. Index buffer (uint32 scalar = 4 bytes per index)
    index_bytes = bytearray(num_indices * 4)
    for i, (i0, i1, i2) in enumerate(mesh.faces):
        struct.pack_into("<3I", index_bytes, i * 12, i0, i1, i2)

    # Offsets and buffer views
    pos_offset = 0
    pos_len = len(pos_bytes)

    norm_offset = pos_offset + pos_len
    norm_len = len(norm_bytes)

    uv_offset = norm_offset + norm_len
    uv_len = len(uv_bytes)

    idx_offset = uv_offset + uv_len
    idx_len = len(index_bytes)

    total_bin = pos_bytes + norm_bytes + uv_bytes + index_bytes

    # Align total binary payload to 4 bytes
    padding = (4 - (len(total_bin) % 4)) % 4
    if padding:
        total_bin += b"\x00" * padding

    gltf_dict: Dict[str, Any] = {
        "asset": {
            "version": "2.0",
            "generator": "badge3d-coin-generator",
        },
        "scene": 0,
        "scenes": [
            {
                "name": "DefaultScene",
                "nodes": [0],
            }
        ],
        "nodes": [
            {
                "name": "CoinNode",
                "mesh": 0,
            }
        ],
        "meshes": [
            {
                "name": "CoinMesh",
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": 0,
                            "NORMAL": 1,
                            "TEXCOORD_0": 2,
                        },
                        "indices": 3,
                        "material": 0,
                        "mode": 4,  # TRIANGLES
                    }
                ],
            }
        ],
        "materials": [
            {
                "name": "CoinGoldPBR",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.95, 0.78, 0.28, 1.0],  # Gold color
                    "metallicFactor": 0.9,
                    "roughnessFactor": 0.25,
                },
                "doubleSided": False,
            }
        ],
        "accessors": [
            # 0: POSITION
            {
                "bufferView": 0,
                "byteOffset": 0,
                "componentType": 5126,  # FLOAT
                "count": num_verts,
                "type": "VEC3",
                "min": [min_pt[0], min_pt[1], min_pt[2]],
                "max": [max_pt[0], max_pt[1], max_pt[2]],
            },
            # 1: NORMAL
            {
                "bufferView": 1,
                "byteOffset": 0,
                "componentType": 5126,  # FLOAT
                "count": num_verts,
                "type": "VEC3",
            },
            # 2: TEXCOORD_0
            {
                "bufferView": 2,
                "byteOffset": 0,
                "componentType": 5126,  # FLOAT
                "count": num_verts,
                "type": "VEC2",
            },
            # 3: INDICES
            {
                "bufferView": 3,
                "byteOffset": 0,
                "componentType": 5125,  # UNSIGNED_INT
                "count": num_indices,
                "type": "SCALAR",
                "min": [0],
                "max": [max(0, num_verts - 1)],
            },
        ],
        "bufferViews": [
            # 0: POSITION
            {
                "buffer": 0,
                "byteOffset": pos_offset,
                "byteLength": pos_len,
                "target": 34962,  # ARRAY_BUFFER
            },
            # 1: NORMAL
            {
                "buffer": 0,
                "byteOffset": norm_offset,
                "byteLength": norm_len,
                "target": 34962,
            },
            # 2: TEXCOORD_0
            {
                "buffer": 0,
                "byteOffset": uv_offset,
                "byteLength": uv_len,
                "target": 34962,
            },
            # 3: INDICES
            {
                "buffer": 0,
                "byteOffset": idx_offset,
                "byteLength": idx_len,
                "target": 34963,  # ELEMENT_ARRAY_BUFFER
            },
        ],
    }

    return bytes(total_bin), gltf_dict


def mesh_to_gltf_json(mesh: MeshData, indent: int = 2) -> str:
    """Serialize MeshData into a standalone GLTF JSON string with embedded Base64 buffer."""
    raw_bin, gltf_dict = _build_gltf_binary_payload(mesh)
    b64_str = base64.b64encode(raw_bin).decode("ascii")
    data_uri = f"data:application/octet-stream;base64,{b64_str}"

    gltf_dict["buffers"] = [
        {
            "uri": data_uri,
            "byteLength": len(raw_bin),
        }
    ]
    return json.dumps(gltf_dict, indent=indent)


def mesh_to_glb_bytes(mesh: MeshData) -> bytes:
    """Serialize MeshData into standard binary GLB container bytes."""
    raw_bin, gltf_dict = _build_gltf_binary_payload(mesh)
    gltf_dict["buffers"] = [{"byteLength": len(raw_bin)}]

    json_str = json.dumps(gltf_dict, separators=(",", ":"))
    json_bytes = json_str.encode("utf-8")

    # Pad JSON chunk to 4-byte boundary with space chars (0x20)
    json_padding = (4 - (len(json_bytes) % 4)) % 4
    if json_padding:
        json_bytes += b" " * json_padding

    # Pad binary chunk to 4-byte boundary with null bytes (0x00)
    bin_padding = (4 - (len(raw_bin) % 4)) % 4
    bin_bytes = raw_bin + (b"\x00" * bin_padding if bin_padding else b"")

    # GLB Header (12 bytes)
    # Magic = 0x46546C67 ("glTF"), Version = 2, Total Length
    chunk0_header_len = 8
    chunk1_header_len = 8
    total_length = 12 + chunk0_header_len + len(json_bytes) + chunk1_header_len + len(bin_bytes)

    header = struct.pack("<4sII", b"glTF", 2, total_length)

    # Chunk 0: JSON (type 0x4E4F534A = "JSON")
    chunk0_header = struct.pack("<II", len(json_bytes), 0x4E4F534A)

    # Chunk 1: BINARY (type 0x004E4942 = "BIN\0")
    chunk1_header = struct.pack("<II", len(bin_bytes), 0x004E4942)

    return header + chunk0_header + json_bytes + chunk1_header + bin_bytes


def export_gltf(mesh: MeshData, filepath: PathLike) -> Path:
    """Export a MeshData instance as a standalone JSON .gltf file atomically."""
    json_text = mesh_to_gltf_json(mesh)
    return atomic_write_text(filepath, json_text)


def export_glb(mesh: MeshData, filepath: PathLike) -> Path:
    """Export a MeshData instance as a binary .glb file atomically."""
    glb_data = mesh_to_glb_bytes(mesh)
    return atomic_write_bytes(filepath, glb_data)


# ---------------------------------------------------------------------------
# Universal Exporter Facade
# ---------------------------------------------------------------------------

def export_mesh(
    mesh: MeshData,
    filepath: PathLike,
    file_format: Optional[str] = None,
    **kwargs: Any,
) -> Path:
    """Export a MeshData instance using automatic format detection from file extension.

    Supported formats:
    - '.stl' (binary STL by default, ascii if ascii=True in kwargs)
    - '.obj' (Wavefront OBJ + MTL)
    - '.gltf' (glTF 2.0 JSON)
    - '.glb' (glTF 2.0 Binary)

    Args:
        mesh: The 3D mesh to export.
        filepath: Target output file path.
        file_format: Optional format override ('stl', 'stl_ascii', 'obj', 'gltf', 'glb').
        **kwargs: Format-specific parameters (e.g. solid_name, material_name, write_mtl).

    Returns:
        Resolved Path of exported primary file.
    """
    dest = safe_path(filepath)
    fmt = (file_format or dest.suffix.lower().lstrip(".")).lower()

    if fmt in ("stl", "stl_bin", "binary_stl"):
        if kwargs.get("ascii", False):
            return export_ascii_stl(mesh, dest, solid_name=kwargs.get("solid_name", "coin"))
        return export_binary_stl(mesh, dest, header_comment=kwargs.get("header_comment", "badge3d-coin-generator"))

    elif fmt in ("stl_ascii", "ascii_stl"):
        return export_ascii_stl(mesh, dest, solid_name=kwargs.get("solid_name", "coin"))

    elif fmt in ("obj", "wavefront"):
        obj_path, _ = export_obj(
            mesh,
            dest,
            object_name=kwargs.get("object_name", "coin"),
            material_name=kwargs.get("material_name", "CoinGold"),
            write_mtl=kwargs.get("write_mtl", True),
        )
        return obj_path

    elif fmt in ("gltf", "json"):
        return export_gltf(mesh, dest)

    elif fmt in ("glb", "binary_gltf"):
        return export_glb(mesh, dest)

    else:
        raise ValueError(
            f"Unsupported 3D export format '{fmt}' for path '{dest}'. "
            f"Supported extensions: .stl, .obj, .gltf, .glb"
        )
