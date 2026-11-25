import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { admin, meAs, server } from "../../test/server";
import { renderApp } from "../../test/render";

// XHR diganti tiruan (lihat Upload.test.tsx).
type Reply = { status: number; body: unknown };
let reply: Reply;
const posts: { url: string; file: FormDataEntryValue | null }[] = [];

class FakeXHR {
  status = 0;
  responseText = "";
  responseType = "";
  withCredentials = false;
  upload = { onprogress: null as ((e: unknown) => void) | null };
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
      this.status = reply.status;
      this.responseText = JSON.stringify(reply.body);
      this.onload?.();
    }, 0);
  }
}

beforeEach(() => {
  posts.length = 0;
  reply = { status: 200, body: { names: 42, nips: 40 } };
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  server.use(meAs(admin));
});
afterEach(() => vi.unstubAllGlobals());

const pick = (f: File) =>
  userEvent.setup({ applyAccept: false }).upload(screen.getByLabelText(/Pilih file xlsx/) as HTMLInputElement, f);

test("employees upload shows count", async () => {
  renderApp("/admin/pegawai");
  expect(await screen.findByText(/disimpan terenkripsi/i)).toBeInTheDocument();
  expect(screen.getByText(/nama/i, { selector: "code" })).toBeInTheDocument();
  await pick(new File(["x"], "pegawai.xlsx"));
  expect(await screen.findByRole("status")).toHaveTextContent("42 nama dan 40 NIP dimuat");
  expect(posts[0].url).toContain("/api/admin/employees");
  expect((posts[0].file as File).name).toBe("pegawai.xlsx");
});

test("employees upload shows server error", async () => {
  reply = { status: 422, body: { detail: "File daftar pegawai tidak bisa dibaca. Gunakan .xlsx dengan kolom Nama." } };
  renderApp("/admin/pegawai");
  await screen.findByText(/disimpan terenkripsi/i);
  await pick(new File(["x"], "pegawai.xlsx"));
  expect(await screen.findByRole("alert")).toHaveTextContent("tidak bisa dibaca");
});
