# Face Embedding CLI Tool

A standalone Python script for embedding images into ChromaDB for face recognition and similarity search.

## Overview

This tool uses the `gaunernst/vit_tiny_patch8_112.arcface_ms1mv3` ViT model to generate 512-dimensional embeddings for images, stored in a ChromaDB "persons" collection. It supports:

- **Batch embedding** of all images in a folder
- **Incremental updates** (skips already-embedded files)
- **Image-to-image similarity search** with configurable top_k results
- **Console and JSON output** formats

## Installation

### Prerequisites

- Python 3.12+
- torch (>=2.12.0)
- timm (>=1.0.0)
- chromadb (>=1.5.9)
- pillow (>=10.0)
- loguru (>=0.7.3)

### Install Dependencies

```bash
# Using uv (recommended)
uv pip install torch timm chromadb pillow loguru

# Or using pip
pip install torch timm chromadb pillow loguru
```

**Note:** The model is loaded from Hugging Face on first run. An internet connection is required for the initial download.

## Usage

### Embed Images

Embed all images in a folder into the ChromaDB "persons" collection:

```bash
# Basic usage (uses default persons.db in current directory)
python embed_faces.py embed /path/to/images

# Use GPU acceleration (if available)
python embed_faces.py embed /path/to/images --device cuda

# Use a custom ChromaDB location
python embed_faces.py embed /path/to/images --db /path/to/custom.db

# Specify a different collection name (advanced)
# Edit the script and change the collection_name parameter in PersonDB.__init__
```

**Supported image formats:** JPEG, PNG, BMP, TIFF, WebP

**Features:**
- Recursively searches subdirectories
- Skips files already in the database (incremental updates)
- Processes images in batches of 32 for efficiency
- Reports progress every 10 images

### Search Similar Images

Find images similar to a query image:

```bash
# Basic usage (returns top 10 results)
python embed_faces.py search /path/to/query_image.jpg

# Specify number of results
python embed_faces.py search /path/to/query_image.jpg --top_k 5

# Output as JSON (for machine consumption)
python embed_faces.py search /path/to/query_image.jpg --top_k 5 --json

# Create a visualization image
python embed_faces.py search /path/to/query_image.jpg --top_k 8 --visualize

# Search for the most dissimilar images
python embed_faces.py search /path/to/query_image.jpg --top_k 5 --invert
```

The `--visualize` flag creates a composite image (`search_results.png`) with:
- The **query image** in the center cell
- The **top 8 results** in a 3x3 grid surrounding the query
- **Distance scores** displayed below each image

The `--invert` flag queries the **entire database** and returns the most dissimilar images (farthest distance), rather than just reversing the top_k closest results. This gives you the truly most different images in the collection.

## How It Works

### Model

Uses the `gaunernst/vit_tiny_patch8_112.arcface_ms1mv3` model:
- **Type:** Vision Transformer (ViT) with ArcFace loss
- **Input size:** 112x112 pixels
- **Output:** 512-dimensional normalized embedding vector
- **Loading:** Via timm from Hugging Face Hub

### Storage

- **Database:** ChromaDB with persistent storage
- **Collection name:** "persons"
- **Distance metric:** Cosine similarity (HNSW index)
- **Default location:** `persons.db` in current working directory
- **Metadata:** Stores absolute file path per entry

### Embedding Pipeline

```
Image → PIL (RGB) → Resize to 112x112 → Normalize to [0,1]
    → ViT Model → 512-dim embedding → L2 normalize → ChromaDB
```

### Search Pipeline

```
Query Image → Embedding (512-dim) → ChromaDB Query (cosine similarity)
    → Top-k Results → Console/JSON Output
```

### Incremental Updates

When running the embed command:
1. Scans all images in the folder (recursively)
2. Checks if each file path exists in ChromaDB
3. Skips files already embedded
4. Embeds only new or changed files
5. Reports: embedded, skipped, failed counts

## Output Formats

### Console (default)

```
Query: /path/to/query.jpg
Top 5 similar images:
  1. /path/to/similar1.jpg (distance: 0.1234)
  2. /path/to/similar2.jpg (distance: 0.2345)
  3. /path/to/similar3.jpg (distance: 0.3456)
  4. /path/to/similar4.jpg (distance: 0.4567)
  5. /path/to/similar5.jpg (distance: 0.5678)
```

### JSON (--json flag)

```json
{
  "query": "/path/to/query.jpg",
  "results": [
    {"id": "/path/to/similar1.jpg", "abs_path": "/path/to/similar1.jpg", "distance": 0.1234},
    {"id": "/path/to/similar2.jpg", "abs_path": "/path/to/similar2.jpg", "distance": 0.2345},
    {"id": "/path/to/similar3.jpg", "abs_path": "/path/to/similar3.jpg", "distance": 0.3456}
  ]
}
```

## Examples

### Example 1: Embed a Folder and Search

```bash
# Step 1: Embed all images in a folder
python embed_faces.py embed ./photos --db my_faces.db

# Step 2: Search for similar images
python embed_faces.py search ./photos/person.jpg --db my_faces.db --top_k 5

# Step 3: Get JSON output for processing
python embed_faces.py search ./photos/person.jpg --db my_faces.db --json
```

### Example 2: Incremental Update

```bash
# First embedding
python embed_faces.py embed ./photos

# Add new images to the folder
cp new_photos/*.jpg ./photos/

# Re-run - only new images will be embedded
python embed_faces.py embed ./photos
# Output: "Embedding complete: 5 new, 100 skipped, 0 failed, 105 total"
```

### Example 3: Use with GPU

```bash
# Check if CUDA is available
python -c "import torch; print(torch.cuda.is_available())"

# Use GPU for faster embedding
python embed_faces.py embed ./photos --device cuda
```

## Error Handling

The script handles common errors gracefully:

- **Missing folder:** `Error: Folder not found: /path/to/folder`
- **Missing image:** `Error: Image not found: /path/to/image.jpg`
- **Invalid image format:** Skipped with warning message
- **Corrupted image file:** Logged as error, continues with next file
- **Model loading failure:** Logs error and exits with code 1

## Architecture

### File Structure

```
embed_faces.py          # Main script (standalone)
persons.db              # ChromaDB database (created on first embed)
```

### Key Components

- **`load_model()`**: Loads the ViT model via timm
- **`PersonDB`**: ChromaDB wrapper for the "persons" collection
- **`embed_folder()`**: Processes folder with batch embedding
- **`embed_image()`**: Single image embedding with preprocessing
- **`embed_batch()`**: Efficient batch embedding
- **`search_image()`**: Query ChromaDB for similar images

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| torch | >=2.12.0 | Deep learning framework |
| timm | >=1.0.0 | Model loading and inference |
| chromadb | >=1.5.9 | Vector database |
| pillow | >=10.0 | Image processing |
| loguru | >=0.7.3 | Logging |

## Limitations

- **Single embedding per image:** No face detection (one embedding per file)
- **No text search:** Vision-only model (image-to-image only)
- **CPU-only by default:** GPU acceleration requires `--device cuda`
- **No batch search:** Single query image at a time

## Troubleshooting

### Model Download Fails

```
Warning: You are sending unauthenticated requests to the HF Hub.
```

**Solution:** Set a Hugging Face token for higher rate limits:
```bash
export HF_TOKEN=your_token_here
```

### Out of Memory (GPU)

**Solution:** Use CPU or reduce batch size (edit `BATCH_SIZE` in script):
```bash
python embed_faces.py embed ./photos --device cpu
```

### ChromaDB Corrupted

**Solution:** Delete the database and re-embed:
```bash
rm persons.db
python embed_faces.py embed ./photos
```

## License

This script is standalone and independent of the skjalf project. It uses the same dependencies as skjalf but has no code dependencies on skjalf packages.

## Contributing

This is a standalone tool. For issues or improvements, please file an issue or submit a pull request.
