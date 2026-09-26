"""CPU-only ALIGN encoder compatible with the desktop app's pooler-output vectors."""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PIL import Image

MODEL_NAME = "kakaobrain/align-base"


class AlignEncoder:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self._load_lock = threading.Lock()
        self._processor = None
        self._tokenizer = None
        self._model = None

    def ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            import torch
            from transformers import AlignModel, AlignProcessor, AutoTokenizer

            self._processor = AlignProcessor.from_pretrained(
                MODEL_NAME, cache_dir=str(self.cache_dir), local_files_only=True
            )
            self._tokenizer = AutoTokenizer.from_pretrained(
                MODEL_NAME, cache_dir=str(self.cache_dir), local_files_only=True
            )
            self._model = AlignModel.from_pretrained(
                MODEL_NAME, cache_dir=str(self.cache_dir), local_files_only=True
            ).to("cpu")
            self._model.eval()

    def encode_image(self, image: Image.Image) -> np.ndarray:
        self.ensure_loaded()
        import torch

        if image.mode != "RGB":
            image = image.convert("RGB")
        inputs = self._processor(images=image, return_tensors="pt")
        with torch.inference_mode():
            vector = self._model.get_image_features(**inputs).pooler_output.squeeze().cpu().numpy()
        return np.asarray(vector, dtype=np.float32).reshape(-1)

    def encode_text(self, query: str) -> np.ndarray:
        self.ensure_loaded()
        import torch

        inputs = self._tokenizer(query, return_tensors="pt")
        with torch.inference_mode():
            vector = self._model.get_text_features(**inputs).pooler_output.squeeze().cpu().numpy()
        return np.asarray(vector, dtype=np.float32).reshape(-1)
