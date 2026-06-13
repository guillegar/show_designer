// schema.test.ts — Tests unitarios de funciones puras de conversión de color (F2).
import { describe, it, expect } from "vitest";
import { hexToRgb, rgbToHex } from "./schema";

describe("hexToRgb", () => {
  it("#ff8800 → {r:255, g:136, b:0}", () => {
    expect(hexToRgb("#ff8800")).toEqual({ r: 255, g: 136, b: 0 });
  });

  it("#000000 → {r:0, g:0, b:0}", () => {
    expect(hexToRgb("#000000")).toEqual({ r: 0, g: 0, b: 0 });
  });

  it("#ffffff → {r:255, g:255, b:255}", () => {
    expect(hexToRgb("#ffffff")).toEqual({ r: 255, g: 255, b: 255 });
  });

  it("acepta hex sin prefijo '#'", () => {
    expect(hexToRgb("ff0000")).toEqual({ r: 255, g: 0, b: 0 });
  });
});

describe("rgbToHex", () => {
  it("{r:255, g:0, b:0} → '#ff0000'", () => {
    expect(rgbToHex(255, 0, 0)).toBe("#ff0000");
  });

  it("{r:0, g:255, b:0} → '#00ff00'", () => {
    expect(rgbToHex(0, 255, 0)).toBe("#00ff00");
  });

  it("{r:0, g:0, b:255} → '#0000ff'", () => {
    expect(rgbToHex(0, 0, 255)).toBe("#0000ff");
  });

  it("clampea valores fuera de [0,255]", () => {
    expect(rgbToHex(300, -10, 128)).toBe("#ff0080");
  });
});

describe("roundtrip hexToRgb → rgbToHex", () => {
  it("hexToRgb(rgbToHex(r,g,b)) === {r,g,b}", () => {
    const cases: [number, number, number][] = [
      [255, 0, 0],
      [0, 255, 0],
      [0, 0, 255],
      [128, 64, 32],
      [0, 0, 0],
      [255, 255, 255],
    ];
    for (const [r, g, b] of cases) {
      expect(hexToRgb(rgbToHex(r, g, b))).toEqual({ r, g, b });
    }
  });
});
