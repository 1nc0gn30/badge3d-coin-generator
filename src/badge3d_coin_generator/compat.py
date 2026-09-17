"""Cross-platform compatibility and safe I/O layer for badge3d-coin-generator.

Provides robust atomic binary/text file writes, safe path normalization,
encoding fallbacks, and environment detection across Linux, macOS, Windows,
and Termux (Android).
"""

from __future__ import annotations

import os
import platform
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Union

# Common path type alias
PathLike = Union[str, Path, os.PathLike]


def is_windows() -> bool:
    """Return True if running on Windows."""
    return sys.platform.startswith("win") or os.name == "nt"


def is_macos() -> bool:
    """Return True if running on macOS (Darwin)."""
    return sys.platform == "darwin"


def is_linux() -> bool:
    """Return True if running on Linux (including Android/Termux)."""
    return sys.platform.startswith("linux")


def is_termux() -> bool:
    """Return True if running inside Termux on Android."""
    return "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux/files")


def get_system_info() -> Dict[str, Any]:
    """Retrieve detailed system, OS, and platform information."""
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "python_compiler": platform.python_compiler(),
        "byteorder": sys.byteorder,
        "is_windows": is_windows(),
        "is_macos": is_macos(),
        "is_linux": is_linux(),
        "is_termux": is_termux(),
    }


def safe_path(path: PathLike) -> Path:
    """Normalize and expand a file or directory path safely.

    Expands user tilde (~), environment variables where needed, and returns an
    absolute Path object with normalized separators.
    """
    if isinstance(path, Path):
        p = path
    else:
        p = Path(os.path.expandvars(str(path)))
    return p.expanduser().resolve()


def ensure_dir(path: PathLike) -> Path:
    """Ensure that a directory exists, creating all parent directories if needed.

    Returns the resolved Path object.
    """
    p = safe_path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_parent_dir(filepath: PathLike) -> Path:
    """Ensure that the parent directory for the given file exists.

    Returns the resolved file Path.
    """
    p = safe_path(filepath)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def sanitize_filename(name: str, replacement: str = "_", max_length: int = 255) -> str:
    """Sanitize a filename by removing or replacing illegal filesystem characters.

    Handles Windows forbidden chars (\\ / : * ? \" < > |), control characters,
    and reserved Windows filenames (CON, PRN, AUX, NUL, COM1..9, LPT1..9).
    """
    # Replace illegal characters
    cleaned = re.sub(r'[\\/*?:"<>|\x00-\x1f]', replacement, name)
    cleaned = cleaned.strip(". ")

    if not cleaned:
        cleaned = "unnamed"

    # Check for reserved Windows device names
    base = cleaned.split(".")[0].upper()
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
    }
    if base in reserved:
        cleaned = f"_{cleaned}"

    # Truncate to maximum filesystem length
    if len(cleaned) > max_length:
        stem, ext = os.path.splitext(cleaned)
        allowed_stem = max(1, max_length - len(ext))
        cleaned = f"{stem[:allowed_stem]}{ext}"

    return cleaned


def get_temp_dir() -> Path:
    """Get the appropriate temporary directory for the current platform.

    Respects Termux prefix if present, otherwise system tempfile.gettempdir().
    """
    if is_termux():
        termux_tmp = Path("/data/data/com.termux/files/usr/tmp")
        if termux_tmp.exists():
            return termux_tmp
    return Path(tempfile.gettempdir()).resolve()


def atomic_write_bytes(
    filepath: PathLike,
    data: bytes,
    backup: bool = False,
    max_retries: int = 5,
    retry_delay: float = 0.05,
) -> Path:
    """Write binary data to a file atomically.

    Writes to a temporary file in the destination's parent directory, flushes and
    syncs to disk, then performs an atomic rename/replace (os.replace).
    Includes retry logic for Windows file lock collisions (antivirus/indexers).

    Args:
        filepath: Destination file path.
        data: Binary payload to write.
        backup: If True, creates a '.bak' copy of any existing destination file.
        max_retries: Number of retry attempts on Windows permission errors.
        retry_delay: Initial delay in seconds between retries.

    Returns:
        The resolved Path of the written file.
    """
    dest = ensure_parent_dir(filepath)
    parent_dir = dest.parent

    # Create temporary file in the same directory to guarantee same filesystem
    temp_filename = f".{dest.name}.{uuid.uuid4().hex[:8]}.tmp"
    temp_path = parent_dir / temp_filename

    try:
        with open(temp_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        # Handle backup if requested and destination exists
        if backup and dest.exists():
            bak_path = dest.with_suffix(dest.suffix + ".bak")
            try:
                if bak_path.exists():
                    bak_path.unlink()
                dest.rename(bak_path)
            except OSError:
                pass

        # Atomic replace with retries for Windows locking quirks
        last_err: Optional[Exception] = None
        delay = retry_delay
        for attempt in range(max_retries):
            try:
                os.replace(temp_path, dest)
                last_err = None
                break
            except (PermissionError, OSError) as err:
                last_err = err
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise last_err

    finally:
        # Clean up temporary file if still exists
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    return dest


def atomic_write_text(
    filepath: PathLike,
    text: str,
    encoding: str = "utf-8",
    errors: str = "replace",
    newline: Optional[str] = None,
    backup: bool = False,
    max_retries: int = 5,
) -> Path:
    """Write text data to a file atomically with specified encoding.

    Args:
        filepath: Destination file path.
        text: Text string to write.
        encoding: Character encoding (default: 'utf-8').
        errors: Error handling scheme for encoding.
        newline: Line ending control (e.g., '\\n' for POSIX, '\\r\\n' for Windows, None for default).
        backup: If True, creates a '.bak' copy of existing file.
        max_retries: Number of retries on atomic rename failure.

    Returns:
        The resolved Path of the written file.
    """
    dest = ensure_parent_dir(filepath)
    parent_dir = dest.parent

    temp_filename = f".{dest.name}.{uuid.uuid4().hex[:8]}.tmp"
    temp_path = parent_dir / temp_filename

    try:
        with open(temp_path, "w", encoding=encoding, errors=errors, newline=newline) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())

        if backup and dest.exists():
            bak_path = dest.with_suffix(dest.suffix + ".bak")
            try:
                if bak_path.exists():
                    bak_path.unlink()
                dest.rename(bak_path)
            except OSError:
                pass

        last_err: Optional[Exception] = None
        delay = 0.05
        for attempt in range(max_retries):
            try:
                os.replace(temp_path, dest)
                last_err = None
                break
            except (PermissionError, OSError) as err:
                last_err = err
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise last_err

    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    return dest


def read_bytes_safe(filepath: PathLike) -> bytes:
    """Read bytes from a file safely.

    Raises:
        FileNotFoundError: If the file does not exist.
        IsADirectoryError: If the path points to a directory.
    """
    p = safe_path(filepath)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    if p.is_dir():
        raise IsADirectoryError(f"Expected a file, but found a directory: {p}")
    with open(p, "rb") as f:
        return f.read()


def read_text_safe(
    filepath: PathLike,
    encodings: Sequence[str] = ("utf-8", "utf-8-sig", "latin-1", "cp1252"),
) -> str:
    """Read text from a file, attempting a list of encodings in sequence.

    Args:
        filepath: Path to the text file.
        encodings: Sequence of encodings to try in order.

    Returns:
        The decoded text content.

    Raises:
        FileNotFoundError: If the file does not exist.
        UnicodeDecodeError: If none of the encodings succeeded.
    """
    raw_bytes = read_bytes_safe(filepath)
    last_error: Optional[UnicodeDecodeError] = None

    for enc in encodings:
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError as err:
            last_error = err

    if last_error is not None:
        raise last_error
    return raw_bytes.decode("utf-8", errors="replace")
