import { Chip } from "./Chip";
import { LABEL_TEXT, STATUS_TEXT, type LabelValue, type StatusValue } from "../lib/labels";

const LABEL_TONE: Record<LabelValue, "pub" | "int" | "rah"> = { publik: "pub", internal: "int", rahasia: "rah" };
const STATUS_TONE: Record<StatusValue, "pub" | "int" | "rah" | "neu"> = {
  diproses: "neu", menunggu_cek: "int", dikembalikan: "rah", membuat_versi: "neu",
  disetujui: "pub", dirilis: "pub", gagal: "rah",
};

export function LabelChip({ label }: { label: string | null | undefined }) {
  if (!label || !(label in LABEL_TEXT)) return <span className="muted">-</span>;
  return <Chip tone={LABEL_TONE[label as LabelValue]}>{LABEL_TEXT[label as LabelValue]}</Chip>;
}

export function StatusChip({ status }: { status: string }) {
  if (!(status in STATUS_TEXT)) return <Chip tone="neu">{status}</Chip>;
  return <Chip tone={STATUS_TONE[status as StatusValue]}>{STATUS_TEXT[status as StatusValue]}</Chip>;
}
