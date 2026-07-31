# Skjalf Search - Nextcloud Plugin

AI-powered image search for Nextcloud using semantic embeddings.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Nextcloud Web   │────▶│  PHP Backend     │────▶│  Python Service │
│  (Vue.js UI)    │     │  (Controllers,   │     │  (FastAPI +     │
│                 │     │   Listeners)     │     │   ChromaDB)     │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                              │
                              ▼
                       ┌──────────────────┐
                       │  Nextcloud DB    │
                       │  (Embedding      │
                       │   Status)        │
                       └──────────────────┘
```

## Components

### 1. Nextcloud App (`skjalf-search/`)
- **Frontend**: Vue.js 3 + Pinia store
- **Backend**: PHP controllers, services, listeners
- **Features**:
  - Image search via text query
  - Automatic embedding on file upload/change
  - Folder monitoring and registration
  - Background job processing

### 2. Embedder Service (`embedder-service/`)
- **Framework**: FastAPI (Python)
- **Embedding**: CLIP/Sentence Transformers
- **Vector Store**: ChromaDB
- **API Endpoints**:
  - `POST /api/v1/embed` - Embed single image
  - `POST /api/v1/search` - Search images
  - `GET /api/v1/folders` - Get registered folders
  - `POST /api/v1/folders/register` - Register folder

## Setup

### Nextcloud App
1. Copy `skjalf-search/` to your Nextcloud `apps/` directory
2. Enable the app in Nextcloud admin settings
3. Configure the embedder service URL in `lib/Controller/APIClient.php`

### Embedder Service
```bash
cd embedder-service
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8101
```

Set environment variables:
- `SKJAFALF_API_URL` - URL to Skjalf core API
- `CHROMA_HOST` - ChromaDB host (default: localhost)
- `CHROMA_PORT` - ChromaDB port (default: 8000)

## Ingest/Query/Retrieve Flow

1. **Ingest**: 
   - User uploads image to Nextcloud
   - `FileChangedListener` detects change
   - `EmbedFileJob` queues embedding
   - Python service encodes image → ChromaDB

2. **Query**:
   - User types search query in Nextcloud UI
   - Vue.js sends request to PHP controller
   - PHP forwards to Python service
   - Query encoded → similarity search in ChromaDB

3. **Retrieve**:
   - ChromaDB returns matching image IDs
   - PHP retrieves file metadata from Nextcloud
   - UI displays results with thumbnails

## License

AGPL-3.0-or-later
