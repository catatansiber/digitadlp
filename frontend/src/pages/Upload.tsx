import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import { uploadDocument } from "../api/upload";
import { Dropzone } from "../components/Dropzone";

export const MAX_UPLOAD = 50 * 1024 * 1024;
// Pesan sama persis dengan backend/digitadlp/app/workflow.py
export const MSG_EXT = "Format file tidak didukung. Gunakan PDF atau DOCX.";
export const MSG_SIZE = "Ukuran file melebihi batas 50 MB.";
export const MSG_EMPTY = "File kosong.";

export function validateFile(f: File): string | null {
  const ext = /\.([^.]+)$/.exec(f.name)?.[1].toLowerCase();
  if (ext !== "pdf" && ext !== "docx") return MSG_EXT;
  if (f.size > MAX_UPLOAD) return MSG_SIZE;
  if (f.size === 0) return MSG_EMPTY;
  return null;
}

export function Upload() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);

  async function onFile(f: File) {
    const bad = validateFile(f);
    if (bad) {
      setError(bad);
      return;
    }
    setError(null);
    setProgress(0);
    try {
      const doc = await uploadDocument<{ id: string }>(f, setProgress);
      void qc.invalidateQueries({ queryKey: ["documents"] });
      nav(`/dokumen/${doc.id}`);
    } catch (e) {
      setProgress(null);
      setError(e instanceof ApiError ? e.detail : "Terjadi kesalahan. Coba lagi.");
    }
  }

  return (
    <section className="page">
      <h1>Unggah dokumen</h1>
      <Dropzone onFile={(f) => void onFile(f)} disabled={progress !== null} />
      {progress !== null && (
        <div className="progress-wrap">
          <progress max={100} value={Math.round(progress * 100)} aria-label="Progres unggah" />
          <span className="muted">{Math.round(progress * 100)}%</span>
        </div>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      <p className="notice">
        Setelah upload, sistem membaca dokumen, mencari data pribadi, lalu memberi saran label. Proses berjalan di
        latar belakang.
      </p>
    </section>
  );
}
