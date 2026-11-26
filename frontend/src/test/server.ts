import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import type { Me } from "../api/types";

export const uploader: Me = { id: "00000000000000000000000000000001", full_name: "Budi Santoso", role: "pengguna", unit: "Bagian Umum" };
export const admin: Me = { id: "00000000000000000000000000000002", full_name: "Sari Admin", role: "admin", unit: "Diskominfo" };

export const meUnauth = http.get("/api/auth/me", () =>
  HttpResponse.json({ detail: "Sesi berakhir. Silakan masuk lagi." }, { status: 401 }),
);
export const meAs = (u: Me) => http.get("/api/auth/me", () => HttpResponse.json(u));

// Bawaan: detail dokumen tidak ada, agar tes lain tidak membuat permintaan tak tertangani.
export const docMissing = http.get("/api/documents/:id", () =>
  HttpResponse.json({ detail: "Dokumen tidak ditemukan." }, { status: 404 }),
);

export const noDocs = http.get("/api/documents", () => HttpResponse.json([]));

export const server = setupServer(meUnauth, docMissing, noDocs);
