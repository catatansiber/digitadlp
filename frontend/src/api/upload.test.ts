import { ApiError } from "./client";
import { uploadDocument } from "./upload";

test("maps non-JSON server error to generic ApiError", async () => {
  class X {
    status = 502;
    responseText = "<html>";
    upload = {};
    onload: (() => void) | null = null;
    open() {}
    setRequestHeader() {}
    send() {
      setTimeout(() => this.onload?.(), 0);
    }
  }
  vi.stubGlobal("XMLHttpRequest", X);
  await expect(uploadDocument(new File(["a"], "a.pdf"))).rejects.toBeInstanceOf(ApiError);
  vi.unstubAllGlobals();
});
