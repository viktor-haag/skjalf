# Skjalf edge: ALIGN as ONNX (CPU / WebGPU)

Experiments for running the ALIGN model (`kakaobrain/align-base`) via ONNX Runtime
on edge devices or in the browser (WebGPU), compared against plain PyTorch.

| File | Purpose |
|------|---------|
| `export_onnx.py` | Export image and text encoder to ONNX, inspect ops/opset, verify against PyTorch on the CPU and WebGPU EPs, report WebGPU CPU-fallback ops |
| `benchmark.py` | Latency/throughput benchmark: PyTorch CPU, PyTorch CUDA, ORT CPU, ORT WebGPU, plus an accuracy check of each backend against PyTorch |
| `list_gpus.py` | List all GPUs (integrated and discrete): OS view, WebGPU adapters with type/backend, CUDA/ROCm devices, plus the benchmark flags that select each one |
| `common.py` | Shared model wrappers, sample inputs, ORT session helpers, accuracy metrics |

## Embeddings

The exported models produce the same vectors as the desktop app
(`skjalf/watcher/embedder.py`) and the Nextcloud app:

* **image** – `get_image_features(pixel_values).pooler_output` (640-d)
  - input `pixel_values` `float32[batch, 3, 289, 289]` from `AlignProcessor`
  - output `image_embeds` `float32[batch, 640]`
* **text** – `get_text_features(...).pooler_output`, i.e. `text_projection` of the [CLS] token (640-d)
  - inputs `input_ids`, `attention_mask`, `token_type_ids` `int64[batch, sequence]` from the tokenizer
  - output `text_embeds` `float32[batch, 640]`

The vectors are **not** L2-normalised, same as in the app (ChromaDB uses the cosine
metric). Normalise them yourself if you compute dot products.

Preprocessing (resize/crop/normalise, tokenisation) is not part of the ONNX graphs.
In the browser it has to be reimplemented, e.g. with transformers.js.

**Export detail:** ALIGN pools with `nn.AvgPool2d(2560, ceil_mode=True)`. ONNX
`AveragePool` with `ceil_mode` divides by a different element count, so the exported
image vector comes out scaled by a constant (~2e-4). Cosine similarity is still 1.0, so
the bug is easy to miss. The export wrapper therefore uses an equivalent spatial `mean`.
For the same reason the accuracy checks also bound the max *relative* difference, not
only the cosine.

## Installation

Use the existing `skjalf` conda environment and add the export tools:

```bash
conda activate skjalf
pip install onnx onnxscript
pip install wgpu        # optional: lets list_gpus.py / benchmark.py --gpu enumerate WebGPU adapters
```

The plain `onnxruntime` that chromadb pulls in only has the CPU EP. You can test
WebGPU (Windows/Linux/macOS, needs a WebGPU-capable GPU driver) in one of two ways:

* in a separate environment: `pip install -r requirements.txt`
* without touching the `skjalf` env, by installing it to a side directory and
  putting that directory first on `PYTHONPATH`:

  ```bash
  ORT_WEBGPU_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/skjalf-ort-webgpu"
  pip install --no-deps --target "$ORT_WEBGPU_DIR" onnxruntime-webgpu
  export PYTHONPATH="$ORT_WEBGPU_DIR${PYTHONPATH:+:$PYTHONPATH}"
  ```

## Usage

```bash
cd edge
python export_onnx.py                    # export to edge/models/ and verify
python export_onnx.py --skip-export      # only verify existing models
python export_onnx.py --opset 18 --exporter legacy

python benchmark.py                      # batch sizes 1 and 8, 20 runs, 3 warm-up
python benchmark.py --batch-size 1 4 16 --runs 50 --warmup 5
python benchmark.py --backends ort-cpu ort-webgpu --encoders image --json results.json

python list_gpus.py                      # all GPUs + how to select them
python benchmark.py --gpu 1              # WebGPU adapter #1 from list_gpus.py
python benchmark.py --webgpu-power low-power --webgpu-backend Vulkan
python benchmark.py --backends torch-cuda --cuda-device 1
```

### Selecting a GPU

`list_gpus.py` prints three lists, and the benchmark selects from them:

| list | benchmark flag | used by |
|------|----------------|---------|
| WebGPU adapters (via `wgpu`) | `--gpu N`, or `--webgpu-power` + `--webgpu-backend` | `ort-webgpu` |
| CUDA/ROCm devices (via torch) | `--cuda-device N` | `torch-cuda` |
| system GPUs (OS) | – (informational) | – |

The ORT WebGPU EP (Dawn) has **no adapter index**. It takes the first adapter of the
chosen backend (default: D3D12 on Windows, Vulkan on Linux, Metal on macOS), ordered by
power preference:

* `high-performance` (default): discrete GPU first
* `low-power`: integrated GPU first

`--gpu N` translates an adapter from the list into these two settings. Two GPUs of the
same type on the same backend can therefore not both be targeted, and software/CPU
adapters cannot be selected at all. `list_gpus.py` marks both cases as "not selectable".

The adapter list comes from wgpu-native, not from the Dawn build inside ONNX Runtime.
The "expected adapter" that benchmark.py prints is a best guess. If ORT's Dawn cannot
use a backend, the run is reported as `skipped: … No supported adapters`. This happens,
for example, with Vulkan on Windows ARM64 (Adreno). ORT's default silent fallback to CPU
is disabled, so a GPU row is never secretly a CPU measurement.

The options are passed as session config entries
(`ep.webgpuexecutionprovider.powerPreference` / `.dawnBackendType`). The provider-options
dict of the Python API ignores them. ORT creates the WebGPU context once per process,
so run one benchmark per adapter.

The models are written to `edge/models/`. `*.onnx` and `models/` are git-ignored.
Image ≈ 240 MB, text ≈ 420 MB, both fp32 with weights embedded.

The benchmark times **inference only**, since inputs are preprocessed once up front.
Backends that are unavailable (no CUDA, no WebGPU EP, models not exported) are
reported as `skipped` and do not abort the run. The exit code is non-zero only if a
backend errors or fails the accuracy check (min cosine < 0.9999 or max relative
diff > 1e-3).

## WebGPU notes

* Opset 18 is exported by default. Opsets 17–21 are well covered by the ORT WebGPU EP.
  `export_onnx.py` warns about opsets outside that band and about non-standard op
  domains, which onnxruntime-web cannot run.
* `export_onnx.py` tries to create a WebGPU session with CPU fallback disabled. If
  that fails, it profiles one run and lists the ops that ORT placed on the CPU.
  * The **image encoder** runs completely on WebGPU.
  * The **text encoder** places a few small int64 shape/index ops on the CPU
    (`Shape`, `Range`, `Expand`, `GatherND`, `Unsqueeze`, …). These are the
    attention-mask and [CLS] index computations. ORT intentionally keeps them on the
    CPU, and their cost is negligible.
* For the browser, the same `.onnx` files load in `onnxruntime-web` with
  `executionProviders: ["webgpu"]`. At 420 MB, the text model may need fp16 or int8
  quantisation for practical download sizes (not done here).

## Example results

Snapdragon X Elite X1E80100 (12 cores, Adreno X1-85, Windows 11 ARM64), torch 2.13 CPU,
onnxruntime-webgpu 1.27, 20 runs, median ms:

| encoder | batch | torch-cpu | ort-cpu | ort-webgpu |
|---------|------:|----------:|--------:|-----------:|
| image   | 1     | 244       | 223     | **175**    |
| image   | 8     | 2132      | 2100    | **872**    |
| text    | 1     | 51        | 25      | **22**     |
| text    | 8     | 125       | 92      | **62**     |

All backends match PyTorch: cosine 1.000000 and max relative diff ≤ 1.1e-6. ORT CPU
showed high latency variance for image batch 8 (p95 ≈ 6.7 s).
