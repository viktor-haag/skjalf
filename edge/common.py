"""Shared helpers for the ONNX export and benchmark scripts.

Embeddings are produced exactly like ``skjalf/watcher/embedder.py``:

* image: ``AlignModel.get_image_features(pixel_values).pooler_output``
  (EfficientNet pooled features, 640-d, *not* L2-normalised)
* text:  ``AlignModel.get_text_features(...).pooler_output``
  (``text_projection`` of the BERT [CLS] token, 640-d, *not* L2-normalised)

The desktop app stores the raw vectors in ChromaDB with the cosine metric, so
normalisation is left to the consumer. All accuracy checks therefore report
cosine similarity in addition to the max absolute difference.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AlignModel, AlignProcessor, AutoTokenizer

MODEL_NAME = "kakaobrain/align-base"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "models"
IMAGE_ONNX = "align_image_encoder.onnx"
TEXT_ONNX = "align_text_encoder.onnx"

CPU_EP = "CPUExecutionProvider"
WEBGPU_EP = "WebGpuExecutionProvider"

SAMPLE_TEXTS = [
    "a photo of a cat",
    "a dog playing in the snow",
    "sunset over the mountains",
    "a birthday party with balloons and a cake",
]


# ---------------------------------------------------------------------------
# Torch side
# ---------------------------------------------------------------------------


class ImageEncoder(torch.nn.Module):
    """pixel_values -> pooler_output, as in ``Embedder.embed_file``.

    ``export_friendly=True`` replaces ALIGN's pooler ``nn.AvgPool2d(2560, ceil_mode=True)``
    with a plain spatial mean. Both are identical in PyTorch (the single, clipped window
    is averaged over the valid elements only), but ONNX ``AveragePool`` with ``ceil_mode``
    divides by a different element count, which scales the whole vector by a constant
    (~2e-4 at 289x289): cosine stays 1.0 while the magnitudes are wrong.
    """

    def __init__(self, model: AlignModel, export_friendly: bool = False) -> None:
        super().__init__()
        self.model = model
        self.export_friendly = export_friendly

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        if not self.export_friendly:
            return self.model.get_image_features(pixel_values=pixel_values).pooler_output
        vision = self.model.vision_model
        hidden = vision.encoder(vision.embeddings(pixel_values))[0]
        if isinstance(vision.pooler, torch.nn.MaxPool2d):
            return hidden.amax(dim=(2, 3))
        return hidden.mean(dim=(2, 3))


class TextEncoder(torch.nn.Module):
    """input_ids/attention_mask/token_type_ids -> pooler_output, as in ``Embedder.query``."""

    def __init__(self, model: AlignModel) -> None:
        super().__init__()
        self.model = model

    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        token_type_ids: torch.Tensor,
    ) -> torch.Tensor:
        return self.model.get_text_features(
            input_ids=input_ids,
            attention_mask=attention_mask,
            token_type_ids=token_type_ids,
        ).pooler_output


def load_torch(device: str = "cpu", local_files_only: bool = False):
    """Return (model, processor, tokenizer) in eval mode on *device*."""
    kw = {"local_files_only": local_files_only}
    processor = AlignProcessor.from_pretrained(MODEL_NAME, **kw)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, **kw)
    model = AlignModel.from_pretrained(MODEL_NAME, **kw).to(device).eval()
    return model, processor, tokenizer


def sample_images(n: int, seed: int = 0) -> list[Image.Image]:
    """Deterministic synthetic RGB images of varying size (no dataset needed)."""
    rng = np.random.default_rng(seed)
    images = []
    for i in range(n):
        h, w = int(rng.integers(200, 640)), int(rng.integers(200, 640))
        # smooth gradient + noise so the encoder sees some structure
        yy, xx = np.mgrid[0:h, 0:w]
        base = np.stack(
            [(xx * (i + 1)) % 256, (yy * (i + 2)) % 256, ((xx + yy) * 3) % 256], axis=-1
        )
        noise = rng.integers(0, 64, size=(h, w, 3))
        images.append(Image.fromarray(((base + noise) % 256).astype(np.uint8), "RGB"))
    return images


def image_inputs(processor, batch_size: int, seed: int = 0) -> dict[str, np.ndarray]:
    pixels = processor(images=sample_images(batch_size, seed), return_tensors="np")
    return {"pixel_values": pixels["pixel_values"].astype(np.float32)}


def text_inputs(tokenizer, batch_size: int) -> dict[str, np.ndarray]:
    texts = [SAMPLE_TEXTS[i % len(SAMPLE_TEXTS)] for i in range(batch_size)]
    tok = tokenizer(texts, padding=True, return_tensors="np")
    return {
        "input_ids": tok["input_ids"].astype(np.int64),
        "attention_mask": tok["attention_mask"].astype(np.int64),
        "token_type_ids": tok["token_type_ids"].astype(np.int64),
    }


# ---------------------------------------------------------------------------
# ONNX Runtime side
# ---------------------------------------------------------------------------


def available_providers() -> list[str]:
    try:
        import onnxruntime as ort
    except ImportError:
        return []
    return ort.get_available_providers()


WEBGPU_POWER_PREFERENCES = ("high-performance", "low-power")
WEBGPU_BACKENDS = ("D3D12", "D3D11", "Vulkan", "Metal", "OpenGL", "OpenGLES")


def webgpu_config(power: str | None = None, backend: str | None = None) -> dict[str, str]:
    """Session config entries that steer which GPU adapter the ORT WebGPU EP picks.

    The WebGPU EP has no adapter index: Dawn picks the first adapter of the requested
    backend that matches the power preference (``high-performance`` -> discrete GPU first,
    ``low-power`` -> integrated GPU first). Defaults are high-performance and D3D12 on
    Windows, Vulkan on Linux, and Metal on macOS.

    Note: these must be *session config entries*; ORT's Python provider-options dict
    ignores them silently. The WebGPU context is created once per process, so only the
    first WebGPU session's settings take effect.
    """
    cfg = {}
    if power:
        cfg["ep.webgpuexecutionprovider.powerPreference"] = power
    if backend:
        cfg["ep.webgpuexecutionprovider.dawnBackendType"] = backend
    return cfg


def make_session(
    model_path: Path,
    provider: str,
    disable_fallback: bool = False,
    profile: bool = False,
    config: dict[str, str] | None = None,
):
    """Create an InferenceSession pinned to *provider* (+ CPU fallback unless disabled)."""
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.log_severity_level = 3
    for key, value in (config or {}).items():
        so.add_session_config_entry(key, value)
    if disable_fallback and provider != CPU_EP:
        so.add_session_config_entry("session.disable_cpu_ep_fallback", "1")
        # This is a probe that is expected to fail when any node needs CPU; the caller
        # reports the result, so keep ORT from logging it as an [E:onnxruntime] error.
        so.log_severity_level = 4
    if profile:
        so.enable_profiling = True
        so.profile_file_prefix = os.path.join(tempfile.gettempdir(), "skjalf_edge_profile")
    providers = [provider] if provider == CPU_EP or disable_fallback else [provider, CPU_EP]
    cls = ort.InferenceSession if provider == CPU_EP else _strict_session_class(ort)
    return cls(str(model_path), sess_options=so, providers=providers)


def _strict_session_class(ort):
    """InferenceSession that raises if the EP fails to initialise.

    By default ORT's Python wrapper catches EP init errors (e.g. no usable WebGPU adapter
    for the requested backend), prints them and silently retries on CPU only, so the
    benchmark would time CPU while calling it WebGPU.
    """

    class StrictInferenceSession(ort.InferenceSession):
        def _create_inference_session(self, *args, **kwargs):
            self._enable_fallback = False
            return super()._create_inference_session(*args, **kwargs)

    return StrictInferenceSession


def cpu_fallback_ops(model_path: Path, provider: str, feeds: dict[str, np.ndarray]) -> dict[str, int]:
    """Run once with profiling and return {op_type: count} of nodes that fell back to CPU."""
    sess = make_session(model_path, provider, profile=True)
    sess.run(None, feeds)
    prof = sess.end_profiling()
    try:
        events = json.loads(Path(prof).read_text(encoding="utf-8"))
    finally:
        Path(prof).unlink(missing_ok=True)
    fallback: dict[str, set[str]] = {}
    for ev in events:
        args = ev.get("args", {})
        if ev.get("cat") == "Node" and args.get("provider") == CPU_EP:
            fallback.setdefault(args.get("op_name", "?"), set()).add(ev.get("name", ""))
    return {op: len(names) for op, names in sorted(fallback.items())}


# ---------------------------------------------------------------------------
# Accuracy
# ---------------------------------------------------------------------------


@dataclass
class Accuracy:
    min_cos: float
    mean_cos: float
    max_abs: float
    max_rel: float  # max|diff| / max|ref|

    @classmethod
    def compare(cls, ref: np.ndarray, out: np.ndarray) -> "Accuracy":
        ref = ref.astype(np.float64)
        out = out.astype(np.float64)
        cos = (ref * out).sum(-1) / (np.linalg.norm(ref, axis=-1) * np.linalg.norm(out, axis=-1))
        max_abs = float(np.abs(ref - out).max())
        return cls(float(cos.min()), float(cos.mean()), max_abs, max_abs / float(np.abs(ref).max()))

    def ok(self, min_cos: float = 0.9999, max_rel: float = 1e-3) -> bool:
        # cosine alone is blind to a constant scale error, so also bound the relative diff
        return self.min_cos >= min_cos and self.max_rel <= max_rel

    def __str__(self) -> str:
        return f"cos(min/mean)={self.min_cos:.6f}/{self.mean_cos:.6f}  max|diff|={self.max_abs:.2e} (rel {self.max_rel:.1e})"
