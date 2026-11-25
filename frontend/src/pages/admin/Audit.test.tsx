import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { admin, meAs, server } from "../../test/server";
import { renderApp } from "../../test/render";

let queries: URLSearchParams[];
beforeEach(() => {
  queries = [];
  server.use(
    meAs(admin),
    http.get("/api/admin/audit", ({ request }) => {
      queries.push(new URL(request.url).searchParams);
      return HttpResponse.json([
        { id: 1, at: "2026-11-20T08:00:00", actor_id: "abcdef1234567890abcdef1234567890", action: "impor_pegawai", document_id: null, detail: "nama=3 nip=2" },
        { id: 2, at: "2026-11-20T09:00:00", actor_id: "ff", actor_name: "Budi", action: "ubah_label", document_id: "d1d1d1d1d1d1d1d1", detail: "" },
        { id: 3, at: "2026-11-20T10:00:00", actor_id: null, action: "gagal_masuk", document_id: null, detail: "" },
      ]);
    }),
  );
});

test("audit shows Indonesian actions, name or short id", async () => {
  renderApp("/admin/audit");
  expect(await screen.findByText("Impor daftar pegawai")).toBeInTheDocument();
  expect(screen.getByText("Ubah label")).toBeInTheDocument();
  expect(screen.getByText("Gagal masuk")).toBeInTheDocument();
  expect(screen.getByText("Budi")).toBeInTheDocument();
  expect(screen.getByText("abcdef12")).toBeInTheDocument();
  expect(screen.getByText("nama=3 nip=2")).toBeInTheDocument();
  expect(queries[0].get("limit")).toBe("100");
});

test("audit filters pass query params", async () => {
  renderApp("/admin/audit");
  await screen.findByText("Ubah label");
  await userEvent.type(screen.getByLabelText("Dokumen"), "d1");
  await userEvent.type(screen.getByLabelText("Pengguna"), "u7");
  await userEvent.selectOptions(screen.getByLabelText("Batas"), "500");
  await waitFor(() => {
    const q = queries[queries.length - 1];
    expect(q.get("document_id")).toBe("d1");
    expect(q.get("actor_id")).toBe("u7");
    expect(q.get("limit")).toBe("500");
  });
  expect(queries.some((q) => q.has("document_id") && q.get("document_id") === "")).toBe(false);
});
