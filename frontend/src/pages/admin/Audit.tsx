import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Table } from "../../components/Table";
import { formatDate } from "../../lib/labels";
import { errText } from "./common";

type Event = {
  id: number;
  at: string;
  actor_id: string | null;
  actor_name?: string | null;
  action: string;
  document_id: string | null;
  detail: string;
};

export const ACTION_TEXT: Record<string, string> = {
  masuk: "Masuk",
  gagal_masuk: "Gagal masuk",
  keluar: "Keluar",
  upload: "Unggah dokumen",
  deteksi_selesai: "Deteksi selesai",
  ubah_label: "Ubah label",
  koreksi: "Koreksi temuan",
  setujui: "Setujui",
  kembalikan: "Kembalikan",
  rilis: "Rilis versi Publik",
  unduh: "Unduh versi",
  akses_ditolak: "Akses ditolak",
  user_dibuat: "Pengguna dibuat",
  user_diubah: "Pengguna diubah",
  impor_pegawai: "Impor daftar pegawai",
  aturan_label: "Ubah aturan label",
  unit_dibuat: "Unit dibuat",
};

const short = (id: string | null) => (id ? id.slice(0, 8) : "-");

export function Audit() {
  const [doc, setDoc] = useState("");
  const [actor, setActor] = useState("");
  const [limit, setLimit] = useState("100");
  const d = doc.trim();
  const a = actor.trim();
  const q = useQuery({
    queryKey: ["admin", "audit", d, a, limit],
    queryFn: () => {
      const p = new URLSearchParams();
      if (d) p.set("document_id", d);
      if (a) p.set("actor_id", a);
      p.set("limit", limit);
      return api<Event[]>("/admin/audit?" + p.toString());
    },
  });

  return (
    <section className="page">
      <h1>Audit</h1>
      <div className="row filters">
        <label className="inline">
          Dokumen
          <input value={doc} onChange={(e) => setDoc(e.target.value)} placeholder="ID dokumen" />
        </label>
        <label className="inline">
          Pengguna
          <input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="ID pengguna" />
        </label>
        <label className="inline">
          Batas
          <select value={limit} onChange={(e) => setLimit(e.target.value)}>
            {["100", "200", "500"].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>
      {q.isError ? (
        <p className="notice error" role="alert">
          {errText(q.error)}
        </p>
      ) : q.isLoading ? (
        <p className="loading">Memuat…</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Waktu</th>
              <th>Pengguna</th>
              <th>Aksi</th>
              <th>Dokumen</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {q.data?.map((e) => (
              <tr key={e.id}>
                <td>{formatDate(e.at)}</td>
                <td>{e.actor_name || short(e.actor_id)}</td>
                <td>{ACTION_TEXT[e.action] ?? e.action}</td>
                <td>{short(e.document_id)}</td>
                <td className="wrap">{e.detail}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </section>
  );
}
