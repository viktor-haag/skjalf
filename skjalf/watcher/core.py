"""Core orchestrator exposing synchronous commands and async events."""

import queue
from pathlib import Path

from loguru import logger

from .embedder import Embedder
from .events import (
    DirectoryUpdatedEvent,
    ErrorEvent,
    FSWatcherEvent,
    FileEntry,
    ProgressEvent,
    SearchResultEvent,
    ThumbnailReadyEvent,
)
from .fs_monitor import FSMonitor
from .models import FolderStore
from .thumbnails import ThumbnailService
from .worker import WorkerPool
from ..config import (
    CHROMA_DB_DIR_NAME,
    EMBED_PROGRESS_UPDATE_EVERY,
    EMBED_PROGRESS_FRACTION,
)
from ..utils import is_image_file, is_thumbnailable, should_skip_dir


class Core:
    """Central orchestrator owned by the UI process.

    Exposes synchronous commands (navigate, search, register) and publishes
    events through an internal queue consumed by the UI event bus.
    """

    def __init__(self) -> None:
        self.event_queue: queue.Queue = queue.Queue(maxsize=1024)
        self.folder_store = FolderStore()
        self.worker = WorkerPool()
        self.fs = FSMonitor()
        self.thumbnails = ThumbnailService()
        self.embedder = Embedder()
        self._current_path: Path | None = None
        self._registered: list[Path] = []
        self._search_cancel = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Load registered folders and start background embedding."""
        self._registered = [Path(p).resolve() for p in self.folder_store.list_folders()]
        for root in self._registered:
            self.embedder.init_folder(root)
            self._background_embed_folder(root)

    def stop(self) -> None:
        """Gracefully shut down background workers and the FS monitor."""
        self._search_cancel = True
        self.fs.stop()
        self.worker.shutdown()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def navigate_to(self, path: str) -> None:
        """Change the watched directory and emit the new contents."""
        self._current_path = Path(path).resolve()
        self.fs.stop()
        self.fs.start(str(self._current_path), self._on_fs_event)
        entries = self._scan_directory(self._current_path)
        self._publish(DirectoryUpdatedEvent(
            path=str(self._current_path), added=entries, removed=[], modified=[],
        ))

    def refresh_directory(self) -> None:
        """Re-scan the current directory and emit updates (FS monitor stays alive)."""
        if self._current_path is None:
            return
        entries = self._scan_directory(self._current_path)
        self._publish(DirectoryUpdatedEvent(
            path=str(self._current_path), added=entries, removed=[], modified=[],
        ))

    # ------------------------------------------------------------------
    # Thumbnails (lazy / on-demand)
    # ------------------------------------------------------------------

    def request_thumbnails(self, entries: list[FileEntry]) -> None:
        """Request thumbnails for *entries* (typically the currently visible items).

        Entries already cached in ThumbnailService are served from cache;
        missing ones are generated in a background thread.  In either case
        a ThumbnailReadyEvent is published so the UI can apply the data to
        the active model.
        """
        self._background_thumbnails(entries)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, n_results: int = 10) -> None:
        """Run a semantic search in the registered folder containing the current path."""
        self._search_cancel = False
        self._publish(SearchResultEvent(query=query, results=[], is_final=False))

        def _run():
            try:
                root = self._find_registered_root()
                if root is None:
                    self._publish(SearchResultEvent(query=query, results=[], is_final=True))
                    return
                results = self.embedder.query(root, query, n_results)
                entries = []
                for result in results:
                    full = Path(result["abs_path"])
                    entries.append(FileEntry(
                        path=str(full),
                        name=full.name,
                        is_dir=False,
                        size=full.stat().st_size,
                        modified=full.stat().st_mtime,
                    ))
                self._publish(SearchResultEvent(query, entries, is_final=True))
            except Exception as exc:
                logger.warning(f"[search] Exception: {exc}")
                self._publish(ErrorEvent(message=str(exc), context="search"))

        self.worker.run_io(_run)

    def clear_search(self) -> None:
        """Cancel any in-progress search and emit an empty final result."""
        self._search_cancel = True
        self._publish(SearchResultEvent(query="", results=[], is_final=True))

    # ------------------------------------------------------------------
    # Folder registration
    # ------------------------------------------------------------------

    def register_folder(self, path: str) -> None:
        root = Path(path).resolve()
        self.folder_store.add_folder(str(root))
        self._registered.append(root)
        self.embedder.init_folder(root)
        self._background_embed_folder(root)

    def deregister_folder(self, path: str) -> None:
        root = Path(path).resolve()
        self.folder_store.remove_folder(str(root))
        self._registered = [p for p in self._registered if p != root]
        self.embedder.close_folder(root)

    def _find_registered_root(self) -> Path | None:
        """Return the registered root that contains the current path, or None."""
        if self._current_path is None:
            return None
        for root in self._registered:
            try:
                self._current_path.relative_to(root)
                return root
            except ValueError:
                continue
        return None

    # ------------------------------------------------------------------
    # Directory scanning
    # ------------------------------------------------------------------

    def _scan_directory(self, path: Path) -> list[FileEntry]:
        entries: list[FileEntry] = []
        try:
            for child in path.iterdir():
                is_dir = child.is_dir()
                if is_dir and should_skip_dir(child.name):
                    continue
                stat = child.stat()
                entries.append(FileEntry(
                    path=str(child),
                    name=child.name,
                    is_dir=is_dir,
                    size=stat.st_size if not is_dir else None,
                    modified=stat.st_mtime,
                ))
        except OSError as e:
            logger.error(f"Error scanning directory: {path} — {e}")
        return entries

    def _find_images_recursive(self, root: Path) -> list[Path]:
        """Recursively find all image files under *root*, skipping hidden dirs."""
        images: list[Path] = []
        for dirpath, dirnames, filenames in root.walk():
            dirnames[:] = [d for d in dirnames if d != CHROMA_DB_DIR_NAME and not d.startswith(".")]
            for fn in filenames:
                full = dirpath / fn
                if is_image_file(full):
                    images.append(full)
        return images

    # ------------------------------------------------------------------
    # Background embedding
    # ------------------------------------------------------------------

    def _background_embed_folder(self, root: Path) -> None:
        """Recursively embed every image in a registered folder (background thread)."""

        def _run():
            images = self._find_images_recursive(root)
            total = len(images)
            logger.info(f"[embedder] embedding {total} images in {root}")
            self._publish(ProgressEvent(operation="embed", folder=str(root), current=0, total=total))
            step = max(1, total // EMBED_PROGRESS_FRACTION)
            for i, img in enumerate(images, start=1):
                self.embedder.embed_file(img)
                if i % step == 0 or i == total:
                    self._publish(ProgressEvent(operation="embed", folder=str(root), current=i, total=total))
                if i % EMBED_PROGRESS_UPDATE_EVERY == 0:
                    logger.info(f"[embedder] {i}/{total} done in {root}")
            logger.info(f"[embedder] finished embedding {total} images in {root}")

        self.worker.run_io(_run)

    def _background_embed(self, entries: list[FileEntry]) -> None:
        """Generate embeddings for individual entries in a worker thread."""

        def _run():
            for entry in entries:
                if entry.is_dir or not entry.path:
                    continue
                p = Path(entry.path)
                if CHROMA_DB_DIR_NAME in p.parts:
                    continue
                if is_image_file(p):
                    self.embedder.embed_file(p)

        self.worker.run_io(_run)

    # ------------------------------------------------------------------
    # Background thumbnails
    # ------------------------------------------------------------------

    def _background_thumbnails(self, entries: list[FileEntry]) -> None:
        """Generate (or fetch from cache) thumbnails in a worker thread.

        A ThumbnailReadyEvent is always published for thumbnailable files so
        the UI can apply the data to the currently active model, regardless
        of whether the thumbnail was already cached.
        """

        def _run():
            for entry in entries:
                if entry.is_dir or not entry.path:
                    continue
                p = Path(entry.path)
                if not is_thumbnailable(p):
                    continue
                data = self.thumbnails.get_thumbnail_for_path(p)
                if data:
                    self._publish(ThumbnailReadyEvent(path=entry.path, image_data=data))

        self.worker.run_io(_run)

    # ------------------------------------------------------------------
    # Filesystem event handler
    # ------------------------------------------------------------------

    def _on_fs_event(self, event_type: str, src: str, dst) -> None:
        """Handle raw filesystem events: embed new/modified files, publish watcher event."""
        self._publish(FSWatcherEvent(event_type=event_type, src_path=src, dst_path=dst))

        if self._current_path is None:
            return

        src_path = Path(src)
        if CHROMA_DB_DIR_NAME in src_path.parts:
            return
        if not is_image_file(src_path):
            return

        stat = src_path.stat() if src_path.exists() else None
        file_entry = FileEntry(
            path=src,
            name=src_path.name,
            is_dir=src_path.is_dir(),
            size=stat.st_size if stat and not src_path.is_dir() else None,
            modified=stat.st_mtime if stat else None,
        )

        if event_type == "created":
            self._background_embed([file_entry])
        elif event_type == "deleted":
            self.embedder.remove_file(src_path)
        elif event_type == "modified":
            self._background_embed([file_entry])
        elif event_type == "moved":
            self.embedder.remove_file(src_path)
            if dst and is_image_file(Path(dst)):
                self._background_embed([file_entry])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _publish(self, event) -> None:
        try:
            self.event_queue.put_nowait(event)
        except queue.Full:
            pass
