# Skjalf

Ever tried to find "the photo of my cat sleeping on the couch" but couldn't remember the filename or folder?

Skjalf lets you search your local photo collection using natural language instead of filenames or tags. It uses AI to understand the content of your images and your search queries, helping you find exactly what you're looking for - while keeping everything on your machine.

Why is it called **Skjalf**? The name is inspired by Hlidskjalf, Odin's high seat in Norse mythology, which allowed him to see and observe the world from above. Similarly, Skjalf helps you gain a new perspective on your own image collection - making it easier to discover what you are looking for.

This project is still in an early stage, so bugs are to be expected. If you run into any issues, please open a ticket. It would be greatly appreciated!

Watch Skjalf in action below!

https://github.com/user-attachments/assets/db17e439-2173-4ff1-84cd-6da0fde0446e

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

### 1. Install Skjalf

**From PyPI (recommended):**

```bash
pip install skjalf
```

**From Source:**

```bash
git clone https://github.com/viktor-haag/skjalf.git
cd skjalf
conda create -n skjalf python=3.12 # feel free to use your favorite python environment manager
conda activate skjalf
pip install -e .
```

### 2. Run the App

Once installed, you can launch Skjalf from your terminal. If you use skjalf for the first time, it will download the `kakaobrain/align-base` from Huggning Face at startup.

```bash
skjalf
```

### 3. Use the App

* Add root folders by dragging and dropping them into the left sidebar or via the context menu. The application will automatically index the selected folders and prepare everything needed for semantic search.
* Select a root folder to explore its contents. Images can be opened in your default image viewer with a double-click.
* Use the right mouse button to access file operations such as moving, copying, or deleting items. Multiple files can be selected using Ctrl-click, Shift-click, or box selection.
* To search, simply enter a query in the search bar. Searches are always limited to the currently selected root folder.

## Roadmap

### Milestone 0: Initial Prototype <-- we are here
- [x] Semantic image search using ALIGN model
- [x] Folder registration and recursive scanning
- [x] Local ChromaDB vector storage per folder
- [x] GPU/CPU toggle for embedding
- [x] Multi-file selection and batch operations
- [x] Progress tracking for embeddings and file operations

### Milestone 1: Consolidation & Distribution
- [X] More control over the ingestion process of registered folders
- [X] Automatic model download at first launch
- [ ] Drag & drop support (folders & files)
- [ ] Light/Dark mode toggle
- [ ] Codebase refactoring and UI design update
- [ ] Test cases
- [ ] Performance improvements
- [ ] Dedicated multi-platform installer (Windows & Linux, maybe macOS)
- [x] PyPI release for easier installation

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
