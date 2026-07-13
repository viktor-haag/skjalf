"""Tests for skjalf.utils functions."""

from pathlib import Path

import pytest

from skjalf.utils import (
    ensure_parent_dir_exists,
    is_image_file,
    is_thumbnailable,
    relative_to_root,
    resolve_path,
    safe_delete,
    should_skip_dir,
    truncate_text,
)


class TestIsImageFile:
    @pytest.mark.parametrize(
        "ext",
        [
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".bmp",
            ".webp",
            ".tiff",
            ".tif",
            ".ico",
            ".heic",
            ".heif",
        ],
    )
    def test_supported_extensions(self, ext):
        assert is_image_file(Path(f"test{ext}"))

    @pytest.mark.parametrize("ext", [".PNG", ".JPG", ".JPEG", ".GIF"])
    def test_case_insensitive(self, ext):
        assert is_image_file(Path(f"test{ext}"))

    @pytest.mark.parametrize("ext", [".txt", ".mp4", ".pdf"])
    def test_unsupported_extensions(self, ext):
        assert not is_image_file(Path(f"test{ext}"))


class TestIsThumbnailable:
    @pytest.mark.parametrize("ext", [".jpg", ".jpeg", ".png"])
    def test_thumbnailable(self, ext):
        assert is_thumbnailable(Path(f"test{ext}"))

    @pytest.mark.parametrize("ext", [".gif", ".bmp", ".webp", ".txt"])
    def test_not_thumbnailable(self, ext):
        assert not is_thumbnailable(Path(f"test{ext}"))


class TestShouldSkipDir:
    @pytest.mark.parametrize("name", [".git", ".skjalf", ".venv", ".DS_Store", ".svn"])
    def test_hidden_dirs_skipped(self, name):
        assert should_skip_dir(name)

    @pytest.mark.parametrize("name", ["images", "photos", "my_folder", "data"])
    def test_normal_dirs_not_skipped(self, name):
        assert not should_skip_dir(name)


class TestTruncateText:
    def test_no_truncation_needed(self):
        assert truncate_text("hello", 10) == "hello"

    def test_exact_length(self):
        assert truncate_text("hello", 5) == "hello"

    def test_truncation_with_ellipsis(self):
        result = truncate_text("hello world", 8)
        assert len(result) == 8
        assert result.endswith("...")
        assert result.startswith("hel")

    def test_empty_string(self):
        assert truncate_text("", 10) == ""


class TestResolvePath:
    def test_absolute_path(self, tmp_path):
        p = tmp_path / "sub" / "file.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
        assert resolve_path(str(p)).is_absolute()

    def test_relative_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = Path("relative.txt")
        p.touch()
        resolved = resolve_path("relative.txt")
        assert resolved == tmp_path / "relative.txt"


class TestRelativeToRoot:
    def test_same_directory(self, temp_dir):
        file_path = temp_dir / "image.png"
        file_path.touch()
        assert relative_to_root(file_path, temp_dir) == "image.png"

    def test_nested_directory(self, temp_dir):
        sub = temp_dir / "sub" / "deep"
        sub.mkdir(parents=True)
        file_path = sub / "image.png"
        file_path.touch()
        assert relative_to_root(file_path, temp_dir) == "sub/deep/image.png"

    def test_cross_root_raises(self, temp_dir):
        other = Path("/tmp/other")
        file_path = temp_dir / "image.png"
        file_path.touch()
        with pytest.raises(ValueError):
            relative_to_root(file_path, other)


class TestEnsureParentDirExists:
    def test_creates_nested_parents(self, temp_dir):
        path = temp_dir / "a" / "b" / "c" / "file.txt"
        ensure_parent_dir_exists(path)
        assert path.parent.exists()

    def test_idempotent(self, temp_dir):
        path = temp_dir / "existing" / "file.txt"
        path.parent.mkdir(parents=True)
        ensure_parent_dir_exists(path)  # Should not raise


class TestSafeDelete:
    """Test safe_delete with temporary files."""

    def test_delete_file(self, temp_dir):
        file_path = temp_dir / "delete_me.txt"
        file_path.write_text("content")
        safe_delete(file_path)
        assert not file_path.exists()

    def test_delete_directory(self, temp_dir):
        dir_path = temp_dir / "to_delete"
        dir_path.mkdir()
        (dir_path / "nested.txt").write_text("content")
        safe_delete(dir_path)
        assert not dir_path.exists()

    def test_delete_file_raises_on_permission_error(self, temp_dir, monkeypatch):
        """OSError should propagate for files we can't delete."""
        file_path = temp_dir / "readonly.txt"
        file_path.write_text("content")
        monkeypatch.setattr(
            Path,
            "unlink",
            lambda self: (_ for _ in ()).throw(PermissionError("perm denied")),
        )
        with pytest.raises(OSError):
            safe_delete(file_path)
