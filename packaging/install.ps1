<#
.SYNOPSIS
    安裝 AURORA 極光播放器（單一使用者，不需要系統管理員權限）。

.DESCRIPTION
    做四件事：

      1. 把整個程式資料夾複製到 %LOCALAPPDATA%\Programs\AURORA
      2. 建立開始功能表與桌面捷徑
      3. 註冊音訊檔的「開啟方式」，讓 AURORA 出現在右鍵選單裡
      4. 寫入解除安裝資訊，讓它出現在「設定 → 應用程式」清單中

    全程只寫入 HKCU 與使用者自己的資料夾，不碰系統目錄，
    所以不需要提權，解除安裝也能還原得乾淨。

.PARAMETER NoShortcut
    不要建立桌面捷徑。

.PARAMETER NoAssociate
    不要註冊檔案關聯。

.PARAMETER NoLaunch
    安裝完不要詢問是否啟動，直接結束。自動化安裝時使用。

.NOTES
    這個檔案必須存成「UTF-8 with BOM」。Windows PowerShell 5.1 沒有 BOM
    就會用系統 ANSI 代碼頁解讀（繁中版是 cp950），中文註解與字串會變成亂碼
    並讓解析器直接失敗。tools/make_release.py 會檢查 BOM 是否存在。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1
#>

[CmdletBinding()]
param(
    [switch]$NoShortcut,
    [switch]$NoAssociate,
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'

$AppName      = 'AURORA'
$DisplayName  = 'AURORA 極光播放器'
$Publisher    = 'waydefu'
$SourceDir    = Join-Path $PSScriptRoot 'AURORA'
$InstallRoot  = Join-Path $env:LOCALAPPDATA 'Programs'
$InstallDir   = Join-Path $InstallRoot $AppName
$ExePath      = Join-Path $InstallDir 'AURORA.exe'
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppName"

function Write-Step([string]$Message) {
    Write-Host "  $Message" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "安裝 $DisplayName" -ForegroundColor White
Write-Host ("=" * 46)

# --- 前置檢查 -------------------------------------------------------------

if (-not (Test-Path -LiteralPath $SourceDir)) {
    Write-Host "找不到程式檔案：$SourceDir" -ForegroundColor Red
    Write-Host "請先把下載的 ZIP 完整解壓縮，再從解壓後的資料夾執行這個腳本。" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $SourceDir 'AURORA.exe'))) {
    Write-Host "找不到 AURORA.exe，壓縮檔可能不完整。" -ForegroundColor Red
    exit 1
}

# 正在執行中的話先請它退場，否則檔案會被鎖住
$running = Get-Process -Name 'AURORA' -ErrorAction SilentlyContinue
if ($running) {
    Write-Step "偵測到 AURORA 正在執行，先關閉它…"
    $running | Stop-Process -Force
    Start-Sleep -Milliseconds 900
}

# --- 複製程式檔案 ---------------------------------------------------------

Write-Step "複製程式檔案到 $InstallDir"
if (Test-Path -LiteralPath $InstallDir) {
    # 保留使用者設定（設定存在 %APPDATA%\Aurora，不在這裡），直接整包換掉
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
Copy-Item -LiteralPath $SourceDir -Destination $InstallDir -Recurse -Force

$sizeMb = [math]::Round(
    (Get-ChildItem $InstallDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
Write-Step "已安裝 $sizeMb MB"

# --- 捷徑 -----------------------------------------------------------------

$shell = New-Object -ComObject WScript.Shell

function New-AuroraShortcut {
    <#
        WScript.Shell 的 COM 介面會把路徑經 ANSI 代碼頁轉換，含中文的
        檔名會變成「AURORA ?????.lnk」並以 FileNotFoundException 失敗。
        （實測：ASCII 檔名可以，中文檔名 100% 失敗。）

        所以先用純 ASCII 的暫存檔名建立捷徑，再用 .NET 的檔案 API 改名 ——
        那條路徑是完整 Unicode，不經過代碼頁轉換。
    #>
    param([string]$Directory, [string]$FileName, [string]$Description = '')

    if (-not (Test-Path -LiteralPath $Directory)) {
        New-Item -ItemType Directory -Path $Directory -Force | Out-Null
    }

    $temp = Join-Path $Directory ('aurora-shortcut-' + [guid]::NewGuid().ToString('N') + '.lnk')
    $link = $shell.CreateShortcut($temp)
    $link.TargetPath       = $ExePath
    $link.WorkingDirectory = $InstallDir
    $link.IconLocation     = "$ExePath,0"
    if ($Description) { $link.Description = $Description }
    $link.Save()

    $final = Join-Path $Directory $FileName
    Move-Item -LiteralPath $temp -Destination $final -Force
    return (Test-Path -LiteralPath $final)
}

# 用 API 取資料夾位置而不是硬寫路徑：企業環境會把它們重新導向
$startMenu = [Environment]::GetFolderPath('Programs')
if (New-AuroraShortcut $startMenu "$DisplayName.lnk" '封面沉浸式桌面音樂播放器') {
    Write-Step "已建立開始功能表捷徑"
} else {
    Write-Host "  開始功能表捷徑建立失敗（不影響使用）" -ForegroundColor Yellow
}

if (-not $NoShortcut) {
    # OneDrive 會接管桌面，一定要用系統回報的實際位置
    $desktop = [Environment]::GetFolderPath('Desktop')
    if (New-AuroraShortcut $desktop "$DisplayName.lnk") {
        Write-Step "已建立桌面捷徑"
    } else {
        Write-Host "  桌面捷徑建立失敗（不影響使用）" -ForegroundColor Yellow
    }
}

# --- 檔案關聯 -------------------------------------------------------------

if (-not $NoAssociate) {
    & $ExePath --register-file-types
    Start-Sleep -Milliseconds 800
    Write-Step "已註冊檔案關聯（MP3 / FLAC / WAV / OGG）"
}

# --- 解除安裝資訊 ---------------------------------------------------------

$version = '0.1.0'
New-Item -Path $UninstallKey -Force | Out-Null
Set-ItemProperty -Path $UninstallKey -Name 'DisplayName'     -Value $DisplayName
Set-ItemProperty -Path $UninstallKey -Name 'DisplayVersion'  -Value $version
Set-ItemProperty -Path $UninstallKey -Name 'Publisher'       -Value $Publisher
Set-ItemProperty -Path $UninstallKey -Name 'DisplayIcon'     -Value $ExePath
Set-ItemProperty -Path $UninstallKey -Name 'InstallLocation' -Value $InstallDir
Set-ItemProperty -Path $UninstallKey -Name 'NoModify'        -Value 1 -Type DWord
Set-ItemProperty -Path $UninstallKey -Name 'NoRepair'        -Value 1 -Type DWord
Set-ItemProperty -Path $UninstallKey -Name 'EstimatedSize'   -Value ($sizeMb * 1024) -Type DWord
Set-ItemProperty -Path $UninstallKey -Name 'UninstallString' `
    -Value ('powershell -ExecutionPolicy Bypass -File "' +
            (Join-Path $InstallDir 'uninstall.ps1') + '"')

Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'uninstall.ps1') `
          -Destination $InstallDir -Force
Write-Step "已登錄解除安裝資訊"

# --- 完成 -----------------------------------------------------------------

Write-Host ""
Write-Host "安裝完成。" -ForegroundColor Green
Write-Host "  程式位置：$InstallDir"
Write-Host ""
Write-Host "要讓音樂檔預設用 AURORA 開啟：" -ForegroundColor Yellow
Write-Host "  在音樂檔上按右鍵 →「開啟方式」→「選擇其他應用程式」"
Write-Host "  → 選 $DisplayName → 按「一律」"
Write-Host ""
Write-Host "  （Windows 10 之後不允許程式自行設定預設播放器，"
Write-Host "    這一步必須由你確認，任何程式都繞不過去。）" -ForegroundColor DarkGray
Write-Host ""

if (-not $NoLaunch) {
    $answer = Read-Host "現在啟動 AURORA 嗎？(Y/n)"
    if ($answer -eq '' -or $answer -match '^[Yy]') {
        Start-Process -FilePath $ExePath
    }
}
