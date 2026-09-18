$ErrorActionPreference = "Stop"
$BaseUrl = "https://workbench-cli.oss-cn-hangzhou.aliyuncs.com"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\workbench"
$TmpDir = Join-Path $env:TEMP ("wb-install-" + (New-Guid).Guid)
New-Item -ItemType Directory -Path $TmpDir -Force | Out-Null
try {
    $ArchivePath = Join-Path $TmpDir "wb.zip"
    Invoke-WebRequest -Uri "$BaseUrl/latest/workbench-windows-amd64.zip" -OutFile $ArchivePath -UseBasicParsing
    $Actual = (Get-FileHash -Path $ArchivePath -Algorithm SHA256).Hash.ToLower()
    $Expected = "e15c03986d67c4398e9757df9edd18915b1f311cd3289cd19a743f358920b87e"
    Write-Host "SHA256 expected: $Expected"
    Write-Host "SHA256 actual:   $Actual"
    if ($Actual -ne $Expected) { Write-Host "CHECKSUM MISMATCH, abort" -ForegroundColor Red; return }
    Write-Host "CHECKSUM OK" -ForegroundColor Green
    $ExtractDir = Join-Path $TmpDir "extract"
    Expand-Archive -Path $ArchivePath -DestinationPath $ExtractDir -Force
    $Binary = Get-ChildItem -Path $ExtractDir -Recurse -Filter "workbench.exe" | Select-Object -First 1
    Write-Host "Binary: $($Binary.FullName)"
    if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null }
    Copy-Item -Path $Binary.FullName -Destination (Join-Path $InstallDir "workbench.exe") -Force
    Write-Host "Installed: $(Join-Path $InstallDir 'workbench.exe')"
    & (Join-Path $InstallDir "workbench.exe") version
    Write-Host "DONE"
} finally {
    Remove-Item -Path $TmpDir -Recurse -Force -ErrorAction SilentlyContinue
}