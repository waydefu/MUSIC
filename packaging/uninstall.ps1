<#
.SYNOPSIS
    解除安裝 AURORA 極光播放器。

.DESCRIPTION
    把 install.ps1 做過的事逐一還原：程式檔案、捷徑、檔案關聯、
    解除安裝登錄項目。

    使用者的設定與音樂庫快取存在 %APPDATA%\Aurora，預設會保留 ——
    重新安裝時播放清單與偏好都還在。要一併清掉請加 -Purge。

.PARAMETER Purge
    連同 %APPDATA%\Aurora 的設定與快取一起刪除。
#>

[CmdletBinding()]
param([switch]$Purge)

$ErrorActionPreference = 'Continue'

$AppName      = 'AURORA'
$DisplayName  = 'AURORA 極光播放器'
$InstallDir   = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppName"
$UserData     = Join-Path $env:APPDATA 'Aurora'

function Write-Step([string]$Message) { Write-Host "  $Message" -ForegroundColor Cyan }

Write-Host ""
Write-Host "解除安裝 $DisplayName" -ForegroundColor White
Write-Host ("=" * 46)

# 執行中就先關掉
$running = Get-Process -Name 'AURORA' -ErrorAction SilentlyContinue
if ($running) {
    Write-Step "關閉執行中的 AURORA…"
    $running | Stop-Process -Force
    Start-Sleep -Milliseconds 900
}

# --- 檔案關聯 -------------------------------------------------------------
# 先移除關聯再刪檔案，否則執行檔沒了就叫不動 --register-file-types 的反向操作。

$exe = Join-Path $InstallDir 'AURORA.exe'
if (Test-Path -LiteralPath $exe) {
    & $exe --unregister-file-types 2>$null
    Start-Sleep -Milliseconds 600
    Write-Step "已移除檔案關聯"
}

# 保險：直接清掉可能殘留的登錄項目
foreach ($ext in '.mp3', '.flac', '.wav', '.ogg', '.oga') {
    $key = "HKCU:\Software\Classes\$ext\OpenWithProgids"
    if (Test-Path $key) {
        Remove-ItemProperty -Path $key -Name 'AURORA.AudioFile' -ErrorAction SilentlyContinue
    }
}
foreach ($key in @(
    'HKCU:\Software\Classes\AURORA.AudioFile',
    'HKCU:\Software\Classes\Applications\AURORA.exe',
    'HKCU:\Software\AURORA'
)) {
    if (Test-Path $key) { Remove-Item -Path $key -Recurse -Force -ErrorAction SilentlyContinue }
}
Remove-ItemProperty -Path 'HKCU:\Software\RegisteredApplications' -Name 'AURORA' `
    -ErrorAction SilentlyContinue

# --- 捷徑 -----------------------------------------------------------------

$links = @(
    (Join-Path ([Environment]::GetFolderPath('Programs')) "$DisplayName.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Programs')) "$AppName.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "$DisplayName.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk")
)
foreach ($link in $links) {
    if (Test-Path -LiteralPath $link) {
        Remove-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
        Write-Step "已移除捷徑 $(Split-Path $link -Leaf)"
    }
}

# --- 程式檔案 -------------------------------------------------------------

if (Test-Path -LiteralPath $InstallDir) {
    # 這個腳本自己就在安裝目錄裡，先複製到暫存再由那份刪除來源目錄
    $staged = Join-Path $env:TEMP 'aurora-uninstall-stage.ps1'
    if ($PSCommandPath -like "$InstallDir*") {
        Copy-Item -LiteralPath $PSCommandPath -Destination $staged -Force
        Write-Step "程式檔案將於腳本結束後移除"
        Start-Process -FilePath 'powershell' -WindowStyle Hidden -ArgumentList @(
            '-ExecutionPolicy', 'Bypass', '-Command',
            "Start-Sleep -Seconds 2; Remove-Item -LiteralPath '$InstallDir' -Recurse -Force -ErrorAction SilentlyContinue"
        )
    } else {
        Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Step "已移除程式檔案"
    }
}

# --- 登錄項目 -------------------------------------------------------------

if (Test-Path $UninstallKey) {
    Remove-Item -Path $UninstallKey -Recurse -Force -ErrorAction SilentlyContinue
    Write-Step "已移除解除安裝登錄項目"
}

# --- 使用者資料 -----------------------------------------------------------

if ($Purge) {
    if (Test-Path -LiteralPath $UserData) {
        Remove-Item -LiteralPath $UserData -Recurse -Force -ErrorAction SilentlyContinue
        Write-Step "已刪除設定與音樂庫快取"
    }
} elseif (Test-Path -LiteralPath $UserData) {
    Write-Step "設定與播放清單保留在 $UserData（要清除請加 -Purge）"
}

Write-Host ""
Write-Host "解除安裝完成。" -ForegroundColor Green
Write-Host ""
