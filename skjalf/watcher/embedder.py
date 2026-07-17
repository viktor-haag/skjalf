"""ChromaDB-based semantic and face embedding service for image files.

Each registered root folder gets a hidden ``.skjalf/`` subdirectory containing
a ChromaDB persistent client database with two collections:
- ``image_embeddings`` (semantic, via ALIGN model)
- ``face_embeddings`` (face recognition, via ArcFace model)
"""

import threading
from pathlib import Path
from typing import Optional

import chromadb
import numpy as np
import torch
from huggingface_hub import hf_hub_download
from huggingface_hub.errors import LocalEntryNotFoundError
from loguru import logger
from PIL import Image
from transformers import AlignModel, AlignProcessor, AutoTokenizer

from ..config import (
    CHROMA_COLLECTION_NAME,
    CHROMA_DB_DIR_NAME,
    CHROMA_METRIC,
    EMBEDDING_DEVICE,
    EMBEDDING_MODEL_NAME,
    FACE_COLLECTION_NAME,
    FACE_EMBEDDING_MODEL_NAME,
    FACE_INPUT_SIZE,
    _NAMES_YAML_PATH,
)
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

    Supports multiple collections within the same database (e.g., 'image_embeddings'
    and 'face_embeddings').
    """

    def __init__(self, root_path: Path, collection_name: str = CHROMA_COLLECTION_NAME) -> None:
        self.root_path = root_path.resolve()
        self.collection_name = collection_name
        self._db_dir = self.root_path / CHROMA_DB_DIR_NAME
        self._db_dir.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(path=str(self._db_dir))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": CHROMA_METRIC},
        )
        logger.info(f"[embedder] ChromaDB ready at {self._db_dir}, collection: {collection_name}")

    def upsert(self, path: Path, embedding: np.ndarray, name: str = "") -> None:
        """Store an embedding for *path* in this collection.

        Args:
            path: File path (keyed by relative path)
            embedding: Numpy embedding vector
            name: Optional person name for face embeddings (stored in metadata)
        """
        doc_id = relative_to_root(path, self.root_path)
        mtime = round(path.stat().st_mtime, 3)
        metadata: dict[str, str | float] = {"abs_path": str(path), "mtime": mtime}
        if name:
            metadata["name"] = name
        self._collection.upsert(
            ids=[doc_id],
            embeddings=[embedding.tolist()],
            metadatas=[metadata],
        )

    def delete(self, path: Path) -> None:
        """Delete an entry from this collection."""
        doc_id = relative_to_root(path, self.root_path)
        self._collection.delete(ids=[doc_id])

    def get_stored_mtime(self, path: Path) -> float | None:
        """Return the stored mtime for *path* in this collection, or None if not found."""
        doc_id = relative_to_root(path, self.root_path)
        try:
            res = self._collection.get(ids=[doc_id], include=["metadatas"])
            if res["ids"] and res["metadatas"] and res["metadatas"][0]:
                return res["metadatas"][0].get("mtime")
        except Exception as e:
            logger.warning(f"[embedder] Error checking mtime for '{doc_id}': {e}")
        return None

    def query(self, embedding: list[float], n_results: int = 10) -> list[dict]:
        """Query this collection for similar embeddings."""
        res = self._collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            include=["metadatas"],
        )
        return [
            {
                "id": doc_id,
                "abs_path": meta["abs_path"],
                "name": meta.get("name", ""),
            }
            for doc_id, meta in zip(res["ids"][0], res["metadatas"][0])
        ]

    def exists(self, path: Path) -> bool:
        """Check if a file path already exists in this collection."""
        doc_id = relative_to_root(path, self.root_path)
        try:
            res = self._collection.get(ids=[doc_id], include=[])
            return len(res["ids"]) > 0
        except Exception:
            return False

    def get_all_entries(self) -> list[dict]:
        """Return all stored entries for this collection."""
        res = self._collection.get(include=["metadatas"])
        results = []
        for i, doc_id in enumerate(res["ids"]):
            meta = res["metadatas"][i] if res["metadatas"] else {}
            results.append({
                "id": doc_id,
                "abs_path": meta.get("abs_path", str(self.root_path / doc_id)),
                "name": meta.get("name", ""),
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
                self._collection.delete(ids=[entry["id"]])
                removed += 1
        return removed


# ------------------------------------------------------------------
# Embedder (model + per-folder DB management)
# ------------------------------------------------------------------


class Embedder:
    """Manages per-folder ChromaDB instances with ALIGN and ArcFace model inference.

    The ALIGN model, processor, and tokenizer are loaded lazily on first access.
    The ArcFace model is also loaded lazily on first face embedding call.
    """

    _processor: "AlignProcessor | None" = None
    _tokenizer: "AutoTokenizer | None" = None
    _model: "AlignModel | None" = None
    _device: str = EMBEDDING_DEVICE
    _load_lock = threading.Lock()

    # ArcFace model (lazy-loaded)
    _face_model: Optional[torch.nn.Module] = None
    _face_model_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dbs: dict[Path, FolderEmbedDB] = {}
        self._face_db: dict[Path, FolderEmbedDB] = {}
        self._names: dict[str, str] = {}
        self._names_path: Path = _NAMES_YAML_PATH
        self._names_loaded = False

    # -- lazy loading --------------------------------------------------------

    @classmethod
    def _ensure_loaded(cls) -> None:
        """Load model, processor, and tokenizer if not already loaded."""
        if cls._model is not None:
            return
        with cls._load_lock:
            if cls._model is not None:
                return  # double-check after acquiring lock
            cls._processor = AlignProcessor.from_pretrained(
                EMBEDDING_MODEL_NAME, local_files_only=True
            )
            cls._tokenizer = AutoTokenizer.from_pretrained(
                EMBEDDING_MODEL_NAME, local_files_only=True
            )
            cls._model = AlignModel.from_pretrained(
                EMBEDDING_MODEL_NAME, device_map=cls._device, local_files_only=True
            )

    @classmethod
    def _ensure_face_model_loaded(cls) -> None:
        """Load the ArcFace model if not already loaded."""
        if cls._face_model is not None:
            return
        with cls._face_model_lock:
            if cls._face_model is not None:
                return
            try:
                import timm
                import torch.nn.functional as F

                logger.info(f"[embedder] Loading ArcFace model {FACE_EMBEDDING_MODEL_NAME} on {cls._device}...")
                cls._face_model = timm.create_model(FACE_EMBEDDING_MODEL_NAME, pretrained=True)
                cls._face_model = cls._face_model.to(cls._device)
                cls._face_model.eval()
                logger.info("[embedder] ArcFace model loaded successfully.")
            except Exception as e:
                logger.warning(f"[embedder] Failed to load ArcFace model: {e}")
                cls._face_model = None

    @classmethod
    def is_model_loaded(cls) -> bool:
        """Return True if model is loaded in memory."""
        return cls._model is not None

    @classmethod
    def face_model_available(cls) -> bool:
        """Return True if the ArcFace model is loaded."""
        return cls._face_model is not None

    @classmethod
    def warm_up(cls) -> None:
        """Run a dummy embedding to initialize GPU/CPU kernels.

        Call after ``_ensure_loaded`` so the first real embedding is fast.
        """
        cls._ensure_loaded()
        dummy = Image.new("RGB", (32, 32), color=(128, 128, 128))
        inputs = cls._processor(images=dummy, return_tensors="pt").to(cls._device)
        cls._model.get_image_features(**inputs)

    @classmethod
    def model_available(cls) -> bool:
        """Check if model files are cached locally without downloading."""
        try:
            hf_hub_download(
                repo_id=EMBEDDING_MODEL_NAME,
                filename="config.json",
                local_files_only=True,
            )
            return True
        except LocalEntryNotFoundError:
            return False

    @property
    def processor(self) -> "AlignProcessor":
        self._ensure_loaded()
        return self._processor  # type: ignore[return-value]

    @property
    def tokenizer(self) -> "AutoTokenizer":
        self._ensure_loaded()
        return self._tokenizer  # type: ignore[return-value]

    @property
    def model(self) -> "AlignModel":
        self._ensure_loaded()
        return self._model  # type: ignore[return-value]

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
        if cls._model is not None:
            cls._model.to(device)
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
                self._dbs[root] = FolderEmbedDB(root, collection_name=CHROMA_COLLECTION_NAME)
            if root not in self._face_db:
                self._face_db[root] = FolderEmbedDB(root, collection_name=FACE_COLLECTION_NAME)
        self._load_names()

    def close_folder(self, root_path: Path) -> None:
        """Remove the ChromaDB for *root_path*."""
        with self._lock:
            self._dbs.pop(root_path.resolve(), None)
            self._face_db.pop(root_path.resolve(), None)

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

    # -- name loading --------------------------------------------------------

    def _load_names(self) -> None:
        """Load names.yaml into memory."""
        if self._names_loaded:
            return
        import yaml

        if self._names_path.exists():
            try:
                with open(self._names_path) as f:
                    data = yaml.safe_load(f) or {}
                # Build {abs_path: name} mapping
                project_root = self._names_path.parent.parent
                for name, path_str in data.items():
                    resolved = (project_root / path_str).resolve()
                    self._names[str(resolved)] = name
                logger.info(f"[embedder] Loaded {len(self._names)} name(s) from {self._names_path}")
            except Exception as e:
                logger.warning(f"[embedder] Failed to load names.yaml: {e}")
        self._names_loaded = True

    # -- face embedding helpers ----------------------------------------------

    @staticmethod
    def _preprocess_face_image(image: Image.Image, input_size: int = FACE_INPUT_SIZE) -> torch.Tensor:
        """Preprocess a PIL image for the ArcFace model."""
        image = image.convert("RGB")
        image = image.resize((input_size, input_size), Image.Resampling.BILINEAR)
        tensor = torch.from_numpy(np.array(image)).permute(2, 0, 1).float() / 255.0
        return tensor

    @classmethod
    def embed_face(cls, image: Image.Image) -> Optional[np.ndarray]:
        """Generate a face embedding for a single image.

        Args:
            image: PIL Image (must be RGB)

        Returns:
            Numpy array of the normalized embedding vector (512-dim), or None on failure.
        """
        if not cls.face_model_available():
            return None
        try:
            import torch.nn.functional as F

            tensor = cls._preprocess_face_image(image)
            tensor = tensor.unsqueeze(0).to(cls._device)
            with torch.no_grad():
                embedding = cls._face_model(tensor)
                embedding = F.normalize(embedding, dim=1)
            return embedding.squeeze(0).cpu().numpy()
        except Exception as e:
            logger.warning(f"[embedder] Failed to generate face embedding: {e}")
            return None

    # -- embedding operations ------------------------------------------------

    def embed_file(self, file_path: Path) -> None:
        """Generate and store semantic and face embeddings for *file_path*.

        Skips the file if its mtime hasn't changed since the last embed.
        """
        root = self._find_root(file_path)
        if root is None:
            return

        try:
            db = self._dbs[root]
            current_mtime = round(file_path.stat().st_mtime, 3)
            if db.get_stored_mtime(file_path) is not None and current_mtime <= db.get_stored_mtime(file_path):
                return  # Skip entirely — both embeddings are up-to-date

            image = Image.open(file_path).convert("RGB")

            # Semantic embedding (ALIGN)
            inputs = self.processor(images=image, return_tensors="pt").to(self.device())
            vec = (
                self.model.get_image_features(**inputs)
                .pooler_output.detach()
                .squeeze()
                .cpu()
                .numpy()
            )
            db.upsert(file_path, vec)

            # Face embedding (ArcFace)
            face_db = self._face_db[root]
            self._ensure_face_model_loaded()
            face_vec = self.embed_face(image)
            if face_vec is not None:
                abs_path = str(file_path.resolve())
                person_name = self._names.get(abs_path, "")
                face_db.upsert(file_path, face_vec, name=person_name)

        except Exception:
            logger.exception(f"[embedder] Failed to embed {file_path}")

    def remove_file(self, file_path: Path) -> None:
        """Remove both semantic and face embeddings for *file_path*."""
        root = self._find_root(file_path)
        if root is None:
            return
        try:
            if root in self._dbs:
                self._dbs[root].delete(file_path)
            if root in self._face_db:
                self._face_db[root].delete(file_path)
        except Exception:
            logger.exception(f"[embedder] Failed to delete {file_path}")

    def query(self, root_path: Path, query: str, n_results: int = 10) -> list[dict]:
        """Return the top-*n_results* matches for *query* in *root_path*'s DB."""
        text_input = self.tokenizer(query, return_tensors="pt").to(self.device())
        embedding = (
            self.model.get_text_features(**text_input)
            .pooler_output.detach()
            .squeeze()
            .cpu()
            .numpy()
        )
        root = root_path.resolve()
        if root in self._dbs:
            return self._dbs[root].query(embedding.tolist(), n_results)
        return []

    def remove_all_dangling(self, root_path: Path) -> tuple[int, int]:
        """Remove dangling entries for *root_path* from both collections.

        Returns:
            Tuple of (semantic_removed, face_removed) counts.
        """
        root = root_path.resolve()
        semantic_removed = 0
        face_removed = 0
        if root in self._dbs:
            semantic_removed = self._dbs[root].remove_all_dangling()
        if root in self._face_db:
            face_removed = self._face_db[root].remove_all_dangling()
        return semantic_removed, face_removed
