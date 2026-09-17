"""Pure Python stdlib ThreadingHTTPServer & REST API for Badge3D Coin Studio.

Serves the Web Studio UI (design influenced by Material 3), handles real-time 3D coin mesh
generation requests, streams binary STL & Wavefront OBJ exports, and computes
physical metal casting weights and 3D printing statistics.

Zero external dependencies (100% Python Standard Library).
"""

from __future__ import annotations

import cgi
import io
import json
import math
import mimetypes
import os
import sys
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from .compat import PathLike, safe_path
from .exporters import mesh_to_ascii_stl_text, mesh_to_binary_stl_bytes, mesh_to_obj_text
from .mesh_engine import CoinMeshEngine, CoinParameters, MeshData

# Standard density values in g/cm³ for precious metals and filaments
DENSITY_TABLE: Dict[str, float] = {
    "gold_24k": 19.32,
    "gold_18k": 15.58,
    "silver_925": 10.36,
    "silver_fine": 10.49,
    "bronze_c932": 8.73,
    "copper_pure": 8.96,
    "titanium_gr5": 4.43,
    "platinum": 21.45,
    "pla_filament": 1.24,
    "petg_filament": 1.27,
    "abs_filament": 1.04,
    "resin_standard": 1.15,
}

# Standard Studio Presets
STUDIO_PRESETS: Dict[str, Dict[str, Any]] = {
    "challenge_coin": {
        "name": "Military Challenge Coin",
        "shape": "circle",
        "radius": 20.0,
        "thickness": 3.5,
        "rim_width": 2.2,
        "rim_height": 0.8,
        "bevel_width": 0.4,
        "bevel_height": 0.4,
        "edge_reed_count": 80,
        "reed_depth": 0.30,
        "reed_profile": "sinusoidal",
        "relief_depth_obverse": 0.8,
        "relief_depth_reverse": 0.8,
        "material": "bronze",
        "text_front": "DEFENSE • HONOR • VALOR",
        "text_back": "EXCELLENCE UNDER PRESSURE",
    },
    "crypto_token": {
        "name": "Crypto / Web3 Token",
        "shape": "hexagon",
        "radius": 17.5,
        "thickness": 2.8,
        "rim_width": 1.8,
        "rim_height": 0.6,
        "bevel_width": 0.5,
        "bevel_height": 0.5,
        "edge_reed_count": 0,
        "reed_depth": 0.0,
        "reed_profile": "square",
        "relief_depth_obverse": 0.9,
        "relief_depth_reverse": 0.9,
        "material": "obsidian",
        "text_front": "ETHEREUM • DECENTRALIZED",
        "text_back": "PROOF OF STAKE 2026",
    },
    "roman_medallion": {
        "name": "Ancient Roman Medallion",
        "shape": "circle",
        "radius": 21.0,
        "thickness": 4.0,
        "rim_width": 2.8,
        "rim_height": 1.0,
        "bevel_width": 0.6,
        "bevel_height": 0.6,
        "edge_reed_count": 0,
        "reed_depth": 0.0,
        "reed_profile": "sinusoidal",
        "relief_depth_obverse": 1.2,
        "relief_depth_reverse": 1.2,
        "material": "silver",
        "text_front": "SENATVS POPVLVSQVE ROMANVS",
        "text_back": "IMPERIVM AETERNVM",
    },
    "sovereign_gold": {
        "name": "Sovereign Gold Bullion",
        "shape": "circle",
        "radius": 11.05,
        "thickness": 1.8,
        "rim_width": 1.2,
        "rim_height": 0.4,
        "bevel_width": 0.2,
        "bevel_height": 0.2,
        "edge_reed_count": 120,
        "reed_depth": 0.18,
        "reed_profile": "trapezoidal",
        "relief_depth_obverse": 0.5,
        "relief_depth_reverse": 0.5,
        "material": "gold",
        "text_front": "BRITANNIA • REGNA FIDELIS",
        "text_back": "ONE SOVEREIGN 2026",
    },
    "scifi_hex_badge": {
        "name": "Sci-Fi Hex Command Badge",
        "shape": "octagon",
        "radius": 19.0,
        "thickness": 3.2,
        "rim_width": 2.4,
        "rim_height": 0.9,
        "bevel_width": 0.6,
        "bevel_height": 0.6,
        "edge_reed_count": 48,
        "reed_depth": 0.40,
        "reed_profile": "square",
        "relief_depth_obverse": 1.0,
        "relief_depth_reverse": 1.0,
        "material": "titanium",
        "text_front": "SECTOR 7 • TASK FORCE",
        "text_back": "ORBITAL COMMAND STATION",
    },
}

# Embedded UI Fallback in case public/index.html is not found on disk
EMBEDDED_HTML_FALLBACK = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Badge3D Coin Studio — Relief Generator</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8f9fa; color: #202124; padding: 40px; text-align: center; }
    .card { background: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); max-width: 600px; margin: 40px auto; padding: 32px; }
    h1 { color: #1a73e8; font-size: 24px; margin-bottom: 12px; }
    p { color: #5f6368; line-height: 1.5; font-size: 14px; }
    .btn { display: inline-block; background: #1a73e8; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: bold; margin-top: 20px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Badge3D Coin Studio API</h1>
    <p>Pure Python stdlib 3D Coin & Relief Mesh Engine is running active on this port.</p>
    <p>API Endpoints: <code>/api/generate</code>, <code>/api/export-stl</code>, <code>/api/export-obj</code>, <code>/api/presets</code>, <code>/api/stats</code></p>
    <a href="/api/presets" class="btn">View API Presets</a>
  </div>
</body>
</html>"""


def parse_coin_params_from_dict(data: Dict[str, Any]) -> CoinParameters:
    """Parse and normalize incoming JSON dictionary into a CoinParameters dataclass."""
    # Check if a preset name was specified
    preset_key = data.get("preset")
    base_dict: Dict[str, Any] = {}
    if preset_key and preset_key in STUDIO_PRESETS:
        base_dict = dict(STUDIO_PRESETS[preset_key])

    # Allow incoming keys to override preset or default values
    radius = float(data.get("radius", base_dict.get("radius", 20.0)))
    thickness = float(data.get("thickness", base_dict.get("thickness", 3.0)))
    
    # Handle alternate camelCase vs snake_case keys
    rim_width = float(data.get("rim_width", data.get("rimWidth", base_dict.get("rim_width", 1.8))))
    rim_height = float(data.get("rim_height", data.get("rimHeight", base_dict.get("rim_height", 0.6))))
    
    bevel_width = float(data.get("bevel_width", data.get("rimBevel", data.get("bevelWidth", base_dict.get("bevel_width", 0.4)))))
    bevel_height = float(data.get("bevel_height", data.get("bevelHeight", base_dict.get("bevel_height", 0.4))))
    
    edge_reed_count = int(data.get("edge_reed_count", data.get("serrations", data.get("reed_count", base_dict.get("edge_reed_count", 80)))))
    reed_depth = float(data.get("reed_depth", data.get("serrationDepth", data.get("serration_depth", base_dict.get("reed_depth", 0.25)))))
    reed_profile = str(data.get("reed_profile", data.get("reedProfile", base_dict.get("reed_profile", "sinusoidal"))))
    
    radial_segments = int(data.get("radial_segments", data.get("radialSegments", 120)))
    field_rings = int(data.get("field_rings", data.get("fieldRings", 36)))
    
    relief_depth_obv = float(data.get("relief_depth_obverse", data.get("reliefDepth", data.get("relief_depth", base_dict.get("relief_depth_obverse", 0.6)))))
    relief_depth_rev = float(data.get("relief_depth_reverse", data.get("reliefDepthReverse", base_dict.get("relief_depth_reverse", 0.6))))
    
    relief_mode_obv = str(data.get("relief_mode_obverse", data.get("reliefMode", "emboss")))
    relief_mode_rev = str(data.get("relief_mode_reverse", data.get("reliefModeReverse", "emboss")))
    
    obverse_hm = data.get("obverse_heightmap", data.get("heightmap"))
    reverse_hm = data.get("reverse_heightmap")

    return CoinParameters(
        radius=radius,
        thickness=thickness,
        rim_width=rim_width,
        rim_height=rim_height,
        edge_reed_count=edge_reed_count,
        reed_depth=reed_depth,
        reed_profile=reed_profile,
        bevel_width=bevel_width,
        bevel_height=bevel_height,
        radial_segments=radial_segments,
        field_rings=field_rings,
        obverse_heightmap=obverse_hm,
        reverse_heightmap=reverse_hm,
        relief_depth_obverse=relief_depth_obv,
        relief_depth_reverse=relief_depth_rev,
        relief_mode_obverse=relief_mode_obv,
        relief_mode_reverse=relief_mode_rev,
        smooth_shading=bool(data.get("smooth_shading", True)),
    )


def compute_physical_statistics(params: CoinParameters, mesh: Optional[MeshData] = None) -> Dict[str, Any]:
    """Calculate geometric dimensions, bounding box, volume, and precious metal mass estimates."""
    r = params.radius
    t = params.thickness
    
    # Calculate geometric cylinder base volume + rim elevation
    # Base cylinder volume in mm³
    base_vol_mm3 = math.pi * (r ** 2) * (t - 2 * params.rim_height)
    # Rim ring volume in mm³
    field_r = max(0.1, r - params.rim_width)
    rim_area_mm2 = math.pi * (r ** 2 - field_r ** 2)
    rim_vol_mm3 = 2.0 * rim_area_mm2 * params.rim_height
    
    # Total volume in cm³ (1 cm³ = 1000 mm³)
    total_vol_cm3 = (base_vol_mm3 + rim_vol_mm3) / 1000.0

    # Weight estimations in grams
    weights: Dict[str, float] = {}
    for metal_key, density in DENSITY_TABLE.items():
        weights[metal_key] = round(total_vol_cm3 * density, 2)

    stats: Dict[str, Any] = {
        "dimensions_mm": {
            "diameter": round(r * 2.0, 2),
            "thickness": round(t, 2),
            "rim_width": round(params.rim_width, 2),
            "rim_height": round(params.rim_height, 2),
        },
        "volume_cm3": round(total_vol_cm3, 3),
        "volume_mm3": round(total_vol_cm3 * 1000.0, 1),
        "weights_grams": weights,
        "slicing_estimates": {
            "layer_height_mm": 0.12,
            "layer_count": math.ceil(t / 0.12),
            "estimated_print_time_minutes": math.ceil(math.ceil(t / 0.12) * 0.75 + 5),
            "recommended_infill_percent": 100,
        },
    }

    if mesh:
        bbox_min, bbox_max = mesh.get_bounding_box()
        stats["mesh"] = {
            "vertex_count": mesh.vertex_count,
            "triangle_count": mesh.triangle_count,
            "bounding_box_min": bbox_min,
            "bounding_box_max": bbox_max,
            "is_watertight": mesh.is_watertight(),
        }

    return stats


class CoinStudioRequestHandler(SimpleHTTPRequestHandler):
    """Custom HTTP Request Handler serving Badge3D Coin Studio."""

    # Explicit class attribute for public directory path
    public_directory: Path = Path(__file__).resolve().parent.parent.parent / "public"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Override directory if supplied
        if hasattr(self, "public_directory") and self.public_directory.exists():
            directory = str(self.public_directory)
        else:
            directory = os.getcwd()
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress noisy access logs during automated testing or quiet runs."""
        if os.environ.get("BADGE3D_QUIET_LOGS") == "1":
            return
        sys.stderr.write(f"[CoinStudio] {self.address_string()} - {format % args}\n")

    def _send_json_response(self, data: Any, status_code: int = 200) -> None:
        """Send a JSON payload response with proper headers."""
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def _parse_json_body(self) -> Dict[str, Any]:
        """Read and parse incoming JSON request body."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            return {}
        raw_body = self.rfile.read(content_length).decode("utf-8", errors="replace")
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self) -> None:
        """Handle CORS pre-flight requests."""
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Content-Disposition")
        self.end_headers()

    def do_GET(self) -> None:
        """Handle GET requests for static assets, presets, health, and stats."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)

        # 1. Health check
        if path in ("/health", "/api/health"):
            self._send_json_response({
                "status": "ok",
                "service": "badge3d-coin-generator",
                "version": "1.0.0",
            })
            return

        # 2. Presets endpoint
        if path == "/api/presets":
            self._send_json_response({
                "presets": STUDIO_PRESETS,
                "count": len(STUDIO_PRESETS),
            })
            return

        # 3. Stats calculation endpoint
        if path == "/api/stats":
            radius = float(query.get("radius", ["20.0"])[0])
            thickness = float(query.get("thickness", ["3.0"])[0])
            rim_width = float(query.get("rim_width", ["1.8"])[0])
            rim_height = float(query.get("rim_height", ["0.6"])[0])

            params = CoinParameters(
                radius=radius,
                thickness=thickness,
                rim_width=rim_width,
                rim_height=rim_height,
            )
            stats = compute_physical_statistics(params)
            self._send_json_response(stats)
            return

        # 4. G-code Slicing endpoint
        if path == "/api/slice-gcode":
            try:
                from .slicer_engine import (
                    FilamentType,
                    InfillPattern,
                    SlicingConfig,
                    slice_mesh,
                )
                from .__init__ import CoinGenerator, resolve_preset
                preset_id = query.get("preset", [None])[0]
                if preset_id:
                    coin_dict = resolve_preset(preset_id)
                    generator = CoinGenerator(**coin_dict)
                else:
                    r = float(query.get("radius", ["20.0"])[0])
                    th = float(query.get("thickness", ["3.0"])[0])
                    generator = CoinGenerator(radius=r, thickness=th)

                mesh = generator.generate()
                layer_h = float(query.get("layer_height", ["0.20"])[0])
                infill_d = float(query.get("infill_density", ["0.20"])[0])
                pat_str = query.get("infill_pattern", ["rectilinear"])[0]
                try:
                    pat = InfillPattern(pat_str)
                except ValueError:
                    pat = InfillPattern.RECTILINEAR

                fil_str = query.get("filament_type", ["pla"])[0]
                try:
                    fil = FilamentType(fil_str)
                except ValueError:
                    fil = FilamentType.PLA

                cfg = SlicingConfig(layer_height=layer_h, infill_density=infill_d, infill_pattern=pat, filament_type=fil)
                result = slice_mesh(mesh, config=cfg)
                self._send_json_response(result.to_dict())
            except Exception as exc:
                self._send_json_response({"error": str(exc)}, status_code=500)
            return

        # 5. Root index.html or static files
        if path in ("", "/index.html"):
            index_path = self.public_directory / "index.html"
            if index_path.exists():
                try:
                    content = index_path.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                except OSError:
                    pass

            # Fallback embedded HTML
            content = EMBEDDED_HTML_FALLBACK.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # Serve other static files from public_directory
        file_target = (self.public_directory / path.lstrip("/")).resolve()
        if file_target.exists() and file_target.is_file():
            mime, _ = mimetypes.guess_type(str(file_target))
            mime = mime or "application/octet-stream"
            content = file_target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # Fall back to standard SimpleHTTPRequestHandler for any standard path
        super().do_GET()

    def do_POST(self) -> None:
        """Handle POST requests for mesh generation and 3D file exports."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        req_data = self._parse_json_body()

        # 1. Mesh generation endpoint
        if path == "/api/generate":
            try:
                params = parse_coin_params_from_dict(req_data)
                engine = CoinMeshEngine(params)
                mesh = engine.generate()
                stats = compute_physical_statistics(params, mesh=mesh)

                response_payload = {
                    "status": "success",
                    "parameters": {
                        "radius": params.radius,
                        "thickness": params.thickness,
                        "rim_width": params.rim_width,
                        "rim_height": params.rim_height,
                        "edge_reed_count": params.edge_reed_count,
                    },
                    "statistics": stats,
                }
                self._send_json_response(response_payload)
            except Exception as exc:
                self._send_json_response({"error": str(exc), "status": "failed"}, status_code=500)
            return

        # 2. Binary STL Export endpoint
        if path == "/api/export-stl":
            try:
                params = parse_coin_params_from_dict(req_data)
                engine = CoinMeshEngine(params)
                mesh = engine.generate()
                stl_bytes = mesh_to_binary_stl_bytes(mesh, header_comment="badge3d-coin-generator")

                filename = f"coin-{params.radius:.1f}mm.stl"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/sla")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(len(stl_bytes)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(stl_bytes)
            except Exception as exc:
                self._send_json_response({"error": str(exc)}, status_code=500)
            return

        # 3. Wavefront OBJ Export endpoint
        if path == "/api/export-obj":
            try:
                params = parse_coin_params_from_dict(req_data)
                engine = CoinMeshEngine(params)
                mesh = engine.generate()
                obj_text = mesh_to_obj_text(mesh, object_name="Coin3D")
                obj_bytes = obj_text.encode("utf-8")

                filename = f"coin-{params.radius:.1f}mm.obj"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(len(obj_bytes)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(obj_bytes)
            except Exception as exc:
                self._send_json_response({"error": str(exc)}, status_code=500)
            return

        # 4. G-code Slicing endpoint
        if path == "/api/slice-gcode":
            try:
                from .slicer_engine import (
                    FilamentType,
                    InfillPattern,
                    SlicingConfig,
                    slice_mesh,
                )
                from .__init__ import CoinGenerator, resolve_preset
                preset_id = req_data.get("preset")
                if preset_id:
                    coin_dict = resolve_preset(preset_id)
                    generator = CoinGenerator(**coin_dict)
                    mesh = generator.generate()
                    radius_val = generator.radius
                else:
                    params = parse_coin_params_from_dict(req_data)
                    engine = CoinMeshEngine(params)
                    mesh = engine.generate()
                    radius_val = params.radius

                layer_h = float(req_data.get("layer_height", 0.20))
                infill_d = float(req_data.get("infill_density", 0.20))
                pat_str = str(req_data.get("infill_pattern", "rectilinear")).lower()
                try:
                    pat = InfillPattern(pat_str)
                except ValueError:
                    pat = InfillPattern.RECTILINEAR

                fil_str = str(req_data.get("filament_type", "pla")).lower()
                try:
                    fil = FilamentType(fil_str)
                except ValueError:
                    fil = FilamentType.PLA

                cfg = SlicingConfig(layer_height=layer_h, infill_density=infill_d, infill_pattern=pat, filament_type=fil)
                result = slice_mesh(mesh, config=cfg)

                if req_data.get("format") == "gcode":
                    gcode_text = result.to_gcode()
                    gcode_bytes = gcode_text.encode("utf-8")
                    filename = f"coin-{radius_val:.1f}mm.gcode"
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/x-gcode; charset=utf-8")
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                    self.send_header("Content-Length", str(len(gcode_bytes)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(gcode_bytes)
                else:
                    self._send_json_response(result.to_dict())
            except Exception as exc:
                self._send_json_response({"error": str(exc)}, status_code=500)
            return

        # 5. Unknown endpoint
        self._send_json_response({"error": f"Endpoint not found: {path}"}, status_code=404)


def create_ui_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    public_dir: Optional[PathLike] = None,
) -> ThreadingHTTPServer:
    """Instantiate and configure the ThreadingHTTPServer instance for the studio."""
    if public_dir is not None:
        CoinStudioRequestHandler.public_directory = safe_path(public_dir)
    else:
        # Default to ../../../public relative to ui_server.py
        CoinStudioRequestHandler.public_directory = (
            Path(__file__).resolve().parent.parent.parent / "public"
        )

    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((host, port), CoinStudioRequestHandler)
    return server


def start_ui_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    public_dir: Optional[PathLike] = None,
    open_browser: bool = False,
) -> None:
    """Start the Badge3D Coin Studio UI server and listen for incoming connections."""
    server = create_ui_server(host=host, port=port, public_dir=public_dir)
    url = f"http://{host}:{port}/"
    print("=" * 70)
    print(f"  Badge3D Coin Studio — Relief & Mesh Engine")
    print(f"  Server URL:    {url}")
    print(f"  API Docs:      {url}api/presets")
    print(f"  Dependencies:  Zero external dependencies (Pure Python Stdlib)")
    print(f"  Press Ctrl+C to stop server")
    print("=" * 70)

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Badge3D Coin Studio server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Start Badge3D Coin Studio UI Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port number (default: 8080)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser")
    args = parser.parse_args()

    start_ui_server(host=args.host, port=args.port, open_browser=not args.no_browser)
