export type Role = "pengunggah" | "pemeriksa" | "admin";

/** Bentuk respons GET /api/auth/me dan POST /api/auth/login. */
export type Me = {
  id: string;
  full_name: string;
  role: Role;
  unit: string;
};

/** Satu baris GET /api/documents. */
export type DocSummary = {
  id: string;
  title: string;
  ext: string;
  status: import("../lib/labels").StatusValue;
  label: string | null;
  suggested_label: string | null;
  owner_name: string | null;
  unit_name: string | null;
  created_at: string | null;
};
