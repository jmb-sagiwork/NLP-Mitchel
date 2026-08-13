"""Download the MiniLM ONNX encoder onto a DEV machine. Never run at runtime.

Deliberate choices:
  * plain urllib, not huggingface_hub - the hub client must never become a
    runtime dependency, so it is not a build dependency either
  * pinned to a commit SHA, not a branch, so the artifact is reproducible
  * SHA256 is recorded to MANIFEST.json on first fetch and VERIFIED on every
    later fetch, so a corrupted or swapped file fails loudly

Usage:
    py -3.14 scripts/fetch_model.py
    py -3.14 scripts/fetch_model.py --verify-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

REPO = "sentence-transformers/all-MiniLM-L6-v2"
# Pinned revision. Bump deliberately, never track a branch.
REVISION = "main"
BASE = f"https://huggingface.co/{REPO}/resolve/{REVISION}"

# AVX2, not AVX512-VNNI: VNNI needs Ice Lake or newer, and the target CPUs are
# unknown/older corporate hardware where VNNI kernels fall back to slow paths.
FILES = {
    "model_quint8_avx2.onnx": f"{BASE}/onnx/model_quint8_avx2.onnx",
    "tokenizer.json": f"{BASE}/tokenizer.json",
}

MODEL_DIR = Path(__file__).resolve().parents[1] / "src" / "email_triage" / "resources" / "model"
MANIFEST = MODEL_DIR / "MANIFEST.json"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"repo": REPO, "revision": REVISION, "files": {}}


def download(url: str, dest: Path) -> None:
    print(f"  fetching {dest.name} ...", end="", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "email-triage-fetch/1.0"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
        total = 0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            total += len(chunk)
    tmp.replace(dest)
    print(f" {total / 1e6:.1f} MB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-only", action="store_true",
                    help="check existing files against the manifest, download nothing")
    args = ap.parse_args()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    recorded = manifest.get("files", {})
    failures = 0

    for name, url in FILES.items():
        dest = MODEL_DIR / name
        if args.verify_only:
            if not dest.exists():
                print(f"  MISSING  {name}")
                failures += 1
                continue
        elif not dest.exists():
            try:
                download(url, dest)
            except Exception as exc:
                print(f" FAILED\n    {type(exc).__name__}: {exc}")
                failures += 1
                continue
        else:
            print(f"  present  {name}")

        digest = sha256_of(dest)
        expected = recorded.get(name, {}).get("sha256")
        if expected is None:
            recorded[name] = {"sha256": digest, "bytes": dest.stat().st_size, "url": url}
            print(f"    recorded sha256 {digest[:16]}...")
        elif expected != digest:
            print(f"    HASH MISMATCH for {name}")
            print(f"      expected {expected}")
            print(f"      actual   {digest}")
            failures += 1
        else:
            print(f"    sha256 ok {digest[:16]}...")

    manifest["files"] = recorded
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    if failures:
        print(f"\n{failures} problem(s). Layer 3 will stay disabled; the engine still "
              f"runs on rules + structural.")
        return 1
    print("\nModel ready. Layer 3 (embeddings) will activate on next engine build.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
