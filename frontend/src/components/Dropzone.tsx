import { useRef, useState } from "react";

type Props = { onFile: (f: File) => void; disabled?: boolean };

export function Dropzone({ onFile, disabled }: Props) {
  const ref = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div
      className={`drop${over ? " over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const f = e.dataTransfer.files?.[0];
        if (f && !disabled) onFile(f);
      }}
    >
      <strong>Seret file ke sini atau pilih file</strong>
      <span>PDF (teks atau hasil scan) dan DOCX · maks. 50 MB</span>
      <label className="btn primary pick">
        Pilih file
        <input
          ref={ref}
          type="file"
          accept=".pdf,.docx"
          disabled={disabled}
          className="visually-hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) onFile(f);
          }}
        />
      </label>
      <span className="mono">File diproses di server instansi. Tidak dikirim ke layanan luar.</span>
    </div>
  );
}
