"""Tenant-scoped durable metadata for roots, files, and manual indexing jobs."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any


class CatalogError(Exception):
    """Base class for catalog validation failures."""


class RootOverlap(CatalogError):
    """Raised when a registered root contains or is contained by another root."""


class RootNotFound(CatalogError):
    """Raised when a root does not belong to the authenticated tenant."""


@dataclass(frozen=True)
class Root:
    root_id: str
    file_id: str
    path: str
    etag: str
    available: bool


def normalize_user_path(path: str) -> str:
    """Normalize a Nextcloud user-relative path without accepting traversal."""
    if "\\" in path or "\x00" in path:
        raise ValueError("Ungültiger Nextcloud-Pfad.")
    raw = path.strip("/")
    parts = raw.split("/") if raw else []
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Ungültiger Nextcloud-Pfad.")
    normalized = PurePosixPath(*parts).as_posix() if parts else ""
    return "" if normalized == "." else normalized


def paths_overlap(left: str, right: str) -> bool:
    """Return True when either normalized path contains the other."""
    a = PurePosixPath(normalize_user_path(left))
    b = PurePosixPath(normalize_user_path(right))
    if not str(a):
        return True
    if not str(b):
        return True
    return a == b or a in b.parents or b in a.parents


class Catalog:
    """Small SQLite catalog. Every query is scoped by an AppAPI-validated user id."""

    def __init__(self, database: Path | str) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.database, timeout=30, check_same_thread=False, isolation_level="IMMEDIATE"
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS roots (
                    user_id TEXT NOT NULL,
                    root_id TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    etag TEXT NOT NULL,
                    available INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (user_id, root_id),
                    UNIQUE (user_id, file_id)
                );
                CREATE TABLE IF NOT EXISTS files (
                    user_id TEXT NOT NULL,
                    root_id TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    etag TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','indexed','failed')),
                    error TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (user_id, root_id, file_id),
                    FOREIGN KEY (user_id, root_id) REFERENCES roots(user_id, root_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    user_id TEXT NOT NULL,
                    root_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('idle','running','paused','completed','error')),
                    total INTEGER NOT NULL DEFAULT 0,
                    processed INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    pause_requested INTEGER NOT NULL DEFAULT 0,
                    message TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (user_id, root_id),
                    FOREIGN KEY (user_id, root_id) REFERENCES roots(user_id, root_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS files_by_tenant_root_status
                    ON files(user_id, root_id, status);
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def pause_interrupted_jobs(self) -> None:
        """Mark work from a previous process as paused; never resume it automatically."""
        with self._lock:
            self._connection.execute(
                "UPDATE jobs SET status='paused', pause_requested=0, "
                "message='Der Dienst wurde neu gestartet; bitte manuell fortsetzen.', updated_at=? "
                "WHERE status='running'",
                (time.time(),),
            )

    def add_root(self, user_id: str, file_id: str, path: str, etag: str) -> Root:
        path = normalize_user_path(path)
        if not user_id or not file_id or not path:
            raise ValueError("Ein persönlicher Unterordner muss ausgewählt werden.")
        now = time.time()
        root_id = uuid.uuid4().hex
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT path FROM roots WHERE user_id=?", (user_id,)
            ).fetchall()
            for row in existing:
                if paths_overlap(path, row["path"]):
                    raise RootOverlap("Registrierte Ordner dürfen sich nicht überschneiden.")
            self._connection.execute(
                "INSERT INTO roots(user_id,root_id,file_id,path,etag,available,created_at,updated_at) "
                "VALUES(?,?,?,?,?,1,?,?)",
                (user_id, root_id, file_id, path, etag, now, now),
            )
            self._connection.execute(
                "INSERT INTO jobs(user_id,root_id,status,updated_at) VALUES(?,?,'idle',?)",
                (user_id, root_id, now),
            )
        return Root(root_id, file_id, path, etag, True)

    def get_root(self, user_id: str, root_id: str) -> Root | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT root_id,file_id,path,etag,available FROM roots WHERE user_id=? AND root_id=?",
                (user_id, root_id),
            ).fetchone()
        return self._root(row) if row else None

    def root_by_file_id(self, user_id: str, file_id: str) -> Root | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT root_id,file_id,path,etag,available FROM roots WHERE user_id=? AND file_id=?",
                (user_id, file_id),
            ).fetchone()
        return self._root(row) if row else None

    def list_roots(self, user_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT r.root_id,r.file_id,r.path,r.etag,r.available,
                    SUM(CASE WHEN f.status='pending' THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN f.status='indexed' THEN 1 ELSE 0 END) AS "indexed",
                    SUM(CASE WHEN f.status='failed' THEN 1 ELSE 0 END) AS failed
                FROM roots r LEFT JOIN files f ON f.user_id=r.user_id AND f.root_id=r.root_id
                WHERE r.user_id=? GROUP BY r.user_id,r.root_id ORDER BY r.path COLLATE NOCASE
                """,
                (user_id,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            root = self._root(row)
            result.append(
                {
                    **asdict(root),
                    "pending": int(row["pending"] or 0),
                    "indexed": int(row["indexed"] or 0),
                    "failed": int(row["failed"] or 0),
                    "job": self.job_state(user_id, root.root_id),
                }
            )
        return result

    def update_root_location(self, user_id: str, root_id: str, path: str, etag: str) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE roots SET path=?,etag=?,available=1,updated_at=? WHERE user_id=? AND root_id=?",
                (normalize_user_path(path), etag, time.time(), user_id, root_id),
            )

    def mark_root_unavailable(self, user_id: str, root_id: str) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE roots SET available=0,updated_at=? WHERE user_id=? AND root_id=?",
                (time.time(), user_id, root_id),
            )

    def remove_root(self, user_id: str, root_id: str) -> Root | None:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT root_id,file_id,path,etag,available FROM roots WHERE user_id=? AND root_id=?",
                (user_id, root_id),
            ).fetchone()
            if row is None:
                return None
            self._connection.execute(
                "DELETE FROM roots WHERE user_id=? AND root_id=?", (user_id, root_id)
            )
        return self._root(row)

    def reconcile(self, user_id: str, root_id: str, root_path: str, root_etag: str,
                  files: list[dict[str, str]]) -> list[str]:
        """Apply a complete successful scan. Returns deleted file IDs for vector cleanup."""
        root_path = normalize_user_path(root_path)
        now = time.time()
        incoming = {item["file_id"]: item for item in files}
        if len(incoming) != len(files):
            raise ValueError("Die Nextcloud-Antwort enthält doppelte Datei-IDs.")
        with self._lock, self._connection:
            root = self._connection.execute(
                "SELECT 1 FROM roots WHERE user_id=? AND root_id=?", (user_id, root_id)
            ).fetchone()
            if root is None:
                raise RootNotFound("Der Ordner ist nicht mehr registriert.")
            self._connection.execute(
                "UPDATE roots SET path=?,etag=?,available=1,updated_at=? WHERE user_id=? AND root_id=?",
                (root_path, root_etag, now, user_id, root_id),
            )
            rows = self._connection.execute(
                "SELECT file_id,path,etag,status FROM files WHERE user_id=? AND root_id=?",
                (user_id, root_id),
            ).fetchall()
            existing = {row["file_id"]: row for row in rows}
            removed = [file_id for file_id in existing if file_id not in incoming]
            for file_id in removed:
                self._connection.execute(
                    "DELETE FROM files WHERE user_id=? AND root_id=? AND file_id=?",
                    (user_id, root_id, file_id),
                )
            for file_id, item in incoming.items():
                path = normalize_user_path(item["path"])
                etag = item["etag"]
                old = existing.get(file_id)
                if old is None:
                    self._connection.execute(
                        "INSERT INTO files(user_id,root_id,file_id,path,etag,status,error,updated_at) "
                        "VALUES(?,?,?,?,?,'pending',NULL,?)",
                        (user_id, root_id, file_id, path, etag, now),
                    )
                elif old["etag"] != etag:
                    self._connection.execute(
                        "UPDATE files SET path=?,etag=?,status='pending',error=NULL,updated_at=? "
                        "WHERE user_id=? AND root_id=? AND file_id=?",
                        (path, etag, now, user_id, root_id, file_id),
                    )
                elif old["path"] != path:
                    self._connection.execute(
                        "UPDATE files SET path=?,updated_at=? WHERE user_id=? AND root_id=? AND file_id=?",
                        (path, now, user_id, root_id, file_id),
                    )
        return removed

    def pending_files(self, user_id: str, root_id: str) -> list[dict[str, str]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT file_id,path,etag FROM files WHERE user_id=? AND root_id=? AND status='pending' "
                "ORDER BY path COLLATE NOCASE",
                (user_id, root_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def file_record(self, user_id: str, root_id: str, file_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT file_id,path,etag,status,error FROM files "
                "WHERE user_id=? AND root_id=? AND file_id=?",
                (user_id, root_id, file_id),
            ).fetchone()
        return dict(row) if row else None

    def list_files(self, user_id: str, root_id: str, status: str | None,
                   limit: int, offset: int) -> list[dict[str, Any]]:
        if status not in (None, "pending", "indexed", "failed"):
            raise ValueError("Ungültiger Dateistatus.")
        with self._lock:
            if status is None:
                rows = self._connection.execute(
                    "SELECT file_id,path,etag,status,error FROM files WHERE user_id=? AND root_id=? "
                    "ORDER BY path COLLATE NOCASE LIMIT ? OFFSET ?",
                    (user_id, root_id, limit, offset),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT file_id,path,etag,status,error FROM files WHERE user_id=? AND root_id=? AND status=? "
                    "ORDER BY path COLLATE NOCASE LIMIT ? OFFSET ?",
                    (user_id, root_id, status, limit, offset),
                ).fetchall()
        return [dict(row) for row in rows]

    def refresh_file(self, user_id: str, root_id: str, file_id: str, path: str, etag: str) -> None:
        path = normalize_user_path(path)
        with self._lock:
            self._connection.execute(
                "UPDATE files SET path=?,etag=?,status=CASE WHEN etag<>? THEN 'pending' ELSE status END, "
                "error=CASE WHEN etag<>? THEN NULL ELSE error END,updated_at=? "
                "WHERE user_id=? AND root_id=? AND file_id=?",
                (path, etag, etag, etag, time.time(), user_id, root_id, file_id),
            )

    def delete_file(self, user_id: str, root_id: str, file_id: str) -> None:
        with self._lock:
            self._connection.execute(
                "DELETE FROM files WHERE user_id=? AND root_id=? AND file_id=?",
                (user_id, root_id, file_id),
            )

    def mark_indexed(self, user_id: str, root_id: str, file_id: str, etag: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE files SET status='indexed',error=NULL,updated_at=? "
                "WHERE user_id=? AND root_id=? AND file_id=? AND etag=? "
                "AND EXISTS(SELECT 1 FROM roots r WHERE r.user_id=? AND r.root_id=?)",
                (time.time(), user_id, root_id, file_id, etag, user_id, root_id),
            )
        return cursor.rowcount == 1

    def mark_failed(self, user_id: str, root_id: str, file_id: str, etag: str, error: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE files SET status='failed',error=?,updated_at=? "
                "WHERE user_id=? AND root_id=? AND file_id=? AND etag=? "
                "AND EXISTS(SELECT 1 FROM roots r WHERE r.user_id=? AND r.root_id=?)",
                (error[:500], time.time(), user_id, root_id, file_id, etag, user_id, root_id),
            )
        return cursor.rowcount == 1

    def start_job(self, user_id: str, root_id: str, total: int) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE jobs SET status=?,total=?,processed=0,failed=0,pause_requested=0,message=NULL,updated_at=? "
                "WHERE user_id=? AND root_id=? AND EXISTS(SELECT 1 FROM roots r "
                "WHERE r.user_id=? AND r.root_id=?)",
                ("completed" if total == 0 else "running", total, time.time(), user_id, root_id, user_id, root_id),
            )

    def request_pause(self, user_id: str, root_id: str) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE jobs SET pause_requested=1,updated_at=? WHERE user_id=? AND root_id=? AND status='running'",
                (time.time(), user_id, root_id),
            )

    def pause_requested(self, user_id: str, root_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT pause_requested FROM jobs WHERE user_id=? AND root_id=?",
                (user_id, root_id),
            ).fetchone()
        return bool(row and row["pause_requested"])

    def increment_job(self, user_id: str, root_id: str, failed: bool = False) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE jobs SET processed=processed+1,failed=failed+?,updated_at=? "
                "WHERE user_id=? AND root_id=? AND status='running'",
                (int(failed), time.time(), user_id, root_id),
            )

    def finish_job(self, user_id: str, root_id: str, status: str, message: str | None = None) -> None:
        if status not in {"paused", "completed", "error"}:
            raise ValueError("Ungültiger Auftragsstatus.")
        with self._lock:
            self._connection.execute(
                "UPDATE jobs SET status=?,pause_requested=0,message=?,updated_at=? "
                "WHERE user_id=? AND root_id=? AND status='running'",
                (status, message[:500] if message else None, time.time(), user_id, root_id),
            )

    def job_state(self, user_id: str, root_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT status,total,processed,failed,pause_requested,message,updated_at FROM jobs "
                "WHERE user_id=? AND root_id=?",
                (user_id, root_id),
            ).fetchone()
        if row is None:
            return {"status": "idle", "total": 0, "processed": 0, "failed": 0,
                    "pauseRequested": False, "message": None}
        return {
            "status": row["status"],
            "total": row["total"],
            "processed": row["processed"],
            "failed": row["failed"],
            "pauseRequested": bool(row["pause_requested"]),
            "message": row["message"],
        }

    @staticmethod
    def _root(row: sqlite3.Row) -> Root:
        return Root(row["root_id"], row["file_id"], row["path"], row["etag"], bool(row["available"]))
