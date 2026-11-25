export type Mark = { text: string; kind: string };
export type Segment = { text: string; kind?: string };

/** Pecah teks menjadi segmen; tiap mark dicari tanpa beda huruf, yang lebih panjang menang. */
export function segments(text: string, marks: Mark[]): Segment[] {
  const lower = text.toLowerCase();
  const occ: number[] = new Array(text.length).fill(-1); // id kemunculan yang menempati karakter
  const kinds: string[] = [];
  const sorted = marks.filter((m) => m.text.length > 0).sort((a, b) => b.text.length - a.text.length);
  for (const m of sorted) {
    const needle = m.text.toLowerCase();
    for (let at = lower.indexOf(needle); at !== -1; at = lower.indexOf(needle, at + 1)) {
      const end = at + needle.length;
      if (occ.slice(at, end).some((o) => o !== -1)) continue;
      occ.fill(kinds.length, at, end);
      kinds.push(m.kind);
    }
  }
  const out: Segment[] = [];
  let start = 0;
  for (let k = 1; k <= text.length; k++) {
    if (k < text.length && occ[k] === occ[start]) continue;
    const s = text.slice(start, k);
    out.push(occ[start] === -1 ? { text: s } : { text: s, kind: kinds[occ[start]] });
    start = k;
  }
  return out.length ? out : [{ text }];
}

export const STRONG_KINDS = new Set(["NIK", "KK", "ACCOUNT", "NPWP"]);
export function strength(kind: string): "strong" | "medium" | "employee" {
  if (STRONG_KINDS.has(kind)) return "strong";
  return kind === "NAME_EMPLOYEE" ? "employee" : "medium";
}
