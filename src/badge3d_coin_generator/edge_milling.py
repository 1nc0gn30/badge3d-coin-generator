"""Pure-Python Edge Milling, Cylindrical Rim Inscription & Cryptographic Security Stamp Engine.

Provides high-precision parametric 3D coin edge detailing:
- Incuse and raised cylindrical edge lettering ("E PLURIBUS UNUM", serial numbers, mottoes)
  using built-in vector stroke typography mapped onto the cylindrical coordinate frame.
- Cryptographic hash-derived anti-counterfeiting micro-grooves and barcode teeth.
- Multi-track segmented reeding with alternating smooth sectors, security notches, and decorative stars.
- 100% Python Standard Library (math, hashlib, dataclasses, typing).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

# Vector Stroke Font for Rim Inscriptions (5x7 grid: width=5, height=7)
# Stored as list of line segments: ((x1, y1), (x2, y2)) in [0..5, 0..7]
STROKE_FONT: Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]] = {
    "A": [((0, 0), (2.5, 7)), ((2.5, 7), (5, 0)), ((1.0, 3.0), (4.0, 3.0))],
    "B": [((0, 0), (0, 7)), ((0, 7), (3.5, 7)), ((3.5, 7), (4.5, 5.5)), ((4.5, 5.5), (3.5, 3.5)),
          ((0, 3.5), (3.5, 3.5)), ((3.5, 3.5), (4.5, 1.5)), ((4.5, 1.5), (3.5, 0)), ((3.5, 0), (0, 0))],
    "C": [((5, 6), (2, 7)), ((2, 7), (0, 4)), ((0, 4), (0, 3)), ((0, 3), (2, 0)), ((2, 0), (5, 1))],
    "D": [((0, 0), (0, 7)), ((0, 7), (3, 7)), ((3, 7), (5, 4.5)), ((5, 4.5), (5, 2.5)), ((5, 2.5), (3, 0)), ((3, 0), (0, 0))],
    "E": [((0, 0), (0, 7)), ((0, 7), (5, 7)), ((0, 3.5), (3.5, 3.5)), ((0, 0), (5, 0))],
    "F": [((0, 0), (0, 7)), ((0, 7), (5, 7)), ((0, 3.5), (3.5, 3.5))],
    "G": [((5, 6), (2, 7)), ((2, 7), (0, 4)), ((0, 4), (0, 3)), ((0, 3), (2, 0)), ((2, 0), (5, 0)), ((5, 0), (5, 3.5)), ((5, 3.5), (3, 3.5))],
    "H": [((0, 0), (0, 7)), ((5, 0), (5, 7)), ((0, 3.5), (5, 3.5))],
    "I": [((1, 7), (4, 7)), ((2.5, 7), (2.5, 0)), ((1, 0), (4, 0))],
    "J": [((0, 2), (2, 0)), ((2, 0), (3.5, 0)), ((3.5, 0), (4, 1.5)), ((4, 1.5), (4, 7)), ((2, 7), (5, 7))],
    "K": [((0, 0), (0, 7)), ((4.5, 7), (0, 3)), ((0, 3), (5, 0))],
    "L": [((0, 7), (0, 0)), ((0, 0), (5, 0))],
    "M": [((0, 0), (0, 7)), ((0, 7), (2.5, 3.5)), ((2.5, 3.5), (5, 7)), ((5, 7), (5, 0))],
    "N": [((0, 0), (0, 7)), ((0, 7), (5, 0)), ((5, 0), (5, 7))],
    "O": [((1.5, 0), (3.5, 0)), ((3.5, 0), (5, 2)), ((5, 2), (5, 5)), ((5, 5), (3.5, 7)),
          ((3.5, 7), (1.5, 7)), ((1.5, 7), (0, 5)), ((0, 5), (0, 2)), ((0, 2), (1.5, 0))],
    "P": [((0, 0), (0, 7)), ((0, 7), (3.5, 7)), ((3.5, 7), (5, 5.5)), ((5, 5.5), (3.5, 4)), ((3.5, 4), (0, 4))],
    "Q": [((1.5, 0), (3.5, 0)), ((3.5, 0), (5, 2)), ((5, 2), (5, 5)), ((5, 5), (3.5, 7)),
          ((3.5, 7), (1.5, 7)), ((1.5, 7), (0, 5)), ((0, 5), (0, 2)), ((0, 2), (1.5, 0)), ((3, 2), (5, 0))],
    "R": [((0, 0), (0, 7)), ((0, 7), (3.5, 7)), ((3.5, 7), (5, 5.5)), ((5, 5.5), (3.5, 4)), ((3.5, 4), (0, 4)), ((2.5, 4), (5, 0))],
    "S": [((0, 1.5), (2, 0)), ((2, 0), (3.5, 0)), ((3.5, 0), (5, 1.5)), ((5, 1.5), (0, 5.5)),
          ((0, 5.5), (1.5, 7)), ((1.5, 7), (3.5, 7)), ((3.5, 7), (5, 5.5))],
    "T": [((0, 7), (5, 7)), ((2.5, 7), (2.5, 0))],
    "U": [((0, 7), (0, 2)), ((0, 2), (2, 0)), ((2, 0), (3, 0)), ((3, 0), (5, 2)), ((5, 2), (5, 7))],
    "V": [((0, 7), (2.5, 0)), ((2.5, 0), (5, 7))],
    "W": [((0, 7), (1.2, 0)), ((1.2, 0), (2.5, 4)), ((2.5, 4), (3.8, 0)), ((3.8, 0), (5, 7))],
    "X": [((0, 0), (5, 7)), ((0, 7), (5, 0))],
    "Y": [((0, 7), (2.5, 3.5)), ((5, 7), (2.5, 3.5)), ((2.5, 3.5), (2.5, 0))],
    "Z": [((0, 7), (5, 7)), ((5, 7), (0, 0)), ((0, 0), (5, 0))],
    "0": [((1, 0), (4, 0)), ((4, 0), (5, 2)), ((5, 2), (5, 5)), ((5, 5), (4, 7)),
          ((4, 7), (1, 7)), ((1, 7), (0, 5)), ((0, 5), (0, 2)), ((0, 2), (1, 0)), ((4, 6), (1, 1))],
    "1": [((1, 5), (2.5, 7)), ((2.5, 7), (2.5, 0)), ((1, 0), (4, 0))],
    "2": [((0, 5.5), (1.5, 7)), ((1.5, 7), (4, 7)), ((4, 7), (5, 5)), ((5, 5), (0, 0)), ((0, 0), (5, 0))],
    "3": [((0, 6), (4, 7)), ((4, 7), (2, 4)), ((2, 4), (4.5, 3)), ((4.5, 3), (4.5, 1)), ((4.5, 1), (2, 0)), ((2, 0), (0, 1))],
    "4": [((4, 0), (4, 7)), ((4, 7), (0, 2.5)), ((0, 2.5), (5, 2.5))],
    "5": [((4.5, 7), (0.5, 7)), ((0.5, 7), (0.5, 3.5)), ((0.5, 3.5), (3.5, 3.5)), ((3.5, 3.5), (5, 2)), ((5, 2), (5, 1)), ((5, 1), (3, 0)), ((3, 0), (0.5, 1))],
    "6": [((4, 6), (2, 7)), ((2, 7), (0, 4)), ((0, 4), (0, 2)), ((0, 2), (2, 0)), ((2, 0), (4, 0)), ((4, 0), (5, 2)), ((5, 2), (3.5, 3.5)), ((3.5, 3.5), (0, 3.5))],
    "7": [((0, 7), (5, 7)), ((5, 7), (2, 0))],
    "8": [((1.5, 3.5), (3.5, 3.5)), ((3.5, 3.5), (5, 5)), ((5, 5), (3.5, 7)), ((3.5, 7), (1.5, 7)),
          ((1.5, 7), (0, 5)), ((0, 5), (1.5, 3.5)), ((1.5, 3.5), (0, 2)), ((0, 2), (1.5, 0)),
          ((1.5, 0), (3.5, 0)), ((3.5, 0), (5, 2)), ((5, 2), (3.5, 3.5))],
    "9": [((5, 3.5), (1.5, 3.5)), ((1.5, 3.5), (0, 5)), ((0, 5), (1, 7)), ((1, 7), (3, 7)),
          ((3, 7), (5, 5)), ((5, 5), (5, 2)), ((5, 2), (3, 0)), ((3, 0), (1, 1))],
    ".": [((2, 0), (3, 0)), ((3, 0), (3, 1)), ((3, 1), (2, 1)), ((2, 1), (2, 0))],
    "-": [((1, 3.5), (4, 3.5))],
    "*": [((2.5, 1.5), (2.5, 5.5)), ((1.0, 2.5), (4.0, 4.5)), ((1.0, 4.5), (4.0, 2.5))],
    " ": [],
}


@dataclass
class EdgeInscriptionSpec:
    """Configuration for text lettering running along the cylindrical coin rim."""
    text: str = ""
    depth: float = 0.25              # Radial depth in mm (positive value)
    mode: str = "incuse"             # 'incuse' (engraved into rim) or 'raised' (embossed outward)
    letter_height_ratio: float = 0.60 # Height of letters relative to coin thickness [0.2..0.85]
    repeats: int = 1                 # Number of times text repeats around circumference
    separator: str = " ★ "           # Decorative glyph between repetitions
    start_angle_deg: float = 0.0     # Angular offset around rim in degrees


@dataclass
class SecurityStampSpec:
    """Cryptographic hash-based anti-counterfeiting rim stamp specification."""
    seed: str = "CHALLENGE-COIN-2026"
    num_grooves: int = 64            # Total security grooves around perimeter
    base_depth: float = 0.3          # Base groove depth in mm
    depth_variation: float = 0.15    # Amplitude of hash-derived depth modulation
    parity_check: bool = True        # Append verification parity tooth at angle 0


@dataclass
class SegmentedReedingSpec:
    """Segmented reeding configuration (e.g. 10 reeded sectors, 10 smooth sectors)."""
    reeded_sectors: int = 8          # Number of reeded groups around circumference
    reeds_per_sector: int = 7        # Ridges inside each reeded sector
    reed_depth: float = 0.25         # Depth of reeding grooves in mm
    profile: str = "trapezoidal"     # 'sinusoidal', 'trapezoidal', 'square', 'fluted'
    marker_groove: bool = True       # Single deeper notch marking orientation


@dataclass
class CompoundMillingSpec:
    """Combined edge detailing specification supporting inscription and security grooves."""
    reeding_profile: str = "sinusoidal"
    reed_count: int = 120
    reed_depth: float = 0.2
    inscription: Optional[EdgeInscriptionSpec] = None
    security_stamp: Optional[SecurityStampSpec] = None
    segmented: Optional[SegmentedReedingSpec] = None


def _point_to_line_distance(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """Compute Euclidean distance from (px, py) to line segment (x1, y1)-(x2, y2)."""
    dx = x2 - x1
    dy = y2 - y1
    line_len_sq = dx * dx + dy * dy
    if line_len_sq < 1e-12:
        return math.hypot(px - x1, py - y1)
    # Projection factor t clamped to [0, 1]
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / line_len_sq))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def evaluate_text_rim_distance(
    text: str,
    theta_norm: float,
    z_norm: float,
    stroke_thickness: float = 0.45,
) -> float:
    """Evaluate distance to the nearest stroke segment of text along the normalized cylindrical surface.
    
    Args:
        text: Uppercase inscribed text string.
        theta_norm: Longitudinal parameter along perimeter in [0.0, 1.0].
        z_norm: Vertical parameter along cylinder height in [0.0, 1.0].
        stroke_thickness: Nominal width of letter strokes in grid units.
    
    Returns:
        Intensity factor in [0.0, 1.0] where 1.0 is directly on a stroke.
    """
    if not text:
        return 0.0

    n_chars = len(text)
    char_width_norm = 1.0 / max(1, n_chars)
    char_idx = int(theta_norm / char_width_norm) % n_chars
    c = text[char_idx].upper()

    segments = STROKE_FONT.get(c)
    if not segments:
        return 0.0

    # Local coordinates inside the character cell: [0..1] x [0..1]
    local_u = (theta_norm - char_idx * char_width_norm) / char_width_norm
    local_v = z_norm

    # Convert local [0..1] to font grid [0..5, 0..7] with margin
    margin = 0.15
    if local_u < margin or local_u > (1.0 - margin) or local_v < margin or local_v > (1.0 - margin):
        return 0.0

    gx = (local_u - margin) / (1.0 - 2.0 * margin) * 5.0
    gy = (local_v - margin) / (1.0 - 2.0 * margin) * 7.0

    min_dist = 999.0
    for (x1, y1), (x2, y2) in segments:
        d = _point_to_line_distance(gx, gy, x1, y1, x2, y2)
        if d < min_dist:
            min_dist = d

    if min_dist < stroke_thickness:
        # Smooth anti-aliased edge factor
        return math.cos(0.5 * math.pi * (min_dist / stroke_thickness)) ** 2
    return 0.0


def derive_crypto_teeth_pattern(seed: str, count: int = 64) -> List[float]:
    """Derive deterministic groove depth factors from a cryptographic hash.
    
    Args:
        seed: Arbitrary string (e.g. coin serial number, key, timestamp).
        count: Number of teeth around perimeter.
        
    Returns:
        List of depth multipliers in [0.0, 1.0] corresponding to perimeter angles.
    """
    # Hash seed using SHA-256
    hasher = hashlib.sha256(seed.encode("utf-8"))
    raw_digest = hasher.digest()

    pattern = []
    for i in range(count):
        # Sample byte cycle
        byte_val = raw_digest[i % len(raw_digest)]
        # Mix with index bit rotation
        factor = ((byte_val ^ (i * 37)) & 0xFF) / 255.0
        pattern.append(factor)
    return pattern


def compute_edge_milling_radius(
    base_radius: float,
    angle_rad: float,
    z_height: float,
    thickness: float,
    spec: CompoundMillingSpec,
) -> float:
    """Compute parametric radius of the coin rim taking all milling details into account.
    
    Args:
        base_radius: Base outer coin cylinder radius in mm.
        angle_rad: Circumference angle in radians [0..2*pi].
        z_height: Height coordinate along coin cylinder in [-thickness/2, +thickness/2].
        thickness: Total coin thickness in mm.
        spec: Compound edge detailing specification.
        
    Returns:
        Evaluated modified radius in mm.
    """
    rad = base_radius
    theta_pos = (angle_rad % (2.0 * math.pi))
    theta_norm = theta_pos / (2.0 * math.pi)

    # 1. Segmented Reeding
    if spec.segmented and spec.segmented.reeded_sectors > 0:
        seg = spec.segmented
        total_sectors = seg.reeded_sectors * 2
        sector_idx = int(theta_norm * total_sectors)
        is_reeded = (sector_idx % 2 == 0)
        
        if is_reeded and seg.reeds_per_sector > 0:
            sector_u = (theta_norm * total_sectors) % 1.0
            cycle = (sector_u * seg.reeds_per_sector) % 1.0
            val = 0.5 * (1.0 + math.cos(2.0 * math.pi * cycle))
            rad -= (1.0 - val) * seg.reed_depth
            
        if seg.marker_groove and theta_norm < (1.0 / 180.0):
            # Alignment index notch at 0 degrees
            rad -= seg.reed_depth * 1.5

    # 2. Base Reeding (if no segmented reeding)
    elif spec.reed_count > 0 and spec.reed_depth > 1e-6:
        cycle = (theta_norm * spec.reed_count) % 1.0
        val = 0.5 * (1.0 + math.cos(2.0 * math.pi * cycle))
        rad -= (1.0 - val) * spec.reed_depth

    # 3. Cryptographic Security Stamp
    if spec.security_stamp:
        sec = spec.security_stamp
        teeth = derive_crypto_teeth_pattern(sec.seed, sec.num_grooves)
        tooth_idx = int(theta_norm * sec.num_grooves) % len(teeth)
        groove_factor = teeth[tooth_idx]
        
        # Micro notch in the center 50% of the coin edge height
        z_band = abs(z_height) / (0.5 * thickness)
        if z_band < 0.65:
            d = sec.base_depth + (groove_factor - 0.5) * sec.depth_variation
            rad -= max(0.0, d)

    # 4. Inscribed Edge Text
    if spec.inscription and spec.inscription.text:
        insc = spec.inscription
        full_text = insc.text
        if insc.repeats > 1:
            full_text = insc.separator.join([insc.text] * insc.repeats) + insc.separator

        # Angular shift
        ang_shift_norm = (insc.start_angle_deg / 360.0) % 1.0
        t_shifted = (theta_norm - ang_shift_norm) % 1.0

        # Normalized vertical coordinate: [0.0..1.0] from -h to +h
        char_half_h = 0.5 * thickness * insc.letter_height_ratio
        if -char_half_h <= z_height <= char_half_h:
            z_norm = (z_height + char_half_h) / (2.0 * char_half_h)
            intensity = evaluate_text_rim_distance(full_text, t_shifted, z_norm)
            if intensity > 1e-4:
                if insc.mode == "incuse":
                    rad -= intensity * insc.depth
                else:
                    rad += intensity * insc.depth

    return rad


def generate_edge_milling_profile_summary(spec: CompoundMillingSpec) -> Dict[str, Any]:
    """Generate technical metadata and inspection summary for an edge milling design."""
    summary: Dict[str, Any] = {
        "reeding_profile": spec.reeding_profile,
        "reed_count": spec.reed_count,
        "reed_depth_mm": spec.reed_depth,
        "has_inscription": spec.inscription is not None and bool(spec.inscription.text),
        "has_security_stamp": spec.security_stamp is not None,
        "has_segmented_reeding": spec.segmented is not None,
    }
    if spec.inscription:
        summary["inscription"] = {
            "text": spec.inscription.text,
            "mode": spec.inscription.mode,
            "depth_mm": spec.inscription.depth,
            "repeats": spec.inscription.repeats,
        }
    if spec.security_stamp:
        sec = spec.security_stamp
        teeth = derive_crypto_teeth_pattern(sec.seed, sec.num_grooves)
        summary["security_stamp"] = {
            "seed": sec.seed,
            "num_grooves": sec.num_grooves,
            "base_depth_mm": sec.base_depth,
            "sample_checksum": hashlib.sha256("".join(f"{x:.2f}" for x in teeth[:8]).encode()).hexdigest()[:12],
        }
    if spec.segmented:
        summary["segmented_reeding"] = {
            "sectors": spec.segmented.reeded_sectors,
            "reeds_per_sector": spec.segmented.reeds_per_sector,
            "depth_mm": spec.segmented.reed_depth,
        }
    return summary
