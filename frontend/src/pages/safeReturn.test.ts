import { safeReturn } from "./Login";

test.each([
  ["//evil.com", "/"],
  ["https://evil.com", "/"],
  ["/\\evil.com", "/"],
  ["/\t/evil.com", "/"],
  ["/masuk", "/"],
  ["/masuk?kembali=/x", "/"],
  [null, "/"],
  ["dokumen", "/"],
  ["/dokumen/abc?x=1#h", "/dokumen/abc?x=1#h"],
])("safeReturn(%j) → %j", (v, want) => {
  expect(safeReturn(v)).toBe(want);
});
