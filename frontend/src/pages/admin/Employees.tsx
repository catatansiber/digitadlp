import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { uploadDocument } from "../../api/upload";
import { errText, isAuthError } from "./common";

type Counts = { names: number; nips: number };

export function Employees() {
  const [error, setError] = useState<string | null>(null);
  const [counts, setCounts] = useState<Counts | null>(null);
  const [busy, setBusy] = useState(false);
  const ac = useRef<AbortController | null>(null);
  useEffect(() => () => ac.current?.abort(), []);
  const m = useMutation({
    mutationFn: (f: File) => {
      ac.current = new AbortController();
      return uploadDocument<Counts>(f, undefined, ac.current.signal, "/admin/employees");
    },
  });

  function onFile(f: File) {
    setError(null);
    setCounts(null);
    setBusy(true);
    m.mutate(f, {
      onSuccess: (c) => {
        setBusy(false);
        setCounts(c);
      },
      onError: (e) => {
        setBusy(false);
        if (!isAuthError(e)) setError(errText(e));
      },
    });
  }

  return (
    <section className="page">
      <h1>Daftar pegawai</h1>
      <p>
        Unggah file <code>.xlsx</code> dengan kolom <code>nama</code> dan <code>nip</code>. Daftar baru menggantikan daftar yang berlaku.
      </p>
      <p className="notice">File disimpan terenkripsi di server. Hanya jumlah baris yang ditampilkan di sini.</p>
      <div className="row">
        <label className="btn primary pick">
          Pilih file xlsx
          <input
            type="file"
            accept=".xlsx"
            disabled={busy}
            className="visually-hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) onFile(f);
            }}
          />
        </label>
        {busy && <span className="loading">Mengunggah…</span>}
      </div>
      {counts && (
        <p className="notice" role="status">
          {counts.names} nama dan {counts.nips} NIP dimuat.
        </p>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
