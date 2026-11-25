export type LabelValue = "publik" | "internal" | "rahasia";
export type StatusValue =
  | "diproses" | "menunggu_cek" | "dikembalikan" | "membuat_versi" | "disetujui" | "dirilis" | "gagal";

export const LABEL_TEXT: Record<LabelValue, string> = { publik: "Publik", internal: "Internal", rahasia: "Rahasia" };

export const STATUS_TEXT: Record<StatusValue, string> = {
  diproses: "Diproses",
  menunggu_cek: "Menunggu cek",
  dikembalikan: "Dikembalikan",
  membuat_versi: "Membuat versi…",
  disetujui: "Disetujui",
  dirilis: "Dirilis",
  gagal: "Gagal diproses",
};

export const KIND_TEXT: Record<string, string> = {
  NIK: "NIK",
  KK: "No. KK",
  NPWP: "NPWP",
  PHONE: "No. HP",
  EMAIL: "Email",
  ACCOUNT: "No. rekening",
  NAME_CITIZEN: "Nama warga",
  NAME_EMPLOYEE: "Nama pegawai",
  NIP: "NIP",
  ADDRESS: "Alamat",
  BIRTHDATE: "Tanggal lahir",
};

const dateFmt = new Intl.DateTimeFormat("id-ID", { dateStyle: "medium", timeStyle: "short" });
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "-" : dateFmt.format(d);
}
