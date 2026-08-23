@echo off
rem ==================================================================
rem  AURORA installer launcher.  Double-click this file to install.
rem
rem  KEEP THIS FILE PURE ASCII, CRLF LINE ENDINGS, NO BOM.
rem  (These comments are in English for that reason alone -- every
rem  other document in this repository is Traditional Chinese.)
rem
rem  cmd.exe decodes a .bat with the console code page but remembers
rem  how far it has read as a BYTE offset.  Any multi-byte character,
rem  or an LF without its CR, desynchronises those two counters and
rem  every later line is resumed from its middle.  That is exactly
rem  how the 0.2.0 release shipped: the file was stored LF-only, so
rem  on a zh-TW console it printed a page of "is not recognized"
rem  and never reached the powershell call below.  Nothing installed.
rem  A UTF-8 BOM breaks it differently -- it swallows the @echo off.
rem
rem  Guarded by .gitattributes, tests/test_version.py and
rem  tools/make_release.py, so it cannot silently regress again.
rem
rem  Every user-facing Chinese string lives in install.ps1, which is
rem  UTF-8-with-BOM PowerShell and handles them correctly.  The chcp
rem  below is what lets that output render in this console.
rem
rem  The wrapper exists because Windows refuses to run unsigned .ps1
rem  by default; double-clicking install.ps1 only produces an
rem  execution-policy error.  -ExecutionPolicy Bypass applies to this
rem  single invocation and does not change any system setting.
rem ==================================================================

chcp 65001 >nul

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"

if errorlevel 1 (
    echo.
    echo Installation failed. Please report the messages above.
    rem install.ps1 has already explained the reason in Chinese; this
    rem branch only keeps the window open so the user can read it.
    rem The pause prompt itself is localised by Windows.
    pause
)
