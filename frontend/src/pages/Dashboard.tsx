import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useDocuments } from "../api/hooks";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState } from "../components/EmptyState";
import { LabelChip, StatusChip } from "../components/StatusChip";
import { Table } from "../components/Table";
import { STATUS_TEXT, formatDate } from "../lib/labels";

const KPI: [string, string][] = [
  ["Menunggu cek", "menunggu_cek"],
  ["Disetujui", "disetujui"],
  ["Dirilis", "dirilis"],
  ["Gagal", "gagal"],
];

export function Dashboard() {
  const { user } = useAuth();
  const nav = useNavigate();
  const [status, setStatus] = useState("");
  const [mine, setMine] = useState(false);
  const q = useDocuments({ status: status || undefined, mine });
  const docs = q.data ?? [];
  const canUpload = user?.role === "pengunggah" || user?.role === "pemeriksa";

  return (
    <section className="page">
      <div className="row between">
        <h1>Beranda</h1>
        {canUpload && (
          <Link className="btn primary" to="/upload">
            + Upload dokumen
          </Link>
        )}
      </div>
      <div className="kpi" aria-label="Ringkasan">
        {KPI.map(([label, st]) => (
          <div key={st}>
            <span className="muted">{label}</span>
            <b>{docs.filter((d) => d.status === st).length}</b>
          </div>
        ))}
      </div>
      <div className="row filters">
        <label className="inline">
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Semua</option>
            {Object.entries(STATUS_TEXT).map(([v, t]) => (
              <option key={v} value={v}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="inline">
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />
          Hanya milik saya
        </label>
      </div>
      {q.isError ? (
        <p className="notice error" role="alert">
          {(q.error as { detail?: string }).detail ?? "Terjadi kesalahan. Coba lagi."}
        </p>
      ) : q.isLoading ? (
        <p className="loading">Memuat…</p>
      ) : docs.length === 0 ? (
        <EmptyState>Belum ada dokumen. Upload dokumen pertama.</EmptyState>
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Dokumen</th>
              <th>Saran label</th>
              <th>Status</th>
              <th>Pemilik</th>
              <th>Unit</th>
              <th>Tanggal</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.id} className="click" onClick={() => nav(`/dokumen/${d.id}`)}>
                <td>
                  <Link to={`/dokumen/${d.id}`} onClick={(e) => e.stopPropagation()}>
                    {d.title}
                  </Link>
                </td>
                <td>
                  <LabelChip label={d.suggested_label} />
                </td>
                <td>
                  <StatusChip status={d.status} />
                </td>
                <td>{d.owner_name ?? "-"}</td>
                <td>{d.unit_name ?? "-"}</td>
                <td>{formatDate(d.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </section>
  );
}
