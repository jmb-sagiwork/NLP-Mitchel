$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$packageName = "SmartAdvisorAutomation"
$version = "0.2.0"
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
    $archivePath = Join-Path $repositoryRoot "dist\$packageName-$version.zip"

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
        --name "$packageName-$version" `
        --specpath $oneFileBuildDirectory `
        --workpath $oneFileBuildDirectory `
        --distpath release `
        --paths src `
        --collect-submodules pywinauto `
        src/smartadvisor_automation/app.py

    Write-Output "Package: $packageDirectory"
    Write-Output "Transfer archive: $archivePath"
    Write-Output (
        "Standalone executable: " +
        (Join-Path $repositoryRoot "release\$packageName-$version.exe")
    )
}
finally {
    Pop-Location
}
