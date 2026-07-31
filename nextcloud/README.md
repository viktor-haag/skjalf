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

### 1. Nextcloud App (`skjalfsearch/`)
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

### Option 1: Docker Compose (Recommended)

```bash
cd nextcloud
docker-compose up -d
```

This starts all services:
- **Nextcloud**: http://localhost:8080
- **Embedder Service**: http://localhost:8101
- **ChromaDB**: http://localhost:8000
- **MySQL**: localhost:3306
- **Redis**: localhost:6379

### Option 2: Manual Installation

#### 1. Install Nextcloud App

```bash
# Copy to custom_apps directory
cp -r skjalfsearch /path/to/nextcloud/custom_apps/skjalfsearch

# Set correct permissions
chown -R www-data:www-data /path/to/nextcloud/custom_apps/skjalfsearch

# Enable the app
cd /path/to/nextcloud
sudo -u www-data php occ app:enable skjalfsearch
```

The app will appear in the **left sidebar** of Nextcloud.

#### 2. Build and Run Frontend

```bash
cd skjalfsearch
npm install
npm run build
```

This compiles the Vue.js frontend and outputs to `js/app.js`.

#### 3. Configure Embedder Service URL

The app needs to know where the Python embedder service is running.

**For Docker Compose**: The default is already configured correctly.

**For manual installation**, update the port in `skjalfsearch/lib/Controller/APIClient.php`:

```php
// Line 42: Change from 8765 to 8101
return 'http://127.0.0.1:8101';
```

Or set it via Nextcloud's app configuration.

#### 4. Start Embedder Service

```bash
cd embedder-service
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8101
```

Set environment variables:
- `SKJAFALF_API_URL` - URL to Skjalf core API
- `CHROMA_HOST` - ChromaDB host (default: localhost)
- `CHROMA_PORT` - ChromaDB port (default: 8000)
- `EMBEDDING_MODEL` - Model for embeddings (default: all-MiniLM-L6-v2)

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
