# PowerShell wrapper for package.py
# Usage: .\scripts\package.ps1 [output_path]

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$packageScript = Join-Path $scriptDir "package.py"

if (-not (Test-Path $packageScript)) {
    Write-Host "Ошибка: не найден скрипт $packageScript" -ForegroundColor Red
    exit 1
}

$outputPath = $args[0]

if ($outputPath) {
    python $packageScript $outputPath
} else {
    python $packageScript
}

exit $LASTEXITCODE
