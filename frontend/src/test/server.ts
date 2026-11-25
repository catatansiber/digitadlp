import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import type { Me } from "../api/types";

export const uploader: Me = { id: 1, full_name: "Budi Santoso", role: "pengunggah", unit: "Bagian Umum" };
export const admin: Me = { id: 2, full_name: "Sari Admin", role: "admin", unit: "Diskominfo" };

export const meUnauth = http.get("/api/auth/me", () =>
  HttpResponse.json({ detail: "Sesi berakhir. Silakan masuk lagi." }, { status: 401 }),
);
export const meAs = (u: Me) => http.get("/api/auth/me", () => HttpResponse.json(u));

export const server = setupServer(meUnauth);
