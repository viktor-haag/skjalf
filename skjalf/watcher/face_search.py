"""Face search module for Skjalf.

This module provides face recognition search capabilities using the
ArcFace ViT model via timm. It queries face embeddings stored in
per-folder ChromaDB instances (``.skjalf/`` subdirectories) and provides
fuzzy name matching against a names.yaml file.

Usage:
    searcher = FaceSearcher(names_path)
    searcher.set_folder_db_dirs([Path("/data/photos/.skjalf"), ...])
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
    FACE_COLLECTION_NAME,
)


# ------------------------------------------------------------------
# Model loading
# ------------------------------------------------------------------

def load_face_model(device: str = "cpu") -> torch.nn.Module:
    """Load the ArcFace ViT model via timm.

    Args:
        device: "cpu" or "cuda"

    Returns:
        Loaded and evaluated model
    """
    logger.info(f"[face_search] Loading model {FACE_EMBEDDING_MODEL_NAME} on {device}...")
    model = timm.create_model(FACE_EMBEDDING_MODEL_NAME, pretrained=True)
    model = model.to(device)
    model.eval()
    logger.info("[face_search] ArcFace model loaded successfully.")
    return model


# ------------------------------------------------------------------
# Image preprocessing and embedding
# ------------------------------------------------------------------

def preprocess_face_image(image: Image.Image, input_size: int = FACE_INPUT_SIZE) -> torch.Tensor:
    """Preprocess a PIL image for the ArcFace model.

    Args:
        image: PIL Image (will be converted to RGB and resized)

    Returns:
        Preprocessed tensor of shape (3, FACE_INPUT_SIZE, FACE_INPUT_SIZE)
    """
    image = image.convert("RGB")
    image = image.resize((input_size, input_size), Image.Resampling.BILINEAR)
    tensor = torch.from_numpy(np.array(image)).permute(2, 0, 1).float() / 255.0
    return tensor


def embed_face_image(image: Image.Image, model: torch.nn.Module, device: str = "cpu") -> np.ndarray:
    """Generate a face embedding for a single image.

    Args:
        image: PIL Image (must be RGB)
        model: ArcFace ViT model
        device: "cpu" or "cuda"

    Returns:
        Numpy array of the normalized embedding vector (512-dim)
    """
    tensor = preprocess_face_image(image).unsqueeze(0).to(device)
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
    the ArcFace model, and queries face embeddings stored in per-folder
    ChromaDB instances.
    """

    def __init__(self, names_path: Path) -> None:
        self._names_path = names_path
        self._names: dict[str, str] = {}
        self._model: Optional[torch.nn.Module] = None
        self._device: str = "cpu"
        self._face_db_dirs: list[Path] = []  # List of .skjalf/ directories to search
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
            self._model = load_face_model(self._device)
        return self._model

    def set_device(self, device: str) -> None:
        """Set the device for face embedding model."""
        if self._device == device:
            return
        self._device = device
        self._model = None  # Force reload on next use
        logger.info(f"[face_search] device switched to {device}")

    def set_folder_db_dirs(self, db_dirs: list[Path]) -> None:
        """Set the list of .skjalf/ directories to search for face embeddings.

        Args:
            db_dirs: List of resolved paths to .skjalf/ directories (one per registered folder)
        """
        self._face_db_dirs = db_dirs

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
            return embed_face_image(image, self._get_model(), self._device)
        except Exception as exc:
            logger.warning(f"[face_search] Failed to embed {image_path}: {exc}")
            return None

    # -- Main search method ----------------------------------------------

    def search(self, query: str, n_results: int = 10) -> list[FileEntry]:
        """Perform a face search for the given query string.

        Pipeline:
        1. Fuzzy-match query against names.yaml keys
        2. If match found, embed the referenced image
        3. Query all registered folders' face_embeddings collections
        4. Merge and sort results by distance
        5. Convert results to FileEntry list

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

        # Step 4: Query all registered folders' face_embeddings collections
        all_results: list[dict] = []
        for db_dir in self._face_db_dirs:
            try:
                client = chromadb.PersistentClient(path=str(db_dir))
                collection = client.get_collection(
                    name=FACE_COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
                res = collection.query(
                    query_embeddings=[embedding.tolist()],
                    n_results=min(n_results * 3, 50),  # Fetch more to merge across folders
                    include=["metadatas", "distances"],
                )
                for i, doc_id in enumerate(res["ids"][0]):
                    meta = res["metadatas"][0][i] if res["metadatas"] else {}
                    distance = res["distances"][0][i] if res["distances"] else None
                    all_results.append({
                        "id": doc_id,
                        "abs_path": meta.get("abs_path", doc_id),
                        "distance": distance,
                        "name": meta.get("name", ""),
                    })
            except Exception as e:
                logger.warning(f"[face_search] Error querying face DB at {db_dir}: {e}")

        # Sort by distance and take top n_results
        all_results.sort(key=lambda x: x["distance"] if x["distance"] is not None else float("inf"))
        all_results = all_results[:n_results]

        # Step 5: Convert to FileEntry list
        entries: list[FileEntry] = []
        for result in all_results:
            full = Path(result["abs_path"])
            if not full.exists():
                logger.debug(f"[face_search] Skipping deleted file: {full}")
                continue
            try:
                stat = full.stat()
                entries.append(FileEntry(
                    path=str(full),
                    name=full.name,
                    is_dir=False,
                    size=stat.st_size,
                    modified=stat.st_mtime,
                    person_name=result.get("name", ""),
                ))
            except OSError as exc:
                logger.warning(f"[face_search] Failed to stat {full}: {exc}")

        logger.info(f"[face_search] Found {len(entries)} face match(es) for '{name}'")
        return entries
