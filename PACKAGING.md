# Mitchel Windows executable

The production package is a single x64 executable:

```text
dist/MitchelNLP.exe
```

It contains the offline MiniLM model, Selenium integration, and a separately
compiled x86 `SmartAdvisorHelper-x86.exe`. PyInstaller extracts the helper into
its private runtime directory when the main executable starts it. The operator
only receives and launches `MitchelNLP.exe`.

## Build prerequisites

- x64 Python 3.14 with the project `build` and `embeddings` dependencies;
- x86 Python 3.11-3.13 with PyInstaller 6.20 and pywinauto 0.6.9;
- `model_quint8_avx2.onnx` and `tokenizer.json` in
  `src/email_triage/resources/model/`.

The build script checks both PE architectures and verifies the model files
against `MANIFEST.json` before packaging.

## Build

When the project-local x86 runtime exists at
`.build-tools/Python313-32/python.exe`:

```powershell
py -3.14 scripts/build_mitchel.py --clean
```

For a different x86 interpreter:

```powershell
py -3.14 scripts/build_mitchel.py --python-x86 C:\Python313-32\python.exe --clean
```

The build performs a frozen headless self-test after creating the executable.
It verifies that MiniLM activates, a representative email produces a valid
SmartAdvisor job, Selenium imports, and the embedded x86 helper completes its
JSON-lines readiness handshake. Results are written to
`dist/mitchel-selftest.json`.

## Run

Open `MitchelNLP.exe`. Before selecting **Start**:

1. Make sure Google Chrome is installed.
2. Open and authenticate the 32-bit SmartAdvisor application in the same
   Windows/Citrix session.
3. Complete the NICE CXone login when Mitchel opens Chrome and prompts you.

The current InContact integration processes the three player URLs configured
in `src/incontact_automation/extractor.py`.

To repeat the packaged diagnostic without opening the UI:

```powershell
.\dist\MitchelNLP.exe --selftest
```
