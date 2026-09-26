"""Per-tenant, per-root ChromaDB storage using cosine similarity."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any


class VectorStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._collections: dict[tuple[str, str], Any] = {}

    @staticmethod
    def tenant_key(user_id: str) -> str:
        return hashlib.sha256(user_id.encode("utf-8")).hexdigest()

    def _collection(self, user_id: str, root_id: str):
        key = (user_id, root_id)
        with self._lock:
            if key not in self._collections:
                import chromadb

                location = self.root / self.tenant_key(user_id) / root_id
                location.mkdir(parents=True, exist_ok=True)
                client = chromadb.PersistentClient(path=str(location))
                collection = client.get_or_create_collection(
                    name="skjalf_images", metadata={"hnsw:space": "cosine"}
                )
                self._collections[key] = (client, collection)
            return self._collections[key][1]

    def upsert(self, user_id: str, root_id: str, file_id: str, embedding: list[float],
               etag: str, path: str) -> None:
        collection = self._collection(user_id, root_id)
        collection.upsert(
            ids=[file_id],
            embeddings=[embedding],
            metadatas=[{"etag": etag, "path": path}],
        )

    def delete(self, user_id: str, root_id: str, file_ids: list[str]) -> None:
        if file_ids:
            self._collection(user_id, root_id).delete(ids=file_ids)

    def count(self, user_id: str, root_id: str) -> int:
        return int(self._collection(user_id, root_id).count())

    def query(self, user_id: str, root_id: str, embedding: list[float], limit: int) -> list[dict[str, Any]]:
        collection = self._collection(user_id, root_id)
        count = int(collection.count())
        if count == 0 or limit <= 0:
            return []
        results = collection.query(
            query_embeddings=[embedding],
            n_results=min(limit, count),
            include=["distances"],
        )
        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        return [{"file_id": file_id, "distance": float(distance)}
                for file_id, distance in zip(ids, distances)]

    def delete_root(self, user_id: str, root_id: str) -> None:
        """Delete only this user's vector collection; source files are reached only via WebDAV."""
        key = (user_id, root_id)
        with self._lock:
            existing = self._collections.pop(key, None)
            if existing:
                client = existing[0]
                client.delete_collection(name="skjalf_images")
                return
            location = self.root / self.tenant_key(user_id) / root_id
            if not location.exists():
                return
            import chromadb

            client = chromadb.PersistentClient(path=str(location))
            try:
                client.delete_collection(name="skjalf_images")
            except Exception as exc:
                if "does not exist" not in str(exc).lower():
                    raise
