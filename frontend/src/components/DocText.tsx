import { segments, strength, type Mark } from "../lib/highlight";

export function DocText({ pages, marks }: { pages: string[]; marks: Mark[] }) {
  return (
    <div className="doc" aria-label="Teks dokumen">
      {pages.map((p, i) => (
        <div key={i} className="doc-page">
          <span className="muted">Halaman {i + 1}</span>
          <p>
            {segments(p, marks).map((s, j) =>
              s.kind ? (
                <mark key={j} className={strength(s.kind)}>
                  {s.text}
                </mark>
              ) : (
                <span key={j}>{s.text}</span>
              ),
            )}
          </p>
        </div>
      ))}
    </div>
  );
}
