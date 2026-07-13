"""Tests for ThumbnailService."""

from pathlib import Path

from skjalf.watcher.thumbnails import THUMBNAIL_SIZE, ThumbnailService


class TestThumbnailCache:
    def test_cache_hit(self, fake_jpeg_path):
        ts = ThumbnailService(cache_size=4)
        # First call generates and caches
        data = ts.get_thumbnail_for_path(Path(fake_jpeg_path))
        assert data is not None
        assert ts.is_cached(Path(fake_jpeg_path))
        # Second call returns cached data
        cached_data = ts.get_thumbnail_for_path(Path(fake_jpeg_path))
        assert cached_data == data

    def test_invalidate_removes_from_cache(self, fake_jpeg_path):
        ts = ThumbnailService(cache_size=4)
        ts.get_thumbnail_for_path(Path(fake_jpeg_path))
        assert ts.is_cached(Path(fake_jpeg_path))
        ts.invalidate(Path(fake_jpeg_path))
        assert not ts.is_cached(Path(fake_jpeg_path))

    def test_invalidate_nonexistent_no_error(self):
        ts = ThumbnailService()
        ts.invalidate(Path("/nonexistent/image.jpg"))


class TestThumbnailEviction:
    def test_lru_eviction(self, tmp_path, fake_image_path):
        """When cache is full, oldest entry is evicted."""
        cache_size = 3
        ts = ThumbnailService(cache_size=cache_size)

        # Create 3 distinct image files
        paths = []
        for i in range(3):
            p = tmp_path / f"img_{i}.png"
            p.write_bytes(Path(fake_image_path).read_bytes())
            paths.append(p)

        # Fill cache
        for p in paths:
            ts.get_thumbnail_for_path(p)

        assert len(ts.cache) == 3

        # Add a 4th image — should evict the oldest (img_0)
        p4 = tmp_path / "img_4.png"
        p4.write_bytes(Path(fake_image_path).read_bytes())
        ts.get_thumbnail_for_path(p4)

        assert len(ts.cache) == 3
        assert not ts.is_cached(paths[0])  # oldest evicted
        assert ts.is_cached(p4)

    def test_cache_size_one(self, tmp_path, fake_image_path):
        ts = ThumbnailService(cache_size=1)
        p1 = tmp_path / "a.png"
        p1.write_bytes(Path(fake_image_path).read_bytes())
        ts.get_thumbnail_for_path(p1)

        p2 = tmp_path / "b.png"
        p2.write_bytes(Path(fake_image_path).read_bytes())
        ts.get_thumbnail_for_path(p2)

        assert not ts.is_cached(p1)
        assert ts.is_cached(p2)


class TestThumbnailGeneration:
    def test_generate_thumbnail_from_path(self, fake_jpeg_path):
        ts = ThumbnailService(size=64)
        data = ts.get_thumbnail_for_path(Path(fake_jpeg_path))
        assert data is not None
        assert len(data) > 0

    def test_generate_thumbnail_from_bytes(self, fake_jpeg_path):
        ts = ThumbnailService(size=64)
        raw = Path(fake_jpeg_path).read_bytes()
        data = ts.get_thumbnail_for_bytes(Path(fake_jpeg_path), raw)
        assert data is not None

    def test_thumbnail_is_resized(self, tmp_path, fake_jpeg_path):
        """Thumbnail of a large image should be smaller than original."""
        # Create a larger image so the thumbnail is actually smaller
        from PIL import Image

        img = Image.new("RGB", (500, 500), color="blue")
        large_path = tmp_path / "large.jpg"
        img.save(large_path, format="JPEG")

        ts = ThumbnailService(size=32)
        data = ts.get_thumbnail_for_path(large_path)
        assert len(data) < large_path.stat().st_size

    def test_non_image_returns_none(self, fake_non_image_path):
        ts = ThumbnailService()
        data = ts.get_thumbnail_for_path(Path(fake_non_image_path))
        assert data is None

    def test_default_size(self):
        ts = ThumbnailService()
        # Default from config
        assert ts.size == THUMBNAIL_SIZE
