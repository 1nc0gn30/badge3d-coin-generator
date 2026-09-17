"""badge3d-coin-generator - Pure Python 3D Parametric Coin Generator, MCP Server & CLI.

Generate watertight, high-precision 3D coin meshes, commemorative medallions,
and challenge tokens for 3D printing (FDM, SLA, Resin) and digital rendering.

Features:
- Pure Python standard library implementation (Zero external runtime dependencies)
- Watertight 2-manifold mesh generation with reeded/serrated edges and bevels
- 10+ procedural relief patterns (wreath, star, cross, sunburst, hex grid, shield, roman head, skull, concentric, smooth)
- Native Binary STL, ASCII STL, and Wavefront OBJ/MTL exporters
- Standard Model Context Protocol (MCP) JSON-RPC 2.0 stdio server
- Multi-OS Command Line Interface (CLI) and embedded Material 3 Web Studio
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .compat import PathLike, atomic_write_bytes, atomic_write_text, ensure_parent_dir, safe_path
from .exporters import (
    export_ascii_stl,
    export_binary_stl,
    export_glb,
    export_gltf,
    export_mesh,
    export_obj as export_obj_files,
    mesh_to_ascii_stl_text,
    mesh_to_binary_stl_bytes,
    mesh_to_glb_bytes,
    mesh_to_gltf_json,
    mesh_to_obj_text,
)
from .mesh_engine import (
    CoinMeshEngine,
    CoinParameters,
    MeshData,
    Vec2,
    Vec3,
    calculate_reed_radius,
    generate_cartesian_relief_mesh,
    sample_heightmap_bilinear,
    triangle_normal,
    vec3_cross,
    vec3_normalize,
    vec3_sub,
)
from .svg_rasterizer import (
    Heightmap,
    ProceduralReliefBuilder,
    SVGRasterizer,
    parse_svg_path_d,
)
from .slicer_engine import (
    FilamentType,
    InfillPattern,
    OverhangAnalysis,
    SliceLayer,
    SliceResult,
    SliceSegment2D,
    SlicingConfig,
    analyze_mesh_overhangs,
    slice_mesh,
)
from .edge_milling import (
    EdgeInscriptionSpec,
    SecurityStampSpec,
    SegmentedReedingSpec,
    CompoundMillingSpec,
    compute_edge_milling_radius,
    derive_crypto_teeth_pattern,
    generate_edge_milling_profile_summary,
)

__version__ = "0.1.0"
__author__ = "Badge3D Architecture Team"
__description__ = "Pure Python 3D Parametric Coin Generator, MCP Server & CLI"
__license__ = "MIT"


# ---------------------------------------------------------------------------
# Standard Coin Presets Catalog
# ---------------------------------------------------------------------------

COIN_PRESETS: Dict[str, Dict[str, Any]] = {
    "commemorative_gold": {
        "id": "commemorative_gold",
        "name": "Commemorative Gold Medallion",
        "description": "Classic commemorative proof medallion with mirror fields and frosted raised wreath relief.",
        "radius": 20.0,
        "diameter": 40.0,
        "thickness": 3.0,
        "rim_width": 2.0,
        "rim_height": 0.4,
        "serrations": 120,
        "reed_profile": "sinusoidal",
        "relief_pattern": "wreath",
        "edge_type": "reeded",
        "bevel_width": 0.4,
        "bevel_height": 0.4,
        "material": "24k Gold",
        "density_g_cm3": 19.32,
    },
    "cyberpunk_hex": {
        "id": "cyberpunk_hex",
        "name": "Cyberpunk Hex Token",
        "description": "Futuristic high-tech currency token featuring geometric hex-circuit etching.",
        "radius": 18.0,
        "diameter": 36.0,
        "thickness": 2.5,
        "rim_width": 1.5,
        "rim_height": 0.5,
        "serrations": 6,
        "reed_profile": "square",
        "relief_pattern": "hex_grid",
        "edge_type": "milled",
        "bevel_width": 0.3,
        "bevel_height": 0.3,
        "material": "Titanium",
        "density_g_cm3": 4.5,
    },
    "antique_roman": {
        "id": "antique_roman",
        "name": "Antique Roman Coin",
        "description": "Classical ancient hammered coin with organic hand-struck relief.",
        "radius": 14.0,
        "diameter": 28.0,
        "thickness": 2.8,
        "rim_width": 1.2,
        "rim_height": 0.3,
        "serrations": 0,
        "reed_profile": "sinusoidal",
        "relief_pattern": "roman_head",
        "edge_type": "plain",
        "bevel_width": 0.5,
        "bevel_height": 0.5,
        "material": "Ancient Silver",
        "density_g_cm3": 10.49,
    },
    "military_challenge": {
        "id": "military_challenge",
        "name": "Military Challenge Coin",
        "description": "Heavy solid brass challenge coin with deep relief and protective bevel rim.",
        "radius": 22.5,
        "diameter": 45.0,
        "thickness": 3.5,
        "rim_width": 2.5,
        "rim_height": 0.6,
        "serrations": 60,
        "reed_profile": "trapezoidal",
        "relief_pattern": "shield",
        "edge_type": "serrated",
        "bevel_width": 0.6,
        "bevel_height": 0.6,
        "material": "Solid Brass",
        "density_g_cm3": 8.73,
    },
    "sovereign_silver": {
        "id": "sovereign_silver",
        "name": "Sovereign Silver Bullion",
        "description": "Standard 1 troy ounce fine silver investment round with radial sunburst anti-counterfeit lines.",
        "radius": 19.5,
        "diameter": 39.0,
        "thickness": 3.2,
        "rim_width": 1.8,
        "rim_height": 0.45,
        "serrations": 140,
        "reed_profile": "fluted",
        "relief_pattern": "sunburst",
        "edge_type": "reeded",
        "bevel_width": 0.4,
        "bevel_height": 0.4,
        "material": "Fine Silver .999",
        "density_g_cm3": 10.49,
    },
}


def get_coin_presets() -> Dict[str, Dict[str, Any]]:
    """Return a dictionary of all available coin presets and specifications."""
    return dict(COIN_PRESETS)


def resolve_preset(name: Optional[str]) -> Optional[Dict[str, Any]]:
    """Resolve preset by exact id, alias, or fuzzy substring match."""
    if not name:
        return None
    key = name.lower().strip().replace("-", "_").replace(" ", "_")
    if key in COIN_PRESETS:
        return COIN_PRESETS[key]

    aliases = {
        "gold": "commemorative_gold",
        "gold_medallion": "commemorative_gold",
        "commemorative": "commemorative_gold",
        "medallion": "commemorative_gold",
        "hex": "cyberpunk_hex",
        "cyberpunk": "cyberpunk_hex",
        "token": "cyberpunk_hex",
        "hex_token": "cyberpunk_hex",
        "roman": "antique_roman",
        "antique": "antique_roman",
        "denarius": "antique_roman",
        "aureus": "antique_roman",
        "roman_coin": "antique_roman",
        "military": "military_challenge",
        "challenge": "military_challenge",
        "challenge_coin": "military_challenge",
        "silver": "sovereign_silver",
        "bullion": "sovereign_silver",
        "silver_bullion": "sovereign_silver",
        "sovereign": "sovereign_silver",
    }
    if key in aliases:
        return COIN_PRESETS[aliases[key]]

    for p_id, p_data in COIN_PRESETS.items():
        if key in p_id or key in p_data["name"].lower():
            return p_data
    return None


# ---------------------------------------------------------------------------
# Procedural Relief Heightmap Generator
# ---------------------------------------------------------------------------

def generate_relief_heightmap(pattern: str, grid_size: int = 64) -> List[List[float]]:
    """Generate a normalized 2D elevation matrix [0.0, 1.0] for coin relief embossing.

    Supported patterns:
    - 'smooth': Flat polished mirror proof field
    - 'wreath': Laurel wreath ring with embossed leaf lobes
    - 'star': 5-pointed geometric star
    - 'cross': Maltese / Iron / Greek cross
    - 'sunburst': Radial anti-counterfeit security rays
    - 'hex_grid': Cyberpunk hexagonal mesh lattice
    - 'shield': Heraldic protective shield crest
    - 'roman_head': Classical laurel-wreathed Emperor portrait profile
    - 'skull': Embossed pirate / gothic skull emblem
    - 'concentric': Stepped concentric bullseye rings
    """
    p = pattern.lower().strip().replace("-", "_")
    grid: List[List[float]] = [[0.0 for _ in range(grid_size)] for _ in range(grid_size)]

    for r in range(grid_size):
        v = r / max(1, grid_size - 1)
        y = 2.0 * (v - 0.5)
        for c in range(grid_size):
            u = c / max(1, grid_size - 1)
            x = 2.0 * (u - 0.5)
            rad = math.sqrt(x * x + y * y)
            theta = math.atan2(y, x)
            if theta < 0:
                theta += 2.0 * math.pi

            val = 0.0
            if rad <= 1.0:
                if p == "smooth":
                    val = 0.0

                elif p == "wreath":
                    w_r = 0.65
                    dist = abs(rad - w_r)
                    if dist < 0.22:
                        leaves = math.cos(14 * theta)
                        ring = 1.0 - (dist / 0.22)
                        val = max(0.0, ring * (0.6 + 0.4 * leaves))

                elif p in ("star", "five_star"):
                    # 5-pointed star
                    p_angle = (theta + math.pi / 2) % (2 * math.pi / 5) - (math.pi / 5)
                    cos_pa = max(1e-5, math.cos(p_angle))
                    r_star = 0.7 * math.cos(math.pi / 5) / cos_pa
                    if rad <= r_star:
                        val = max(0.0, (1.0 - (rad / r_star)) ** 0.8)

                elif p == "cross":
                    arm_w = 0.15 + 0.20 * rad
                    if (abs(x) < arm_w and rad < 0.75) or (abs(y) < arm_w and rad < 0.75):
                        val = max(0.0, (1.0 - (rad / 0.75)) ** 1.3)

                elif p == "sunburst":
                    rays = 0.5 + 0.5 * math.cos(24 * theta)
                    val = max(0.0, rays * (1.0 - rad * 0.3))

                elif p == "hex_grid":
                    hx = x * 8.0
                    hy = y * 8.0
                    h_val = 0.5 + 0.5 * (math.cos(hx) * math.cos(hy * 1.732) + math.cos(hx * 0.5) * math.sin(hy * 0.866))
                    val = max(0.0, min(1.0, h_val))

                elif p == "shield":
                    in_shield = False
                    if -0.6 <= y <= 0.5:
                        if y > -0.1 and abs(x) <= 0.52:
                            in_shield = True
                        elif y <= -0.1:
                            t = (y + 0.1) / -0.5
                            max_x = 0.52 * max(0.0, 1.0 - t * t)
                            if abs(x) <= max_x:
                                in_shield = True
                    if in_shield:
                        val = max(0.0, 0.85 - rad * 0.4)

                elif p == "roman_head":
                    head_dist = math.sqrt((x - 0.05) ** 2 + (y - 0.1) ** 2)
                    if head_dist < 0.45:
                        val = 0.8 * (1.0 - head_dist / 0.45)
                        if abs(rad - 0.5) < 0.08:
                            val += 0.2 * math.cos(10 * theta)

                elif p == "skull":
                    cranium = math.sqrt(x * x + (y - 0.15) ** 2)
                    if cranium < 0.42:
                        val = 0.9 * (1.0 - cranium / 0.42)
                        eye1 = math.sqrt((x - 0.15) ** 2 + (y - 0.1) ** 2)
                        eye2 = math.sqrt((x + 0.15) ** 2 + (y - 0.1) ** 2)
                        if eye1 < 0.1 or eye2 < 0.1:
                            val = max(0.0, val - 0.6)
                    elif abs(x) < 0.25 and -0.55 < y < 0.0:
                        val = 0.7 * (1.0 - abs(x) / 0.25)

                elif p == "concentric":
                    val = 0.5 + 0.5 * math.sin(8.0 * math.pi * rad)

                else:
                    # Default smooth
                    val = 0.0

            grid[r][c] = max(0.0, min(1.0, val))

    return grid


# ---------------------------------------------------------------------------
# Mesh Physics, Volume & Mass Estimation
# ---------------------------------------------------------------------------

def compute_mesh_volume(mesh: MeshData) -> float:
    """Compute exact signed volume of a watertight 3D mesh in cubic millimeters (mm³)."""
    if not mesh.faces:
        return 0.0
    vol_sum = 0.0
    for i0, i1, i2 in mesh.faces:
        v0, v1, v2 = mesh.vertices[i0], mesh.vertices[i1], mesh.vertices[i2]
        cx = v1[1] * v2[2] - v1[2] * v2[1]
        cy = v1[2] * v2[0] - v1[0] * v2[2]
        cz = v1[0] * v2[1] - v1[1] * v2[0]
        vol_sum += v0[0] * cx + v0[1] * cy + v0[2] * cz
    return abs(vol_sum) / 6.0


def compute_mesh_weights(volume_mm3: float) -> Dict[str, float]:
    """Calculate estimated mass in grams for standard coin minting materials and 3D printing filaments."""
    vol_cm3 = volume_mm3 / 1000.0
    return {
        "gold_24k_g": round(vol_cm3 * 19.32, 2),
        "silver_999_g": round(vol_cm3 * 10.49, 2),
        "sterling_silver_g": round(vol_cm3 * 10.36, 2),
        "brass_bronze_g": round(vol_cm3 * 8.73, 2),
        "copper_g": round(vol_cm3 * 8.96, 2),
        "pla_filament_g": round(vol_cm3 * 1.24, 2),
        "resin_standard_g": round(vol_cm3 * 1.15, 2),
        "troy_oz_gold": round((vol_cm3 * 19.32) / 31.1034768, 3),
        "troy_oz_silver": round((vol_cm3 * 10.49) / 31.1034768, 3),
    }


# ---------------------------------------------------------------------------
# High-Level CoinGenerator Class
# ---------------------------------------------------------------------------

class CoinGenerator:
    """High-level API for configuring, generating, and exporting 3D coins."""

    def __init__(
        self,
        radius: float = 20.0,
        thickness: float = 3.0,
        serrations: int = 80,
        relief_pattern: str = "wreath",
        rim_width: float = 2.0,
        rim_height: float = 0.4,
        edge_type: str = "reeded",
        bevel_width: float = 0.4,
        bevel_height: float = 0.4,
        resolution: int = 64,
        field_rings: int = 16,
        preset: Optional[str] = None,
        reverse_relief_pattern: Optional[str] = None,
        edge_inscription: Optional[str] = None,
        edge_inscription_depth: float = 0.25,
        edge_inscription_mode: str = "incuse",
        security_stamp_seed: Optional[str] = None,
        security_stamp_grooves: int = 64,
        segmented_sectors: int = 0,
    ) -> None:
        self.radius = float(radius)
        self.thickness = float(thickness)
        self.serrations = int(serrations)
        self.relief_pattern = str(relief_pattern)
        self.rim_width = float(rim_width)
        self.rim_height = float(rim_height)
        self.edge_type = str(edge_type)
        self.bevel_width = float(bevel_width)
        self.bevel_height = float(bevel_height)
        self.resolution = int(resolution)
        self.field_rings = int(field_rings)
        self.reverse_relief_pattern = reverse_relief_pattern or self.relief_pattern
        self.edge_inscription = edge_inscription
        self.edge_inscription_depth = float(edge_inscription_depth)
        self.edge_inscription_mode = str(edge_inscription_mode)
        self.security_stamp_seed = security_stamp_seed
        self.security_stamp_grooves = int(security_stamp_grooves)
        self.segmented_sectors = int(segmented_sectors)

        if preset:
            p_data = resolve_preset(preset)
            if p_data:
                self.radius = float(p_data.get("radius", self.radius))
                self.thickness = float(p_data.get("thickness", self.thickness))
                self.serrations = int(p_data.get("serrations", self.serrations))
                self.rim_width = float(p_data.get("rim_width", self.rim_width))
                self.rim_height = float(p_data.get("rim_height", self.rim_height))
                self.relief_pattern = str(p_data.get("relief_pattern", self.relief_pattern))
                self.edge_type = str(p_data.get("edge_type", self.edge_type))
                self.bevel_width = float(p_data.get("bevel_width", self.bevel_width))
                self.bevel_height = float(p_data.get("bevel_height", self.bevel_height))
                if not reverse_relief_pattern:
                    self.reverse_relief_pattern = self.relief_pattern

    def generate(self) -> MeshData:
        """Generate a watertight, manifold 3D coin mesh."""
        reed_profile_map = {
            "reeded": "sinusoidal",
            "serrated": "trapezoidal",
            "milled": "square",
            "plain": "sinusoidal",
        }
        profile = reed_profile_map.get(self.edge_type.lower(), "sinusoidal")
        reed_count = 0 if self.edge_type.lower() == "plain" else self.serrations

        obv_hm = generate_relief_heightmap(self.relief_pattern, grid_size=64)
        rev_hm = generate_relief_heightmap(self.reverse_relief_pattern, grid_size=64)

        params = CoinParameters(
            radius=self.radius,
            thickness=self.thickness,
            rim_width=self.rim_width,
            rim_height=self.rim_height,
            edge_reed_count=reed_count,
            reed_depth=0.25 if reed_count > 0 else 0.0,
            reed_profile=profile,
            bevel_width=self.bevel_width,
            bevel_height=self.bevel_height,
            radial_segments=max(32, self.resolution),
            field_rings=max(8, self.field_rings),
            obverse_heightmap=obv_hm,
            reverse_heightmap=rev_hm,
            relief_depth_obverse=self.rim_height * 0.9,
            relief_depth_reverse=self.rim_height * 0.9,
            edge_inscription=self.edge_inscription,
            edge_inscription_depth=self.edge_inscription_depth,
            edge_inscription_mode=self.edge_inscription_mode,
            security_stamp_seed=self.security_stamp_seed,
            security_stamp_grooves=self.security_stamp_grooves,
            segmented_sectors=self.segmented_sectors,
            smooth_shading=True,
        )
        return CoinMeshEngine(params).generate()

    def export_stl(self, filepath: PathLike, binary: bool = True) -> Path:
        """Export the generated 3D coin mesh as STL."""
        mesh = self.generate()
        if binary:
            return export_binary_stl(mesh, filepath)
        return export_ascii_stl(mesh, filepath)

    def export_obj(
        self,
        filepath: PathLike,
        object_name: str = "CoinMesh",
        include_normals: bool = True,
    ) -> Path:
        """Export the generated 3D coin mesh as Wavefront OBJ."""
        mesh = self.generate()
        written, _ = export_obj_files(mesh, filepath, object_name=object_name)
        return written

    def get_summary(self) -> Dict[str, Any]:
        """Generate full metadata, physical estimates, and mesh metrics."""
        mesh = self.generate()
        vol = compute_mesh_volume(mesh)
        weights = compute_mesh_weights(vol)
        min_pt, max_pt = mesh.get_bounding_box()
        return {
            "parameters": {
                "radius_mm": self.radius,
                "diameter_mm": self.radius * 2.0,
                "thickness_mm": self.thickness,
                "serrations": self.serrations,
                "relief_pattern": self.relief_pattern,
                "rim_width_mm": self.rim_width,
                "rim_height_mm": self.rim_height,
                "edge_type": self.edge_type,
            },
            "mesh_stats": {
                "vertex_count": mesh.vertex_count,
                "triangle_count": mesh.triangle_count,
                "is_watertight": mesh.is_watertight(),
                "bounding_box_min": min_pt,
                "bounding_box_max": max_pt,
                "dimensions_mm": {
                    "width": round(max_pt[0] - min_pt[0], 2),
                    "depth": round(max_pt[1] - min_pt[1], 2),
                    "height": round(max_pt[2] - min_pt[2], 2),
                },
            },
            "physical_estimates": {
                "volume_mm3": round(vol, 2),
                "volume_cm3": round(vol / 1000.0, 4),
                "weights_g": weights,
            },
        }


# ---------------------------------------------------------------------------
# Public API Convenience Functions
# ---------------------------------------------------------------------------

def generate_coin_mesh(
    radius: float = 20.0,
    thickness: float = 3.0,
    serrations: int = 80,
    relief_pattern: str = "wreath",
    rim_width: float = 2.0,
    rim_height: float = 0.4,
    edge_type: str = "reeded",
    resolution: int = 64,
    preset: Optional[str] = None,
    **kwargs: Any,
) -> MeshData:
    """Generate a 3D coin MeshData directly from parameters or preset name."""
    gen = CoinGenerator(
        radius=radius,
        thickness=thickness,
        serrations=serrations,
        relief_pattern=relief_pattern,
        rim_width=rim_width,
        rim_height=rim_height,
        edge_type=edge_type,
        resolution=resolution,
        preset=preset,
        **kwargs,
    )
    return gen.generate()


def export_stl(
    mesh_or_generator: Union[MeshData, CoinGenerator, Dict[str, Any]],
    filepath: PathLike,
    binary: bool = True,
    **kwargs: Any,
) -> Path:
    """Export 3D coin mesh or generator object to an STL file."""
    if isinstance(mesh_or_generator, MeshData):
        if binary:
            return export_binary_stl(mesh_or_generator, filepath)
        return export_ascii_stl(mesh_or_generator, filepath)
    elif isinstance(mesh_or_generator, CoinGenerator):
        return mesh_or_generator.export_stl(filepath, binary=binary)
    elif isinstance(mesh_or_generator, dict):
        gen = CoinGenerator(**mesh_or_generator)
        return gen.export_stl(filepath, binary=binary)
    else:
        raise TypeError(f"Unsupported type for export_stl: {type(mesh_or_generator)}")


def export_obj(
    mesh_or_generator: Union[MeshData, CoinGenerator, Dict[str, Any]],
    filepath: PathLike,
    object_name: str = "CoinMesh",
    include_normals: bool = True,
    **kwargs: Any,
) -> Path:
    """Export 3D coin mesh or generator object to a Wavefront OBJ file."""
    if isinstance(mesh_or_generator, MeshData):
        written, _ = export_obj_files(mesh_or_generator, filepath, object_name=object_name)
        return written
    elif isinstance(mesh_or_generator, CoinGenerator):
        return mesh_or_generator.export_obj(filepath, object_name=object_name, include_normals=include_normals)
    elif isinstance(mesh_or_generator, dict):
        gen = CoinGenerator(**mesh_or_generator)
        return gen.export_obj(filepath, object_name=object_name, include_normals=include_normals)
    else:
        raise TypeError(f"Unsupported type for export_obj: {type(mesh_or_generator)}")


def slice_coin(
    mesh_or_generator: Union[MeshData, CoinGenerator, Dict[str, Any]],
    config: Optional[SlicingConfig] = None,
) -> SliceResult:
    """Slice a 3D coin mesh into G-code layers with infill and printability telemetry."""
    if isinstance(mesh_or_generator, MeshData):
        mesh = mesh_or_generator
    elif isinstance(mesh_or_generator, CoinGenerator):
        mesh = mesh_or_generator.generate()
    elif isinstance(mesh_or_generator, dict):
        gen = CoinGenerator(**mesh_or_generator)
        mesh = gen.generate()
    else:
        raise TypeError(f"Unsupported type for slice_coin: {type(mesh_or_generator)}")

    return slice_mesh(mesh, config=config)


# Lazy imports for entry points to avoid cyclic dependencies
def run_mcp_server() -> None:
    """Entry point for running the Model Context Protocol (MCP) server."""
    from .mcp_server import run_mcp_server as _run
    _run()


def main() -> None:
    """CLI entry point."""
    from .cli import main as _main
    _main()


__all__ = [
    "CoinGenerator",
    "MeshData",
    "CoinParameters",
    "CoinMeshEngine",
    "generate_cartesian_relief_mesh",
    "Heightmap",
    "ProceduralReliefBuilder",
    "SVGRasterizer",
    "COIN_PRESETS",
    "generate_coin_mesh",
    "export_stl",
    "export_obj",
    "export_binary_stl",
    "export_ascii_stl",
    "export_gltf",
    "export_glb",
    "export_mesh",
    "get_coin_presets",
    "resolve_preset",
    "generate_relief_heightmap",
    "compute_mesh_volume",
    "compute_mesh_weights",
    # Slicer Engine
    "InfillPattern",
    "FilamentType",
    "SliceSegment2D",
    "SliceLayer",
    "OverhangAnalysis",
    "SlicingConfig",
    "SliceResult",
    "analyze_mesh_overhangs",
    "slice_mesh",
    "slice_coin",
    # Edge Milling & Cryptographic Stamp
    "EdgeInscriptionSpec",
    "SecurityStampSpec",
    "SegmentedReedingSpec",
    "CompoundMillingSpec",
    "compute_edge_milling_radius",
    "derive_crypto_teeth_pattern",
    "generate_edge_milling_profile_summary",
    "run_mcp_server",
    "main",
    "__version__",
]
