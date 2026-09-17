"""G-code Slicer & FDM 3D-Printability Slicing Engine for Badge3D Coin Generator.

Provides direct triangular mesh plane-contour slicing, closed perimeter extraction,
multi-pattern infill generation (rectilinear, grid, concentric, triangles),
overhang angle risk assessment, filament material cost telemetry, and standard
Marlin/RepRap/Klipper G-code synthesis.

Zero third-party runtime dependencies (100% Python Standard Library).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .mesh_engine import MeshData, Vec2, Vec3, vec3_dot, vec3_length, vec3_sub


class InfillPattern(str, Enum):
    """Infill geometric distribution pattern."""

    RECTILINEAR = "rectilinear"
    GRID = "grid"
    CONCENTRIC = "concentric"
    TRIANGLES = "triangles"


class FilamentType(str, Enum):
    """3D printing filament material properties."""

    PLA = "pla"
    PETG = "petg"
    ABS = "abs"
    RESIN = "resin"

    @property
    def density_g_cm3(self) -> float:
        """Physical material density in g/cm³."""
        mapping = {
            FilamentType.PLA: 1.24,
            FilamentType.PETG: 1.27,
            FilamentType.ABS: 1.04,
            FilamentType.RESIN: 1.15,
        }
        return mapping[self]

    @property
    def default_bed_temp(self) -> int:
        mapping = {
            FilamentType.PLA: 60,
            FilamentType.PETG: 75,
            FilamentType.ABS: 100,
            FilamentType.RESIN: 0,
        }
        return mapping[self]

    @property
    def default_nozzle_temp(self) -> int:
        mapping = {
            FilamentType.PLA: 205,
            FilamentType.PETG: 235,
            FilamentType.ABS: 245,
            FilamentType.RESIN: 0,
        }
        return mapping[self]


@dataclass
class SliceSegment2D:
    """A 2D line segment in a horizontal slice plane."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    def to_dict(self) -> Dict[str, float]:
        return {
            "x1": round(self.x1, 3),
            "y1": round(self.y1, 3),
            "x2": round(self.x2, 3),
            "y2": round(self.y2, 3),
            "length": round(self.length, 3),
        }


@dataclass
class SliceLayer:
    """A single discrete horizontal slice at height Z."""

    index: int
    z_height: float
    thickness: float
    perimeters: List[List[Tuple[float, float]]] = field(default_factory=list)
    infill_segments: List[SliceSegment2D] = field(default_factory=list)
    extrusion_length_mm: float = 0.0
    print_time_sec: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "z_height": round(self.z_height, 3),
            "thickness": round(self.thickness, 3),
            "perimeter_count": len(self.perimeters),
            "infill_segment_count": len(self.infill_segments),
            "extrusion_length_mm": round(self.extrusion_length_mm, 2),
            "print_time_sec": round(self.print_time_sec, 2),
        }


@dataclass
class OverhangAnalysis:
    """Analysis of mesh face overhang angles relative to print bed."""

    overhang_threshold_deg: float
    total_faces: int
    steep_faces_count: int
    overhang_area_mm2: float
    overhang_percentage: float
    requires_supports: bool
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overhang_threshold_deg": self.overhang_threshold_deg,
            "total_faces": self.total_faces,
            "steep_faces_count": self.steep_faces_count,
            "overhang_area_mm2": round(self.overhang_area_mm2, 2),
            "overhang_percentage": round(self.overhang_percentage, 1),
            "requires_supports": self.requires_supports,
            "recommendations": self.recommendations,
        }


@dataclass
class SlicingConfig:
    """Parameters governing slice plane spacing, extrusion, and G-code generation."""

    layer_height: float = 0.20
    first_layer_height: float = 0.25
    nozzle_diameter: float = 0.40
    filament_diameter: float = 1.75
    filament_type: FilamentType = FilamentType.PLA
    infill_density: float = 0.20  # 20%
    infill_pattern: InfillPattern = InfillPattern.RECTILINEAR
    perimeter_count: int = 2
    print_speed_mm_s: float = 50.0
    travel_speed_mm_s: float = 120.0
    bed_temp: Optional[int] = None
    nozzle_temp: Optional[int] = None

    def __post_init__(self) -> None:
        if self.bed_temp is None:
            self.bed_temp = self.filament_type.default_bed_temp
        if self.nozzle_temp is None:
            self.nozzle_temp = self.filament_type.default_nozzle_temp


@dataclass
class SliceResult:
    """Full outcome of mesh slicing, telemetry, and G-code export."""

    total_layers: int
    layer_height: float
    layers: List[SliceLayer]
    total_print_time_sec: float
    total_filament_mm: float
    total_filament_grams: float
    total_volume_cm3: float
    overhang: OverhangAnalysis
    config: SlicingConfig
    gcode_preview: str = ""

    def to_gcode(self, flavor: str = "marlin") -> str:
        """Synthesize full printable G-code text from sliced layers."""
        return _generate_gcode(self, flavor=flavor)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_layers": self.total_layers,
            "layer_height": self.layer_height,
            "total_print_time_minutes": round(self.total_print_time_sec / 60.0, 1),
            "total_filament_meters": round(self.total_filament_mm / 1000.0, 3),
            "total_filament_grams": round(self.total_filament_grams, 2),
            "total_volume_cm3": round(self.total_volume_cm3, 3),
            "layers_count": len(self.layers),
            "overhang": self.overhang.to_dict(),
            "infill_pattern": self.config.infill_pattern.value,
            "infill_density_pct": round(self.config.infill_density * 100, 1),
            "filament_type": self.config.filament_type.value,
        }


# ---------------------------------------------------------------------------
# Slicing Geometry Algorithms
# ---------------------------------------------------------------------------

def analyze_mesh_overhangs(
    mesh: MeshData,
    threshold_degrees: float = 45.0,
) -> OverhangAnalysis:
    """Evaluate triangle normals against vertical build direction to detect overhangs.

    An overhang occurs when a downward-facing surface exceeds the threshold angle
    from vertical (i.e. angle with -Z axis).
    """
    if not mesh.faces or not mesh.vertices:
        return OverhangAnalysis(
            overhang_threshold_deg=threshold_degrees,
            total_faces=0,
            steep_faces_count=0,
            overhang_area_mm2=0.0,
            overhang_percentage=0.0,
            requires_supports=False,
            recommendations=["Mesh is empty."],
        )

    steep_count = 0
    overhang_area = 0.0
    total_area = 0.0
    rad_thresh = math.radians(threshold_degrees)

    for f in mesh.faces:
        v0, v1, v2 = mesh.vertices[f[0]], mesh.vertices[f[1]], mesh.vertices[f[2]]
        e1 = vec3_sub(v1, v0)
        e2 = vec3_sub(v2, v0)
        cross = (
            e1[1] * e2[2] - e1[2] * e2[1],
            e1[2] * e2[0] - e1[0] * e2[2],
            e1[0] * e2[1] - e1[1] * e2[0],
        )
        c_len = vec3_length(cross)
        if c_len < 1e-9:
            continue

        f_area = 0.5 * c_len
        total_area += f_area
        nz = cross[2] / c_len

        # Downward facing face: nz < 0
        if nz < -1e-4:
            # Angle with downward vertical (-Z): dot product with (0,0,-1) is -nz
            cos_down = max(-1.0, min(1.0, -nz))
            angle_from_down = math.acos(cos_down)
            # If the angle with horizontal is shallow (i.e. angle from downward vertical > threshold)
            if angle_from_down > (math.pi / 2.0 - rad_thresh):
                steep_count += 1
                overhang_area += f_area

    pct = (overhang_area / total_area * 100.0) if total_area > 0 else 0.0
    req_supports = pct > 4.0

    recommendations = []
    if req_supports:
        recommendations.append(
            f"Overhang area is {pct:.1f}% (> 4.0%). Consider adding tree supports or increasing chamfer bevel angle."
        )
    else:
        recommendations.append(
            f"Printable without supports! Overhang area is well within tolerances ({pct:.1f}%)."
        )

    return OverhangAnalysis(
        overhang_threshold_deg=threshold_degrees,
        total_faces=len(mesh.faces),
        steep_faces_count=steep_count,
        overhang_area_mm2=overhang_area,
        overhang_percentage=pct,
        requires_supports=req_supports,
        recommendations=recommendations,
    )


def _intersect_triangle_with_z_plane(
    v0: Vec3,
    v1: Vec3,
    v2: Vec3,
    z_plane: float,
) -> Optional[SliceSegment2D]:
    """Calculate exact line segment formed by intersecting triangle with horizontal plane z = z_plane."""
    verts = [v0, v1, v2]
    zs = [v[2] for v in verts]

    # Quick rejection: all vertices strictly above or strictly below
    if (zs[0] > z_plane and zs[1] > z_plane and zs[2] > z_plane) or (
        zs[0] < z_plane and zs[1] < z_plane and zs[2] < z_plane
    ):
        return None

    edges = [(verts[0], verts[1]), (verts[1], verts[2]), (verts[2], verts[0])]
    intersections: List[Tuple[float, float]] = []

    for a, b in edges:
        az, bz = a[2], b[2]
        if (az <= z_plane <= bz) or (bz <= z_plane <= az):
            dz = bz - az
            if abs(dz) > 1e-8:
                t = (z_plane - az) / dz
                ix = a[0] + t * (b[0] - a[0])
                iy = a[1] + t * (b[1] - a[1])
                # Avoid duplicate point
                if not any(math.hypot(ix - ex, iy - ey) < 1e-4 for ex, ey in intersections):
                    intersections.append((ix, iy))
            elif abs(az - z_plane) < 1e-8:
                # Segment lies on the plane
                if not any(math.hypot(a[0] - ex, a[1] - ey) < 1e-4 for ex, ey in intersections):
                    intersections.append((a[0], a[1]))
                if not any(math.hypot(b[0] - ex, b[1] - ey) < 1e-4 for ex, ey in intersections):
                    intersections.append((b[0], b[1]))

    if len(intersections) == 2:
        return SliceSegment2D(
            x1=intersections[0][0],
            y1=intersections[0][1],
            x2=intersections[1][0],
            y2=intersections[1][1],
        )
    return None


def _chain_segments_into_contours(
    segments: List[SliceSegment2D],
    tolerance: float = 1e-3,
) -> List[List[Tuple[float, float]]]:
    """Chain unordered 2D line segments into closed polygonal contours."""
    if not segments:
        return []

    remaining = list(segments)
    contours: List[List[Tuple[float, float]]] = []

    while remaining:
        first = remaining.pop(0)
        chain = [(first.x1, first.y1), (first.x2, first.y2)]

        progress = True
        while progress and remaining:
            progress = False
            head = chain[0]
            tail = chain[-1]

            # Try to match tail
            matched_idx = -1
            reverse_seg = False

            for i, seg in enumerate(remaining):
                if math.hypot(seg.x1 - tail[0], seg.y1 - tail[1]) < tolerance:
                    matched_idx = i
                    reverse_seg = False
                    break
                elif math.hypot(seg.x2 - tail[0], seg.y2 - tail[1]) < tolerance:
                    matched_idx = i
                    reverse_seg = True
                    break

            if matched_idx >= 0:
                seg = remaining.pop(matched_idx)
                if reverse_seg:
                    chain.append((seg.x1, seg.y1))
                else:
                    chain.append((seg.x2, seg.y2))
                progress = True
                continue

            # Try to match head
            for i, seg in enumerate(remaining):
                if math.hypot(seg.x2 - head[0], seg.y2 - head[1]) < tolerance:
                    matched_idx = i
                    reverse_seg = False
                    break
                elif math.hypot(seg.x1 - head[0], seg.y1 - head[1]) < tolerance:
                    matched_idx = i
                    reverse_seg = True
                    break

            if matched_idx >= 0:
                seg = remaining.pop(matched_idx)
                if reverse_seg:
                    chain.insert(0, (seg.x2, seg.y2))
                else:
                    chain.insert(0, (seg.x1, seg.y1))
                progress = True

        if len(chain) >= 3:
            contours.append(chain)

    return contours


def _generate_infill_segments(
    contours: List[List[Tuple[float, float]]],
    layer_index: int,
    pattern: InfillPattern,
    density: float,
    nozzle_diam: float,
) -> List[SliceSegment2D]:
    """Synthesize infill line segments bounded inside the sliced layer."""
    if density <= 0.0 or not contours:
        return []

    # Get layer 2D bounding box
    min_x = min(pt[0] for c in contours for pt in c)
    max_x = max(pt[0] for c in contours for pt in c)
    min_y = min(pt[1] for c in contours for pt in c)
    max_y = max(pt[1] for c in contours for pt in c)

    line_spacing = max(nozzle_diam * 1.5, nozzle_diam / density)
    infill_segments: List[SliceSegment2D] = []

    # Simple bounding ellipse/circle check (coins are circular)
    cx = (min_x + max_x) * 0.5
    cy = (min_y + max_y) * 0.5
    rx = (max_x - min_x) * 0.5 - (nozzle_diam * 1.2)
    ry = (max_y - min_y) * 0.5 - (nozzle_diam * 1.2)

    if rx <= 0 or ry <= 0:
        return []

    if pattern == InfillPattern.CONCENTRIC:
        # Concentric rings
        ring_spacing = line_spacing
        max_r = min(rx, ry)
        curr_r = max_r
        while curr_r > line_spacing * 0.5:
            num_pts = max(16, int(2 * math.pi * curr_r / (nozzle_diam * 2)))
            for k in range(num_pts):
                th1 = (k / num_pts) * 2.0 * math.pi
                th2 = ((k + 1) / num_pts) * 2.0 * math.pi
                infill_segments.append(
                    SliceSegment2D(
                        x1=cx + curr_r * math.cos(th1),
                        y1=cy + curr_r * math.sin(th1),
                        x2=cx + curr_r * math.cos(th2),
                        y2=cy + curr_r * math.sin(th2),
                    )
                )
            curr_r -= ring_spacing

    elif pattern == InfillPattern.RECTILINEAR:
        # Alternating 45° and 135° hatching
        angle = math.pi / 4.0 if (layer_index % 2 == 0) else (3.0 * math.pi / 4.0)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)

        diag = math.hypot(rx, ry)
        d = -diag
        while d <= diag:
            # Distance from center along normal is d
            # Chord length in circle of radius R at distance d: 2 * sqrt(R^2 - d^2)
            if abs(d) < rx:
                half_chord = math.sqrt(max(0.0, rx * rx - d * d))
                # Midpoint on chord
                mx = cx - d * sin_a
                my = cy + d * cos_a
                x1 = mx - half_chord * cos_a
                y1 = my - half_chord * sin_a
                x2 = mx + half_chord * cos_a
                y2 = my + half_chord * sin_a
                infill_segments.append(SliceSegment2D(x1=x1, y1=y1, x2=x2, y2=y2))
            d += line_spacing

    elif pattern == InfillPattern.GRID:
        # Orthogonal horizontal + vertical lines
        y = cy - ry + line_spacing * 0.5
        while y <= cy + ry:
            dy = abs(y - cy)
            if dy < ry:
                half_w = rx * math.sqrt(max(0.0, 1.0 - (dy / ry) ** 2))
                infill_segments.append(SliceSegment2D(x1=cx - half_w, y1=y, x2=cx + half_w, y2=y))
            y += line_spacing

        x = cx - rx + line_spacing * 0.5
        while x <= cx + rx:
            dx = abs(x - cx)
            if dx < rx:
                half_h = ry * math.sqrt(max(0.0, 1.0 - (dx / rx) ** 2))
                infill_segments.append(SliceSegment2D(x1=x, y1=cy - half_h, x2=x, y2=cy + half_h))
            x += line_spacing

    elif pattern == InfillPattern.TRIANGLES:
        # 3 directions: 0°, 60°, 120°
        angles = [0.0, math.pi / 3.0, 2.0 * math.pi / 3.0]
        effective_spacing = line_spacing * 1.5
        for ang in angles:
            cos_a = math.cos(ang)
            sin_a = math.sin(ang)
            d = -rx
            while d <= rx:
                half_chord = math.sqrt(max(0.0, rx * rx - d * d))
                mx = cx - d * sin_a
                my = cy + d * cos_a
                infill_segments.append(
                    SliceSegment2D(
                        x1=mx - half_chord * cos_a,
                        y1=my - half_chord * sin_a,
                        x2=mx + half_chord * cos_a,
                        y2=my + half_chord * sin_a,
                    )
                )
                d += effective_spacing

    return infill_segments


def slice_mesh(
    mesh: MeshData,
    config: Optional[SlicingConfig] = None,
) -> SliceResult:
    """Slice a 3D triangle mesh into horizontal layers and synthesize extrusion telemetry."""
    if config is None:
        config = SlicingConfig()

    (min_pt, max_pt) = mesh.get_bounding_box()
    min_z, max_z = min_pt[2], max_pt[2]
    total_height = max_z - min_z

    if total_height <= 0.0 or not mesh.faces:
        return SliceResult(
            total_layers=0,
            layer_height=config.layer_height,
            layers=[],
            total_print_time_sec=0.0,
            total_filament_mm=0.0,
            total_filament_grams=0.0,
            total_volume_cm3=0.0,
            overhang=analyze_mesh_overhangs(mesh),
            config=config,
            gcode_preview="; Empty mesh, zero layers.",
        )

    # Calculate layer count
    usable_h = max(0.0, total_height - config.first_layer_height)
    body_layers = int(math.ceil(usable_h / config.layer_height))
    total_layer_count = 1 + max(0, body_layers)

    layers: List[SliceLayer] = []
    total_filament_extruded_mm = 0.0
    total_print_time = 0.0

    fil_area = math.pi * ((config.filament_diameter * 0.5) ** 2)
    bead_area = config.layer_height * config.nozzle_diameter

    # Slicing loop
    current_z = min_z + (config.first_layer_height * 0.5)
    for layer_idx in range(total_layer_count):
        layer_thickness = config.first_layer_height if layer_idx == 0 else config.layer_height

        # 1. Collect all triangle intersections at current_z
        raw_segments: List[SliceSegment2D] = []
        for face in mesh.faces:
            v0 = mesh.vertices[face[0]]
            v1 = mesh.vertices[face[1]]
            v2 = mesh.vertices[face[2]]
            seg = _intersect_triangle_with_z_plane(v0, v1, v2, current_z)
            if seg and seg.length > 1e-4:
                raw_segments.append(seg)

        # 2. Chain into closed contours
        contours = _chain_segments_into_contours(raw_segments)

        # 3. Infill generation
        infill = _generate_infill_segments(
            contours=contours,
            layer_index=layer_idx,
            pattern=config.infill_pattern,
            density=config.infill_density,
            nozzle_diam=config.nozzle_diameter,
        )

        # 4. Compute toolpath length and extrusion for this layer
        perimeter_dist = sum(
            math.hypot(c[k + 1][0] - c[k][0], c[k + 1][1] - c[k][1])
            for c in contours
            for k in range(len(c) - 1)
        )
        infill_dist = sum(s.length for s in infill)
        total_extrusion_dist = perimeter_dist + infill_dist

        # Extrusion length (E) in mm of filament
        layer_vol_mm3 = total_extrusion_dist * bead_area
        layer_fil_mm = layer_vol_mm3 / fil_area
        total_filament_extruded_mm += layer_fil_mm

        # Print time estimation (including travel moves)
        print_t = total_extrusion_dist / config.print_speed_mm_s
        travel_t = (total_extrusion_dist * 0.3) / config.travel_speed_mm_s
        layer_time = print_t + travel_t
        total_print_time += layer_time

        layers.append(
            SliceLayer(
                index=layer_idx,
                z_height=current_z,
                thickness=layer_thickness,
                perimeters=contours,
                infill_segments=infill,
                extrusion_length_mm=layer_fil_mm,
                print_time_sec=layer_time,
            )
        )

        current_z += config.layer_height

    # Volume & Mass
    total_vol_cm3 = (total_filament_extruded_mm * fil_area) / 1000.0
    total_mass_g = total_vol_cm3 * config.filament_type.density_g_cm3

    # Overhang analysis
    overhang = analyze_mesh_overhangs(mesh)

    # Preview G-code
    gcode_preview = _generate_gcode_preview(layers[:3], config)

    return SliceResult(
        total_layers=len(layers),
        layer_height=config.layer_height,
        layers=layers,
        total_print_time_sec=total_print_time,
        total_filament_mm=total_filament_extruded_mm,
        total_filament_grams=total_mass_g,
        total_volume_cm3=total_vol_cm3,
        overhang=overhang,
        config=config,
        gcode_preview=gcode_preview,
    )


# ---------------------------------------------------------------------------
# G-code Output Generation
# ---------------------------------------------------------------------------

def _generate_gcode(result: SliceResult, flavor: str = "marlin") -> str:
    """Generate complete production G-code program."""
    cfg = result.config
    feed_print = cfg.print_speed_mm_s * 60.0
    feed_travel = cfg.travel_speed_mm_s * 60.0

    lines: List[str] = [
        "; ===========================================================================",
        "; Generated by Badge3D Coin Slicer & G-code Synthesizer",
        f"; Total Layers: {result.total_layers}",
        f"; Layer Height: {cfg.layer_height} mm (First Layer: {cfg.first_layer_height} mm)",
        f"; Infill: {cfg.infill_density * 100:.1f}% {cfg.infill_pattern.value.title()}",
        f"; Material: {cfg.filament_type.value.upper()} (Est: {result.total_filament_grams:.2f}g, {result.total_filament_mm / 1000.0:.2f}m)",
        f"; Est. Print Time: {result.total_print_time_sec / 60.0:.1f} minutes",
        "; ===========================================================================",
        "",
        "; --- START G-CODE ---",
        "G21 ; metric values",
        "G90 ; absolute positioning",
        "M82 ; set extruder to absolute mode",
        f"M140 S{cfg.bed_temp} ; set bed temp",
        f"M104 S{cfg.nozzle_temp} ; set extruder temp",
        f"M190 S{cfg.bed_temp} ; wait for bed temp",
        f"M109 S{cfg.nozzle_temp} ; wait for extruder temp",
        "G28 ; home all axes",
        "G92 E0 ; reset extruder",
        "G1 Z2.0 F3000 ; move Z up",
        "G1 X10.0 Y20.0 Z0.28 F5000.0 ; move to start",
        "G1 X10.0 Y180.0 Z0.28 F1500.0 E15 ; prime purge line",
        "G1 X10.4 Y180.0 Z0.28 F5000.0 ; step aside",
        "G1 X10.4 Y20.0 Z0.28 F1500.0 E30 ; prime second line",
        "G92 E0 ; reset extruder",
        "G1 Z2.0 F3000 ; lift nozzle",
        "",
    ]

    fil_area = math.pi * ((cfg.filament_diameter * 0.5) ** 2)
    bead_area = cfg.layer_height * cfg.nozzle_diameter
    e_ratio = bead_area / fil_area
    cumulative_e = 0.0

    for layer in result.layers:
        lines.append(f"; --- LAYER {layer.index} (Z={layer.z_height:.3f}mm) ---")
        lines.append(f"G1 Z{layer.z_height:.3f} F{feed_travel:.0f}")

        # Perimeters
        for c_idx, contour in enumerate(layer.perimeters):
            if not contour:
                continue
            lines.append(f"; Perimeter {c_idx + 1}")
            # Travel to start
            lines.append(f"G1 X{contour[0][0]:.3f} Y{contour[0][1]:.3f} F{feed_travel:.0f}")
            # Extrude along contour
            for pt in contour[1:]:
                d = math.hypot(pt[0] - contour[0][0], pt[1] - contour[0][1])
                cumulative_e += d * e_ratio
                lines.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} E{cumulative_e:.4f} F{feed_print:.0f}")

        # Infill segments
        if layer.infill_segments:
            lines.append("; Infill")
            for seg in layer.infill_segments:
                lines.append(f"G1 X{seg.x1:.3f} Y{seg.y1:.3f} F{feed_travel:.0f}")
                cumulative_e += seg.length * e_ratio
                lines.append(f"G1 X{seg.x2:.3f} Y{seg.y2:.3f} E{cumulative_e:.4f} F{feed_print:.0f}")

        lines.append("")

    # End G-code
    lines.extend([
        "; --- END G-CODE ---",
        "M104 S0 ; turn off hotend",
        "M140 S0 ; turn off bed",
        "G91 ; relative positioning",
        "G1 E-2 F2700 ; retract filament",
        "G1 Z10 F3000 ; raise nozzle 10mm",
        "G90 ; absolute positioning",
        "G1 X0 Y200 F3000 ; present print",
        "M84 ; disable stepper motors",
        "; End of print",
    ])

    return "\n".join(lines)


def _generate_gcode_preview(layers: List[SliceLayer], cfg: SlicingConfig) -> str:
    """Generate concise top 20 lines of G-code for UI preview."""
    lines = [
        f"; G-code Preview ({cfg.filament_type.value.upper()} | {cfg.infill_density * 100:.0f}% {cfg.infill_pattern.value})",
        "G28 ; home all axes",
        f"M104 S{cfg.nozzle_temp}",
        f"M140 S{cfg.bed_temp}",
    ]
    for layer in layers:
        lines.append(f"; LAYER {layer.index} (Z={layer.z_height:.2f}mm) - {len(layer.perimeters)} perimeters, {len(layer.infill_segments)} infill")
    return "\n".join(lines)
