"""Event definitions for Core → UI communication.

All events are plain dataclasses published to a ``queue.Queue`` by the Core
orchestrator and consumed by the UI-side EventBus, which re-emits them as
Qt signals.
"""

from dataclasses import dataclass


@dataclass
class FileEntry:
    """Represents a file or directory entry in the model."""

    path: str
    name: str
    is_dir: bool
    size: int | None = None
    modified: float | None = None
    thumbnail_data: bytes | None = None


@dataclass
class DirectoryUpdatedEvent:
    """Emitted when the watched directory changes (navigation or refresh)."""

    path: str
    added: list[FileEntry]
    removed: list[str]
    modified: list[FileEntry]


@dataclass
class ThumbnailReadyEvent:
    """Emitted when a thumbnail has been generated (or fetched from cache)."""

    path: str
    image_data: bytes


@dataclass
class SearchResultEvent:
    """Emitted when a batch of search results is ready.

    Intermediate batches have ``is_final=False``; the last batch has ``is_final=True``.
    """

    query: str
    results: list[FileEntry]
    is_final: bool


@dataclass
class FSWatcherEvent:
    """Emitted for raw filesystem watcher events (create/delete/modify/move)."""

    event_type: str  # "created", "deleted", "modified", "moved"
    src_path: str
    dst_path: str | None = None


@dataclass
class ErrorEvent:
    """Emitted when an error occurs in a background task."""

    message: str
    context: str | None = None


@dataclass
class ProgressEvent:
    """Emitted to track long-running operations (embedding, file ops)."""

    operation: str
    current: int
    total: int
    folder: str | None = None


@dataclass
class FolderPendingUpdated:
    """Emitted when the number of unembedded files in a folder changes."""

    folder: str
    pending_count: int  # Number of files that need embedding


@dataclass
class EmbeddingStarted:
    """Emitted when the user manually starts embedding for a folder."""

    folder: str


@dataclass
class EmbeddingCancelled:
    """Emitted when the user pauses/cancels an in-progress embedding."""

    folder: str
