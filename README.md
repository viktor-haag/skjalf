# NOTE:

This project is still at its prototype stage. While it is fully functioning, it may still have some major bugs or suboptimal performance which should be resolved once milestone 1 is reached.

# Skjalf

**Skjalf** is an image file browser with semantic search capabilities. Skjalf uses AI to understand the content of your images, allowing you to find exactly what you're looking for using natural language queries.

![Skjalf in action](placeholder.gif)

## Features

- **Semantic Search**: Find images by describing their content (e.g., "a cat sleeping on a sofa").
- **Local & Private**: All processing happens locally on your machine. Your images never leave your computer.
- **Folder Watching**: Register folders to automatically scan and embed new images.
- **Drag & Drop**: Easily register folders or move files via drag and drop.
- **Multi-Select & File Operations**: Select multiple files and perform batch operations (copy, move, delete).
- **GPU Acceleration**: Toggle GPU processing for faster embedding generation.

## Technology Stack

- **Language**: Python 3.12+
- **UI Framework**: PySide6
- **Embedding Model**: Hugging Face Transformers (`kakaobrain/align-base`)
- **Vector Storage**: ChromaDB
- **Filesystem Monitoring**: `watchdog`

## Installation & Usage


### Prerequisites

- Python 3.12 or higher
- Git

### 1. Install Skjalf

Clone the repository and install the package:

```bash
git clone https://github.com/viktor-haag/skjalf.git
cd skjalf
pip install .
```

### 2. Download the ALIGN Model

Skjalf uses the `kakaobrain/align-base` model for image understanding. You need to download it locally using the Hugging Face CLI:

```bash
pip install huggingface_hub
hf download kakaobrain/align-base
```

### 3. Run the App

Once installed, you can launch Skjalf from your terminal:

```bash
skjalf
```

## Roadmap

### Milestone 0: Initial Prototype <-- we are here
- [x] Semantic image search using ALIGN model
- [x] Folder registration and recursive scanning
- [x] Local ChromaDB vector storage per folder
- [x] GPU/CPU toggle for embedding
- [x] Multi-file selection and batch operations
- [x] Progress tracking for embeddings and file operations

### Milestone 1: Consolidation & Distribution
- [ ] Drag & drop support (folders & files)
- [ ] Light/Dark mode toggle
- [ ] Codebase refactoring and UI design update
- [ ] Test cases
- [ ] Performance improvements
- [ ] Dedicated multi-platform installer (Windows & Linux, maybe macOS)
- [ ] PyPI release for easier installation

### Milestone 2: People & Search-By-Example
- [ ] Face detection and recognition
- [ ] Person-based search and grouping
- [ ] Privacy-preserving local face embeddings
- [ ] Retrieval by example image

### Milestone 3: Web Platform
- [ ] Browser-based interface for remote access
- [ ] Server-client architecture
- [ ] All current features available in the web version
- [ ] Multi-user support and sharing

## License

[Apache 2.0](LICENSE)