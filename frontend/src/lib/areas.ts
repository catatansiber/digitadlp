export type Box = { x0: number; y0: number; x1: number; y1: number };
export type Area = Box & { id: string; page: number };

export const MIN_SIDE = 0.005;

const clamp = (v: number) => Math.min(1, Math.max(0, v));

/** Ubah dua titik piksel (relatif ke permukaan w×h) menjadi kotak ternormalisasi 0..1. */
export function normalizeBox(
  ax: number,
  ay: number,
  bx: number,
  by: number,
  w: number,
  h: number,
): Box | null {
  if (!(w > 0) || !(h > 0)) return null;
  const x0 = clamp(Math.min(ax, bx) / w);
  const x1 = clamp(Math.max(ax, bx) / w);
  const y0 = clamp(Math.min(ay, by) / h);
  const y1 = clamp(Math.max(ay, by) / h);
  if (x1 - x0 < MIN_SIDE || y1 - y0 < MIN_SIDE) return null;
  return { x0, y0, x1, y1 };
}
