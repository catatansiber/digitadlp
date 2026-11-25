import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthProvider";
import { Button } from "../../components/Button";
import { Table } from "../../components/Table";
import { Toast } from "../../components/Toast";
import { errText, isAuthError, MIN_PASSWORD, MSG_PASSWORD, type AdminUser, type Unit } from "./common";

const ROLES: { value: AdminUser["role"]; text: string }[] = [
  { value: "pengunggah", text: "Pengunggah" },
  { value: "pemeriksa", text: "Pemeriksa" },
  { value: "admin", text: "Admin" },
];

type Patch = Partial<{ role: string; unit_id: string; active: boolean; password: string }>;

export function Users() {
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const [toast, setToast] = useState<{ message: string; kind: "info" | "error" } | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [resetFor, setResetFor] = useState<AdminUser | null>(null);

  const users = useQuery({ queryKey: ["admin", "users"], queryFn: () => api<AdminUser[]>("/admin/users") });
  const units = useQuery({ queryKey: ["admin", "units"], queryFn: () => api<Unit[]>("/admin/units") });

  const refresh = () => void qc.invalidateQueries({ queryKey: ["admin", "users"] });
  const fail = (e: unknown) => {
    if (!isAuthError(e)) setToast({ message: errText(e), kind: "error" });
  };

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Patch }) =>
      api<AdminUser>(`/admin/users/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: refresh,
    // Daftar dimuat ulang juga saat gagal agar pilihan kembali ke nilai server.
    onError: (e) => {
      fail(e);
      refresh();
    },
  });

  const create = useMutation({
    mutationFn: (body: Record<string, string>) =>
      api<AdminUser>("/admin/users", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      setToast({ message: "Pengguna ditambahkan.", kind: "info" });
      refresh();
    },
    onError: (e) => {
      if (!isAuthError(e)) setFormError(errText(e));
    },
  });

  const [f, setF] = useState({ username: "", full_name: "", role: "pengunggah", unit_id: "", password: "" });
  const unitId = f.unit_id || units.data?.[0]?.id || "";

  function submit(e: FormEvent) {
    e.preventDefault();
    if (f.password.length < MIN_PASSWORD) return setFormError(MSG_PASSWORD);
    if (!unitId) return setFormError("Unit kerja tidak ditemukan.");
    setFormError(null);
    create.mutate({ username: f.username, full_name: f.full_name, role: f.role, unit_id: unitId, password: f.password });
    // Kata sandi tidak disimpan di state setelah dikirim.
    setF((s) => ({ ...s, username: "", full_name: "", password: "" }));
  }

  return (
    <section className="page">
      <h1>Pengguna</h1>
      <form className="form-grid" onSubmit={submit} autoComplete="off">
        <label className="field">
          Nama pengguna
          <input value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} required maxLength={100} autoComplete="off" />
        </label>
        <label className="field">
          Nama lengkap
          <input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} required maxLength={200} autoComplete="off" />
        </label>
        <label className="field">
          Peran
          <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.text}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Unit
          <select value={unitId} onChange={(e) => setF({ ...f, unit_id: e.target.value })}>
            {units.data?.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Kata sandi
          <input type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        </label>
        <div className="row">
          <Button type="submit" variant="primary" disabled={create.isPending}>
            Tambah pengguna
          </Button>
        </div>
        {formError && (
          <p className="notice error full" role="alert">
            {formError}
          </p>
        )}
      </form>

      {users.isLoading ? (
        <p className="loading">Memuat…</p>
      ) : users.isError ? (
        <p className="notice error" role="alert">
          {errText(users.error)}
        </p>
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Nama pengguna</th>
              <th>Nama</th>
              <th>Peran</th>
              <th>Unit</th>
              <th>Aktif</th>
              <th>Tindakan</th>
            </tr>
          </thead>
          <tbody>
            {users.data?.map((u) => {
              const self = me != null && String(me.id) === String(u.id);
              return (
                <tr key={u.id}>
                  <td>{u.username}</td>
                  <td>{u.full_name}</td>
                  <td>
                    <select
                      aria-label={`Peran ${u.username}`}
                      value={u.role}
                      disabled={self || patch.isPending}
                      onChange={(e) => patch.mutate({ id: u.id, body: { role: e.target.value } })}
                    >
                      {ROLES.map((r) => (
                        <option key={r.value} value={r.value}>
                          {r.text}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <select
                      aria-label={`Unit ${u.username}`}
                      value={u.unit_id}
                      disabled={patch.isPending}
                      onChange={(e) => patch.mutate({ id: u.id, body: { unit_id: e.target.value } })}
                    >
                      {units.data?.map((x) => (
                        <option key={x.id} value={x.id}>
                          {x.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>{u.active ? "Ya" : "Tidak"}</td>
                  <td>
                    <div className="row">
                      <Button
                        disabled={(self && u.active) || patch.isPending}
                        onClick={() => patch.mutate({ id: u.id, body: { active: !u.active } })}
                      >
                        {u.active ? "Nonaktifkan" : "Aktifkan"}
                      </Button>
                      <Button onClick={() => setResetFor(u)}>Reset sandi</Button>
                    </div>
                    {self && <p className="muted">Ini akun Anda sendiri: peran tidak bisa diubah dan akun tidak bisa dinonaktifkan.</p>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}

      {resetFor && (
        <ResetDialog
          user={resetFor}
          onClose={() => setResetFor(null)}
          onSubmit={(password) => {
            patch.mutate(
              { id: resetFor.id, body: { password } },
              { onSuccess: () => setToast({ message: `Kata sandi ${resetFor.username} diganti.`, kind: "info" }) },
            );
            setResetFor(null);
          }}
        />
      )}
      <Toast message={toast?.message ?? null} kind={toast?.kind} onClose={() => setToast(null)} />
    </section>
  );
}

function ResetDialog({ user, onClose, onSubmit }: { user: AdminUser; onClose: () => void; onSubmit: (pw: string) => void }) {
  const [pw, setPw] = useState("");
  const [error, setError] = useState<string | null>(null);
  function submit(e: FormEvent) {
    e.preventDefault();
    if (pw.length < MIN_PASSWORD) return setError(MSG_PASSWORD);
    const v = pw;
    setPw("");
    onSubmit(v);
  }
  return (
    <div className="overlay">
      <form className="dialog" role="dialog" aria-modal="true" aria-label={`Reset sandi ${user.username}`} onSubmit={submit}>
        <h2>Reset sandi {user.username}</h2>
        <label className="field">
          Kata sandi baru
          <input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus />
        </label>
        <p className="muted">Semua sesi masuk pengguna ini akan diakhiri.</p>
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
        <div className="row">
          <Button type="submit" variant="primary">
            Simpan sandi
          </Button>
          <Button onClick={onClose}>Batal</Button>
        </div>
      </form>
    </div>
  );
}
