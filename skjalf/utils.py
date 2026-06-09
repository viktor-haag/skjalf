"""Common utility functions for Skjalf.

This module provides reusable helpers that are independent of the UI
and business logic. Keeping them separate improves testability
and reduces duplication.
"""

from pathlib import Path
from typing import Union

from .config import IMAGE_EXTENSIONS, THUMBNAIL_EXTENSIONS, SKIP_DIR_PREFIXES


def is_image_file(path: Union[str, Path]) -> bool:
    """Return True if *path* has a recognized image extension.

    The check is case-insensitive and examines only the file suffix.
    """
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


def is_thumbnailable(path: Union[str, Path]) -> bool:
    """Return True if *path* can have a thumbnail generated.

    Thumbnail generation currently supports only JPEG and PNG formats.
    """
    return Path(path).suffix.lower() in THUMBNAIL_EXTENSIONS


def should_skip_dir(dirname: str) -> bool:
    """Return True if *dirname* should be skipped during directory scans.

    Directories like .skjalf, .git, .venv, etc. are ignored.
    """
    return any(dirname.startswith(prefix) for prefix in SKIP_DIR_PREFIXES)


def resolve_path(path: Union[str, Path]) -> Path:
    """Return an absolute resolved Path object for *path*."""
    return Path(path).expanduser().resolve()


def safe_delete(path: Path) -> None:
    """Delete *path* (file or directory) with error handling.

    Raises:
        OSError: If deletion fails due to permissions, disk errors, etc.
    """
    if path.is_dir():
        import shutil
        shutil.rmtree(path)
    else:
        path.unlink()


def truncate_text(text: str, max_length: int = 200) -> str:
    """Truncate *text* to *max_length* characters, adding ellipsis if truncated."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def relative_to_root(path: Path, root: Path) -> str:
    """Return a relative path string from *root* to *path*.

    Used for generating stable ChromaDB document IDs.
    """
    return path.resolve().relative_to(root.resolve()).as_posix()


def ensure_parent_dir_exists(path: Union[str, Path]) -> None:
    """Create the parent directory for *path* if it doesn't exist."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
