$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$packageName = "SmartAdvisorDiscovery"
$version = "0.1.0"
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
        src/smartadvisor_discovery/app.py

    $packageDirectory = Join-Path $repositoryRoot "dist\$packageName"
    $archivePath = Join-Path $repositoryRoot "dist\$packageName-$version.zip"

    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }

    Compress-Archive `
        -Path "$packageDirectory\*" `
        -DestinationPath $archivePath `
        -CompressionLevel Optimal

    Write-Output "Package: $packageDirectory"
    Write-Output "Transfer archive: $archivePath"
}
finally {
    Pop-Location
}
