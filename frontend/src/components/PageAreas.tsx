import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { PointerEvent as RPointerEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, FALLBACK_MESSAGE } from "../api/client";
import { normalizeBox, type Area, type Box } from "../lib/areas";
import { Button } from "./Button";
import { Toast } from "./Toast";

type Props = {
  docId: string;
  ext: string;
  pageCount: number;
  canEdit: boolean;
  status?: string;
};

const msg = (e: unknown) => (e instanceof ApiError ? e.detail : FALLBACK_MESSAGE);
const pct = (v: number) => `${+(v * 100).toFixed(4)}%`;

/** Kotak yang diposisikan lewat CSSOM (setProperty), bukan atribut style, agar sesuai CSP. */
function BoxEl({ box, className, testId }: { box: Box; className: string; testId?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const s = ref.current?.style;
    if (!s) return;
    s.setProperty("--x0", pct(box.x0));
    s.setProperty("--y0", pct(box.y0));
    s.setProperty("--x1", pct(box.x1));
    s.setProperty("--y1", pct(box.y1));
  }, [box.x0, box.y0, box.x1, box.y1]);
  return <div ref={ref} className={className} data-testid={testId} aria-hidden="true" />;
}

export function PageAreas({ docId, ext, pageCount, canEdit, status }: Props) {
  const qc = useQueryClient();
  const base = `/documents/${encodeURIComponent(docId)}`;
  const [page, setPage] = useState(0);
  const [drag, setDrag] = useState<{ id: number; ax: number; ay: number; bx: number; by: number } | null>(null);
  const [toast, setToast] = useState<{ message: string; kind: "info" | "error" } | null>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);
  const isPdf = ext === "pdf";

  const pages = useQuery({
    queryKey: ["document-pages", docId],
    queryFn: () => api<{ count: number; sizes: number[][] }>(`${base}/pages`),
    enabled: isPdf,
  });
  const areasQ = useQuery({
    queryKey: ["document-areas", docId],
    queryFn: () => api<Area[]>(`${base}/areas`),
    enabled: isPdf,
  });
  const count = Math.max(1, pages.data?.count ?? pageCount);
  useEffect(() => {
    if (page >= count) setPage(count - 1);
  }, [page, count]);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["document-areas", docId] });
    void qc.invalidateQueries({ queryKey: ["document", docId] });
    void qc.invalidateQueries({ queryKey: ["documents"] });
  };
  const add = useMutation({
    mutationFn: (b: Box & { page: number }) =>
      api<Area>(`${base}/areas`, { method: "POST", body: JSON.stringify(b) }),
    onSuccess: () => {
      setToast({ message: "Area ditambahkan", kind: "info" });
      refresh();
    },
    onError: (e) => setToast({ message: msg(e), kind: "error" }),
  });
  const del = useMutation({
    mutationFn: (id: string) =>
      api(`${base}/areas/${encodeURIComponent(id)}`, { method: "DELETE" }),
    onSuccess: () => {
      setToast({ message: "Area dihapus", kind: "info" });
      refresh();
    },
    onError: (e) => setToast({ message: msg(e), kind: "error" }),
  });
  const busy = add.isPending || del.isPending;

  if (!isPdf) return null;

  const all = areasQ.data ?? [];
  const onPage = all.filter((a) => a.page === page);

  function point(e: RPointerEvent<HTMLDivElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top, w: r.width, h: r.height };
  }
  function onDown(e: RPointerEvent<HTMLDivElement>) {
    if (busy || e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const p = point(e);
    setDrag({ id: e.pointerId, ax: p.x, ay: p.y, bx: p.x, by: p.y });
  }
  function onMove(e: RPointerEvent<HTMLDivElement>) {
    if (!drag || e.pointerId !== drag.id) return;
    const p = point(e);
    setDrag({ ...drag, bx: p.x, by: p.y });
  }
  function onUp(e: RPointerEvent<HTMLDivElement>) {
    if (!drag || e.pointerId !== drag.id) return;
    const p = point(e);
    setDrag(null);
    if (e.currentTarget.hasPointerCapture?.(e.pointerId))
      e.currentTarget.releasePointerCapture(e.pointerId);
    const box = normalizeBox(drag.ax, drag.ay, p.x, p.y, p.w, p.h);
    if (box) add.mutate({ page, ...box });
  }
  function onCancel() {
    setDrag(null);
  }

  let preview: Box | null = null;
  if (drag && surfaceRef.current) {
    const r = surfaceRef.current.getBoundingClientRect();
    preview = normalizeBox(drag.ax, drag.ay, drag.bx, drag.by, r.width, r.height);
  }

  return (
    <div className="page-areas">
      <div className="page-view">
        <div className="row page-nav">
          <Button aria-label="Halaman sebelumnya" disabled={page <= 0} onClick={() => setPage(page - 1)}>
            ◀
          </Button>
          <span aria-live="polite">
            {page + 1} / {count}
          </span>
          <Button aria-label="Halaman berikutnya" disabled={page >= count - 1} onClick={() => setPage(page + 1)}>
            ▶
          </Button>
        </div>
        <div className="page-canvas">
          <img
            src={`/api${base}/pages/${page}.png`}
            alt={`Halaman ${page + 1}`}
            draggable={false}
          />
          {onPage.map((a) => (
            <BoxEl key={a.id} box={a} className="area-box" />
          ))}
          {preview && <BoxEl box={preview} className="area-box preview" testId="draw-preview" />}
          {canEdit && (
            <div
              ref={surfaceRef}
              className="draw-surface"
              data-testid="draw-surface"
              onPointerDown={onDown}
              onPointerMove={onMove}
              onPointerUp={onUp}
              onPointerCancel={onCancel}
            />
          )}
        </div>
      </div>
      <div className="find">
        {canEdit && <p className="muted">Seret di atas halaman untuk menutup area (mis. tanda tangan, foto, stempel).</p>}
        {canEdit && status === "disetujui" && (
          <p className="notice">Mengubah area membatalkan persetujuan.</p>
        )}
        {areasQ.isError && (
          <p className="notice error" role="alert">
            {msg(areasQ.error)}
          </p>
        )}
        {all.length === 0 ? (
          <p className="muted">Belum ada area.</p>
        ) : (
          <ol className="area-list" aria-label="Daftar area">
            {all.map((a, i) => (
              <li key={a.id} className={a.page === page ? "current" : undefined}>
                <button type="button" className="link" onClick={() => setPage(a.page)}>
                  Area {i + 1} · Halaman {a.page + 1}
                </button>
                {canEdit && (
                  <Button
                    disabled={busy}
                    aria-label={`Hapus area ${i + 1}, halaman ${a.page + 1}`}
                    onClick={() => del.mutate(a.id)}
                  >
                    Hapus
                  </Button>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>
      <Toast message={toast?.message ?? null} kind={toast?.kind} onClose={() => setToast(null)} />
    </div>
  );
}
