# PyInstaller spec for the teaching UI.
#
# Scope note: this freezes `email_triage_ui` only. The library deliverable a
# host system imports stays a wheel - a frozen exe cannot be imported by another
# interpreter's main.py. See pipeline SP-1.1-31.
#
# Build:  py -3.14 -m PyInstaller EmailTriage.spec --noconfirm
#
# One-file mode: set EMAILTRIAGE_ONEFILE=1 (scripts/build_exe.py --onefile does
# this). A spec cannot take custom CLI flags, so the switch travels by env var.

import os
from pathlib import Path

PROJECT = Path(SPECPATH)

# One self-contained EmailTriage.exe vs a folder beside the exe.
ONEFILE = os.environ.get("EMAILTRIAGE_ONEFILE") == "1"
SRC = PROJECT / "src"
RESOURCES = SRC / "email_triage" / "resources"

# Ship the config the operator edits and the regex library.
datas = [
    (str(RESOURCES / "concerns.json"), "email_triage/resources"),
    (str(RESOURCES / "patterns.library.json"), "email_triage/resources"),
]
binaries = []

a = Analysis(
    # Must be the launcher, not email_triage_ui/app.py. PyInstaller runs the
    # entry script as __main__ with no package context, which breaks relative
    # imports.
    [str(PROJECT / "launcher.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "email_triage",
        "email_triage_ui",
    ],
    hookspath=[],
    runtime_hooks=[],
    # Nothing here is imported at runtime.
    excludes=[
        "torch",
        "transformers",
        "sentence_transformers",
        "scipy",
        "pandas",
        "matplotlib",
        "PIL",
        "IPython",
        "pytest",
        "sklearn",
        # No network stack should be reachable from the inference path.
        "requests",
        "urllib3",
        "huggingface_hub",
        "hf_xet",
        "fastembed",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    # One-file folds every binary and data file into the exe itself; one-dir
    # leaves them to COLLECT below.
    *([a.binaries, a.datas] if ONEFILE else [[]]),
    exclude_binaries=not ONEFILE,
    name="EmailTriage",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI app: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if not ONEFILE:
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="EmailTriage",
    )

# One-file trade-off, for whoever reads this next:
#   - The bootloader unpacks the Python/Tk runtime to a temp dir on every
#     launch, so cold start is slower than one-dir mode.
#   - config.py already resolves resources through sys._MEIPASS, and
#     email_triage_ui/app.py writes data/dataset.jsonl next to sys.executable -
#     which stays the real exe path, not the temp dir. So both modes behave
#     identically on disk.
#   - Locked-down endpoints sometimes block self-extracting exes outright. If
#     the client's machine refuses to launch it, fall back to the one-dir zip.
