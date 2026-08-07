"""One-time fetch of the local voice models.

    cd backend && python -m app.services.voice.bootstrap          # download
    cd backend && python -m app.services.voice.bootstrap --check  # report only

Downloading is a separate, deliberate step rather than something the
synthesiser does on first use. Kokoro's weights are ~310 MB, and a fetch
triggered by the first sentence of a live call would stall that call for
minutes and then time out — on the officer's very first question, on the worst
possible occasion, and with the whole event loop watching. Doing it here means
the failure mode of an unprepared machine is a browser voice, which works.

The files land in KOKORO_MODEL_DIR (backend/models/kokoro by default) and are
the ones kokoro-onnx expects by name. They are released under Apache-2.0 by the
kokoro-onnx project; the model itself is Kokoro-82M, also Apache-2.0, which is
why this is the local voice the product ships toward rather than Piper's
GPL-3.0 library.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

from app.services.voice.transformer.tts import KokoroTTS

RELEASE = ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
           "model-files-v1.0")
#: (url, destination) — destination names are fixed by kokoro-onnx.
FILES = ((f"{RELEASE}/kokoro-v1.0.onnx", "kokoro-v1.0.onnx"),
         (f"{RELEASE}/voices-v1.0.bin", "voices-v1.0.bin"))


def _download(url: str, dest: Path) -> None:
    """Streamed to a .part file, then renamed.

    An interrupted download that leaves a half-written kokoro-v1.0.onnx in
    place is worse than no download at all: `available()` only checks that the
    file exists, so the truncated one would be loaded on every call and fail
    every time. Renaming only after the last byte means a file that exists is
    a file that is whole.
    """
    part = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        done = 0
        with part.open("wb") as handle:
            for chunk in response.iter_bytes(chunk_size=1 << 20):
                handle.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {dest.name}: {done * 100 // total}% "
                          f"({done >> 20}/{total >> 20} MB)", end="", flush=True)
        print()
    part.replace(dest)


def check() -> bool:
    model, voices = KokoroTTS.model_files()
    ready = True
    for path in (model, voices):
        if path.exists():
            print(f"  present  {path}  ({path.stat().st_size >> 20} MB)")
        else:
            print(f"  MISSING  {path}")
            ready = False
    try:
        import kokoro_onnx  # noqa: F401
        print("  present  kokoro-onnx package")
    except Exception:
        print("  MISSING  kokoro-onnx package — pip install kokoro-onnx")
        ready = False
    print(f"\nKokoro is {'ready' if ready else 'NOT ready'}; "
          f"tts.status() reports available={KokoroTTS.available()}")
    return ready


def download() -> None:
    model, _voices = KokoroTTS.model_files()
    directory = model.parent
    directory.mkdir(parents=True, exist_ok=True)
    print(f"Fetching Kokoro voice models into {directory}")
    for url, name in FILES:
        dest = directory / name
        if dest.exists():
            print(f"  {name} already present — skipping")
            continue
        _download(url, dest)
    print()
    check()


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
    download()
