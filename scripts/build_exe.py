"""Build the demo EXE, then prove it works before declaring success.

    py -3.14 scripts/build_exe.py
    py -3.14 scripts/build_exe.py --clean

A build that produces an .exe is not evidence. This runs the frozen binary's
--selftest from a foreign working directory (which is how a real operator will
launch it) and fails loudly if the bundled model or config did not come along.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SPEC = PROJECT / "EmailTriage.spec"
DIST = PROJECT / "dist" / "EmailTriage"
EXE = DIST / "EmailTriage.exe"
MODEL = PROJECT / "src" / "email_triage" / "resources" / "model" / "model_quint8_avx2.onnx"


def _exe_is_running() -> bool:
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {EXE.name}", "/NH"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return EXE.name.lower() in out.lower()


def human(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB"


def tree_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="remove build/ and dist/ first")
    args = ap.parse_args()

    if not MODEL.exists():
        print("Model not found. Run: py -3.14 scripts/fetch_model.py")
        print("(Building without it produces an exe that silently runs on rules only.)")
        return 1

    # A running instance holds its DLLs open and PyInstaller fails mid-build
    # with a bare WinError 5 that names a random .pyd. Say what is actually wrong.
    if EXE.exists() and _exe_is_running():
        print(f"{EXE.name} is currently running - close the window and re-run.")
        print("(Windows locks the bundled DLLs, so the build cannot replace them.)")
        return 1

    if args.clean:
        for d in (PROJECT / "build", PROJECT / "dist"):
            shutil.rmtree(d, ignore_errors=True)
            print(f"  removed {d.name}/")

    print("Building...")
    proc = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm",
         "--distpath", str(PROJECT / "dist"), "--workpath", str(PROJECT / "build")],
        cwd=PROJECT, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout[-3000:])
        print(proc.stderr[-3000:])
        return proc.returncode

    if not EXE.exists():
        print(f"Build reported success but {EXE.name} is missing.")
        return 1

    print(f"  {EXE.name}  {human(EXE.stat().st_size)}")
    print(f"  bundle    {human(tree_size(DIST))}")

    # Run from somewhere else entirely: a frozen app must not depend on cwd.
    print("\nSelf-test (from a temp working directory)...")
    (DIST / "selftest.json").unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        run = subprocess.run([str(EXE), "--selftest"], cwd=tmp,
                             capture_output=True, text=True, timeout=180)

    report_path = DIST / "selftest.json"
    if not report_path.exists():
        print("  FAILED: no selftest.json written")
        print(run.stdout[-2000:] or "(no stdout)")
        print(run.stderr[-2000:] or "(no stderr)")
        return 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report.get("ok"):
        print("  FAILED")
        print(json.dumps(report, indent=2)[:3000])
        return 1

    print(f"  ok               : {report['ok']}")
    print(f"  embeddings active: {report['embeddings_active']}")
    print(f"  layers           : {', '.join(report['layers'])}")
    print(f"  concerns         : {len(report['concern_ids'])}")
    res = report["result"]
    print(f"  sample           : {res['concern_id']} @ {res['confidence']} "
          f"-> {res['values']}")
    print(f"\nReady: {EXE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
