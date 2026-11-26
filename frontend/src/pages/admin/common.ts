import { ApiError, FALLBACK_MESSAGE } from "../../api/client";

export const MIN_PASSWORD = 10;
// Sama persis dengan pesan server (MSG_PASSWORD).
export const MSG_PASSWORD = `Kata sandi minimal ${MIN_PASSWORD} karakter.`;

export const errText = (e: unknown) => (e instanceof ApiError ? e.detail : FALLBACK_MESSAGE);
/** 401 ditangani global (sesi berakhir): tidak perlu pesan lokal. */
export const isAuthError = (e: unknown) => e instanceof ApiError && e.status === 401;

export type Unit = { id: string; name: string };
export type AdminUser = {
  id: string;
  username: string;
  full_name: string;
  role: "pengguna" | "admin";
  unit_id: string;
  unit: string;
  active: boolean;
};
