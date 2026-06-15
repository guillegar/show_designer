import { useEffect, useRef, useState } from "react";
import { stream } from "../api/stream";

// ── K3: constantes exportadas para tests (Vitest) ─────────────────────────

export const NUM_BARS = 10;
export const PREVIEW_LEDS = 93; // LEDs por barra (misma que LEDS en stream.ts)

/**
 * Convierte el frame binario (NUM_BARS × PREVIEW_LEDS × 3 bytes uint8 RGB)
 * a un ImageData de width=PREVIEW_LEDS, height=NUM_BARS.
 * Si el buffer es de tamaño incorrecto, devuelve ImageData negro.
 */
export function buildImageData(
  frameBuffer: ArrayBuffer,
  _pixelSize: number = 1
): ImageData {
  const expected = NUM_BARS * PREVIEW_LEDS * 3;
  const img = new ImageData(PREVIEW_LEDS, NUM_BARS);
  if (frameBuffer.byteLength !== expected) return img;

  const src = new Uint8Array(frameBuffer);
  const dst32 = new Uint32Array(img.data.buffer);
  for (let i = 0, n = NUM_BARS * PREVIEW_LEDS; i < n; i++) {
    // Little-endian RGBA packed as uint32: 0xAABBGGRR
    dst32[i] = (255 << 24) | (src[i * 3 + 2] << 16) | (src[i * 3 + 1] << 8) | src[i * 3];
  }
  return img;
}

// ── K3: Vista Preview 2D en tiempo real ───────────────────────────────────

export function PreviewView() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);
  const [pixelSize, setPixelSize] = useState(4);
  const [showLabels, setShowLabels] = useState(true);

  // Render loop via requestAnimationFrame
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Cache rendering objects once per effect run — no GC pressure in the draw loop
    const ctx = canvas.getContext("2d")!;
    const tmpCanvas = document.createElement("canvas");
    tmpCanvas.width = PREVIEW_LEDS;
    tmpCanvas.height = NUM_BARS;
    const tmpCtx = tmpCanvas.getContext("2d")!;
    const imgData = new ImageData(PREVIEW_LEDS, NUM_BARS);
    const dst32 = new Uint32Array(imgData.data.buffer);

    function draw() {
      const frame = stream.latestFrame;
      if (frame && frame.byteLength === NUM_BARS * PREVIEW_LEDS * 3) {
        // Uint32 pixel copy: 4× faster than byte-by-byte, no per-frame allocation
        for (let i = 0, n = NUM_BARS * PREVIEW_LEDS; i < n; i++) {
          dst32[i] = (255 << 24) | (frame[i * 3 + 2] << 16) | (frame[i * 3 + 1] << 8) | frame[i * 3];
        }
        tmpCtx.putImageData(imgData, 0, 0);
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(tmpCanvas, 0, 0, PREVIEW_LEDS * pixelSize, NUM_BARS * pixelSize);
      } else {
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.fillStyle = "#0a0a10";
        ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
      }

      // Overlay: etiquetas de barra
      if (showLabels) {
        ctx.font = `${Math.max(9, pixelSize * 0.9)}px monospace`;
        ctx.textBaseline = "middle";
        for (let bar = 0; bar < NUM_BARS; bar++) {
          const y = bar * pixelSize + pixelSize / 2;
          ctx.fillStyle = "rgba(0,0,0,0.5)";
          ctx.fillRect(0, y - pixelSize / 2, 28, pixelSize);
          ctx.fillStyle = "#aac";
          ctx.fillText(`B${bar}`, 2, y);
        }
      }

      rafRef.current = requestAnimationFrame(draw);
    }

    rafRef.current = requestAnimationFrame(draw);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [pixelSize, showLabels]);

  const canvasW = PREVIEW_LEDS * pixelSize;
  const canvasH = NUM_BARS * pixelSize;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: "var(--bg)",
        overflow: "hidden",
      }}
    >
      {/* Toolbar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "6px 14px",
          borderBottom: "1px solid var(--line)",
          flexShrink: 0,
        }}
      >
        <span style={{ fontWeight: 600, fontSize: 12, color: "var(--txt-2)" }}>
          Preview 2D
        </span>
        <span style={{ fontSize: 11, color: "var(--txt-3)" }}>
          Zoom:
        </span>
        {[2, 4, 6, 8].map((sz) => (
          <button
            key={sz}
            className={"btn sm" + (pixelSize === sz ? "" : " ghost")}
            style={{ fontSize: 11, padding: "1px 7px" }}
            onClick={() => setPixelSize(sz)}
          >
            ×{sz}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <label style={{ fontSize: 11, color: "var(--txt-2)", display: "flex", gap: 4, alignItems: "center", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={showLabels}
            onChange={(e) => setShowLabels(e.target.checked)}
            style={{ cursor: "pointer" }}
          />
          Etiquetas
        </label>
      </div>

      {/* Canvas centrado */}
      <div
        style={{
          flex: 1,
          overflow: "auto",
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "flex-start",
          padding: 16,
        }}
      >
        <canvas
          ref={canvasRef}
          width={canvasW}
          height={canvasH}
          style={{
            imageRendering: "pixelated",
            border: "1px solid var(--line)",
            display: "block",
          }}
        />
      </div>

      {/* Info */}
      <div
        style={{
          padding: "4px 14px",
          fontSize: 10,
          color: "var(--txt-3)",
          borderTop: "1px solid var(--line)",
          flexShrink: 0,
        }}
      >
        {NUM_BARS} barras · {PREVIEW_LEDS} LEDs/barra · {canvasW}×{canvasH}px
      </div>
    </div>
  );
}
