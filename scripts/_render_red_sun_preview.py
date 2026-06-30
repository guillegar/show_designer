#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render headless de frames del show red_sun a PNG (sin libs de imagen externas)."""
import sys
import zlib
import struct
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.session import ShowSession


def write_png(path, rgb):
    """rgb: (H,W,3) uint8 → PNG truecolor (stdlib zlib)."""
    H, W, _ = rgb.shape
    raw = bytearray()
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    for y in range(H):
        raw.append(0)               # filtro 0 (None) por scanline
        raw.extend(rgb[y].tobytes())
    comp = zlib.compress(bytes(raw), 9)

    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data +
                struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", comp))
        f.write(chunk(b"IEND", b""))


def upscale(frame, led_w=6, bar_h=16, gap=2):
    """(10,93,3) → imagen grande con barras apiladas (gap negro entre barras)."""
    nb, nl, _ = frame.shape
    big = np.kron(frame, np.ones((bar_h, led_w, 1), dtype=np.uint8))  # (nb*bar_h, nl*led_w,3)
    # insertar gaps entre barras
    rows = []
    for i in range(nb):
        rows.append(big[i * bar_h:(i + 1) * bar_h])
        if i < nb - 1:
            rows.append(np.zeros((gap, nl * led_w, 3), dtype=np.uint8))
    return np.vstack(rows)


def montage(frames, sep=6):
    """Lista de imágenes (apiladas verticalmente) con separador blanco tenue."""
    W = max(f.shape[1] for f in frames)
    out = []
    for i, f in enumerate(frames):
        if f.shape[1] < W:
            pad = np.zeros((f.shape[0], W - f.shape[1], 3), dtype=np.uint8)
            f = np.hstack([f, pad])
        out.append(f)
        if i < len(frames) - 1:
            out.append(np.full((sep, W, 3), 30, dtype=np.uint8))
    return np.vstack(out)


def main():
    sess = ShowSession("red_sun")

    # 1) Viaje de color: un frame por momento representativo (rojo→ámbar).
    journey_ts = [(20, "void/intro"), (50, "entra fuerte"), (95, "PEAK 1"),
                  (175, "breakdown"), (245, "PEAK 2"), (290, "clímax final"),
                  (315, "outro/puesta")]
    j_imgs = [upscale(sess.compute_frame(float(t))) for t, _ in journey_ts]
    write_png(ROOT / "red_sun_journey.png", montage(j_imgs))
    print("[+] red_sun_journey.png  ·  " +
          " | ".join(f"{t}s {lbl}" for t, lbl in journey_ts))

    # 2) Barrido asimétrico: instantes consecutivos en una frase de cometa (high/peak).
    sweep_ts = [95.0, 95.25, 95.5, 95.75, 96.0, 96.25]
    s_imgs = [upscale(sess.compute_frame(t)) for t in sweep_ts]
    write_png(ROOT / "red_sun_sweep.png", montage(s_imgs))
    print("[+] red_sun_sweep.png  ·  instantes " +
          ", ".join(f"{t}s" for t in sweep_ts))

    # 3) PULSO: secuencia fina (cada 70ms) en un pico → se ve el bombeo con el kick.
    t = 90.0
    pulse_imgs = []
    while t <= 93.0:
        pulse_imgs.append(upscale(sess.compute_frame(t), led_w=6, bar_h=10, gap=1))
        t += 0.07
    write_png(ROOT / "red_sun_pulse.png", montage(pulse_imgs, sep=2))
    print(f"[+] red_sun_pulse.png  ·  {len(pulse_imgs)} frames 90.0-93.0s (cada 70ms)")


if __name__ == "__main__":
    main()
