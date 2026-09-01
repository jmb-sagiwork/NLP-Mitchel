import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

PROJECT = Path(SPECPATH)
SRC = PROJECT / "src"
RESOURCES = SRC / "email_triage" / "resources"
BRANDING = SRC / "mitchel_pipeline" / "resources"
HELPER = Path(os.environ["MITCHEL_HELPER_EXE"]).resolve()

if not HELPER.is_file():
    raise SystemExit(f"SmartAdvisor helper not found: {HELPER}")

APP_ICON = BRANDING / "AURA.ico"
if not APP_ICON.is_file():
    raise SystemExit(f"App icon not found: {APP_ICON}")

datas = [
    (str(RESOURCES / "concerns.json"), "email_triage/resources"),
    (str(RESOURCES / "patterns.library.json"), "email_triage/resources"),
    (str(BRANDING / "AURA.ico"), "mitchel_pipeline/resources"),
    (str(BRANDING / "brand_logo.png"), "mitchel_pipeline/resources"),
    (str(HELPER), "."),
]
for name in ("model_quint8_avx2.onnx", "tokenizer.json", "MANIFEST.json"):
    path = RESOURCES / "model" / name
    if not path.is_file():
        raise SystemExit(f"Required MiniLM asset not found: {path}")
    datas.append((str(path), "email_triage/resources/model"))

# Selenium Manager is a packaged native executable used to locate a compatible
# ChromeDriver. Its hook coverage varies by Selenium/PyInstaller release, so
# include Selenium's non-Python data explicitly.
datas += collect_data_files("selenium")
binaries = collect_dynamic_libs("onnxruntime")

a = Analysis(
    [str(PROJECT / "mitchel_launcher.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=(
        collect_submodules("selenium")
        + [
            "email_triage",
            "incontact_automation.extractor",
            "salesforce_automation.driver",
            "salesforce_automation.lookup",
            "mitchel_pipeline.app",
            "mitchel_pipeline.helper_client",
            "mitchel_pipeline.orchestrator",
            "mitchel_pipeline.results_workbook",
            "mitchel_pipeline.selftest",
            "onnxruntime",
            "openpyxl",
            "tokenizers",
            "numpy",
        ]
    ),
    hookspath=[],
    runtime_hooks=[],
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
    a.binaries,
    a.datas,
    [],
    name="MitchelNLP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(APP_ICON),
)
