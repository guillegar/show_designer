// Pure geometry helpers for the timeline interaction layer.
// Kept side-effect free so they can be unit-tested in isolation.

/** Pixel X (within the lanes container) → milliseconds, given the zoom (px per second). */
export function xToMs(px: number, zoom: number): number {
  return (px / zoom) * 1000;
}

/** Milliseconds → pixel X within the lanes container. */
export function msToX(ms: number, zoom: number): number {
  return (ms / 1000) * zoom;
}

export type LaneSlot = {
  laneKey: string;
  kind: "bar" | "fixture";
  bar: number | null;        // bar index for pixel lanes, null for fixture lanes
  fixtureId: string | null;  // fixture id for fixture lanes
  top: number;               // cumulative top offset (px) inside the lanes container
  height: number;            // measured row height (px)
};

export type LaneInput = {
  laneKey: string;
  kind: "bar" | "fixture";
  bar: number | null;
  fixtureId: string | null;
  height: number;
};

/**
 * Build the vertical layout of lane rows with REAL cumulative offsets.
 * Row heights vary (a bar with N layers is taller), so we can't assume a fixed
 * row height — this is exactly the bug that broke vertical drag before.
 */
export function buildLaneLayout(lanes: LaneInput[]): LaneSlot[] {
  const out: LaneSlot[] = [];
  let top = 0;
  for (const l of lanes) {
    out.push({
      laneKey: l.laneKey,
      kind: l.kind,
      bar: l.bar,
      fixtureId: l.fixtureId,
      top,
      height: l.height,
    });
    top += l.height;
  }
  return out;
}

/**
 * Hit-test: given a Y coordinate LOCAL to the lanes container, return the lane
 * slot under it. Clamps to the first/last lane so a drag slightly out of bounds
 * still resolves to the nearest lane.
 */
export function yToLane(localY: number, layout: LaneSlot[]): LaneSlot | null {
  if (layout.length === 0) return null;
  if (localY < 0) return layout[0];
  for (const slot of layout) {
    if (localY >= slot.top && localY < slot.top + slot.height) return slot;
  }
  return layout[layout.length - 1];
}
