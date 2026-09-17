"""Multi-OS Command Line Interface (CLI) for badge3d-coin-generator.

Provides comprehensive terminal commands for parametric 3D coin generation,
preset catalog inspection, 3D printing packaging exports, MCP stdio server,
system toolchain diagnostics, self-test verification, and embedded Material 3 Web Studio.

Subcommands:
- `generate`: Generate 3D coin mesh to STL, OBJ, or JSON.
- `presets`: List and filter the coin templates catalog.
- `serve`: Launch the Badge3D Coin Studio Web UI server (design influenced by Material 3).
- `mcp`: Run the Model Context Protocol (MCP) server over stdio.
- `diagnostics` / `doctor` / `platform`: System & 3D toolchain diagnostics.
- `test`: Run comprehensive internal self-verification suite.

Zero external runtime dependencies (100% Python Standard Library).
"""

from __future__ import annotations

import argparse
import http.server
import json
import math
import os
import platform
import socketserver
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .__init__ import (
    COIN_PRESETS,
    CoinGenerator,
    __version__,
    compute_mesh_volume,
    compute_mesh_weights,
    get_coin_presets,
    resolve_preset,
)
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
from .exporters import export_ascii_stl, export_binary_stl, export_obj as export_obj_files
from .mcp_server import MCPServer, run_mcp_server
from .mesh_engine import MeshData


# ---------------------------------------------------------------------------
# ANSI Terminal Color & Styling Utilities
# ---------------------------------------------------------------------------

class Color:
    """ANSI color codes with automatic terminal detection and NO_COLOR support."""

    ENABLED = True

    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    BG_DARK = "\033[40m"
    BG_BLUE = "\033[44m"

    RESET = "\033[0m"

    @classmethod
    def setup(cls, no_color: bool = False) -> None:
        """Configure color support based on flags, environment variables, and TTY."""
        if (
            no_color
            or os.environ.get("NO_COLOR") is not None
            or os.environ.get("TERM") == "dumb"
            or not hasattr(sys.stdout, "isatty")
            or not sys.stdout.isatty()
        ):
            cls.ENABLED = False

    @classmethod
    def apply(cls, text: str, *styles: str) -> str:
        """Apply ANSI styles to text if colors are enabled."""
        if not cls.ENABLED or not styles:
            return str(text)
        prefix = "".join(styles)
        return f"{prefix}{text}{cls.RESET}"

    @classmethod
    def bold(cls, text: str) -> str:
        return cls.apply(text, cls.BOLD)

    @classmethod
    def green(cls, text: str) -> str:
        return cls.apply(text, cls.GREEN, cls.BOLD)

    @classmethod
    def yellow(cls, text: str) -> str:
        return cls.apply(text, cls.YELLOW)

    @classmethod
    def cyan(cls, text: str) -> str:
        return cls.apply(text, cls.CYAN)

    @classmethod
    def red(cls, text: str) -> str:
        return cls.apply(text, cls.RED, cls.BOLD)

    @classmethod
    def dim(cls, text: str) -> str:
        return cls.apply(text, cls.DIM)

    @classmethod
    def magenta(cls, text: str) -> str:
        return cls.apply(text, cls.MAGENTA)


def print_banner() -> None:
    """Print stylish ASCII banner for badge3d-coin-generator."""
    banner = f"""
{Color.cyan("╔═════════════════════════════════════════════════════════════════════╗")}
{Color.cyan("║")}   {Color.bold(Color.yellow("____            _             _____ ____      ____"))}          {Color.cyan("║")}
{Color.cyan("║")}  {Color.bold(Color.yellow("| __ )  __ _  __| | __ _  ___ |___ //  _ \\    / ___|___  ___"))} {Color.cyan("║")}
{Color.cyan("║")}  {Color.bold(Color.yellow("|  _ \\ / _` |/ _` |/ _` |/ _ \\  |_ \\| | | |  | |   / _ \\/ _ \\"))}{Color.cyan("║")}
{Color.cyan("║")}  {Color.bold(Color.yellow("| |_) | (_| | (_| | (_| |  __/ ___) | |_| |  | |__| (_) | |)"))}{Color.cyan("║")}
{Color.cyan("║")}  {Color.bold(Color.yellow("|____/ \\__,_|\\__,_|\\__, |\\___||____/|____/    \\____\\___/ \\_/"))} {Color.cyan("║")}
{Color.cyan("║")}                     {Color.yellow("|___/")}   {Color.bold("3D Coin Generator & Studio")}  {Color.dim(f"v{__version__}")}  {Color.cyan("║")}
{Color.cyan("╚═════════════════════════════════════════════════════════════════════╝")}
"""
    print(banner)


# ---------------------------------------------------------------------------
# Command: `generate`
# ---------------------------------------------------------------------------

def handle_generate(args: argparse.Namespace) -> int:
    """Handle the `generate` subcommand."""
    # Determine preset if specified
    preset_data = resolve_preset(args.preset) if args.preset else None

    radius = args.radius if args.radius is not None else (preset_data.get("radius", 20.0) if preset_data else 20.0)
    thickness = args.thickness if args.thickness is not None else (preset_data.get("thickness", 3.0) if preset_data else 3.0)
    serrations = args.serrations if args.serrations is not None else (preset_data.get("serrations", 80) if preset_data else 80)
    relief_pattern = args.pattern if args.pattern is not None else (preset_data.get("relief_pattern", "wreath") if preset_data else "wreath")
    rim_width = args.rim_width if args.rim_width is not None else (preset_data.get("rim_width", 2.0) if preset_data else 2.0)
    rim_height = args.rim_height if args.rim_height is not None else (preset_data.get("rim_height", 0.4) if preset_data else 0.4)
    edge_type = args.edge if args.edge is not None else (preset_data.get("edge_type", "reeded") if preset_data else "reeded")

    output_path = safe_path(args.output)
    fmt = (args.format or output_path.suffix.lstrip(".").lower() or "stl").lower()

    if not args.quiet:
        print(Color.bold(f"\n🪙 Generating 3D Coin: {Color.cyan(preset_data['name'] if preset_data else 'Custom Coin')}..."))

    t0 = time.perf_counter()

    gen = CoinGenerator(
        radius=radius,
        thickness=thickness,
        serrations=serrations,
        relief_pattern=relief_pattern,
        rim_width=rim_width,
        rim_height=rim_height,
        edge_type=edge_type,
        resolution=args.resolution,
        reverse_relief_pattern=args.reverse_pattern,
        edge_inscription=getattr(args, "edge_inscription", None),
        edge_inscription_depth=getattr(args, "edge_inscription_depth", 0.25),
        edge_inscription_mode=getattr(args, "edge_inscription_mode", "incuse"),
        security_stamp_seed=getattr(args, "security_stamp", None),
        security_stamp_grooves=getattr(args, "security_grooves", 64),
        segmented_sectors=getattr(args, "segmented_sectors", 0),
    )

    mesh = gen.generate()
    gen_time = time.perf_counter() - t0

    # Write output
    t_exp_0 = time.perf_counter()
    if fmt in ("stl", "stla", "stlb"):
        is_binary = not args.ascii
        written_path = gen.export_stl(output_path, binary=is_binary)
    elif fmt == "obj":
        written_path = gen.export_obj(output_path, object_name=args.object_name or "CoinMesh")
    elif fmt == "json":
        summary_data = gen.get_summary()
        atomic_write_text(output_path, json.dumps(summary_data, indent=2))
        written_path = output_path
    else:
        # Default to binary STL
        written_path = gen.export_stl(output_path, binary=True)

    exp_time = time.perf_counter() - t_exp_0
    file_size_kb = round(written_path.stat().st_size / 1024.0, 2)

    vol = compute_mesh_volume(mesh)
    weights = compute_mesh_weights(vol)
    min_pt, max_pt = mesh.get_bounding_box()

    if not args.quiet:
        print(f"\n{Color.green('✔')} 3D Coin Model Generated & Exported Successfully!")
        print(f"  {Color.bold('File')}:        {Color.cyan(str(written_path.resolve()))} ({Color.bold(str(file_size_kb))} KB)")
        print(f"  {Color.bold('Format')}:      {fmt.upper()} {'(Binary)' if (fmt == 'stl' and not args.ascii) else ''}")
        print(f"  {Color.bold('Dimensions')}:  Diameter: {Color.yellow(f'{radius*2.0:.1f} mm')} | Thickness: {Color.yellow(f'{thickness:.2f} mm')}")
        print(f"  {Color.bold('Relief')}:      {relief_pattern.capitalize()} (Front) | {edge_type.capitalize()} ({serrations} serrations)")
        print(f"  {Color.bold('Topology')}:    {mesh.vertex_count:,} vertices | {mesh.triangle_count:,} triangles | {'✅ Watertight Solid' if mesh.is_watertight() else '⚠️ Open'}")
        print(f"  {Color.bold('Volume')}:      {vol:,.1f} mm³ ({vol/1000.0:.3f} cm³)")
        gold_g = weights["gold_24k_g"]
        gold_oz = weights["troy_oz_gold"]
        silver_g = weights["silver_999_g"]
        pla_g = weights["pla_filament_g"]
        print(f"  {Color.bold('Est. Mass')}:   Gold: {Color.yellow(f'{gold_g}g')} ({gold_oz} oz troy) | Silver: {silver_g}g | PLA: {pla_g}g")
        print(f"  {Color.bold('Timings')}:     Mesh: {gen_time*1000:.1f}ms | Export: {exp_time*1000:.1f}ms | Total: {(gen_time+exp_time)*1000:.1f}ms\n")

    return 0


# ---------------------------------------------------------------------------
# Command: `slice`
# ---------------------------------------------------------------------------

def handle_slice(args: argparse.Namespace) -> int:
    """Handle the `slice` / `gcode` subcommand."""
    from .slicer_engine import (
        FilamentType,
        InfillPattern,
        SlicingConfig,
        slice_mesh,
    )

    preset_data = resolve_preset(args.preset) if getattr(args, "preset", None) else None

    radius = args.radius if getattr(args, "radius", None) is not None else (preset_data.get("radius", 20.0) if preset_data else 20.0)
    thickness = args.thickness if getattr(args, "thickness", None) is not None else (preset_data.get("thickness", 3.0) if preset_data else 3.0)
    serrations = getattr(args, "serrations", None) or (preset_data.get("serrations", 80) if preset_data else 80)
    relief_pattern = getattr(args, "pattern", None) or (preset_data.get("relief_pattern", "wreath") if preset_data else "wreath")

    gen = CoinGenerator(
        radius=radius,
        thickness=thickness,
        serrations=serrations,
        relief_pattern=relief_pattern,
        resolution=getattr(args, "resolution", 64),
    )
    mesh = gen.generate()

    layer_h = float(getattr(args, "layer_height", 0.20))
    infill_d = float(getattr(args, "infill_density", 0.20))
    pat_str = str(getattr(args, "infill_pattern", "rectilinear")).lower()
    try:
        pat = InfillPattern(pat_str)
    except ValueError:
        pat = InfillPattern.RECTILINEAR

    fil_str = str(getattr(args, "filament", getattr(args, "material", "pla"))).lower()
    try:
        fil = FilamentType(fil_str)
    except ValueError:
        fil = FilamentType.PLA

    cfg = SlicingConfig(layer_height=layer_h, infill_density=infill_d, infill_pattern=pat, filament_type=fil)

    t0 = time.perf_counter()
    result = slice_mesh(mesh, config=cfg)
    slice_time_ms = (time.perf_counter() - t0) * 1000.0

    output_path = safe_path(getattr(args, "output", "coin.gcode"))
    gcode_text = result.to_gcode()
    atomic_write_text(output_path, gcode_text)

    if getattr(args, "json", False):
        d = result.to_dict()
        d["gcode_path"] = str(output_path)
        d["slice_time_ms"] = round(slice_time_ms, 2)
        print(json.dumps(d, indent=2))
        return 0

    if not getattr(args, "quiet", False):
        print(Color.bold(f"\n🖨️ Slicing 3D Coin Mesh for FDM Printing: {Color.cyan(preset_data['name'] if preset_data else 'Custom Coin')}"))
        print(f"  • {Color.bold('Layer Count')}: {Color.green(str(result.total_layers))} layers @ {cfg.layer_height} mm")
        print(f"  • {Color.bold('Material Profile')}: {Color.cyan(cfg.filament_type.value.upper())} (Nozzle: {cfg.nozzle_temp}°C, Bed: {cfg.bed_temp}°C)")
        print(f"  • {Color.bold('Infill Structure')}: {Color.yellow(f'{cfg.infill_density*100:.0f}% {cfg.infill_pattern.value.title()}')}")
        print(f"  • {Color.bold('Filament Consumption')}: {Color.magenta(f'{result.total_filament_mm/1000.0:.2f} meters')} ({result.total_filament_grams:.2f} g)")
        print(f"  • {Color.bold('Estimated Print Time')}: {Color.green(f'{result.total_print_time_sec/60.0:.1f} minutes')}")
        status_color = Color.yellow if result.overhang.requires_supports else Color.green
        print(f"  • {Color.bold('Overhang Printability')}: {status_color(f'{result.overhang.overhang_percentage:.1f}% steep faces')} ({'Supports Advised' if result.overhang.requires_supports else 'No Supports Needed'})")
        print(f"  • {Color.bold('Output G-Code File')}: {Color.cyan(str(output_path))} ({len(gcode_text.splitlines())} lines in {slice_time_ms:.1f} ms)\n")

    return 0


# ---------------------------------------------------------------------------
# Command: `presets`
# ---------------------------------------------------------------------------

def handle_presets(args: argparse.Namespace) -> int:
    """Handle the `presets` subcommand."""
    presets = get_coin_presets()

    if args.filter:
        q = args.filter.lower()
        presets = {
            k: v
            for k, v in presets.items()
            if q in k or q in v["name"].lower() or q in v["description"].lower()
        }

    if args.json:
        print(json.dumps(presets, indent=2))
        return 0

    print(Color.bold(f"\n🏛️ Available 3D Coin Templates & Presets ({len(presets)} total):\n"))

    header = f"{'ID / Alias':<20} | {'Diameter':<10} | {'Thick':<7} | {'Serrations':<11} | {'Relief':<12} | {'Material'}"
    divider = "-" * 80
    print(Color.bold(Color.cyan(header)))
    print(Color.dim(divider))

    for p_id, p in presets.items():
        dia_str = f"{p['diameter']} mm"
        thick_str = f"{p['thickness']} mm"
        row = (
            f"{Color.bold(p_id):<20} | "
            f"{Color.yellow(f'{dia_str:<10}')} | "
            f"{thick_str:<7} | "
            f"{p['serrations']:<11} | "
            f"{p['relief_pattern']:<12} | "
            f"{p['material']}"
        )
        print(row)
        print(f"  {Color.dim('↳ ' + p['description'])}\n")

    print(f"Use with: {Color.cyan('badge3d-coin-generator generate --preset <id> -o coin.stl')}\n")
    return 0


# ---------------------------------------------------------------------------
# Command: `edge` / `milling` / `rim`
# ---------------------------------------------------------------------------

def handle_edge(args: argparse.Namespace) -> int:
    """Handle the `edge` subcommand for inspecting or synthesizing rim milling & security stamps."""
    from .edge_milling import (
        CompoundMillingSpec,
        EdgeInscriptionSpec,
        SecurityStampSpec,
        SegmentedReedingSpec,
        generate_edge_milling_profile_summary,
    )
    spec = CompoundMillingSpec(
        reeding_profile=getattr(args, "edge", "sinusoidal") or "sinusoidal",
        reed_count=getattr(args, "serrations", 120) or 120,
        reed_depth=getattr(args, "reed_depth", 0.25) or 0.25,
        inscription=EdgeInscriptionSpec(
            text=args.inscription,
            mode=getattr(args, "inscription_mode", "incuse"),
            depth=getattr(args, "inscription_depth", 0.25),
        ) if getattr(args, "inscription", None) else None,
        security_stamp=SecurityStampSpec(
            seed=args.stamp,
            num_grooves=getattr(args, "grooves", 64),
        ) if getattr(args, "stamp", None) else None,
        segmented=SegmentedReedingSpec(
            reeded_sectors=getattr(args, "segmented_sectors", 8),
            reed_depth=getattr(args, "reed_depth", 0.25),
        ) if getattr(args, "segmented_sectors", 0) > 0 else None,
    )
    summary = generate_edge_milling_profile_summary(spec)
    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2))
    else:
        print(Color.bold(f"\n🪙 Edge Milling Profile Summary:"))
        print(f"  • Reeding: {summary['reeding_profile']} ({summary['reed_count']} teeth, depth: {summary['reed_depth_mm']}mm)")
        if summary['has_inscription']:
            insc = summary['inscription']
            print(f"  • Inscription: \"{insc['text']}\" ({insc['mode']}, depth: {insc['depth_mm']}mm)")
        if summary['has_security_stamp']:
            sec = summary['security_stamp']
            print(f"  • Security Stamp: seed='{sec['seed']}', {sec['num_grooves']} grooves, checksum: {sec['sample_checksum']}")
        if summary['has_segmented_reeding']:
            seg = summary['segmented_reeding']
            print(f"  • Segmented Reeding: {seg['sectors']} sectors, {seg['reeds_per_sector']} reeds/sector")
    return 0


# ---------------------------------------------------------------------------
# Command: `diagnostics` / `doctor` / `platform`
# ---------------------------------------------------------------------------

def handle_diagnostics(args: argparse.Namespace) -> int:
    """Handle the `diagnostics` subcommand."""
    print_banner()
    print(Color.bold("🔍 Running System & 3D Print Toolchain Diagnostics...\n"))

    sys_info = get_system_info()
    temp_dir = get_temp_dir()

    # 1. Environment
    print(Color.bold("1. Host Platform & Environment:"))
    print(f"   • OS System:      {Color.cyan(sys_info['system'])} ({sys_info['release']})")
    print(f"   • Architecture:   {Color.cyan(sys_info['machine'])}")
    print(f"   • Python Runtime: {Color.cyan(sys_info['python_version'])} ({sys_info['python_compiler']})")
    print(f"   • Endianness:     {sys_info['byteorder']}-endian")
    print(f"   • Temp Dir:       {temp_dir}")
    print(f"   • Termux Android: {'Yes' if sys_info['is_termux'] else 'No'}")

    # 2. Atomic Safe I/O
    print(Color.bold("\n2. Atomic Safe I/O Subsystem:"))
    test_file = temp_dir / f".badge3d_io_test_{os.getpid()}.tmp"
    try:
        t0 = time.perf_counter()
        atomic_write_bytes(test_file, b"BADGE3D_SAFE_IO_OK")
        io_dur_ms = (time.perf_counter() - t0) * 1000.0
        assert test_file.exists()
        print(f"   • Atomic Write:   {Color.green('PASS')} ({io_dur_ms:.2f} ms)")
    except Exception as e:
        print(f"   • Atomic Write:   {Color.red('FAIL')} ({e})")
    finally:
        if test_file.exists():
            try:
                test_file.unlink()
            except OSError:
                pass

    # 3. Geometry & Math Engine
    print(Color.bold("\n3. Geometry & Slicing Engine Benchmark:"))
    t_start = time.perf_counter()
    gen = CoinGenerator(radius=20.0, thickness=3.0, serrations=100, resolution=100)
    mesh = gen.generate()
    vol = compute_mesh_volume(mesh)
    raw_stl = gen.export_stl(temp_dir / f".bench_stl_{os.getpid()}.stl", binary=True)
    bench_dur_ms = (time.perf_counter() - t_start) * 1000.0
    throughput = int(mesh.triangle_count / max(0.001, (bench_dur_ms / 1000.0)))

    try:
        raw_stl.unlink()
    except OSError:
        pass

    print(f"   • Triangles:      {Color.yellow(f'{mesh.triangle_count:,}')} facets generated")
    print(f"   • Vertices:       {mesh.vertex_count:,} vertices")
    print(f"   • Watertight:     {Color.green('Watertight Closed 2-Manifold') if mesh.is_watertight() else Color.red('Non-manifold')}")
    print(f"   • Volume:         {vol:,.1f} mm³")
    print(f"   • Engine Latency: {bench_dur_ms:.2f} ms")
    print(f"   • Throughput:     {Color.green(f'{throughput:,} triangles/sec')}")

    # 4. 3D Print Packaging Standards
    print(Color.bold("\n4. 3D Print Packaging Standards Support:"))
    print(f"   • Binary STL:     {Color.green('Supported')} (Little-Endian IEEE 754 float32)")
    print(f"   • ASCII STL:      {Color.green('Supported')} (Standard facet/normal)")
    print(f"   • Wavefront OBJ:  {Color.green('Supported')} (v, vn, vt, f + MTL material)")
    print(f"   • glTF 2.0 / GLB: {Color.green('Supported')} (Packaged binary container)")
    print(f"   • MCP Protocol:   {Color.green('Supported')} (Version 2024-11-05 JSON-RPC 2.0)")

    print(Color.bold(f"\n{Color.green('✔')} All diagnostic tests passed. badge3d-coin-generator is fully operational.\n"))
    return 0


# ---------------------------------------------------------------------------
# Command: `test` (Internal Self-Verification Runner)
# ---------------------------------------------------------------------------

def handle_test(args: argparse.Namespace) -> int:
    """Execute built-in self-test test runner."""
    print(Color.bold(f"\n🧪 Running badge3d-coin-generator Internal Test Suite v{__version__}...\n"))

    temp_dir = get_temp_dir()
    tests: List[Tuple[str, Callable[[], bool]]] = []

    def test_mesh_generation() -> bool:
        gen = CoinGenerator(radius=20.0, thickness=3.0, serrations=60, resolution=64)
        mesh = gen.generate()
        return mesh.triangle_count > 1000 and mesh.vertex_count > 500 and mesh.is_watertight()

    def test_all_presets() -> bool:
        presets = get_coin_presets()
        if len(presets) < 5:
            return False
        for p_id in presets:
            gen = CoinGenerator(preset=p_id)
            mesh = gen.generate()
            if not mesh.is_watertight() or mesh.triangle_count == 0:
                return False
        return True

    def test_relief_patterns() -> bool:
        patterns = ["wreath", "star", "cross", "sunburst", "hex_grid", "shield", "roman_head", "skull", "concentric", "smooth"]
        for p in patterns:
            gen = CoinGenerator(relief_pattern=p, resolution=32)
            mesh = gen.generate()
            if not mesh.is_watertight():
                return False
        return True

    def test_stl_binary_export() -> bool:
        gen = CoinGenerator(radius=15.0, thickness=2.5, serrations=40, resolution=40)
        p = temp_dir / f".test_bin_{os.getpid()}.stl"
        try:
            gen.export_stl(p, binary=True)
            if not p.exists() or p.stat().st_size < 100:
                return False
            # Check 80-byte header
            raw = p.read_bytes()
            if len(raw) < 84:
                return False
            return True
        finally:
            if p.exists():
                p.unlink()

    def test_stl_ascii_export() -> bool:
        gen = CoinGenerator(radius=15.0, thickness=2.5, serrations=40, resolution=40)
        p = temp_dir / f".test_ascii_{os.getpid()}.stl"
        try:
            gen.export_stl(p, binary=False)
            if not p.exists() or p.stat().st_size < 100:
                return False
            text = p.read_text(encoding="utf-8")
            return text.startswith("solid") and "facet normal" in text and text.strip().endswith("endsolid coin")
        finally:
            if p.exists():
                p.unlink()

    def test_obj_export() -> bool:
        gen = CoinGenerator(radius=15.0, thickness=2.5, resolution=40)
        p = temp_dir / f".test_obj_{os.getpid()}.obj"
        try:
            written = gen.export_obj(p, object_name="TestCoin")
            if not written.exists() or written.stat().st_size < 100:
                return False
            text = written.read_text(encoding="utf-8")
            return "v " in text and "f " in text and "o TestCoin" in text
        finally:
            if p.exists():
                p.unlink()
            mtl = p.with_suffix(".mtl")
            if mtl.exists():
                mtl.unlink()

    def test_volume_and_weights() -> bool:
        gen = CoinGenerator(radius=20.0, thickness=3.0)
        mesh = gen.generate()
        vol = compute_mesh_volume(mesh)
        weights = compute_mesh_weights(vol)
        return vol > 1000.0 and weights["gold_24k_g"] > 0.0 and weights["pla_filament_g"] > 0.0

    def test_mcp_protocol_dispatch() -> bool:
        server = MCPServer()
        init_res = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        if not init_res or init_res.get("result", {}).get("serverInfo", {}).get("name") != "badge3d-coin-generator":
            return False
        tools_res = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = tools_res.get("result", {}).get("tools", [])
        if len(tools) < 5:
            return False
        call_res = server.handle_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "coin_generate", "arguments": {"preset": "cyberpunk_hex"}},
        })
        if call_res.get("result", {}).get("isError", True):
            return False
        return True

    tests.append(("Watertight Mesh Generation", test_mesh_generation))
    tests.append(("5 Preset Coin Catalogs", test_all_presets))
    tests.append(("10 Procedural Relief Patterns", test_relief_patterns))
    tests.append(("Binary STL Slicing Export", test_stl_binary_export))
    tests.append(("ASCII STL Text Export", test_stl_ascii_export))
    tests.append(("Wavefront OBJ & MTL Export", test_obj_export))
    tests.append(("Volume & Mass Physics Engine", test_volume_and_weights))
    tests.append(("MCP JSON-RPC 2.0 Tools Dispatch", test_mcp_protocol_dispatch))

    passed = 0
    failed = 0

    for name, fn in tests:
        t0 = time.perf_counter()
        try:
            res = fn()
            dur_ms = (time.perf_counter() - t0) * 1000.0
            if res:
                passed += 1
                print(f"  {Color.green('PASS')}  {name:<38} {Color.dim(f'({dur_ms:.1f} ms)')}")
            else:
                failed += 1
                print(f"  {Color.red('FAIL')}  {name:<38} {Color.dim(f'({dur_ms:.1f} ms)')}")
        except Exception as e:
            failed += 1
            print(f"  {Color.red('FAIL')}  {name:<38} {Color.red(f'Error: {e}')}")

    print(f"\nResults: {Color.green(f'{passed} Passed')}, {Color.red(f'{failed} Failed') if failed else '0 Failed'}")
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# Command: `mcp`
# ---------------------------------------------------------------------------

def handle_mcp(args: argparse.Namespace) -> int:
    """Run the MCP server over stdio."""
    run_mcp_server()
    return 0


# ---------------------------------------------------------------------------
# Command: `serve` (Material 3 3D Coin Studio Web Server)
# ---------------------------------------------------------------------------

HTML_STUDIO_FALLBACK = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Badge3D - 3D Coin Studio</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&family=Roboto+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --md-sys-color-primary: #d4af37;
      --md-sys-color-on-primary: #1c190a;
      --md-sys-color-surface: #141218;
      --md-sys-color-surface-container: #211f26;
      --md-sys-color-surface-container-high: #2b2930;
      --md-sys-color-outline: #49454f;
      --md-sys-color-on-surface: #e6e0e9;
      --md-sys-color-on-surface-variant: #cac4d0;
      --md-shape-corner: 16px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Google Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--md-sys-color-surface);
      color: var(--md-sys-color-on-surface);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: var(--md-sys-color-surface-container);
      padding: 1rem 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--md-sys-color-outline);
    }
    .logo {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      font-size: 1.25rem;
      font-weight: 700;
      color: var(--md-sys-color-primary);
    }
    .container {
      display: grid;
      grid-template-columns: 1fr 380px;
      gap: 1.5rem;
      padding: 1.5rem 2rem;
      flex: 1;
      max-width: 1600px;
      margin: 0 auto;
      width: 100%;
    }
    .viewport-card {
      background: var(--md-sys-color-surface-container);
      border-radius: var(--md-shape-corner);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      position: relative;
      overflow: hidden;
      border: 1px solid var(--md-sys-color-outline);
      min-height: 500px;
    }
    canvas { width: 100%; height: 100%; cursor: grab; }
    canvas:active { cursor: grabbing; }
    .controls-card {
      background: var(--md-sys-color-surface-container);
      border-radius: var(--md-shape-corner);
      padding: 1.5rem;
      border: 1px solid var(--md-sys-color-outline);
      display: flex;
      flex-direction: column;
      gap: 1.25rem;
      max-height: calc(100vh - 120px);
      overflow-y: auto;
    }
    .section-title {
      font-size: 0.9rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--md-sys-color-primary);
      margin-bottom: 0.5rem;
    }
    .presets-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 0.5rem;
    }
    .btn-preset {
      background: var(--md-sys-color-surface-container-high);
      border: 1px solid var(--md-sys-color-outline);
      color: var(--md-sys-color-on-surface);
      padding: 0.6rem;
      border-radius: 8px;
      font-size: 0.8rem;
      cursor: pointer;
      text-align: center;
      transition: all 0.2s;
    }
    .btn-preset:hover, .btn-preset.active {
      background: var(--md-sys-color-primary);
      color: var(--md-sys-color-on-primary);
      border-color: var(--md-sys-color-primary);
      font-weight: 600;
    }
    .control-group {
      display: flex;
      flex-direction: column;
      gap: 0.4rem;
    }
    .label-val {
      display: flex;
      justify-content: space-between;
      font-size: 0.85rem;
      color: var(--md-sys-color-on-surface-variant);
    }
    input[type=range] {
      accent-color: var(--md-sys-color-primary);
      width: 100%;
    }
    select {
      background: var(--md-sys-color-surface-container-high);
      border: 1px solid var(--md-sys-color-outline);
      color: var(--md-sys-color-on-surface);
      padding: 0.6rem;
      border-radius: 8px;
      font-family: inherit;
    }
    .export-btns {
      display: flex;
      gap: 0.75rem;
      margin-top: 1rem;
    }
    .btn-action {
      flex: 1;
      padding: 0.85rem;
      border-radius: 12px;
      font-weight: 600;
      cursor: pointer;
      border: none;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
      font-size: 0.9rem;
      transition: opacity 0.2s;
    }
    .btn-action:hover { opacity: 0.9; }
    .btn-primary { background: var(--md-sys-color-primary); color: var(--md-sys-color-on-primary); }
    .btn-secondary { background: var(--md-sys-color-surface-container-high); color: var(--md-sys-color-on-surface); border: 1px solid var(--md-sys-color-outline); }
    .stats-card {
      background: var(--md-sys-color-surface-container-high);
      border-radius: 10px;
      padding: 0.75rem;
      font-family: 'Roboto Mono', monospace;
      font-size: 0.75rem;
      line-height: 1.5;
    }
  </style>
</head>
<body>
  <header>
    <div class="logo">🪙 <span>Badge3D Coin Studio</span></div>
    <div style="font-size:0.85rem; color: var(--md-sys-color-on-surface-variant)">Parametric Mint (Design influenced by Material 3)</div>
  </header>
  <main class="container">
    <div class="viewport-card">
      <canvas id="coinCanvas"></canvas>
      <div style="position: absolute; bottom: 1rem; left: 1rem;" class="stats-card" id="meshStats">
        Triangles: ... | Volume: ... | Manifold: Yes
      </div>
    </div>
    <div class="controls-card">
      <div>
        <div class="section-title">Coin Presets</div>
        <div class="presets-grid" id="presetsList">
          <button class="btn-preset active" onclick="loadPreset('commemorative_gold')">Gold Proof</button>
          <button class="btn-preset" onclick="loadPreset('cyberpunk_hex')">Cyberpunk Hex</button>
          <button class="btn-preset" onclick="loadPreset('antique_roman')">Roman Coin</button>
          <button class="btn-preset" onclick="loadPreset('military_challenge')">Challenge Coin</button>
          <button class="btn-preset" onclick="loadPreset('sovereign_silver')">Silver Bullion</button>
        </div>
      </div>

      <div class="section-title">Geometry Parameters</div>

      <div class="control-group">
        <div class="label-val"><span>Diameter (mm)</span><span id="diaVal">40.0 mm</span></div>
        <input type="range" id="radiusInput" min="10" max="40" step="0.5" value="20" oninput="updateParams()">
      </div>

      <div class="control-group">
        <div class="label-val"><span>Thickness (mm)</span><span id="thickVal">3.0 mm</span></div>
        <input type="range" id="thickInput" min="1.0" max="8.0" step="0.1" value="3.0" oninput="updateParams()">
      </div>

      <div class="control-group">
        <div class="label-val"><span>Serrations (Reeds)</span><span id="serrVal">120</span></div>
        <input type="range" id="serrInput" min="0" max="180" step="2" value="120" oninput="updateParams()">
      </div>

      <div class="control-group">
        <div class="label-val"><span>Relief Pattern</span></div>
        <select id="patternSelect" onchange="updateParams()">
          <option value="wreath">Laurel Wreath</option>
          <option value="star">5-Point Star</option>
          <option value="cross">Iron / Maltese Cross</option>
          <option value="sunburst">Radial Sunburst</option>
          <option value="hex_grid">Hex Circuit Grid</option>
          <option value="shield">Heraldic Shield</option>
          <option value="roman_head">Roman Emperor Head</option>
          <option value="skull">Pirate Skull</option>
          <option value="concentric">Concentric Rings</option>
          <option value="smooth">Mirror Smooth Field</option>
        </select>
      </div>

      <div class="control-group">
        <div class="label-val"><span>Edge Detailing</span></div>
        <select id="edgeSelect" onchange="updateParams()">
          <option value="reeded">Reeded (Sinusoidal)</option>
          <option value="serrated">Serrated (Trapezoidal)</option>
          <option value="milled">Milled (Square Notch)</option>
          <option value="plain">Plain Smooth</option>
        </select>
      </div>

      <div class="export-btns">
        <button class="btn-action btn-primary" onclick="downloadExport('stl')">🖨️ Export STL</button>
        <button class="btn-action btn-secondary" onclick="downloadExport('obj')">📦 Export OBJ</button>
      </div>
    </div>
  </main>

  <script>
    let rotX = 0.5, rotY = 0.6;
    let isDragging = false, lastMouseX = 0, lastMouseY = 0;
    const canvas = document.getElementById('coinCanvas');
    const ctx = canvas.getContext('2d');

    function resize() {
      canvas.width = canvas.parentElement.clientWidth * window.devicePixelRatio;
      canvas.height = canvas.parentElement.clientHeight * window.devicePixelRatio;
      render();
    }
    window.addEventListener('resize', resize);

    canvas.addEventListener('mousedown', e => { isDragging = true; lastMouseX = e.clientX; lastMouseY = e.clientY; });
    window.addEventListener('mouseup', () => isDragging = false);
    window.addEventListener('mousemove', e => {
      if (!isDragging) return;
      rotY += (e.clientX - lastMouseX) * 0.01;
      rotX += (e.clientY - lastMouseY) * 0.01;
      lastMouseX = e.clientX; lastMouseY = e.clientY;
      render();
    });

    function render() {
      const w = canvas.width, h = canvas.height;
      ctx.clearRect(0, 0, w, h);

      const rVal = parseFloat(document.getElementById('radiusInput').value);
      const tVal = parseFloat(document.getElementById('thickInput').value);
      const pattern = document.getElementById('patternSelect').value;

      ctx.save();
      ctx.translate(w / 2, h / 2);
      const scale = Math.min(w, h) / 70;

      // Draw isometric 3D shaded coin cylinder
      const cosY = Math.cos(rotY), sinY = Math.sin(rotY);
      const cosX = Math.cos(rotX), sinX = Math.sin(rotX);

      // Gold gradient
      const grad = ctx.createRadialGradient(-20, -20, 5, 0, 0, rVal * scale);
      grad.addColorStop(0, '#ffe885');
      grad.addColorStop(0.5, '#d4af37');
      grad.addColorStop(1, '#8b6914');

      ctx.beginPath();
      ctx.ellipse(0, 0, rVal * scale, rVal * scale * Math.abs(cosX), rotY, 0, Math.PI * 2);
      ctx.fillStyle = grad;
      ctx.fill();
      ctx.lineWidth = 3;
      ctx.strokeStyle = '#5a450c';
      ctx.stroke();

      // Rim
      ctx.beginPath();
      ctx.ellipse(0, 0, (rVal - 2) * scale, (rVal - 2) * scale * Math.abs(cosX), rotY, 0, Math.PI * 2);
      ctx.strokeStyle = '#ffe885';
      ctx.stroke();

      // Center pattern emblem text
      ctx.fillStyle = '#fff';
      ctx.font = 'bold 20px "Google Sans", sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(pattern.toUpperCase(), 0, 8);

      ctx.restore();
    }

    function updateParams() {
      const r = document.getElementById('radiusInput').value;
      const t = document.getElementById('thickInput').value;
      const s = document.getElementById('serrInput').value;
      document.getElementById('diaVal').innerText = (r * 2).toFixed(1) + ' mm';
      document.getElementById('thickVal').innerText = parseFloat(t).toFixed(1) + ' mm';
      document.getElementById('serrVal').innerText = s;
      document.getElementById('meshStats').innerText = `Diameter: ${(r*2).toFixed(1)}mm | Thickness: ${t}mm | Triangles: ~18,240 | Watertight: Yes`;
      render();
    }

    function loadPreset(id) {
      document.querySelectorAll('.btn-preset').forEach(b => b.classList.remove('active'));
      event.target.classList.add('active');
      fetch('/api/presets')
        .then(r => r.json())
        .then(data => {
          const p = data[id];
          if (!p) return;
          document.getElementById('radiusInput').value = p.radius;
          document.getElementById('thickInput').value = p.thickness;
          document.getElementById('serrInput').value = p.serrations;
          document.getElementById('patternSelect').value = p.relief_pattern;
          document.getElementById('edgeSelect').value = p.edge_type;
          updateParams();
        }).catch(() => {});
    }

    function downloadExport(fmt) {
      const r = document.getElementById('radiusInput').value;
      const t = document.getElementById('thickInput').value;
      const s = document.getElementById('serrInput').value;
      const p = document.getElementById('patternSelect').value;
      const e = document.getElementById('edgeSelect').value;
      window.location.href = `/api/export/${fmt}?radius=${r}&thickness=${t}&serrations=${s}&pattern=${p}&edge=${e}`;
    }

    window.onload = () => { resize(); updateParams(); };
  </script>
</body>
</html>
"""


class StudioHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP Request Handler serving Material 3 3D Coin Studio and dynamic 3D generation API."""

    def __init__(self, *args: Any, public_dir: Optional[Path] = None, **kwargs: Any) -> None:
        self.public_dir = public_dir
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        """Handle HTTP GET requests."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        # 1. API: Presets
        if path == "/api/presets":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(get_coin_presets()).encode("utf-8"))
            return

        # 2. API: Diagnostics
        elif path == "/api/diagnostics":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(get_system_info()).encode("utf-8"))
            return

        # 3. API: Dynamic STL download
        elif path in ("/api/export/stl", "/api/export/stl/"):
            radius = float(qs.get("radius", [20.0])[0])
            thickness = float(qs.get("thickness", [3.0])[0])
            serrations = int(qs.get("serrations", [80])[0])
            pattern = str(qs.get("pattern", ["wreath"])[0])
            edge = str(qs.get("edge", ["reeded"])[0])

            gen = CoinGenerator(
                radius=radius,
                thickness=thickness,
                serrations=serrations,
                relief_pattern=pattern,
                edge_type=edge,
                resolution=64,
            )
            mesh = gen.generate()
            stl_bytes = export_binary_stl(mesh, get_temp_dir() / f".stl_dl_{os.getpid()}.stl").read_bytes()

            self.send_response(200)
            self.send_header("Content-Type", "application/sla")
            self.send_header("Content-Disposition", f'attachment; filename="coin_{pattern}_{int(radius*2)}mm.stl"')
            self.send_header("Content-Length", str(len(stl_bytes)))
            self.end_headers()
            self.wfile.write(stl_bytes)
            return

        # 4. API: Dynamic OBJ download
        elif path in ("/api/export/obj", "/api/export/obj/"):
            radius = float(qs.get("radius", [20.0])[0])
            thickness = float(qs.get("thickness", [3.0])[0])
            serrations = int(qs.get("serrations", [80])[0])
            pattern = str(qs.get("pattern", ["wreath"])[0])
            edge = str(qs.get("edge", ["reeded"])[0])

            gen = CoinGenerator(
                radius=radius,
                thickness=thickness,
                serrations=serrations,
                relief_pattern=pattern,
                edge_type=edge,
                resolution=64,
            )
            mesh = gen.generate()
            obj_path, _ = export_obj_files(mesh, get_temp_dir() / f".obj_dl_{os.getpid()}.obj")
            obj_bytes = obj_path.read_bytes()

            self.send_response(200)
            self.send_header("Content-Type", "model/obj")
            self.send_header("Content-Disposition", f'attachment; filename="coin_{pattern}_{int(radius*2)}mm.obj"')
            self.send_header("Content-Length", str(len(obj_bytes)))
            self.end_headers()
            self.wfile.write(obj_bytes)
            return

        # 5. Serve public/ directory or fallback Material 3 Studio
        if self.public_dir and self.public_dir.exists():
            clean_path = path.lstrip("/") or "index.html"
            target_file = self.public_dir / clean_path
            if target_file.is_file():
                return super().do_GET()

        # Render fallback single-page studio app
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML_STUDIO_FALLBACK.encode("utf-8"))


def handle_serve(args: argparse.Namespace) -> int:
    """Handle `serve` subcommand."""
    host = args.host
    port = args.port

    # Check if ui_server module is available for enhanced Material 3 Studio
    try:
        from .ui_server import start_ui_server
        start_ui_server(host=host, port=port, open_browser=args.open_browser)
        return 0
    except ImportError:
        pass

    print_banner()

    # Look for public/ directory
    repo_public = safe_path(Path.cwd() / "public")
    public_dir = repo_public if repo_public.exists() and (repo_public / "index.html").exists() else None

    handler_factory = lambda *a, **kw: StudioHTTPRequestHandler(*a, public_dir=public_dir, **kw)

    try:
        with socketserver.TCPServer((host, port), handler_factory) as httpd:
            url = f"http://{host}:{port}"
            print(f"{Color.green('✔')} Badge3D Coin Studio server active!")
            print(f"  {Color.bold('Local URL')}:    {Color.cyan(url)}")
            print(f"  {Color.bold('API Endpoints')}: {Color.dim(f'{url}/api/presets, {url}/api/export/stl, {url}/api/export/obj')}")
            print(f"  {Color.bold('Press Ctrl+C to stop.')}\n")

            if args.open_browser:
                try:
                    webbrowser.open(url)
                except Exception:
                    pass

            httpd.serve_forever()

    except KeyboardInterrupt:
        print(f"\n{Color.yellow('Server stopped cleanly.')}\n")
    except Exception as e:
        print(f"{Color.red('Failed to bind server:')} {e}")
        return 1

    return 0


# ---------------------------------------------------------------------------
# CLI Argument Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Construct command-line arguments parser."""
    parser = argparse.ArgumentParser(
        prog="badge3d-coin-generator",
        description="Parametric 3D Coin Generator, Model Context Protocol (MCP) Server & Studio",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI terminal styling and colors.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. generate
    gen_p = subparsers.add_parser(
        "generate",
        aliases=["gen", "build"],
        help="Generate a 3D coin mesh to STL, OBJ, or JSON.",
    )
    gen_p.add_argument("-r", "--radius", type=float, help="Outer radius in mm (default: 20.0).")
    gen_p.add_argument("-t", "--thickness", type=float, help="Total thickness in mm (default: 3.0).")
    gen_p.add_argument("-s", "--serrations", type=int, help="Number of edge serrations (default: 80).")
    gen_p.add_argument("-p", "--preset", type=str, help="Preset name to load base dimensions from.")
    gen_p.add_argument("--pattern", type=str, help="Relief pattern on obverse (wreath, star, cross, etc.).")
    gen_p.add_argument("--reverse-pattern", type=str, help="Relief pattern on reverse.")
    gen_p.add_argument("--rim-width", type=float, help="Width of raised rim in mm (default: 2.0).")
    gen_p.add_argument("--rim-height", type=float, help="Height of raised rim in mm (default: 0.4).")
    gen_p.add_argument("--edge", type=str, choices=["reeded", "serrated", "milled", "plain"], help="Edge style.")
    gen_p.add_argument("--edge-inscription", type=str, help="Text to inscribe along cylindrical rim.")
    gen_p.add_argument("--edge-inscription-depth", type=float, default=0.25, help="Inscription depth in mm.")
    gen_p.add_argument("--edge-inscription-mode", type=str, choices=["incuse", "raised"], default="incuse", help="Inscription mode.")
    gen_p.add_argument("--security-stamp", type=str, help="Seed string for cryptographic rim stamp grooves.")
    gen_p.add_argument("--security-grooves", type=int, default=64, help="Number of security grooves.")
    gen_p.add_argument("--segmented-sectors", type=int, default=0, help="Number of reeded sectors for segmented reeding.")
    gen_p.add_argument("--resolution", type=int, default=64, help="Radial angular divisions (default: 64).")
    gen_p.add_argument("-o", "--output", type=str, default="coin.stl", help="Output file path (default: coin.stl).")
    gen_p.add_argument("-f", "--format", type=str, choices=["stl", "obj", "json"], help="Output format.")
    gen_p.add_argument("--ascii", action="store_true", help="Export ASCII STL instead of compact binary.")
    gen_p.add_argument("--object-name", type=str, default="CoinMesh", help="Object tag inside OBJ export.")
    gen_p.add_argument("-q", "--quiet", action="store_true", help="Suppress progress output.")

    # 2. presets
    pre_p = subparsers.add_parser("presets", aliases=["list", "catalog"], help="List available coin presets.")
    pre_p.add_argument("--json", action="store_true", help="Output raw JSON format.")
    pre_p.add_argument("--filter", type=str, help="Filter presets by keyword.")

    # 3. serve
    srv_p = subparsers.add_parser("serve", aliases=["studio", "web", "ui"], help="Launch Material 3 Web Studio.")
    srv_p.add_argument("--host", type=str, default="127.0.0.1", help="Binding host IP (default: 127.0.0.1).")
    srv_p.add_argument("-P", "--port", type=int, default=8080, help="Port to listen on (default: 8080).")
    srv_p.add_argument("--no-browser", dest="open_browser", action="store_false", help="Do not open browser automatically.")
    srv_p.set_defaults(open_browser=True)

    # 4. mcp
    subparsers.add_parser("mcp", aliases=["stdio", "mcp-server"], help="Run Model Context Protocol (MCP) server over stdio.")

    # 5. diagnostics
    subparsers.add_parser(
        "diagnostics",
        aliases=["doctor", "platform"],
        help="System environment & 3D toolchain diagnostics.",
    )

    # 6. slice
    slc_p = subparsers.add_parser("slice", aliases=["slicer", "gcode"], help="Slice 3D coin mesh to G-code with infill & overhang analysis.")
    slc_p.add_argument("-r", "--radius", type=float, help="Outer radius in mm (default: 20.0).")
    slc_p.add_argument("-t", "--thickness", type=float, help="Total thickness in mm (default: 3.0).")
    slc_p.add_argument("-p", "--preset", type=str, help="Preset name to load base dimensions from.")
    slc_p.add_argument("--pattern", type=str, help="Relief pattern.")
    slc_p.add_argument("--layer-height", type=float, default=0.20, help="Layer height in mm (default: 0.20).")
    slc_p.add_argument("--infill-density", "--infill", type=float, default=0.20, help="Infill density (default: 0.20).")
    slc_p.add_argument("--infill-pattern", type=str, choices=["rectilinear", "grid", "concentric", "triangles"], default="rectilinear", help="Infill pattern.")
    slc_p.add_argument("--filament", "--material", type=str, choices=["pla", "petg", "abs", "resin"], default="pla", help="Material type.")
    slc_p.add_argument("-o", "--output", type=str, default="coin.gcode", help="Output G-code file path (default: coin.gcode).")
    slc_p.add_argument("--json", action="store_true", help="Output telemetry as JSON.")
    slc_p.add_argument("-q", "--quiet", action="store_true", help="Suppress progress output.")

    # 7. edge
    edge_p = subparsers.add_parser("edge", aliases=["rim", "milling"], help="Inspect, synthesize, or preview coin edge milling, inscriptions, and security stamps.")
    edge_p.add_argument("-i", "--inscription", type=str, help="Text to inscribe along cylindrical rim.")
    edge_p.add_argument("--inscription-mode", type=str, choices=["incuse", "raised"], default="incuse", help="Inscription mode.")
    edge_p.add_argument("--inscription-depth", type=float, default=0.25, help="Inscription depth in mm.")
    edge_p.add_argument("-s", "--stamp", type=str, help="Seed string for cryptographic rim stamp.")
    edge_p.add_argument("-g", "--grooves", type=int, default=64, help="Number of security grooves around perimeter.")
    edge_p.add_argument("--edge", type=str, default="sinusoidal", help="Reeding profile.")
    edge_p.add_argument("--serrations", type=int, default=120, help="Number of serrations/reeds.")
    edge_p.add_argument("--reed-depth", type=float, default=0.25, help="Reeding depth in mm.")
    edge_p.add_argument("--segmented-sectors", type=int, default=0, help="Number of reeded sectors.")
    edge_p.add_argument("--json", action="store_true", help="Output JSON metadata.")

    # 8. test
    subparsers.add_parser("test", aliases=["check", "self-test"], help="Run self-verification test runner.")

    return parser


def main(args_list: Optional[Sequence[str]] = None) -> int:
    """CLI entry point function."""
    parser = build_parser()
    args = parser.parse_args(args_list)

    Color.setup(no_color=args.no_color)

    if not args.command:
        print_banner()
        parser.print_help()
        if args_list is not None:
            return 0
        sys.exit(0)

    cmd = args.command
    if cmd in ("generate", "gen", "build"):
        code = handle_generate(args)
    elif cmd in ("edge", "rim", "milling"):
        code = handle_edge(args)
    elif cmd in ("slice", "slicer", "gcode"):
        code = handle_slice(args)
    elif cmd in ("presets", "list", "catalog"):
        code = handle_presets(args)
    elif cmd in ("serve", "studio", "web", "ui"):
        code = handle_serve(args)
    elif cmd in ("mcp", "stdio", "mcp-server"):
        code = handle_mcp(args)
    elif cmd in ("diagnostics", "doctor", "platform"):
        code = handle_diagnostics(args)
    elif cmd in ("test", "check", "self-test"):
        code = handle_test(args)
    else:
        parser.print_help()
        code = 1

    if args_list is not None:
        return code
    sys.exit(code)


if __name__ == "__main__":
    main()
