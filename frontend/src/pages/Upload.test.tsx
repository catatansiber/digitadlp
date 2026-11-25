import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { admin, meAs, meUnauth, server, uploader } from "../test/server";
import { renderApp } from "../test/render";

// jsdom + MSW: XHR dengan FormData berisi File/Blob tidak pernah selesai (batasan lingkungan uji),
// jadi XHR diganti tiruan kecil yang mencatat kiriman dan membalas sesuai skenario.
type Reply = { status: number; body: unknown };
let reply: Reply = { status: 201, body: { id: "abc" } };
const posts: { url: string; file: FormDataEntryValue | null }[] = [];

class FakeXHR {
  status = 0;
  responseText = "";
  responseType = "";
  withCredentials = false;
  upload: { onprogress: ((e: unknown) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  private url = "";
  open(_m: string, url: string) {
    this.url = url;
  }
  setRequestHeader() {}
  send(fd: FormData) {
    posts.push({ url: this.url, file: fd.get("file") });
    setTimeout(() => {
      this.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 2 });
      this.status = reply.status;
      this.responseText = JSON.stringify(reply.body);
      this.onload?.();
    }, 0);
  }
}

beforeEach(() => {
  posts.length = 0;
  reply = { status: 201, body: { id: "abc" } };
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
});
afterEach(() => vi.unstubAllGlobals());

const input = () => screen.getByLabelText(/Pilih file/) as HTMLInputElement;
const pick = (f: File) => userEvent.setup({ applyAccept: false }).upload(input(), f);

test("upload rejects .txt client-side without request", async () => {
  server.use(meAs(uploader));
  renderApp("/upload");
  await screen.findByRole("heading", { name: "Unggah dokumen" });
  await pick(new File(["x"], "a.txt", { type: "text/plain" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Format file tidak didukung. Gunakan PDF atau DOCX.");
  expect(posts).toHaveLength(0);
});

test("upload rejects 51MB client-side", async () => {
  server.use(meAs(uploader));
  renderApp("/upload");
  await screen.findByRole("heading", { name: "Unggah dokumen" });
  const big = new File(["x"], "a.pdf", { type: "application/pdf" });
  Object.defineProperty(big, "size", { value: 51 * 1024 * 1024 });
  await pick(big);
  expect(await screen.findByRole("alert")).toHaveTextContent("Ukuran file melebihi batas 50 MB.");
  expect(posts).toHaveLength(0);
});

test("upload rejects empty file", async () => {
  server.use(meAs(uploader));
  renderApp("/upload");
  await screen.findByRole("heading", { name: "Unggah dokumen" });
  await pick(new File([], "a.pdf", { type: "application/pdf" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("File kosong.");
  expect(posts).toHaveLength(0);
});

test("upload success navigates to review", async () => {
  server.use(meAs(uploader));
  renderApp("/upload");
  await screen.findByRole("heading", { name: "Unggah dokumen" });
  expect(screen.getByText("File diproses di server instansi. Tidak dikirim ke layanan luar.")).toBeInTheDocument();
  await pick(new File(["%PDF-1.4"], "a.pdf", { type: "application/pdf" }));
  expect(await screen.findByRole("heading", { name: "Cek temuan" })).toBeInTheDocument();
  expect(posts).toHaveLength(1);
});

test("server 422 detail shown", async () => {
  server.use(meAs(uploader));
  reply = {
    status: 422,
    body: { detail: "Dokumen terenkripsi atau rusak. Buka kunci atau simpan ulang file, lalu upload lagi." },
  };
  renderApp("/upload");
  await screen.findByRole("heading", { name: "Unggah dokumen" });
  await pick(new File(["junk"], "a.pdf", { type: "application/pdf" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Dokumen terenkripsi atau rusak.");
});

test("upload 401 triggers session-expired flow", async () => {
  server.use(meAs(uploader));
  reply = { status: 401, body: { detail: "Sesi berakhir. Silakan masuk lagi." } };
  renderApp("/upload");
  await screen.findByRole("heading", { name: "Unggah dokumen" });
  server.use(meUnauth);
  await pick(new File(["%PDF-1.4"], "a.pdf", { type: "application/pdf" }));
  expect(await screen.findByLabelText("Nama pengguna")).toBeInTheDocument();
});

test("pemeriksa may upload, admin may not", async () => {
  server.use(meAs({ ...uploader, role: "pemeriksa" }));
  renderApp("/upload");
  expect(await screen.findByRole("heading", { name: "Unggah dokumen" })).toBeInTheDocument();
});

test("admin denied", async () => {
  server.use(meAs(admin));
  renderApp("/upload");
  expect(await screen.findByText("Anda tidak punya akses ke halaman ini.")).toBeInTheDocument();
});
