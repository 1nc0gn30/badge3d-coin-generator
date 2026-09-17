"""Tests for badge3d command line interface (CLI)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from badge3d_coin_generator.cli import (
    build_parser,
    handle_diagnostics,
    handle_generate,
    handle_presets,
    handle_test,
    main,
)


def test_cli_parser_creation() -> None:
    """Verify that CLI parser registers all subcommands and flags."""
    parser = build_parser()
    assert parser is not None

    # Test subcommand parsing
    args_gen = parser.parse_args(["generate", "-r", "25.0", "-t", "4.0", "-o", "test.stl"])
    assert args_gen.command == "generate"
    assert args_gen.radius == 25.0
    assert args_gen.thickness == 4.0
    assert args_gen.output == "test.stl"

    args_pre = parser.parse_args(["presets", "--json"])
    assert args_pre.command == "presets"
    assert args_pre.json is True

    args_srv = parser.parse_args(["serve", "--port", "9090", "--no-browser"])
    assert args_srv.command == "serve"
    assert args_srv.port == 9090
    assert args_srv.open_browser is False


def test_cli_presets_subcommand(capsys) -> None:
    """Verify presets listing and filtering."""
    parser = build_parser()

    # JSON presets output
    args = parser.parse_args(["presets", "--json"])
    exit_code = handle_presets(args)
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, dict)
    assert len(data) > 0

    # Filtered presets output
    args_filter = parser.parse_args(["presets", "--filter", "gold", "--json"])
    exit_code = handle_presets(args_filter)
    assert exit_code == 0
    captured_filter = capsys.readouterr()
    filter_data = json.loads(captured_filter.out)
    for k in filter_data:
        assert "gold" in k.lower() or "gold" in filter_data[k]["name"].lower()


def test_cli_generate_stl_binary(temp_output_dir: Path, capsys, stl_validator) -> None:
    """Verify generating binary STL from CLI."""
    out_file = temp_output_dir / "cli_coin_binary.stl"
    parser = build_parser()
    args = parser.parse_args([
        "generate",
        "--preset", "commemorative_gold",
        "-o", str(out_file),
        "-q",
    ])
    exit_code = handle_generate(args)
    assert exit_code == 0
    assert out_file.exists()

    is_valid, num_triangles, msg = stl_validator.validate(out_file.read_bytes())
    assert is_valid is True, msg
    assert num_triangles > 100


def test_cli_generate_stl_ascii(temp_output_dir: Path, capsys) -> None:
    """Verify generating ASCII STL from CLI."""
    out_file = temp_output_dir / "cli_coin_ascii.stl"
    parser = build_parser()
    args = parser.parse_args([
        "generate",
        "-r", "16.0",
        "-t", "2.5",
        "--ascii",
        "-o", str(out_file),
        "-q",
    ])
    exit_code = handle_generate(args)
    assert exit_code == 0
    assert out_file.exists()

    content = out_file.read_text(encoding="utf-8")
    assert content.startswith("solid ")
    assert "endsolid " in content


def test_cli_generate_obj(temp_output_dir: Path, capsys) -> None:
    """Verify generating Wavefront OBJ from CLI."""
    out_file = temp_output_dir / "cli_coin.obj"
    parser = build_parser()
    args = parser.parse_args([
        "generate",
        "-r", "16.0",
        "-t", "2.5",
        "-f", "obj",
        "-o", str(out_file),
        "-q",
    ])
    exit_code = handle_generate(args)
    assert exit_code == 0
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "v " in content
    assert "f " in content


def test_cli_generate_json(temp_output_dir: Path, capsys) -> None:
    """Verify generating JSON summary from CLI."""
    out_file = temp_output_dir / "cli_coin.json"
    parser = build_parser()
    args = parser.parse_args([
        "generate",
        "-r", "18.0",
        "-f", "json",
        "-o", str(out_file),
        "-q",
    ])
    exit_code = handle_generate(args)
    assert exit_code == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert "parameters" in data
    assert "physical_estimates" in data
    assert "mesh_stats" in data


def test_cli_diagnostics_subcommand(capsys) -> None:
    """Verify diagnostics subcommand runs and prints platform info."""
    parser = build_parser()
    args = parser.parse_args(["diagnostics"])
    exit_code = handle_diagnostics(args)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Python Runtime" in captured.out or "Platform" in captured.out


def test_cli_test_subcommand(capsys) -> None:
    """Verify test self-check subcommand runs."""
    parser = build_parser()
    args = parser.parse_args(["test"])
    exit_code = handle_test(args)
    assert exit_code == 0


def test_cli_main_help(capsys) -> None:
    """Verify main entrypoint with no args prints banner & help."""
    with patch.object(sys, "argv", ["badge3d"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "3D Coin Generator" in captured.out or "usage:" in captured.out
