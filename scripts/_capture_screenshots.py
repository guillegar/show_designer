"""Captura screenshots reales de la app para el README (portfolio).

Arranca Chromium (Playwright), navega por las pestañas y guarda PNGs en docs/images/.
Pone el show a reproducir para que el visor 3D y el preview muestren las LEDs encendidas.
Requiere el backend corriendo en http://localhost:8000.
"""
import pathlib
from playwright.sync_api import sync_playwright

OUT = pathlib.Path("docs/images")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8000"


def shot(page, name):
    path = OUT / name
    page.screenshot(path=str(path))
    print("saved", path)


def click_tab(page, text, settle=2200):
    page.locator(".tabs button", has_text=text).first.click()
    page.wait_for_timeout(settle)


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000}, device_scale_factor=1.5)
    page = ctx.new_page()
    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(3500)  # deja que React + WS + waveform asienten

    # 1) Timeline (estado limpio, t=0)
    shot(page, "01-timeline.png")

    # Reproducir para encender LEDs (reloj maestro en el servidor: sigue aunque cambie de tab)
    page.locator(".tp-btn.play").first.click()
    page.wait_for_timeout(5000)  # avanza a una zona con luz

    # 2) Visor 3D (WebGL en iframe /v3d/ — dale margen para renderizar)
    click_tab(page, "3D Viewer", settle=4500)
    shot(page, "02-viewer3d.png")

    # 3) Preview 2D (frame RGB en tiempo real)
    click_tab(page, "Preview", settle=2500)
    shot(page, "03-preview.png")

    # 4) Patch (editor de rig / canvas de fixtures)
    click_tab(page, "Patch", settle=2500)
    shot(page, "04-patch.png")

    # 5) Live · Feedback (control en directo)
    click_tab(page, "Live", settle=2500)
    shot(page, "05-live.png")

    # 6) Analyzer (análisis de audio)
    click_tab(page, "Analyzer", settle=2500)
    shot(page, "06-analyzer.png")

    # Pausa
    click_tab(page, "Timeline", settle=800)
    page.locator(".tp-btn.play").first.click()

    browser.close()
    print("DONE")
