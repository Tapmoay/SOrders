param(
  [switch]$NoBuild,       # skip gradle build, install existing APK
  [switch]$NoRun,         # install only, do not launch app
  [switch]$CleanBuild     # gradle clean before assembleEmuDebug
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$sdk    = "D:\APPS\sdk"
$adb    = "$sdk\platform-tools\adb.exe"
# ABI flavors since 2026-09-15: emulators are x86_64 -> use the "emu" flavor.
# Real phones get the "phone" flavor (arm64-v8a + armeabi-v7a), which is what
# _tools/deploy/publish_apk.py uploads. See docs/APP_UPDATE_AND_RELEASE.md.
$apk    = "$root\android\app\build\outputs\apk\emu\debug\app-emu-debug.apk"
$variant = "assembleEmuDebug"
$gradle = "$root\_agent\gradle\gradle-8.9\bin\gradle.bat"
$jbr    = "D:\APPS\AndroidStudio\jbr"
$pkg    = "com.tapmoay.sorders"
$launch = "com.tapmoay.sorders/.MainActivity"

function Log($m) { Write-Host "[dev-build] $m" }

# ---------- devices ----------
$lines = & $adb devices | Select-String "^emulator-\d+\s+device"
$serials = @($lines | ForEach-Object { ($_ -split "\s+")[0] })
if ($serials.Count -gt 0) { Log ("online devices: " + ($serials -join ", ")) } else { Log "online devices: none" }

# ---------- build ----------
if (-not $NoBuild) {
  if ($CleanBuild) {
    Log "gradle clean ..."
    $env:JAVA_HOME = $jbr; $env:ANDROID_HOME = $sdk
    & $gradle clean --no-daemon -p "$root\android"
    if ($LASTEXITCODE -ne 0) { Log "clean FAILED"; exit 1 }
  }
  Log "building $variant ..."
  $env:JAVA_HOME = $jbr; $env:ANDROID_HOME = $sdk
  & $gradle $variant --no-daemon -p "$root\android"
  if ($LASTEXITCODE -ne 0) { Log "build FAILED"; exit 1 }
}
if (-not (Test-Path $apk)) { Log "APK missing: $apk"; exit 1 }
if ($serials.Count -eq 0) {
  Log "no emulator online, skip install (start emulators first, then rerun)"
  exit 0
}

# ---------- wait boot ----------
foreach ($s in $serials) {
  $deadline = (Get-Date).AddMinutes(4); $boot = ""
  do {
    Start-Sleep 5
    $boot = (& $adb -s $s shell getprop sys.boot_completed 2>$null).Trim()
  } while ($boot -ne "1" -and (Get-Date) -lt $deadline)
  if ($boot -eq "1") { Log "$s ready" } else { Log "$s boot timeout, skip" }
}

# ---------- install + launch ----------
foreach ($s in $serials) {
  $boot = (& $adb -s $s shell getprop sys.boot_completed 2>$null).Trim()
  if ($boot -ne "1") { continue }
  Log "install -> $s ..."
  $out = & $adb -s $s install -r $apk 2>&1 | Out-String
  if ($out -match "Success") {
    Log "$s install OK"
    if (-not $NoRun) {
      & $adb -s $s shell am force-stop $pkg | Out-Null
      & $adb -s $s shell am start -n $launch | Out-Null
      Log "$s app started"
    }
  } else {
    Log "$s install FAILED: $($out.Trim())"
  }
}
Log "DONE"