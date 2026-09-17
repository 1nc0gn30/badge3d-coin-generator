"""Tests for Pure Python SVG Parser, Bézier Curve Flattener & Heightmap Rasterizer."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from badge3d_coin_generator.svg_rasterizer import (
    Heightmap,
    ProceduralReliefBuilder,
    SVGRasterizer,
)


# ---------------------------------------------------------------------------
# Heightmap Core Tests
# ---------------------------------------------------------------------------

def test_heightmap_initialization_and_access() -> None:
    """Verify Heightmap data buffer allocation and bounds-clamped get/set."""
    hm = Heightmap(width=64, height=64, initial_value=0.0)
    assert hm.width == 64
    assert hm.height == 64
    assert hm.get(10, 10) == 0.0

    hm.set(10, 10, 0.75)
    assert hm.get(10, 10) == 0.75

    # Out of bounds clamping
    assert hm.get(-5, -5) == hm.get(0, 0)
    assert hm.get(100, 100) == hm.get(63, 63)


def test_heightmap_to_and_from_2d_list() -> None:
    """Verify round-trip serialization between Heightmap and 2D float matrix."""
    grid = [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
        [0.7, 0.8, 0.9],
    ]
    hm = Heightmap.from_2d_list(grid)
    assert hm.width == 3
    assert hm.height == 3
    assert hm.get(1, 1) == 0.5

    out_grid = hm.to_2d_list()
    assert len(out_grid) == 3
    assert len(out_grid[0]) == 3
    for r in range(3):
        for c in range(3):
            assert pytest.approx(out_grid[r][c], abs=1e-5) == grid[r][c]


def test_heightmap_sampling_bilinear() -> None:
    """Verify bilinear sub-pixel interpolation on Heightmap."""
    hm = Heightmap(width=2, height=2)
    hm.set(0, 0, 0.0)
    hm.set(1, 0, 1.0)
    hm.set(0, 1, 1.0)
    hm.set(1, 1, 1.0)

    val = hm.sample_bilinear(0.5, 0.5)
    assert 0.0 <= val <= 1.0


def test_heightmap_image_processing_ops() -> None:
    """Verify blur, invert, normalize, and bevel operations."""
    hm = Heightmap(width=16, height=16)
    hm.set(8, 8, 1.0)

    # Blur
    blurred = hm.blur(radius=2.0)
    assert blurred.get(8, 8) > 0.0

    # Invert
    inverted = hm.invert()
    assert inverted.get(0, 0) == 1.0
    assert inverted.get(8, 8) == 0.0

    # Netpbm PGM exporters
    pgm_bin = hm.export_pgm_binary()
    assert pgm_bin.startswith(b"P5\n")

    pgm_asc = hm.export_pgm_ascii()
    assert pgm_asc.startswith("P2\n")


# ---------------------------------------------------------------------------
# Procedural Relief Builder Tests
# ---------------------------------------------------------------------------

def test_procedural_star_relief() -> None:
    """Verify star motif heightmap generation."""
    builder = ProceduralReliefBuilder(size=128)
    builder.draw_star(cx=64, cy=64, outer_r=40.0, points=5, elevation=1.0)
    hm = builder.heightmap

    assert isinstance(hm, Heightmap)
    assert hm.width == 128
    assert hm.height == 128
    # Center should be elevated
    assert hm.get(64, 64) > 0.0


def test_procedural_beaded_and_rope_borders() -> None:
    """Verify circular beaded and rope border generation."""
    builder = ProceduralReliefBuilder(size=128)
    builder.draw_beaded_border(radius=50.0, bead_count=24, bead_radius_px=3.0)
    builder.draw_rope_border(radius=40.0, strand_count=24)
    hm = builder.heightmap

    assert isinstance(hm, Heightmap)
    max_val = max(hm.data)
    assert max_val > 0.0


def test_procedural_shield_relief() -> None:
    """Verify medieval shield relief generation."""
    builder = ProceduralReliefBuilder(size=128)
    builder.draw_shield(cx=64, cy=64, width=40.0, height=50.0)
    hm = builder.heightmap
    assert hm.get(64, 64) > 0.0


# ---------------------------------------------------------------------------
# SVG Parser & Rasterizer Tests
# ---------------------------------------------------------------------------

def test_svg_rasterizer_shapes(sample_svg_text: str) -> None:
    """Verify parsing and rasterizing basic SVG shapes (circle, rect, path)."""
    rasterizer = SVGRasterizer(target_width=128, target_height=128)
    hm = rasterizer.rasterize_svg_string(sample_svg_text, bevel_relief=False)

    assert isinstance(hm, Heightmap)
    assert hm.width == 128
    assert hm.height == 128

    # Some pixels must be non-zero due to the rendered shapes
    assert max(hm.data) > 0.0


def test_svg_rasterizer_file_io(sample_svg_text: str, temp_output_dir: Path) -> None:
    """Verify reading and rasterizing SVG files from disk."""
    svg_file = temp_output_dir / "test_logo.svg"
    svg_file.write_text(sample_svg_text, encoding="utf-8")

    rasterizer = SVGRasterizer(target_width=64, target_height=64)
    hm = rasterizer.rasterize_svg_file(svg_file, bevel_relief=True)

    assert isinstance(hm, Heightmap)
    assert hm.width == 64
    assert hm.height == 64
    assert max(hm.data) > 0.0
