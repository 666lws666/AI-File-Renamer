[CmdletBinding()]
param(
    [switch]$SkipClean,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = if ($PythonPath) { $PythonPath } else { Join-Path $projectRoot ".venv\Scripts\python.exe" }
$spec = Join-Path $projectRoot "packaging\xuxia.spec"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment not found: $python"
}
$python = (Resolve-Path -LiteralPath $python).Path
$originalBuildPath = $env:PATH
$buildSystemDirectory = [Environment]::GetFolderPath("System")
$buildWindowsDirectory = Split-Path -Parent $buildSystemDirectory

Push-Location $projectRoot
try {
    # A caller's PATH can include unrelated tools (for example Poppler) whose
    # ICU DLL has incompatible exports. Do not let it shadow Windows/Qt DLLs
    # during PyInstaller's binary dependency analysis. Restore it in finally.
    $env:PATH = (@((Split-Path -Parent $python), $buildSystemDirectory, $buildWindowsDirectory) -join ";")
    & $python -m PyInstaller --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is not installed. Run: pip install -r requirements-build.txt"
    }

    $arguments = @("-m", "PyInstaller", "--noconfirm")
    if (-not $SkipClean) {
        $arguments += "--clean"
    }
    $arguments += $spec
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE"
    }

    $packageRoot = Join-Path $projectRoot "dist\Xuxia"
    $exe = Join-Path $packageRoot "Xuxia.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "Expected packaged executable was not created: $exe"
    }

    # PyInstaller onedir stores datas under _internal. The manual is a
    # user-facing companion artifact, so expose a verified copy beside Xuxia.exe.
    # Discover the sole root HTML file instead of embedding a non-ASCII literal;
    # Windows PowerShell 5.1 otherwise decodes UTF-8 scripts using a legacy codepage.
    $manualCandidates = @(Get-ChildItem -LiteralPath $projectRoot -Filter "*.html" -File)
    if ($manualCandidates.Count -ne 1) {
        throw "Expected exactly one root-level user manual HTML, found $( $manualCandidates.Count )"
    }
    $manualSource = $manualCandidates[0].FullName
    $manualTarget = Join-Path $packageRoot $manualCandidates[0].Name
    $assetsSource = Join-Path $projectRoot "user-guide-assets"
    $assetsTarget = Join-Path $packageRoot "user-guide-assets"
    Copy-Item -LiteralPath $manualSource -Destination $manualTarget -Force
    Copy-Item -LiteralPath $assetsSource -Destination $assetsTarget -Recurse -Force
    Write-Output $exe
}
finally {
    $env:PATH = $originalBuildPath
    Pop-Location
}
