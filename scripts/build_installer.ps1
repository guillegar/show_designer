# build_installer.ps1 — Script de build reproducible para Show Designer Pro (H2)
#
# Uso:
#   cd show-designer
#   .\scripts\build_installer.ps1
#
# Pasos:
#   1. npm run build  → genera web/dist/
#   2. pyinstaller    → genera dist/ShowDesigner/
#   3. iscc (opcional) → ShowDesigner_setup.exe (requiere Inno Setup en PATH)
#
# Requiere:
#   - Python 3.11 con venv311/ activado (o python.exe en PATH)
#   - Node.js + npm en PATH
#   - pyinstaller: pip install pyinstaller
#   - Inno Setup (opcional): https://jrsoftware.org/isinfo.php

[CmdletBinding()]
param(
    [switch]$SkipFrontend,    # omite npm run build (util si ya compilaste)
    [switch]$SkipInstaller,   # omite Inno Setup (solo PyInstaller)
    [switch]$Clean,           # borra dist/ y build/ antes de compilar
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent

Push-Location $Root

try {
    # ── 0. Limpieza opcional ────────────────────────────────────────────────────
    if ($Clean) {
        Write-Host "[build] Limpiando dist/ y build/..." -ForegroundColor Cyan
        if (Test-Path "dist")  { Remove-Item -Recurse -Force "dist" }
        if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
    }

    # ── 1. Compilar frontend ────────────────────────────────────────────────────
    if (-not $SkipFrontend) {
        Write-Host "[build] npm run build en web/..." -ForegroundColor Cyan
        Push-Location "$Root\web"
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build falló (exit $LASTEXITCODE)" }
        Pop-Location

        if (-not (Test-Path "$Root\web\dist\index.html")) {
            throw "web/dist/index.html no encontrado tras npm run build"
        }
        Write-Host "[build] Frontend OK → web/dist/" -ForegroundColor Green
    } else {
        Write-Host "[build] Saltando npm run build (--SkipFrontend)" -ForegroundColor Yellow
    }

    # ── 2. PyInstaller ──────────────────────────────────────────────────────────
    Write-Host "[build] PyInstaller..." -ForegroundColor Cyan

    # Detectar python: venv311 > python en PATH
    $PythonExe = if (Test-Path "$Root\venv311\Scripts\python.exe") {
        "$Root\venv311\Scripts\python.exe"
    } else {
        "python"
    }

    & $PythonExe -m PyInstaller showdesigner.spec --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller falló (exit $LASTEXITCODE)" }

    $DistExe = "$Root\dist\ShowDesigner\ShowDesigner.exe"
    if (-not (Test-Path $DistExe)) {
        throw "ShowDesigner.exe no encontrado en dist/ShowDesigner/"
    }
    Write-Host "[build] PyInstaller OK → dist/ShowDesigner/" -ForegroundColor Green

    # ── 3. Inno Setup (opcional) ────────────────────────────────────────────────
    if (-not $SkipInstaller -and (Test-Path "$Root\ShowDesigner.iss")) {
        $IsccCmd = Get-Command "iscc" -ErrorAction SilentlyContinue
        if ($IsccCmd) {
            Write-Host "[build] Inno Setup..." -ForegroundColor Cyan
            & iscc "$Root\ShowDesigner.iss"
            if ($LASTEXITCODE -ne 0) { throw "Inno Setup (iscc) falló (exit $LASTEXITCODE)" }
            Write-Host "[build] Inno Setup OK → ShowDesigner_setup.exe" -ForegroundColor Green
        } else {
            Write-Host "[build] iscc no encontrado en PATH — saltando Inno Setup" -ForegroundColor Yellow
            Write-Host "        Instala Inno Setup desde https://jrsoftware.org/isinfo.php" -ForegroundColor Yellow
        }
    } else {
        Write-Host "[build] Saltando Inno Setup (sin ShowDesigner.iss o --SkipInstaller)" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "=== BUILD COMPLETO ===" -ForegroundColor Green
    Write-Host "  Directorio: dist\ShowDesigner\" -ForegroundColor Green
    Write-Host "  Ejecutable: dist\ShowDesigner\ShowDesigner.exe" -ForegroundColor Green

} finally {
    Pop-Location
}
