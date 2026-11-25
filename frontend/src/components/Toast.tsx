import { useEffect } from "react";

type Props = { message: string | null; kind?: "info" | "error"; onClose?: () => void; timeoutMs?: number };

export function Toast({ message, kind = "info", onClose, timeoutMs = 5000 }: Props) {
  useEffect(() => {
    if (!message || !onClose) return;
    const t = setTimeout(onClose, timeoutMs);
    return () => clearTimeout(t);
  }, [message, onClose, timeoutMs]);
  if (!message) return null;
  return (
    <div className={`toast ${kind}`} role={kind === "error" ? "alert" : "status"}>
      <span>{message}</span>
      {onClose && (
        <button type="button" className="toast-close" aria-label="Tutup" onClick={onClose}>
          ×
        </button>
      )}
    </div>
  );
}
