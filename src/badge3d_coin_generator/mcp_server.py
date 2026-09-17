"""Model Context Protocol (MCP) JSON-RPC 2.0 Server for badge3d-coin-generator.

Provides standard MCP stdio server integration with AI agents (Antigravity, Claude,
Cursor, OpenAI Codex, Windsurf) for generating, inspecting, and exporting 3D
coins, challenge tokens, and relief medallions for 3D printing and digital rendering.

Registered Tools:
1. `coin_generate`: Generate 3D coin mesh parameters, volume, mass, and bounding box.
2. `coin_export_stl`: Export 3D coin as binary or ASCII STL for slicing & 3D printing.
3. `coin_export_obj`: Export 3D coin as Wavefront OBJ/MTL for 3D modeling & rendering.
4. `coin_presets`: Return catalog of professional coin presets.
5. `coin_diagnostics`: System, Python, and 3D print toolchain diagnostics.

Zero external dependencies (Pure Python Standard Library).
"""

from __future__ import annotations

import io
import json
import math
import os
import platform
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from .compat import (
    atomic_write_bytes,
    atomic_write_text,
    get_system_info,
    get_temp_dir,
    is_linux,
    is_macos,
    is_termux,
    is_windows,
    safe_path,
)
from .exporters import (
    export_ascii_stl,
    export_binary_stl,
    export_obj as export_obj_files,
    mesh_to_ascii_stl_text,
    mesh_to_binary_stl_bytes,
    mesh_to_obj_text,
)
from .mesh_engine import (
    CoinMeshEngine,
    CoinParameters,
    MeshData,
    calculate_reed_radius,
)

# Version & Protocol Constants
MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "badge3d-coin-generator"
SERVER_VERSION = "0.1.0"


def _log(msg: str) -> None:
    """Log informational messages to stderr to keep stdout pure for JSON-RPC."""
    sys.stderr.write(f"[{SERVER_NAME}] {msg}\n")
    sys.stderr.flush()


def _log_err(msg: str) -> None:
    """Log error messages to stderr."""
    sys.stderr.write(f"[{SERVER_NAME}:ERROR] {msg}\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Tool Schemas Definitions
# ---------------------------------------------------------------------------

TOOLS_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "coin_generate",
        "description": (
            "Generate a high-precision parametric 3D coin mesh and return comprehensive "
            "geometry statistics, watertight manifold status, dimensions, volume (mm³), "
            "and estimated weights for various minting metals (24k Gold, Fine Silver, "
            "Brass, Copper) and 3D printing filaments (PLA, Resin)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "radius": {
                    "type": "number",
                    "description": "Outer radius of the coin in millimeters (e.g., 20.0 for 40mm diameter).",
                    "default": 20.0,
                },
                "thickness": {
                    "type": "number",
                    "description": "Total coin thickness at the rim peak in millimeters (e.g., 3.0).",
                    "default": 3.0,
                },
                "serrations": {
                    "type": "integer",
                    "description": "Number of edge reeding serrations/grooves around the perimeter (0 for smooth).",
                    "default": 80,
                },
                "relief_pattern": {
                    "type": "string",
                    "description": "Procedural relief pattern for front face.",
                    "enum": [
                        "wreath",
                        "star",
                        "cross",
                        "sunburst",
                        "hex_grid",
                        "shield",
                        "roman_head",
                        "skull",
                        "concentric",
                        "smooth",
                    ],
                    "default": "wreath",
                },
                "reverse_relief_pattern": {
                    "type": "string",
                    "description": "Optional relief pattern for reverse/back face (defaults to relief_pattern).",
                    "enum": [
                        "wreath",
                        "star",
                        "cross",
                        "sunburst",
                        "hex_grid",
                        "shield",
                        "roman_head",
                        "skull",
                        "concentric",
                        "smooth",
                    ],
                },
                "rim_width": {
                    "type": "number",
                    "description": "Width of raised outer protective rim in mm (default: 2.0).",
                    "default": 2.0,
                },
                "rim_height": {
                    "type": "number",
                    "description": "Height of raised rim above central field basin in mm (default: 0.4).",
                    "default": 0.4,
                },
                "edge_type": {
                    "type": "string",
                    "description": "Perimeter edge detailing style.",
                    "enum": ["reeded", "serrated", "milled", "plain"],
                    "default": "reeded",
                },
                "resolution": {
                    "type": "integer",
                    "description": "Angular radial segments for circumferential mesh density (default: 64).",
                    "default": 64,
                },
                "preset": {
                    "type": "string",
                    "description": (
                        "Optional name of a standard coin preset to load base parameters from "
                        "(e.g., commemorative_gold, cyberpunk_hex, antique_roman, military_challenge, sovereign_silver)."
                    ),
                },
            },
        },
    },
    {
        "name": "coin_export_stl",
        "description": (
            "Generate and export a watertight 3D coin mesh to a Binary (.stl) or ASCII STL "
            "file ready for 3D printing slicers (PrusaSlicer, Bambu Studio, Cura, Lychee). "
            "Includes automated printability checks and slicing recommendations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_path": {
                    "type": "string",
                    "description": "Target filesystem path for the exported STL file (e.g. 'output/coin.stl').",
                },
                "binary": {
                    "type": "boolean",
                    "description": "If True (default), exports compact binary STL. If False, exports ASCII STL.",
                    "default": True,
                },
                "radius": {
                    "type": "number",
                    "description": "Outer radius in mm (default: 20.0).",
                    "default": 20.0,
                },
                "thickness": {
                    "type": "number",
                    "description": "Thickness in mm (default: 3.0).",
                    "default": 3.0,
                },
                "serrations": {
                    "type": "integer",
                    "description": "Edge serrations count (default: 80).",
                    "default": 80,
                },
                "relief_pattern": {
                    "type": "string",
                    "description": "Relief pattern for front face.",
                    "enum": [
                        "wreath",
                        "star",
                        "cross",
                        "sunburst",
                        "hex_grid",
                        "shield",
                        "roman_head",
                        "skull",
                        "concentric",
                        "smooth",
                    ],
                    "default": "wreath",
                },
                "reverse_relief_pattern": {
                    "type": "string",
                    "description": "Relief pattern for back face.",
                },
                "rim_width": {
                    "type": "number",
                    "description": "Rim width in mm (default: 2.0).",
                    "default": 2.0,
                },
                "rim_height": {
                    "type": "number",
                    "description": "Rim height in mm (default: 0.4).",
                    "default": 0.4,
                },
                "edge_type": {
                    "type": "string",
                    "description": "Edge style: 'reeded', 'serrated', 'milled', 'plain'.",
                    "default": "reeded",
                },
                "resolution": {
                    "type": "integer",
                    "description": "Radial angular resolution (default: 64).",
                    "default": 64,
                },
                "preset": {
                    "type": "string",
                    "description": "Optional preset name to load base parameters from.",
                },
            },
            "required": ["output_path"],
        },
    },
    {
        "name": "coin_export_obj",
        "description": (
            "Generate and export a 3D coin mesh as a Wavefront OBJ file (.obj) along with "
            "an accompanying Material Template Library file (.mtl) for 3D modeling (Blender, "
            "Maya, Cinema4D) and game engines (Unreal, Unity, Godot)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_path": {
                    "type": "string",
                    "description": "Target filesystem path for the exported OBJ file (e.g. 'output/coin.obj').",
                },
                "object_name": {
                    "type": "string",
                    "description": "Object identifier tag inside OBJ file (default: 'CoinMesh').",
                    "default": "CoinMesh",
                },
                "include_normals": {
                    "type": "boolean",
                    "description": "Whether to export smooth vertex normals (vn) (default: True).",
                    "default": True,
                },
                "material_name": {
                    "type": "string",
                    "description": "Material name in MTL file (default: 'CoinGold').",
                    "default": "CoinGold",
                },
                "radius": {
                    "type": "number",
                    "description": "Outer radius in mm (default: 20.0).",
                    "default": 20.0,
                },
                "thickness": {
                    "type": "number",
                    "description": "Thickness in mm (default: 3.0).",
                    "default": 3.0,
                },
                "serrations": {
                    "type": "integer",
                    "description": "Edge serrations count (default: 80).",
                    "default": 80,
                },
                "relief_pattern": {
                    "type": "string",
                    "description": "Relief pattern for front face.",
                    "default": "wreath",
                },
                "reverse_relief_pattern": {
                    "type": "string",
                    "description": "Relief pattern for back face.",
                },
                "rim_width": {
                    "type": "number",
                    "description": "Rim width in mm (default: 2.0).",
                    "default": 2.0,
                },
                "rim_height": {
                    "type": "number",
                    "description": "Rim height in mm (default: 0.4).",
                    "default": 0.4,
                },
                "edge_type": {
                    "type": "string",
                    "description": "Edge style.",
                    "default": "reeded",
                },
                "resolution": {
                    "type": "integer",
                    "description": "Radial resolution.",
                    "default": 64,
                },
                "preset": {
                    "type": "string",
                    "description": "Optional preset name.",
                },
            },
            "required": ["output_path"],
        },
    },
    {
        "name": "coin_presets",
        "description": (
            "Retrieve the complete catalog of professionally crafted coin presets "
            "including dimensions, serration specifications, relief descriptions, "
            "and metal densities (Commemorative Gold Medallion, Cyberpunk Hex Token, "
            "Antique Roman Coin, Military Challenge Coin, Sovereign Silver Bullion)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "preset_name": {
                    "type": "string",
                    "description": "Optional specific preset ID or alias to inspect in detail.",
                },
            },
        },
    },
    {
        "name": "coin_diagnostics",
        "description": (
            "Run 3D print toolchain diagnostics, host platform environment verification, "
            "atomic I/O test, and mesh geometry performance benchmark."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


# ---------------------------------------------------------------------------
# MCPServer Implementation
# ---------------------------------------------------------------------------

class MCPServer:
    """Model Context Protocol (MCP) JSON-RPC 2.0 Stdio Server."""

    def __init__(self) -> None:
        self.initialized = False
        self._tool_handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            "coin_generate": self._handle_coin_generate,
            "coin_export_stl": self._handle_coin_export_stl,
            "coin_export_obj": self._handle_coin_export_obj,
            "coin_presets": self._handle_coin_presets,
            "coin_diagnostics": self._handle_coin_diagnostics,
        }

    # -----------------------------------------------------------------------
    # Tool Handlers
    # -----------------------------------------------------------------------

    def _handle_coin_generate(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute `coin_generate` tool."""
        # Import dynamically from package
        from .__init__ import CoinGenerator, compute_mesh_volume, compute_mesh_weights

        gen = CoinGenerator(
            radius=float(args.get("radius", 20.0)),
            thickness=float(args.get("thickness", 3.0)),
            serrations=int(args.get("serrations", 80)),
            relief_pattern=str(args.get("relief_pattern", "wreath")),
            rim_width=float(args.get("rim_width", 2.0)),
            rim_height=float(args.get("rim_height", 0.4)),
            edge_type=str(args.get("edge_type", "reeded")),
            resolution=int(args.get("resolution", 64)),
            preset=args.get("preset"),
            reverse_relief_pattern=args.get("reverse_relief_pattern"),
        )

        t0 = time.perf_counter()
        summary = gen.get_summary()
        gen_time_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        p = summary["parameters"]
        m = summary["mesh_stats"]
        phys = summary["physical_estimates"]
        w = phys["weights_g"]

        markdown_text = (
            f"### 🪙 3D Coin Mesh Generated\n\n"
            f"- **Preset / Base**: `{args.get('preset') or 'Custom'}`\n"
            f"- **Dimensions**: Diameter `{p['diameter_mm']} mm` × Thickness `{p['thickness_mm']} mm`\n"
            f"- **Rim**: Width `{p['rim_width_mm']} mm` | Height `{p['rim_height_mm']} mm`\n"
            f"- **Edge Detailing**: `{p['edge_type'].capitalize()}` with `{p['serrations']}` serrations\n"
            f"- **Relief Pattern**: `{p['relief_pattern']}`\n\n"
            f"#### 📐 Mesh Topology\n"
            f"- **Vertices**: `{m['vertex_count']:,}`\n"
            f"- **Triangles**: `{m['triangle_count']:,}`\n"
            f"- **Watertight Manifold**: `{'✅ Yes (Closed 2-Manifold)' if m['is_watertight'] else '⚠️ Open/Non-Manifold'}`\n"
            f"- **Bounding Box**: `{m['dimensions_mm']['width']} × {m['dimensions_mm']['depth']} × {m['dimensions_mm']['height']} mm`\n"
            f"- **Generation Time**: `{gen_time_ms} ms`\n\n"
            f"#### ⚖️ Physical Estimates & Materials\n"
            f"- **Solid Volume**: `{phys['volume_mm3']:,} mm³` (`{phys['volume_cm3']} cm³`)\n"
            f"- **24k Pure Gold**: `{w['gold_24k_g']} g` ({w['troy_oz_gold']} oz troy)\n"
            f"- **.999 Fine Silver**: `{w['silver_999_g']} g` ({w['troy_oz_silver']} oz troy)\n"
            f"- **Solid Brass/Bronze**: `{w['brass_bronze_g']} g`\n"
            f"- **3D Print (PLA)**: `{w['pla_filament_g']} g`\n"
            f"- **3D Print (Resin)**: `{w['resin_standard_g']} g`\n\n"
            f"```json\n{json.dumps(summary, indent=2)}\n```"
        )

        return {
            "content": [
                {
                    "type": "text",
                    "text": markdown_text,
                }
            ],
            "isError": False,
        }

    def _handle_coin_export_stl(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute `coin_export_stl` tool."""
        from .__init__ import CoinGenerator, compute_mesh_volume, compute_mesh_weights

        output_path_str = args.get("output_path")
        if not output_path_str:
            return {
                "content": [{"type": "text", "text": "Error: 'output_path' is required for coin_export_stl."}],
                "isError": True,
            }

        binary_mode = bool(args.get("binary", True))

        gen = CoinGenerator(
            radius=float(args.get("radius", 20.0)),
            thickness=float(args.get("thickness", 3.0)),
            serrations=int(args.get("serrations", 80)),
            relief_pattern=str(args.get("relief_pattern", "wreath")),
            rim_width=float(args.get("rim_width", 2.0)),
            rim_height=float(args.get("rim_height", 0.4)),
            edge_type=str(args.get("edge_type", "reeded")),
            resolution=int(args.get("resolution", 64)),
            preset=args.get("preset"),
            reverse_relief_pattern=args.get("reverse_relief_pattern"),
        )

        t0 = time.perf_counter()
        dest_path = safe_path(output_path_str)
        written_path = gen.export_stl(dest_path, binary=binary_mode)
        export_time_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        file_size_bytes = written_path.stat().st_size
        file_size_kb = round(file_size_bytes / 1024.0, 2)
        summary = gen.get_summary()
        m = summary["mesh_stats"]
        p = summary["parameters"]
        phys = summary["physical_estimates"]

        # Printability evaluation
        min_wall_mm = min(p["rim_width_mm"], p["thickness_mm"])
        fdm_ready = min_wall_mm >= 0.8 and m["is_watertight"]
        sla_ready = min_wall_mm >= 0.4 and m["is_watertight"]

        markdown_text = (
            f"### 🖨️ STL Export Complete\n\n"
            f"- **File Path**: `{written_path.resolve()}`\n"
            f"- **Format**: `{'Binary STL (Compact)' if binary_mode else 'ASCII STL (Text)'}`\n"
            f"- **File Size**: `{file_size_kb} KB` (`{file_size_bytes:,} bytes`)\n"
            f"- **Triangles**: `{m['triangle_count']:,}` | **Vertices**: `{m['vertex_count']:,}`\n"
            f"- **Export Time**: `{export_time_ms} ms`\n\n"
            f"#### 🔍 3D Printability Assessment\n"
            f"- **Watertight Solid**: `{'✅ Watertight 2-Manifold' if m['is_watertight'] else '❌ Non-manifold error'}`\n"
            f"- **FDM (Filament) Slicing**: `{'✅ Ready (Recommended: 0.12mm layer height, 100% concentric infill)' if fdm_ready else '⚠️ Wall thickness thin for FDM'}`\n"
            f"- **SLA / DLP / Resin**: `{'✅ Optimal (Recommended: 0.05mm layer height, vertical or 45° coin orientation)' if sla_ready else '⚠️ Check minimum details'}`\n"
            f"- **Volume**: `{phys['volume_mm3']:,} mm³` (Est. `{phys['weights_g']['pla_filament_g']} g` PLA / `{phys['weights_g']['resin_standard_g']} g` Resin)\n"
        )

        return {
            "content": [
                {
                    "type": "text",
                    "text": markdown_text,
                }
            ],
            "isError": False,
        }

    def _handle_coin_export_obj(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute `coin_export_obj` tool."""
        from .__init__ import CoinGenerator

        output_path_str = args.get("output_path")
        if not output_path_str:
            return {
                "content": [{"type": "text", "text": "Error: 'output_path' is required for coin_export_obj."}],
                "isError": True,
            }

        object_name = str(args.get("object_name", "CoinMesh"))
        include_normals = bool(args.get("include_normals", True))

        gen = CoinGenerator(
            radius=float(args.get("radius", 20.0)),
            thickness=float(args.get("thickness", 3.0)),
            serrations=int(args.get("serrations", 80)),
            relief_pattern=str(args.get("relief_pattern", "wreath")),
            rim_width=float(args.get("rim_width", 2.0)),
            rim_height=float(args.get("rim_height", 0.4)),
            edge_type=str(args.get("edge_type", "reeded")),
            resolution=int(args.get("resolution", 64)),
            preset=args.get("preset"),
            reverse_relief_pattern=args.get("reverse_relief_pattern"),
        )

        t0 = time.perf_counter()
        dest_path = safe_path(output_path_str)
        written_obj = gen.export_obj(dest_path, object_name=object_name, include_normals=include_normals)
        export_time_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        file_size_bytes = written_obj.stat().st_size
        file_size_kb = round(file_size_bytes / 1024.0, 2)
        mtl_path = written_obj.with_suffix(".mtl")

        summary = gen.get_summary()
        m = summary["mesh_stats"]

        markdown_text = (
            f"### 📦 Wavefront OBJ Export Complete\n\n"
            f"- **OBJ File**: `{written_obj.resolve()}` (`{file_size_kb} KB`)\n"
            f"- **MTL File**: `{mtl_path.resolve()}`\n"
            f"- **Object Name**: `{object_name}`\n"
            f"- **Vertices**: `{m['vertex_count']:,}` | **Faces**: `{m['triangle_count']:,}`\n"
            f"- **Normals Included**: `{'Yes (Smooth vn tags)' if include_normals else 'No'}`\n"
            f"- **Export Time**: `{export_time_ms} ms`\n"
        )

        return {
            "content": [
                {
                    "type": "text",
                    "text": markdown_text,
                }
            ],
            "isError": False,
        }

    def _handle_coin_presets(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute `coin_presets` tool."""
        from .__init__ import COIN_PRESETS, resolve_preset

        requested = args.get("preset_name")
        if requested:
            preset = resolve_preset(requested)
            if not preset:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Preset '{requested}' not found. Available presets: {', '.join(COIN_PRESETS.keys())}",
                        }
                    ],
                    "isError": True,
                }
            md = (
                f"### 🪙 Coin Preset: {preset['name']}\n\n"
                f"- **ID**: `{preset['id']}`\n"
                f"- **Description**: {preset['description']}\n"
                f"- **Diameter**: `{preset['diameter']} mm` (Radius `{preset['radius']} mm`)\n"
                f"- **Thickness**: `{preset['thickness']} mm`\n"
                f"- **Rim**: Width `{preset['rim_width']} mm`, Height `{preset['rim_height']} mm`\n"
                f"- **Serrations**: `{preset['serrations']}` ridges (`{preset['edge_type']}` edge, `{preset['reed_profile']}` profile)\n"
                f"- **Relief Pattern**: `{preset['relief_pattern']}`\n"
                f"- **Default Material**: `{preset['material']}` (Density `{preset['density_g_cm3']} g/cm³`)\n\n"
                f"```json\n{json.dumps(preset, indent=2)}\n```"
            )
            return {"content": [{"type": "text", "text": md}], "isError": False}

        # Return full catalog table
        lines = [
            "### 🏛️ Standard Coin Presets Catalog\n",
            "| Preset Name | ID | Diameter | Thickness | Serrations | Edge | Relief | Material |",
            "|:---|:---|:---|:---|:---|:---|:---|:---|",
        ]
        for p_id, p in COIN_PRESETS.items():
            lines.append(
                f"| **{p['name']}** | `{p_id}` | {p['diameter']} mm | {p['thickness']} mm | {p['serrations']} | {p['edge_type']} | {p['relief_pattern']} | {p['material']} |"
            )

        lines.append("\n#### Detailed Specifications\n")
        for p_id, p in COIN_PRESETS.items():
            lines.append(f"**{p['name']}** (`{p_id}`):")
            lines.append(f"> {p['description']}")
            lines.append(f"> *Params*: Radius {p['radius']}mm, Thickness {p['thickness']}mm, Rim {p['rim_width']}x{p['rim_height']}mm, Serrations {p['serrations']}.\n")

        return {
            "content": [{"type": "text", "text": "\n".join(lines)}],
            "isError": False,
        }

    def _handle_coin_diagnostics(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute `coin_diagnostics` tool."""
        from .__init__ import CoinGenerator, compute_mesh_volume

        sys_info = get_system_info()
        temp_dir = get_temp_dir()

        # Atomic write test
        test_file = temp_dir / f".badge3d_diag_{os.getpid()}_{int(time.time())}.tmp"
        io_ok = False
        io_time_ms = 0.0
        try:
            t0 = time.perf_counter()
            atomic_write_bytes(test_file, b"BADGE3D_DIAGNOSTIC_VERIFICATION_BYTES")
            if test_file.exists() and test_file.read_bytes() == b"BADGE3D_DIAGNOSTIC_VERIFICATION_BYTES":
                io_ok = True
            io_time_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        except Exception as e:
            _log_err(f"Diagnostic I/O test failed: {e}")
        finally:
            if test_file.exists():
                try:
                    test_file.unlink()
                except OSError:
                    pass

        # Math and mesh engine benchmark
        t_mesh_start = time.perf_counter()
        bench_gen = CoinGenerator(radius=20.0, thickness=3.0, serrations=60, resolution=64)
        bench_mesh = bench_gen.generate()
        bench_vol = compute_mesh_volume(bench_mesh)
        bench_stl_bytes = mesh_to_binary_stl_bytes(bench_mesh)
        bench_time_ms = round((time.perf_counter() - t_mesh_start) * 1000.0, 2)

        report = {
            "mcp_server": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
                "mcp_protocol_version": MCP_PROTOCOL_VERSION,
                "tools_registered": len(TOOLS_DEFINITIONS),
            },
            "environment": {
                "os_system": sys_info["system"],
                "os_release": sys_info["release"],
                "machine": sys_info["machine"],
                "python_version": sys_info["python_version"],
                "python_compiler": sys_info["python_compiler"],
                "byteorder": sys_info["byteorder"],
                "is_windows": sys_info["is_windows"],
                "is_macos": sys_info["is_macos"],
                "is_linux": sys_info["is_linux"],
                "is_termux": sys_info["is_termux"],
                "temp_directory": str(temp_dir),
            },
            "file_io_subsystem": {
                "atomic_write_status": "PASS" if io_ok else "FAIL",
                "atomic_write_latency_ms": io_time_ms,
            },
            "geometry_engine_benchmark": {
                "triangles_generated": bench_mesh.triangle_count,
                "vertices_generated": bench_mesh.vertex_count,
                "is_watertight": bench_mesh.is_watertight(),
                "calculated_volume_mm3": round(bench_vol, 2),
                "stl_binary_bytes": len(bench_stl_bytes),
                "benchmark_latency_ms": bench_time_ms,
                "throughput_triangles_per_sec": int(bench_mesh.triangle_count / max(0.001, (bench_time_ms / 1000.0))),
            },
            "supported_3d_formats": [
                "Binary STL (.stl - Little-Endian IEEE 754 50-byte record)",
                "ASCII STL (.stl - solid / facet normal text)",
                "Wavefront OBJ (.obj - v, vn, vt, f)",
                "Wavefront MTL (.mtl - Ka, Kd, Ks, Ns, illum)",
                "glTF 2.0 / GLB (.glb, .gltf - WebGL 3D asset)",
                "JSON Mesh Data",
            ],
        }

        markdown_text = (
            f"### 🩺 System & 3D Print Toolchain Diagnostics\n\n"
            f"- **Platform**: `{sys_info['system']} {sys_info['release']} ({sys_info['machine']})`\n"
            f"- **Python**: `{sys_info['python_version']}` ({sys_info['byteorder']}-endian)\n"
            f"- **Temp Directory**: `{temp_dir}`\n"
            f"- **Atomic Safe I/O**: `{'✅ Operational' if io_ok else '❌ Failed'}` (`{io_time_ms} ms`)\n"
            f"- **Geometry Benchmark**: `{bench_mesh.triangle_count:,} triangles` generated & serialized in `{bench_time_ms} ms`\n"
            f"- **Watertight Manifold**: `{'✅ Watertight Solid' if bench_mesh.is_watertight() else '❌ Open Mesh'}`\n"
            f"- **Throughput**: `{report['geometry_engine_benchmark']['throughput_triangles_per_sec']:,} triangles/sec`\n\n"
            f"```json\n{json.dumps(report, indent=2)}\n```"
        )

        return {
            "content": [
                {
                    "type": "text",
                    "text": markdown_text,
                }
            ],
            "isError": False,
        }

    # -----------------------------------------------------------------------
    # JSON-RPC 2.0 Protocol Dispatcher
    # -----------------------------------------------------------------------

    def handle_request(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle a single JSON-RPC 2.0 request or notification dictionary."""
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if not method or not isinstance(method, str):
            if req_id is not None:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32600, "message": "Invalid Request: missing or non-string 'method'"},
                }
            return None

        # 1. MCP initialize handshake
        if method == "initialize":
            self.initialized = True
            client_info = params.get("clientInfo", {})
            _log(f"Client connected: {client_info.get('name', 'Unknown')} (v{client_info.get('version', '0.0.0')})")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {
                            "listChanged": False,
                        },
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                },
            }

        # 2. MCP initialized notification
        elif method == "notifications/initialized" or method == "initialized":
            _log("Handshake finalized (initialized notification received).")
            return None

        # 3. Ping
        elif method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {},
            }

        # 4. Tools list
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": TOOLS_DEFINITIONS,
                },
            }

        # 5. Tools call
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            if not tool_name or tool_name not in self._tool_handlers:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method/Tool not found: '{tool_name}'",
                    },
                }

            handler = self._tool_handlers[tool_name]
            try:
                result_payload = handler(tool_args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": result_payload,
                }
            except Exception as ex:
                err_trace = traceback.format_exc()
                _log_err(f"Error executing tool '{tool_name}': {ex}\n{err_trace}")
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Error executing tool '{tool_name}': {str(ex)}\n\nTraceback:\n{err_trace}",
                            }
                        ],
                        "isError": True,
                    },
                }

        # Unknown method
        else:
            if req_id is not None:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: '{method}'",
                    },
                }
            return None

    def run_stdio(self, in_stream: Optional[io.TextIOBase] = None, out_stream: Optional[io.TextIOBase] = None) -> None:
        """Run the MCP JSON-RPC 2.0 loop reading from stdio."""
        reader = in_stream or sys.stdin
        writer = out_stream or sys.stdout

        _log(f"Starting {SERVER_NAME} v{SERVER_VERSION} MCP Stdio Server...")

        while True:
            try:
                line = reader.readline()
                if not line:
                    _log("Standard input closed (EOF). Terminating server cleanly.")
                    break

                raw_line = line.strip()
                if not raw_line:
                    continue

                # Support Content-Length header framing if present
                if raw_line.lower().startswith("content-length:"):
                    try:
                        content_len = int(raw_line.split(":", 1)[1].strip())
                        # Read blank line
                        empty_line = reader.readline()
                        while empty_line.strip() != "":
                            empty_line = reader.readline()
                        raw_body = reader.read(content_len)
                    except Exception as parse_header_err:
                        _log_err(f"Error parsing Content-Length frame: {parse_header_err}")
                        continue
                else:
                    raw_body = raw_line

                if not raw_body.strip():
                    continue

                try:
                    request_obj = json.loads(raw_body)
                except json.JSONDecodeError as json_err:
                    _log_err(f"JSON-RPC parse error: {json_err} on input: {raw_body[:100]}")
                    err_resp = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": f"Parse error: {str(json_err)}"},
                    }
                    writer.write(json.dumps(err_resp) + "\n")
                    writer.flush()
                    continue

                if isinstance(request_obj, dict):
                    resp = self.handle_request(request_obj)
                    if resp is not None:
                        writer.write(json.dumps(resp) + "\n")
                        writer.flush()
                elif isinstance(request_obj, list):
                    # Batch JSON-RPC
                    batch_responses = []
                    for single_req in request_obj:
                        if isinstance(single_req, dict):
                            single_resp = self.handle_request(single_req)
                            if single_resp is not None:
                                batch_responses.append(single_resp)
                    if batch_responses:
                        writer.write(json.dumps(batch_responses) + "\n")
                        writer.flush()

            except KeyboardInterrupt:
                _log("Keyboard interrupt received. Shutting down.")
                break
            except Exception as e:
                _log_err(f"Unexpected error in MCP stdio loop: {e}\n{traceback.format_exc()}")
                break


def run_mcp_server() -> None:
    """Entry point helper for MCP server invocation."""
    server = MCPServer()
    server.run_stdio()


if __name__ == "__main__":
    run_mcp_server()
