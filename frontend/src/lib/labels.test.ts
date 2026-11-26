import { KIND_TEXT, LABEL_TEXT, STATUS_TEXT } from "./labels";

test("label and status texts", () => {
  expect(LABEL_TEXT).toEqual({ publik: "Publik", internal: "Internal", rahasia: "Rahasia" });
  expect(STATUS_TEXT.membuat_versi).toBe("Membuat versi…");
  expect(STATUS_TEXT.gagal).toBe("Gagal diproses");
  expect(Object.keys(STATUS_TEXT)).toHaveLength(6);
});

test("kind texts cover 11 kinds", () => {
  expect(Object.keys(KIND_TEXT)).toHaveLength(11);
  expect(KIND_TEXT.KK).toBe("No. KK");
  expect(KIND_TEXT.NAME_EMPLOYEE).toBe("Nama pegawai");
  expect(KIND_TEXT.NAME_CITIZEN).toBe("Nama orang");
  expect(STATUS_TEXT).not.toHaveProperty("dikembalikan");
});
