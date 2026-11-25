import { segments } from "./highlight";

test("segments covers text exactly, case-insensitive, longest wins", () => {
  const text = "Nama Siti Rahmawati dan siti, NIK 123";
  const segs = segments(text, [
    { text: "siti", kind: "NAME_CITIZEN" },
    { text: "Siti Rahmawati", kind: "NAME_EMPLOYEE" },
    { text: "123", kind: "NIK" },
  ]);
  expect(segs.map((s) => s.text).join("")).toBe(text);
  expect(segs.filter((s) => s.kind)).toEqual([
    { text: "Siti Rahmawati", kind: "NAME_EMPLOYEE" },
    { text: "siti", kind: "NAME_CITIZEN" },
    { text: "123", kind: "NIK" },
  ]);
});

test("segments with no marks returns whole text", () => {
  expect(segments("abc", [])).toEqual([{ text: "abc" }]);
  expect(segments("abc", [{ text: "", kind: "NIK" }])).toEqual([{ text: "abc" }]);
});
