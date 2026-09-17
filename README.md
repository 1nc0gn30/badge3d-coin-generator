<div align="center">

# 🪙 Badge3D Coin Generator

**Pure Python 3D Parametric Coin, Medal & Relief Mesh Generator with Real-Time Web Studio & AI Agent MCP Server**

[![CI Matrix](https://img.shields.io/badge/CI-Multi--OS%20%7C%20Py%203.9--3.13-success?logo=github-actions)](https://github.com/google/badge3d-coin-generator/actions)
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-Zero%20(Pure%20Stdlib)-blue.svg)](https://docs.python.org/3/)
[![3D Print Ready](https://img.shields.io/badge/3D%20Print-Watertight%20Manifold%20STL-orange.svg)](https://en.wikipedia.org/wiki/STL_(file_format))
[![PBR Studio UI](https://img.shields.io/badge/Studio%20UI-Google%20Material%203-4285F4.svg?logo=google)](http://localhost:8080)
[![MCP Server](https://img.shields.io/badge/MCP-Claude%20%7C%20Cursor%20%7C%20Cline-8A2BE2.svg)](https://modelcontextprotocol.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

<p align="center">
  <b>Generate millimeter-accurate, 3D-printable challenge coins, bullion medals, and crypto badges directly from vector SVGs, text inscriptions, or parametric specifications.</b>
</p>

</div>

---

## 🌟 Highlights & Key Capabilities

- **Zero External Dependencies**: 100% Pure Python Standard Library (`dependencies = []`). Runs out-of-the-box on Linux, macOS, Windows, and Termux without compiling C extensions or requiring NumPy/Trimesh.
- **Parametric 3D Mesh Engine**: Full control over outer diameter, total thickness, raised protective rims, step walls, edge bevels/chamfers, central loops, and edge serrations (sinusoidal, square, fluted, trapezoidal reeding).
- **Pure Python SVG Vector-to-Relief Rasterizer**: Built-in cubic/quadratic Bézier curve flattener, path tokenizer, and scanline polygon fill rasterizer that converts 2D SVGs into 3D displacement heightmaps.
- **High-Performance Exporters**:
  - **Binary STL**: Standard IEEE 754 32-bit Little-Endian with 80-byte header, exact face counts, and calculated face normals.
  - **ASCII STL**: Human-readable STL format for CAD debugging.
  - **Wavefront OBJ & MTL**: Complete polygonal mesh with vertex normals (`vn`), UV texture coordinates (`vt`), and material definitions.
  - **glTF / GLB 2.0**: Ready for Three.js, Babylon.js, WebGL viewers, and augmented reality.
- **Google 3D Coin Studio Web UI**: Google Material 3 Light/Dark studio with interactive Three.js 3D viewport, real-time metallic PBR shaders (24K Gold, Antique Silver, Bronze, Obsidian, Titanium), turntable controls, dropzone logo uploader, and 1-click STL export.
- **AI Agent MCP Server**: Full Model Context Protocol (MCP) server for Claude Desktop, Cursor, and Cline to create 3D coins through natural language.
- **Watertight Manifold Geometry**: All generated meshes are verified 2-manifolds with outward-facing consistent normals, zero unstitched boundaries, and zero non-manifold edges.

---

## 📐 Architecture & Workflow

```
   ┌─────────────────────────────────────────────────────────────┐
   │                       INPUT SOURCES                         │
   │  Parametric Dimensions  │  Vector SVG Logos  │  Text & Fonts│
   └───────────────┬─────────────────────┬───────────────┬───────┘
                   │                     │               │
                   ▼                     ▼               │
   ┌──────────────────────────────────────────────┐      │
   │      Pure Python SVG Scanline Rasterizer     │      │
   │  - Bézier Curve Flattening (Cubic/Quad)      │      │
   │  - Path Tokenizer & Non-Zero Winding Fill    │      │
   │  - Discrete 2D Floating Elevation Heightmap  │      │
   └──────────────────────┬───────────────────────┘      │
                          │                              │
                          ▼                              ▼
   ┌─────────────────────────────────────────────────────────────┐
   │             Parametric Polar Mesh Engine (CoinMeshEngine)   │
   │  - Concentric Polar Grid (Obverse & Reverse Fields)         │
   │  - Bilinear Heightmap Elevation Displacement                │
   │  - Outer Rim Extrusion & Chamfer/Bevel Steps                │
   │  - Edge Reeding / Serration Waveform Modulation             │
   │  - Area-Weighted Vertex Normal Accumulation                 │
   └──────────────────────────────┬──────────────────────────────┘
                                  │
                                  ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                   3D EXPORTERS & INTERFACES                 │
   ├──────────────────────────────┬──────────────────────────────┤
   │  Binary STL (.stl)           │  Wavefront OBJ (.obj/.mtl)   │
   │  glTF / GLB 2.0 Container    │  Physical Mass Calculator    │
   ├──────────────────────────────┼──────────────────────────────┤
   │  Google 3D Coin Studio (UI)  │  Model Context Protocol (MCP)│
   └──────────────────────────────┴──────────────────────────────┘
```

---

## 🚀 Quickstart

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/google/badge3d-coin-generator.git
cd badge3d-coin-generator

# Install in editable mode
pip install -e .
```

### 2. Launch Google 3D Coin Studio (Web UI)

```bash
badge3d serve --port 8080
```
Open **`http://localhost:8080`** in your browser to interact with the real-time Material 3 3D studio.

### 3. CLI Coin Generation

```bash
# Generate a standard 40mm military challenge coin
badge3d generate --preset challenge_coin --output challenge_coin.stl

# Generate a custom 38mm titanium crypto badge
badge3d generate \
  --radius 19.0 \
  --thickness 3.2 \
  --rim-width 2.0 \
  --rim-height 0.8 \
  --serrations 60 \
  --output custom_badge.stl

# View physical weight & mass breakdown for gold, silver, bronze, titanium
badge3d stats --radius 20.0 --thickness 3.5
```

---

## 💎 Preset Catalog

| Preset Name | Diameter | Thickness | Rim Width | Rim Height | Reeding | Bevel | Ideal Metal Finish | Description |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---|:---|
| **`challenge_coin`** | 40.0 mm | 3.5 mm | 2.2 mm | 0.8 mm | 80 ribs | 0.4 mm | Polished Bronze / Brass | Classic military unit coin with raised outer rim and serrated edge |
| **`crypto_token`** | 35.0 mm | 2.8 mm | 1.8 mm | 0.6 mm | Smooth | 0.5 mm | Cyberpunk Obsidian / Gold | Hexagonal boundary with cybernetic relief displacement |
| **`roman_medallion`** | 42.0 mm | 4.0 mm | 2.8 mm | 1.0 mm | Smooth | 0.6 mm | Antique Silver (.925) | Classical hammered thick imperial coin with heavy relief |
| **`sovereign_gold`** | 22.1 mm | 1.8 mm | 1.2 mm | 0.4 mm | 120 ribs | 0.2 mm | 24K Pure Gold | Fine investment bullion with micro-reeded perimeter |
| **`scifi_hex_badge`** | 38.0 mm | 3.2 mm | 2.4 mm | 0.9 mm | 48 ribs | 0.6 mm | Brushed Grade 5 Titanium | Octagonal futuristic tactical duty badge |

---

## 🖨️ 3D Printing & Slicing Specifications

Every mesh produced by `badge3d-coin-generator` is a watertight closed 2-manifold optimized for additive manufacturing.

### FDM 3D Printing (Bambu Studio / PrusaSlicer / Cura)
- **Orientation**: Lay flat on build plate (Z-axis vertical).
- **Layer Height**: `0.08 mm` to `0.12 mm` (0.08mm recommended for high-relief details).
- **Nozzle Diameter**: `0.2 mm` or `0.4 mm`.
- **Infill**: `100% Solid` (Concentric top/bottom pattern).
- **Ironing**: Enable **"Iron top surfaces"** (Flow: 12%, Speed: 20mm/s) to achieve a mirror-smooth background field between relief engravings.
- **First Layer**: First layer height `0.2 mm`, line width `120%` for maximum bed adhesion.

### SLA / Resin 3D Printing (Anycubic, Elegoo, Formlabs)
- **Orientation**: Tilt coin at **35° to 45°** relative to the build plate. *Do not print flat directly against the FEP film to avoid suction cup force tearing.*
- **Layer Height**: `0.025 mm` (25 microns) or `0.05 mm`.
- **Support Strategy**: Place light supports along the lower outer rim perimeter only. Avoid placing supports across the face relief artwork.
- **Exposure**: Follow resin manufacturer specs (e.g. 2.2s normal exposure on 12K Mono screens).

### Lost-Wax Investment Casting (Precious Metals)
- **Casting Wax Resin**: Print using castable photopolymer resin (e.g. Formlabs Castable Wax 40, Siraya Tech Cast).
- **Shrinkage Compensation**: Scale coin dimensions by **+1.5% to +2.0%** in slicer prior to export to compensate for metal cooling contraction.
- **Burnout Schedule**: Standard 12-hour progressive burnout ramp to 730°C (1350°F) in gypsum investment flask.

---

## 🤖 AI Agent MCP Server Configuration

`badge3d-coin-generator` exposes a complete **Model Context Protocol (MCP)** server over `stdio` JSON-RPC for AI assistants (Claude Desktop, Cursor, Cline).

### 1. Claude Desktop Setup
Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "badge3d": {
      "command": "python",
      "args": ["-m", "badge3d_coin_generator.mcp_server"]
    }
  }
}
```

### 2. Cursor Setup
Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "badge3d-coin-generator": {
      "command": "badge3d",
      "args": ["mcp"]
    }
  }
}
```

### 3. Cline / VS Code Setup
Add to `cline_mcp_settings.json`:

```json
{
  "mcpServers": {
    "badge3d": {
      "command": "python3",
      "args": ["-m", "badge3d_coin_generator.mcp_server"]
    }
  }
}
```

### Available MCP Tools:
- **`generate_coin`**: Generate 3D coin mesh and export to binary STL / OBJ with custom dimensions, rims, serrations, and relief displacement.
- **`list_presets`**: Query all available coin presets (`challenge_coin`, `crypto_token`, `roman_medallion`, etc.).
- **`get_coin_stats`**: Compute physical dimensions, volume (cm³), and mass in 24K Gold, Silver, Bronze, Titanium, and PLA.

---

## 🐍 Python API Reference

```python
from badge3d_coin_generator.mesh_engine import CoinParameters, CoinMeshEngine
from badge3d_coin_generator.exporters import export_binary_stl, export_obj
from badge3d_coin_generator.ui_server import compute_physical_statistics

# 1. Configure parametric dimensions
params = CoinParameters(
    radius=20.0,             # 40mm diameter
    thickness=3.5,            # 3.5mm total thickness
    rim_width=2.2,            # 2.2mm raised rim
    rim_height=0.8,           # 0.8mm rim elevation
    bevel_width=0.4,          # 0.4mm rim edge chamfer
    edge_reed_count=80,       # 80 serrated reeding ridges
    reed_depth=0.30,          # 0.3mm reed groove depth
    relief_depth_obverse=0.8, # 0.8mm obverse relief height
    smooth_shading=True,
)

# 2. Generate 3D polygonal mesh
engine = CoinMeshEngine(params)
mesh = engine.generate()

print(f"Generated mesh with {mesh.vertex_count:,} vertices and {mesh.triangle_count:,} triangles.")
print(f"Is watertight manifold: {mesh.is_watertight()}")

# 3. Export to Binary STL for 3D printing
export_binary_stl(mesh, "custom_coin.stl")

# 4. Export to Wavefront OBJ for CAD / Blender
export_obj(mesh, "custom_coin.obj")

# 5. Compute metal mass estimates
stats = compute_physical_statistics(params, mesh=mesh)
print(f"Solid Volume: {stats['volume_cm3']} cm³")
print(f"Weight in 24K Gold: {stats['weights_grams']['gold_24k']} grams")
print(f"Weight in Sterling Silver: {stats['weights_grams']['silver_925']} grams")
```

---

## 💻 CLI Command Reference

```bash
# Print general help
badge3d --help

# List all built-in presets
badge3d presets

# Generate 3D coin from preset
badge3d generate --preset challenge_coin --output output.stl

# Generate custom dimensions
badge3d generate --radius 22.5 --thickness 3.0 --rim-width 2.0 --output coin.stl

# Launch Web UI Server
badge3d serve --host 127.0.0.1 --port 8080

# Start MCP Server for AI agents
badge3d mcp

# Calculate physical volume and weights
badge3d stats --radius 20.0 --thickness 3.5
```

---

## 🧪 Running the Test Suite

```bash
# Run full pytest suite with verbose output
pytest -v

# Run with test coverage
pytest --cov=badge3d_coin_generator tests/
```

---

## 📄 License

This project is licensed under the **MIT License**. Free for commercial and personal 3D printing, CAD modeling, and manufacturing.
