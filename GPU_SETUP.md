# GPU Acceleration Setup

This project now automatically detects and uses GPU (CUDA) when available, falling back to CPU if not present. No configuration changes are needed — the system will work with either.

## Automatic GPU Detection

The following components now support GPU acceleration:

### ✅ GPU-Accelerated
- **Threat Classification** (Transformer models)
- **Sentiment Analysis** (Transformer models)  
- **Toxicity Detection** (Transformer models)
- **Fine-tuning** (Training scripts for custom models)

### ⚠️ CPU-Only
- **Face Detection** (dlib via face_recognition library)
  - Face detection uses dlib's HOG and CNN detectors, which are CPU-only
  - Face embedding comparison (matching) uses NumPy and is well-optimized for multi-core CPUs
  - For GPU-accelerated face detection, consider using [insightface](https://github.com/deepinsightnet/insightface) as an alternative backend

## Setup Instructions

### Option 1: Automatic (Recommended)
Just run the bootstrap script — it will automatically install CUDA-enabled PyTorch if available:

```bash
cd backend
python -m app.ml.bootstrap
```

This will:
- Attempt to install PyTorch from the CUDA 12.8 wheel index (if you have a compatible GPU)
- Fall back to CPU-only PyTorch if no GPU is detected
- Download datasets and train models on the available device

### Option 2: Manual CUDA Setup
If you want explicit control over CUDA installation:

#### Windows
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu128
```

#### Linux/macOS
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

#### CPU-Only (if you don't have a GPU)
```bash
pip install torch
```

### Prerequisites for GPU Support
- **NVIDIA GPU** (CUDA Compute Capability 3.5+)
- **NVIDIA Drivers** (latest recommended)
- **CUDA Toolkit 12.1+** (PyTorch will use this version)
- **cuDNN** (bundled with PyTorch wheels)

Check your setup:
```bash
python -c "import torch; print(f'GPU available: {torch.cuda.is_available()}'); print(f'Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"CPU\"}')"
```

## Device Detection

The system logs which device is being used when models load. Look for messages like:

```
[INFO] GPU available: NVIDIA A100-PCIE-40GB (1 device(s))
[INFO] Loading transformer models on device: cuda
```

Or:

```
[INFO] No GPU detected, using CPU
[INFO] Loading transformer models on device: cpu
```

## Performance Notes

### Expected Speedups (GPU vs CPU)
- **Threat Classification**: ~10-30x faster (depending on batch size and model)
- **Sentiment Analysis**: ~10-30x faster
- **Fine-tuning**: ~5-20x faster (larger models benefit more)
- **Face Detection/Matching**: ~1-2x faster (already CPU-optimized; GPU benefit is limited)

### Batch Processing
For best GPU utilization when processing multiple items:
- Threat classification: batches of 8-32
- Sentiment analysis: batches of 16-64
- Face detection: processes images sequentially (GPU benefit is mainly in the encoding step)

## Troubleshooting

### "No GPU detected, using CPU"
- Check if an NVIDIA GPU is installed: `nvidia-smi`
- Ensure NVIDIA drivers are up to date
- Verify CUDA toolkit is installed: `nvcc --version`
- Check PyTorch installation: `python -c "import torch; print(torch.cuda.is_available())"`

### Out of Memory (OOM) errors on GPU
- Reduce batch size in training scripts (e.g., `--batch 8` instead of 16)
- Reduce input sequence length (e.g., `--max-len 64` instead of 128)
- CPU will auto-fallback in production if GPU runs out of memory

### PyTorch not using GPU after install
Reinstall PyTorch from the CUDA index:
```bash
pip uninstall torch
pip install torch --index-url https://download.pytorch.org/whl/cu128
```

## Code Changes

The following files were updated to support GPU acceleration:

- `backend/app/ml/device.py` — Device detection utilities
- `backend/app/ml/transformer_engine.py` — Automatic GPU/CPU selection for inference
- `backend/app/ml/train.py` — GPU detection for fine-tuning
- `backend/app/ml/train_sentiment.py` — GPU detection for sentiment model training
- `backend/app/ml/bootstrap.py` — CUDA wheel installation (already supported)

All changes are backward-compatible. The code will work seamlessly on CPU-only systems.
