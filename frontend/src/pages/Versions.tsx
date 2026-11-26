import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiBlob, ApiError, FALLBACK_MESSAGE } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { Button } from "../components/Button";
import { LabelChip, StatusChip } from "../components/StatusChip";
import { Toast } from "../components/Toast";
import { LABEL_TEXT, STATUS_TEXT, type LabelValue, type StatusValue } from "../lib/labels";

type DocInfo = { id: string; title: string; status: string; owner_id?: string };

const VERSIONS: { key: LabelValue; desc: string }[] = [
  { key: "publik", desc: "Semua data pribadi warga dihapus dari file. Metadata, komentar, dan riwayat revisi dibuang." },
  { key: "internal", desc: "Penyamaran sebagian. NIK, KK, dan rekening tetap tidak utuh." },
  { key: "rahasia", desc: "Dokumen utuh. Hanya unit pemilik. Tiap akses dicatat." },
];

const msg = (e: unknown) => (e instanceof ApiError ? e.detail : FALLBACK_MESSAGE);

function saveBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 0);
}

export function Versions() {
  const { id = "" } = useParams();
  // Keyed by id so blocked/confirm/toast state resets when navigating between documents.
  return <VersionsFor key={id} id={id} />;
}

function VersionsFor({ id }: { id: string }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [toast, setToast] = useState<{ message: string; kind: "info" | "error" } | null>(null);
  const [blocked, setBlocked] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const path = `/documents/${encodeURIComponent(id)}`;

  const q = useQuery({ queryKey: ["document", id], queryFn: () => api<DocInfo>(path) });
  const doc = q.data;

  const download = useMutation({
    mutationFn: async (v: LabelValue) => {
      const { blob, filename } = await apiBlob(`${path}/versions/${v}`);
      saveBlob(blob, filename);
    },
    onError: (e, v) => {
      if (e instanceof ApiError && (e.status === 403 || e.status === 404))
        setBlocked((b) => ({ ...b, [v]: e.detail }));
      else if (!(e instanceof ApiError && e.status === 401)) setToast({ message: msg(e), kind: "error" });
    },
  });

  const release = useMutation({
    mutationFn: () => api(`${path}/release`, { method: "POST" }),
    onSuccess: () => {
      setConfirming(false);
      setToast({ message: "Versi Publik dirilis.", kind: "info" });
      void qc.invalidateQueries({ queryKey: ["document", id] });
      void qc.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (e) => {
      setConfirming(false);
      if (!(e instanceof ApiError && e.status === 401)) setToast({ message: msg(e), kind: "error" });
    },
  });

  if (q.isLoading || q.isError || !doc)
    return (
      <section className="page">
        <h1>Tiga versi</h1>
        {q.isLoading ? (
          <p className="loading">Memuat…</p>
        ) : (
          <p className="notice error" role="alert">
            {msg(q.error)}
          </p>
        )}
      </section>
    );

  const ready = doc.status === "disetujui" || doc.status === "dirilis";
  const canRelease = (user?.role === "admin" || (!!user && doc.owner_id === user.id)) && doc.status === "disetujui";
  const statusText = doc.status in STATUS_TEXT ? STATUS_TEXT[doc.status as StatusValue] : doc.status;

  return (
    <section className="page">
      <h1>Tiga versi</h1>
      <div className="row between">
        <h2 className="doc-title">{doc.title}</h2>
        <StatusChip status={doc.status} />
      </div>

      {!ready ? (
        <>
          <p className="notice">Versi belum tersedia. Dokumen berstatus {statusText}.</p>
          <Link className="btn" to={`/dokumen/${encodeURIComponent(doc.id)}`}>
            Kembali ke cek temuan
          </Link>
        </>
      ) : (
        <>
          <div className="ver">
            {VERSIONS.map(({ key, desc }) => (
              <div key={key} role="group" aria-label={`Versi ${LABEL_TEXT[key]}`} className="box">
                <LabelChip label={key} />
                <span className="muted">{desc}</span>
                {blocked[key] && (
                  <p className="notice error" role="alert">
                    {blocked[key]}
                  </p>
                )}
                <Button
                  variant="primary"
                  disabled={!!blocked[key] || (download.isPending && download.variables === key)}
                  onClick={() => download.mutate(key)}
                >
                  Unduh
                </Button>
              </div>
            ))}
          </div>

          {canRelease && !confirming && (
            <div className="row">
              <Button variant="primary" onClick={() => setConfirming(true)}>
                Rilis versi Publik
              </Button>
            </div>
          )}
          {confirming && (
            <div role="dialog" aria-label="Rilis versi Publik" className="dialog">
              <p>Rilis versi Publik? Tindakan ini dicatat di audit dan tidak dapat dibatalkan.</p>
              <div className="row">
                <Button variant="primary" disabled={release.isPending} onClick={() => release.mutate()}>
                  {release.isPending ? "Merilis…" : "Ya, rilis"}
                </Button>
                <Button disabled={release.isPending} onClick={() => setConfirming(false)}>
                  Batal
                </Button>
              </div>
            </div>
          )}
        </>
      )}
      <Toast message={toast?.message ?? null} kind={toast?.kind} onClose={() => setToast(null)} />
    </section>
  );
}
