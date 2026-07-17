"""Unit tests for the face search backend module."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

from skjalf.watcher.face_search import FaceSearcher, PersonDB
from skjalf.watcher.events import FileEntry


class TestFaceSearcherFuzzyMatch(unittest.TestCase):
    """Test the fuzzy matching against names.yaml."""

    def setUp(self):
        """Create a temporary names.yaml with test data."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.names_path = Path(self.temp_dir.name) / "names.yaml"
        with open(self.names_path, "w") as f:
            yaml.dump({
                "Onkel Werner": "/tmp/test/001.jpg",
                "Jacqueline": "/tmp/test/002.jpg",
                "Fred": "/tmp/test/003.jpg",
            }, f)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_exact_match(self):
        """Exact name match should return the name."""
        searcher = FaceSearcher(
            names_path=self.names_path,
            persons_db_path="/tmp/test_persons.db",
        )
        result = searcher._fuzzy_match("Jacqueline")
        self.assertEqual(result, "Jacqueline")

    def test_case_insensitive_match(self):
        """Match should be case-insensitive."""
        searcher = FaceSearcher(
            names_path=self.names_path,
            persons_db_path="/tmp/test_persons.db",
        )
        result = searcher._fuzzy_match("jacqueline")
        self.assertEqual(result, "Jacqueline")

    def test_fuzzy_match_partial(self):
        """Partial name should fuzzy-match to closest name."""
        searcher = FaceSearcher(
            names_path=self.names_path,
            persons_db_path="/tmp/test_persons.db",
        )
        result = searcher._fuzzy_match("jacq")
        self.assertEqual(result, "Jacqueline")

    def test_no_match_returns_none(self):
        """Query with no close match should return None."""
        searcher = FaceSearcher(
            names_path=self.names_path,
            persons_db_path="/tmp/test_persons.db",
        )
        result = searcher._fuzzy_match("xyz_nonexistent")
        self.assertIsNone(result)

    def test_empty_query_returns_none(self):
        """Empty query should return None."""
        searcher = FaceSearcher(
            names_path=self.names_path,
            persons_db_path="/tmp/test_persons.db",
        )
        result = searcher._fuzzy_match("")
        self.assertIsNone(result)

    def test_whitespace_query_returns_none(self):
        """Whitespace-only query should return None."""
        searcher = FaceSearcher(
            names_path=self.names_path,
            persons_db_path="/tmp/test_persons.db",
        )
        result = searcher._fuzzy_match("   ")
        self.assertIsNone(result)


class TestFaceSearcherSearch(unittest.TestCase):
    """Test the full search pipeline."""

    def setUp(self):
        """Create temporary test fixtures with actual image files."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_img_dir = Path(self.temp_dir.name) / "test_images"
        self.test_img_dir.mkdir()

        # Create actual image files that names.yaml will reference
        self.img_001 = self.test_img_dir / "001.jpg"
        self.img_002 = self.test_img_dir / "002.jpg"
        self.img_003 = self.test_img_dir / "003.jpg"
        for img in [self.img_001, self.img_002, self.img_003]:
            img.write_bytes(b"fake image data")

        self.names_path = Path(self.temp_dir.name) / "names.yaml"
        with open(self.names_path, "w") as f:
            yaml.dump({
                "Onkel Werner": str(self.img_001),
                "Jacqueline": str(self.img_002),
                "Fred": str(self.img_003),
            }, f)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_no_name_match_returns_empty_list(self):
        """If no name matches, search should return an empty list."""
        searcher = FaceSearcher(
            names_path=self.names_path,
            persons_db_path="/tmp/test_persons.db",
        )
        results = searcher.search("xyz_nonexistent")
        self.assertEqual(results, [])

    @patch("skjalf.watcher.face_search.FaceSearcher._embed_image")
    @patch("skjalf.watcher.face_search.FaceSearcher._get_db")
    def test_match_with_no_chromadb_results(
        self, mock_get_db, mock_embed
    ):
        """If name matches but ChromaDB has no results, return empty list."""
        mock_embed.return_value = MagicMock()
        mock_db = MagicMock()
        mock_db.query.return_value = []
        mock_get_db.return_value = mock_db

        searcher = FaceSearcher(
            names_path=self.names_path,
            persons_db_path="/tmp/test_persons.db",
        )
        results = searcher.search("jacqueline")
        self.assertEqual(results, [])
        mock_db.query.assert_called_once()

    @patch("skjalf.watcher.face_search.FaceSearcher._embed_image")
    @patch("skjalf.watcher.face_search.FaceSearcher._get_db")
    def test_match_with_chromadb_results(
        self, mock_get_db, mock_embed
    ):
        """If name matches and ChromaDB returns results, return FileEntry list."""
        mock_embed.return_value = MagicMock()

        # Create a temp file to simulate an existing image
        test_img = Path(self.temp_dir.name) / "result.jpg"
        test_img.write_bytes(b"fake image data")

        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "id": str(test_img),
                "abs_path": str(test_img),
                "distance": 0.1,
            }
        ]
        mock_get_db.return_value = mock_db

        searcher = FaceSearcher(
            names_path=self.names_path,
            persons_db_path="/tmp/test_persons.db",
        )
        results = searcher.search("jacqueline")

        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], FileEntry)
        self.assertEqual(results[0].name, "result.jpg")
        self.assertFalse(results[0].is_dir)


class TestFaceSearcherNamesFile(unittest.TestCase):
    """Test names.yaml loading behavior."""

    def test_missing_names_file(self):
        """If names.yaml doesn't exist, _names should be empty dict."""
        searcher = FaceSearcher(
            names_path=Path("/nonexistent/path/names.yaml"),
            persons_db_path="/tmp/test_persons.db",
        )
        self.assertEqual(searcher._names, {})

    def test_empty_names_file(self):
        """If names.yaml is empty, _names should be empty dict."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            temp_path = Path(f.name)

        try:
            searcher = FaceSearcher(
                names_path=temp_path,
                persons_db_path="/tmp/test_persons.db",
            )
            self.assertEqual(searcher._names, {})
        finally:
            temp_path.unlink()


class TestPersonDB(unittest.TestCase):
    """Test the PersonDB ChromaDB wrapper."""

    def setUp(self):
        """Create a temporary ChromaDB for testing."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_persons.db")
        self.db = PersonDB(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_upsert_and_query(self):
        """Test that upsert and query work correctly."""
        import numpy as np
        embedding = np.random.rand(512).astype(np.float32)
        embedding = embedding / np.linalg.norm(embedding)  # L2 normalize

        test_path = "/tmp/test_image.jpg"
        self.db.upsert(test_path, embedding)

        # Query should find the embedded image
        results = self.db.query(embedding.tolist(), n_results=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["abs_path"], test_path)

    def test_exists(self):
        """Test that exists correctly identifies embedded paths."""
        test_path = "/tmp/test_image.jpg"
        self.assertFalse(self.db.exists(test_path))

        import numpy as np
        embedding = np.random.rand(512).astype(np.float32)
        embedding = embedding / np.linalg.norm(embedding)
        self.db.upsert(test_path, embedding)

        self.assertTrue(self.db.exists(test_path))


if __name__ == "__main__":
    unittest.main()
