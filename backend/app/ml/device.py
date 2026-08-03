"""GPU/CPU device detection and management.

Automatically selects GPU if available, falls back to CPU.
"""
import logging

log = logging.getLogger("sentinel.ml")

_device = None


def get_device() -> str:
    """Returns 'cuda' if available, else 'cpu'. Cached after first call."""
    global _device
    if _device is not None:
        return _device

    try:
        import torch
        if torch.cuda.is_available():
            _device = "cuda"
            cuda_count = torch.cuda.device_count()
            device_name = torch.cuda.get_device_name(0)
            log.info(f"GPU available: {device_name} ({cuda_count} device(s))")
        else:
            _device = "cpu"
            log.info("No GPU detected, using CPU")
    except Exception as exc:
        log.warning(f"Device detection failed: {exc}, defaulting to CPU")
        _device = "cpu"

    return _device


def is_gpu_available() -> bool:
    """True if CUDA/GPU is available."""
    return get_device() == "cuda"
