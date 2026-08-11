@echo off
chcp 65001 >nul
rem 雙擊即可安裝。
rem
rem 包一層 .bat 的理由：Windows 預設的執行原則會擋下未簽章的 .ps1，
rem 一般使用者雙擊 install.ps1 只會看到「無法載入，因為這個系統上已停用指令碼執行」。
rem 這裡用 -ExecutionPolicy Bypass 只影響這一次呼叫，不會改變系統設定。

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
    echo.
    echo 安裝失敗。請把上面的訊息回報給我們。
    pause
)
