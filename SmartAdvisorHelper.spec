from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

PROJECT = Path(SPECPATH)
SRC = PROJECT / "src"

a = Analysis(
    [str(PROJECT / "smartadvisor_helper_launcher.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[],
    hiddenimports=(
        collect_submodules("pywinauto")
        + collect_submodules("comtypes")
        + [
            "smartadvisor_automation.driver",
            "smartadvisor_automation.errors",
            "smartadvisor_automation.models",
            "smartadvisor_automation.selectors",
            "smartadvisor_automation.workflow",
        ]
    ),
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "numpy", "onnxruntime", "tokenizers", "selenium"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SmartAdvisorHelper-x86",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
