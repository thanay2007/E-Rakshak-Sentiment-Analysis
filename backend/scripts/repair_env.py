"""Find and reinstall packages whose compiled files have gone missing.

This repo lives under OneDrive, which deletes .pyd/.dll files inside the venv
without any error. pip never notices: the package metadata is intact and only
the binary is gone (bundled `*.libs` DLLs are often not even in pip's RECORD).
The symptom is an ImportError at uvicorn startup — "DLL load failed",
"No module named 'pydantic_core._pydantic_core'" — that looks like a code bug.

Each module below is imported in a fresh interpreter. Any package that fails is
force-reinstalled at the version already installed (no upgrade, no dependency
changes), and the check runs again.

Usage:  python scripts/repair_env.py            check, and repair what is broken
        python scripts/repair_env.py --check    check only; exit 1 if anything is broken
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, packages_distributions, version

# Modules with compiled code, lowest-level first. A package that is not
# installed is skipped, so optional dependencies cost nothing here.
#
# An entry is either a module name or (module to import, module whose package
# owns the binary). psycopg_binary refuses to be imported on its own, and when
# its binary is gone the failure surfaces as `import psycopg` failing — but it
# is psycopg-binary that needs reinstalling, not psycopg.
MODULES: list[str | tuple[str, str]] = [
    "numpy",
    "scipy.linalg",
    "pandas",
    "pyarrow.lib",
    "sklearn.utils",
    "PIL._imaging",
    "pydantic_core._pydantic_core",
    ("psycopg", "psycopg_binary"),
    "cryptography.hazmat.bindings._rust",
    "Cryptodome.Cipher.AES",
    "lxml.etree",
    "regex._regex",
    "jiter",
    "watchfiles",
    "httptools",
    "tokenizers",
    "hf_xet",
    "safetensors",
    "sentencepiece",
    "tiktoken",
    "llvmlite.binding",
    "numba",
    "torch",
    "dlib",
]

# Runs in the child: import each module and report the traceback of any that fail.
_PROBE = r"""
import importlib, json, sys, traceback
out = {}
for name in json.loads(sys.argv[1]):
    try:
        importlib.import_module(name)
    except BaseException:
        out[name] = traceback.format_exc()
print(json.dumps(out))
"""


def installed_modules() -> dict[str, str]:
    """Map each installed module in MODULES to the distribution that ships it."""
    owners = packages_distributions()
    found = {}
    for entry in MODULES:
        mod, owner = entry if isinstance(entry, tuple) else (entry, entry)
        dists = owners.get(owner.split(".")[0])
        if dists:
            found[mod] = dists[0]
    return found


def probe(modules: list[str]) -> dict[str, str]:
    """Import `modules` in a fresh interpreter; return {module: traceback} for failures."""
    proc = subprocess.run([sys.executable, "-c", _PROBE, json.dumps(modules)],
                          capture_output=True, text=True)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        # The interpreter itself died (a crashing extension). Fall back to one
        # process per module so a single bad binary cannot hide the others.
        if len(modules) == 1:
            return {modules[0]: proc.stderr or f"exit code {proc.returncode}"}
        failed = {}
        for mod in modules:
            failed.update(probe([mod]))
        return failed


def root_causes(failed: dict[str, str]) -> list[str]:
    """Drop failures that only happened because an earlier module is broken.

    scikit-learn fails to import when scipy's DLL is missing, and reinstalling
    scikit-learn would not help. A traceback that passes through another failed
    package's files is treated as collateral.
    """
    roots = []
    for mod, tb in failed.items():
        tops = {m.split(".")[0] for m in failed if m != mod}
        if not any(f"\\{top}\\" in tb or f"/{top}/" in tb for top in tops):
            roots.append(mod)
    return roots or list(failed)[:1]


def reinstall(dist: str) -> bool:
    try:
        ver = version(dist)
    except PackageNotFoundError:
        return False
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
           "-q", "--force-reinstall", "--no-deps", f"{dist}=={ver}"]
    # A local version tag like 2.9.0+cu128 only exists on PyTorch's own index.
    if "+" in ver:
        cmd += ["--index-url", f"https://download.pytorch.org/whl/{ver.split('+', 1)[1]}"]
    print(f"    reinstalling {dist}=={ver}", flush=True)
    return subprocess.run(cmd).returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="report only, do not repair")
    args = ap.parse_args()

    owners = installed_modules()
    failed = probe(list(owners))
    if not failed:
        print(f"    all {len(owners)} native packages load")
        return 0

    tried: set[str] = set()
    for _ in range(len(owners)):
        print("    broken: " + ", ".join(sorted(failed)), flush=True)
        if args.check:
            return 1
        todo = [owners[m] for m in root_causes(failed) if owners[m] not in tried]
        if not todo:
            break
        for dist in dict.fromkeys(todo):
            tried.add(dist)
            reinstall(dist)
        failed = probe(list(owners))
        if not failed:
            print("    repaired; all native packages load")
            return 0

    print("    could not repair: " + ", ".join(sorted(failed)), file=sys.stderr)
    for mod, tb in failed.items():
        print(f"\n--- {mod} ---\n{tb.strip().splitlines()[-1]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
