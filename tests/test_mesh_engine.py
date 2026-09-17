"""Comprehensive tests for the 3D parametric coin geometry & mesh generation engine."""

from __future__ import annotations

import math
from typing import List

import pytest

from badge3d_coin_generator.mesh_engine import (
    CoinMeshEngine,
    CoinParameters,
    MeshData,
    Vec3,
    calculate_reed_radius,
    generate_cartesian_relief_mesh,
    sample_heightmap_bilinear,
    triangle_area,
    triangle_normal,
    vec3_add,
    vec3_cross,
    vec3_dot,
    vec3_length,
    vec3_normalize,
    vec3_scale,
    vec3_sub,
)


# ---------------------------------------------------------------------------
# Vector Math & Triangle Tests
# ---------------------------------------------------------------------------

def test_vector_math_primitives() -> None:
    """Test pure Python vector operations."""
    a = (1.0, 2.0, 3.0)
    b = (4.0, 5.0, 6.0)

    assert vec3_add(a, b) == (5.0, 7.0, 9.0)
    assert vec3_sub(b, a) == (3.0, 3.0, 3.0)
    assert vec3_scale(a, 2.0) == (2.0, 4.0, 6.0)
    assert vec3_dot(a, b) == 1.0 * 4.0 + 2.0 * 5.0 + 3.0 * 6.0
    assert vec3_length((3.0, 4.0, 0.0)) == 5.0

    # Cross product unit axes: X cross Y = Z
    x_axis = (1.0, 0.0, 0.0)
    y_axis = (0.0, 1.0, 0.0)
    assert vec3_cross(x_axis, y_axis) == (0.0, 0.0, 1.0)

    # Normalization
    norm_v = vec3_normalize((0.0, 5.0, 0.0))
    assert norm_v == (0.0, 1.0, 0.0)
    assert vec3_normalize((0.0, 0.0, 0.0)) == (0.0, 0.0, 1.0)


def test_triangle_geometry_helpers() -> None:
    """Test triangle normal and area calculations."""
    v0 = (0.0, 0.0, 0.0)
    v1 = (2.0, 0.0, 0.0)
    v2 = (0.0, 2.0, 0.0)

    normal = triangle_normal(v0, v1, v2)
    assert pytest.approx(normal[0]) == 0.0
    assert pytest.approx(normal[1]) == 0.0
    assert pytest.approx(normal[2]) == 1.0

    area = triangle_area(v0, v1, v2)
    assert pytest.approx(area) == 2.0  # 0.5 * 2 * 2


# ---------------------------------------------------------------------------
# MeshData Class Tests
# ---------------------------------------------------------------------------

def test_mesh_data_properties_and_bbox(simple_cube_mesh: MeshData) -> None:
    """Verify MeshData vertex/triangle counts and axis-aligned bounding box."""
    assert simple_cube_mesh.vertex_count == 8
    assert simple_cube_mesh.triangle_count == 12

    bbox_min, bbox_max = simple_cube_mesh.get_bounding_box()
    assert bbox_min == (-1.0, -1.0, -1.0)
    assert bbox_max == (1.0, 1.0, 1.0)


def test_mesh_data_is_watertight(simple_cube_mesh: MeshData) -> None:
    """Verify closed 2-manifold check on a watertight mesh vs an open mesh."""
    assert simple_cube_mesh.is_watertight() is True

    # Remove one triangle -> creates an open boundary hole
    open_mesh = MeshData(
        vertices=list(simple_cube_mesh.vertices),
        faces=list(simple_cube_mesh.faces[:-1]),
    )
    assert open_mesh.is_watertight() is False


def test_mesh_transform_and_merge(simple_cube_mesh: MeshData) -> None:
    """Verify scaling, translation, and mesh merging."""
    transformed = simple_cube_mesh.transform(
        scale=(2.0, 2.0, 2.0),
        translation=(10.0, 0.0, 0.0),
    )
    bbox_min, bbox_max = transformed.get_bounding_box()
    assert pytest.approx(bbox_min[0]) == 8.0   # -2 + 10
    assert pytest.approx(bbox_max[0]) == 12.0  #  2 + 10

    merged = simple_cube_mesh.merge(transformed)
    assert merged.vertex_count == 16
    assert merged.triangle_count == 24


def test_mesh_compute_normals(simple_cube_mesh: MeshData) -> None:
    """Verify smooth area-weighted normal computation."""
    simple_cube_mesh.compute_normals(smooth=True, weight_by_area=True)
    assert len(simple_cube_mesh.normals) == simple_cube_mesh.vertex_count
    for n in simple_cube_mesh.normals:
        length = vec3_length(n)
        assert pytest.approx(length, rel=1e-3) == 1.0


# ---------------------------------------------------------------------------
# Reeding & Heightmap Sampling Tests
# ---------------------------------------------------------------------------

def test_reed_radius_profiles() -> None:
    """Test reeding radius calculations across different waveform profiles."""
    base_r = 20.0
    reed_count = 100
    reed_depth = 0.5

    profiles = ["sinusoidal", "square", "triangular", "trapezoidal", "fluted"]
    for prof in profiles:
        # At angle 0
        r0 = calculate_reed_radius(base_r, 0.0, reed_count, reed_depth, profile=prof)
        # At middle of reed trough
        trough_angle = (math.pi / reed_count)
        r_trough = calculate_reed_radius(base_r, trough_angle, reed_count, reed_depth, profile=prof)

        assert (base_r - reed_depth - 1e-4) <= r_trough <= base_r + 1e-4
        assert (base_r - reed_depth - 1e-4) <= r0 <= base_r + 1e-4

    # Disabled reeds return base radius
    assert calculate_reed_radius(base_r, 1.23, reed_count=0, reed_depth=0.5) == base_r


def test_bilinear_heightmap_sampler() -> None:
    """Test bilinear elevation interpolation on 2D heightmap grids."""
    grid = [
        [0.0, 1.0],
        [1.0, 0.0],
    ]
    # Center UV (0.5, 0.5) should be average = 0.5
    val_center = sample_heightmap_bilinear(grid, 0.5, 0.5)
    assert pytest.approx(val_center) == 0.5

    # Corner (0.0, 0.0) -> top-left = 0.0
    assert pytest.approx(sample_heightmap_bilinear(grid, 0.0, 0.0)) == 0.0
    # Corner (1.0, 0.0) -> top-right = 1.0
    assert pytest.approx(sample_heightmap_bilinear(grid, 1.0, 0.0)) == 1.0

    # Empty heightmap fallback
    assert sample_heightmap_bilinear(None, 0.5, 0.5, default=0.25) == 0.25


# ---------------------------------------------------------------------------
# Parametric Coin Generation Tests
# ---------------------------------------------------------------------------

def test_generate_default_coin_mesh(sample_coin_params: CoinParameters) -> None:
    """Test standard coin generation and verify manifold geometry."""
    engine = CoinMeshEngine(sample_coin_params)
    mesh = engine.generate()

    assert mesh.vertex_count > 500
    assert mesh.triangle_count > 1000
    assert mesh.is_watertight() is True

    bbox_min, bbox_max = mesh.get_bounding_box()
    # Check approximate radius
    approx_r = (bbox_max[0] - bbox_min[0]) / 2.0
    assert pytest.approx(approx_r, rel=0.05) == sample_coin_params.radius

    # Check approximate thickness
    approx_t = bbox_max[2] - bbox_min[2]
    assert pytest.approx(approx_t, rel=0.05) == sample_coin_params.thickness


def test_coin_with_relief_heightmaps(sample_heightmap_matrix: List[List[float]]) -> None:
    """Test coin mesh generation with obverse and reverse heightmap displacement."""
    params = CoinParameters(
        radius=18.0,
        thickness=3.0,
        rim_width=1.5,
        rim_height=0.6,
        edge_reed_count=40,
        reed_depth=0.2,
        obverse_heightmap=sample_heightmap_matrix,
        reverse_heightmap=sample_heightmap_matrix,
        relief_depth_obverse=0.8,
        relief_depth_reverse=0.8,
        relief_mode_obverse="emboss",
        relief_mode_reverse="engrave",
        radial_segments=40,
        field_rings=16,
    )
    engine = CoinMeshEngine(params)
    mesh = engine.generate()

    assert mesh.vertex_count > 300
    assert mesh.triangle_count > 600
    assert mesh.is_watertight() is True


def test_generate_cartesian_relief_mesh(sample_heightmap_matrix: List[List[float]]) -> None:
    """Test generating a rectangular relief badge plaque."""
    mesh = generate_cartesian_relief_mesh(
        heightmap=sample_heightmap_matrix,
        width_mm=30.0,
        height_mm=30.0,
        base_thickness_mm=2.0,
        relief_depth_mm=1.0,
        smooth_shading=True,
    )

    assert mesh.vertex_count > 100
    assert mesh.triangle_count > 200
    assert mesh.is_watertight() is True

    bbox_min, bbox_max = mesh.get_bounding_box()
    assert pytest.approx(bbox_max[0] - bbox_min[0]) == 30.0
    assert pytest.approx(bbox_max[1] - bbox_min[1]) == 30.0
