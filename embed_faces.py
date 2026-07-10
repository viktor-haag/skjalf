#!/usr/bin/env python3
"""Standalone script for embedding images into ChromaDB for face recognition.

Usage:
    python embed_faces.py embed <folder> [--db persons.db] [--device cpu|cuda]
    python embed_faces.py search <image> [--db persons.db] [--top_k N] [--json]

Uses the gaunernst/vit_tiny_patch8_112.arcface_ms1mv3 ViT model via timm
to generate 512-dimensional embeddings stored in a ChromaDB "persons" collection.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import chromadb
import numpy as np
import torch
import torch.nn.functional as F
import timm
from loguru import logger
from PIL import Image, ImageDraw, ImageFont

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

MODEL_NAME = "hf_hub:gaunernst/vit_tiny_patch8_112.arcface_ms1mv3"
INPUT_SIZE = 112  # Model expects 112x112 input
EMBEDDING_DIM = 512  # Model outputs 512-dimensional embeddings
BATCH_SIZE = 32  # Batch size for efficient processing


# ------------------------------------------------------------------
# Model loading
# ------------------------------------------------------------------

def load_model(device: str = "cpu") -> torch.nn.Module:
    """Load the ViT model via timm.

    Args:
        device: "cpu" or "cuda"

    Returns:
        Loaded and evaluated model
    """
    logger.info(f"Loading model {MODEL_NAME} on {device}...")
    model = timm.create_model(MODEL_NAME, pretrained=True)
    model = model.to(device)
    model.eval()
    logger.info("Model loaded successfully.")
    return model


# ------------------------------------------------------------------
# ChromaDB wrapper (inspired by FolderEmbedDB in skjalf)
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

    def upsert(self, path: str, embedding: np.ndarray) -> None:
        """Store an embedding for the given file path."""
        self._collection.upsert(
            ids=[path],
            embeddings=[embedding.tolist()],
            metadatas=[{"abs_path": path}],
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
        # Fetch all documents from the collection
        all_data = self._collection.get(
            include=["embeddings", "metadatas"],
        )

        if not all_data["ids"]:
            return []

        results = []
        query_vec = np.array(embedding)

        for i, doc_id in enumerate(all_data["ids"]):
            emb = np.array(all_data["embeddings"][i])
            # Cosine distance = 1 - cosine_similarity
            # Since embeddings are L2-normalized, cosine_sim = dot product
            cos_sim = np.dot(query_vec, emb) / (np.linalg.norm(query_vec) * np.linalg.norm(emb))
            distance = 1.0 - cos_sim  # Convert to distance (0 = identical, 2 = opposite)
            meta = all_data["metadatas"][i] if all_data["metadatas"] else {}
            results.append({
                "id": doc_id,
                "abs_path": meta.get("abs_path", doc_id),
                "distance": float(distance),
            })

        # Sort by distance descending (farthest first)
        results.sort(key=lambda x: x["distance"], reverse=True)
        return results[:n_results]

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
        # Fetch all documents from the collection
        all_data = self._collection.get(
            include=["embeddings", "metadatas"],
        )

        if not all_data["ids"]:
            return []

        results = []
        query_vec = np.array(embedding)

        for i, doc_id in enumerate(all_data["ids"]):
            emb = np.array(all_data["embeddings"][i])
            # Cosine distance = 1 - cosine_similarity
            # Since embeddings are L2-normalized, cosine_sim = dot product
            cos_sim = np.dot(query_vec, emb) / (np.linalg.norm(query_vec) * np.linalg.norm(emb))
            distance = 1.0 - cos_sim  # Convert to distance (0 = identical, 2 = opposite)
            meta = all_data["metadatas"][i] if all_data["metadatas"] else {}
            results.append({
                "id": doc_id,
                "abs_path": meta.get("abs_path", doc_id),
                "distance": float(distance),
            })

        # Sort by distance descending (farthest first)
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
# Image preprocessing
# ------------------------------------------------------------------

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}


def is_image_file(path: Path) -> bool:
    """Check if a file is a supported image."""
    return path.suffix.lower() in IMAGE_EXTENSIONS


def preprocess_image(image: Image.Image) -> torch.Tensor:
    """Preprocess a PIL image for the model.

    Args:
        image: PIL Image (will be converted to RGB and resized)

    Returns:
        Preprocessed tensor of shape (3, INPUT_SIZE, INPUT_SIZE)
    """
    image = image.convert("RGB")
    image = image.resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.BILINEAR)
    # Convert to tensor and normalize to [0, 1]
    tensor = torch.from_numpy(np.array(image)).permute(2, 0, 1).float() / 255.0
    return tensor


# ------------------------------------------------------------------
# Image embedding
# ------------------------------------------------------------------

def embed_image(image: Image.Image, model: torch.nn.Module, device: str) -> np.ndarray:
    """Generate an embedding for a single image.

    Args:
        image: PIL Image (must be RGB)
        model: ViT model
        device: "cpu" or "cuda"

    Returns:
        Numpy array of the normalized embedding vector
    """
    tensor = preprocess_image(image).unsqueeze(0).to(device)
    with torch.no_grad():
        embedding = model(tensor)
        embedding = F.normalize(embedding, dim=1)
    return embedding.squeeze(0).cpu().numpy()


def embed_batch(images: list[Image.Image], model: torch.nn.Module, device: str) -> np.ndarray:
    """Generate embeddings for a batch of images efficiently.

    Args:
        images: List of PIL Images
        model: ViT model
        device: "cpu" or "cuda"

    Returns:
        Numpy array of shape (len(images), EMBEDDING_DIM) with normalized embeddings
    """
    tensors = [preprocess_image(img).unsqueeze(0) for img in images]
    batch = torch.cat(tensors, dim=0).to(device)

    with torch.no_grad():
        embeddings = model(batch)
        embeddings = F.normalize(embeddings, dim=1)

    return embeddings.cpu().numpy()


def embed_file(file_path: Path, model: torch.nn.Module, device: str) -> Optional[np.ndarray]:
    """Embed a single image file.

    Returns:
        Embedding vector or None if failed
    """
    try:
        image = Image.open(file_path).convert("RGB")
        embedding = embed_image(image, model, device)
        return embedding
    except Exception as e:
        logger.warning(f"Failed to embed {file_path}: {e}")
        return None


# ------------------------------------------------------------------
# Embed command logic
# ------------------------------------------------------------------

def embed_folder(folder_path: Path, db: PersonDB, model: torch.nn.Module, device: str) -> None:
    """Embed all images in a folder into ChromaDB.

    Skips files already in the database (incremental update).
    Uses batch processing for efficiency.
    """
    if not folder_path.is_dir():
        logger.error(f"Not a directory: {folder_path}")
        sys.exit(1)

    images = sorted([
        p for p in folder_path.rglob("*")
        if p.is_file() and is_image_file(p)
    ])

    total = len(images)
    logger.info(f"Found {total} image(s) in {folder_path}")

    if not images:
        logger.warning(f"No images found in {folder_path}")
        return

    embedded = 0
    skipped = 0
    failed = 0

    # Process in batches for efficiency
    for i in range(0, total, BATCH_SIZE):
        batch_paths = images[i:i + BATCH_SIZE]
        batch_abs_paths = [str(p.resolve()) for p in batch_paths]

        # Check which files need embedding (incremental)
        to_embed = []
        for j, abs_path in enumerate(batch_abs_paths):
            if db.exists(abs_path):
                skipped += 1
                logger.debug(f"Skipping (already embedded): {abs_path}")
            else:
                to_embed.append(batch_paths[j])

        # Embed the batch
        if to_embed:
            try:
                batch_images = [Image.open(p).convert("RGB") for p in to_embed]
                batch_embeddings = embed_batch(batch_images, model, device)

                for k, (path, embedding) in enumerate(zip(to_embed, batch_embeddings)):
                    abs_path = str(path.resolve())
                    db.upsert(abs_path, embedding)
                    embedded += 1
            except Exception as e:
                failed += len(to_embed)
                logger.error(f"Failed to embed batch: {e}")

        # Progress reporting
        if (i + BATCH_SIZE) % 10 == 0 or (i + BATCH_SIZE) == total:
            logger.info(f"Progress: {min(i + BATCH_SIZE, total)}/{total} ({embedded} embedded, {skipped} skipped, {failed} failed)")

    logger.info(f"Embedding complete: {embedded} new, {skipped} skipped, {failed} failed, {total} total")


# ------------------------------------------------------------------
# Search command logic
# ------------------------------------------------------------------

def search_image(
    query_path: Path,
    db: PersonDB,
    model: torch.nn.Module,
    device: str,
    top_k: int = 10,
    as_json: bool = False,
    visualize: bool = False,
    invert: bool = False,
) -> None:
    """Search for similar images to a query image.

    Args:
        query_path: Path to the query image
        db: PersonDB instance
        model: ViT model
        device: "cpu" or "cuda"
        top_k: Number of results to return
        as_json: If True, output as JSON
        visualize: If True, create a composite visualization image
        invert: If True, return farthest samples instead of closest
    """
    abs_path = str(query_path.resolve())

    # Generate embedding for query image
    try:
        image = Image.open(query_path).convert("RGB")
        embedding = embed_image(image, model, device)
    except Exception as e:
        logger.error(f"Failed to embed query image {query_path}: {e}")
        sys.exit(1)

    # Query ChromaDB
    if invert:
        results = db.query_inverted(embedding.tolist(), n_results=top_k)
    else:
        results = db.query(embedding.tolist(), n_results=top_k)

    if as_json:
        output = {
            "query": abs_path,
            "results": results,
        }
        print(json.dumps(output, indent=2))

    if visualize:
        _create_visualization(query_path, results)

    if as_json or visualize:
        # Console output is also shown when visualize is used
        pass
    else:
        print(f"Query: {abs_path}")
        print(f"Top {len(results)} similar images:")
        for i, result in enumerate(results, start=1):
            distance = result.get("distance")
            dist_str = f"{distance:.4f}" if distance is not None else "N/A"
            print(f"  {i}. {result['abs_path']} (distance: {dist_str})")


def _create_visualization(query_path: Path, results: list[dict], output_path: str = "search_results.png") -> None:
    """Create a composite image with query in center and results in a 3x3 grid.

    Args:
        query_path: Path to the query image
        results: List of result dicts from ChromaDB query
        output_path: Path to save the output image
    """
    # Grid layout: 3x3 = 9 cells
    # Center cell (1,1) = query image
    # Surrounding 8 cells = top 8 results (or fewer if less than 9 results)
    # Labels below each image

    CELL_SIZE = 200  # pixels per cell
    LABEL_HEIGHT = 30  # pixels for distance label
    MARGIN = 10  # margin between cells
    TITLE_HEIGHT = 50  # title at top

    # Calculate grid dimensions
    grid_cols = 3
    grid_rows = 3
    total_width = grid_cols * CELL_SIZE + (grid_cols + 1) * MARGIN
    total_height = grid_rows * (CELL_SIZE + LABEL_HEIGHT) + (grid_rows + 1) * MARGIN + TITLE_HEIGHT

    # Create blank image with white background
    viz_image = Image.new("RGB", (total_width, total_height), "white")
    draw = ImageDraw.Draw(viz_image)

    # Add title
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
    except (IOError, OSError):
        font = ImageFont.load_default()

    title = "Similar Images"
    bbox = draw.textbbox((0, 0), title, font=font)
    title_width = bbox[2] - bbox[0]
    draw.text(((total_width - title_width) // 2, 10), title, fill="black", font=font)

    # Helper function to place image in grid cell
    def place_image(img: Image.Image, row: int, col: int, label: str = "") -> None:
        """Place an image in the grid at (row, col) with optional label."""
        # Calculate position
        x = MARGIN + col * (CELL_SIZE + MARGIN)
        y = TITLE_HEIGHT + MARGIN + row * (CELL_SIZE + LABEL_HEIGHT + MARGIN)

        # Resize image to fit cell
        img_resized = img.copy()
        img_resized.thumbnail((CELL_SIZE, CELL_SIZE), Image.Resampling.LANCZOS)

        # Center image in cell
        img_x = x + (CELL_SIZE - img_resized.width) // 2
        img_y = y + (CELL_SIZE - img_resized.height) // 2
        viz_image.paste(img_resized, (img_x, img_y))

        # Draw border around cell
        draw.rectangle(
            [x, y, x + CELL_SIZE - 1, y + CELL_SIZE - 1],
            outline="gray",
            width=2,
        )

        # Draw label below image
        if label:
            try:
                label_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
            except (IOError, OSError):
                label_font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), label, font=label_font)
            label_width = bbox[2] - bbox[0]
            label_x = x + (CELL_SIZE - label_width) // 2
            label_y = y + CELL_SIZE + 5
            draw.text((label_x, label_y), label, fill="black", font=label_font)

    # Load query image
    try:
        query_img = Image.open(query_path).convert("RGB")
    except Exception as e:
        logger.error(f"Failed to load query image: {e}")
        return

    # Place query image in center (row=1, col=1)
    place_image(query_img, 1, 1, "Query")

    # Place results in surrounding cells
    # Grid positions (row, col) for 3x3 grid excluding center (1,1):
    # (0,0) (0,1) (0,2)
    # (1,0)       (1,2)
    # (2,0) (2,1) (2,2)
    grid_positions = [
        (0, 0), (0, 1), (0, 2),
        (1, 0),         (1, 2),
        (2, 0), (2, 1), (2, 2),
    ]

    for i, result in enumerate(results[:8]):  # Max 8 results for surrounding cells
        if i >= len(grid_positions):
            break

        row, col = grid_positions[i]
        abs_path = result.get("abs_path", result.get("id", ""))

        try:
            result_img = Image.open(abs_path).convert("RGB")
            distance = result.get("distance", 0)
            label = f"Dist: {distance:.4f}"
            place_image(result_img, row, col, label)
        except Exception as e:
            logger.warning(f"Failed to load result image {abs_path}: {e}")
            # Place placeholder
            placeholder = Image.new("RGB", (CELL_SIZE, CELL_SIZE), "lightgray")
            draw = ImageDraw.Draw(placeholder)
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 10)
            except (IOError, OSError):
                font = ImageFont.load_default()
            draw.text((10, 10), "N/A", fill="black", font=font)
            place_image(placeholder, row, col, "Error")

    # Save the visualization
    viz_image.save(output_path)
    logger.info(f"Visualization saved to {output_path}")


# ------------------------------------------------------------------
# CLI interface
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Embed images into ChromaDB for face recognition and similarity search."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Embed command
    embed_parser = subparsers.add_parser("embed", help="Embed all images in a folder")
    embed_parser.add_argument("folder", type=Path, help="Path to folder containing images")
    embed_parser.add_argument("--db", type=str, default="persons.db", help="Path to ChromaDB file (default: persons.db)")
    embed_parser.add_argument("--device", type=str, default="cpu", choices=["cpu", "cuda"], help="Device to use (default: cpu)")

    # Search command
    search_parser = subparsers.add_parser("search", help="Search for similar images")
    search_parser.add_argument("image", type=Path, help="Path to query image")
    search_parser.add_argument("--db", type=str, default="persons.db", help="Path to ChromaDB file (default: persons.db)")
    search_parser.add_argument("--top_k", type=int, default=10, help="Number of results to return (default: 10)")
    search_parser.add_argument("--json", action="store_true", help="Output results as JSON")
    search_parser.add_argument("--visualize", action="store_true", help="Create a composite image with query and results")
    search_parser.add_argument("--invert", action="store_true", help="Return the farthest samples instead of closest")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Setup logging
    logger.remove()
    logger.add(sys.stderr, level="INFO")

    # Initialize ChromaDB
    db = PersonDB(db_path=args.db)

    if args.command == "embed":
        if not args.folder.exists():
            logger.error(f"Folder not found: {args.folder}")
            sys.exit(1)

        # Load model
        model = load_model(args.device)

        # Embed folder
        embed_folder(args.folder, db, model, args.device)

    elif args.command == "search":
        if not args.image.exists():
            logger.error(f"Image not found: {args.image}")
            sys.exit(1)

        # Load model for query
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = load_model(device)

        # Search
        search_image(args.image, db, model, device, top_k=args.top_k, as_json=args.json, visualize=args.visualize, invert=args.invert)


if __name__ == "__main__":
    main()
