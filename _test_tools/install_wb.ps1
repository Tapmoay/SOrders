$ErrorActionPreference = "Stop"
$BaseUrl = "https://workbench-cli.oss-cn-hangzhou.aliyuncs.com"
$Version = "v0.1.4-beta"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\workbench"
$TmpDir = Join-Path $env:TEMP ("workbench-install-" + (New-Guid).Guid)
New-Item -ItemType Directory -Path $TmpDir -Force | Out-Null
try {
    $ArchiveUrl = "$BaseUrl/releases/$Version/workbench-windows-amd64.zip"
    Write-Host "Downloading $ArchiveUrl..."
    $ArchivePath = Join-Path $TmpDir "wb.zip"
    Invoke-WebRequest -Uri $ArchiveUrl -OutFile $ArchivePath -UseBasicParsing
    Write-Host "Downloading checksums..."
    $ChecksumPath = Join-Path $TmpDir "checksums.sha256"
    Invoke-WebRequest -Uri "$BaseUrl/releases/$Version/checksums.sha256" -OutFile $ChecksumPath -UseBasicParsing
    $Lines = Get-Content $ChecksumPath
    foreach ($Line in $Lines) {
        if ($Line -match "^(\S+)\s+.*workbench-windows-amd64.zip") {
            $Expected = $Matches[1]
            $Actual = (Get-FileHash -Path $ArchivePath -Algorithm SHA256).Hash.ToLower()
            Write-Host "Expected: $Expected"
            Write-Host "Actual:   $Actual"
            if ($Actual -eq $Expected) { Write-Host "CHECKSUM OK" -ForegroundColor Green } else { Write-Host "CHECKSUM MISMATCH!" -ForegroundColor Red }
            break
        }
    }
    $ExtractDir = Join-Path $TmpDir "extract"
    Expand-Archive -Path $ArchivePath -DestinationPath $ExtractDir -Force
    $Binary = Get-ChildItem -Path $ExtractDir -Recurse -Filter "workbench.exe" | Select-Object -First 1
    Write-Host "Binary found: $($Binary.FullName)"
    if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null }
    Copy-Item -Path $Binary.FullName -Destination (Join-Path $InstallDir "workbench.exe") -Force
    Write-Host "Installed to: $(Join-Path $InstallDir 'workbench.exe')"
    $RegKey = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
    $UserPath = $RegKey.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    [string[]]$PathEntries = @($UserPath -split ";" | Where-Object { $_ -ne "" })
    if ($InstallDir -notin $PathEntries) {
        $NewPath = ($PathEntries + $InstallDir) -join ";"
        $RegKey.SetValue('Path', $NewPath, [Microsoft.Win32.RegistryValueKind]::ExpandString)
        Write-Host "PATH added"
    }
    $RegKey.Close()
    Write-Host ""
    & (Join-Path $InstallDir "workbench.exe") version
    Write-Host "DONE"
} finally {
    Remove-Item -Path $TmpDir -Recurse -Force -ErrorAction SilentlyContinue
}