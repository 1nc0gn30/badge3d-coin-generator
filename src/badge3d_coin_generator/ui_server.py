"""Pure Python stdlib ThreadingHTTPServer & REST API for Badge3D Coin Studio.

Serves the Web Studio UI, handles real-time 3D coin mesh generation requests,
streams watertight Binary STL, Wavefront OBJ, glTF 2.0/GLB, and RepRap/Marlin
G-code exports, and computes physical metal casting weights and 3D printing
statistics.

Hardened for local loopback operation (127.0.0.1:8084):
- Strict Host & Origin allowlists with Vary: Origin (zero wildcard CORS)
- Canonicalized static path containment (is_relative_to) blocking traversal/symlinks
- 1 MiB request body cap (413), strict JSON object parsing (400), finite bounds (400)
- CSP + X-Content-Type-Options + Referrer-Policy security headers on every response

Zero external dependencies (100% Python Standard Library).
"""

from __future__ import annotations

import hashlib
import json
import math
import mimetypes
import os
import sys
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Set

from . import (
    STUDIO_PRESET_MAP,
    __version__,
    resolve_preset,
    validate_bounded_int,
    validate_finite_float,
)
from .compat import PathLike, safe_path
from .exporters import (
    mesh_to_binary_stl_bytes,
    mesh_to_glb_bytes,
    mesh_to_gltf_json,
    mesh_to_obj_text,
)
from .mesh_engine import CoinMeshEngine, CoinParameters, MeshData

# Security & protocol constants
MAX_BODY_BYTES = 1_048_576  # 1 MiB
ALLOWED_HOSTS: Set[str] = {"127.0.0.1", "localhost", "[::1]", "::1"}
STATIC_ALLOWED_ORIGINS: Set[str] = {
    "http://127.0.0.1:8084",
    "http://localhost:8084",
    "http://[::1]:8084",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://[::1]:3000",
    "https://badge3d.nullai.tech",
    "https://badge3d-coin-studio.netlify.app",
    "https://zoth.nullai.tech",
}
SECURITY_CSP = (
    "default-src 'self' data: blob:; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self' http://127.0.0.1:8084 http://localhost:8084 http://127.0.0.1:3000 http://localhost:3000; "
    "frame-ancestors 'self' http://127.0.0.1:3000 http://localhost:3000 http://127.0.0.1:8084 http://localhost:8084"
)
LEGAL_ROUTES: Dict[str, str] = {
    "/terms": "terms.html",
    "/privacy": "privacy.html",
    "/support": "support.html",
}

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

# Standard Studio Presets (unified with __init__.STUDIO_PRESET_MAP)
STUDIO_PRESETS: Dict[str, Dict[str, Any]] = STUDIO_PRESET_MAP

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
    h1 { color: #7a5808; font-size: 24px; margin-bottom: 12px; }
    p { color: #475467; line-height: 1.5; font-size: 14px; }
    .btn { display: inline-block; background: #7a5808; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: bold; margin-top: 20px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Badge3D Coin Studio API</h1>
    <p>Pure Python stdlib 3D Coin &amp; Relief Mesh Engine is running active on this port.</p>
    <p>API Endpoints: <code>/api/generate</code>, <code>/api/export-stl</code>, <code>/api/export-obj</code>, <code>/api/export-glb</code>, <code>/api/slice-gcode</code>, <code>/api/presets</code>, <code>/api/stats</code></p>
    <a href="/api/presets" class="btn">View API Presets</a>
  </div>
</body>
</html>"""


class _RequestValidationError(Exception):
    """Internal exception carrying an HTTP status code for client input errors."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _extract_host_only(host_header: Optional[str]) -> Optional[str]:
    """Extract normalized hostname from HTTP Host header (supporting IPv6 bracketed form)."""
    if not host_header:
        return None
    raw = host_header.strip().lower()
    if not raw or any(ch in raw for ch in ("/", "\\", "@", " ", "\t", "\r", "\n")):
        return None
    if raw.startswith("["):
        end_bracket = raw.find("]")
        if end_bracket == -1:
            return None
        host_part = raw[: end_bracket + 1]
        rest = raw[end_bracket + 1 :]
        if rest:
            if not rest.startswith(":") or not rest[1:].isdigit():
                return None
        return host_part
    if ":" in raw:
        parts = raw.rsplit(":", 1)
        if not parts[1].isdigit():
            return None
        return parts[0]
    return raw


def parse_coin_params_from_dict(data: Dict[str, Any]) -> CoinParameters:
    """Parse, normalize, and bounds-validate incoming JSON dictionary into CoinParameters."""
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object.")

    preset_key = data.get("preset")
    base_dict: Dict[str, Any] = {}
    if preset_key is not None and preset_key != "":
        resolved = resolve_preset(str(preset_key))
        if resolved is None:
            raise ValueError(f"Unknown preset: {preset_key!r}")
        base_dict = dict(resolved)

    radius = validate_finite_float(data.get("radius", base_dict.get("radius", 20.0)), "radius", 1.0, 100.0)
    thickness = validate_finite_float(data.get("thickness", base_dict.get("thickness", 3.0)), "thickness", 0.5, 25.0)

    rim_width = validate_finite_float(
        data.get("rim_width", data.get("rimWidth", base_dict.get("rim_width", 1.8))),
        "rim_width",
        0.1,
        20.0,
    )
    rim_height = validate_finite_float(
        data.get("rim_height", data.get("rimHeight", base_dict.get("rim_height", 0.6))),
        "rim_height",
        0.0,
        10.0,
    )

    bevel_width = validate_finite_float(
        data.get("bevel_width", data.get("rimBevel", data.get("bevelWidth", base_dict.get("bevel_width", 0.4)))),
        "bevel_width",
        0.0,
        10.0,
    )
    bevel_height = validate_finite_float(
        data.get("bevel_height", data.get("bevelHeight", base_dict.get("bevel_height", 0.4))),
        "bevel_height",
        0.0,
        10.0,
    )

    default_reeds = base_dict.get("edge_reed_count", base_dict.get("serrations", 80))
    edge_reed_count = validate_bounded_int(
        data.get("edge_reed_count", data.get("serrations", data.get("reed_count", default_reeds))),
        "edge_reed_count",
        0,
        360,
    )
    reed_depth = validate_finite_float(
        data.get("reed_depth", data.get("serrationDepth", data.get("serration_depth", base_dict.get("reed_depth", 0.25)))),
        "reed_depth",
        0.0,
        5.0,
    )
    reed_profile = str(data.get("reed_profile", data.get("reedProfile", base_dict.get("reed_profile", "sinusoidal"))))

    radial_segments = validate_bounded_int(
        data.get("radial_segments", data.get("radialSegments", data.get("resolution", 120))),
        "radial_segments",
        16,
        512,
    )
    field_rings = validate_bounded_int(
        data.get("field_rings", data.get("fieldRings", 36)),
        "field_rings",
        4,
        128,
    )

    relief_depth_obv = validate_finite_float(
        data.get(
            "relief_depth_obverse",
            data.get("relief_height", data.get("reliefDepth", data.get("relief_depth", base_dict.get("relief_depth_obverse", 0.6)))),
        ),
        "relief_height",
        0.0,
        5.0,
    )
    relief_depth_rev = validate_finite_float(
        data.get("relief_depth_reverse", data.get("reliefDepthReverse", base_dict.get("relief_depth_reverse", 0.6))),
        "relief_depth_reverse",
        0.0,
        5.0,
    )

    relief_mode_obv = str(data.get("relief_mode_obverse", data.get("reliefMode", "emboss")))
    relief_mode_rev = str(data.get("relief_mode_reverse", data.get("reliefModeReverse", "emboss")))

    obverse_hm = data.get("obverse_heightmap", data.get("heightmap"))
    reverse_hm = data.get("reverse_heightmap")

    edge_inscription = data.get("edge_inscription", data.get("edgeInscription", data.get("inscription")))
    edge_inscription_depth = validate_finite_float(
        data.get("edge_inscription_depth", data.get("edgeInscriptionDepth", 0.25)),
        "edge_inscription_depth",
        0.0,
        3.0,
    )
    edge_inscription_mode = str(data.get("edge_inscription_mode", data.get("edgeInscriptionMode", "incuse")))
    security_stamp_seed = data.get("security_stamp_seed", data.get("securityStampSeed", data.get("security_stamp", data.get("stamp"))))
    security_stamp_grooves = validate_bounded_int(
        data.get("security_stamp_grooves", data.get("securityStampGrooves", 64)),
        "security_stamp_grooves",
        1,
        512,
    )
    segmented_sectors = validate_bounded_int(
        data.get("segmented_sectors", data.get("segmentedSectors", 0)),
        "segmented_sectors",
        0,
        64,
    )

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
        edge_inscription=edge_inscription,
        edge_inscription_depth=edge_inscription_depth,
        edge_inscription_mode=edge_inscription_mode,
        security_stamp_seed=security_stamp_seed,
        security_stamp_grooves=security_stamp_grooves,
        segmented_sectors=segmented_sectors,
        smooth_shading=bool(data.get("smooth_shading", True)),
    )


def compute_physical_statistics(params: CoinParameters, mesh: Optional[MeshData] = None) -> Dict[str, Any]:
    """Calculate geometric dimensions, bounding box, volume, and precious metal mass estimates."""
    r = validate_finite_float(params.radius, "radius", 1.0, 100.0)
    t = validate_finite_float(params.thickness, "thickness", 0.5, 25.0)
    rim_w = validate_finite_float(params.rim_width, "rim_width", 0.1, 20.0)
    rim_h = validate_finite_float(params.rim_height, "rim_height", 0.0, 10.0)
    eff_rim_h = min(rim_h, t * 0.45)

    # Base cylinder volume in mm³
    base_vol_mm3 = math.pi * (r ** 2) * (t - 2.0 * eff_rim_h)
    field_r = max(0.1, r - min(rim_w, r * 0.4))
    rim_area_mm2 = math.pi * (r ** 2 - field_r ** 2)
    rim_vol_mm3 = 2.0 * rim_area_mm2 * eff_rim_h

    total_vol_cm3 = max(0.001, (base_vol_mm3 + rim_vol_mm3) / 1000.0)

    weights: Dict[str, float] = {}
    for metal_key, density in DENSITY_TABLE.items():
        weights[metal_key] = round(total_vol_cm3 * density, 2)

    stats: Dict[str, Any] = {
        "dimensions_mm": {
            "diameter": round(r * 2.0, 2),
            "thickness": round(t, 2),
            "rim_width": round(rim_w, 2),
            "rim_height": round(rim_h, 2),
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


class CoinStudioRequestHandler(BaseHTTPRequestHandler):
    """Hardened HTTP Request Handler serving Badge3D Coin Studio & REST API."""

    public_directory: Path = Path(__file__).resolve().parent.parent.parent / "public"
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress noisy access logs during automated testing or quiet runs."""
        if os.environ.get("BADGE3D_QUIET_LOGS") == "1":
            return
        sys.stderr.write(f"[CoinStudio] {self.address_string()} - {format % args}\n")

    def _allowed_origins(self) -> Set[str]:
        origins = set(STATIC_ALLOWED_ORIGINS)
        try:
            port = self.server.server_address[1]
            origins.add(f"http://127.0.0.1:{port}")
            origins.add(f"http://localhost:{port}")
            origins.add(f"http://[::1]:{port}")
        except Exception:
            pass
        return origins

    def _send_security_headers(self, allow_cors_origin: Optional[str] = None) -> None:
        self.close_connection = True
        self.send_header("Connection", "close")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", SECURITY_CSP)
        self.send_header("Vary", "Origin")
        if allow_cors_origin:
            self.send_header("Access-Control-Allow-Origin", allow_cors_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Content-Disposition")

    def _validated_origin(self) -> Optional[str]:
        origin = self.headers.get("Origin")
        if origin is None:
            return None
        origin_clean = origin.strip()
        if origin_clean in self._allowed_origins():
            return origin_clean
        return None

    def _check_host_and_origin(self, send_body: bool = True) -> bool:
        """Enforce loopback Host allowlist and exact-match Origin allowlist."""
        host_only = _extract_host_only(self.headers.get("Host"))
        if host_only not in ALLOWED_HOSTS:
            self._send_json_response(
                {"error": "Forbidden: untrusted Host header"},
                status_code=HTTPStatus.FORBIDDEN,
                send_body=send_body,
                include_cors=False,
            )
            return False

        origin = self.headers.get("Origin")
        if origin is not None and origin.strip() not in self._allowed_origins():
            self._send_json_response(
                {"error": "Forbidden: Origin not allowed"},
                status_code=HTTPStatus.FORBIDDEN,
                send_body=send_body,
                include_cors=False,
            )
            return False

        return True

    def _send_json_response(
        self,
        data: Any,
        status_code: int = 200,
        send_body: bool = True,
        include_cors: bool = True,
    ) -> None:
        payload = json.dumps(data, indent=2, allow_nan=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload) if send_body else 0))
        cors_origin = self._validated_origin() if include_cors else None
        self._send_security_headers(allow_cors_origin=cors_origin)
        self.end_headers()
        if send_body:
            self.wfile.write(payload)

    def _send_bytes_response(
        self,
        content: bytes,
        content_type: str,
        status_code: int = 200,
        filename: Optional[str] = None,
        send_body: bool = True,
    ) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(content) if send_body else 0))
        self._send_security_headers(allow_cors_origin=self._validated_origin())
        self.end_headers()
        if send_body:
            self.wfile.write(content)

    def _parse_json_body(self) -> Dict[str, Any]:
        """Read and strictly validate JSON object request body with 1 MiB cap."""
        raw_cl = self.headers.get("Content-Length")
        if raw_cl is None or raw_cl.strip() == "":
            content_length = 0
        else:
            try:
                content_length = int(raw_cl.strip())
            except ValueError as exc:
                raise _RequestValidationError("Invalid Content-Length header.", HTTPStatus.BAD_REQUEST) from exc
            if content_length < 0:
                raise _RequestValidationError("Negative Content-Length header.", HTTPStatus.BAD_REQUEST)

        if content_length > MAX_BODY_BYTES:
            raise _RequestValidationError(
                f"Payload too large: exceeds maximum limit of {MAX_BODY_BYTES} bytes (1 MiB).",
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )

        if content_length == 0:
            return {}

        raw_bytes = self.rfile.read(content_length)
        try:
            raw_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _RequestValidationError("Request body must be valid UTF-8.", HTTPStatus.BAD_REQUEST) from exc

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise _RequestValidationError(f"Malformed JSON payload: {exc.msg}", HTTPStatus.BAD_REQUEST) from exc

        if not isinstance(parsed, dict):
            raise _RequestValidationError("JSON request body must be a JSON object.", HTTPStatus.BAD_REQUEST)

        return parsed

    def _has_path_traversal(self, raw_url_path: str) -> bool:
        """Detect null bytes, backslashes, or '..' segments in raw or URL-decoded paths."""
        if "\x00" in raw_url_path or "\\" in raw_url_path:
            return True
        decoded_once = urllib.parse.unquote(raw_url_path)
        decoded_twice = urllib.parse.unquote(decoded_once)
        for candidate in (raw_url_path, decoded_once, decoded_twice):
            if "\x00" in candidate or "\\" in candidate:
                return True
            parts = candidate.split("/")
            if any(part == ".." for part in parts):
                return True
        return False

    def _resolve_static_file(self, url_path: str) -> Optional[Path]:
        """Safely resolve a static file inside public_directory; raise PermissionError on escape."""
        public_root = self.public_directory.resolve()
        decoded = urllib.parse.unquote(url_path)
        rel_str = decoded.lstrip("/")
        if not rel_str or rel_str == "index.html":
            candidate = (public_root / "index.html").resolve()
        else:
            candidate = (public_root / rel_str).resolve()
            if candidate.is_dir():
                candidate = (candidate / "index.html").resolve()

        if not candidate.is_relative_to(public_root):
            raise PermissionError("Path escapes static public root.")

        if candidate.exists() and candidate.is_file():
            return candidate
        return None

    def _handle_get_or_head(self, send_body: bool = True) -> None:
        if not self._check_host_and_origin(send_body=send_body):
            return

        parsed = urllib.parse.urlparse(self.path)
        raw_path = parsed.path

        if self._has_path_traversal(raw_path):
            self._send_json_response(
                {"error": "Forbidden: path traversal rejected"},
                status_code=HTTPStatus.FORBIDDEN,
                send_body=send_body,
            )
            return

        path = raw_path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)

        # 1. Health check
        if path in ("/health", "/api/health"):
            self._send_json_response(
                {
                    "status": "ok",
                    "service": "badge3d-coin-generator",
                    "version": __version__,
                },
                send_body=send_body,
            )
            return

        # 2. Presets endpoint
        if path == "/api/presets":
            self._send_json_response(
                {
                    "presets": STUDIO_PRESETS,
                    "count": len(STUDIO_PRESETS),
                },
                send_body=send_body,
            )
            return

        # 3. Stats calculation endpoint
        if path == "/api/stats":
            try:
                radius = validate_finite_float(query.get("radius", ["20.0"])[0], "radius", 1.0, 100.0)
                thickness = validate_finite_float(query.get("thickness", ["3.0"])[0], "thickness", 0.5, 25.0)
                rim_width = validate_finite_float(query.get("rim_width", ["1.8"])[0], "rim_width", 0.1, 20.0)
                rim_height = validate_finite_float(query.get("rim_height", ["0.6"])[0], "rim_height", 0.0, 10.0)

                params = CoinParameters(
                    radius=radius,
                    thickness=thickness,
                    rim_width=rim_width,
                    rim_height=rim_height,
                )
                stats = compute_physical_statistics(params)
                self._send_json_response(stats, send_body=send_body)
            except ValueError as exc:
                self._send_json_response({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST, send_body=send_body)
            return

        # 4. G-code Slicing GET endpoint
        if path == "/api/slice-gcode":
            try:
                from . import CoinGenerator
                from .slicer_engine import FilamentType, InfillPattern, SlicingConfig, slice_mesh

                preset_id = query.get("preset", [None])[0]
                if preset_id:
                    if resolve_preset(preset_id) is None:
                        raise ValueError(f"Unknown preset: {preset_id!r}")
                    generator = CoinGenerator(preset=preset_id)
                else:
                    r = validate_finite_float(query.get("radius", ["20.0"])[0], "radius", 1.0, 100.0)
                    th = validate_finite_float(query.get("thickness", ["3.0"])[0], "thickness", 0.5, 25.0)
                    generator = CoinGenerator(radius=r, thickness=th)

                layer_h = validate_finite_float(query.get("layer_height", ["0.20"])[0], "layer_height", 0.04, 1.0)
                infill_d = validate_finite_float(query.get("infill_density", ["0.20"])[0], "infill_density", 0.0, 1.0)
                nozzle_d = validate_finite_float(query.get("nozzle_diameter", ["0.40"])[0], "nozzle_diameter", 0.1, 2.0)

                pat_str = str(query.get("infill_pattern", ["rectilinear"])[0]).lower()
                try:
                    pat = InfillPattern(pat_str)
                except ValueError:
                    pat = InfillPattern.RECTILINEAR

                fil_str = str(query.get("filament_type", ["pla"])[0]).lower()
                try:
                    fil = FilamentType(fil_str)
                except ValueError:
                    fil = FilamentType.PLA

                cfg = SlicingConfig(
                    layer_height=layer_h,
                    infill_density=infill_d,
                    infill_pattern=pat,
                    filament_type=fil,
                    nozzle_diameter=nozzle_d,
                )
                mesh = generator.generate()
                result = slice_mesh(mesh, config=cfg)
                self._send_json_response(result.to_dict(), send_body=send_body)
            except ValueError as exc:
                self._send_json_response({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST, send_body=send_body)
            except Exception:
                self._send_json_response(
                    {"error": "Internal error while slicing coin mesh."},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    send_body=send_body,
                )
            return

        # 5. Unknown /api/* routes (allow existing static public/api/*.json like /api/netlify-ax.json)
        if path.startswith("/api/"):
            try:
                static_api = self._resolve_static_file(path)
            except PermissionError:
                self._send_json_response(
                    {"error": "Forbidden: path traversal rejected"},
                    status_code=HTTPStatus.FORBIDDEN,
                    send_body=send_body,
                )
                return
            if static_api is not None:
                mime, _ = mimetypes.guess_type(str(static_api))
                self._send_bytes_response(
                    static_api.read_bytes(),
                    mime or "application/json; charset=utf-8",
                    send_body=send_body,
                )
                return
            self._send_json_response(
                {"error": f"API endpoint not found: {path}"},
                status_code=HTTPStatus.NOT_FOUND,
                send_body=send_body,
            )
            return

        # 6. Clean legal routes (/terms, /privacy, /support)
        if path in LEGAL_ROUTES:
            try:
                legal_file = self._resolve_static_file("/" + LEGAL_ROUTES[path])
                if legal_file is not None:
                    self._send_bytes_response(
                        legal_file.read_bytes(),
                        "text/html; charset=utf-8",
                        send_body=send_body,
                    )
                    return
            except PermissionError:
                self._send_json_response(
                    {"error": "Forbidden"},
                    status_code=HTTPStatus.FORBIDDEN,
                    send_body=send_body,
                )
                return

        # 7. Root index.html
        if path in ("", "/index.html"):
            try:
                index_file = self._resolve_static_file("/index.html")
            except PermissionError:
                index_file = None
            if index_file is not None:
                self._send_bytes_response(
                    index_file.read_bytes(),
                    "text/html; charset=utf-8",
                    send_body=send_body,
                )
                return
            self._send_bytes_response(
                EMBEDDED_HTML_FALLBACK.encode("utf-8"),
                "text/html; charset=utf-8",
                send_body=send_body,
            )
            return

        # 8. Contained static file serving from public_directory
        try:
            file_target = self._resolve_static_file(raw_path)
        except PermissionError:
            self._send_json_response(
                {"error": "Forbidden: path escapes public root"},
                status_code=HTTPStatus.FORBIDDEN,
                send_body=send_body,
            )
            return

        if file_target is not None:
            mime, _ = mimetypes.guess_type(str(file_target))
            mime = mime or "application/octet-stream"
            if mime.startswith("text/") or mime in ("application/javascript", "application/json", "image/svg+xml"):
                if "charset=" not in mime:
                    mime = f"{mime}; charset=utf-8"
            self._send_bytes_response(file_target.read_bytes(), mime, send_body=send_body)
            return

        self._send_json_response(
            {"error": f"Resource not found: {raw_path}"},
            status_code=HTTPStatus.NOT_FOUND,
            send_body=send_body,
        )

    def do_OPTIONS(self) -> None:
        """Handle CORS pre-flight requests under strict Host and Origin allowlists."""
        if not self._check_host_and_origin(send_body=True):
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Content-Length", "0")
        self._send_security_headers(allow_cors_origin=self._validated_origin())
        self.end_headers()

    def do_HEAD(self) -> None:
        """Handle HEAD requests cleanly with 0 body bytes."""
        self._handle_get_or_head(send_body=False)

    def do_GET(self) -> None:
        """Handle GET requests for static assets, presets, health, legal pages, and stats."""
        self._handle_get_or_head(send_body=True)

    def do_POST(self) -> None:
        """Handle POST requests for mesh generation, slicing, edge milling, and 3D file exports."""
        if not self._check_host_and_origin(send_body=True):
            return

        parsed = urllib.parse.urlparse(self.path)
        if self._has_path_traversal(parsed.path):
            self._send_json_response(
                {"error": "Forbidden: path traversal rejected"},
                status_code=HTTPStatus.FORBIDDEN,
            )
            return

        path = parsed.path.rstrip("/")

        try:
            req_data = self._parse_json_body()
        except _RequestValidationError as exc:
            self._send_json_response({"error": str(exc)}, status_code=exc.status_code)
            return

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
            except ValueError as exc:
                self._send_json_response({"error": str(exc), "status": "failed"}, status_code=HTTPStatus.BAD_REQUEST)
            except Exception:
                self._send_json_response(
                    {"error": "Internal error during mesh generation.", "status": "failed"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return

        # 2. Binary STL Export endpoint
        if path == "/api/export-stl":
            try:
                params = parse_coin_params_from_dict(req_data)
                mesh = CoinMeshEngine(params).generate()
                stl_bytes = mesh_to_binary_stl_bytes(mesh, header_comment="badge3d-coin-generator")
                filename = f"coin-{params.radius:.1f}mm.stl"
                self._send_bytes_response(stl_bytes, "application/sla", filename=filename)
            except ValueError as exc:
                self._send_json_response({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)
            except Exception:
                self._send_json_response({"error": "Internal error during STL export."}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # 3. Wavefront OBJ Export endpoint
        if path == "/api/export-obj":
            try:
                params = parse_coin_params_from_dict(req_data)
                mesh = CoinMeshEngine(params).generate()
                obj_bytes = mesh_to_obj_text(mesh, object_name="Coin3D").encode("utf-8")
                filename = f"coin-{params.radius:.1f}mm.obj"
                self._send_bytes_response(obj_bytes, "text/plain; charset=utf-8", filename=filename)
            except ValueError as exc:
                self._send_json_response({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)
            except Exception:
                self._send_json_response({"error": "Internal error during OBJ export."}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # 3b. Binary GLTF (GLB) Export endpoint
        if path == "/api/export-glb":
            try:
                params = parse_coin_params_from_dict(req_data)
                mesh = CoinMeshEngine(params).generate()
                glb_bytes = mesh_to_glb_bytes(mesh)
                filename = f"coin-{params.radius:.1f}mm.glb"
                self._send_bytes_response(glb_bytes, "model/gltf-binary", filename=filename)
            except ValueError as exc:
                self._send_json_response({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)
            except Exception:
                self._send_json_response({"error": "Internal error during GLB export."}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # 3c. Text GLTF JSON Export endpoint
        if path == "/api/export-gltf":
            try:
                params = parse_coin_params_from_dict(req_data)
                mesh = CoinMeshEngine(params).generate()
                gltf_bytes = mesh_to_gltf_json(mesh).encode("utf-8")
                filename = f"coin-{params.radius:.1f}mm.gltf"
                self._send_bytes_response(gltf_bytes, "model/gltf+json; charset=utf-8", filename=filename)
            except ValueError as exc:
                self._send_json_response({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)
            except Exception:
                self._send_json_response({"error": "Internal error during glTF export."}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # 4. G-code Slicing endpoint
        if path == "/api/slice-gcode":
            try:
                from . import CoinGenerator
                from .slicer_engine import FilamentType, InfillPattern, SlicingConfig, slice_mesh

                preset_id = req_data.get("preset")
                if preset_id is not None and preset_id != "":
                    if resolve_preset(str(preset_id)) is None:
                        raise ValueError(f"Unknown preset: {preset_id!r}")
                    params = parse_coin_params_from_dict(req_data)
                    generator = CoinGenerator(
                        radius=params.radius,
                        thickness=params.thickness,
                        rim_width=params.rim_width,
                        rim_height=params.rim_height,
                        serrations=params.edge_reed_count,
                        resolution=min(96, params.radial_segments),
                        preset=None,
                    )
                    mesh = generator.generate()
                    radius_val = params.radius
                else:
                    params = parse_coin_params_from_dict(req_data)
                    mesh = CoinMeshEngine(params).generate()
                    radius_val = params.radius

                layer_h = validate_finite_float(req_data.get("layer_height", 0.20), "layer_height", 0.04, 1.0)
                infill_d = validate_finite_float(req_data.get("infill_density", 0.20), "infill_density", 0.0, 1.0)
                nozzle_d = validate_finite_float(req_data.get("nozzle_diameter", 0.40), "nozzle_diameter", 0.1, 2.0)

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

                cfg = SlicingConfig(
                    layer_height=layer_h,
                    infill_density=infill_d,
                    infill_pattern=pat,
                    filament_type=fil,
                    nozzle_diameter=nozzle_d,
                )
                result = slice_mesh(mesh, config=cfg)

                if req_data.get("format") == "gcode":
                    gcode_bytes = result.to_gcode().encode("utf-8")
                    filename = f"coin-{radius_val:.1f}mm.gcode"
                    self._send_bytes_response(gcode_bytes, "text/x-gcode; charset=utf-8", filename=filename)
                else:
                    self._send_json_response(result.to_dict())
            except ValueError as exc:
                self._send_json_response({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)
            except Exception:
                self._send_json_response({"error": "Internal error during G-code slicing."}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # 5. Edge profile summary endpoint
        if path == "/api/edge/profile":
            try:
                from .edge_milling import (
                    CompoundMillingSpec,
                    EdgeInscriptionSpec,
                    SecurityStampSpec,
                    SegmentedReedingSpec,
                    generate_edge_milling_profile_summary,
                )

                reed_count = validate_bounded_int(req_data.get("reed_count", 120), "reed_count", 0, 360)
                reed_depth = validate_finite_float(req_data.get("reed_depth", 0.25), "reed_depth", 0.0, 5.0)
                insc_depth = validate_finite_float(req_data.get("inscription_depth", 0.25), "inscription_depth", 0.0, 3.0)
                sec_grooves = validate_bounded_int(req_data.get("security_grooves", 64), "security_grooves", 1, 512)
                seg_sectors = validate_bounded_int(req_data.get("segmented_sectors", 0), "segmented_sectors", 0, 64)

                spec = CompoundMillingSpec(
                    reeding_profile=str(req_data.get("reeding_profile", "sinusoidal")),
                    reed_count=reed_count,
                    reed_depth=reed_depth,
                    inscription=EdgeInscriptionSpec(
                        text=str(req_data.get("inscription", "")),
                        mode=str(req_data.get("inscription_mode", "incuse")),
                        depth=insc_depth,
                    ) if req_data.get("inscription") else None,
                    security_stamp=SecurityStampSpec(
                        seed=str(req_data.get("security_seed", "")),
                        num_grooves=sec_grooves,
                    ) if req_data.get("security_seed") else None,
                    segmented=SegmentedReedingSpec(
                        reeded_sectors=seg_sectors,
                        reed_depth=reed_depth,
                    ) if seg_sectors > 0 else None,
                )
                summary = generate_edge_milling_profile_summary(spec)
                self._send_json_response(summary)
            except ValueError as exc:
                self._send_json_response({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)
            except Exception:
                self._send_json_response({"error": "Internal error computing edge profile."}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # 6. Cryptographic security stamp derivation endpoint
        if path == "/api/edge/crypto-stamp":
            try:
                from .edge_milling import derive_crypto_teeth_pattern

                seed = str(req_data.get("seed", "CHALLENGE-COIN-2026"))
                num_grooves = validate_bounded_int(req_data.get("num_grooves", 64), "num_grooves", 1, 512)
                base_depth = validate_finite_float(req_data.get("base_depth", 0.3), "base_depth", 0.0, 5.0)
                depth_variation = validate_finite_float(req_data.get("depth_variation", 0.15), "depth_variation", 0.0, 2.0)

                teeth = derive_crypto_teeth_pattern(seed, num_grooves)
                hash_digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
                self._send_json_response({
                    "seed": seed,
                    "sha256": hash_digest,
                    "num_grooves": num_grooves,
                    "base_depth_mm": base_depth,
                    "depth_variation_mm": depth_variation,
                    "sample_teeth_depths_mm": [round(base_depth + (t - 0.5) * depth_variation, 4) for t in teeth[:16]],
                    "parity_verification_checksum": hash_digest[:16],
                })
            except ValueError as exc:
                self._send_json_response({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)
            except Exception:
                self._send_json_response({"error": "Internal error computing crypto stamp."}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # 7. Edge text inscription mapping endpoint
        if path == "/api/edge/inscribe":
            try:
                from .edge_milling import evaluate_text_rim_distance

                text = str(req_data.get("text", "LIBERTY"))
                mode = str(req_data.get("mode", "incuse"))
                depth = validate_finite_float(req_data.get("depth", 0.25), "depth", 0.0, 3.0)
                diameter = validate_finite_float(req_data.get("diameter", 40.0), "diameter", 2.0, 200.0)
                thickness = validate_finite_float(req_data.get("thickness", 3.0), "thickness", 0.5, 25.0)
                repeats = validate_bounded_int(req_data.get("repeats", 1), "repeats", 1, 32)
                circumference = math.pi * diameter
                self._send_json_response({
                    "text": text,
                    "mode": mode,
                    "depth_mm": depth,
                    "diameter_mm": diameter,
                    "thickness_mm": thickness,
                    "circumference_mm": round(circumference, 2),
                    "repeats": repeats,
                    "char_pitch_mm": round(circumference / max(1, len(text) * repeats), 2),
                    "sample_midpoint_intensity": evaluate_text_rim_distance(text.upper(), 0.5, 0.5),
                })
            except ValueError as exc:
                self._send_json_response({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)
            except Exception:
                self._send_json_response({"error": "Internal error computing rim inscription."}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # 8. Unknown endpoint
        self._send_json_response({"error": f"Endpoint not found: {path}"}, status_code=HTTPStatus.NOT_FOUND)


def create_ui_server(
    host: str = "127.0.0.1",
    port: int = 8084,
    public_dir: Optional[PathLike] = None,
) -> ThreadingHTTPServer:
    """Instantiate and configure the ThreadingHTTPServer instance for the studio."""
    if public_dir is not None:
        resolved_public = safe_path(public_dir)
    else:
        resolved_public = Path(__file__).resolve().parent.parent.parent / "public"

    class _BoundCoinStudioRequestHandler(CoinStudioRequestHandler):
        public_directory = resolved_public

    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((host, port), _BoundCoinStudioRequestHandler)
    return server


def start_ui_server(
    host: str = "127.0.0.1",
    port: int = 8084,
    public_dir: Optional[PathLike] = None,
    open_browser: bool = False,
) -> None:
    """Start the Badge3D Coin Studio UI server and listen for incoming connections."""
    server = create_ui_server(host=host, port=port, public_dir=public_dir)
    url = f"http://{host}:{port}/"
    print("=" * 70)
    print(f"  Badge3D Coin Studio v{__version__} — Relief & Mesh Engine")
    print(f"  Server URL:    {url}")
    print(f"  API Docs:      {url}api/presets")
    print("  Dependencies:  Zero external dependencies (Pure Python Stdlib)")
    print("  Press Ctrl+C to stop server")
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
    parser.add_argument("--port", type=int, default=8084, help="Port number (default: 8084)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser")
    args = parser.parse_args()

    start_ui_server(host=args.host, port=args.port, open_browser=not args.no_browser)
