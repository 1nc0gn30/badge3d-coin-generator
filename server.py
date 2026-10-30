#!/usr/bin/env python3
"""
Badge3D Coin Generator — Sovereign Server Launcher.
Zero-dependency 3D Coin Mesh & Relief Studio on port 8084.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from badge3d_coin_generator.ui_server import start_ui_server

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Badge3D Coin Studio UI Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", "-p", type=int, default=8084, help="Port to listen on (default: 8084)")
    args = parser.parse_args()

    print(f"✦ Starting Badge3D Coin Studio on http://{args.host}:{args.port}")
    start_ui_server(host=args.host, port=args.port, open_browser=False)
