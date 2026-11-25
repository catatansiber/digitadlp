import { KIND_TEXT } from "../lib/labels";
import { strength } from "../lib/highlight";
import { Button } from "./Button";

export type Finding = { kind: string; text: string; page: number | null; start?: number; end?: number; source?: string };

const TONE = { strong: ["rah", "Kuat"], medium: ["int", "Sedang"], employee: ["pub", "Pegawai"] } as const;

export function FindingList({
  findings,
  onIgnore,
  busy,
}: {
  findings: Finding[];
  onIgnore?: (f: Finding) => void;
  busy?: boolean;
}) {
  const groups = new Map<string, Finding[]>();
  for (const f of [...findings].sort((a, b) => (a.page ?? Infinity) - (b.page ?? Infinity))) {
    const key = f.page == null ? "Di luar halaman" : `Halaman ${f.page + 1}`;
    groups.set(key, [...(groups.get(key) ?? []), f]);
  }
  if (groups.size === 0) return <p className="muted">Tidak ada temuan.</p>;
  return (
    <>
      {[...groups].map(([name, list]) => (
        <div key={name} role="group" aria-label={name} className="f-group">
          <h3 className="muted">{name}</h3>
          {list.map((f, i) => {
            const [tone, word] = TONE[strength(f.kind)];
            return (
              <div key={i} className="f">
                <span className="t">{KIND_TEXT[f.kind] ?? f.kind}</span>
                <span className={`chip ${tone}`}>{word}</span>
                <span className="f-v">{f.text}</span>
                {onIgnore && (
                  <Button className="f-act" disabled={busy} onClick={() => onIgnore(f)}>
                    Abaikan
                  </Button>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </>
  );
}
