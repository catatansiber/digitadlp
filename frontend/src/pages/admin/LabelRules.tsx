import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Button } from "../../components/Button";
import { Table } from "../../components/Table";
import { KIND_TEXT, LABEL_TEXT, type LabelValue } from "../../lib/labels";
import { errText, isAuthError } from "./common";

type Rules = Record<string, LabelValue>;

const KINDS = Object.keys(KIND_TEXT);
// Cermin backend default_label_for: kekuatan STRONG -> rahasia, selain itu internal.
const STRONG = new Set(["NIK", "KK", "ACCOUNT", "NPWP"]);
export const DEFAULT_RULES: Rules = Object.fromEntries(KINDS.map((k) => [k, STRONG.has(k) ? "rahasia" : "internal"]));

export function LabelRules() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "label-rules"], queryFn: () => api<Rules>("/admin/label-rules") });
  const [rules, setRules] = useState<Rules | null>(null);
  const [msg, setMsg] = useState<{ text: string; error: boolean } | null>(null);

  useEffect(() => {
    if (q.data) setRules(q.data);
  }, [q.data]);

  const save = useMutation({
    mutationFn: (r: Rules) => api<Rules>("/admin/label-rules", { method: "PUT", body: JSON.stringify(r) }),
    onSuccess: (r) => {
      setRules(r);
      setMsg({ text: "Aturan label disimpan.", error: false });
      void qc.invalidateQueries({ queryKey: ["admin", "label-rules"] });
    },
    onError: (e) => {
      if (!isAuthError(e)) setMsg({ text: errText(e), error: true });
    },
  });

  if (q.isLoading || !rules)
    return (
      <section className="page">
        <h1>Aturan label</h1>
        {q.isError ? (
          <p className="notice error" role="alert">
            {errText(q.error)}
          </p>
        ) : (
          <p className="loading">Memuat…</p>
        )}
      </section>
    );

  return (
    <section className="page">
      <h1>Aturan label</h1>
      <p className="muted">Label yang disarankan untuk dokumen yang memuat jenis data berikut. Label tertinggi menang.</p>
      <Table>
        <thead>
          <tr>
            <th>Jenis data</th>
            <th>Label</th>
          </tr>
        </thead>
        <tbody>
          {KINDS.map((k) => (
            <tr key={k}>
              <td>{KIND_TEXT[k]}</td>
              <td>
                <select
                  aria-label={`Label ${KIND_TEXT[k]}`}
                  value={rules[k] ?? DEFAULT_RULES[k]}
                  onChange={(e) => {
                    setMsg(null);
                    setRules({ ...rules, [k]: e.target.value as LabelValue });
                  }}
                >
                  {(Object.keys(LABEL_TEXT) as LabelValue[]).map((l) => (
                    <option key={l} value={l}>
                      {LABEL_TEXT[l]}
                    </option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      <div className="row">
        <Button
          variant="primary"
          disabled={save.isPending}
          onClick={() => {
            setMsg(null);
            save.mutate(Object.fromEntries(KINDS.map((k) => [k, rules[k] ?? DEFAULT_RULES[k]])) as Rules);
          }}
        >
          Simpan
        </Button>
        <Button
          onClick={() => {
            setMsg(null);
            setRules({ ...DEFAULT_RULES });
          }}
        >
          Kembalikan bawaan
        </Button>
      </div>
      {msg && (
        <p className={`notice${msg.error ? " error" : ""}`} role={msg.error ? "alert" : "status"}>
          {msg.text}
        </p>
      )}
    </section>
  );
}
