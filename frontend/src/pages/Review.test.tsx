import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { meAs, server, uploader } from "../test/server";
import { renderApp } from "../test/render";
import type { Me } from "../api/types";

const reviewer: Me = { id: 3, full_name: "Dedi Pemeriksa", role: "pemeriksa", unit: "Diskominfo" };

const base = {
  id: "d1", title: "SK Bansos.pdf", ext: "pdf", status: "menunggu_cek", owner_id: 1, unit_id: 1,
  label: null, suggested_label: "rahasia", reviewer_id: null, approved_at: null, released_at: null,
  revision: 1, created_at: null, owner_name: "Budi Santoso", unit_name: "Bagian Umum",
  return_reason: null, corrections: [],
  findings: [
    [
      { kind: "NIK", text: "6474015203880002", page: 0, start: 5, end: 21, source: "regex" },
      { kind: "NAME_CITIZEN", text: "Siti", page: 0, start: 0, end: 4, source: "ner" },
    ],
    [{ kind: "EMAIL", text: "x@y.id", page: null, start: -1, end: -1, source: "regex" }],
  ],
};

let doc: Record<string, unknown>;
let textCalls = 0;
const posts: { path: string; body: unknown }[] = [];

function handlers() {
  return [
    http.get("/api/documents/d1", () => HttpResponse.json(doc)),
    http.get("/api/documents/d1/text", () => {
      textCalls++;
      return HttpResponse.json({ pages: ["Siti 6474015203880002 <script>alert(1)</script>", "Hal dua"] });
    }),
    http.post("/api/documents/d1/:action", async ({ request, params }) => {
      posts.push({ path: String(params.action), body: await request.json().catch(() => null) });
      return HttpResponse.json(doc);
    }),
  ];
}

beforeEach(() => {
  doc = structuredClone(base);
  textCalls = 0;
  posts.length = 0;
});

async function open(me: Me) {
  server.use(meAs(me), ...handlers());
  renderApp("/dokumen/d1");
  await screen.findByRole("heading", { name: "SK Bansos.pdf" });
}

test("script text rendered as text", async () => {
  const { container } = await (async () => {
    server.use(meAs(reviewer), ...handlers());
    const r = renderApp("/dokumen/d1");
    await screen.findByText(/<script>alert\(1\)<\/script>/);
    return r;
  })();
  expect(container.querySelector("script")).toBeNull();
  const m = container.querySelector("mark.strong");
  expect(m).toHaveTextContent("6474015203880002");
  expect(screen.getByText(/Ada 1 NIK/)).toBeInTheDocument();
});

test('page=null findings in "Di luar halaman"', async () => {
  await open(reviewer);
  const g = await screen.findByRole("group", { name: "Di luar halaman" });
  expect(within(g).getByText("x@y.id")).toBeInTheDocument();
  expect(within(screen.getByRole("group", { name: "Halaman 1" })).getByText("Siti")).toBeInTheDocument();
});

test("self-approval button disabled with reason", async () => {
  await open({ ...reviewer, id: 1 });
  const b = await screen.findByRole("button", { name: "Setujui & buat versi" });
  expect(b).toBeDisabled();
  expect(screen.getByText("Pemeriksa tidak boleh menyetujui dokumen yang ia upload sendiri.")).toBeInTheDocument();
});

test("abaikan posts correction and refetches", async () => {
  await open(reviewer);
  const g = await screen.findByRole("group", { name: "Halaman 1" });
  doc = { ...doc, findings: [[base.findings[0][1]], []] };
  await userEvent.click(within(g).getAllByRole("button", { name: "Abaikan" })[0]);
  await waitFor(() =>
    expect(posts).toContainEqual({
      path: "corrections",
      body: { op: "abaikan", kind: "NIK", text: "6474015203880002", page: 0 },
    }),
  );
  expect(await screen.findByText("Temuan diabaikan")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByText("6474015203880002", { selector: ".f-v" })).toBeNull());
});

test("manual add prefilled from selection", async () => {
  await open(reviewer);
  await screen.findByText("Hal dua");
  vi.spyOn(window, "getSelection").mockReturnValue({ toString: () => "Hal dua" } as unknown as Selection);
  await userEvent.click(screen.getByRole("button", { name: "+ Tandai manual" }));
  expect(screen.getByLabelText("Teks")).toHaveValue("Hal dua");
  await userEvent.selectOptions(screen.getByLabelText("Jenis"), "ADDRESS");
  await userEvent.clear(screen.getByLabelText("Halaman"));
  await userEvent.type(screen.getByLabelText("Halaman"), "2");
  await userEvent.click(screen.getByRole("button", { name: "Simpan temuan" }));
  await waitFor(() =>
    expect(posts).toContainEqual({ path: "corrections", body: { op: "tambah", kind: "ADDRESS", text: "Hal dua", page: 1 } }),
  );
  expect(await screen.findByText("Temuan ditambahkan")).toBeInTheDocument();
  vi.restoreAllMocks();
});

test("return requires reason ≤200", async () => {
  await open(reviewer);
  await userEvent.click(await screen.findByRole("button", { name: "Kembalikan ke pengunggah" }));
  const box = screen.getByLabelText("Alasan");
  const send = screen.getByRole("button", { name: "Kirim" });
  expect(send).toBeDisabled();
  await userEvent.click(box);
  await userEvent.paste("a".repeat(201));
  expect(send).toBeDisabled();
  expect(screen.getByText(/maksimal 200 karakter/)).toBeInTheDocument();
  await userEvent.clear(box);
  await userEvent.type(box, "Lampiran kurang");
  await userEvent.click(send);
  await waitFor(() => expect(posts).toContainEqual({ path: "return", body: { reason: "Lampiran kurang" } }));
});

test("owner sees return reason and reupload", async () => {
  doc = { ...base, status: "dikembalikan", return_reason: "Lampiran kurang", findings: undefined, corrections: undefined };
  delete doc.findings;
  await open(uploader);
  expect(await screen.findByText("Lampiran kurang")).toBeInTheDocument();
  expect(screen.getByLabelText("Upload ulang")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Setujui & buat versi" })).toBeNull();
  expect(textCalls).toBe(0);
});

test("403 detail shown in toast", async () => {
  await open(reviewer);
  server.use(
    http.post("/api/documents/d1/approve", () =>
      HttpResponse.json({ detail: "Anda tidak punya akses untuk tindakan ini." }, { status: 403 }),
    ),
  );
  await userEvent.click(await screen.findByRole("button", { name: "Setujui & buat versi" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Anda tidak punya akses untuk tindakan ini.");
});

test("approved shows three-versions link", async () => {
  doc = { ...base, status: "disetujui" };
  await open(reviewer);
  expect(await screen.findByRole("link", { name: "Lihat tiga versi" })).toHaveAttribute("href", "/dokumen/d1/versi");
});

test("disetujui still allows corrections with warning", async () => {
  doc = { ...base, status: "disetujui" };
  await open(reviewer);
  expect(await screen.findByText("Mengubah temuan membatalkan persetujuan.")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Abaikan" }).length).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: "+ Tandai manual" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Setujui & buat versi" })).toBeNull();
});

test("docx manual add sends page 0", async () => {
  doc = { ...base, ext: "docx", findings: [base.findings[0]] };
  await open(reviewer);
  await screen.findByText("Hal dua");
  vi.spyOn(window, "getSelection").mockReturnValue({ toString: () => "Hal dua" } as unknown as Selection);
  await userEvent.click(screen.getByRole("button", { name: "+ Tandai manual" }));
  expect(screen.queryByLabelText("Halaman")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Simpan temuan" }));
  await waitFor(() =>
    expect(posts).toContainEqual({ path: "corrections", body: { op: "tambah", kind: "NAME_CITIZEN", text: "Hal dua", page: 0 } }),
  );
  vi.restoreAllMocks();
});

test("label select shows placeholder when no label", async () => {
  doc = { ...base, label: null, suggested_label: null };
  await open(reviewer);
  const sel = (await screen.findByLabelText("Label")) as HTMLSelectElement;
  expect(sel.value).toBe("");
  expect(screen.getByRole("option", { name: "Pilih label" })).toBeDisabled();
});

test("diproses shows processing message", async () => {
  doc = { ...base, status: "diproses", findings: [] };
  await open(reviewer);
  expect(await screen.findByText("Dokumen masih diproses…")).toBeInTheDocument();
  expect(textCalls).toBe(0);
});
