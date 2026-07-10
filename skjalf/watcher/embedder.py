"""ChromaDB-based semantic embedding service for image files.

Each registered root folder gets a hidden ``.skjalf/`` subdirectory containing
a ChromaDB persistent client database.
"""

import threading
from pathlib import Path

import chromadb
import numpy as np
import torch
from PIL import Image
from loguru import logger
from transformers import AlignModel, AlignProcessor, AutoTokenizer

from ..config import CHROMA_DB_DIR_NAME, CHROMA_COLLECTION_NAME, CHROMA_METRIC, EMBEDDING_DEVICE, EMBEDDING_MODEL_NAME
from ..utils import relative_to_root


def _gpu_available() -> bool:
    """Return True if a CUDA-capable GPU is detected."""
    return torch.cuda.is_available()


# ------------------------------------------------------------------
# Per-folder ChromaDB wrapper
# ------------------------------------------------------------------

class FolderEmbedDB:
    """Wraps a ChromaDB collection stored inside *root_path*/.skjalf/.

    Documents are keyed by relative path; metadata includes the absolute path
    and last-modified timestamp so we can skip unchanged files.
    """

    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path.resolve()
        self._db_dir = self.root_path / CHROMA_DB_DIR_NAME
        self._db_dir.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(path=str(self._db_dir))
        self._collection = self._client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME,
            metadata={"hnsw:space": CHROMA_METRIC},
        )
        logger.info(f"[embedder] ChromaDB ready at {self._db_dir}")

    def upsert(self, path: Path, embedding: np.ndarray) -> None:
        doc_id = relative_to_root(path, self.root_path)
        mtime = round(path.stat().st_mtime, 3)
        self._collection.upsert(
            ids=[doc_id],
            embeddings=[embedding.tolist()],
            metadatas=[{"abs_path": str(path), "mtime": mtime}],
        )

    def delete(self, path: Path) -> None:
        doc_id = relative_to_root(path, self.root_path)
        self._collection.delete(ids=[doc_id])

    def get_stored_mtime(self, path: Path) -> float | None:
        """Return the stored mtime for *path*, or None if not found."""
        doc_id = relative_to_root(path, self.root_path)
        try:
            res = self._collection.get(ids=[doc_id], include=["metadatas"])
            if res["ids"] and res["metadatas"] and res["metadatas"][0]:
                return res["metadatas"][0].get("mtime")
        except Exception as e:
            logger.warning(f"[embedder] Error checking mtime for '{doc_id}': {e}")
        return None

    def query(self, embedding: list[float], n_results: int = 10) -> list[dict]:
        res = self._collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            include=["metadatas"],
        )
        return [
            {"id": doc_id, "abs_path": meta["abs_path"]}
            for doc_id, meta in zip(res["ids"][0], res["metadatas"][0])
        ]

    def get_all_entries(self) -> list[dict]:
        """Return all stored entries for this folder."""
        res = self._collection.get(include=["metadatas"])
        results = []
        for i, doc_id in enumerate(res["ids"]):
            meta = res["metadatas"][i] if res["metadatas"] else {}
            results.append({
                "id": doc_id,
                "abs_path": meta.get("abs_path", str(self.root_path / doc_id)),
            })
        return results

    def remove_all_dangling(self) -> int:
        """Remove entries whose abs_path no longer exists on disk. Returns count removed."""
        entries = self.get_all_entries()
        removed = 0
        for entry in entries:
            abs_path = Path(entry["abs_path"])
            if not abs_path.exists():
                logger.info(f"[embedder] removing dangling entry: {entry['id']}")
                self.delete(abs_path)
                removed += 1
        return removed


# ------------------------------------------------------------------
# Embedder (model + per-folder DB management)
# ------------------------------------------------------------------

class Embedder:
    """Manages per-folder ChromaDB instances with ALIGN model inference.

    The ALIGN model and processor are loaded once as class attributes.
    Individual ``Embedder`` instances manage the per-folder databases.
    """

    processor = AlignProcessor.from_pretrained(EMBEDDING_MODEL_NAME)
    tokenizer = AutoTokenizer.from_pretrained(EMBEDDING_MODEL_NAME)
    model = AlignModel.from_pretrained(EMBEDDING_MODEL_NAME, device_map=EMBEDDING_DEVICE)

    _device: str = EMBEDDING_DEVICE

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dbs: dict[Path, FolderEmbedDB] = {}

    # -- device management ---------------------------------------------------

    @staticmethod
    def gpu_available() -> bool:
        return _gpu_available()

    @classmethod
    def set_device(cls, device: str) -> None:
        """Move model and processor to the given device ('cpu' or 'cuda')."""
        if cls._device == device:
            return
        cls._device = device
        cls.model.to(device)
        logger.info(f"[embedder] device switched to {device}")

    @classmethod
    def device(cls) -> str:
        return cls._device

    # -- folder lifecycle ----------------------------------------------------

    def init_folder(self, root_path: Path) -> None:
        """Create (or load) the ChromaDB for *root_path*."""
        root = root_path.resolve()
        with self._lock:
            if root not in self._dbs:
                self._dbs[root] = FolderEmbedDB(root)

    def close_folder(self, root_path: Path) -> None:
        """Remove the ChromaDB for *root_path*."""
        with self._lock:
            self._dbs.pop(root_path.resolve(), None)

    def get_stored_mtime(self, file_path: Path) -> float | None:
        """Return the stored mtime for *file_path*, or None if not in any DB."""
        root = self._find_root(file_path)
        if root is None:
            return None
        try:
            return self._dbs[root].get_stored_mtime(file_path)
        except Exception:
            return None

    def _find_root(self, path: Path) -> Path | None:
        """Find the registered root folder that contains *path*, or None."""
        resolved = path.resolve()
        for root in sorted(self._dbs.keys(), key=lambda r: len(r.parts), reverse=True):
            try:
                resolved.relative_to(root)
                return root
            except ValueError:
                continue
        return None

    # -- embedding operations ------------------------------------------------

    def embed_file(self, file_path: Path) -> None:
        """Generate and store an embedding for *file_path*.

        Skips the file if its mtime hasn't changed since the last embed.
        """
        root = self._find_root(file_path)
        if root is None:
            return

        try:
            db = self._dbs[root]
            current_mtime = round(file_path.stat().st_mtime, 3)
            if db.get_stored_mtime(file_path) is not None and current_mtime <= db.get_stored_mtime(file_path):
                return

            image = Image.open(file_path).convert("RGB")
            inputs = self.processor(images=image, return_tensors="pt").to(self._device)
            vec = self.model.get_image_features(**inputs).pooler_output.detach().squeeze().cpu().numpy()
            db.upsert(file_path, vec)
        except Exception:
            logger.exception(f"[embedder] Failed to embed {file_path}")

    def remove_file(self, file_path: Path) -> None:
        """Remove the embedding for *file_path* from its folder DB."""
        root = self._find_root(file_path)
        if root is None:
            return
        try:
            self._dbs[root].delete(file_path)
        except Exception:
            logger.exception(f"[embedder] Failed to delete {file_path}")

    def query(self, root_path: Path, query: str, n_results: int = 10) -> list[dict]:
        """Return the top-*n_results* matches for *query* in *root_path*'s DB."""
        text_input = self.tokenizer(query, return_tensors="pt").to(self._device)
        embedding = self.model.get_text_features(**text_input).pooler_output.detach().squeeze().cpu().numpy()
        root = root_path.resolve()
        if root in self._dbs:
            return self._dbs[root].query(embedding.tolist(), n_results)
        return []

    def remove_all_dangling(self, root_path: Path) -> int:
        """Remove dangling entries for *root_path* and return count."""
        root = root_path.resolve()
        if root in self._dbs:
            return self._dbs[root].remove_all_dangling()
        return 0
