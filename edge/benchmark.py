"""Benchmark ALIGN image/text encoding: ONNX Runtime (CPU, WebGPU) vs plain PyTorch.

Measures model inference only (inputs are preprocessed/tokenised once up front),
with warm-up, N timed runs, mean / median / p95 latency and throughput, and
checks every backend's output against the PyTorch CPU reference
(``get_*_features().pooler_output``, same as the desktop app).

    python benchmark.py --batch-size 1 8 --runs 20
    python benchmark.py --backends ort-cpu ort-webgpu --encoders image
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import torch

from common import (
    CPU_EP,
    DEFAULT_OUT_DIR,
    IMAGE_ONNX,
    TEXT_ONNX,
    WEBGPU_EP,
    Accuracy,
    ImageEncoder,
    TextEncoder,
    available_providers,
    image_inputs,
    load_torch,
    make_session,
    text_inputs,
)

BACKENDS = ["torch-cpu", "torch-cuda", "ort-cpu", "ort-webgpu"]
TEXT_KEYS = ("input_ids", "attention_mask", "token_type_ids")


@dataclass
class Result:
    backend: str
    encoder: str
    batch: int
    status: str = "ok"
    mean_ms: float = float("nan")
    median_ms: float = float("nan")
    p95_ms: float = float("nan")
    items_per_s: float = float("nan")
    accuracy: dict = field(default_factory=dict)
    accuracy_ok: bool | None = None


class Skip(Exception):
    """Backend not usable on this machine — reported, not fatal."""


def time_fn(fn: Callable[[], object], warmup: int, runs: int, sync: Callable[[], None] = lambda: None):
    for _ in range(warmup):
        fn()
    sync()
    times = []
    out = None
    for _ in range(runs):
        t0 = time.perf_counter()
        out = fn()
        sync()
        times.append((time.perf_counter() - t0) * 1000.0)
    return times, out


def make_runner(backend: str, encoder: str, feeds: dict[str, np.ndarray], model, models_dir: Path):
    """Return (callable producing a numpy embedding batch, sync fn)."""
    if backend.startswith("torch"):
        device = "cuda" if backend == "torch-cuda" else "cpu"
        if device == "cuda" and not torch.cuda.is_available():
            raise Skip("CUDA not available")
        mod = (ImageEncoder(model) if encoder == "image" else TextEncoder(model)).to(device).eval()
        keys = ("pixel_values",) if encoder == "image" else TEXT_KEYS
        tensors = [torch.from_numpy(feeds[k]).to(device) for k in keys]
        sync = torch.cuda.synchronize if device == "cuda" else (lambda: None)

        def run():
            with torch.inference_mode():
                return mod(*tensors)

        return run, sync, lambda out: out.float().cpu().numpy()

    provider = CPU_EP if backend == "ort-cpu" else WEBGPU_EP
    providers = available_providers()
    if not providers:
        raise Skip("onnxruntime not installed")
    if provider not in providers:
        raise Skip(f"{provider} not available (installed: {', '.join(providers)})")
    path = models_dir / (IMAGE_ONNX if encoder == "image" else TEXT_ONNX)
    if not path.exists():
        raise Skip(f"{path.name} missing — run export_onnx.py first")
    try:
        sess = make_session(path, provider)
    except Exception as e:  # noqa: BLE001
        raise Skip(f"session creation failed: {str(e).splitlines()[0][:120]}") from e
    if provider not in sess.get_providers():
        raise Skip(f"{provider} was not activated by ORT")
    return (lambda: sess.run(None, feeds)[0]), (lambda: None), (lambda out: out)


def fmt(v: float, nd: int = 1) -> str:
    return "-" if v != v else f"{v:.{nd}f}"  # NaN -> "-"


def print_table(results: list[Result]) -> None:
    headers = ["encoder", "batch", "backend", "mean ms", "median ms", "p95 ms", "items/s", "min cos", "max rel", "status"]
    rows = []
    for r in results:
        acc = r.accuracy
        status = r.status if r.status != "ok" else ("ok" if r.accuracy_ok in (None, True) else "ok (ACCURACY MISMATCH)")
        rows.append([
            r.encoder, str(r.batch), r.backend,
            fmt(r.mean_ms), fmt(r.median_ms), fmt(r.p95_ms), fmt(r.items_per_s, 2),
            f"{acc['min_cos']:.6f}" if acc else "-",
            f"{acc['max_rel']:.1e}" if acc else "-",
            status,
        ])
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(headers)]
    right = {1, 3, 4, 5, 6, 7, 8}

    def line(cells):
        return "  ".join(c.rjust(w) if i in right else c.ljust(w) for i, (c, w) in enumerate(zip(cells, widths)))

    print()
    print(line(headers))
    print("  ".join("-" * w for w in widths))
    prev = None
    for r, row in zip(results, rows):
        if prev is not None and (r.encoder, r.batch) != prev:
            print()
        prev = (r.encoder, r.batch)
        print(line(row))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch-size", type=int, nargs="+", default=[1, 8])
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--encoders", nargs="+", choices=["image", "text"], default=["image", "text"])
    ap.add_argument("--backends", nargs="+", choices=BACKENDS, default=BACKENDS)
    ap.add_argument("--models-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--threads", type=int, default=0, help="torch intra-op threads (0 = default)")
    ap.add_argument("--local-files-only", action="store_true")
    ap.add_argument("--json", type=Path, help="also write raw results to this file")
    args = ap.parse_args()

    if args.threads:
        torch.set_num_threads(args.threads)
    model, processor, tokenizer = load_torch("cpu", local_files_only=args.local_files_only)
    print(f"torch {torch.__version__} (threads={torch.get_num_threads()}, cuda={torch.cuda.is_available()})")
    try:
        import onnxruntime as ort

        print(f"onnxruntime {ort.__version__}, providers={ort.get_available_providers()}")
    except ImportError:
        print("onnxruntime not installed — ORT backends will be skipped")

    results: list[Result] = []
    for encoder in args.encoders:
        for bs in args.batch_size:
            feeds = image_inputs(processor, bs) if encoder == "image" else text_inputs(tokenizer, bs)
            ref_mod = ImageEncoder(model) if encoder == "image" else TextEncoder(model)
            keys = ("pixel_values",) if encoder == "image" else TEXT_KEYS
            with torch.inference_mode():
                reference = ref_mod(*(torch.from_numpy(feeds[k]) for k in keys)).numpy()

            for backend in args.backends:
                res = Result(backend, encoder, bs)
                print(f"[run] {encoder:5s} batch={bs:<3d} {backend:10s} ... ", end="", flush=True)
                try:
                    run, sync, to_np = make_runner(backend, encoder, feeds, model, args.models_dir)
                    times, out = time_fn(run, args.warmup, args.runs, sync)
                    res.mean_ms = statistics.fmean(times)
                    res.median_ms = statistics.median(times)
                    res.p95_ms = float(np.percentile(times, 95))
                    res.items_per_s = bs / (res.mean_ms / 1000.0)
                    acc = Accuracy.compare(reference, to_np(out))
                    res.accuracy = asdict(acc)
                    res.accuracy_ok = acc.ok()
                    print(f"{res.median_ms:.1f} ms median, {acc}")
                except Skip as e:
                    res.status = f"skipped: {e}"
                    print(res.status)
                except Exception as e:  # noqa: BLE001 — keep benchmarking the other backends
                    res.status = f"error: {type(e).__name__}: {str(e).splitlines()[0][:100]}"
                    print(res.status)
                finally:
                    if backend == "torch-cuda" and torch.cuda.is_available():
                        model.to("cpu")
                        torch.cuda.empty_cache()
                results.append(res)

    print_table(results)
    if args.json:
        args.json.write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
        print(f"\nraw results written to {args.json}")
    bad = [r for r in results if r.accuracy_ok is False or r.status.startswith("error")]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
