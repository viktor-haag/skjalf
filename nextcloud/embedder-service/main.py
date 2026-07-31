"""
Skjalf Embedder Service for Nextcloud.

FastAPI service that provides image embedding, search, and folder management
for the Nextcloud Skjalf Search app.
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SKJAFALF_API_URL = os.getenv("SKJAFALF_API_URL", "http://localhost:8000")
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "skjalf_nextcloud")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    limit: int = 20
    threshold: float = 0.5
    folder_id: Optional[str] = None


class EmbedResponse(BaseModel):
    file_id: int
    status: str
    chroma_id: Optional[str] = None
    error: Optional[str] = None


class SearchResponse(BaseModel):
    results: list
    count: int


class FolderResponse(BaseModel):
    folders: list
    embedder_available: bool


# ---------------------------------------------------------------------------
# ChromaDB client
# ---------------------------------------------------------------------------

import chromadb
from chromadb.config import Settings

chroma_client = chromadb.Client(
    Settings(persist_directory=os.path.join(tempfile.gettempdir(), "chroma_skjalf"))
)
chroma_collection = chroma_client.get_or_create_collection(name=CHROMA_COLLECTION)

# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------

try:
    from sentence_transformers import SentenceTransformer
    embedder = SentenceTransformer(EMBEDDING_MODEL)
except ImportError:
    logger.warning("sentence-transformers not installed; using random embeddings")
    embedder = None


def encode_image(image_path: str) -> np.ndarray:
    """Encode an image file to a vector embedding."""
    from PIL import Image
    import clip  # OpenCLIP for image embeddings

    image = Image.open(image_path).convert("RGB")
    return clip.encode_image(image).cpu().numpy()


def encode_text(text: str) -> np.ndarray:
    """Encode a text query to a vector embedding."""
    if embedder is not None:
        return embedder.encode([text])[0]
    return np.random.rand(384).astype(np.float32)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Skjalf Embedder Service",
    description="Image embedding and search backend for Nextcloud Skjalf Search",
    version="0.1.0",
)


@app.get("/health")
async def health():
    return {"status": "ok", "collection": CHROMA_COLLECTION}


@app.post("/api/v1/embed", response_model=EmbedResponse)
async def embed_image(file_id: int, file_path: str):
    """Embed a single image file."""
    try:
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found")

        embedding = encode_image(file_path)
        chroma_id = f"nc_{file_id}"

        chroma_collection.add(
            ids=[chroma_id],
            embeddings=[embedding.tolist()],
            metadatas=[{
                "file_id": str(file_id),
                "file_path": file_path,
                "mimetype": "image/jpeg",
            }],
        )

        logger.info(f"Embedded image file_id={file_id} chroma_id={chroma_id}")
        return EmbedResponse(file_id=file_id, status="complete", chroma_id=chroma_id)

    except Exception as e:
        logger.exception(f"Embedding failed for file_id={file_id}")
        return EmbedResponse(file_id=file_id, status="error", error=str(e))


@app.post("/api/v1/upload", response_model=EmbedResponse)
async def upload_and_embed(file_id: int, file: UploadFile):
    """Upload an image and embed it."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        return await embed_image(file_id=file_id, file_path=tmp_path)
    except Exception as e:
        return EmbedResponse(file_id=file_id, status="error", error=str(e))


@app.post("/api/v1/search", response_model=SearchResponse)
async def search_images(req: SearchRequest):
    """Search for images matching a text query."""
    try:
        query_vec = encode_text(req.query)

        results = chroma_collection.query(
            query_embeddings=[query_vec.tolist()],
            n_results=min(req.limit, 100),
            where={"threshold": {"$gte": req.threshold}},
            include=["metadatas", "distances"],
        )

        formatted = []
        for i, meta in enumerate(results["metadatas"][0]):
            formatted.append({
                "file_id": int(meta["file_id"]),
                "file_path": meta["file_path"],
                "similarity": float(1 - results["distances"][0][i]),
            })

        return SearchResponse(results=formatted, count=len(formatted))

    except Exception as e:
        logger.exception("Search failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/folders", response_model=FolderResponse)
async def get_folders():
    """Get registered folders from Skjalf core."""
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{SKJAFALF_API_URL}/api/v1/folders")
            data = resp.json()
            return FolderResponse(
                folders=data.get("folders", []),
                embedder_available=True,
            )
    except Exception as e:
        logger.exception("Failed to get folders")
        return FolderResponse(folders=[], embedder_available=False)


@app.post("/api/v1/folders/register")
async def register_folder(folder_path: str):
    """Register a folder for monitoring."""
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{SKJAFALF_API_URL}/api/v1/folders/register",
                json={"path": folder_path},
            )
            resp.raise_for_status()
            return {"status": "registered"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8101)
