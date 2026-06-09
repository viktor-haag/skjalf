"""Thumbnail generation service.

Generates resized image thumbnails and caches them in memory (LRU policy).
"""

import io
from pathlib import Path

from PIL import Image
from loguru import logger

from ..config import THUMBNAIL_SIZE, THUMBNAIL_CACHE_SIZE


class ThumbnailService:
    """Generates and caches thumbnails for image files.

    Thumbnails are stored as bytes in a bounded in-memory cache.
    When the cache is full, the oldest entry is evicted.
    """

    def __init__(self, size: int = THUMBNAIL_SIZE, cache_size: int = THUMBNAIL_CACHE_SIZE) -> None:
        self.size = size
        self.cache: dict[str, bytes] = {}
        self.cache_size = cache_size

    def get_thumbnail_for_bytes(self, path: Path, data: bytes) -> bytes | None:
        """Generate a thumbnail from raw image data, caching the result."""
        key = str(path)
        if key in self.cache:
            return self.cache[key]

        try:
            img = Image.open(io.BytesIO(data))
            img.thumbnail((self.size, self.size))
            out = io.BytesIO()
            img.save(out, format=img.format)
            result = out.getvalue()
            self._cache_put(key, result)
            return result
        except Exception as e:
            logger.error(f"Failed to generate thumbnail for {path}: {e}")
            return None

    def get_thumbnail_for_path(self, path: Path) -> bytes | None:
        """Generate a thumbnail by reading the file from disk."""
        return self.get_thumbnail_for_bytes(path, path.read_bytes())

    def is_cached(self, path: Path) -> bool:
        """Return True if a thumbnail for *path* is already in the cache."""
        return str(path) in self.cache

    def invalidate(self, path: Path) -> None:
        """Remove the thumbnail for *path* from the cache."""
        self.cache.pop(str(path), None)

    def _cache_put(self, key: str, data: bytes) -> None:
        """Insert into cache, evicting the oldest entry if full."""
        if len(self.cache) >= self.cache_size:
            oldest = next(iter(self.cache))
            del self.cache[oldest]
        self.cache[key] = data
