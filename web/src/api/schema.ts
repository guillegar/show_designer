// schema.ts — Helpers para PARAM_SCHEMA (F2: Plugin UI auto-generada).
// Funciones puras de conversión color hex ↔ {r,g,b}.

export interface ParamSpec {
  type: "float" | "int" | "bool" | "enum" | "color" | "str";
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
  default?: unknown;
  label?: string;
  unit?: string;
}

export type EffectSchema = Record<string, ParamSpec>;

// ── Conversión de color ────────────────────────────────────────────────────

/** Convierte un hex de 6 dígitos (con o sin #) a {r, g, b} 0-255. */
export function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const clean = hex.startsWith("#") ? hex.slice(1) : hex;
  const n = parseInt(clean, 16);
  return {
    r: (n >> 16) & 0xff,
    g: (n >> 8) & 0xff,
    b: n & 0xff,
  };
}

/** Convierte componentes r, g, b 0-255 a hex con prefijo '#'. */
export function rgbToHex(r: number, g: number, b: number): string {
  return (
    "#" +
    [r, g, b]
      .map((x) => Math.max(0, Math.min(255, Math.round(x))).toString(16).padStart(2, "0"))
      .join("")
  );
}

// ── Detección de grupos de color en el schema ──────────────────────────────

/** Triplete RGB conocido: nombres de los tres canales que forman un color. */
export interface ColorGroup {
  label: string;
  keys: [string, string, string]; // [rKey, gKey, bKey]
}

/**
 * Detecta grupos r/g/b dentro del schema y devuelve la lista de grupos.
 * Convención:
 *   - Keys "r","g","b"           → grupo "Color"
 *   - Keys "color1_r/g/b"        → grupo "Color 1"
 *   - Keys "color2_r/g/b"        → grupo "Color 2"
 *   - Keys "r_low/g_low/b_low"   → grupo "Color bajo"
 *   - Keys "r_high/g_high/b_high"→ grupo "Color alto"
 */
export function detectColorGroups(schema: EffectSchema): ColorGroup[] {
  const keys = new Set(Object.keys(schema));
  const groups: ColorGroup[] = [];

  const candidates: Array<{ label: string; r: string; g: string; b: string }> = [
    { label: "Color",       r: "r",        g: "g",        b: "b"        },
    { label: "Color 1",     r: "color1_r", g: "color1_g", b: "color1_b" },
    { label: "Color 2",     r: "color2_r", g: "color2_g", b: "color2_b" },
    { label: "Color bajo",  r: "r_low",    g: "g_low",    b: "b_low"    },
    { label: "Color alto",  r: "r_high",   g: "g_high",   b: "b_high"   },
    { label: "Tono",        r: "hue_r",    g: "hue_g",    b: "hue_b"    },
  ];

  for (const c of candidates) {
    if (keys.has(c.r) && keys.has(c.g) && keys.has(c.b)) {
      groups.push({ label: c.label, keys: [c.r, c.g, c.b] });
    }
  }
  return groups;
}

/** Conjunto de keys que pertenecen a algún grupo de color (se omiten del render individual). */
export function colorGroupKeys(schema: EffectSchema): Set<string> {
  const out = new Set<string>();
  for (const g of detectColorGroups(schema)) {
    g.keys.forEach((k) => out.add(k));
  }
  return out;
}
