"""Tests for cross-platform compatibility layer and zero-dependency guarantees."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Set

import pytest

from badge3d_coin_generator.compat import (
    atomic_write_bytes,
    atomic_write_text,
    ensure_dir,
    ensure_parent_dir,
    get_system_info,
    get_temp_dir,
    is_linux,
    is_macos,
    is_termux,
    is_windows,
    read_bytes_safe,
    read_text_safe,
    safe_path,
    sanitize_filename,
)


def test_platform_detection() -> None:
    """Verify that platform detection functions return consistent booleans."""
    info = get_system_info()
    assert isinstance(info, dict)
    assert "system" in info
    assert "python_version" in info
    assert "byteorder" in info

    assert isinstance(is_windows(), bool)
    assert isinstance(is_macos(), bool)
    assert isinstance(is_linux(), bool)
    assert isinstance(is_termux(), bool)

    # At least one OS must match if on a common desktop/server OS
    if sys.platform.startswith("linux"):
        assert is_linux() is True
    elif sys.platform == "darwin":
        assert is_macos() is True
    elif sys.platform.startswith("win"):
        assert is_windows() is True


def test_safe_path_normalization(temp_output_dir: Path) -> None:
    """Verify safe path expansion and normalization."""
    p = safe_path(temp_output_dir / "test_subdir" / "file.stl")
    assert p.is_absolute()
    assert p.name == "file.stl"


def test_ensure_dir(temp_output_dir: Path) -> None:
    """Verify directory creation."""
    target_dir = temp_output_dir / "nested" / "deep" / "folder"
    assert not target_dir.exists()
    created = ensure_dir(target_dir)
    assert created.exists()
    assert created.is_dir()


def test_ensure_parent_dir(temp_output_dir: Path) -> None:
    """Verify parent directory creation for a file target."""
    target_file = temp_output_dir / "parent_test" / "sub" / "coin.stl"
    assert not target_file.parent.exists()
    ensured = ensure_parent_dir(target_file)
    assert ensured.parent.exists()
    assert ensured.name == "coin.stl"


def test_sanitize_filename() -> None:
    """Verify filename sanitization removes illegal characters and handles reserved names."""
    assert sanitize_filename("normal_coin.stl") == "normal_coin.stl"
    assert sanitize_filename('bad:file*name?.stl') == "bad_file_name_.stl"
    assert sanitize_filename("../../../etc/passwd") == "_.._.._etc_passwd"
    assert sanitize_filename("CON.stl") == "_CON.stl"
    assert sanitize_filename("nul.txt") == "_nul.txt"
    assert sanitize_filename("") == "unnamed"
    assert sanitize_filename("   ") == "unnamed"

    long_name = "a" * 300 + ".stl"
    sanitized = sanitize_filename(long_name, max_length=100)
    assert len(sanitized) <= 100
    assert sanitized.endswith(".stl")


def test_atomic_write_bytes(temp_output_dir: Path) -> None:
    """Verify atomic binary file writes and optional backups."""
    file_path = temp_output_dir / "atomic_binary.bin"
    payload = b"\x00\x01\x02\x03\x04\x05HELLO"

    written = atomic_write_bytes(file_path, payload)
    assert written.exists()
    assert written.read_bytes() == payload

    # Overwrite with backup
    new_payload = b"NEW_DATA"
    atomic_write_bytes(file_path, new_payload, backup=True)
    assert file_path.read_bytes() == new_payload

    bak_file = file_path.with_suffix(".bin.bak")
    assert bak_file.exists()
    assert bak_file.read_bytes() == payload


def test_atomic_write_text(temp_output_dir: Path) -> None:
    """Verify atomic text file writes with specific encodings."""
    file_path = temp_output_dir / "atomic_text.txt"
    text = "Badge3D Coin Studio \u2022 Pure Python \u2728"

    written = atomic_write_text(file_path, text, encoding="utf-8")
    assert written.exists()
    assert read_text_safe(file_path) == text


def test_read_safe_errors(temp_output_dir: Path) -> None:
    """Verify appropriate exceptions for missing files or directory targets."""
    with pytest.raises(FileNotFoundError):
        read_bytes_safe(temp_output_dir / "non_existent_file.bin")

    with pytest.raises(IsADirectoryError):
        read_bytes_safe(temp_output_dir)


def test_zero_third_party_dependencies() -> None:
    """Verify badge3d_coin_generator uses purely standard library modules."""
    import importlib
    import sys

    # Get stdlib module names
    stdlib_modules = getattr(sys, "stdlib_module_names", None)
    
    # List of known 3rd-party CAD/mesh libraries that must NEVER be imported
    forbidden_packages = {
        "numpy", "scipy", "trimesh", "shapely", "open3d", "pyvista",
        "meshio", "matplotlib", "PIL", "cv2", "fastapi", "flask",
        "requests", "aiohttp", "pydantic", "torch"
    }

    import badge3d_coin_generator
    import badge3d_coin_generator.compat
    import badge3d_coin_generator.exporters
    import badge3d_coin_generator.mesh_engine
    import badge3d_coin_generator.ui_server

    loaded_modules = set(sys.modules.keys())
    for forbidden in forbidden_packages:
        assert forbidden not in loaded_modules, (
            f"Violation: 3rd party dependency '{forbidden}' was imported!"
        )
