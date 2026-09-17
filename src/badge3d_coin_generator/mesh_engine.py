"""Pure Python 3D Parametric Coin Geometry & Mesh Generation Engine.

Generates watertight 3D meshes for commemorative coins, challenge coins,
and relief medallions with parametric control over:
- Coin dimensions (diameter, thickness, rim width, rim height)
- Edge detailing (sinusoidal, square, fluted, trapezoidal reeding/serrations)
- Obverse (front) and Reverse (back) 2D heightmap displacement embossing
- Multi-segment beveling and chamfers
- Normal computation (smooth vertex normals, area-weighted, or flat face normals)
- UV texture coordinate generation

Zero external dependencies (100% Python Standard Library).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

# Type aliases
Vec2 = Tuple[float, float]
Vec3 = Tuple[float, float, float]
Face3 = Tuple[int, int, int]


# ---------------------------------------------------------------------------
# Vector Math Utilities (Pure Python)
# ---------------------------------------------------------------------------

def vec3_add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vec3_sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vec3_scale(v: Vec3, s: float) -> Vec3:
    return (v[0] * s, v[1] * s, v[2] * s)


def vec3_dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vec3_cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def vec3_length(v: Vec3) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def vec3_normalize(v: Vec3, default: Vec3 = (0.0, 0.0, 1.0)) -> Vec3:
    length = vec3_length(v)
    if length > 1e-9:
        inv = 1.0 / length
        return (v[0] * inv, v[1] * inv, v[2] * inv)
    return default


def triangle_normal(v0: Vec3, v1: Vec3, v2: Vec3) -> Vec3:
    """Compute normalized geometric face normal for a triangle (v0, v1, v2)."""
    e1 = vec3_sub(v1, v0)
    e2 = vec3_sub(v2, v0)
    cross = vec3_cross(e1, e2)
    return vec3_normalize(cross)


def triangle_area(v0: Vec3, v1: Vec3, v2: Vec3) -> float:
    """Compute surface area of triangle (v0, v1, v2)."""
    e1 = vec3_sub(v1, v0)
    e2 = vec3_sub(v2, v0)
    cross = vec3_cross(e1, e2)
    return 0.5 * vec3_length(cross)


# ---------------------------------------------------------------------------
# Core Mesh Data Structure
# ---------------------------------------------------------------------------

@dataclass
class MeshData:
    """Represents a 3D polygonal triangle mesh.

    Attributes:
        vertices: List of 3D points (x, y, z).
        normals: List of 3D unit normal vectors corresponding to vertices or faces.
        faces: List of 3-tuples containing 0-based vertex indices.
        uvs: List of 2D texture coordinates (u, v) in [0.0, 1.0].
        materials: Optional list of material identifiers per face or group.
    """

    vertices: List[Vec3] = field(default_factory=list)
    normals: List[Vec3] = field(default_factory=list)
    faces: List[Face3] = field(default_factory=list)
    uvs: List[Vec2] = field(default_factory=list)
    materials: Optional[List[str]] = None

    @property
    def vertex_count(self) -> int:
        return len(self.vertices)

    @property
    def triangle_count(self) -> int:
        return len(self.faces)

    def get_bounding_box(self) -> Tuple[Vec3, Vec3]:
        """Compute the axis-aligned bounding box (min_point, max_point)."""
        if not self.vertices:
            return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        min_x = min_y = min_z = float("inf")
        max_x = max_y = max_z = float("-inf")
        for x, y, z in self.vertices:
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y
            if z < min_z:
                min_z = z
            if z > max_z:
                max_z = z
        return ((min_x, min_y, min_z), (max_x, max_y, max_z))

    def compute_normals(self, smooth: bool = True, weight_by_area: bool = True) -> None:
        """Compute surface normal vectors for all vertices.

        Args:
            smooth: If True, computes area-weighted averaged vertex normals for
                smooth shading. If False, computes flat face normals.
            weight_by_area: If True, weights face contributions by triangle area.
        """
        if not self.vertices or not self.faces:
            self.normals = [(0.0, 0.0, 1.0)] * len(self.vertices)
            return

        if not smooth:
            # Flat normals: each face gets its geometric normal
            # (Requires duplicating vertices if per-vertex normals are needed)
            self.normals = []
            for i0, i1, i2 in self.faces:
                v0 = self.vertices[i0]
                v1 = self.vertices[i1]
                v2 = self.vertices[i2]
                norm = triangle_normal(v0, v1, v2)
                self.normals.append(norm)
            return

        # Smooth vertex normals: accumulate face normals into vertices
        accum_normals: List[List[float]] = [[0.0, 0.0, 0.0] for _ in range(len(self.vertices))]

        for i0, i1, i2 in self.faces:
            v0 = self.vertices[i0]
            v1 = self.vertices[i1]
            v2 = self.vertices[i2]
            e1 = vec3_sub(v1, v0)
            e2 = vec3_sub(v2, v0)
            cross = vec3_cross(e1, e2)
            c_len = vec3_length(cross)

            if c_len > 1e-12:
                # If weight_by_area is True, unnormalized cross product is directly proportional to area!
                weight = 1.0 if not weight_by_area else (0.5 * c_len)
                n = vec3_scale(cross, weight / c_len)
                for idx in (i0, i1, i2):
                    accum_normals[idx][0] += n[0]
                    accum_normals[idx][1] += n[1]
                    accum_normals[idx][2] += n[2]

        self.normals = [
            vec3_normalize((nx, ny, nz), default=(0.0, 0.0, 1.0))
            for nx, ny, nz in accum_normals
        ]

    def merge(self, other: MeshData) -> MeshData:
        """Merge this mesh with another, offsetting vertex indices properly."""
        offset = len(self.vertices)
        new_vertices = list(self.vertices) + list(other.vertices)
        new_normals = list(self.normals) + list(other.normals) if (self.normals and other.normals) else []
        new_uvs = list(self.uvs) + list(other.uvs) if (self.uvs and other.uvs) else []
        new_faces = list(self.faces) + [(f[0] + offset, f[1] + offset, f[2] + offset) for f in other.faces]

        new_materials = None
        if self.materials is not None or other.materials is not None:
            m1 = self.materials or ["default"] * len(self.faces)
            m2 = other.materials or ["default"] * len(other.faces)
            new_materials = m1 + m2

        return MeshData(
            vertices=new_vertices,
            normals=new_normals,
            faces=new_faces,
            uvs=new_uvs,
            materials=new_materials,
        )

    def transform(
        self,
        scale: Vec3 = (1.0, 1.0, 1.0),
        rotation_deg: Vec3 = (0.0, 0.0, 0.0),
        translation: Vec3 = (0.0, 0.0, 0.0),
    ) -> MeshData:
        """Apply scale, Euler XYZ rotation (in degrees), and translation to the mesh."""
        rx = math.radians(rotation_deg[0])
        ry = math.radians(rotation_deg[1])
        rz = math.radians(rotation_deg[2])

        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)

        # Combined Euler rotation matrix R = Rz * Ry * Rx
        r00 = cz * cy
        r01 = cz * sy * sx - sz * cx
        r02 = cz * sy * cx + sz * sx

        r10 = sz * cy
        r11 = sz * sy * sx + cz * cx
        r12 = sz * sy * cx - cz * sx

        r20 = -sy
        r21 = cy * sx
        r22 = cy * cx

        transformed_verts: List[Vec3] = []
        for x, y, z in self.vertices:
            # Scale
            sx_val, sy_val, sz_val = x * scale[0], y * scale[1], z * scale[2]
            # Rotate
            rx_val = r00 * sx_val + r01 * sy_val + r02 * sz_val
            ry_val = r10 * sx_val + r11 * sy_val + r12 * sz_val
            rz_val = r20 * sx_val + r21 * sy_val + r22 * sz_val
            # Translate
            transformed_verts.append((
                rx_val + translation[0],
                ry_val + translation[1],
                rz_val + translation[2],
            ))

        transformed_normals: List[Vec3] = []
        for nx, ny, nz in self.normals:
            # Normal rotation
            nrx = r00 * nx + r01 * ny + r02 * nz
            nry = r10 * nx + r11 * ny + r12 * nz
            nrz = r20 * nx + r21 * ny + r22 * nz
            transformed_normals.append(vec3_normalize((nrx, nry, nrz)))

        return MeshData(
            vertices=transformed_verts,
            normals=transformed_normals,
            faces=list(self.faces),
            uvs=list(self.uvs),
            materials=list(self.materials) if self.materials else None,
        )

    def invert_faces(self) -> None:
        """Invert triangle winding order and flip normal directions."""
        self.faces = [(f[0], f[2], f[1]) for f in self.faces]
        self.normals = [(-n[0], -n[1], -n[2]) for n in self.normals]

    def is_watertight(self) -> bool:
        """Check if the mesh is a closed 2-manifold without boundary holes."""
        if not self.faces:
            return False

        edge_counts: Dict[Tuple[int, int], int] = {}
        for i0, i1, i2 in self.faces:
            edges = [
                (i0, i1) if i0 < i1 else (i1, i0),
                (i1, i2) if i1 < i2 else (i2, i1),
                (i2, i0) if i2 < i0 else (i0, i2),
            ]
            for edge in edges:
                edge_counts[edge] = edge_counts.get(edge, 0) + 1

        # Every edge must be shared by exactly 2 faces for a closed manifold
        return all(count == 2 for count in edge_counts.values())


# ---------------------------------------------------------------------------
# Reed / Serration Profile Generator
# ---------------------------------------------------------------------------

def calculate_reed_radius(
    base_radius: float,
    angle_rad: float,
    reed_count: int,
    reed_depth: float,
    profile: str = "sinusoidal",
) -> float:
    """Calculate the modified radius at a given circumference angle for coin reeding.

    Args:
        base_radius: Outer coin cylinder radius.
        angle_rad: Angle around circumference in radians [0..2*pi].
        reed_count: Number of ridges around the perimeter (0 for smooth).
        reed_depth: Radial amplitude of ridges (in mm).
        profile: Profile style: 'sinusoidal', 'square', 'triangular', 'trapezoidal', 'fluted'.

    Returns:
        The evaluated radius at that angle.
    """
    if reed_count <= 0 or reed_depth <= 1e-6:
        return base_radius

    # Phase in [0..1)
    cycle = (angle_rad * reed_count / (2.0 * math.pi)) % 1.0

    if profile == "sinusoidal":
        # Smooth sinusoidal groove: depth ranges from 0 to reed_depth
        val = 0.5 * (1.0 + math.cos(2.0 * math.pi * cycle))
        return base_radius - (1.0 - val) * reed_depth

    elif profile == "square":
        # Square tooth with small slope transition to prevent zero-width non-manifold faces
        if cycle < 0.45:
            val = 1.0
        elif cycle < 0.50:
            val = 1.0 - (cycle - 0.45) / 0.05
        elif cycle < 0.95:
            val = 0.0
        else:
            val = (cycle - 0.95) / 0.05
        return base_radius - (1.0 - val) * reed_depth

    elif profile == "triangular":
        # Triangular saw tooth
        val = 1.0 - 2.0 * abs(cycle - 0.5)
        return base_radius - (1.0 - val) * reed_depth

    elif profile == "trapezoidal":
        # Classic fluted mint reed: flat crest, sloped ramp, flat trough
        if cycle < 0.3:
            val = 1.0
        elif cycle < 0.5:
            val = 1.0 - (cycle - 0.3) / 0.2
        elif cycle < 0.8:
            val = 0.0
        else:
            val = (cycle - 0.8) / 0.2
        return base_radius - (1.0 - val) * reed_depth

    elif profile == "fluted":
        # Concave circular gouge/flute cut into the rim
        # Flat rim with concave cylindrical scallop
        if 0.25 <= cycle <= 0.75:
            # Normalized [-1..1] across the groove
            t = (cycle - 0.5) / 0.25
            depth_factor = math.sqrt(max(0.0, 1.0 - t * t))
            return base_radius - depth_factor * reed_depth
        return base_radius

    elif profile in ("helical_milled", "helical", "milled_bevel"):
        # Asymmetric angled helical cutter notch
        saw = (cycle * 2.0) % 1.0
        val = math.sin(saw * math.pi) ** 1.5
        return base_radius - (1.0 - val) * reed_depth

    elif profile in ("segmented", "lettered_edge"):
        # Alternating reeded groups and plain smooth segments
        segment_group = int(angle_rad * 6.0 / (2.0 * math.pi)) % 2
        if segment_group == 0:
            val = 0.5 * (1.0 + math.cos(2.0 * math.pi * cycle))
            return base_radius - (1.0 - val) * reed_depth
        return base_radius

    else:
        # Default sinusoidal
        val = 0.5 * (1.0 + math.cos(2.0 * math.pi * cycle))
        return base_radius - (1.0 - val) * reed_depth


# ---------------------------------------------------------------------------
# Heightmap Sampler Helper
# ---------------------------------------------------------------------------

def sample_heightmap_bilinear(
    heightmap: Optional[Sequence[Sequence[float]]],
    u: float,
    v: float,
    default: float = 0.0,
) -> float:
    """Sample a 2D float elevation grid using bilinear interpolation.

    UV coordinates are expected in [0.0, 1.0].
    """
    if heightmap is None or len(heightmap) == 0 or len(heightmap[0]) == 0:
        return default

    # Clamp UV to [0.0, 1.0]
    u = max(0.0, min(1.0, u))
    v = max(0.0, min(1.0, v))

    h = len(heightmap)
    w = len(heightmap[0])

    # Convert to continuous pixel coordinates
    px = u * (w - 1)
    py = v * (h - 1)

    x0 = int(px)
    y0 = int(py)
    x1 = min(x0 + 1, w - 1)
    y1 = min(y0 + 1, h - 1)

    fx = px - x0
    fy = py - y0

    # Bilinear interpolate
    top = (1.0 - fx) * heightmap[y0][x0] + fx * heightmap[y0][x1]
    bot = (1.0 - fx) * heightmap[y1][x0] + fx * heightmap[y1][x1]

    return (1.0 - fy) * top + fy * bot


# ---------------------------------------------------------------------------
# Parametric Coin Configuration & Mesh Generator
# ---------------------------------------------------------------------------

@dataclass
class CoinParameters:
    """Parametric dimensions and detailing configuration for 3D coin generation.

    All physical dimensions are in millimeters (mm).
    """

    radius: float = 20.0
    """Outer radius of the coin body (default 20.0mm -> 40mm diameter)."""

    thickness: float = 3.0
    """Total coin thickness at the rim peak (in mm)."""

    rim_width: float = 1.5
    """Width of the raised outer rim bordering the inner relief field (in mm)."""

    rim_height: float = 0.4
    """Height of the raised rim above the inner recessed base field (in mm)."""

    edge_reed_count: int = 120
    """Number of reeded serrations around the circumference (0 for smooth edge)."""

    reed_depth: float = 0.25
    """Radial depth/amplitude of the edge serrations (in mm)."""

    reed_profile: str = "sinusoidal"
    """Reeding style: 'sinusoidal', 'square', 'triangular', 'trapezoidal', 'fluted'."""

    bevel_width: float = 0.4
    """Width of the chamfer/bevel on outer rim top edges (in mm)."""

    bevel_height: float = 0.4
    """Height of the chamfer/bevel on outer rim edges (in mm)."""

    radial_segments: int = 180
    """Number of circumferential angular divisions for high mesh smoothness."""

    field_rings: int = 48
    """Number of concentric rings on inner obverse/reverse polar mesh grids."""

    obverse_heightmap: Optional[Sequence[Sequence[float]]] = None
    """2D grid of elevation values in [0.0, 1.0] for front face relief."""

    reverse_heightmap: Optional[Sequence[Sequence[float]]] = None
    """2D grid of elevation values in [0.0, 1.0] for back face relief."""

    relief_depth_obverse: float = 0.6
    """Maximum elevation displacement height for obverse relief (in mm)."""

    relief_depth_reverse: float = 0.6
    """Maximum elevation displacement height for reverse relief (in mm)."""

    relief_mode_obverse: str = "emboss"
    """Obverse relief mode: 'emboss' (raised), 'engrave' (cut into), 'bi-directional'."""

    relief_mode_reverse: str = "emboss"
    """Reverse relief mode: 'emboss' (raised), 'engrave' (cut into), 'bi-directional'."""

    hole_radius: float = 0.0
    """Central hole radius (e.g. for donut coin / keychain loop, 0.0 for solid)."""

    smooth_shading: bool = True
    """Whether to compute smooth area-weighted vertex normals."""

    edge_inscription: Optional[str] = None
    """Text inscription running along the cylindrical rim (e.g. 'E PLURIBUS UNUM')."""

    edge_inscription_depth: float = 0.25
    """Engraving or embossing depth for edge lettering (in mm)."""

    edge_inscription_mode: str = "incuse"
    """Lettering mode: 'incuse' (engraved) or 'raised' (embossed)."""

    security_stamp_seed: Optional[str] = None
    """Seed string for cryptographic hash-derived security anti-counterfeiting rim grooves."""

    security_stamp_grooves: int = 64
    """Number of hash-derived anti-counterfeiting micro-grooves around perimeter."""

    segmented_sectors: int = 0
    """Number of reeded sectors for segmented reeding (0 for continuous)."""

    edge_vertical_slices: int = 1
    """Vertical subdivisions along cylindrical rim."""



class CoinMeshEngine:
    """3D Parametric Mesh Engine for generating challenge coins and badges."""

    def __init__(self, params: Optional[CoinParameters] = None) -> None:
        self.params = params or CoinParameters()

    def generate(self) -> MeshData:
        """Generate a complete, watertight, manifold 3D coin mesh.

        Constructs:
        1. Obverse (front) polar relief field with heightmap displacement.
        2. Obverse inner rim step wall.
        3. Obverse top rim face ring.
        4. Obverse outer edge chamfer / bevel.
        5. Cylindrical reeded edge with serrated ridges.
        6. Reverse outer edge chamfer / bevel.
        7. Reverse top rim face ring.
        8. Reverse inner rim step wall.
        9. Reverse (back) polar relief field with heightmap displacement.
        """
        p = self.params

        # Validate and adjust parameters to avoid self-intersecting degenerate geometry
        radius = max(1.0, p.radius)
        thickness = max(0.5, p.thickness)
        rim_width = max(0.2, min(p.rim_width, radius * 0.4))
        rim_height = max(0.05, min(p.rim_height, thickness * 0.45))
        field_radius = radius - rim_width

        bevel_w = max(0.0, min(p.bevel_width, rim_width * 0.8))
        bevel_h = max(0.0, min(p.bevel_height, (thickness * 0.5) - 0.1))

        segments = max(16, p.radial_segments)
        # If reeded, ensure segments is an integer multiple of reed count for clean topology
        if p.edge_reed_count > 0:
            reeds = p.edge_reed_count
            samples_per_reed = max(2, math.ceil(segments / reeds))
            segments = reeds * samples_per_reed

        rings = max(4, p.field_rings)

        half_thick = thickness * 0.5
        field_base_z_obverse = half_thick - rim_height
        field_base_z_reverse = -half_thick + rim_height

        vertices: List[Vec3] = []
        uvs: List[Vec2] = []
        faces: List[Face3] = []

        # -------------------------------------------------------------------
        # Helper: Heightmap displacement elevation calculators
        # -------------------------------------------------------------------
        def get_obverse_z(norm_r: float, theta: float) -> float:
            # Map polar coordinates to UV [0..1]
            u = 0.5 + 0.5 * norm_r * math.cos(theta)
            v = 0.5 - 0.5 * norm_r * math.sin(theta)  # SVG top-down coordinate
            val = sample_heightmap_bilinear(p.obverse_heightmap, u, v, 0.0)

            if p.relief_mode_obverse == "engrave":
                disp = -val * p.relief_depth_obverse
            elif p.relief_mode_obverse == "bi-directional":
                disp = (val - 0.5) * 2.0 * p.relief_depth_obverse
            else:  # emboss
                disp = val * p.relief_depth_obverse

            return field_base_z_obverse + disp

        def get_reverse_z(norm_r: float, theta: float) -> float:
            # Mirrored horizontally for back side
            u = 0.5 - 0.5 * norm_r * math.cos(theta)
            v = 0.5 - 0.5 * norm_r * math.sin(theta)
            val = sample_heightmap_bilinear(p.reverse_heightmap, u, v, 0.0)

            if p.relief_mode_reverse == "engrave":
                disp = -val * p.relief_depth_reverse
            elif p.relief_mode_reverse == "bi-directional":
                disp = (val - 0.5) * 2.0 * p.relief_depth_reverse
            else:  # emboss
                disp = val * p.relief_depth_reverse

            # Reverse side points downwards (-Z)
            return field_base_z_reverse - disp

        # -------------------------------------------------------------------
        # 1. OBVERSE FIELD (Concentric Polar Grid)
        # -------------------------------------------------------------------
        # Center vertex (ring 0)
        center_z_obv = get_obverse_z(0.0, 0.0)
        vertices.append((0.0, 0.0, center_z_obv))
        uvs.append((0.5, 0.5))
        obv_center_idx = 0

        # Concentric rings 1..rings
        obv_ring_start_indices: List[int] = []
        for r_step in range(1, rings + 1):
            r_ratio = r_step / rings
            cur_r = field_radius * r_ratio
            ring_start = len(vertices)
            obv_ring_start_indices.append(ring_start)

            for s in range(segments):
                theta = (2.0 * math.pi * s) / segments
                x = cur_r * math.cos(theta)
                y = cur_r * math.sin(theta)
                z = get_obverse_z(r_ratio, theta)
                vertices.append((x, y, z))
                u = 0.5 + 0.5 * r_ratio * math.cos(theta)
                v = 0.5 - 0.5 * r_ratio * math.sin(theta)
                uvs.append((u, v))

        # Obverse center fan faces (connect center to ring 1)
        first_ring_idx = obv_ring_start_indices[0]
        for s in range(segments):
            next_s = (s + 1) % segments
            # Counter-clockwise when viewed from +Z
            faces.append((obv_center_idx, first_ring_idx + s, first_ring_idx + next_s))

        # Obverse grid quads between ring k and ring k+1
        for k in range(rings - 1):
            curr_r_start = obv_ring_start_indices[k]
            next_r_start = obv_ring_start_indices[k + 1]
            for s in range(segments):
                next_s = (s + 1) % segments
                v0 = curr_r_start + s
                v1 = next_r_start + s
                v2 = next_r_start + next_s
                v3 = curr_r_start + next_s
                # Triangulate quad
                faces.append((v0, v1, v2))
                faces.append((v0, v2, v3))

        # Outer edge index of obverse field
        obv_field_outer_start = obv_ring_start_indices[-1]

        # -------------------------------------------------------------------
        # 2. OBVERSE INNER RIM STEP WALL (from field edge up to rim level)
        # -------------------------------------------------------------------
        obv_inner_rim_top_start = len(vertices)
        for s in range(segments):
            theta = (2.0 * math.pi * s) / segments
            x = field_radius * math.cos(theta)
            y = field_radius * math.sin(theta)
            vertices.append((x, y, half_thick))
            uvs.append((0.5 + 0.5 * math.cos(theta), 0.5 - 0.5 * math.sin(theta)))

        for s in range(segments):
            next_s = (s + 1) % segments
            f_curr = obv_field_outer_start + s
            f_next = obv_field_outer_start + next_s
            r_curr = obv_inner_rim_top_start + s
            r_next = obv_inner_rim_top_start + next_s
            faces.append((f_curr, r_curr, r_next))
            faces.append((f_curr, r_next, f_next))

        # -------------------------------------------------------------------
        # 3. OBVERSE RIM TOP FACE (from field_radius to radius - bevel_width)
        # -------------------------------------------------------------------
        rim_bevel_in_r = radius - bevel_w
        obv_bevel_in_start = len(vertices)
        for s in range(segments):
            theta = (2.0 * math.pi * s) / segments
            x = rim_bevel_in_r * math.cos(theta)
            y = rim_bevel_in_r * math.sin(theta)
            vertices.append((x, y, half_thick))
            uvs.append((0.5 + 0.5 * (rim_bevel_in_r / radius) * math.cos(theta),
                        0.5 - 0.5 * (rim_bevel_in_r / radius) * math.sin(theta)))

        for s in range(segments):
            next_s = (s + 1) % segments
            r_curr = obv_inner_rim_top_start + s
            r_next = obv_inner_rim_top_start + next_s
            b_curr = obv_bevel_in_start + s
            b_next = obv_bevel_in_start + next_s
            faces.append((r_curr, b_curr, b_next))
            faces.append((r_curr, b_next, r_next))

        # -------------------------------------------------------------------
        # 4. OBVERSE OUTER BEVEL (from rim_bevel_in_r to reeded edge at top)
        # -------------------------------------------------------------------
        from .edge_milling import (
            CompoundMillingSpec,
            EdgeInscriptionSpec,
            SecurityStampSpec,
            SegmentedReedingSpec,
            compute_edge_milling_radius,
        )

        has_advanced_edge = bool(p.edge_inscription or p.security_stamp_seed or p.segmented_sectors > 0)
        v_slices = max(1, p.edge_vertical_slices)
        if has_advanced_edge and v_slices < 8:
            v_slices = 8

        milling_spec = CompoundMillingSpec(
            reeding_profile=p.reed_profile,
            reed_count=p.edge_reed_count,
            reed_depth=p.reed_depth,
            inscription=EdgeInscriptionSpec(
                text=p.edge_inscription,
                depth=p.edge_inscription_depth,
                mode=p.edge_inscription_mode,
            ) if p.edge_inscription else None,
            security_stamp=SecurityStampSpec(
                seed=p.security_stamp_seed,
                num_grooves=p.security_stamp_grooves,
            ) if p.security_stamp_seed else None,
            segmented=SegmentedReedingSpec(
                reeded_sectors=p.segmented_sectors,
                reeds_per_sector=max(1, p.edge_reed_count // max(1, p.segmented_sectors * 2)),
                reed_depth=p.reed_depth,
            ) if p.segmented_sectors > 0 else None,
        )

        z_edge_top = half_thick - bevel_h
        edge_top_start = len(vertices)
        for s in range(segments):
            theta = (2.0 * math.pi * s) / segments
            if has_advanced_edge:
                cur_r = compute_edge_milling_radius(radius, theta, z_edge_top, thickness, milling_spec)
            else:
                cur_r = calculate_reed_radius(radius, theta, p.edge_reed_count, p.reed_depth, p.reed_profile)
            x = cur_r * math.cos(theta)
            y = cur_r * math.sin(theta)
            vertices.append((x, y, z_edge_top))
            uvs.append((s / segments, 1.0))

        for s in range(segments):
            next_s = (s + 1) % segments
            b_curr = obv_bevel_in_start + s
            b_next = obv_bevel_in_start + next_s
            e_curr = edge_top_start + s
            e_next = edge_top_start + next_s
            faces.append((b_curr, e_curr, e_next))
            faces.append((b_curr, e_next, b_next))

        # -------------------------------------------------------------------
        # 5. CYLINDRICAL REEDED & INSCRIBED EDGE (from +z_edge_top down to -z_edge_top)
        # -------------------------------------------------------------------
        z_edge_bot = -z_edge_top
        edge_ring_starts = [edge_top_start]
        for slice_idx in range(1, v_slices + 1):
            cur_z = z_edge_top - slice_idx * (z_edge_top - z_edge_bot) / v_slices
            ring_start = len(vertices)
            edge_ring_starts.append(ring_start)
            for s in range(segments):
                theta = (2.0 * math.pi * s) / segments
                if has_advanced_edge:
                    cur_r = compute_edge_milling_radius(radius, theta, cur_z, thickness, milling_spec)
                else:
                    cur_r = calculate_reed_radius(radius, theta, p.edge_reed_count, p.reed_depth, p.reed_profile)
                x = cur_r * math.cos(theta)
                y = cur_r * math.sin(theta)
                vertices.append((x, y, cur_z))
                uvs.append((s / segments, 1.0 - (slice_idx / v_slices)))

        for slice_idx in range(v_slices):
            r_top = edge_ring_starts[slice_idx]
            r_bot = edge_ring_starts[slice_idx + 1]
            for s in range(segments):
                next_s = (s + 1) % segments
                et_curr = r_top + s
                et_next = r_top + next_s
                eb_curr = r_bot + s
                eb_next = r_bot + next_s
                faces.append((et_curr, eb_curr, eb_next))
                faces.append((et_curr, eb_next, et_next))

        edge_bot_start = edge_ring_starts[-1]

        # -------------------------------------------------------------------
        # 6. REVERSE OUTER BEVEL (from reeded edge bot to reverse rim bevel in)
        # -------------------------------------------------------------------
        rev_bevel_in_start = len(vertices)
        for s in range(segments):
            theta = (2.0 * math.pi * s) / segments
            x = rim_bevel_in_r * math.cos(theta)
            y = rim_bevel_in_r * math.sin(theta)
            vertices.append((x, y, -half_thick))
            uvs.append((0.5 - 0.5 * (rim_bevel_in_r / radius) * math.cos(theta),
                        0.5 - 0.5 * (rim_bevel_in_r / radius) * math.sin(theta)))

        for s in range(segments):
            next_s = (s + 1) % segments
            eb_curr = edge_bot_start + s
            eb_next = edge_bot_start + next_s
            rb_curr = rev_bevel_in_start + s
            rb_next = rev_bevel_in_start + next_s
            # Winding order flipped for negative Z
            faces.append((eb_curr, rb_next, rb_curr))
            faces.append((eb_curr, eb_next, rb_next))

        # -------------------------------------------------------------------
        # 7. REVERSE RIM TOP FACE (from radius - bevel_width to field_radius)
        # -------------------------------------------------------------------
        rev_inner_rim_top_start = len(vertices)
        for s in range(segments):
            theta = (2.0 * math.pi * s) / segments
            x = field_radius * math.cos(theta)
            y = field_radius * math.sin(theta)
            vertices.append((x, y, -half_thick))
            uvs.append((0.5 - 0.5 * math.cos(theta), 0.5 - 0.5 * math.sin(theta)))

        for s in range(segments):
            next_s = (s + 1) % segments
            rb_curr = rev_bevel_in_start + s
            rb_next = rev_bevel_in_start + next_s
            rt_curr = rev_inner_rim_top_start + s
            rt_next = rev_inner_rim_top_start + next_s
            faces.append((rb_curr, rt_next, rt_curr))
            faces.append((rb_curr, rb_next, rt_next))

        # -------------------------------------------------------------------
        # 8. REVERSE INNER RIM STEP WALL & REVERSE FIELD
        # -------------------------------------------------------------------
        # Reverse concentric rings 1..rings (from field_radius down to ring 1)
        rev_ring_start_indices: List[int] = []
        for r_step in range(1, rings + 1):
            r_ratio = r_step / rings
            cur_r = field_radius * r_ratio
            ring_start = len(vertices)
            rev_ring_start_indices.append(ring_start)

            for s in range(segments):
                theta = (2.0 * math.pi * s) / segments
                x = cur_r * math.cos(theta)
                y = cur_r * math.sin(theta)
                z = get_reverse_z(r_ratio, theta)
                vertices.append((x, y, z))
                u = 0.5 - 0.5 * r_ratio * math.cos(theta)
                v = 0.5 - 0.5 * r_ratio * math.sin(theta)
                uvs.append((u, v))

        # Reverse inner rim step wall (connects rev_inner_rim_top to rev outer ring)
        rev_field_outer_start = rev_ring_start_indices[-1]
        for s in range(segments):
            next_s = (s + 1) % segments
            rt_curr = rev_inner_rim_top_start + s
            rt_next = rev_inner_rim_top_start + next_s
            rf_curr = rev_field_outer_start + s
            rf_next = rev_field_outer_start + next_s
            faces.append((rt_curr, rf_next, rf_curr))
            faces.append((rt_curr, rt_next, rf_next))

        # Reverse grid quads between ring k and ring k+1
        for k in range(rings - 1):
            curr_r_start = rev_ring_start_indices[k]
            next_r_start = rev_ring_start_indices[k + 1]
            for s in range(segments):
                next_s = (s + 1) % segments
                v0 = curr_r_start + s
                v1 = next_r_start + s
                v2 = next_r_start + next_s
                v3 = curr_r_start + next_s
                # Inverted winding for reverse side (-Z normal)
                faces.append((v0, v2, v1))
                faces.append((v0, v3, v2))

        # Reverse center vertex
        center_z_rev = get_reverse_z(0.0, 0.0)
        rev_center_idx = len(vertices)
        vertices.append((0.0, 0.0, center_z_rev))
        uvs.append((0.5, 0.5))

        # Reverse center fan faces
        rev_first_ring_idx = rev_ring_start_indices[0]
        for s in range(segments):
            next_s = (s + 1) % segments
            # Inverted winding
            faces.append((rev_center_idx, rev_first_ring_idx + next_s, rev_first_ring_idx + s))

        # Construct MeshData and compute normals
        mesh = MeshData(vertices=vertices, faces=faces, uvs=uvs)
        mesh.compute_normals(smooth=p.smooth_shading, weight_by_area=True)
        return mesh


# ---------------------------------------------------------------------------
# Additional Parametric Badge Shapes & Utilities
# ---------------------------------------------------------------------------

def generate_cartesian_relief_mesh(
    heightmap: Sequence[Sequence[float]],
    width_mm: float = 40.0,
    height_mm: float = 40.0,
    base_thickness_mm: float = 2.0,
    relief_depth_mm: float = 1.0,
    smooth_shading: bool = True,
) -> MeshData:
    """Generate a solid rectangular plaque / badge mesh from a 2D heightmap matrix.

    Constructs a closed, watertight 6-sided solid block with displaced top surface.
    """
    if not heightmap or not heightmap[0]:
        raise ValueError("Heightmap matrix must not be empty.")

    rows = len(heightmap)
    cols = len(heightmap[0])

    dx = width_mm / (cols - 1)
    dy = height_mm / (rows - 1)
    half_w = width_mm * 0.5
    half_h = height_mm * 0.5
    base_z = -base_thickness_mm

    vertices: List[Vec3] = []
    uvs: List[Vec2] = []
    faces: List[Face3] = []

    # 1. Top grid vertices
    top_grid_indices: List[List[int]] = []
    for r in range(rows):
        row_indices: List[int] = []
        y = half_h - r * dy
        v = r / (rows - 1)
        for c in range(cols):
            x = -half_w + c * dx
            u = c / (cols - 1)
            elevation = heightmap[r][c] * relief_depth_mm
            idx = len(vertices)
            vertices.append((x, y, elevation))
            uvs.append((u, v))
            row_indices.append(idx)
        top_grid_indices.append(row_indices)

    # Top faces
    for r in range(rows - 1):
        for c in range(cols - 1):
            i0 = top_grid_indices[r][c]
            i1 = top_grid_indices[r + 1][c]
            i2 = top_grid_indices[r + 1][c + 1]
            i3 = top_grid_indices[r][c + 1]
            faces.append((i0, i1, i2))
            faces.append((i0, i2, i3))

    # 2. Bottom flat grid vertices
    bot_grid_indices: List[List[int]] = []
    for r in range(rows):
        row_indices = []
        y = half_h - r * dy
        v = r / (rows - 1)
        for c in range(cols):
            x = -half_w + c * dx
            u = c / (cols - 1)
            idx = len(vertices)
            vertices.append((x, y, base_z))
            uvs.append((u, v))
            row_indices.append(idx)
        bot_grid_indices.append(row_indices)

    # Bottom faces (inverted winding)
    for r in range(rows - 1):
        for c in range(cols - 1):
            i0 = bot_grid_indices[r][c]
            i1 = bot_grid_indices[r + 1][c]
            i2 = bot_grid_indices[r + 1][c + 1]
            i3 = bot_grid_indices[r][c + 1]
            faces.append((i0, i2, i1))
            faces.append((i0, i3, i2))

    # 3. Side walls
    # Top edge (r = 0)
    for c in range(cols - 1):
        t0 = top_grid_indices[0][c]
        t1 = top_grid_indices[0][c + 1]
        b0 = bot_grid_indices[0][c]
        b1 = bot_grid_indices[0][c + 1]
        faces.append((t0, t1, b1))
        faces.append((t0, b1, b0))

    # Bottom edge (r = rows - 1)
    for c in range(cols - 1):
        t0 = top_grid_indices[rows - 1][c]
        t1 = top_grid_indices[rows - 1][c + 1]
        b0 = bot_grid_indices[rows - 1][c]
        b1 = bot_grid_indices[rows - 1][c + 1]
        faces.append((t0, b1, t1))
        faces.append((t0, b0, b1))

    # Left edge (c = 0)
    for r in range(rows - 1):
        t0 = top_grid_indices[r][0]
        t1 = top_grid_indices[r + 1][0]
        b0 = bot_grid_indices[r][0]
        b1 = bot_grid_indices[r + 1][0]
        faces.append((t0, b1, t1))
        faces.append((t0, b0, b1))

    # Right edge (c = cols - 1)
    for r in range(rows - 1):
        t0 = top_grid_indices[r][cols - 1]
        t1 = top_grid_indices[r + 1][cols - 1]
        b0 = bot_grid_indices[r][cols - 1]
        b1 = bot_grid_indices[r + 1][cols - 1]
        faces.append((t0, t1, b1))
        faces.append((t0, b1, b0))

    mesh = MeshData(vertices=vertices, faces=faces, uvs=uvs)
    mesh.compute_normals(smooth=smooth_shading, weight_by_area=True)
    return mesh
