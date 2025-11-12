"""
Utility module for secure temporary file handling.

Provides context managers and utilities for creating temporary files with
proper security permissions and guaranteed cleanup.
"""

import tempfile
import os
import stat
from contextlib import contextmanager
from typing import Generator


@contextmanager
def secure_temp_file(suffix: str = "", content: bytes = b"") -> Generator[str, None, None]:
    """
    Create a secure temporary file with restricted permissions.

    This context manager creates a temporary file with restricted permissions
    (owner read/write only) and guarantees cleanup even if exceptions occur.

    Args:
        suffix (str): File suffix (e.g., ".pdf", ".docx"). Defaults to empty string.
        content (bytes): Optional content to write to the file. Defaults to empty bytes.

    Yields:
        str: The path to the temporary file.

    Example:
        >>> with secure_temp_file(suffix=".pdf", content=pdf_bytes) as tmp_path:
        ...     result = process_pdf(tmp_path)

    Note:
        The temporary file is automatically deleted when exiting the context,
        even if an exception occurs during processing.
    """
    # Set umask to create file with owner-only permissions atomically
    old_umask = os.umask(0o177)  # 177 = 777 - 600, results in 600 permissions
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode='wb') as tmp_file:
            if content:
                tmp_file.write(content)
            tmp_path = tmp_file.name
    finally:
        # Restore original umask immediately
        os.umask(old_umask)

    try:
        yield tmp_path
    finally:
        # Guaranteed cleanup with error suppression
        try:
            os.unlink(tmp_path)
        except OSError:
            # File already deleted or permission issue - ignore
            pass


def create_temp_file_with_content(content: bytes, suffix: str = "") -> str:
    """
    Create a temporary file with content and return its path.

    Warning: This function does NOT automatically clean up the file.
    Use secure_temp_file() context manager for automatic cleanup.

    Args:
        content (bytes): Content to write to the file.
        suffix (str): File suffix (e.g., ".pdf", ".docx").

    Returns:
        str: Path to the created temporary file.

    Note:
        The caller is responsible for deleting the file when done.
        Consider using secure_temp_file() instead for automatic cleanup.
    """
    # Set umask to create file with owner-only permissions atomically
    old_umask = os.umask(0o177)  # 177 = 777 - 600, results in 600 permissions
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode='wb') as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name
    finally:
        # Restore original umask immediately
        os.umask(old_umask)

    return tmp_path


def cleanup_temp_file(file_path: str) -> bool:
    """
    Safely delete a temporary file.

    Args:
        file_path (str): Path to the file to delete.

    Returns:
        bool: True if file was successfully deleted, False otherwise.
    """
    try:
        os.unlink(file_path)
        return True
    except OSError:
        return False