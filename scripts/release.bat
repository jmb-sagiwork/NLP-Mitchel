@echo off
REM Bump version, commit, push, build MitchelNLP.exe, tag, and publish a
REM GitHub release with the built exe attached. Prints the download link.
REM
REM Usage:
REM   scripts\release.bat <version> ["release notes"]
REM   scripts\release.bat 0.2.16 "Fix XYZ"
REM
REM Requires: py -3.14 on PATH, a 32-bit build Python (see
REM scripts\build_mitchel.py), and `gh` authenticated (gh auth status).

setlocal enabledelayedexpansion

if "%~1"=="" (
    echo Usage: release.bat ^<version^> ["release notes"]
    echo Example: release.bat 0.2.16 "Fix XYZ"
    exit /b 1
)

set "VERSION=%~1"
set "NOTES=%~2"
if "%NOTES%"=="" set "NOTES=Release v%VERSION%"

set "REPO_ROOT=%~dp0.."
pushd "%REPO_ROOT%" || exit /b 1

echo === Checking working tree ===
git diff --quiet --exit-code
if errorlevel 1 (
    echo Working tree has unstaged changes. Commit or stash them first.
    goto :error
)
git diff --cached --quiet --exit-code
if errorlevel 1 (
    echo Index has staged but uncommitted changes. Commit or stash them first.
    goto :error
)

echo === Resolving repo ===
for /f "tokens=*" %%r in ('gh repo view --json nameWithOwner -q .nameWithOwner') do set "REPO=%%r"
if "%REPO%"=="" (
    echo Could not resolve the GitHub repo via gh. Is gh authenticated?
    goto :error
)

for /f "tokens=*" %%b in ('git rev-parse --abbrev-ref HEAD') do set "BRANCH=%%b"

echo === Bumping version to %VERSION% ===
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bump_version.ps1" -Version "%VERSION%"
if errorlevel 1 goto :error

echo === Committing version bump ===
git add pyproject.toml src\email_triage\__init__.py README.md
git commit -m "Release v%VERSION%"
if errorlevel 1 goto :error

echo === Pushing %BRANCH% ===
git push origin %BRANCH%
if errorlevel 1 goto :error

echo === Building MitchelNLP.exe (this takes several minutes) ===
py -3.14 scripts\build_mitchel.py --clean
if errorlevel 1 goto :error

set "ARTIFACT=dist\MitchelNLP-v%VERSION%-windows-x64.exe"
echo === Preparing release artifact ===
copy /y dist\MitchelNLP.exe "%ARTIFACT%" >nul
if errorlevel 1 goto :error

echo === Tagging v%VERSION% ===
git tag v%VERSION%
if errorlevel 1 goto :error
git push origin v%VERSION%
if errorlevel 1 goto :error

echo === Creating GitHub release ===
gh release create v%VERSION% "%ARTIFACT%" --title "v%VERSION%" --notes "%NOTES%"
if errorlevel 1 goto :error

echo.
echo === Done ===
echo Download link:
echo https://github.com/%REPO%/releases/download/v%VERSION%/MitchelNLP-v%VERSION%-windows-x64.exe

popd
exit /b 0

:error
echo.
echo Release FAILED.
popd
exit /b 1
