"""Central configuration for Skjalf.

This module contains all tunable constants and default values used throughout
the application. By centralizing configuration, we make the codebase easier
to maintain and adjust.
"""

from pathlib import Path

# ------------------------------------------------------------------
# Paths and directories
# ------------------------------------------------------------------

# Hidden directory placed inside registered folders for ChromaDB storage
CHROMA_DB_DIR_NAME = ".skjalf"

# ------------------------------------------------------------------
# UI dimensions (in pixels)
# ------------------------------------------------------------------

ICON_SIZE = (64, 64)  # Thumbnail icon size in the grid
GRID_SIZE = (140, 140)  # Grid cell size
THUMBNAIL_SIZE = 128  # Generated thumbnail size
THUMBNAIL_CACHE_SIZE = 1024  # Max thumbnails in memory

TOOLBAR_ICON_SIZE = (24, 24)  # Toolbar button icons
SIDEBAR_ICON_SIZE = (16, 16)  # Folder row icon

DIALOG_SIZE = (400, 150)  # File operation dialog size

# ------------------------------------------------------------------
# Behavior timings
# ------------------------------------------------------------------

DEBOUNCE_SCROLL_MS = 250  # Delay before requesting visible thumbnails
FS_POLL_INTERVAL_SEC = 0.05  # Event queue polling interval (seconds)

# ------------------------------------------------------------------
# Worker counts
# ------------------------------------------------------------------

THREAD_WORKERS = 4
PROCESS_WORKERS = 2

# ------------------------------------------------------------------
# Image file extensions
# ------------------------------------------------------------------

# All image formats that the application can recognize
IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp",
    ".webp", ".tiff", ".tif", ".ico", ".heic", ".heif",
}

# Formats that support thumbnail generation
THUMBNAIL_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# ------------------------------------------------------------------
# Embedding model
# ------------------------------------------------------------------

EMBEDDING_MODEL_NAME = "kakaobrain/align-base"
EMBEDDING_DEVICE = "cpu"  # Default device for model inference

# ------------------------------------------------------------------
# ChromaDB configuration
# ------------------------------------------------------------------

CHROMA_COLLECTION_NAME = "image_embeddings"
CHROMA_METRIC = "cosine"

# ------------------------------------------------------------------
# Progress reporting
# ------------------------------------------------------------------

EMBED_PROGRESS_UPDATE_EVERY = 10  # Log and emit progress every N images
EMBED_PROGRESS_FRACTION = 0.01  # Emit progress at 1% increments

# ------------------------------------------------------------------
# Error handling
# ------------------------------------------------------------------

MAX_DISPLAY_ERROR_LENGTH = 200  # Truncate long error messages in UI

# ------------------------------------------------------------------
# Miscellaneous
# ------------------------------------------------------------------

# Hidden directory placed inside registered folders
HIDDEN_DIR_NAME = ".skjalf"

# File entries that should be skipped during scanning
SKIP_DIR_PREFIXES = (".",)


# ------------------------------------------------------------------
# Database paths
# ------------------------------------------------------------------

def _default_db_path() -> str:
    cache_dir = Path.home() / ".cache" / "skjalf"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{cache_dir / 'skjalf.db'}"


# Default SQLite database for folder registrations
DB_PATH = _default_db_path()

# ------------------------------------------------------------------
# UI appearance
# ------------------------------------------------------------------

SIDEBAR_WIDTH = 200  # Fixed width of sidebar (pixels)
HELP_WINDOW_SIZE = (420, 340)  # Help dialog dimensions

# ------------------------------------------------------------------
# Search behavior
# ------------------------------------------------------------------

DEBOUNCE_SEARCH_MS = 300  # Search bar debounce interval
SEARCH_RESULTS_MIN = 1
SEARCH_RESULTS_MAX = 1000
SEARCH_RESULTS_DEFAULT = 10

# ------------------------------------------------------------------
# Face search
# ------------------------------------------------------------------

PERSONS_DB_PATH = str(Path.home() / ".cache" / "skjalf" / "persons.db")
PERSONS_COLLECTION_NAME = "persons"
FACE_EMBEDDING_MODEL_NAME = "hf_hub:gaunernst/vit_tiny_patch8_112.arcface_ms1mv3"
FACE_INPUT_SIZE = 112
FACE_EMBEDDING_DIM = 512
