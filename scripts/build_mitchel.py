"""Build the x86 SmartAdvisor helper and single-file MitchelNLP.exe.

The main process must be x64 for ONNX Runtime. The helper must be x86 to match
the 32-bit SmartAdvisor WinForms process. Set MITCHEL_PYTHON_X86 to a 32-bit
Python 3.11-3.13 executable with PyInstaller and pywinauto installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
MODEL_DIR = PROJECT / "src" / "email_triage" / "resources" / "model"
HELPER_SPEC = PROJECT / "SmartAdvisorHelper.spec"
MAIN_SPEC = PROJECT / "MitchelNLP.spec"
BUILD_DIR = PROJECT / "build" / "mitchel"
HELPER_DIST = BUILD_DIR / "helper-dist"
HELPER_EXE = HELPER_DIST / "SmartAdvisorHelper-x86.exe"
MAIN_EXE = PROJECT / "dist" / "MitchelNLP.exe"

PE_X86 = 0x014C
PE_X64 = 0x8664


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    display = " ".join(command)
    print(f"> {display}")
    completed = subprocess.run(command, cwd=PROJECT, env=env)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def _machine(path: Path) -> int:
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise RuntimeError(f"not a PE executable: {path}")
        stream.seek(0x3C)
        pe_offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(pe_offset)
        if stream.read(4) != b"PE\0\0":
            raise RuntimeError(f"invalid PE signature: {path}")
        return struct.unpack("<H", stream.read(2))[0]


def _python_bits(python: Path) -> int:
    completed = subprocess.run(
        [str(python), "-c", "import struct;print(struct.calcsize('P')*8)"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(completed.stdout.strip())


def _resolve_x86(value: str | None) -> Path:
    configured = value or os.environ.get("MITCHEL_PYTHON_X86")
    candidates = [
        Path(configured) if configured else None,
        PROJECT / ".build-tools" / "Python313-32" / "python.exe",
        Path(r"C:\Python313-32\python.exe"),
        Path(r"C:\Python312-32\python.exe"),
        Path(r"C:\Python311-32\python.exe"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file() and _python_bits(candidate) == 32:
            return candidate.resolve()
    raise SystemExit(
        "A 32-bit Python build runtime was not found. Set MITCHEL_PYTHON_X86 "
        "to its python.exe after installing PyInstaller and pywinauto."
    )


def _verify_models() -> None:
    manifest = json.loads((MODEL_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        path = MODEL_DIR / name
        if not path.is_file():
            raise SystemExit(f"Missing model asset: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected["sha256"] or path.stat().st_size != expected["bytes"]:
            raise SystemExit(f"Model asset failed verification: {path}")


def _build_helper(python_x86: Path, clean: bool) -> None:
    if clean and BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    HELPER_DIST.mkdir(parents=True, exist_ok=True)
    work = BUILD_DIR / "helper-work"
    _run(
        [
            str(python_x86),
            "-m",
            "PyInstaller",
            str(HELPER_SPEC),
            "--noconfirm",
            "--clean",
            "--distpath",
            str(HELPER_DIST),
            "--workpath",
            str(work),
        ]
    )
    if not HELPER_EXE.is_file() or _machine(HELPER_EXE) != PE_X86:
        raise SystemExit("SmartAdvisor helper build is missing or is not x86.")


def _build_main() -> None:
    env = {**os.environ, "MITCHEL_HELPER_EXE": str(HELPER_EXE)}
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(MAIN_SPEC),
            "--noconfirm",
            "--clean",
            "--distpath",
            str(PROJECT / "dist"),
            "--workpath",
            str(BUILD_DIR / "main-work"),
        ],
        env=env,
    )
    if not MAIN_EXE.is_file() or _machine(MAIN_EXE) != PE_X64:
        raise SystemExit("MitchelNLP.exe build is missing or is not x64.")


def _selftest() -> None:
    report = MAIN_EXE.parent / "mitchel-selftest.json"
    report.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        completed = subprocess.run(
            [str(MAIN_EXE), "--selftest"],
            cwd=temporary,
            capture_output=True,
            text=True,
            timeout=300,
        )
    if completed.returncode or not report.is_file():
        print(completed.stdout[-4000:])
        print(completed.stderr[-4000:])
        raise SystemExit("Frozen self-test failed to produce a passing report.")
    result = json.loads(report.read_text(encoding="utf-8"))
    if not result.get("ok"):
        print(json.dumps(result, indent=2))
        raise SystemExit("Frozen self-test failed.")
    print(json.dumps(result, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-x86", help="path to a 32-bit Python executable")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--skip-selftest", action="store_true")
    args = parser.parse_args()

    if struct.calcsize("P") != 8:
        raise SystemExit("Run this build script with 64-bit Python.")
    python_x86 = _resolve_x86(args.python_x86)
    _verify_models()
    _build_helper(python_x86, args.clean)
    _build_main()
    if not args.skip_selftest:
        _selftest()
    print(f"Ready: {MAIN_EXE} ({MAIN_EXE.stat().st_size / 1_000_000:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
