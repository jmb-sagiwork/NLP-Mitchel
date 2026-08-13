# PyInstaller spec for the demo UI.
#
# Scope note: this freezes the *demo harness* only. The library deliverable a
# host system imports stays a wheel - a frozen exe cannot be imported by another
# interpreter's main.py. See pipeline SP-1.1-31.
#
# Build:  py -3.14 -m PyInstaller EmailTriage.spec --noconfirm

from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

PROJECT = Path(SPECPATH)
SRC = PROJECT / "src"
RESOURCES = SRC / "email_triage" / "resources"

# Ship the config the operator edits, the regex library, and the encoder.
datas = [
    (str(RESOURCES / "concerns.json"), "email_triage/resources"),
    (str(RESOURCES / "patterns.library.json"), "email_triage/resources"),
]
model_dir = RESOURCES / "model"
for name in ("model_quint8_avx2.onnx", "tokenizer.json", "MANIFEST.json"):
    f = model_dir / name
    if f.exists():
        datas.append((str(f), "email_triage/resources/model"))

# onnxruntime loads its native libs by name; PyInstaller does not find them
# from the Python imports alone.
binaries = collect_dynamic_libs("onnxruntime")

a = Analysis(
    # Must be the launcher, not ui/app.py. PyInstaller runs the entry script as
    # __main__ with no package context, which breaks relative imports.
    [str(PROJECT / "launcher.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "email_triage",
        "onnxruntime",
        "tokenizers",
        "numpy",
    ],
    hookspath=[],
    runtime_hooks=[],
    # Nothing here is imported at runtime, and each one is tens to hundreds of
    # MB. torch alone is ~497 MB for what a 22 MB ONNX file does.
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
    [],
    exclude_binaries=True,
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

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="EmailTriage",
)
