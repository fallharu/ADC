"""Resource-aware helpers for tuning YOLO inference."""
from __future__ import annotations

import importlib
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Optional


# Optional dependencies -----------------------------------------------------

def _load_optional_module(name: str):
    spec = importlib.util.find_spec(name)
    if spec is None:
        return None
    return importlib.import_module(name)


_psutil = _load_optional_module("psutil")
_pynvml = _load_optional_module("pynvml")
_torch = _load_optional_module("torch")


@dataclass
class SystemMetrics:
    """Snapshot of the host load used for auto tuning."""

    cpu_util_percent: Optional[float] = None
    ram_available_mb: Optional[float] = None
    ram_total_mb: Optional[float] = None
    gpu_util_percent: Optional[float] = None
    gpu_mem_free_frac: Optional[float] = None
    gpu_mem_free_mb: Optional[float] = None
    gpu_mem_total_mb: Optional[float] = None
    timestamp: float = time.time()

    def has_gpu_data(self) -> bool:
        return self.gpu_util_percent is not None or self.gpu_mem_free_frac is not None


def _collect_cpu_metrics(metrics: SystemMetrics) -> None:
    if _psutil is not None:
        metrics.cpu_util_percent = float(_psutil.cpu_percent(interval=0.1))
        mem = _psutil.virtual_memory()
        metrics.ram_available_mb = mem.available / (1024 * 1024)
        metrics.ram_total_mb = mem.total / (1024 * 1024)
        return

    # Fallback using load average when psutil is unavailable.
    try:
        load_1, _, _ = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        metrics.cpu_util_percent = min(100.0, max(0.0, (load_1 / cpu_count) * 100.0))
    except (OSError, AttributeError):
        metrics.cpu_util_percent = None


def _collect_ram_fallback(metrics: SystemMetrics) -> None:
    if metrics.ram_available_mb is not None:
        return
    if hasattr(os, "sysconf"):
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            phys_pages = os.sysconf("SC_PHYS_PAGES")
            avail_pages = os.sysconf("SC_AVPHYS_PAGES")
        except (ValueError, OSError, AttributeError):
            return
        metrics.ram_total_mb = phys_pages * page_size / (1024 * 1024)
        metrics.ram_available_mb = avail_pages * page_size / (1024 * 1024)


def _collect_gpu_metrics(metrics: SystemMetrics, device_index: int = 0) -> None:
    if _torch is None or not _torch.cuda.is_available():
        return

    try:
        free_bytes, total_bytes = _torch.cuda.mem_get_info(device_index)
    except Exception:
        free_bytes = total_bytes = None
    else:
        if total_bytes:
            metrics.gpu_mem_free_frac = free_bytes / total_bytes
            metrics.gpu_mem_free_mb = free_bytes / (1024 * 1024)
            metrics.gpu_mem_total_mb = total_bytes / (1024 * 1024)

    # GPU utilisation via NVML if available, otherwise fall back to nvidia-smi.
    if _pynvml is not None:
        try:
            _pynvml.nvmlInit()
            handle = _pynvml.nvmlDeviceGetHandleByIndex(device_index)
            util = _pynvml.nvmlDeviceGetUtilizationRates(handle)
            metrics.gpu_util_percent = float(util.gpu)
        except Exception:
            metrics.gpu_util_percent = None
        finally:
            try:
                _pynvml.nvmlShutdown()
            except Exception:
                pass
        return

    # nvidia-smi fallback; ignore errors silently.
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
        )
    except Exception:
        return

    try:
        values = [line.strip() for line in output.splitlines() if line.strip()]
        if values:
            metrics.gpu_util_percent = float(values[min(device_index, len(values) - 1)])
    except (ValueError, IndexError):
        metrics.gpu_util_percent = None


def capture_system_metrics(device_index: int = 0) -> SystemMetrics:
    """Collect a best-effort snapshot of host resource usage."""

    metrics = SystemMetrics(timestamp=time.time())
    _collect_cpu_metrics(metrics)
    _collect_ram_fallback(metrics)
    _collect_gpu_metrics(metrics, device_index=device_index)
    return metrics


def configure_cuda_memory_budget(target_fraction: float = 0.8) -> None:
    """Clamp the CUDA memory budget so the process uses a fixed fraction."""

    if _torch is None or not _torch.cuda.is_available():
        return

    fraction = max(0.05, min(0.95, float(target_fraction)))
    device_count = _torch.cuda.device_count()
    for index in range(device_count):
        try:
            _torch.cuda.set_per_process_memory_fraction(fraction, index)
        except Exception:
            continue


def recommend_parallelism(
    requested: int,
    metrics: SystemMetrics,
    max_parallel: int = 8,
) -> int:
    """Adjust the requested frame parallelism based on system headroom."""

    requested = max(1, requested)
    max_parallel = max(1, max_parallel)

    target = requested

    # Downscale if resources are saturated.
    if metrics.cpu_util_percent is not None and metrics.cpu_util_percent > 92:
        target = max(1, min(target, requested - 1))
    if metrics.ram_available_mb is not None and metrics.ram_available_mb < 1024:
        target = max(1, min(target, requested - 1))
    if metrics.gpu_util_percent is not None and metrics.gpu_util_percent > 92:
        target = max(1, min(target, requested - 1))
    if metrics.gpu_mem_free_frac is not None and metrics.gpu_mem_free_frac < 0.15:
        target = max(1, min(target, requested - 1))

    if target < requested:
        return target

    # Upscale if there is generous headroom.
    cpu_ok = metrics.cpu_util_percent is None or metrics.cpu_util_percent < 70
    ram_ok = metrics.ram_available_mb is None or metrics.ram_available_mb > 4096
    gpu_mem_ok = (
        metrics.gpu_mem_free_frac is None or metrics.gpu_mem_free_frac > 0.45
    )
    gpu_util_ok = metrics.gpu_util_percent is None or metrics.gpu_util_percent < 65

    if cpu_ok and ram_ok and gpu_mem_ok and gpu_util_ok:
        if requested < max_parallel:
            # Increase gradually so we do not overshoot.
            target = min(max_parallel, max(requested + 1, int(round(requested * 1.5))))

    return target


__all__ = [
    "SystemMetrics",
    "capture_system_metrics",
    "configure_cuda_memory_budget",
    "recommend_parallelism",
]
