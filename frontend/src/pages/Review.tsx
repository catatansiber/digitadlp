import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, FALLBACK_MESSAGE } from "../api/client";
import { uploadDocument } from "../api/upload";
import { useAuth } from "../auth/AuthProvider";
import { Button } from "../components/Button";
import { DocText } from "../components/DocText";
import { FindingList, type Finding } from "../components/FindingList";
import { PageAreas } from "../components/PageAreas";
import { LabelChip, StatusChip } from "../components/StatusChip";
import { Toast } from "../components/Toast";
import { STRONG_KINDS } from "../lib/highlight";
import { KIND_TEXT, LABEL_TEXT, type LabelValue } from "../lib/labels";
import { validateFile } from "./Upload";

export const MSG_REUPLOAD =
  "Unggah ulang akan menghapus temuan dan koreksi dokumen ini. Lanjutkan?";
export const MSG_NAME_HELP =
  "Nama tidak dideteksi otomatis. Tandai nama orang yang perlu disensor; semua kemunculan yang sama ikut tersensor.";

/** Jenis yang bisa dipilih pada "Tandai manual": nama orang dulu, tanpa NAME_EMPLOYEE (hanya data lama). */
const MANUAL_KINDS = [
  "NAME_CITIZEN",
  ...Object.keys(KIND_TEXT).filter(
    (k) => k !== "NAME_CITIZEN" && k !== "NAME_EMPLOYEE",
  ),
];

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
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [tab, setTab] = useState<"teks" | "halaman">("teks");

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
      setPendingFile(null);
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
  const isOwner = !!user && doc.owner_id === user.id;
  const canAct = isOwner && doc.status === "menunggu_cek";
  const canEdit =
    isOwner && (doc.status === "menunggu_cek" || doc.status === "disetujui");
  const canReupload =
    isOwner && (doc.status === "menunggu_cek" || doc.status === "gagal");
  // Temuan DOCX disimpan server sebagai satu halaman (indeks 0); /text memecah per paragraf.
  const isDocx = doc.ext === "docx";
  const pageCount =
    t.data?.pages.length ?? Math.max(1, (doc.findings ?? []).length);

  function openManual() {
    const sel = window.getSelection()?.toString().trim().slice(0, 200) ?? "";
    setManual({ kind: "NAME_CITIZEN", text: sel, page: "1" });
  }

  function pickReupload(f: File) {
    const bad = validateFile(f);
    if (bad) return setToast({ message: bad, kind: "error" });
    setPendingFile(f);
  }

  function doReupload(f: File) {
    act.mutate({
      name: "reupload",
      run: () => uploadDocument(f, undefined, undefined, `${path}/reupload`),
      done: "Dokumen diunggah ulang.",
    });
  }

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

      {canReupload && (
        <div className="row">
          <label className="btn">
            {pending("reupload") ? "Mengunggah…" : "Unggah ulang"}
            <input
              type="file"
              accept=".pdf,.docx"
              aria-label="Unggah ulang"
              className="visually-hidden"
              disabled={busy}
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) pickReupload(f);
              }}
            />
          </label>
        </div>
      )}
      {pendingFile && (
        <div role="dialog" aria-label="Unggah ulang" className="dialog">
          <p>{MSG_REUPLOAD}</p>
          <div className="row">
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => doReupload(pendingFile)}
            >
              Lanjutkan
            </Button>
            <Button disabled={busy} onClick={() => setPendingFile(null)}>
              Batal
            </Button>
          </div>
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

      {allowed && !isDocx && (
        <div className="seg" role="tablist" aria-label="Tampilan dokumen">
          <button
            type="button"
            role="tab"
            id="tab-teks"
            aria-selected={tab === "teks"}
            aria-controls="panel-dok"
            className={tab === "teks" ? "active" : undefined}
            onClick={() => setTab("teks")}
          >
            Teks
          </button>
          <button
            type="button"
            role="tab"
            id="tab-halaman"
            aria-selected={tab === "halaman"}
            aria-controls="panel-dok"
            className={tab === "halaman" ? "active" : undefined}
            onClick={() => setTab("halaman")}
          >
            Halaman
          </button>
        </div>
      )}
      {allowed && !isDocx && tab === "halaman" && (
        <div role="tabpanel" id="panel-dok" aria-labelledby="tab-halaman">
          <PageAreas
            docId={doc.id}
            ext={doc.ext}
            pageCount={pageCount}
            canEdit={canEdit}
            status={doc.status}
          />
        </div>
      )}
      {allowed && (isDocx || tab === "teks") && (
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
                    <p className="muted">{MSG_NAME_HELP}</p>
                    <label className="field">
                      Jenis
                      <select
                        value={manual.kind}
                        onChange={(e) =>
                          setManual({ ...manual, kind: e.target.value })
                        }
                      >
                        {MANUAL_KINDS.map((v) => (
                          <option key={v} value={v}>
                            {KIND_TEXT[v]}
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
                      disabled={busy}
                      onClick={() =>
                        act.mutate({
                          name: "approve",
                          run: post("approve"),
                          done: "Disetujui. Versi sedang dibuat.",
                        })
                      }
                    >
                      {pending("approve") ? "Memproses…" : "Buat versi"}
                    </Button>
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
