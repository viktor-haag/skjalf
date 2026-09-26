"""Tenant-scoped indexing and search service for the Nextcloud external app.

Only the authenticated ``AsyncNextcloudApp`` instance is accepted at the
boundary.  User identifiers are obtained from ``await nc.user`` and are never
accepted from request parameters.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .align import AlignEncoder
from .nextcloud_files import (
    FileUnavailable,
    list_personal_folders,
    resolve_indexed_file,
    resolve_personal_folder,
    scan_root,
)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


class ServiceError(RuntimeError):
    pass


class RootOverlap(ServiceError):
    pass


class RootUnavailable(ServiceError):
    pass


class ModelNotReady(ServiceError):
    pass


class AppDisabled(ServiceError):
    pass


@dataclass(frozen=True)
class Root:
    root_id: str
    file_id: str
    path: str
    etag: str
    available: bool = True


class SkjalfService:
    """SQLite metadata, a single CPU encoder, and serialized indexing work."""

    def __init__(self, storage: str | Path, model_cache: str | Path):
        self.storage = Path(storage)
        self.storage.mkdir(parents=True, exist_ok=True)
        self.model_cache = Path(model_cache)
        self.model_cache.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.storage / "skjalf.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.RLock()
        self.commit_gate = asyncio.Lock()
        self.queue: asyncio.Queue[tuple[Any, str, str]] = asyncio.Queue()
        self.runner: asyncio.Task[None] | None = None
        self.encoder: AlignEncoder | None = None
        self.enabled = False
        self._init_db()
        # An interrupted job is deliberately not resumed on process restart.
        with self.lock, self.db:
            self.db.execute(
                "UPDATE jobs SET status='paused', pause_requested=0, message='App neu gestartet; bitte fortsetzen' "
                "WHERE status IN ('running','queued')"
            )

    def _init_db(self) -> None:
        with self.lock, self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS roots (
                    user_id TEXT NOT NULL, root_id TEXT NOT NULL, file_id TEXT NOT NULL,
                    path TEXT NOT NULL, etag TEXT NOT NULL, available INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(user_id, root_id), UNIQUE(user_id, file_id)
                );
                CREATE TABLE IF NOT EXISTS files (
                    user_id TEXT NOT NULL, root_id TEXT NOT NULL, file_id TEXT NOT NULL,
                    path TEXT NOT NULL, etag TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    error TEXT, PRIMARY KEY(user_id, root_id, file_id),
                    FOREIGN KEY(user_id, root_id) REFERENCES roots(user_id, root_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    user_id TEXT NOT NULL, root_id TEXT NOT NULL, status TEXT NOT NULL,
                    total INTEGER NOT NULL DEFAULT 0, processed INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0, pause_requested INTEGER NOT NULL DEFAULT 0,
                    message TEXT, updated_at REAL NOT NULL,
                    PRIMARY KEY(user_id, root_id),
                    FOREIGN KEY(user_id, root_id) REFERENCES roots(user_id, root_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS files_pending ON files(user_id, root_id, status, path);
            """)

    @staticmethod
    async def user_id(nc: Any) -> str:
        """Identity comes only from the verified AppAPI request context."""
        user = await nc.user
        if not user or not isinstance(user, str):
            raise ServiceError("Die Nextcloud-Anmeldung konnte nicht bestätigt werden.")
        return user

    async def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            # The current image may finish decoding, but the commit gate below
            # prevents any vector write after disable. Queued work becomes paused.
            with self.lock, self.db:
                self.db.execute(
                    "UPDATE jobs SET pause_requested=1,message='App deaktiviert; Indizierung pausiert',updated_at=? "
                    "WHERE status IN ('queued','running')", (time.time(),)
                )

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise AppDisabled("Skjalf ist in Nextcloud derzeit deaktiviert.")

    @staticmethod
    def _root_key(file_id: str) -> str:
        # Root IDs remain stable with their Nextcloud file IDs and are safe for URLs.
        return hashlib.sha256(file_id.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _safe_user_key(user_id: str) -> str:
        return hashlib.sha256(user_id.encode("utf-8")).hexdigest()

    def _vector_collection(self, user_id: str, root_id: str):
        import chromadb

        tenant_dir = self.storage / "vectors" / self._safe_user_key(user_id)
        tenant_dir.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(tenant_dir))
        name = "r_" + root_id
        return client, client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"}
        )

    def _existing_vector_collection(self, user_id: str, root_id: str):
        import chromadb

        tenant_dir = self.storage / "vectors" / self._safe_user_key(user_id)
        if not tenant_dir.exists():
            return None
        client = chromadb.PersistentClient(path=str(tenant_dir))
        name = "r_" + root_id
        names = [getattr(item, "name", item) for item in client.list_collections()]
        if name not in names:
            return None
        return client, client.get_collection(name)

    def _get_root(self, user_id: str, root_id: str) -> Root | None:
        with self.lock:
            row = self.db.execute(
                "SELECT root_id,file_id,path,etag,available FROM roots WHERE user_id=? AND root_id=?",
                (user_id, root_id),
            ).fetchone()
        return Root(row["root_id"], row["file_id"], row["path"], row["etag"], bool(row["available"])) if row else None

    def roots(self, user_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT r.root_id,r.file_id,r.path,r.etag,r.available,j.status,j.total,j.processed,j.failed,j.message, "
                "(SELECT COUNT(*) FROM files f WHERE f.user_id=r.user_id AND f.root_id=r.root_id AND f.status='indexed') AS \"indexed\" "
                "FROM roots r LEFT JOIN jobs j USING(user_id,root_id) WHERE r.user_id=? ORDER BY r.path",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    async def browse(self, nc: Any, path: str = "") -> list[dict[str, Any]]:
        await self.user_id(nc)
        return await list_personal_folders(nc, path)

    async def _scan_selected_root(self, nc: Any, file_id: str):
        node = await resolve_personal_folder(nc, file_id)
        # scan_root is an all-or-nothing recursive DAV walk. Exceptions are allowed
        # to escape so a partial listing is never interpreted as mass deletion.
        root_node, discovered = await scan_root(nc, node)
        return root_node, discovered

    async def add_root(self, nc: Any, file_id: str) -> dict[str, Any]:
        user_id = await self.user_id(nc)
        node, discovered = await self._scan_selected_root(nc, file_id)
        path = node.user_path
        with self.lock, self.db:
            existing = self.db.execute("SELECT root_id,path FROM roots WHERE user_id=?", (user_id,)).fetchall()
            for item in existing:
                old = item["path"]
                if old == path or old.startswith(path.rstrip("/") + "/") or path.startswith(old.rstrip("/") + "/"):
                    raise RootOverlap("Indizierte Ordner dürfen sich nicht überschneiden.")
            root_id = self._root_key(str(node.file_id))
            self.db.execute(
                "INSERT INTO roots(user_id,root_id,file_id,path,etag,available) VALUES(?,?,?,?,?,1)",
                (user_id, root_id, str(node.file_id), path, str(node.etag)),
            )
        await self._apply_scan(user_id, root_id, node, discovered)
        return self.root_status(user_id, root_id)

    async def reconcile_root(self, nc: Any, root_id: str) -> dict[str, Any]:
        user_id = await self.user_id(nc)
        root = self._get_root(user_id, root_id)
        if not root or not root.available:
            raise RootUnavailable("Der Ordner ist nicht mehr verfügbar.")
        node, discovered = await self._scan_selected_root(nc, root.file_id)
        await self._apply_scan(user_id, root_id, node, discovered)
        return self.root_status(user_id, root_id)

    async def _apply_scan(self, user_id: str, root_id: str, node: Any, discovered: dict[str, Any]) -> None:
        # The complete scan was successful before entering this transaction.
        path = node.user_path
        stale_vector_ids: list[str] = []
        async with self.commit_gate:
            with self.lock, self.db:
                root = self.db.execute(
                    "SELECT available FROM roots WHERE user_id=? AND root_id=?", (user_id, root_id)
                ).fetchone()
                if not root or not root["available"]:
                    raise RootUnavailable("Der Ordner wurde während des Abgleichs entfernt.")
                others = self.db.execute(
                    "SELECT path FROM roots WHERE user_id=? AND root_id<>? AND available=1", (user_id, root_id)
                ).fetchall()
                for other in others:
                    old = other["path"]
                    if old == path or old.startswith(path.rstrip("/") + "/") or path.startswith(old.rstrip("/") + "/"):
                        raise RootOverlap("Nach einer Ordner-Verschiebung würden sich Indizes überschneiden.")
                self.db.execute(
                    "UPDATE roots SET path=?,etag=? WHERE user_id=? AND root_id=? AND available=1",
                    (path, str(node.etag), user_id, root_id),
                )
                current = self.db.execute(
                    "SELECT file_id,etag,path,status FROM files WHERE user_id=? AND root_id=?", (user_id, root_id)
                ).fetchall()
                seen = set(discovered)
                for row in current:
                    file_id = row["file_id"]
                    if file_id not in seen:
                        stale_vector_ids.append(file_id)
                        self.db.execute(
                            "DELETE FROM files WHERE user_id=? AND root_id=? AND file_id=?",
                            (user_id, root_id, file_id),
                        )
                        continue
                    item = discovered[file_id]
                    etag = str(item.etag)
                    if row["etag"] != etag:
                        stale_vector_ids.append(file_id)
                        self.db.execute(
                            "UPDATE files SET path=?,etag=?,status='pending',error=NULL WHERE user_id=? AND root_id=? AND file_id=?",
                            (item.user_path, etag, user_id, root_id, file_id),
                        )
                    elif row["status"] == "changed":
                        self.db.execute(
                            "UPDATE files SET path=?,status='pending',error=NULL WHERE user_id=? AND root_id=? AND file_id=?",
                            (item.user_path, user_id, root_id, file_id),
                        )
                    else:
                        self.db.execute(
                            "UPDATE files SET path=? WHERE user_id=? AND root_id=? AND file_id=?",
                            (item.user_path, user_id, root_id, file_id),
                        )
                for file_id, item in discovered.items():
                    self.db.execute(
                        "INSERT OR IGNORE INTO files(user_id,root_id,file_id,path,etag,status) VALUES(?,?,?,?,?,'pending')",
                        (user_id, root_id, file_id, item.user_path, str(item.etag)),
                    )
            if stale_vector_ids:
                _client, collection = self._vector_collection(user_id, root_id)
                collection.delete(ids=stale_vector_ids)

    def root_status(self, user_id: str, root_id: str) -> dict[str, Any]:
        with self.lock:
            root = self.db.execute("SELECT * FROM roots WHERE user_id=? AND root_id=?", (user_id, root_id)).fetchone()
            if not root:
                raise RootUnavailable("Der Ordner ist nicht mehr verfügbar.")
            counts = self.db.execute(
                "SELECT COUNT(*) total,SUM(CASE WHEN status='indexed' THEN 1 ELSE 0 END) AS \"indexed\"," 
                "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed "
                "FROM files WHERE user_id=? AND root_id=?", (user_id, root_id)
            ).fetchone()
            job = self.db.execute("SELECT * FROM jobs WHERE user_id=? AND root_id=?", (user_id, root_id)).fetchone()
        return {"root_id": root_id, "file_id": root["file_id"], "path": root["path"],
                "available": bool(root["available"]), "total": counts["total"] or 0,
                "indexed": counts["indexed"] or 0, "failed": counts["failed"] or 0,
                "job": dict(job) if job else None}

    async def list_and_reconcile(self, nc: Any) -> list[dict[str, Any]]:
        user_id = await self.user_id(nc)
        # Opening and refreshing the UI performs a manual metadata reconcile only.
        for root in self.roots(user_id):
            try:
                await self.reconcile_root(nc, root["root_id"])
            except FileUnavailable:
                with self.lock, self.db:
                    self.db.execute("UPDATE roots SET available=0 WHERE user_id=? AND root_id=?", (user_id, root["root_id"]))
        return self.roots(user_id)

    def _ensure_encoder(self) -> AlignEncoder:
        if self.encoder is None:
            self.encoder = AlignEncoder(cache_dir=self.model_cache, device="cpu")
        return self.encoder

    async def _load_encoder(self) -> AlignEncoder:
        encoder = self._ensure_encoder()
        try:
            await asyncio.to_thread(encoder.ensure_loaded)
        except Exception as exc:
            # ALIGN is loaded from the AppAPI-managed persistent cache only; user
            # requests never trigger a network download.
            raise ModelNotReady(
                "Das ALIGN-Modell ist nicht bereit. Bitte die App in Nextcloud "
                "deaktivieren und erneut aktivieren, damit AppAPI den Modellcache lädt."
            ) from exc
        return encoder

    async def start(self, nc: Any, root_id: str) -> dict[str, Any]:
        self._require_enabled()
        user_id = await self.user_id(nc)
        # Every explicit start gets a fresh complete DAV snapshot before work begins.
        status = await self.reconcile_root(nc, root_id)
        encoder = await self._load_encoder()
        with self.lock, self.db:
            root = self.db.execute("SELECT available FROM roots WHERE user_id=? AND root_id=?", (user_id, root_id)).fetchone()
            if not root or not root["available"]:
                raise RootUnavailable("Der Ordner ist nicht mehr verfügbar.")
            job = self.db.execute("SELECT status FROM jobs WHERE user_id=? AND root_id=?", (user_id, root_id)).fetchone()
            if job and job["status"] in ("queued", "running"):
                return self.root_status(user_id, root_id)
            pending = self.db.execute(
                "SELECT COUNT(*) n FROM files WHERE user_id=? AND root_id=? AND status='pending'", (user_id, root_id)
            ).fetchone()["n"]
            keep_progress = bool(job and job["status"] in ("paused", "error"))
            processed = self.db.execute(
                "SELECT processed,failed FROM jobs WHERE user_id=? AND root_id=?", (user_id, root_id)
            ).fetchone() if keep_progress else None
            done = processed["processed"] if processed else 0
            failed = processed["failed"] if processed else 0
            self.db.execute(
                "INSERT INTO jobs(user_id,root_id,status,total,processed,failed,pause_requested,message,updated_at) "
                "VALUES(?,?, 'queued', ?,?,?,0,NULL,?) ON CONFLICT(user_id,root_id) DO UPDATE SET "
                "status='queued',total=excluded.total,processed=excluded.processed,failed=excluded.failed,pause_requested=0,message=NULL,updated_at=excluded.updated_at",
                (user_id, root_id, done + pending, done, failed, time.time()),
            )
        await self.queue.put((nc, user_id, root_id))
        self._ensure_runner()
        return self.root_status(user_id, root_id)

    def _ensure_runner(self) -> None:
        if self.runner is None or self.runner.done():
            self.runner = asyncio.create_task(self._run_queue(), name="skjalf-index-worker")

    async def pause(self, nc: Any, root_id: str) -> dict[str, Any]:
        user_id = await self.user_id(nc)
        with self.lock, self.db:
            self.db.execute(
                "UPDATE jobs SET pause_requested=1,message='Wird nach der aktuellen Datei angehalten',updated_at=? "
                "WHERE user_id=? AND root_id=? AND status IN ('queued','running')",
                (time.time(), user_id, root_id),
            )
        return self.root_status(user_id, root_id)

    async def remove_root(self, nc: Any, root_id: str) -> None:
        user_id = await self.user_id(nc)
        async with self.commit_gate:
            # Fence commits before deleting vectors or metadata. A worker that has
            # downloaded/embedded a file must re-check this flag under the same gate.
            with self.lock, self.db:
                root = self.db.execute(
                    "SELECT available FROM roots WHERE user_id=? AND root_id=?", (user_id, root_id)
                ).fetchone()
                if not root:
                    raise RootUnavailable("Der Ordner ist nicht mehr verfügbar.")
                self.db.execute(
                    "UPDATE roots SET available=0 WHERE user_id=? AND root_id=?", (user_id, root_id)
                )
                client, _collection = self._vector_collection(user_id, root_id)
                collection_name = "r_" + root_id
                names = [getattr(item, "name", item) for item in client.list_collections()]
                if collection_name in names:
                    client.delete_collection(collection_name)
                self.db.execute("DELETE FROM roots WHERE user_id=? AND root_id=?", (user_id, root_id))

    async def _run_queue(self) -> None:
        while True:
            try:
                nc, user_id, root_id = await asyncio.wait_for(self.queue.get(), timeout=0.25)
            except asyncio.TimeoutError:
                return
            try:
                await self._run_job(nc, user_id, root_id)
            finally:
                self.queue.task_done()

    async def _run_job(self, nc: Any, user_id: str, root_id: str) -> None:
        if await self.user_id(nc) != user_id:
            raise ServiceError("Die AppAPI-Identität des Jobs stimmt nicht überein.")
        with self.lock, self.db:
            root = self.db.execute("SELECT available FROM roots WHERE user_id=? AND root_id=?", (user_id, root_id)).fetchone()
            job = self.db.execute("SELECT * FROM jobs WHERE user_id=? AND root_id=?", (user_id, root_id)).fetchone()
            if not root or not root["available"] or not job or job["status"] != "queued":
                return
            if not self.enabled:
                self.db.execute(
                    "UPDATE jobs SET status='paused',pause_requested=0,message='App deaktiviert',updated_at=? WHERE user_id=? AND root_id=?",
                    (time.time(), user_id, root_id),
                )
                return
            self.db.execute("UPDATE jobs SET status='running',updated_at=? WHERE user_id=? AND root_id=?", (time.time(), user_id, root_id))
        encoder = self._ensure_encoder()
        try:
            while True:
                with self.lock:
                    job = self.db.execute("SELECT * FROM jobs WHERE user_id=? AND root_id=?", (user_id, root_id)).fetchone()
                    root = self.db.execute("SELECT available FROM roots WHERE user_id=? AND root_id=?", (user_id, root_id)).fetchone()
                    row = self.db.execute(
                        "SELECT file_id,path,etag FROM files WHERE user_id=? AND root_id=? AND status='pending' ORDER BY path LIMIT 1",
                        (user_id, root_id),
                    ).fetchone()
                if not root or not root["available"]:
                    return
                if not job or job["pause_requested"]:
                    self._finish_job(user_id, root_id, "paused", "Pausiert")
                    return
                if not row:
                    self._finish_job(user_id, root_id, "complete", None)
                    return
                await self._index_one(nc, user_id, root_id, row, encoder)
        except Exception as exc:
            # A network/model failure pauses the job and leaves its current file
            # pending so it is safe to resume. Corrupt images are handled per-file.
            self._finish_job(user_id, root_id, "error", str(exc)[:300])

    async def _index_one(self, nc: Any, user_id: str, root_id: str, row: sqlite3.Row, encoder: AlignEncoder) -> None:
        root = self._get_root(user_id, root_id)
        if not root or not root.available:
            return
        if await self.user_id(nc) != user_id:
            raise ServiceError("Die AppAPI-Identität des Jobs stimmt nicht überein.")
        try:
            node = await resolve_indexed_file(nc, row["file_id"], root.path)
        except FileUnavailable:
            async with self.commit_gate:
                with self.lock, self.db:
                    self.db.execute("DELETE FROM files WHERE user_id=? AND root_id=? AND file_id=?", (user_id, root_id, row["file_id"]))
                _client, collection = self._vector_collection(user_id, root_id)
                collection.delete(ids=[row["file_id"]])
                self._advance_job(user_id, root_id, failed=False)
            return
        if str(node.etag) != row["etag"]:
            self._mark_changed(user_id, root_id, row["file_id"], str(node.etag), node.user_path)
            return

        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(suffix=Path(row["path"]).suffix, delete=False) as image_file:
                temp_name = image_file.name
                await nc.files.download2stream(node, image_file)
            try:
                # Decode once here so corrupt/unsupported files become per-file errors.
                with Image.open(temp_name) as image:
                    image.verify()
                with Image.open(temp_name) as image:
                    image = image.convert("RGB")
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError) as exc:
                async with self.commit_gate:
                    with self.lock, self.db:
                        self.db.execute(
                            "UPDATE files SET status='failed',error=? WHERE user_id=? AND root_id=? AND file_id=?",
                            (str(exc)[:300], user_id, root_id, row["file_id"]),
                        )
                    self._advance_job(user_id, root_id, failed=True)
                return
            image_vector = await asyncio.to_thread(encoder.encode_image, image)
        finally:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass

        # Re-check the same stable file ID, root membership and etag after download
        # and image encoding. Root removal and this upsert share commit_gate, so the
        # worker cannot resurrect a collection or row after removal.
        async with self.commit_gate:
            current_root = self._get_root(user_id, root_id)
            if not self.enabled:
                self._finish_job(user_id, root_id, "paused", "App deaktiviert")
                return
            if not current_root or not current_root.available:
                return
            try:
                current = await resolve_indexed_file(nc, row["file_id"], current_root.path)
            except FileUnavailable:
                with self.lock, self.db:
                    self.db.execute("DELETE FROM files WHERE user_id=? AND root_id=? AND file_id=?", (user_id, root_id, row["file_id"]))
                _client, collection = self._vector_collection(user_id, root_id)
                collection.delete(ids=[row["file_id"]])
                self._advance_job(user_id, root_id, failed=False)
                return
            if str(current.etag) != row["etag"]:
                with self.lock, self.db:
                    self.db.execute(
                        "UPDATE files SET path=?,etag=?,status='changed',error='Datei während der Indizierung geändert' "
                        "WHERE user_id=? AND root_id=? AND file_id=?",
                        (current.user_path, str(current.etag), user_id, root_id, row["file_id"]),
                    )
                _client, collection = self._vector_collection(user_id, root_id)
                collection.delete(ids=[row["file_id"]])
                self._advance_job(user_id, root_id, failed=False)
                return
            client, collection = self._vector_collection(user_id, root_id)
            collection.upsert(
                ids=[row["file_id"]],
                embeddings=[image_vector.tolist()],
                metadatas=[{"path": current.user_path, "etag": str(current.etag)}],
            )
            with self.lock, self.db:
                self.db.execute(
                    "UPDATE files SET path=?,status='indexed',error=NULL WHERE user_id=? AND root_id=? AND file_id=? AND etag=?",
                    (current.user_path, user_id, root_id, row["file_id"], row["etag"]),
                )
            self._advance_job(user_id, root_id, failed=False)

    async def search(self, nc: Any, root_id: str, query: str) -> list[dict[str, Any]]:
        self._require_enabled()
        user_id = await self.user_id(nc)
        if not query.strip():
            return []
        root = self._get_root(user_id, root_id)
        if not root or not root.available:
            raise RootUnavailable("Der Ordner ist nicht mehr verfügbar.")
        # Re-check the selected root's current permission and stable ID for each search.
        root_node = await resolve_personal_folder(nc, root.file_id)
        current_path = root_node.user_path
        with self.lock, self.db:
            others = self.db.execute(
                "SELECT path FROM roots WHERE user_id=? AND root_id<>? AND available=1", (user_id, root_id)
            ).fetchall()
            for other in others:
                old = other["path"]
                if old == current_path or old.startswith(current_path.rstrip("/") + "/") or current_path.startswith(old.rstrip("/") + "/"):
                    raise RootOverlap("Die Ordner-Indizes überschneiden sich nach einer Verschiebung.")
            self.db.execute(
                "UPDATE roots SET path=?,etag=? WHERE user_id=? AND root_id=? AND available=1",
                (current_path, str(root_node.etag), user_id, root_id),
            )
        encoder = await self._load_encoder()
        text_vector = await asyncio.to_thread(encoder.encode_text, query.strip())
        vector_pair = self._existing_vector_collection(user_id, root_id)
        if not vector_pair:
            return []
        _client, collection = vector_pair
        count = collection.count()
        if not count:
            return []
        limit = min(count, 64)
        valid: list[dict[str, Any]] = []
        checked: set[str] = set()
        while limit:
            response = collection.query(
                query_embeddings=[text_vector.tolist()], n_results=limit,
                include=["metadatas", "distances"],
            )
            ids = response.get("ids", [[]])[0]
            metadata = response.get("metadatas", [[]])[0]
            distances = response.get("distances", [[]])[0]
            for file_id, vector_meta, distance in zip(ids, metadata, distances):
                if file_id in checked:
                    continue
                checked.add(file_id)
                with self.lock:
                    record = self.db.execute(
                        "SELECT path,etag,status FROM files WHERE user_id=? AND root_id=? AND file_id=?",
                        (user_id, root_id, file_id),
                    ).fetchone()
                if not record or record["status"] != "indexed" or record["etag"] != str(vector_meta.get("etag", "")):
                    continue
                try:
                    current = await resolve_indexed_file(nc, file_id, current_path)
                except FileUnavailable:
                    continue
                if str(current.etag) != record["etag"]:
                    async with self.commit_gate:
                        with self.lock, self.db:
                            active = self.db.execute(
                                "SELECT available FROM roots WHERE user_id=? AND root_id=?", (user_id, root_id)
                            ).fetchone()
                            if not active or not active["available"]:
                                return []
                            self.db.execute(
                                "UPDATE files SET path=?,etag=?,status='pending',error=NULL WHERE user_id=? AND root_id=? AND file_id=?",
                                (current.user_path, str(current.etag), user_id, root_id, file_id),
                            )
                        collection.delete(ids=[file_id])
                    continue
                valid.append({
                    "file_id": file_id, "path": current.user_path,
                    "name": current.user_path.rsplit("/", 1)[-1],
                    "score": 1.0 - float(distance), "etag": str(current.etag),
                })
                if len(valid) >= 10:
                    break
            if len(valid) >= 10 or limit >= count:
                break
            limit = min(count, limit * 2)
        with self.lock:
            still_available = self.db.execute(
                "SELECT available FROM roots WHERE user_id=? AND root_id=?", (user_id, root_id)
            ).fetchone()
        return valid[:10] if still_available and still_available["available"] else []

    def _mark_changed(self, user_id: str, root_id: str, file_id: str, etag: str, path: str) -> None:
        with self.lock, self.db:
            self.db.execute(
                "UPDATE files SET path=?,etag=?,status='changed',error='Datei während der Indizierung geändert' "
                "WHERE user_id=? AND root_id=? AND file_id=?",
                (path, etag, user_id, root_id, file_id),
            )
        self._advance_job(user_id, root_id, failed=False)

    def _advance_job(self, user_id: str, root_id: str, failed: bool) -> None:
        with self.lock, self.db:
            self.db.execute(
                "UPDATE jobs SET processed=processed+1,failed=failed+?,updated_at=? WHERE user_id=? AND root_id=?",
                (1 if failed else 0, time.time(), user_id, root_id),
            )

    def _finish_job(self, user_id: str, root_id: str, status: str, message: str | None) -> None:
        with self.lock, self.db:
            row = self.db.execute("SELECT status FROM jobs WHERE user_id=? AND root_id=?", (user_id, root_id)).fetchone()
            if row:
                self.db.execute(
                    "UPDATE jobs SET status=?,pause_requested=0,message=?,updated_at=? WHERE user_id=? AND root_id=?",
                    (status, message, time.time(), user_id, root_id),
                )

    async def shutdown(self) -> None:
        self.enabled = False
        with self.lock, self.db:
            self.db.execute(
                "UPDATE jobs SET pause_requested=1,message='App wird beendet; Indizierung pausiert',updated_at=? "
                "WHERE status IN ('queued','running')", (time.time(),)
            )
        task = self.runner
        if task and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=20)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        with self.lock, self.db:
            self.db.execute(
                "UPDATE jobs SET status='paused',pause_requested=0,message='App neu gestartet; bitte fortsetzen',updated_at=? "
                "WHERE status IN ('running','queued')", (time.time(),)
            )

    def close(self) -> None:
        with self.lock:
            self.db.close()
