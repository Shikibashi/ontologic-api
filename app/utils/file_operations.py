"""
Atomic file operations for safe file writing.

Provides utilities for writing files atomically to prevent corruption
from partial writes during crashes or interruptions.
"""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from typing import Union, Any


def atomic_write(content: str, target_path: Union[str, Path]) -> None:
    """
    Write content to a file atomically.

    Uses a temporary file in the same directory and atomic rename to prevent
    partial writes from leaving truncated or corrupted files.

    Args:
        content: The content to write
        target_path: The target file path

    Raises:
        OSError: If write or rename fails
        PermissionError: If insufficient permissions

    Example:
        >>> from pathlib import Path
        >>> atomic_write("config data", Path("config.yml"))
        >>> atomic_write('{"key": "value"}', "config.json")

    Note:
        - Creates parent directories if they don't exist
        - File is closed before rename (required on some filesystems)
        - Uses os.fsync() to ensure data is written to disk
        - Atomic rename guarantees no partial writes (POSIX systems)
    """
    target_path = Path(target_path)
    target_dir = target_path.parent

    # Ensure parent directory exists
    target_dir.mkdir(parents=True, exist_ok=True)

    tmp_path = None
    try:
        # Create temporary file in same directory as target for atomic rename
        with NamedTemporaryFile(mode='w', dir=target_dir, delete=False, suffix='.tmp') as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())  # Ensure data is written to disk

        # Atomic rename (outside context manager to ensure file is closed)
        tmp_path.replace(target_path)
        tmp_path = None  # Mark as successfully moved

    except Exception:
        # Clean up temp file only if rename didn't succeed
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_json(data: Any, target_path: Union[str, Path], indent: int = 2) -> None:
    """
    Write JSON data to a file atomically.

    Serializes data to JSON and writes atomically using the same
    temporary file + rename pattern as atomic_write.

    Args:
        data: The data to serialize and write
        target_path: The target file path
        indent: JSON indentation level (default: 2)

    Raises:
        OSError: If write or rename fails
        PermissionError: If insufficient permissions
        TypeError: If data is not JSON serializable

    Example:
        >>> from pathlib import Path
        >>> atomic_write_json({"key": "value"}, Path("config.json"))
        >>> atomic_write_json([1, 2, 3], "data.json", indent=4)

    Note:
        - Uses atomic_write internally for consistency
        - Ensures formatted JSON with trailing newline
        - Creates parent directories if they don't exist
    """
    content = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
    atomic_write(content, target_path)
