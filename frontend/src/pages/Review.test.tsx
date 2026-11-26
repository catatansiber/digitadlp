import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { meAs, server } from "../test/server";
import { renderApp } from "../test/render";
import type { Me } from "../api/types";

const owner: Me = { id: "00000000000000000000000000000001", full_name: "Budi Santoso", role: "pengguna", unit: "Bagian Umum" };
const mate: Me = { id: "00000000000000000000000000000009", full_name: "Rina Rekan", role: "pengguna", unit: "Bagian Umum" };

const base = {
  id: "d1", title: "SK Bansos.pdf", ext: "pdf", status: "menunggu_cek", owner_id: "00000000000000000000000000000001", unit_id: "u1",
  label: null, suggested_label: "rahasia", reviewer_id: null, approved_at: null, released_at: null,
  revision: 1, created_at: null, owner_name: "Budi Santoso", unit_name: "Bagian Umum",
  return_reason: null, corrections: [],
  findings: [
    [
      { kind: "NIK", text: "6474015203880002", page: 0, start: 5, end: 21, source: "regex" },
      { kind: "NAME_CITIZEN", text: "Siti", page: 0, start: 0, end: 4, source: "manual" },
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
    server.use(meAs(owner), ...handlers());
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
  await open(owner);
  const g = await screen.findByRole("group", { name: "Di luar halaman" });
  expect(within(g).getByText("x@y.id")).toBeInTheDocument();
  expect(within(screen.getByRole("group", { name: "Halaman 1" })).getByText("Siti")).toBeInTheDocument();
});

test("abaikan posts correction and refetches", async () => {
  await open(owner);
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
  await open(owner);
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

test("403 detail shown in toast", async () => {
  await open(owner);
  server.use(
    http.post("/api/documents/d1/approve", () =>
      HttpResponse.json({ detail: "Anda tidak punya akses untuk tindakan ini." }, { status: 403 }),
    ),
  );
  await userEvent.click(await screen.findByRole("button", { name: "Buat versi" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Anda tidak punya akses untuk tindakan ini.");
});

test("approved shows three-versions link", async () => {
  doc = { ...base, status: "disetujui" };
  await open(owner);
  expect(await screen.findByRole("link", { name: "Lihat tiga versi" })).toHaveAttribute("href", "/dokumen/d1/versi");
});

test("disetujui still allows corrections with warning", async () => {
  doc = { ...base, status: "disetujui" };
  await open(owner);
  expect(await screen.findByText("Mengubah temuan membatalkan persetujuan.")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Abaikan" }).length).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: "+ Tandai manual" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Buat versi" })).toBeNull();
});

test("docx manual add sends page 0", async () => {
  doc = { ...base, ext: "docx", findings: [base.findings[0]] };
  await open(owner);
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
  await open(owner);
  const sel = (await screen.findByLabelText("Label")) as HTMLSelectElement;
  expect(sel.value).toBe("");
  expect(screen.getByRole("option", { name: "Pilih label" })).toBeDisabled();
});

test("diproses shows processing message", async () => {
  doc = { ...base, status: "diproses", findings: [] };
  await open(owner);
  expect(await screen.findByText("Dokumen masih diproses…")).toBeInTheDocument();
  expect(textCalls).toBe(0);
});

test("review: owner sees Buat versi; unit mate sees no actions", async () => {
  await open(owner);
  expect(await screen.findByRole("button", { name: "Buat versi" })).toBeEnabled();
  expect(screen.getAllByRole("button", { name: "Abaikan" }).length).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: "+ Tandai manual" })).toBeInTheDocument();
  expect(screen.getByLabelText("Label")).toBeInTheDocument();
  expect(screen.getByLabelText("Unggah ulang")).toBeInTheDocument();
});

test("review: unit mate sees no actions", async () => {
  await open(mate);
  await screen.findByRole("group", { name: "Halaman 1" });
  for (const n of ["Buat versi", "+ Tandai manual", "Abaikan"])
    expect(screen.queryByRole("button", { name: n })).toBeNull();
  expect(screen.queryByLabelText("Label")).toBeNull();
  expect(screen.queryByLabelText("Unggah ulang")).toBeNull();
  expect(screen.queryByRole("button", { name: "Kembalikan ke pengunggah" })).toBeNull();
});

test("review: manual kinds exclude NAME_EMPLOYEE and start with Nama orang", async () => {
  await open(owner);
  await screen.findByText("Hal dua");
  await userEvent.click(screen.getByRole("button", { name: "+ Tandai manual" }));
  const opts = within(screen.getByLabelText("Jenis")).getAllByRole("option").map((o) => o.textContent);
  expect(opts[0]).toBe("Nama orang");
  expect(opts).not.toContain("Nama pegawai");
  expect(screen.getByText("Nama tidak dideteksi otomatis. Tandai nama orang yang perlu disensor; semua kemunculan yang sama ikut tersensor.")).toBeInTheDocument();
});

test("review: legacy NAME_EMPLOYEE finding renders", async () => {
  doc = { ...base, findings: [[{ kind: "NAME_EMPLOYEE", text: "Pak Joko", page: 0, start: 0, end: 8, source: "ner" }]] };
  await open(owner);
  const g = await screen.findByRole("group", { name: "Halaman 1" });
  expect(within(g).getByText("Pak Joko")).toBeInTheDocument();
  expect(within(g).getByText("Nama pegawai")).toBeInTheDocument();
});

test("review: old return_reason is not shown", async () => {
  doc = { ...base, return_reason: "Lampiran kurang" };
  await open(owner);
  await screen.findByRole("group", { name: "Halaman 1" });
  expect(screen.queryByText("Lampiran kurang")).toBeNull();
});

test("review: reupload asks in-page confirmation first", async () => {
  await open(owner);
  const input = await screen.findByLabelText("Unggah ulang");
  const uploads: string[] = [];
  server.use(http.post("/api/documents/d1/reupload", () => { uploads.push("x"); return HttpResponse.json(doc); }));
  await userEvent.upload(input, new File(["%PDF-1.4 x"], "baru.pdf", { type: "application/pdf" }));
  const dlg = await screen.findByRole("dialog", { name: "Unggah ulang" });
  expect(within(dlg).getByText("Unggah ulang akan menghapus temuan dan koreksi dokumen ini. Lanjutkan?")).toBeInTheDocument();
  expect(uploads).toHaveLength(0);
  await userEvent.click(within(dlg).getByRole("button", { name: "Batal" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(uploads).toHaveLength(0);
  await userEvent.upload(input, new File(["%PDF-1.4 x"], "baru.pdf", { type: "application/pdf" }));
  await userEvent.click(within(await screen.findByRole("dialog", { name: "Unggah ulang" })).getByRole("button", { name: "Lanjutkan" }));
  await waitFor(() => expect(uploads).toHaveLength(1));
});

test("review: failed document offers reupload to owner", async () => {
  doc = { ...base, status: "gagal" };
  delete doc.findings;
  await open(owner);
  expect(await screen.findByLabelText("Unggah ulang")).toBeInTheDocument();
});
