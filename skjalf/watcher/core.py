"""Core orchestrator exposing synchronous commands and async events."""

import queue
from pathlib import Path

from loguru import logger

from .embedder import Embedder
from .events import (
    DirectoryUpdatedEvent,
    EmbeddingCancelled,
    EmbeddingStarted,
    ErrorEvent,
    FSWatcherEvent,
    FileEntry,
    FolderPendingUpdated,
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
        # Manual embedding state tracking
        self._folder_pending_count: dict[Path, int] = {}   # folder → unembedded file count
        self._embed_cancel: dict[Path, bool] = {}           # folder → cancel flag

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Load registered folders and initialize per-folder databases."""
        self._registered = [Path(p).resolve() for p in self.folder_store.list_folders()]
        for root in self._registered:
            self.embedder.init_folder(root)
        # Clean up dangling ChromaDB entries before scanning
        for root in self._registered:
            removed = self.embedder.remove_all_dangling(root)
            if removed > 0:
                logger.info(f"[core] removed {removed} dangling entry(ies) from {root}")
        # Scan each folder to determine pending count (no automatic embedding)
        for root in self._registered:
            self._update_pending_count(root)
        # Start watching all registered folders
        paths = [str(r) for r in self._registered]
        if paths:
            self.fs.start(paths, self._on_fs_event)

    def stop(self) -> None:
        """Gracefully shut down background workers and the FS monitor."""
        self._search_cancel = True
        self.fs.stop()
        self.worker.shutdown()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def navigate_to(self, path: str) -> None:
        """Change the current directory and emit the new contents.

        Note: The FS monitor continues watching *all registered folders*,
        so this only changes the UI's active directory context.
        """
        self._current_path = Path(path).resolve()
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
                    if not full.exists():
                        logger.warning(f"[search] skipping deleted file: {full}")
                        continue
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
        self._update_pending_count(root)

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
    # Pending count detection
    # ------------------------------------------------------------------

    def _update_pending_count(self, root: Path) -> None:
        """Reconcile disk files vs ChromaDB and update the pending count.

        Files on disk that are NOT in ChromaDB are considered "pending"
        (need embedding).
        """
        images = self._find_images_recursive(root)
        if not images:
            pending = 0
        else:
            pending = sum(1 for img in images if self.embedder.get_stored_mtime(img) is None)

        self._folder_pending_count[root] = pending
        self._publish(FolderPendingUpdated(folder=str(root), pending_count=pending))

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

            step = max(1, int(total * EMBED_PROGRESS_FRACTION))
            for i, img in enumerate(images, start=1):
                # Check cancel flag between files
                if self._embed_cancel.get(root, False):
                    logger.info(f"[embedder] cancelled after {i-1}/{total} images in {root}")
                    return

                self.embedder.embed_file(img)
                if i % step == 0 or i == total:
                    self._publish(ProgressEvent(operation="embed", folder=str(root), current=i, total=total))
                if i % EMBED_PROGRESS_UPDATE_EVERY == 0:
                    logger.info(f"[embedder] {i}/{total} done in {root}")

            # Embedding completed — clear cancel flag and update pending count
            self._embed_cancel[root] = False
            self._folder_pending_count[root] = 0
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
        """Handle raw filesystem events: publish watcher event and update pending counts."""
        self._publish(FSWatcherEvent(event_type=event_type, src_path=src, dst_path=dst))

        src_path = Path(src)
        if CHROMA_DB_DIR_NAME in src_path.parts:
            return
        if not is_image_file(src_path):
            return

        # Update pending count for the folder containing this file (even if no nav path yet)
        root = self._find_root_for_path(src_path)
        if root is not None and event_type == "deleted":
            # Remove stale ChromaDB entry and recalculate pending count
            self.embedder.remove_file(src_path)
            self._update_pending_count(root)
        elif root is not None and event_type in ("created", "modified"):
            self._update_pending_count(root)

    # ------------------------------------------------------------------
    # Manual embedding trigger & cancel
    # ------------------------------------------------------------------

    def start_embed_folder(self, path: str) -> None:
        """Start manual embedding for the specified folder."""
        root = Path(path).resolve()
        # Mark as in-progress and clear any previous cancel flag
        self._embed_cancel[root] = False
        self._folder_pending_count[root] = 0  # Reset pending while embedding
        self._publish(EmbeddingStarted(folder=str(root)))
        self._background_embed_folder(root)

    def cancel_embed_folder(self, path: str) -> None:
        """Pause (cancel) the current embedding for the specified folder."""
        root = Path(path).resolve()
        self._embed_cancel[root] = True
        # Recalculate pending count — files processed so far are embedded, rest need it
        self._update_pending_count(root)
        self._publish(EmbeddingCancelled(folder=str(root)))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_root_for_path(self, path: Path) -> Path | None:
        """Find the registered root folder that contains *path*, or None."""
        resolved = path.resolve()
        for root in self._registered:
            try:
                resolved.relative_to(root)
                return root
            except ValueError:
                continue
        return None

    def _publish(self, event) -> None:
        try:
            self.event_queue.put_nowait(event)
        except queue.Full:
            pass
