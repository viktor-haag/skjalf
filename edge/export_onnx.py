"""Export the ALIGN image and text encoders (kakaobrain/align-base) to ONNX.

Outputs ``align_image_encoder.onnx`` and ``align_text_encoder.onnx`` that produce
the same ``pooler_output`` vectors as the desktop app (see ``common.py``).
After export the models are run with ONNX Runtime on the CPU provider and, if
available, the WebGPU provider and compared against PyTorch.

    python export_onnx.py                      # export + verify
    python export_onnx.py --opset 18 --exporter legacy
"""

from __future__ import annotations

import argparse
import sys
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
import onnx
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
    cpu_fallback_ops,
    image_inputs,
    load_torch,
    make_session,
    text_inputs,
)

# Opsets the ORT WebGPU EP kernels are registered for. Newer opsets usually still
# load, but individual ops may only have kernels up to an older version and then
# silently run on CPU. 17-21 is the safe band for ORT 1.2x.
WEBGPU_SAFE_OPSETS = range(17, 22)


def _export(module, args, path: Path, input_names, output_names, dynamic_axes, opset, exporter):
    path.parent.mkdir(parents=True, exist_ok=True)
    common_kw = dict(
        input_names=input_names,
        output_names=output_names,
        opset_version=opset,
    )
    if exporter == "dynamo":
        try:
            prog = torch.onnx.export(
                module,
                args,
                dynamo=True,
                dynamic_axes=dynamic_axes,
                external_data=False,
                optimize=True,
                **common_kw,
            )
            prog.save(str(path), external_data=False)
            return "dynamo"
        except Exception as e:  # noqa: BLE001
            print(f"  ! dynamo exporter failed ({type(e).__name__}: {e}); falling back to legacy")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        torch.onnx.export(
            module,
            args,
            str(path),
            dynamo=False,
            dynamic_axes=dynamic_axes,
            do_constant_folding=True,
            **common_kw,
        )
    return "legacy"


def export_all(out_dir: Path, opset: int, exporter: str, local_only: bool):
    model, processor, tokenizer = load_torch("cpu", local_files_only=local_only)
    img = image_inputs(processor, 1)
    txt = text_inputs(tokenizer, 2)

    with torch.inference_mode():
        print(f"[export] image encoder -> {out_dir / IMAGE_ONNX}")
        used = _export(
            ImageEncoder(model, export_friendly=True).eval(),
            (torch.from_numpy(img["pixel_values"]),),
            out_dir / IMAGE_ONNX,
            ["pixel_values"],
            ["image_embeds"],
            {"pixel_values": {0: "batch"}, "image_embeds": {0: "batch"}},
            opset,
            exporter,
        )
        print(f"  done ({used} exporter)")

        print(f"[export] text encoder  -> {out_dir / TEXT_ONNX}")
        used = _export(
            TextEncoder(model).eval(),
            tuple(torch.from_numpy(txt[k]) for k in ("input_ids", "attention_mask", "token_type_ids")),
            out_dir / TEXT_ONNX,
            ["input_ids", "attention_mask", "token_type_ids"],
            ["text_embeds"],
            {
                "input_ids": {0: "batch", 1: "sequence"},
                "attention_mask": {0: "batch", 1: "sequence"},
                "token_type_ids": {0: "batch", 1: "sequence"},
                "text_embeds": {0: "batch"},
            },
            opset,
            exporter,
        )
        print(f"  done ({used} exporter)")
    return model, processor, tokenizer


def inspect_model(path: Path) -> None:
    m = onnx.load(str(path), load_external_data=False)
    onnx.checker.check_model(str(path))
    opsets = {imp.domain or "ai.onnx": imp.version for imp in m.opset_import}
    ops = Counter((n.domain or "ai.onnx", n.op_type) for n in m.graph.node)
    size_mb = path.stat().st_size / 2**20
    print(f"[inspect] {path.name}: {size_mb:.0f} MB, {len(m.graph.node)} nodes, opsets={opsets}")
    print("          ops: " + ", ".join(f"{op}x{c}" for (_, op), c in sorted(ops.items())))
    main = opsets.get("ai.onnx")
    if main is not None and main not in WEBGPU_SAFE_OPSETS:
        print(
            f"  ! hint: opset {main} is outside {WEBGPU_SAFE_OPSETS.start}-{WEBGPU_SAFE_OPSETS.stop - 1}; "
            "some WebGPU kernels may not be registered for it (ops then fall back to CPU)."
        )
    custom = sorted({d for d, _ in ops if d not in ("ai.onnx", "")})
    if custom:
        print(f"  ! hint: non-standard op domains {custom} — not supported by onnxruntime-web/WebGPU.")


def verify(path: Path, feeds_list, torch_fn, providers: list[str]) -> bool:
    all_ok = True
    for provider in (CPU_EP, WEBGPU_EP):
        if provider not in providers:
            print(f"[verify] {path.name} on {provider}: SKIPPED (provider not available)")
            continue
        try:
            sess = make_session(path, provider)
        except Exception as e:  # noqa: BLE001
            print(f"[verify] {path.name} on {provider}: FAILED to create session: {e}")
            all_ok = False
            continue
        for feeds in feeds_list:
            ref = torch_fn(feeds)
            out = sess.run(None, feeds)[0]
            acc = Accuracy.compare(ref, out)
            shape = "x".join(map(str, next(iter(feeds.values())).shape))
            status = "OK" if acc.ok() else "MISMATCH"
            all_ok &= acc.ok()
            print(f"[verify] {path.name} on {provider} [{shape}]: {status}  {acc}")

        if provider == WEBGPU_EP:
            webgpu_hints(path, feeds_list[0])
    return all_ok


def webgpu_hints(path: Path, feeds) -> None:
    try:
        make_session(path, WEBGPU_EP, disable_fallback=True)
        print(f"  WebGPU: every node is assigned to {WEBGPU_EP} (no CPU fallback).")
        return
    except Exception as e:  # noqa: BLE001
        print(f"  ! WebGPU: session with CPU fallback disabled fails: {str(e).splitlines()[0][:200]}")
    try:
        ops = cpu_fallback_ops(path, WEBGPU_EP, feeds)
    except Exception as e:  # noqa: BLE001
        print(f"  ! WebGPU: could not profile node placement: {e}")
        return
    if ops:
        print("  ! hint: ops running on CPU instead of WebGPU (unsupported kernel / dtype / opset): "
              + ", ".join(f"{op}x{n}" for op, n in ops.items()))
    else:
        print("  WebGPU: no compute nodes fell back to CPU (only shape/initializer nodes).")


def main() -> int:
    # torch.onnx prints emoji progress markers; the Windows console codepage chokes on them.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--opset", type=int, default=18)
    ap.add_argument("--exporter", choices=["dynamo", "legacy"], default="dynamo")
    ap.add_argument("--skip-export", action="store_true", help="only verify existing models")
    ap.add_argument("--local-files-only", action="store_true", help="do not hit the HF Hub")
    args = ap.parse_args()

    if args.skip_export:
        model, processor, tokenizer = load_torch("cpu", local_files_only=args.local_files_only)
    else:
        model, processor, tokenizer = export_all(args.out_dir, args.opset, args.exporter, args.local_files_only)

    img_path, txt_path = args.out_dir / IMAGE_ONNX, args.out_dir / TEXT_ONNX
    for p in (img_path, txt_path):
        inspect_model(p)

    providers = available_providers()
    print(f"[ort] available providers: {providers}")
    if WEBGPU_EP not in providers:
        print("  hint: install `onnxruntime-webgpu` (instead of `onnxruntime`) to test the WebGPU EP.")

    def torch_image(feeds):
        with torch.inference_mode():
            return ImageEncoder(model)(torch.from_numpy(feeds["pixel_values"])).numpy()

    def torch_text(feeds):
        with torch.inference_mode():
            return TextEncoder(model)(*(torch.from_numpy(feeds[k]) for k in
                                        ("input_ids", "attention_mask", "token_type_ids"))).numpy()

    ok = verify(img_path, [image_inputs(processor, 1), image_inputs(processor, 3, seed=1)], torch_image, providers)
    ok &= verify(txt_path, [text_inputs(tokenizer, 1), text_inputs(tokenizer, 4)], torch_text, providers)
    print("[result] all checks passed" if ok else "[result] SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
