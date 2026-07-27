$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$packageName = "SmartAdvisorAutomation"
$version = "0.2.9"
$architecture = python -c "import struct; print('x64' if struct.calcsize('P') == 8 else 'x86')"
$artifactName = "$packageName-$version-$architecture"
$extractorName = "SmartAdvisorObjectExtractor"
$extractorVersion = "0.1.0"
$extractorArtifactName = "$extractorName-$extractorVersion-$architecture"
$pickerName = "SmartAdvisorControlPicker"
$pickerVersion = "0.1.0"
$pickerArtifactName = "$pickerName-$pickerVersion-$architecture"
Push-Location $repositoryRoot

try {
    python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --name $packageName `
        --specpath build `
        --paths src `
        --collect-submodules pywinauto `
        src/smartadvisor_automation/app.py

    $packageDirectory = Join-Path $repositoryRoot "dist\$packageName"
    $archivePath = Join-Path $repositoryRoot "dist\$artifactName.zip"

    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }

    Compress-Archive `
        -Path "$packageDirectory\*" `
        -DestinationPath $archivePath `
        -CompressionLevel Optimal

    $oneFileBuildDirectory = Join-Path $repositoryRoot "build\onefile"
    New-Item `
        -ItemType Directory `
        -Force `
        -Path $oneFileBuildDirectory | Out-Null

    python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onefile `
        --name $artifactName `
        --specpath $oneFileBuildDirectory `
        --workpath $oneFileBuildDirectory `
        --distpath release `
        --paths src `
        --collect-submodules pywinauto `
        src/smartadvisor_automation/app.py

    $extractorBuildDirectory = Join-Path $repositoryRoot "build\extractor"
    New-Item `
        -ItemType Directory `
        -Force `
        -Path $extractorBuildDirectory | Out-Null

    python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onefile `
        --name $extractorArtifactName `
        --specpath $extractorBuildDirectory `
        --workpath $extractorBuildDirectory `
        --distpath release `
        --paths src `
        --collect-submodules pywinauto `
        src/smartadvisor_automation/object_extractor_app.py

    $pickerBuildDirectory = Join-Path $repositoryRoot "build\picker"
    New-Item `
        -ItemType Directory `
        -Force `
        -Path $pickerBuildDirectory | Out-Null

    python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onefile `
        --name $pickerArtifactName `
        --specpath $pickerBuildDirectory `
        --workpath $pickerBuildDirectory `
        --distpath release `
        --paths src `
        --collect-submodules pywinauto `
        src/smartadvisor_automation/control_picker_app.py

    Write-Output "Package: $packageDirectory"
    Write-Output "Transfer archive: $archivePath"
    Write-Output (
        "Standalone executable: " +
        (Join-Path $repositoryRoot "release\$artifactName.exe")
    )
    Write-Output (
        "Object extractor: " +
        (
            Join-Path $repositoryRoot (
                "release\$extractorArtifactName.exe"
            )
        )
    )
    Write-Output (
        "Control picker: " +
        (
            Join-Path $repositoryRoot (
                "release\$pickerArtifactName.exe"
            )
        )
    )
}
finally {
    Pop-Location
}
