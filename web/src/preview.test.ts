/**
 * preview.test.ts — Tests K3: buildImageData (Vitest + happy-dom)
 */
import { describe, it, expect, vi, beforeAll } from "vitest";

// Mockear stream antes de importar Preview para evitar WebSocket en happy-dom
vi.mock("./api/stream", () => ({
  stream: { latestFrame: null, latestDmx: {}, onDmx: () => () => {}, onState: () => () => {} },
  LEDS: 93,
}));

// Constantes replicadas aquí para no depender del export con el mock
const NUM_BARS_TEST = 10;
const PREVIEW_LEDS_TEST = 93;
const EXPECTED_SIZE = NUM_BARS_TEST * PREVIEW_LEDS_TEST * 3;

// Import dinámico para que el mock ya esté activo
let buildImageData: (buf: ArrayBuffer, ps?: number) => ImageData;

beforeAll(async () => {
  const mod = await import("./views/Preview");
  buildImageData = mod.buildImageData;
});

describe("buildImageData", () => {
  it("devuelve ImageData con width=93, height=10 desde buffer correcto", () => {
    const buf = new ArrayBuffer(EXPECTED_SIZE);
    const img = buildImageData(buf);
    expect(img.width).toBe(PREVIEW_LEDS_TEST);
    expect(img.height).toBe(NUM_BARS_TEST);
  });

  it("primer LED rojo (bytes 0-2 = 255,0,0) → píxel (0,0) rojo en ImageData", () => {
    const buf = new ArrayBuffer(EXPECTED_SIZE);
    const view = new Uint8Array(buf);
    view[0] = 255; // R
    view[1] = 0;   // G
    view[2] = 0;   // B
    const img = buildImageData(buf);
    // píxel (0,0) en RGBA: índice 0..3
    expect(img.data[0]).toBe(255); // R
    expect(img.data[1]).toBe(0);   // G
    expect(img.data[2]).toBe(0);   // B
    expect(img.data[3]).toBe(255); // A (opaco)
  });

  it("buffer de tamaño incorrecto → no lanza, devuelve ImageData negro (93×10)", () => {
    const buf = new ArrayBuffer(100); // tamaño incorrecto
    let img: ImageData | undefined;
    expect(() => { img = buildImageData(buf); }).not.toThrow();
    expect(img!.width).toBe(PREVIEW_LEDS_TEST);
    expect(img!.height).toBe(NUM_BARS_TEST);
    // El buffer negro tiene todos los píxeles RGBA = 0
    const allZero = Array.from(img!.data).every((v) => v === 0);
    expect(allZero).toBe(true);
  });
});
