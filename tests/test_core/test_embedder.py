"""Tests for Embedder device switching and CUDA OOM handling."""

from unittest.mock import MagicMock, patch

import pytest
import torch


class TestSetDevice:
    def test_switch_to_cuda_succeeds(self):
        """Test successful switch to CUDA device."""
        from skjalf.watcher.embedder import Embedder

        mock_model = MagicMock()
        with patch.object(Embedder, "_model", mock_model):
            with patch.object(Embedder, "_device", "cpu"):
                Embedder._device = "cpu"
                Embedder.set_device("cuda")
                assert Embedder._device == "cuda"
                mock_model.to.assert_called_once_with("cuda")

    def test_switch_to_cpu_succeeds(self):
        """Test successful switch to CPU device."""
        from skjalf.watcher.embedder import Embedder

        mock_model = MagicMock()
        with patch.object(Embedder, "_model", mock_model):
            with patch.object(Embedder, "_device", "cuda"):
                Embedder._device = "cuda"
                Embedder.set_device("cpu")
                assert Embedder._device == "cpu"
                mock_model.to.assert_called_once_with("cpu")

    def test_same_device_no_change(self):
        """Test that switching to the same device does nothing."""
        from skjalf.watcher.embedder import Embedder

        mock_model = MagicMock()
        with patch.object(Embedder, "_model", mock_model):
            with patch.object(Embedder, "_device", "cuda"):
                Embedder._device = "cuda"
                Embedder.set_device("cuda")
                mock_model.to.assert_not_called()

    def test_cuda_oom_reverts_to_original_device(self):
        """Test that CUDA OOM error reverts to original device."""
        from skjalf.watcher.embedder import Embedder

        mock_model = MagicMock()
        mock_model.to.side_effect = torch.cuda.OutOfMemoryError()
        with patch.object(Embedder, "_model", mock_model):
            with patch.object(Embedder, "_device", "cpu"):
                Embedder._device = "cpu"
                Embedder.set_device("cuda")
                # Should revert to original device
                assert Embedder._device == "cpu"

    def test_cuda_oom_logs_warning(self):
        """Test that CUDA OOM is handled gracefully without raising."""
        from skjalf.watcher.embedder import Embedder

        mock_model = MagicMock()
        mock_model.to.side_effect = torch.cuda.OutOfMemoryError()
        with patch.object(Embedder, "_model", mock_model):
            with patch.object(Embedder, "_device", "cpu"):
                Embedder._device = "cpu"
                # Should not raise, just handle gracefully
                Embedder.set_device("cuda")
                # Model.to should have been called but raised OOM
                mock_model.to.assert_called_once_with("cuda")
