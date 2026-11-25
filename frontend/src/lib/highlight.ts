export type Mark = { text: string; kind: string };
export type Segment = { text: string; kind?: string };

/** Pecah teks menjadi segmen; tiap mark dicari tanpa beda huruf, yang lebih panjang menang. */
export function segments(text: string, marks: Mark[]): Segment[] {
  // Bandingkan per posisi pada teks asli: toLowerCase bisa mengubah panjang (mis. "İ").
  const eq = (a: string, b: string) => a === b || a.toLowerCase() === b.toLowerCase();
  const find = (needle: string, from: number) => {
    for (let i = from; i + needle.length <= text.length; i++) {
      let ok = true;
      for (let j = 0; j < needle.length; j++) if (!eq(text[i + j], needle[j])) { ok = false; break; }
      if (ok) return i;
    }
    return -1;
  };
  const occ: number[] = new Array(text.length).fill(-1); // id kemunculan yang menempati karakter
  const kinds: string[] = [];
  const sorted = marks.filter((m) => m.text.length > 0).sort((a, b) => b.text.length - a.text.length);
  for (const m of sorted) {
    const needle = m.text;
    for (let at = find(needle, 0); at !== -1; at = find(needle, at + 1)) {
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
