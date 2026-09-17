"""Comprehensive Unit & Integration Test Suite for Subagent 1 Modules:
- compat.py
- mesh_engine.py
- exporters.py
- svg_rasterizer.py
"""

import math
import os
import struct
import tempfile
import unittest
from pathlib import Path

from badge3d_coin_generator.compat import (
    atomic_write_bytes,
    atomic_write_text,
    ensure_dir,
    ensure_parent_dir,
    get_system_info,
    is_linux,
    is_macos,
    is_termux,
    is_windows,
    read_bytes_safe,
    read_text_safe,
    safe_path,
    sanitize_filename,
)
from badge3d_coin_generator.exporters import (
    export_ascii_stl,
    export_binary_stl,
    export_glb,
    export_gltf,
    export_mesh,
    export_obj,
    mesh_to_ascii_stl_text,
    mesh_to_binary_stl_bytes,
    mesh_to_glb_bytes,
    mesh_to_gltf_json,
    mesh_to_obj_text,
)
from badge3d_coin_generator.mesh_engine import (
    CoinMeshEngine,
    CoinParameters,
    MeshData,
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
from badge3d_coin_generator.svg_rasterizer import (
    FONT_STROKES,
    Heightmap,
    ProceduralReliefBuilder,
    SVGRasterizer,
    _parse_color_to_luminance,
    parse_svg_path_d,
)


class TestCompat(unittest.TestCase):
    """Test compat.py functionality."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_safe_path_and_ensure_dir(self) -> None:
        p = self.tmp_path / "sub" / "nested"
        ensured = ensure_dir(p)
        self.assertTrue(ensured.exists())
        self.assertTrue(ensured.is_dir())

    def test_sanitize_filename(self) -> None:
        raw = "my:coin/file*name?<test>|.stl"
        sanitized = sanitize_filename(raw)
        self.assertNotIn(":", sanitized)
        self.assertNotIn("/", sanitized)
        self.assertNotIn("*", sanitized)
        self.assertNotIn("<", sanitized)
        self.assertTrue(sanitized.endswith(".stl"))

        # Reserved Windows filename
        con_file = sanitize_filename("CON.stl")
        self.assertTrue(con_file.startswith("_CON"))

    def test_atomic_write_and_read_bytes(self) -> None:
        target = self.tmp_path / "data.bin"
        payload = b"\x00\x01\x02\x03HELLO\xff"
        res_path = atomic_write_bytes(target, payload, backup=True)
        self.assertEqual(res_path, target)
        self.assertTrue(target.exists())
        self.assertEqual(read_bytes_safe(target), payload)

        # Overwrite with backup
        new_payload = b"NEW_DATA"
        atomic_write_bytes(target, new_payload, backup=True)
        self.assertEqual(read_bytes_safe(target), new_payload)
        bak_file = target.with_suffix(".bin.bak")
        self.assertTrue(bak_file.exists())
        self.assertEqual(read_bytes_safe(bak_file), payload)

    def test_atomic_write_and_read_text(self) -> None:
        target = self.tmp_path / "text.txt"
        text = "Hello World! 🪙 3D Coin Generator"
        res_path = atomic_write_text(target, text, encoding="utf-8")
        self.assertEqual(res_path, target)
        self.assertTrue(target.exists())
        self.assertEqual(read_text_safe(target), text)

    def test_system_info(self) -> None:
        info = get_system_info()
        self.assertIn("system", info)
        self.assertIn("python_version", info)
        self.assertIn("byteorder", info)


class TestMeshEngine(unittest.TestCase):
    """Test 3D Vector math, MeshData, and CoinMeshEngine."""

    def test_vector_math(self) -> None:
        v1 = (1.0, 2.0, 3.0)
        v2 = (4.0, 5.0, 6.0)
        self.assertEqual(vec3_add(v1, v2), (5.0, 7.0, 9.0))
        self.assertEqual(vec3_sub(v2, v1), (3.0, 3.0, 3.0))
        self.assertEqual(vec3_scale(v1, 2.0), (2.0, 4.0, 6.0))
        self.assertAlmostEqual(vec3_dot(v1, v2), 32.0)
        self.assertEqual(vec3_cross((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), (0.0, 0.0, 1.0))
        self.assertAlmostEqual(vec3_length((3.0, 4.0, 0.0)), 5.0)

    def test_mesh_data_operations(self) -> None:
        # Simple tetrahedron
        verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
        faces = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
        mesh = MeshData(vertices=verts, faces=faces)
        mesh.compute_normals(smooth=True)
        self.assertEqual(len(mesh.normals), 4)
        self.assertTrue(mesh.is_watertight())
        bbox_min, bbox_max = mesh.get_bounding_box()
        self.assertEqual(bbox_min, (0.0, 0.0, 0.0))
        self.assertEqual(bbox_max, (1.0, 1.0, 1.0))

        # Transform
        t_mesh = mesh.transform(scale=(2.0, 2.0, 2.0), translation=(5.0, 5.0, 5.0))
        t_min, t_max = t_mesh.get_bounding_box()
        self.assertEqual(t_min, (5.0, 5.0, 5.0))
        self.assertEqual(t_max, (7.0, 7.0, 7.0))

        # Merge
        merged = mesh.merge(t_mesh)
        self.assertEqual(merged.vertex_count, 8)
        self.assertEqual(merged.triangle_count, 8)

    def test_reed_profiles(self) -> None:
        profiles = ["sinusoidal", "square", "triangular", "trapezoidal", "fluted"]
        for p in profiles:
            r0 = calculate_reed_radius(20.0, 0.0, 100, 0.25, profile=p)
            r1 = calculate_reed_radius(20.0, math.pi / 100.0, 100, 0.25, profile=p)
            self.assertGreaterEqual(r0, 19.5)
            self.assertLessEqual(r0, 20.05)
            self.assertGreaterEqual(r1, 19.5)
            self.assertLessEqual(r1, 20.05)

    def test_coin_generation_watertightness(self) -> None:
        # Test default coin
        params = CoinParameters(
            radius=20.0,
            thickness=3.0,
            rim_width=1.5,
            rim_height=0.4,
            edge_reed_count=80,
            radial_segments=160,
            field_rings=16,
        )
        engine = CoinMeshEngine(params)
        mesh = engine.generate()

        self.assertTrue(mesh.is_watertight())
        self.assertGreater(mesh.vertex_count, 1000)
        self.assertGreater(mesh.triangle_count, 2000)
        min_pt, max_pt = mesh.get_bounding_box()
        self.assertAlmostEqual(min_pt[0], -20.0, delta=0.5)
        self.assertAlmostEqual(max_pt[0], 20.0, delta=0.5)
        self.assertAlmostEqual(min_pt[2], -1.5, delta=0.01)
        self.assertAlmostEqual(max_pt[2], 1.5, delta=0.01)

    def test_heightmap_displacement_on_coin(self) -> None:
        # Create a procedural relief heightmap
        builder = ProceduralReliefBuilder(size=64)
        builder.draw_star(32, 32, 20, points=5, elevation=1.0)
        hm_grid = builder.build().to_2d_list()

        params = CoinParameters(
            radius=15.0,
            thickness=2.5,
            obverse_heightmap=hm_grid,
            relief_depth_obverse=0.5,
            relief_mode_obverse="emboss",
            radial_segments=64,
            field_rings=16,
        )
        mesh = CoinMeshEngine(params).generate()
        self.assertTrue(mesh.is_watertight())
        min_pt, max_pt = mesh.get_bounding_box()
        # Max Z should reflect base thickness + relief height
        self.assertGreater(max_pt[2], 1.25)


class TestExporters(unittest.TestCase):
    """Test STL, OBJ, GLTF, and GLB exporters."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

        # Create a lightweight test coin mesh
        p = CoinParameters(radius=10.0, thickness=2.0, edge_reed_count=20, radial_segments=40, field_rings=6)
        self.mesh = CoinMeshEngine(p).generate()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_binary_stl_exporter(self) -> None:
        out_file = self.tmp_path / "coin.stl"
        res = export_binary_stl(self.mesh, out_file)
        self.assertTrue(res.exists())
        data = res.read_bytes()

        # Binary STL header checks
        self.assertGreaterEqual(len(data), 84)
        num_tris = struct.unpack_from("<I", data, 80)[0]
        self.assertEqual(num_tris, self.mesh.triangle_count)
        expected_size = 84 + num_tris * 50
        self.assertEqual(len(data), expected_size)

    def test_ascii_stl_exporter(self) -> None:
        out_file = self.tmp_path / "coin_ascii.stl"
        res = export_ascii_stl(self.mesh, out_file, solid_name="my_coin")
        self.assertTrue(res.exists())
        text = res.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("solid my_coin"))
        self.assertTrue(text.strip().endswith("endsolid my_coin"))
        self.assertIn("facet normal", text)
        self.assertIn("vertex", text)

    def test_obj_exporter(self) -> None:
        out_file = self.tmp_path / "coin.obj"
        obj_p, mtl_p = export_obj(self.mesh, out_file, object_name="CoinModel", write_mtl=True)
        self.assertTrue(obj_p.exists())
        self.assertIsNotNone(mtl_p)
        self.assertTrue(mtl_p.exists())

        obj_text = obj_p.read_text(encoding="utf-8")
        self.assertIn("o CoinModel", obj_text)
        self.assertIn("mtllib coin.mtl", obj_text)
        self.assertIn("v ", obj_text)
        self.assertIn("vn ", obj_text)
        self.assertIn("f ", obj_text)

        mtl_text = mtl_p.read_text(encoding="utf-8")
        self.assertIn("newmtl CoinGold", mtl_text)
        self.assertIn("Kd ", mtl_text)

    def test_gltf_json_exporter(self) -> None:
        out_file = self.tmp_path / "coin.gltf"
        res = export_gltf(self.mesh, out_file)
        self.assertTrue(res.exists())
        json_text = res.read_text(encoding="utf-8")
        self.assertIn('"version": "2.0"', json_text)
        self.assertIn('"POSITION"', json_text)
        self.assertIn('"data:application/octet-stream;base64,', json_text)

    def test_glb_binary_exporter(self) -> None:
        out_file = self.tmp_path / "coin.glb"
        res = export_glb(self.mesh, out_file)
        self.assertTrue(res.exists())
        data = res.read_bytes()

        # GLB 12-byte header check
        magic, version, total_len = struct.unpack_from("<4sII", data, 0)
        self.assertEqual(magic, b"glTF")
        self.assertEqual(version, 2)
        self.assertEqual(total_len, len(data))

    def test_universal_export_facade(self) -> None:
        for ext in (".stl", ".obj", ".gltf", ".glb"):
            out_file = self.tmp_path / f"test{ext}"
            res = export_mesh(self.mesh, out_file)
            self.assertTrue(res.exists())
            self.assertGreater(res.stat().st_size, 0)


class TestSVGRasterizer(unittest.TestCase):
    """Test SVG parsing, procedural relief building, and heightmaps."""

    def test_heightmap_primitives(self) -> None:
        hm = Heightmap(32, 32, initial_value=0.0)
        hm.set(16, 16, 1.0)
        self.assertEqual(hm.get(16, 16), 1.0)
        self.assertAlmostEqual(hm.sample_bilinear(16 / 31, 16 / 31), 1.0, places=3)

        # Blur
        blurred = hm.blur(radius=1.5)
        self.assertGreater(blurred.get(16, 17), 0.0)

        # Invert
        inv = hm.invert()
        self.assertEqual(inv.get(0, 0), 1.0)
        self.assertEqual(inv.get(16, 16), 0.0)

        # Blend
        hm2 = Heightmap(32, 32, initial_value=0.5)
        blended = hm.blend(hm2, mode="max")
        self.assertEqual(blended.get(0, 0), 0.5)
        self.assertEqual(blended.get(16, 16), 1.0)

        # PGM export
        pgm_bytes = hm.export_pgm_binary()
        self.assertTrue(pgm_bytes.startswith(b"P5\n32 32\n255\n"))

    def test_procedural_relief_builder(self) -> None:
        builder = ProceduralReliefBuilder(size=64)
        builder.draw_beaded_border(radius=28.0, bead_count=20, bead_radius_px=2.0)
        builder.draw_rope_border(radius=24.0, strand_count=16)
        builder.draw_shield(32, 32, width=20, height=24)
        builder.draw_star(32, 32, outer_r=10, points=5)
        builder.draw_laurel_wreath(radius=18.0, leaf_count=8)
        builder.draw_circular_text("LIBERTY", radius=22.0, start_angle_deg=160.0, end_angle_deg=20.0)
        builder.draw_text("2026", 32, 48, font_size=8.0)

        hm = builder.build()
        self.assertEqual(hm.width, 64)
        self.assertEqual(hm.height, 64)
        # Check non-empty elevation
        max_val = max(hm.data)
        self.assertGreater(max_val, 0.5)

    def test_svg_path_parser(self) -> None:
        d = "M 10 10 L 20 10 C 25 10 30 15 30 20 Q 30 25 20 30 Z"
        subpaths = parse_svg_path_d(d)
        self.assertEqual(len(subpaths), 1)
        self.assertGreater(len(subpaths[0]), 5)

    def test_svg_rasterizer_shapes(self) -> None:
        svg_content = """<svg width="64" height="64" viewBox="0 0 64 64">
            <circle cx="32" cy="32" r="20" fill="#ffffff" />
            <rect x="22" y="22" width="20" height="20" fill="#888888" />
            <polygon points="32,10 40,30 24,30" fill="#ffffff" />
            <path d="M 10 32 L 54 32" stroke="#ffffff" stroke-width="4" />
        </svg>"""
        rasterizer = SVGRasterizer(target_width=64, target_height=64)
        hm = rasterizer.rasterize_svg_string(svg_content, bevel_relief=True)
        self.assertEqual(hm.width, 64)
        self.assertEqual(hm.height, 64)
        self.assertGreater(max(hm.data), 0.5)


if __name__ == "__main__":
    unittest.main()
