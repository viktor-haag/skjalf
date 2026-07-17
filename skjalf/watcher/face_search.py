"""Face search module for Skjalf.

This module provides face recognition search capabilities using the
ArcFace ViT model via timm. It wraps a ChromaDB "persons" collection
and provides fuzzy name matching against a names.yaml file.

Usage:
    searcher = FaceSearcher(names_path, persons_db_path)
    results = searcher.search("jacqueline", n_results=10)
"""

from pathlib import Path
from typing import Optional

import chromadb
import numpy as np
import torch
import torch.nn.functional as F
import timm
from difflib import get_close_matches
from loguru import logger
from PIL import Image

from .events import FileEntry
from ..config import (
    FACE_EMBEDDING_MODEL_NAME,
    FACE_INPUT_SIZE,
    FACE_EMBEDDING_DIM,
    PERSONS_DB_PATH,
    PERSONS_COLLECTION_NAME,
)


# ------------------------------------------------------------------
# ChromaDB wrapper for face embeddings
# ------------------------------------------------------------------

class PersonDB:
    """Wraps a ChromaDB collection for face embeddings.

    Documents are keyed by absolute file path; metadata includes the
    absolute path for result lookups.
    """

    def __init__(self, db_path: str, collection_name: str = "persons", metric: str = "cosine"):
        self.db_path = db_path
        self.collection_name = collection_name
        self._client = chromadb.PersistentClient(path=db_path)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": metric},
        )
        logger.info(f"ChromaDB ready at {db_path}, collection: {collection_name}")

    def upsert(self, path: str, embedding: np.ndarray, name: str = "") -> None:
        """Store an embedding for the given file path.

        Args:
            path: Absolute file path (used as document ID)
            embedding: Numpy embedding vector
            name: Optional person name for metadata
        """
        metadata: dict[str, str] = {"abs_path": path}
        if name:
            metadata["name"] = name
        self._collection.upsert(
            ids=[path],
            embeddings=[embedding.tolist()],
            metadatas=[metadata],
        )

    def query(self, embedding: list[float], n_results: int = 10) -> list[dict]:
        """Query the collection for similar images.

        Returns:
            List of dicts with 'id', 'abs_path', and 'distance'
        """
        res = self._collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            include=["metadatas", "distances"],
        )
        results = []
        for i, doc_id in enumerate(res["ids"][0]):
            meta = res["metadatas"][0][i] if res["metadatas"] else {}
            distance = res["distances"][0][i] if res["distances"] else None
            results.append({
                "id": doc_id,
                "abs_path": meta.get("abs_path", doc_id),
                "distance": distance,
                "name": meta.get("name", ""),
            })
        return results

    def query_inverted(self, embedding: list[float], n_results: int = 10) -> list[dict]:
        """Query the collection for the least similar images (farthest away).

        ChromaDB only supports nearest-neighbor search, so we fetch all
        embeddings and compute distances manually.

        Args:
            embedding: Query embedding vector
            n_results: Number of farthest results to return

        Returns:
            List of dicts with 'id', 'abs_path', and 'distance' (descending order)
        """
        all_data = self._collection.get(
            include=["embeddings", "metadatas"],
        )

        if not all_data["ids"]:
            return []

        results = []
        query_vec = np.array(embedding)

        for i, doc_id in enumerate(all_data["ids"]):
            emb = np.array(all_data["embeddings"][i])
            cos_sim = np.dot(query_vec, emb) / (np.linalg.norm(query_vec) * np.linalg.norm(emb))
            distance = 1.0 - cos_sim
            meta = all_data["metadatas"][i] if all_data["metadatas"] else {}
            results.append({
                "id": doc_id,
                "abs_path": meta.get("abs_path", doc_id),
                "distance": float(distance),
            })

        results.sort(key=lambda x: x["distance"], reverse=True)
        return results[:n_results]

    def exists(self, path: str) -> bool:
        """Check if a file path already exists in the collection."""
        try:
            res = self._collection.get(ids=[path], include=[])
            return len(res["ids"]) > 0
        except Exception:
            return False

    def get_all_paths(self) -> list[str]:
        """Return all stored file paths."""
        res = self._collection.get(include=[])
        return res["ids"]


# ------------------------------------------------------------------
# Model loading
# ------------------------------------------------------------------

def load_model(device: str = "cpu") -> torch.nn.Module:
    """Load the ArcFace ViT model via timm.

    Args:
        device: "cpu" or "cuda"

    Returns:
        Loaded and evaluated model
    """
    logger.info(f"Loading model {FACE_EMBEDDING_MODEL_NAME} on {device}...")
    model = timm.create_model(FACE_EMBEDDING_MODEL_NAME, pretrained=True)
    model = model.to(device)
    model.eval()
    logger.info("Model loaded successfully.")
    return model


# ------------------------------------------------------------------
# Image preprocessing and embedding
# ------------------------------------------------------------------

def preprocess_image(image: Image.Image) -> torch.Tensor:
    """Preprocess a PIL image for the ArcFace model.

    Args:
        image: PIL Image (will be converted to RGB and resized)

    Returns:
        Preprocessed tensor of shape (3, FACE_INPUT_SIZE, FACE_INPUT_SIZE)
    """
    image = image.convert("RGB")
    image = image.resize((FACE_INPUT_SIZE, FACE_INPUT_SIZE), Image.Resampling.BILINEAR)
    tensor = torch.from_numpy(np.array(image)).permute(2, 0, 1).float() / 255.0
    return tensor


def embed_image(image: Image.Image, model: torch.nn.Module, device: str) -> np.ndarray:
    """Generate an embedding for a single image.

    Args:
        image: PIL Image (must be RGB)
        model: ArcFace ViT model
        device: "cpu" or "cuda"

    Returns:
        Numpy array of the normalized embedding vector (512-dim)
    """
    tensor = preprocess_image(image).unsqueeze(0).to(device)
    with torch.no_grad():
        embedding = model(tensor)
        embedding = F.normalize(embedding, dim=1)
    return embedding.squeeze(0).cpu().numpy()


# ------------------------------------------------------------------
# Face search orchestrator
# ------------------------------------------------------------------

class FaceSearcher:
    """Encapsulates face search: fuzzy name match -> ArcFace embedding -> ChromaDB query.

    This class loads names.yaml for fuzzy matching, lazily initializes
    the ArcFace model and ChromaDB connection, and provides a single
    search method that ties it all together.
    """

    def __init__(self, names_path: Path, persons_db_path: str = PERSONS_DB_PATH) -> None:
        self._names_path = names_path
        self._persons_db_path = persons_db_path
        self._names: dict[str, str] = {}
        self._model: Optional[torch.nn.Module] = None
        self._db: Optional[PersonDB] = None
        self._load_names()

    # -- Initialization --------------------------------------------------

    def _load_names(self) -> None:
        """Load names.yaml into memory."""
        import yaml
        if not self._names_path.exists():
            logger.warning(f"[face_search] names.yaml not found: {self._names_path}")
            self._names = {}
            return
        try:
            with open(self._names_path) as f:
                self._names = yaml.safe_load(f) or {}
        except Exception as exc:
            logger.warning(f"[face_search] Failed to load names.yaml: {exc}")
            self._names = {}

    def _get_model(self) -> torch.nn.Module:
        """Lazy-load the ArcFace model."""
        if self._model is None:
            self._model = load_model("cpu")
        return self._model

    def _get_db(self) -> PersonDB:
        """Lazy-load the persons.db ChromaDB instance."""
        if self._db is None:
            self._db = PersonDB(db_path=self._persons_db_path)
        return self._db

    # -- Fuzzy matching --------------------------------------------------

    def _fuzzy_match(self, query: str) -> Optional[str]:
        """Fuzzy-match query against names.yaml keys.

        Returns the best-matching name key (original casing), or None if
        no match found with cutoff >= 0.5.
        """
        if not query or not self._names:
            return None

        query_lower = query.lower().strip()
        if not query_lower:
            return None

        # Build lowercase lookup dict
        keys_lower = {k.lower(): k for k in self._names.keys()}
        matches = get_close_matches(query_lower, list(keys_lower.keys()), n=1, cutoff=0.5)

        if matches:
            return keys_lower[matches[0]]
        return None

    # -- Image embedding -------------------------------------------------

    def _embed_image(self, image_path: Path) -> Optional[np.ndarray]:
        """Generate a face embedding for a single image.

        Returns a 512-dim L2-normalized numpy array, or None on failure.
        """
        try:
            image = Image.open(image_path).convert("RGB")
            return embed_image(image, self._get_model(), "cpu")
        except Exception as exc:
            logger.warning(f"[face_search] Failed to embed {image_path}: {exc}")
            return None

    # -- Main search method ----------------------------------------------

    def search(self, query: str, n_results: int = 10) -> list[FileEntry]:
        """Perform a face search for the given query string.

        Pipeline:
        1. Fuzzy-match query against names.yaml keys
        2. If match found, embed the referenced image
        3. Query persons.db ChromaDB for similar faces
        4. Convert results to FileEntry list

        Args:
            query: User's search text (e.g., "jacqueline")
            n_results: Number of results to return

        Returns:
            List of FileEntry objects for matching images.
            Returns an **empty list** if no name match is found.
        """
        # Step 1: Fuzzy match against names
        name = self._fuzzy_match(query)
        if name is None:
            logger.debug(f"[face_search] No name match for query: '{query}'")
            return []

        # Step 2: Look up image path
        image_path_str = self._names.get(name)
        if not image_path_str:
            logger.warning(f"[face_search] No image path for name: '{name}'")
            return []

        image_path = Path(image_path_str)
        if not image_path.exists():
            logger.warning(f"[face_search] Referenced image not found: {image_path}")
            return []

        # Step 3: Generate face embedding
        embedding = self._embed_image(image_path)
        if embedding is None:
            logger.warning(f"[face_search] Failed to generate embedding for {image_path}")
            return []

        # Step 4: Query ChromaDB for similar faces
        db = self._get_db()
        results = db.query(embedding.tolist(), n_results=n_results)

        # Step 5: Convert to FileEntry list
        entries: list[FileEntry] = []
        for result in results:
            full = Path(result["abs_path"])
            if not full.exists():
                logger.debug(f"[face_search] Skipping deleted file: {full}")
                continue
            try:
                stat = full.stat()
                person_name = result.get("name", "")
                entries.append(FileEntry(
                    path=str(full),
                    name=full.name,
                    is_dir=False,
                    size=stat.st_size,
                    modified=stat.st_mtime,
                    person_name=person_name,
                ))
            except OSError as exc:
                logger.warning(f"[face_search] Failed to stat {full}: {exc}")

        logger.info(f"[face_search] Found {len(entries)} face match(es) for '{name}'")
        return entries
