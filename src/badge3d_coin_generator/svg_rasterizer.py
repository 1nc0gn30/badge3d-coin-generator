"""Pure Python SVG Rasterizer & Procedural Coin Relief Synthesizer.

Provides 2D heightmap generation, image processing, distance transforms,
and SVG path parsing without any third-party dependencies (100% Python Standard Library).

Features:
1. `Heightmap`: 2D elevation grid with bilinear sampling, blurring, beveling, blending.
2. `ProceduralReliefBuilder`: Generates coin borders (pearl beads, ropes), heraldic shields,
   stars, laurel wreaths, rosettes, gears, and straight/circular arc lettering.
3. `SVGRasterizer`: Parses SVG files (rect, circle, ellipse, line, polyline, polygon, path)
   with full support for cubic/quadratic beziers, elliptical arcs, and fill/stroke rasterization.
"""

from __future__ import annotations

import math
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from .compat import PathLike, atomic_write_bytes, atomic_write_text, read_text_safe, safe_path

# Type aliases
Point2D = Tuple[float, float]


# ---------------------------------------------------------------------------
# 1. Heightmap Core Class & Image Processing
# ---------------------------------------------------------------------------

class Heightmap:
    """2D elevation grid representing surface relief with values normalized to [0.0, 1.0]."""

    def __init__(self, width: int = 256, height: int = 256, initial_value: float = 0.0) -> None:
        self.width = max(2, int(width))
        self.height = max(2, int(height))
        val = max(0.0, min(1.0, float(initial_value)))
        self.data: List[float] = [val] * (self.width * self.height)

    def get(self, x: int, y: int) -> float:
        """Get pixel elevation at integer coordinates (clamped)."""
        cx = max(0, min(self.width - 1, x))
        cy = max(0, min(self.height - 1, y))
        return self.data[cy * self.width + cx]

    def set(self, x: int, y: int, value: float) -> None:
        """Set pixel elevation at integer coordinates (clamped)."""
        if 0 <= x < self.width and 0 <= y < self.height:
            self.data[y * self.width + x] = max(0.0, min(1.0, float(value)))

    def sample_bilinear(self, u: float, v: float) -> float:
        """Sample heightmap elevation at normalized UV coordinates in [0.0, 1.0]."""
        u = max(0.0, min(1.0, u))
        v = max(0.0, min(1.0, v))

        px = u * (self.width - 1)
        py = v * (self.height - 1)

        x0 = int(px)
        y0 = int(py)
        x1 = min(x0 + 1, self.width - 1)
        y1 = min(y0 + 1, self.height - 1)

        fx = px - x0
        fy = py - y0

        v00 = self.data[y0 * self.width + x0]
        v10 = self.data[y0 * self.width + x1]
        v01 = self.data[y1 * self.width + x0]
        v11 = self.data[y1 * self.width + x1]

        top = (1.0 - fx) * v00 + fx * v10
        bot = (1.0 - fx) * v01 + fx * v11

        return (1.0 - fy) * top + fy * bot

    def to_2d_list(self) -> List[List[float]]:
        """Convert flat data into a 2D list of floats [height][width]."""
        grid: List[List[float]] = []
        w = self.width
        for y in range(self.height):
            row = self.data[y * w : (y + 1) * w]
            grid.append(list(row))
        return grid

    @classmethod
    def from_2d_list(cls, grid: Sequence[Sequence[float]]) -> Heightmap:
        """Create a Heightmap instance from a 2D sequence of elevation values."""
        if not grid or not grid[0]:
            raise ValueError("Grid sequence must not be empty.")
        h = len(grid)
        w = len(grid[0])
        hm = cls(w, h)
        for y in range(h):
            for x in range(w):
                hm.set(x, y, grid[y][x])
        return hm

    def clone(self) -> Heightmap:
        """Create a deep copy of this heightmap."""
        hm = Heightmap(self.width, self.height)
        hm.data = list(self.data)
        return hm

    def invert(self) -> Heightmap:
        """Invert all elevations (1.0 - val)."""
        hm = Heightmap(self.width, self.height)
        hm.data = [1.0 - v for v in self.data]
        return hm

    def normalize(self) -> Heightmap:
        """Stretch elevation values to span full [0.0, 1.0] range."""
        if not self.data:
            return self.clone()
        min_v = min(self.data)
        max_v = max(self.data)
        rng = max_v - min_v
        if rng < 1e-9:
            return self.clone()
        hm = Heightmap(self.width, self.height)
        hm.data = [(v - min_v) / rng for v in self.data]
        return hm

    def adjust_contrast(self, gamma: float = 1.0) -> Heightmap:
        """Apply gamma/power curve to elevations."""
        g = max(0.01, float(gamma))
        hm = Heightmap(self.width, self.height)
        hm.data = [math.pow(v, g) for v in self.data]
        return hm

    def threshold(self, cutoff: float = 0.5, low: float = 0.0, high: float = 1.0) -> Heightmap:
        """Binary threshold the heightmap."""
        hm = Heightmap(self.width, self.height)
        hm.data = [high if v >= cutoff else low for v in self.data]
        return hm

    def blur(self, radius: float = 1.5) -> Heightmap:
        """Apply separable Gaussian blur to smooth out relief steps and jagged edges."""
        r = max(0.5, float(radius))
        kernel_size = int(math.ceil(r * 3.0)) * 2 + 1
        half_k = kernel_size // 2

        # 1D Gaussian kernel
        kernel: List[float] = []
        two_sigma_sq = 2.0 * r * r
        for i in range(-half_k, half_k + 1):
            w = math.exp(-(i * i) / two_sigma_sq)
            kernel.append(w)
        k_sum = sum(kernel)
        kernel = [k / k_sum for k in kernel]

        w, h = self.width, self.height

        # Horizontal pass
        temp = [0.0] * (w * h)
        for y in range(h):
            row_offset = y * w
            for x in range(w):
                acc = 0.0
                for ki, k_val in enumerate(kernel):
                    ix = min(max(x + ki - half_k, 0), w - 1)
                    acc += self.data[row_offset + ix] * k_val
                temp[row_offset + x] = acc

        # Vertical pass
        out = Heightmap(w, h)
        for x in range(w):
            for y in range(h):
                acc = 0.0
                for ki, k_val in enumerate(kernel):
                    iy = min(max(y + ki - half_k, 0), h - 1)
                    acc += temp[iy * w + x] * k_val
                out.data[y * w + x] = max(0.0, min(1.0, acc))

        return out

    def bevel_edges(self, max_slope_px: float = 10.0, profile: str = "chisel") -> Heightmap:
        """Compute Euclidean/Chamfer distance transform for 3D raised chiseled relief.

        Converts binary/solid shapes into sloped 3D profiles.
        Profiles: 'chisel' (linear ramp), 'dome' (spherical/circular), 'cone' (pyramidal),
        'ridge' (sharp peaked center).
        """
        w, h = self.width, self.height
        inf = float("inf")
        dist = [inf] * (w * h)

        # Initialize: boundary of non-zero pixels is distance 0
        for y in range(h):
            for x in range(w):
                if self.data[y * w + x] <= 0.05:
                    dist[y * w + x] = 0.0

        # Chamfer distance 3-4 pass 1 (top-left to bottom-right)
        d_ortho = 1.0
        d_diag = 1.41421356

        for y in range(h):
            for x in range(w):
                idx = y * w + x
                cur = dist[idx]
                if x > 0:
                    cur = min(cur, dist[idx - 1] + d_ortho)
                if y > 0:
                    cur = min(cur, dist[idx - w] + d_ortho)
                    if x > 0:
                        cur = min(cur, dist[idx - w - 1] + d_diag)
                    if x < w - 1:
                        cur = min(cur, dist[idx - w + 1] + d_diag)
                dist[idx] = cur

        # Chamfer pass 2 (bottom-right to top-left)
        for y in range(h - 1, -1, -1):
            for x in range(w - 1, -1, -1):
                idx = y * w + x
                cur = dist[idx]
                if x < w - 1:
                    cur = min(cur, dist[idx + 1] + d_ortho)
                if y < h - 1:
                    cur = min(cur, dist[idx + w] + d_ortho)
                    if x < w - 1:
                        cur = min(cur, dist[idx + w + 1] + d_diag)
                    if x > 0:
                        cur = min(cur, dist[idx + w - 1] + d_diag)
                dist[idx] = cur

        # Map distance to elevation profile
        slope_limit = max(1.0, float(max_slope_px))
        out = Heightmap(w, h)

        for i in range(w * h):
            if self.data[i] <= 0.05:
                out.data[i] = 0.0
                continue

            d_val = dist[i]
            t = min(1.0, d_val / slope_limit)

            if profile == "dome":
                # Spherical arc
                elev = math.sqrt(max(0.0, 1.0 - (1.0 - t) * (1.0 - t)))
            elif profile == "cone":
                # Linear pyramid
                elev = t
            elif profile == "ridge":
                # Sinusoidal ridge
                elev = math.sin(t * math.pi * 0.5)
            else:  # chisel (linear)
                elev = t

            # Multiply by original pixel intensity for anti-aliasing preservation
            out.data[i] = max(0.0, min(1.0, elev * self.data[i]))

        return out

    def blend(
        self,
        other: Heightmap,
        mode: str = "max",
        opacity: float = 1.0,
    ) -> Heightmap:
        """Blend another heightmap into this one.

        Blend modes: 'max', 'add', 'multiply', 'screen', 'overlay', 'sub'.
        """
        if self.width != other.width or self.height != other.height:
            raise ValueError(
                f"Heightmap dimensions must match for blend: "
                f"({self.width}x{self.height}) vs ({other.width}x{other.height})"
            )

        op = max(0.0, min(1.0, float(opacity)))
        out = Heightmap(self.width, self.height)

        for i in range(self.width * self.height):
            a = self.data[i]
            b = other.data[i]

            if mode == "add":
                res = a + b * op
            elif mode == "multiply":
                res = a * (1.0 - op + b * op)
            elif mode == "screen":
                res = 1.0 - (1.0 - a) * (1.0 - b * op)
            elif mode == "overlay":
                if a < 0.5:
                    target = 2.0 * a * b
                else:
                    target = 1.0 - 2.0 * (1.0 - a) * (1.0 - b)
                res = (1.0 - op) * a + op * target
            elif mode == "sub":
                res = a - b * op
            else:  # 'max'
                res = max(a, b * op)

            out.data[i] = max(0.0, min(1.0, res))

        return out

    def export_pgm_binary(self) -> bytes:
        """Export heightmap as Netpbm binary P5 PGM format bytes (0..255)."""
        header = f"P5\n{self.width} {self.height}\n255\n".encode("ascii")
        pixels = bytearray(int(max(0.0, min(1.0, v)) * 255.0) for v in self.data)
        return header + pixels

    def export_pgm_ascii(self) -> str:
        """Export heightmap as Netpbm ASCII P2 PGM format text."""
        lines = [f"P2", f"{self.width} {self.height}", f"255"]
        w = self.width
        for y in range(self.height):
            row_vals = [str(int(max(0.0, min(1.0, self.data[y * w + x])) * 255.0)) for x in range(w)]
            lines.append(" ".join(row_vals))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. Vector Stroke Typography Engine (Pure Python)
# ---------------------------------------------------------------------------

# Built-in vector stroke definitions for ASCII characters [0..1] normalized box
FONT_STROKES: Dict[str, List[List[Point2D]]] = {
    "A": [[(0, 1), (0.5, 0), (1, 1)], [(0.2, 0.6), (0.8, 0.6)]],
    "B": [[(0, 1), (0, 0), (0.7, 0), (0.9, 0.25), (0.7, 0.5), (0, 0.5)], [(0.7, 0.5), (0.9, 0.75), (0.7, 1), (0, 1)]],
    "C": [[(1, 0.15), (0.7, 0), (0.3, 0), (0, 0.3), (0, 0.7), (0.3, 1), (0.7, 1), (1, 0.85)]],
    "D": [[(0, 1), (0, 0), (0.6, 0), (1, 0.35), (1, 0.65), (0.6, 1), (0, 1)]],
    "E": [[(1, 0), (0, 0), (0, 1), (1, 1)], [(0, 0.5), (0.7, 0.5)]],
    "F": [[(0, 1), (0, 0), (1, 0)], [(0, 0.5), (0.7, 0.5)]],
    "G": [[(1, 0.15), (0.7, 0), (0.3, 0), (0, 0.3), (0, 0.7), (0.3, 1), (0.7, 1), (1, 0.8), (1, 0.5), (0.5, 0.5)]],
    "H": [[(0, 0), (0, 1)], [(1, 0), (1, 1)], [(0, 0.5), (1, 0.5)]],
    "I": [[(0.2, 0), (0.8, 0)], [(0.5, 0), (0.5, 1)], [(0.2, 1), (0.8, 1)]],
    "J": [[(0.8, 0), (0.8, 0.75), (0.5, 1), (0.2, 0.75)]],
    "K": [[(0, 0), (0, 1)], [(1, 0), (0, 0.5), (1, 1)]],
    "L": [[(0, 0), (0, 1), (1, 1)]],
    "M": [[(0, 1), (0, 0), (0.5, 0.6), (1, 0), (1, 1)]],
    "N": [[(0, 1), (0, 0), (1, 1), (1, 0)]],
    "O": [[(0.3, 0), (0.7, 0), (1, 0.3), (1, 0.7), (0.7, 1), (0.3, 1), (0, 0.7), (0, 0.3), (0.3, 0)]],
    "P": [[(0, 1), (0, 0), (0.8, 0), (1, 0.25), (0.8, 0.5), (0, 0.5)]],
    "Q": [[(0.3, 0), (0.7, 0), (1, 0.3), (1, 0.7), (0.7, 1), (0.3, 1), (0, 0.7), (0, 0.3), (0.3, 0)], [(0.6, 0.6), (1.1, 1.1)]],
    "R": [[(0, 1), (0, 0), (0.8, 0), (1, 0.25), (0.8, 0.5), (0, 0.5)], [(0.5, 0.5), (1, 1)]],
    "S": [[(1, 0.15), (0.7, 0), (0.3, 0), (0, 0.25), (0.3, 0.5), (0.7, 0.5), (1, 0.75), (0.7, 1), (0.3, 1), (0, 0.85)]],
    "T": [[(0, 0), (1, 0)], [(0.5, 0), (0.5, 1)]],
    "U": [[(0, 0), (0, 0.7), (0.3, 1), (0.7, 1), (1, 0.7), (1, 0)]],
    "V": [[(0, 0), (0.5, 1), (1, 0)]],
    "W": [[(0, 0), (0.25, 1), (0.5, 0.4), (0.75, 1), (1, 0)]],
    "X": [[(0, 0), (1, 1)], [(1, 0), (0, 1)]],
    "Y": [[(0, 0), (0.5, 0.5), (1, 0)], [(0.5, 0.5), (0.5, 1)]],
    "Z": [[(0, 0), (1, 0), (0, 1), (1, 1)]],
    "0": [[(0.3, 0), (0.7, 0), (1, 0.3), (1, 0.7), (0.7, 1), (0.3, 1), (0, 0.7), (0, 0.3), (0.3, 0)], [(0.8, 0.2), (0.2, 0.8)]],
    "1": [[(0.2, 0.3), (0.5, 0), (0.5, 1)], [(0.2, 1), (0.8, 1)]],
    "2": [[(0, 0.25), (0.3, 0), (0.7, 0), (1, 0.3), (0, 1), (1, 1)]],
    "3": [[(0, 0.1), (0.3, 0), (0.7, 0), (1, 0.25), (0.6, 0.5), (1, 0.75), (0.7, 1), (0.3, 1), (0, 0.9)]],
    "4": [[(0.8, 1), (0.8, 0), (0, 0.65), (1, 0.65)]],
    "5": [[(1, 0), (0, 0), (0, 0.45), (0.7, 0.45), (1, 0.7), (0.7, 1), (0.2, 1), (0, 0.85)]],
    "6": [[(0.8, 0.1), (0.4, 0), (0, 0.4), (0, 0.7), (0.4, 1), (0.8, 1), (1, 0.7), (1, 0.5), (0.6, 0.4), (0, 0.55)]],
    "7": [[(0, 0), (1, 0), (0.3, 1)]],
    "8": [[(0.4, 0), (0.7, 0), (0.9, 0.25), (0.7, 0.5), (0.3, 0.5), (0.1, 0.75), (0.3, 1), (0.7, 1), (0.9, 0.75), (0.7, 0.5), (0.3, 0.5), (0.1, 0.25), (0.4, 0)]],
    "9": [[(1, 0.45), (0.4, 0.6), (0, 0.5), (0, 0.3), (0.2, 0), (0.6, 0), (1, 0.3), (1, 0.6), (0.6, 1), (0.2, 0.9)]],
    ".": [[(0.4, 0.9), (0.6, 0.9), (0.6, 1.0), (0.4, 1.0), (0.4, 0.9)]],
    ",": [[(0.5, 0.8), (0.6, 0.9), (0.4, 1.1)]],
    "-": [[(0.2, 0.5), (0.8, 0.5)]],
    "+": [[(0.2, 0.5), (0.8, 0.5)], [(0.5, 0.2), (0.5, 0.8)]],
    ":": [[(0.4, 0.3), (0.6, 0.3)], [(0.4, 0.8), (0.6, 0.8)]],
    "!": [[(0.5, 0), (0.5, 0.7)], [(0.5, 0.9), (0.5, 1.0)]],
    "?": [[(0, 0.25), (0.3, 0), (0.7, 0), (1, 0.25), (0.5, 0.6), (0.5, 0.75)], [(0.5, 0.95), (0.5, 1.0)]],
    "*": [[(0.5, 0.2), (0.5, 0.8)], [(0.2, 0.35), (0.8, 0.65)], [(0.2, 0.65), (0.8, 0.35)]],
    "/": [[(0.1, 1), (0.9, 0)]],
    " ": [],
}


def draw_thick_line(
    hm: Heightmap,
    p0: Point2D,
    p1: Point2D,
    thickness_px: float = 2.0,
    elevation: float = 1.0,
) -> None:
    """Draw a smooth line segment with width onto heightmap."""
    x0, y0 = p0
    x1, y1 = p1
    dx = x1 - x0
    dy = y1 - y0
    length = math.sqrt(dx * dx + dy * dy)
    half_th = thickness_px * 0.5

    min_x = int(max(0, math.floor(min(x0, x1) - half_th - 1)))
    max_x = int(min(hm.width - 1, math.ceil(max(x0, x1) + half_th + 1)))
    min_y = int(max(0, math.floor(min(y0, y1) - half_th - 1)))
    max_y = int(min(hm.height - 1, math.ceil(max(y0, y1) + half_th + 1)))

    if length < 1e-6:
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                dist = math.hypot(x - x0, y - y0)
                if dist <= half_th:
                    hm.set(x, y, max(hm.get(x, y), elevation))
        return

    inv_len_sq = 1.0 / (length * length)

    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            # Project (x, y) onto line segment [p0, p1]
            t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) * inv_len_sq))
            proj_x = x0 + t * dx
            proj_y = y0 + t * dy
            dist = math.hypot(x - proj_x, y - proj_y)

            if dist <= half_th:
                # Smooth antialiased border falloff
                falloff = 1.0 if dist <= (half_th - 0.5) else (half_th + 0.5 - dist)
                val = elevation * max(0.0, min(1.0, falloff))
                hm.set(x, y, max(hm.get(x, y), val))


# ---------------------------------------------------------------------------
# 3. Procedural Relief Builder (Coins, Medallions, Emblems)
# ---------------------------------------------------------------------------

class ProceduralReliefBuilder:
    """High-level builder for generating classic numismatic coin relief elements."""

    def __init__(self, size: int = 256) -> None:
        self.size = size
        self.heightmap = Heightmap(size, size, 0.0)
        self.cx = size * 0.5
        self.cy = size * 0.5

    def draw_filled_circle(
        self,
        cx: float,
        cy: float,
        radius: float,
        elevation: float = 1.0,
        bevel_width_px: float = 0.0,
    ) -> ProceduralReliefBuilder:
        """Draw a filled circle with optional rounded bevel profile."""
        r_sq = radius * radius
        min_x = max(0, int(cx - radius - 1))
        max_x = min(self.size - 1, int(cx + radius + 1))
        min_y = max(0, int(cy - radius - 1))
        max_y = min(self.size - 1, int(cy + radius + 1))

        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                dist = math.hypot(x - cx, y - cy)
                if dist <= radius:
                    if bevel_width_px > 0.0:
                        edge_dist = radius - dist
                        t = min(1.0, edge_dist / bevel_width_px)
                        elev = elevation * math.sin(t * math.pi * 0.5)
                    else:
                        elev = elevation
                    self.heightmap.set(x, y, max(self.heightmap.get(x, y), elev))
        return self

    def draw_ring(
        self,
        cx: float,
        cy: float,
        inner_r: float,
        outer_r: float,
        elevation: float = 1.0,
        profile: str = "flat",
    ) -> ProceduralReliefBuilder:
        """Draw a concentric circular ring/border."""
        min_x = max(0, int(cx - outer_r - 1))
        max_x = min(self.size - 1, int(cx + outer_r + 1))
        min_y = max(0, int(cy - outer_r - 1))
        max_y = min(self.size - 1, int(cy + outer_r + 1))

        half_thick = (outer_r - inner_r) * 0.5
        mid_r = inner_r + half_thick

        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                dist = math.hypot(x - cx, y - cy)
                if inner_r <= dist <= outer_r:
                    if profile == "round":
                        d_mid = abs(dist - mid_r)
                        t = max(0.0, 1.0 - (d_mid / half_thick))
                        elev = elevation * math.sqrt(max(0.0, 1.0 - (1.0 - t) * (1.0 - t)))
                    else:
                        elev = elevation
                    self.heightmap.set(x, y, max(self.heightmap.get(x, y), elev))
        return self

    def draw_beaded_border(
        self,
        radius: float,
        bead_count: int = 64,
        bead_radius_px: float = 3.0,
        elevation: float = 1.0,
    ) -> ProceduralReliefBuilder:
        """Draw a classic numismatic beaded pearl rim along a circumference circle."""
        for i in range(bead_count):
            theta = (2.0 * math.pi * i) / bead_count
            bx = self.cx + radius * math.cos(theta)
            by = self.cy + radius * math.sin(theta)
            self.draw_filled_circle(bx, by, bead_radius_px, elevation=elevation, bevel_width_px=bead_radius_px * 0.8)
        return self

    def draw_rope_border(
        self,
        radius: float,
        strand_count: int = 48,
        strand_length: float = 6.0,
        strand_width: float = 2.5,
        elevation: float = 1.0,
        twist_angle_deg: float = 35.0,
    ) -> ProceduralReliefBuilder:
        """Draw a nautical / military challenge coin twisted rope border."""
        twist_rad = math.radians(twist_angle_deg)
        half_len = strand_length * 0.5

        for i in range(strand_count):
            theta = (2.0 * math.pi * i) / strand_count
            mid_x = self.cx + radius * math.cos(theta)
            mid_y = self.cy + radius * math.sin(theta)

            tan_angle = theta + math.pi * 0.5 + twist_rad
            p0 = (mid_x - half_len * math.cos(tan_angle), mid_y - half_len * math.sin(tan_angle))
            p1 = (mid_x + half_len * math.cos(tan_angle), mid_y + half_len * math.sin(tan_angle))

            draw_thick_line(self.heightmap, p0, p1, thickness_px=strand_width, elevation=elevation)
        return self

    def draw_star(
        self,
        cx: float,
        cy: float,
        outer_r: float,
        inner_r: Optional[float] = None,
        points: int = 5,
        elevation: float = 1.0,
        faceted_bevel: bool = True,
    ) -> ProceduralReliefBuilder:
        """Draw a multi-pointed heraldic/military star with optional 3D faceted beveling."""
        if inner_r is None:
            # Golden ratio standard star inner radius
            inner_r = outer_r * (math.sin(math.pi / 10.0) / math.sin(7.0 * math.pi / 10.0))

        # Generate star vertices
        star_poly: List[Point2D] = []
        total_pts = points * 2
        for i in range(total_pts):
            angle = -math.pi * 0.5 + (math.pi * i) / points
            r = outer_r if (i % 2 == 0) else inner_r
            star_poly.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))

        # Rasterize 2D star mask
        star_mask = Heightmap(self.size, self.size, 0.0)
        _rasterize_polygon_fill(star_mask, star_poly, elevation=1.0)

        if faceted_bevel:
            beveled = star_mask.bevel_edges(max_slope_px=outer_r * 0.5, profile="ridge")
            beveled.data = [v * elevation for v in beveled.data]
            self.heightmap = self.heightmap.blend(beveled, mode="max")
        else:
            star_mask.data = [v * elevation for v in star_mask.data]
            self.heightmap = self.heightmap.blend(star_mask, mode="max")

        return self

    def draw_shield(
        self,
        cx: float,
        cy: float,
        width: float,
        height: float,
        elevation: float = 1.0,
        bevel: bool = True,
    ) -> ProceduralReliefBuilder:
        """Draw a classic medieval / military heater shield emblem."""
        half_w = width * 0.5
        half_h = height * 0.5
        top = cy - half_h
        bot = cy + half_h
        mid_y = cy

        # Contour: Top flat with slight dip, vertical upper sides, curving to bottom point
        poly: List[Point2D] = [
            (cx - half_w, top),
            (cx + half_w, top),
            (cx + half_w, mid_y),
        ]
        # Curve to bottom point
        curve_steps = 16
        for step in range(curve_steps + 1):
            t = step / curve_steps
            # Quadratic curve from (cx + half_w, mid_y) to (cx, bot)
            px = (1 - t) * (1 - t) * (cx + half_w) + 2 * (1 - t) * t * (cx + half_w * 0.8) + t * t * cx
            py = (1 - t) * (1 - t) * mid_y + 2 * (1 - t) * t * (bot - height * 0.1) + t * t * bot
            poly.append((px, py))

        # Curve up left side
        for step in range(curve_steps, -1, -1):
            t = step / curve_steps
            px = (1 - t) * (1 - t) * (cx - half_w) + 2 * (1 - t) * t * (cx - half_w * 0.8) + t * t * cx
            py = (1 - t) * (1 - t) * mid_y + 2 * (1 - t) * t * (bot - height * 0.1) + t * t * bot
            poly.append((px, py))

        poly.append((cx - half_w, mid_y))

        shield_mask = Heightmap(self.size, self.size, 0.0)
        _rasterize_polygon_fill(shield_mask, poly, elevation=1.0)

        if bevel:
            beveled = shield_mask.bevel_edges(max_slope_px=width * 0.2, profile="chisel")
            beveled.data = [v * elevation for v in beveled.data]
            self.heightmap = self.heightmap.blend(beveled, mode="max")
        else:
            shield_mask.data = [v * elevation for v in shield_mask.data]
            self.heightmap = self.heightmap.blend(shield_mask, mode="max")

        return self

    def draw_laurel_wreath(
        self,
        radius: float,
        leaf_count: int = 14,
        leaf_size: float = 12.0,
        elevation: float = 1.0,
    ) -> ProceduralReliefBuilder:
        """Draw an ancient Roman / Olympic commemorative laurel wreath."""
        # Draw left and right arcs
        for side in (-1, 1):
            for i in range(leaf_count):
                # Distribute along side arc from bottom to top
                frac = i / (leaf_count - 1)
                angle_deg = 110.0 + frac * 140.0 if side == 1 else 70.0 - frac * 140.0
                theta = math.radians(angle_deg)

                base_x = self.cx + radius * math.cos(theta)
                base_y = self.cy + radius * math.sin(theta)

                # Leaf pointing direction
                leaf_angle = theta + (math.radians(35.0) * side)
                tip_x = base_x + leaf_size * math.cos(leaf_angle)
                tip_y = base_y + leaf_size * math.sin(leaf_angle)

                # Draw oval leaf
                mid_x = (base_x + tip_x) * 0.5
                mid_y = (base_y + tip_y) * 0.5
                self.draw_filled_circle(mid_x, mid_y, leaf_size * 0.35, elevation=elevation, bevel_width_px=leaf_size * 0.2)

        return self

    def draw_text(
        self,
        text: str,
        x: float,
        y: float,
        font_size: float = 16.0,
        thickness_px: float = 2.0,
        elevation: float = 1.0,
        align: str = "center",
    ) -> ProceduralReliefBuilder:
        """Draw straight embossed text using vector stroke font."""
        text = text.upper()
        char_w = font_size * 0.65
        total_w = len(text) * char_w

        if align == "center":
            start_x = x - total_w * 0.5
        elif align == "right":
            start_x = x - total_w
        else:
            start_x = x

        cur_x = start_x
        for ch in text:
            strokes = FONT_STROKES.get(ch, FONT_STROKES.get(" ", []))
            for stroke in strokes:
                for idx in range(len(stroke) - 1):
                    p0_norm = stroke[idx]
                    p1_norm = stroke[idx + 1]
                    p0 = (cur_x + p0_norm[0] * char_w, y + p0_norm[1] * font_size)
                    p1 = (cur_x + p1_norm[0] * char_w, y + p1_norm[1] * font_size)
                    draw_thick_line(self.heightmap, p0, p1, thickness_px=thickness_px, elevation=elevation)
            cur_x += char_w

        return self

    def draw_circular_text(
        self,
        text: str,
        radius: float,
        start_angle_deg: float = 180.0,
        end_angle_deg: float = 0.0,
        font_size: float = 14.0,
        thickness_px: float = 2.0,
        elevation: float = 1.0,
        inward: bool = True,
    ) -> ProceduralReliefBuilder:
        """Draw text embossed along a circular arc (essential for coin perimeter mottos)."""
        text = text.upper()
        if not text:
            return self

        num_chars = len(text)
        total_span_deg = end_angle_deg - start_angle_deg
        step_deg = total_span_deg / max(1, num_chars - 1) if num_chars > 1 else 0.0
        char_w = font_size * 0.6

        for i, ch in enumerate(text):
            cur_angle_deg = start_angle_deg + i * step_deg
            theta = math.radians(cur_angle_deg)

            # Center position of character on arc
            char_cx = self.cx + radius * math.cos(theta)
            char_cy = self.cy + radius * math.sin(theta)

            # Tangent angle for orienting the character
            rot_angle = theta + (math.pi * 0.5 if inward else -math.pi * 0.5)
            cos_r = math.cos(rot_angle)
            sin_r = math.sin(rot_angle)

            strokes = FONT_STROKES.get(ch, FONT_STROKES.get(" ", []))
            for stroke in strokes:
                for idx in range(len(stroke) - 1):
                    p0_n = stroke[idx]
                    p1_n = stroke[idx + 1]

                    # Local char box [-0.5..0.5, -0.5..0.5]
                    lx0 = (p0_n[0] - 0.5) * char_w
                    ly0 = (p0_n[1] - 0.5) * font_size
                    lx1 = (p1_n[0] - 0.5) * char_w
                    ly1 = (p1_n[1] - 0.5) * font_size

                    # Rotate into world space
                    wx0 = char_cx + (lx0 * cos_r - ly0 * sin_r)
                    wy0 = char_cy + (lx0 * sin_r + ly0 * cos_r)
                    wx1 = char_cx + (lx1 * cos_r - ly1 * sin_r)
                    wy1 = char_cy + (lx1 * sin_r + ly1 * cos_r)

                    draw_thick_line(self.heightmap, (wx0, wy0), (wx1, wy1), thickness_px=thickness_px, elevation=elevation)

        return self

    def build(self) -> Heightmap:
        """Return the finalized synthesized heightmap."""
        return self.heightmap


# ---------------------------------------------------------------------------
# 4. Pure Python SVG Path Parser & Rasterizer
# ---------------------------------------------------------------------------

def _parse_color_to_luminance(color_str: str, default: float = 1.0) -> float:
    """Convert CSS/SVG color string to normalized grayscale luminance [0.0, 1.0]."""
    if not color_str or color_str.strip().lower() in ("none", "transparent"):
        return 0.0

    c = color_str.strip().lower()
    if c == "white":
        return 1.0
    if c == "black":
        return 0.0

    # Hex colors #RGB, #RRGGBB
    if c.startswith("#"):
        hex_val = c[1:]
        if len(hex_val) == 3:
            r = int(hex_val[0] * 2, 16) / 255.0
            g = int(hex_val[1] * 2, 16) / 255.0
            b = int(hex_val[2] * 2, 16) / 255.0
        elif len(hex_val) >= 6:
            r = int(hex_val[0:2], 16) / 255.0
            g = int(hex_val[2:4], 16) / 255.0
            b = int(hex_val[4:6], 16) / 255.0
        else:
            return default
        return 0.299 * r + 0.587 * g + 0.114 * b

    # rgb(r, g, b)
    m = re.match(r"rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", c)
    if m:
        r = float(m.group(1)) / 255.0
        g = float(m.group(2)) / 255.0
        b = float(m.group(3)) / 255.0
        return 0.299 * r + 0.587 * g + 0.114 * b

    return default


def _rasterize_polygon_fill(
    hm: Heightmap,
    polygon: Sequence[Point2D],
    elevation: float = 1.0,
) -> None:
    """Rasterize a closed 2D polygon using standard scanline / ray-casting algorithm."""
    if len(polygon) < 3:
        return

    min_x = max(0, int(min(p[0] for p in polygon)))
    max_x = min(hm.width - 1, int(max(p[0] for p in polygon)))
    min_y = max(0, int(min(p[1] for p in polygon)))
    max_y = min(hm.height - 1, int(max(p[1] for p in polygon)))

    n = len(polygon)

    # Scanline point-in-polygon
    for y in range(min_y, max_y + 1):
        py = float(y) + 0.5
        node_x: List[float] = []

        # Find intersections with polygon edges
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i]
            xj, yj = polygon[j]

            if (yi < py <= yj) or (yj < py <= yi):
                x_intersect = xi + (py - yi) / (yj - yi) * (xj - xi)
                node_x.append(x_intersect)
            j = i

        node_x.sort()

        # Fill scanline spans
        for k in range(0, len(node_x) - 1, 2):
            x_start = max(min_x, int(math.ceil(node_x[k])))
            x_end = min(max_x, int(math.floor(node_x[k + 1])))
            for x in range(x_start, x_end + 1):
                hm.set(x, y, max(hm.get(x, y), elevation))


def _subdivide_cubic_bezier(
    p0: Point2D,
    p1: Point2D,
    p2: Point2D,
    p3: Point2D,
    segments: int = 16,
) -> List[Point2D]:
    """Sample points along a cubic Bézier curve."""
    pts: List[Point2D] = []
    for i in range(1, segments + 1):
        t = i / segments
        omt = 1.0 - t
        omt2 = omt * omt
        omt3 = omt2 * omt
        t2 = t * t
        t3 = t2 * t

        x = omt3 * p0[0] + 3.0 * omt2 * t * p1[0] + 3.0 * omt * t2 * p2[0] + t3 * p3[0]
        y = omt3 * p0[1] + 3.0 * omt2 * t * p1[1] + 3.0 * omt * t2 * p2[1] + t3 * p3[1]
        pts.append((x, y))
    return pts


def _subdivide_quadratic_bezier(
    p0: Point2D,
    p1: Point2D,
    p2: Point2D,
    segments: int = 12,
) -> List[Point2D]:
    """Sample points along a quadratic Bézier curve."""
    pts: List[Point2D] = []
    for i in range(1, segments + 1):
        t = i / segments
        omt = 1.0 - t
        omt2 = omt * omt
        t2 = t * t

        x = omt2 * p0[0] + 2.0 * omt * t * p1[0] + t2 * p2[0]
        y = omt2 * p0[1] + 2.0 * omt * t * p1[1] + t2 * p2[1]
        pts.append((x, y))
    return pts


def parse_svg_path_d(d_str: str) -> List[List[Point2D]]:
    """Parse SVG path 'd' attribute string into discrete 2D polyline subpaths.

    Supports M/m, L/l, H/h, V/v, C/c, S/s, Q/q, T/t, A/a, Z/z commands.
    """
    # Tokenize commands and numeric values
    tokens = re.findall(r"([a-zA-Z]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)", d_str)
    if not tokens:
        return []

    subpaths: List[List[Point2D]] = []
    current_subpath: List[Point2D] = []

    cur_x, cur_y = 0.0, 0.0
    start_x, start_y = 0.0, 0.0
    last_ctrl_x, last_ctrl_y = 0.0, 0.0
    last_cmd = ""

    idx = 0
    num_tokens = len(tokens)

    def next_float() -> float:
        nonlocal idx
        if idx >= num_tokens:
            return 0.0
        val = float(tokens[idx])
        idx += 1
        return val

    while idx < num_tokens:
        tok = tokens[idx]
        idx += 1

        if tok.isalpha():
            cmd = tok
        else:
            # Repeated coordinate with same command
            idx -= 1
            cmd = last_cmd

        is_rel = cmd.islower()
        cmd_up = cmd.upper()

        if cmd_up == "M":
            if current_subpath:
                subpaths.append(current_subpath)
                current_subpath = []
            x = next_float()
            y = next_float()
            cur_x = (cur_x + x) if is_rel else x
            cur_y = (cur_y + y) if is_rel else y
            start_x, start_y = cur_x, cur_y
            current_subpath.append((cur_x, cur_y))
            last_cmd = "l" if is_rel else "L"

        elif cmd_up == "L":
            x = next_float()
            y = next_float()
            cur_x = (cur_x + x) if is_rel else x
            cur_y = (cur_y + y) if is_rel else y
            current_subpath.append((cur_x, cur_y))
            last_cmd = cmd

        elif cmd_up == "H":
            x = next_float()
            cur_x = (cur_x + x) if is_rel else x
            current_subpath.append((cur_x, cur_y))
            last_cmd = cmd

        elif cmd_up == "V":
            y = next_float()
            cur_y = (cur_y + y) if is_rel else y
            current_subpath.append((cur_x, cur_y))
            last_cmd = cmd

        elif cmd_up == "C":
            x1 = next_float()
            y1 = next_float()
            x2 = next_float()
            y2 = next_float()
            x = next_float()
            y = next_float()

            cx1 = (cur_x + x1) if is_rel else x1
            cy1 = (cur_y + y1) if is_rel else y1
            cx2 = (cur_x + x2) if is_rel else x2
            cy2 = (cur_y + y2) if is_rel else y2
            dst_x = (cur_x + x) if is_rel else x
            dst_y = (cur_y + y) if is_rel else y

            pts = _subdivide_cubic_bezier((cur_x, cur_y), (cx1, cy1), (cx2, cy2), (dst_x, dst_y))
            current_subpath.extend(pts)

            last_ctrl_x, last_ctrl_y = cx2, cy2
            cur_x, cur_y = dst_x, dst_y
            last_cmd = cmd

        elif cmd_up == "S":
            # Smooth cubic bezier
            if last_cmd in ("C", "c", "S", "s"):
                cx1 = 2.0 * cur_x - last_ctrl_x
                cy1 = 2.0 * cur_y - last_ctrl_y
            else:
                cx1, cy1 = cur_x, cur_y

            x2 = next_float()
            y2 = next_float()
            x = next_float()
            y = next_float()

            cx2 = (cur_x + x2) if is_rel else x2
            cy2 = (cur_y + y2) if is_rel else y2
            dst_x = (cur_x + x) if is_rel else x
            dst_y = (cur_y + y) if is_rel else y

            pts = _subdivide_cubic_bezier((cur_x, cur_y), (cx1, cy1), (cx2, cy2), (dst_x, dst_y))
            current_subpath.extend(pts)

            last_ctrl_x, last_ctrl_y = cx2, cy2
            cur_x, cur_y = dst_x, dst_y
            last_cmd = cmd

        elif cmd_up == "Q":
            x1 = next_float()
            y1 = next_float()
            x = next_float()
            y = next_float()

            cx1 = (cur_x + x1) if is_rel else x1
            cy1 = (cur_y + y1) if is_rel else y1
            dst_x = (cur_x + x) if is_rel else x
            dst_y = (cur_y + y) if is_rel else y

            pts = _subdivide_quadratic_bezier((cur_x, cur_y), (cx1, cy1), (dst_x, dst_y))
            current_subpath.extend(pts)

            last_ctrl_x, last_ctrl_y = cx1, cy1
            cur_x, cur_y = dst_x, dst_y
            last_cmd = cmd

        elif cmd_up == "Z":
            cur_x, cur_y = start_x, start_y
            if current_subpath:
                current_subpath.append((start_x, start_y))
                subpaths.append(current_subpath)
                current_subpath = []
            last_cmd = cmd

    if current_subpath:
        subpaths.append(current_subpath)

    return subpaths


class SVGRasterizer:
    """Pure Python SVG Vector to 2D Heightmap Rasterizer."""

    def __init__(self, target_width: int = 256, target_height: int = 256) -> None:
        self.target_width = target_width
        self.target_height = target_height

    def rasterize_svg_string(self, svg_text: str, bevel_relief: bool = True) -> Heightmap:
        """Parse and rasterize an SVG XML string into a Heightmap."""
        try:
            # Strip default xmlns namespaces so tags are easy to match
            cleaned_svg = re.sub(r'\sxmlns="[^"]+"', "", svg_text)
            root = ET.fromstring(cleaned_svg)
        except Exception as err:
            raise ValueError(f"Failed to parse SVG XML: {err}") from err

        # Determine SVG viewBox / coordinate frame
        view_box = root.get("viewBox")
        if view_box:
            vb_parts = [float(p) for p in re.split(r"[\s,]+", view_box.strip())]
            vb_x, vb_y, vb_w, vb_h = vb_parts[0], vb_parts[1], vb_parts[2], vb_parts[3]
        else:
            vb_x = 0.0
            vb_y = 0.0
            vb_w = float(re.sub(r"[^\d.]", "", root.get("width", str(self.target_width))))
            vb_h = float(re.sub(r"[^\d.]", "", root.get("height", str(self.target_height))))

        scale_x = self.target_width / max(1e-6, vb_w)
        scale_y = self.target_height / max(1e-6, vb_h)

        def transform_pt(p: Point2D) -> Point2D:
            return ((p[0] - vb_x) * scale_x, (p[1] - vb_y) * scale_y)

        hm = Heightmap(self.target_width, self.target_height, 0.0)

        for elem in root.iter():
            tag = elem.tag.split("}")[-1].lower()

            fill_str = elem.get("fill", "#ffffff")
            stroke_str = elem.get("stroke", "none")
            stroke_w_str = elem.get("stroke-width", "1")
            stroke_w = float(re.sub(r"[^\d.]", "", stroke_w_str)) if stroke_w_str else 1.0

            fill_lum = _parse_color_to_luminance(fill_str, default=1.0)
            has_fill = fill_str.strip().lower() not in ("none", "transparent") and fill_lum > 0.01

            # 1. Circle
            if tag == "circle":
                cx = float(elem.get("cx", 0))
                cy = float(elem.get("cy", 0))
                r = float(elem.get("r", 0))
                tcx, tcy = transform_pt((cx, cy))
                tr = r * scale_x
                if has_fill:
                    # Draw filled circle
                    min_x = max(0, int(tcx - tr - 1))
                    max_x = min(hm.width - 1, int(tcx + tr + 1))
                    min_y = max(0, int(tcy - tr - 1))
                    max_y = min(hm.height - 1, int(tcy + tr + 1))
                    for y in range(min_y, max_y + 1):
                        for x in range(min_x, max_x + 1):
                            if math.hypot(x - tcx, y - tcy) <= tr:
                                hm.set(x, y, max(hm.get(x, y), fill_lum))

            # 2. Rect
            elif tag == "rect":
                rx = float(elem.get("x", 0))
                ry = float(elem.get("y", 0))
                rw = float(elem.get("width", 0))
                rh = float(elem.get("height", 0))
                p0 = transform_pt((rx, ry))
                p1 = transform_pt((rx + rw, ry + rh))
                if has_fill:
                    for y in range(max(0, int(p0[1])), min(hm.height, int(p1[1]) + 1)):
                        for x in range(max(0, int(p0[0])), min(hm.width, int(p1[0]) + 1)):
                            hm.set(x, y, max(hm.get(x, y), fill_lum))

            # 3. Polygon / Polyline
            elif tag in ("polygon", "polyline"):
                pts_str = elem.get("points", "")
                coord_vals = [float(v) for v in re.findall(r"[-+]?(?:\d*\.\d+|\d+)", pts_str)]
                pts: List[Point2D] = []
                for i in range(0, len(coord_vals) - 1, 2):
                    pts.append(transform_pt((coord_vals[i], coord_vals[i + 1])))
                if has_fill and len(pts) >= 3:
                    _rasterize_polygon_fill(hm, pts, elevation=fill_lum)

            # 4. Path
            elif tag == "path":
                d = elem.get("d", "")
                subpaths = parse_svg_path_d(d)
                for sp in subpaths:
                    t_sp = [transform_pt(p) for p in sp]
                    if has_fill and len(t_sp) >= 3:
                        _rasterize_polygon_fill(hm, t_sp, elevation=fill_lum)
                    if stroke_str.lower() not in ("none", "transparent"):
                        s_lum = _parse_color_to_luminance(stroke_str, default=1.0)
                        for idx in range(len(t_sp) - 1):
                            draw_thick_line(hm, t_sp[idx], t_sp[idx + 1], thickness_px=stroke_w * scale_x, elevation=s_lum)

        if bevel_relief:
            hm = hm.bevel_edges(max_slope_px=max(4.0, self.target_width * 0.04), profile="chisel")

        return hm

    def rasterize_svg_file(self, filepath: PathLike, bevel_relief: bool = True) -> Heightmap:
        """Load and rasterize an SVG file from disk."""
        text = read_text_safe(filepath)
        return self.rasterize_svg_string(text, bevel_relief=bevel_relief)
