#!/usr/bin/env python3
"""Check GPU/CPU device availability and configuration.

Usage from backend/:
    python -m app.ml.check_device
"""

def main():
    print("\n" + "=" * 70)
    print("  Device Configuration Check")
    print("=" * 70 + "\n")

    try:
        import torch
        print(f"PyTorch version: {torch.__version__}")

        cuda_available = torch.cuda.is_available()
        print(f"CUDA available: {cuda_available}")

        if cuda_available:
            device_count = torch.cuda.device_count()
            print(f"GPU device(s): {device_count}")

            for i in range(device_count):
                name = torch.cuda.get_device_name(i)
                capability = torch.cuda.get_device_capability(i)
                print(f"  [{i}] {name} (Compute Capability: {capability[0]}.{capability[1]})")

            print(f"CUDA version: {torch.version.cuda}")
            print(f"cuDNN version: {torch.backends.cudnn.version()}")
        else:
            print("Running on CPU only")
    except ImportError:
        print("PyTorch not installed")
        return 1

    print("\n" + "-" * 70)
    print("  Checking E-Rakshak device detection")
    print("-" * 70 + "\n")

    try:
        from app.ml.device import get_device, is_gpu_available

        device = get_device()
        gpu_ready = is_gpu_available()

        print(f"E-Rakshak device: {device}")
        print(f"GPU acceleration: {'✓ Enabled' if gpu_ready else '✗ Disabled'}")

    except Exception as exc:
        print(f"Device detection error: {exc}")
        return 1

    print("\n" + "-" * 70)
    print("  Model Loading Check")
    print("-" * 70 + "\n")

    try:
        from app.ml.transformer_engine import get_engine

        engine = get_engine()
        if engine:
            print(f"Transformer engine: ✓ Ready (device: {engine.device})")
            print(f"  - Threat classifier: ✓")
            print(f"  - Sentiment model: ✓")
            if engine.tox:
                print(f"  - Toxicity model: ✓")
            else:
                print(f"  - Toxicity model: ✗ (optional, lite mode active)")
        else:
            print("Transformer engine: ✗ Failed to load (using lite mode)")
    except Exception as exc:
        print(f"Transformer engine error: {exc}")

    print("\n" + "=" * 70 + "\n")
    return 0


if __name__ == "__main__":
    exit(main())
