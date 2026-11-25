import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Button } from "../../components/Button";
import { Table } from "../../components/Table";
import { Toast } from "../../components/Toast";
import { errText, isAuthError, type Unit } from "./common";

export function Units() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["admin", "units"], queryFn: () => api<Unit[]>("/admin/units") });
  const create = useMutation({
    mutationFn: (n: string) => api<Unit>("/admin/units", { method: "POST", body: JSON.stringify({ name: n }) }),
    onSuccess: () => {
      setName("");
      void qc.invalidateQueries({ queryKey: ["admin", "units"] });
    },
    onError: (e) => {
      if (!isAuthError(e)) setError(errText(e));
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const n = name.trim();
    if (!n) return setError("Nama unit kerja wajib diisi.");
    setError(null);
    create.mutate(n);
  }

  return (
    <section className="page">
      <h1>Unit kerja</h1>
      <form className="row form" onSubmit={submit}>
        <label className="field grow">
          Nama unit
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
        </label>
        <Button type="submit" variant="primary" disabled={create.isPending}>
          Tambah unit
        </Button>
      </form>
      {q.isLoading ? (
        <p className="loading">Memuat…</p>
      ) : q.isError ? (
        <p className="notice error" role="alert">
          {errText(q.error)}
        </p>
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Nama unit</th>
            </tr>
          </thead>
          <tbody>
            {q.data?.map((u) => (
              <tr key={u.id}>
                <td>{u.name}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      <Toast message={error} kind="error" onClose={() => setError(null)} />
    </section>
  );
}
