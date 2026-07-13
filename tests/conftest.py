"""Shared test fixtures for Skjalf."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image


@pytest.fixture()
def temp_dir():
    """Yield a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture()
def fake_image_path(temp_dir):
    """Create a minimal valid PNG image in temp_dir and return its path."""
    img = Image.new("RGB", (10, 10), color="red")
    path = temp_dir / "test.png"
    img.save(path)
    return path


@pytest.fixture()
def fake_jpeg_path(temp_dir):
    """Create a minimal valid JPEG image in temp_dir and return its path."""
    img = Image.new("RGB", (10, 10), color="blue")
    path = temp_dir / "test.jpg"
    img.save(path, format="JPEG")
    return path


@pytest.fixture()
def fake_non_image_path(temp_dir):
    """Create a non-image file in temp_dir and return its path."""
    path = temp_dir / "test.txt"
    path.write_text("not an image")
    return path


@pytest.fixture()
def sqlite_memory_url():
    """Yield an in-memory SQLite URL for FolderStore tests."""
    return "sqlite:///:memory:"


@pytest.fixture()
def mock_core(monkeypatch, tmp_path):
    """Return a Core instance with mocked heavy dependencies.

    Embedder, WorkerPool, and FSMonitor are replaced with MagicMock instances.
    FolderStore uses a real in-memory SQLite database (it's lightweight).
    ThumbnailService is kept real (it's fast).
    """
    from skjalf.watcher.core import Core

    mock_embedder = MagicMock()
    mock_worker = MagicMock()
    mock_fs = MagicMock()

    monkeypatch.setattr(
        "skjalf.watcher.core.Embedder", lambda: mock_embedder
    )
    monkeypatch.setattr(
        "skjalf.watcher.core.WorkerPool", lambda **kw: mock_worker
    )
    monkeypatch.setattr(
        "skjalf.watcher.core.FSMonitor", lambda: mock_fs
    )

    core = Core()
    # Replace folder_store with a real instance using in-memory SQLite
    db_url = f"sqlite:///{tmp_path}/test.db"
    core.folder_store = type(core.folder_store)(db_url)
    return core
