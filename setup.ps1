# Aftermovie Studio setup for Windows 10/11.
# Double-click "Aftermovie Studio.bat" (it runs this on first start), or run:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Step($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Yellow }

Step "Python"
$py = $null
foreach ($v in @("3.13", "3.12", "3.11")) {
    if (-not $py -and (Have "py")) { & py "-$v" --version *> $null; if ($LASTEXITCODE -eq 0) { $py = @("py", "-$v") } }
}
if (-not $py -and (Have "python")) { $ver = (& python --version 2>&1) -join ""; if ($ver -match "3\.1[1-3]") { $py = @("python") } }
if (-not $py) {
    Write-Host "Installing Python 3.13 with winget..."
    winget install -e --id Python.Python.3.13 --accept-package-agreements --accept-source-agreements
    $py = @("py", "-3.13")
}
Write-Host ("using: " + ($py -join " "))

Step "ffmpeg"
if (Have "ffmpeg") { Write-Host "ffmpeg found" } else {
    winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

Step "Python packages (first time: ~3 GB, 5-15 minutes)"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $rest = @($py | Select-Object -Skip 1)
    & $py[0] @rest -m venv .venv
}
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install -r requirements.txt

Step "Face models"
New-Item -ItemType Directory -Force models | Out-Null
$models = @{
    "face_detection_yunet_2023mar.onnx"   = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
    "face_recognition_sface_2021dec.onnx" = "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
}
foreach ($m in $models.Keys) {
    if (-not (Test-Path "models\$m")) { Write-Host "downloading $m"; Invoke-WebRequest -Uri $models[$m] -OutFile "models\$m" }
}

Step "Claude Code (the director)"
if (Have "claude") { Write-Host "Claude Code found" } else {
    Write-Host "Claude Code is not installed. It directs the films (you need a Claude plan)." -ForegroundColor Cyan
    Write-Host "Install it with:   irm https://claude.ai/install.ps1 | iex"
    Write-Host "then run 'claude' once in this folder to log in."
}

Step "Check"
& .venv\Scripts\python.exe tools\studio.py doctor
Write-Host ""
Write-Host "Done. Start the studio with 'Aftermovie Studio.bat'." -ForegroundColor Green
