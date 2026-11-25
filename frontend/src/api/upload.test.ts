import { ApiError } from "./client";
import { uploadDocument } from "./upload";

let last: X;
class X {
  status = 0;
  responseText = "";
  timeout = 0;
  aborted = false;
  upload = {};
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  constructor() {
    last = this;
  }
  open() {}
  setRequestHeader() {}
  send() {}
  abort() {
    this.aborted = true;
    this.onabort?.();
  }
}
beforeEach(() => vi.stubGlobal("XMLHttpRequest", X));
afterEach(() => vi.unstubAllGlobals());
const f = () => new File(["a"], "a.pdf");

test("maps non-JSON server error to generic ApiError", async () => {
  const p = uploadDocument(f());
  last.status = 502;
  last.responseText = "<html>";
  last.onload?.();
  await expect(p).rejects.toBeInstanceOf(ApiError);
});

test("network error becomes ApiError(0)", async () => {
  const p = uploadDocument(f());
  last.onerror?.();
  await expect(p).rejects.toMatchObject({ status: 0 });
});

test("abort signal aborts xhr", async () => {
  const ac = new AbortController();
  const p = uploadDocument(f(), undefined, ac.signal);
  ac.abort();
  expect(last.aborted).toBe(true);
  await expect(p).rejects.toMatchObject({ status: 0 });
});

test("already-aborted signal never sends", async () => {
  const ac = new AbortController();
  ac.abort();
  await expect(uploadDocument(f(), undefined, ac.signal)).rejects.toMatchObject({ status: 0 });
});

test("timeout is 10 minutes with Indonesian message", async () => {
  const p = uploadDocument(f());
  expect(last.timeout).toBe(10 * 60 * 1000);
  last.ontimeout?.();
  await expect(p).rejects.toMatchObject({ status: 0, detail: "Unggahan terlalu lama. Coba lagi." });
});
