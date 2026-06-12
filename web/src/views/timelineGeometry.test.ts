// timelineGeometry.test.ts — primer test de frontend (ROADMAP v2, F0.3).
// Regla: todo módulo TS PURO nuevo nace con test. Los componentes React no se
// testean (no merece el coste); solo la lógica pura.
// Ejecutar: cd web && npm test   (requiere `npm install` una vez para vitest)
import { describe, it, expect } from "vitest";
import { xToMs, msToX, buildLaneLayout, yToLane, LaneInput } from "./timelineGeometry";

describe("xToMs / msToX", () => {
  it("son inversas", () => {
    expect(msToX(xToMs(123, 7), 7)).toBeCloseTo(123);
    expect(xToMs(msToX(5000, 12), 12)).toBeCloseTo(5000);
  });
  it("zoom = px por segundo", () => {
    expect(msToX(1000, 10)).toBe(10);   // 1 s a zoom 10 → 10 px
    expect(xToMs(10, 10)).toBe(1000);
  });
});

const lanes: LaneInput[] = [
  { laneKey: "bar-0", kind: "bar", bar: 0, fixtureId: null, height: 36 },
  { laneKey: "bar-1", kind: "bar", bar: 1, fixtureId: null, height: 58 }, // 2 capas
  { laneKey: "fx-mover", kind: "fixture", bar: null, fixtureId: "mover", height: 36 },
];

describe("buildLaneLayout", () => {
  it("acumula offsets reales con alturas variables", () => {
    const layout = buildLaneLayout(lanes);
    expect(layout.map((l) => l.top)).toEqual([0, 36, 94]);
  });
});

describe("yToLane", () => {
  const layout = buildLaneLayout(lanes);
  it("resuelve la fila bajo la Y", () => {
    expect(yToLane(40, layout)?.laneKey).toBe("bar-1");
    expect(yToLane(95, layout)?.laneKey).toBe("fx-mover");
  });
  it("clampa fuera de rango al primero/último", () => {
    expect(yToLane(-5, layout)?.laneKey).toBe("bar-0");
    expect(yToLane(9999, layout)?.laneKey).toBe("fx-mover");
  });
  it("layout vacío → null", () => {
    expect(yToLane(10, [])).toBeNull();
  });
});
