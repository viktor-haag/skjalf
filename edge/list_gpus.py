"""List all GPUs (integrated and discrete) and how to select them in benchmark.py.

Three views, each best-effort and skipped if the needed tool is missing:

* system   – GPUs the OS knows about (Windows: CIM, Linux: /sys/class/drm + lspci,
             macOS: system_profiler)
* WebGPU   – adapters as seen through WebGPU (needs ``pip install wgpu``), with type
             (integrated / discrete / CPU) and backend. The ``--gpu N`` index of
             benchmark.py refers to this list.
* CUDA     – devices visible to PyTorch (also ROCm builds), selectable with ``--cuda-device N``

    python list_gpus.py
    python list_gpus.py --json
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from common import WEBGPU_BACKENDS

# How the ORT WebGPU EP (Dawn) is steered towards an adapter type.
POWER_FOR_TYPE = {"IntegratedGPU": "low-power", "DiscreteGPU": "high-performance"}
TYPE_LABEL = {"IntegratedGPU": "integrated", "DiscreteGPU": "discrete", "CPU": "cpu (software)", "Unknown": "unknown"}


def default_webgpu_backend() -> str:
    return {"Windows": "D3D12", "Darwin": "Metal"}.get(platform.system(), "Vulkan")


# ---------------------------------------------------------------------------
# System view
# ---------------------------------------------------------------------------


def _run(cmd: list[str]) -> str | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def system_gpus() -> list[dict]:
    system = platform.system()
    gpus: list[dict] = []
    if system == "Windows":
        out = _run([
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name,AdapterRAM,DriverVersion,PNPDeviceID | ConvertTo-Json",
        ])
        if out and out.strip():
            data = json.loads(out)
            for d in data if isinstance(data, list) else [data]:
                ram = d.get("AdapterRAM") or 0  # uint32 in CIM -> capped at 4 GB
                gpus.append({
                    "name": d.get("Name"),
                    "memory": f"{ram / 2**30:.1f} GB" + ("+" if ram >= 2**32 - 2**20 else "") if ram else "-",
                    "driver": d.get("DriverVersion") or "-",
                    "id": d.get("PNPDeviceID") or "-",
                })
    elif system == "Linux":
        for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
            if "-" in card.name:  # connectors like card0-HDMI-A-1
                continue
            dev = card / "device"
            read = lambda f: (dev / f).read_text().strip() if (dev / f).exists() else ""  # noqa: E731
            slot = dev.resolve().name
            name = ""
            if shutil.which("lspci"):
                out = _run(["lspci", "-s", slot, "-mm"]) or ""
                parts = [p.strip('"') for p in out.strip().split('" "')]
                name = " ".join(parts[1:3]) if len(parts) >= 3 else out.strip()
            driver = (dev / "driver").resolve().name if (dev / "driver").exists() else "-"
            vram = read("mem_info_vram_total")  # amdgpu only
            gpus.append({
                "name": name or f"{card.name} (vendor {read('vendor')}, device {read('device')})",
                "memory": f"{int(vram) / 2**30:.1f} GB" if vram else "-",
                "driver": driver,
                "id": f"{slot} {read('vendor')}:{read('device')}".strip(),
            })
    elif system == "Darwin":
        out = _run(["system_profiler", "SPDisplaysDataType", "-json"])
        if out:
            for d in json.loads(out).get("SPDisplaysDataType", []):
                gpus.append({
                    "name": d.get("sppci_model") or d.get("_name"),
                    "memory": d.get("spdisplays_vram") or d.get("spdisplays_vram_shared") or "shared",
                    "driver": d.get("spdisplays_metal") or d.get("spdisplays_mtlgpufamilysupport") or "-",
                    "id": d.get("spdisplays_device-id") or "-",
                })
    return gpus


# ---------------------------------------------------------------------------
# WebGPU view
# ---------------------------------------------------------------------------


def webgpu_adapters() -> list[dict] | None:
    """Adapters reported by wgpu-native, or None if ``wgpu`` is not installed."""
    try:
        import wgpu
    except ImportError:
        return None
    adapters = []
    for a in wgpu.gpu.enumerate_adapters_sync():
        info = a.info
        adapters.append({
            "index": len(adapters),
            "name": info.get("device") or info.get("vendor") or "?",
            "type": info.get("adapter_type", "Unknown"),
            "backend": info.get("backend_type", "?"),
            "vendor_id": f"{info.get('vendor_id', 0):#06x}",
            "device_id": f"{info.get('device_id', 0):#x}",
            "driver": (info.get("vendor") or "").strip() or "-",
        })
    for a in adapters:
        a["ort_flags"] = ort_flags_for(a, adapters)
    return adapters


def ort_flags_for(adapter: dict, adapters: list[dict]) -> dict | None:
    """Benchmark settings that make the ORT WebGPU EP pick *adapter*, or None if impossible."""
    power = POWER_FOR_TYPE.get(adapter["type"])
    if power is None or adapter["backend"] not in WEBGPU_BACKENDS:
        return None
    if expected_adapter(adapters, power, adapter["backend"]) is not adapter:
        return None  # e.g. a second discrete GPU on the same backend: Dawn always takes the first one
    return {"power": power, "backend": adapter["backend"]}


def expected_adapter(adapters: list[dict], power: str | None, backend: str | None) -> dict | None:
    """Mimic Dawn's choice: first adapter of *backend* ordered by power preference."""
    backend = backend or default_webgpu_backend()
    power = power or "high-performance"
    order = ["DiscreteGPU", "IntegratedGPU"] if power == "high-performance" else ["IntegratedGPU", "DiscreteGPU"]
    candidates = [a for a in adapters if a["backend"] == backend and a["type"] in order]
    candidates.sort(key=lambda a: order.index(a["type"]))  # stable: keeps enumeration order
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# CUDA view
# ---------------------------------------------------------------------------


def cuda_devices() -> list[dict] | None:
    try:
        import torch
    except ImportError:
        return None
    if not torch.cuda.is_available():
        return []
    kind = "ROCm" if getattr(torch.version, "hip", None) else "CUDA"
    out = []
    for i in range(torch.cuda.device_count()):
        p = torch.cuda.get_device_properties(i)
        out.append({
            "index": i,
            "name": p.name,
            "memory": f"{p.total_memory / 2**30:.1f} GB",
            "kind": kind,
            "integrated": bool(getattr(p, "is_integrated", False)),
        })
    return out


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="print machine-readable JSON instead of tables")
    args = ap.parse_args()

    result = {"system": system_gpus(), "webgpu": webgpu_adapters(), "cuda": cuda_devices()}
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"System GPUs ({platform.system()} {platform.machine()})")
    if result["system"]:
        table(["name", "memory", "driver", "id"],
              [[g["name"] or "?", g["memory"], g["driver"], g["id"]] for g in result["system"]])
    else:
        print("  (none found / not supported on this OS)")

    print("\nWebGPU adapters  -> benchmark.py --gpu N")
    adapters = result["webgpu"]
    if adapters is None:
        print("  `wgpu` not installed (pip install wgpu) — WebGPU adapters cannot be listed.")
    elif not adapters:
        print("  (no WebGPU adapters)")
    else:
        rows = []
        for a in adapters:
            f = a["ort_flags"]
            sel = f"--webgpu-power {f['power']} --webgpu-backend {f['backend']}" if f else "not selectable in ORT"
            rows.append([str(a["index"]), a["name"], TYPE_LABEL.get(a["type"], a["type"]), a["backend"],
                         f"{a['vendor_id']}:{a['device_id']}", sel])
        table(["#", "name", "type", "backend", "vendor:device", "equivalent benchmark flags"], rows)
        default = expected_adapter(adapters, None, None)
        print(f"\n  ORT WebGPU default (high-performance, {default_webgpu_backend()}): "
              + (f"#{default['index']} {default['name']}" if default else "no matching adapter"))
        print("  Note: ORT's WebGPU EP (Dawn) has no adapter index. It selects by backend + power\n"
              "  preference, so of several GPUs with the same type and backend only the first is reachable.")

    print("\nCUDA / ROCm devices (PyTorch)  -> benchmark.py --cuda-device N")
    cuda = result["cuda"]
    if cuda is None:
        print("  torch not installed")
    elif not cuda:
        print("  (none — torch reports no CUDA/ROCm device)")
    else:
        table(["#", "name", "memory", "kind", "integrated"],
              [[str(d["index"]), d["name"], d["memory"], d["kind"], "yes" if d["integrated"] else "no"] for d in cuda])
    return 0


if __name__ == "__main__":
    sys.exit(main())
