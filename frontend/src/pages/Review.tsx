import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, FALLBACK_MESSAGE } from "../api/client";
import { uploadDocument } from "../api/upload";
import { useAuth } from "../auth/AuthProvider";
import { Button } from "../components/Button";
import { DocText } from "../components/DocText";
import { FindingList, type Finding } from "../components/FindingList";
import { LabelChip, StatusChip } from "../components/StatusChip";
import { Toast } from "../components/Toast";
import { STRONG_KINDS } from "../lib/highlight";
import { KIND_TEXT, LABEL_TEXT, type LabelValue } from "../lib/labels";
import { validateFile } from "./Upload";

export const MAX_REASON = 200; // sama dengan backend workflow.MAX_REASON
export const MSG_SELF =
  "Pemeriksa tidak boleh menyetujui dokumen yang ia upload sendiri.";

type DocDetail = {
  id: string;
  title: string;
  ext: string;
  status: string;
  owner_id: string;
  label: string | null;
  suggested_label: string | null;
  owner_name: string | null;
  unit_name: string | null;
  revision: number;
  return_reason?: string | null;
  findings?: unknown[];
};

const POLL = new Set(["diproses", "membuat_versi"]);

/** findings dari server berupa daftar per halaman; terima juga bentuk datar. */
function flatten(raw: unknown[] | undefined): Finding[] {
  if (!raw) return [];
  return raw
    .flatMap((x) => (Array.isArray(x) ? x : [x]))
    .filter(
      (f): f is Finding =>
        !!f && typeof f === "object" && typeof (f as Finding).text === "string",
    );
}

function suggestionReason(findings: Finding[], label: string | null): string {
  const counts = new Map<string, number>();
  for (const f of findings)
    if (STRONG_KINDS.has(f.kind))
      counts.set(f.kind, (counts.get(f.kind) ?? 0) + 1);
  const target =
    label && label in LABEL_TEXT ? LABEL_TEXT[label as LabelValue] : "-";
  if (counts.size === 0) return `Tidak ada data identitas kuat → ${target}`;
  const parts = [...counts].map(([k, n]) => `${n} ${KIND_TEXT[k] ?? k}`);
  return `Ada ${parts.join(", ")} → ${target}`;
}

const msg = (e: unknown) =>
  e instanceof ApiError ? e.detail : FALLBACK_MESSAGE;

export function Review() {
  const { id = "" } = useParams();
  const { user } = useAuth();
  const qc = useQueryClient();
  const [toast, setToast] = useState<{
    message: string;
    kind: "info" | "error";
  } | null>(null);
  const [manual, setManual] = useState<{
    kind: string;
    text: string;
    page: string;
  } | null>(null);
  const [reason, setReason] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["document", id],
    queryFn: () => api<DocDetail>(`/documents/${encodeURIComponent(id)}`),
    refetchInterval: (qq) =>
      qq.state.data && POLL.has(qq.state.data.status) ? 3000 : false,
  });
  const doc = q.data;
  const allowed = !!doc && Array.isArray(doc.findings);
  const t = useQuery({
    queryKey: ["document-text", id, doc?.revision],
    queryFn: () =>
      api<{ pages: string[] }>(`/documents/${encodeURIComponent(id)}/text`),
    enabled: allowed && doc?.status !== "diproses",
    staleTime: Infinity,
  });

  const path = `/documents/${encodeURIComponent(id)}`;
  const act = useMutation({
    mutationFn: (a: {
      name: string;
      run: () => Promise<unknown>;
      done: string;
    }) => a.run(),
    onSuccess: (_r, a) => {
      setToast({ message: a.done, kind: "info" });
      setManual(null);
      setReason(null);
      void qc.invalidateQueries({ queryKey: ["document", id] });
      void qc.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (e) => setToast({ message: msg(e), kind: "error" }),
  });
  const busy = act.isPending;
  const pending = (name: string) => busy && act.variables?.name === name;
  const post = (sub: string, body?: unknown) => () =>
    api(`${path}/${sub}`, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    });

  if (q.isLoading || q.isError || !doc)
    return (
      <section className="page">
        <h1>Cek temuan</h1>
        {q.isLoading ? (
          <p className="loading">Memuat…</p>
        ) : (
          <p className="notice error" role="alert">
            {msg(q.error)}
          </p>
        )}
      </section>
    );

  const findings = flatten(doc.findings);
  const isReviewer = user?.role === "pemeriksa";
  const canAct = isReviewer && doc.status === "menunggu_cek";
  const canEdit =
    isReviewer && (doc.status === "menunggu_cek" || doc.status === "disetujui");
  // Temuan DOCX disimpan server sebagai satu halaman (indeks 0); /text memecah per paragraf.
  const isDocx = doc.ext === "docx";
  const self = doc.owner_id === user?.id;
  const pageCount =
    t.data?.pages.length ?? Math.max(1, (doc.findings ?? []).length);

  function openManual() {
    const sel = window.getSelection()?.toString().trim().slice(0, 200) ?? "";
    setManual({ kind: "NAME_CITIZEN", text: sel, page: "1" });
  }

  function onReupload(f: File) {
    const bad = validateFile(f);
    if (bad) return setToast({ message: bad, kind: "error" });
    act.mutate({
      name: "reupload",
      run: () => uploadDocument(f, undefined, undefined, `${path}/reupload`),
      done: "Dokumen diunggah ulang.",
    });
  }

  const reasonTooLong = (reason ?? "").length > MAX_REASON;

  return (
    <section className="page">
      <h1>Cek temuan</h1>
      <div className="row between">
        <h2 className="doc-title">{doc.title}</h2>
        <span className="row">
          <StatusChip status={doc.status} />
          <LabelChip label={doc.label ?? doc.suggested_label} />
        </span>
      </div>
      <p className="muted">
        {doc.owner_name ?? "-"} · {doc.unit_name ?? "-"} · revisi {doc.revision}
      </p>

      {doc.status === "dikembalikan" && (
        <div className="notice error">
          <b>Dikembalikan ke pengunggah.</b>{" "}
          {doc.return_reason && <span>{doc.return_reason}</span>}
          {self && (
            <div className="row">
              <label className="btn primary">
                {pending("reupload") ? "Mengunggah…" : "Upload ulang"}
                <input
                  type="file"
                  accept=".pdf,.docx"
                  aria-label="Upload ulang"
                  className="visually-hidden"
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (f) onReupload(f);
                  }}
                />
              </label>
            </div>
          )}
        </div>
      )}
      {doc.status === "membuat_versi" && (
        <p className="notice">Versi sedang dibuat…</p>
      )}
      {(doc.status === "disetujui" || doc.status === "dirilis") && (
        <Link
          className="btn primary"
          to={`/dokumen/${encodeURIComponent(doc.id)}/versi`}
        >
          Lihat tiga versi
        </Link>
      )}

      {allowed && (
        <div className="split">
          {t.data ? (
            <DocText pages={t.data.pages} marks={findings} />
          ) : (
            <div className="doc muted">
              {doc.status === "diproses"
                ? "Dokumen masih diproses…"
                : t.isError
                  ? msg(t.error)
                  : "Memuat teks…"}
            </div>
          )}
          <div className="find">
            <div className="suggest">
              <b>
                Saran label:{" "}
                {doc.suggested_label
                  ? (LABEL_TEXT[doc.suggested_label as LabelValue] ??
                    doc.suggested_label)
                  : "-"}
              </b>
              <span>{suggestionReason(findings, doc.suggested_label)}</span>
              {canAct && (
                <label className="inline">
                  Label
                  <select
                    value={doc.label ?? doc.suggested_label ?? ""}
                    disabled={busy}
                    onChange={(e) => {
                      const label = e.target.value;
                      act.mutate({
                        name: "label",
                        run: () =>
                          api(`${path}/label`, {
                            method: "PUT",
                            body: JSON.stringify({ label }),
                          }),
                        done: "Label diubah",
                      });
                    }}
                  >
                    <option value="" disabled>
                      Pilih label
                    </option>
                    {Object.entries(LABEL_TEXT).map(([v, txt]) => (
                      <option key={v} value={v}>
                        {txt}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>

            <FindingList
              findings={findings}
              busy={busy}
              onIgnore={
                canEdit
                  ? (f) =>
                      act.mutate({
                        name: "ignore",
                        run: post("corrections", {
                          op: "abaikan",
                          kind: f.kind,
                          text: f.text,
                          page: f.page,
                        }),
                        done: "Temuan diabaikan",
                      })
                  : undefined
              }
            />

            {canEdit && (
              <>
                {doc.status === "disetujui" && (
                  <p className="notice">
                    Mengubah temuan membatalkan persetujuan.
                  </p>
                )}
                {manual ? (
                  <form
                    className="manual"
                    onSubmit={(e) => {
                      e.preventDefault();
                      act.mutate({
                        name: "add",
                        run: post("corrections", {
                          op: "tambah",
                          kind: manual.kind,
                          text: manual.text,
                          page: isDocx ? 0 : Number(manual.page) - 1,
                        }),
                        done: "Temuan ditambahkan",
                      });
                    }}
                  >
                    <label className="field">
                      Jenis
                      <select
                        value={manual.kind}
                        onChange={(e) =>
                          setManual({ ...manual, kind: e.target.value })
                        }
                      >
                        {Object.entries(KIND_TEXT).map(([v, txt]) => (
                          <option key={v} value={v}>
                            {txt}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field">
                      Teks
                      <input
                        value={manual.text}
                        maxLength={200}
                        onChange={(e) =>
                          setManual({ ...manual, text: e.target.value })
                        }
                      />
                    </label>
                    {!isDocx && (
                      <label className="field">
                        Halaman
                        <input
                          type="number"
                          min={1}
                          max={pageCount}
                          value={manual.page}
                          onChange={(e) =>
                            setManual({ ...manual, page: e.target.value })
                          }
                        />
                      </label>
                    )}
                    <div className="row">
                      <Button
                        type="submit"
                        variant="primary"
                        disabled={busy || !manual.text.trim()}
                      >
                        {pending("add") ? "Menyimpan…" : "Simpan temuan"}
                      </Button>
                      <Button onClick={() => setManual(null)}>Batal</Button>
                    </div>
                  </form>
                ) : (
                  <div className="row">
                    {/* onMouseDown mencegah seleksi teks hilang sebelum dibaca */}
                    <Button
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={openManual}
                    >
                      + Tandai manual
                    </Button>
                  </div>
                )}

                {canAct && (
                  <div className="row">
                    <Button
                      variant="primary"
                      disabled={busy || self}
                      title={self ? MSG_SELF : undefined}
                      onClick={() =>
                        act.mutate({
                          name: "approve",
                          run: post("approve"),
                          done: "Disetujui. Versi sedang dibuat.",
                        })
                      }
                    >
                      {pending("approve")
                        ? "Memproses…"
                        : "Setujui & buat versi"}
                    </Button>
                    <Button disabled={busy} onClick={() => setReason("")}>
                      Kembalikan ke pengunggah
                    </Button>
                  </div>
                )}
                {canAct && self && <p className="muted">{MSG_SELF}</p>}

                {reason !== null && (
                  <div
                    role="dialog"
                    aria-label="Kembalikan ke pengunggah"
                    className="dialog"
                  >
                    <label className="field">
                      Alasan
                      <textarea
                        value={reason}
                        rows={3}
                        onChange={(e) => setReason(e.target.value)}
                      />
                    </label>
                    <span className={reasonTooLong ? "notice error" : "muted"}>
                      {reason.length}/{MAX_REASON} (maksimal {MAX_REASON}{" "}
                      karakter)
                    </span>
                    <div className="row">
                      <Button
                        variant="danger"
                        disabled={busy || !reason.trim() || reasonTooLong}
                        onClick={() =>
                          act.mutate({
                            name: "return",
                            run: post("return", { reason }),
                            done: "Dokumen dikembalikan",
                          })
                        }
                      >
                        {pending("return") ? "Mengirim…" : "Kirim"}
                      </Button>
                      <Button onClick={() => setReason(null)}>Batal</Button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
      <Toast
        message={toast?.message ?? null}
        kind={toast?.kind}
        onClose={() => setToast(null)}
      />
    </section>
  );
}
