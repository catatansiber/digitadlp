import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { api, apiBlob, ApiError } from "./client";

test("client throws ApiError with server detail", async () => {
  server.use(http.get("/api/x", () => HttpResponse.json({ detail: "Tidak ditemukan." }, { status: 404 })));
  const err = await api<never>("/x").catch((e: ApiError) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err.status).toBe(404);
  expect(err.detail).toBe("Tidak ditemukan.");
  expect(err.message).toBe("Tidak ditemukan.");
});

test("client fallback message on non-JSON error", async () => {
  server.use(http.get("/api/x", () => new HttpResponse("<html>boom</html>", { status: 500 })));
  const err = await api<never>("/x").catch((e: ApiError) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err.status).toBe(500);
  expect(err.detail).toBe("Terjadi kesalahan. Coba lagi.");
});

test("client sends JSON body and parses JSON", async () => {
  server.use(
    http.post("/api/echo", async ({ request }) => {
      expect(request.headers.get("content-type")).toContain("application/json");
      return HttpResponse.json({ got: await request.json() });
    }),
  );
  const r = await api<{ got: unknown }>("/echo", { method: "POST", body: JSON.stringify({ a: 1 }) });
  expect(r.got).toEqual({ a: 1 });
});

test("client sends FormData as-is", async () => {
  // jsdom FormData tidak bisa dialirkan oleh fetch Node, jadi periksa argumen fetch langsung.
  const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ ok: true }));
  const fd = new FormData();
  fd.append("f", new File(["x"], "a.txt"));
  await api("/up", { method: "POST", body: fd });
  const [u, init] = spy.mock.calls[0] as [string, RequestInit];
  expect(u).toMatch(/\/api\/up$/);
  expect(init.body).toBe(fd);
  expect(init.credentials).toBe("same-origin");
  expect(new Headers(init.headers).has("Content-Type")).toBe(false);
  spy.mockRestore();
});

test("apiBlob returns blob and filename", async () => {
  server.use(
    http.get("/api/dl", () =>
      new HttpResponse("data", { headers: { "Content-Disposition": 'attachment; filename="hasil.pdf"' } }),
    ),
  );
  const r = await apiBlob("/dl");
  expect(r.filename).toBe("hasil.pdf");
  expect(await r.blob.text()).toBe("data");
});
