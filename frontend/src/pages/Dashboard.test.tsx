import { http, HttpResponse } from "msw";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { admin, meAs, server, uploader } from "../test/server";
import { renderApp } from "../test/render";

const doc = (o: Record<string, unknown>) => ({
  id: "d1", title: "SK Bansos.pdf", ext: "pdf", status: "menunggu_cek", label: null,
  suggested_label: "rahasia", owner_name: "Budi Santoso", unit_name: "Bagian Umum",
  created_at: "2026-11-24T09:12:00+00:00", ...o,
});

test("dashboard lists docs with chips", async () => {
  server.use(
    meAs(uploader),
    http.get("/api/documents", () =>
      HttpResponse.json([
        doc({}),
        doc({ id: "d2", title: "Laporan.docx", status: "dirilis", suggested_label: "internal" }),
        doc({ id: "d3", title: "Gagal.pdf", status: "gagal", suggested_label: null }),
      ]),
    ),
  );
  renderApp("/");
  const row = (await screen.findByText("SK Bansos.pdf")).closest("tr")!;
  expect(within(row).getByText("Rahasia")).toHaveClass("rah");
  expect(within(row).getByText("Menunggu cek")).toBeInTheDocument();
  expect(within(row).getByText("Bagian Umum")).toBeInTheDocument();
  expect(within(row).getByText("Budi Santoso")).toBeInTheDocument();
  expect(within(row).getByText(/2026/)).toBeInTheDocument();
  const kpi = screen.getByLabelText("Ringkasan");
  expect(within(kpi).getByText("Gagal").nextSibling).toHaveTextContent("1");
  expect(screen.getByRole("link", { name: /Unggah dokumen/ })).toBeInTheDocument();
});

test("row click opens review", async () => {
  server.use(meAs(uploader), http.get("/api/documents", () => HttpResponse.json([doc({})])));
  renderApp("/");
  await userEvent.click(await screen.findByText("SK Bansos.pdf"));
  expect(await screen.findByRole("heading", { name: "Cek temuan" })).toBeInTheDocument();
});

test("empty state", async () => {
  server.use(meAs(uploader), http.get("/api/documents", () => HttpResponse.json([])));
  renderApp("/");
  expect(await screen.findByText("Belum ada dokumen. Unggah dokumen pertama.")).toBeInTheDocument();
});

test("admin has no upload button", async () => {
  server.use(meAs(admin), http.get("/api/documents", () => HttpResponse.json([])));
  renderApp("/");
  await screen.findByText("Belum ada dokumen.", { exact: false });
  expect(screen.queryByRole("link", { name: /Unggah dokumen/ })).toBeNull();
});

test("filters send query params", async () => {
  const urls: string[] = [];
  server.use(
    meAs(uploader),
    http.get("/api/documents", ({ request }) => {
      urls.push(new URL(request.url).search);
      return HttpResponse.json([]);
    }),
  );
  renderApp("/");
  const u = userEvent.setup();
  await u.selectOptions(await screen.findByLabelText("Status"), "dirilis");
  await u.click(screen.getByLabelText("Hanya milik saya"));
  await waitFor(() => expect(urls.some((s) => s.includes("status=dirilis") && s.includes("mine=true"))).toBe(true));
});

test("polls while diproses, stops when done", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let calls = 0;
  server.use(
    meAs(uploader),
    http.get("/api/documents", () => {
      calls++;
      return HttpResponse.json([doc({ status: calls >= 2 ? "menunggu_cek" : "diproses" })]);
    }),
  );
  try {
    renderApp("/");
    await screen.findByText("Diproses");
    await act(() => vi.advanceTimersByTimeAsync(5100));
    await screen.findByText("Menunggu cek", { selector: ".chip" });
    const after = calls;
    await act(() => vi.advanceTimersByTimeAsync(16000));
    expect(calls).toBe(after);
  } finally {
    vi.useRealTimers();
  }
});

test("KPI counts ignore the active filter", async () => {
  server.use(
    meAs(uploader),
    http.get("/api/documents", ({ request }) => {
      const st = new URL(request.url).searchParams.get("status");
      const all = [doc({}), doc({ id: "d2", status: "gagal" })];
      return HttpResponse.json(st ? all.filter((d) => d.status === st) : all);
    }),
  );
  renderApp("/");
  const u = userEvent.setup();
  await u.selectOptions(await screen.findByLabelText("Status"), "gagal");
  await waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(2));
  const kpi = screen.getByLabelText("Ringkasan");
  expect(within(kpi).getByText("Menunggu cek").nextSibling).toHaveTextContent("1");
});
