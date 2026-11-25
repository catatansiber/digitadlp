import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { admin, meAs, server } from "../../test/server";
import { renderApp } from "../../test/render";

const KINDS = ["NIK", "KK", "NPWP", "PHONE", "EMAIL", "ACCOUNT", "NAME_CITIZEN", "NAME_EMPLOYEE", "NIP", "ADDRESS", "BIRTHDATE"];
let rules: Record<string, string>;
let puts: Record<string, string>[];

beforeEach(() => {
  rules = Object.fromEntries(KINDS.map((k) => [k, "internal"]));
  rules.NIK = "rahasia";
  puts = [];
  server.use(
    meAs(admin),
    http.get("/api/admin/label-rules", () => HttpResponse.json(rules)),
    http.put("/api/admin/label-rules", async ({ request }) => {
      puts.push((await request.json()) as Record<string, string>);
      return HttpResponse.json(puts[puts.length - 1]);
    }),
  );
});

test("label rules save sends full table", async () => {
  renderApp("/admin/aturan-label");
  const nik = await screen.findByLabelText("Label No. HP");
  expect(screen.getAllByRole("combobox")).toHaveLength(11);
  expect(screen.getByLabelText("Label NIK")).toHaveValue("rahasia");
  await userEvent.selectOptions(nik, "publik");
  await userEvent.click(screen.getByRole("button", { name: "Simpan" }));
  await waitFor(() => expect(puts).toHaveLength(1));
  expect(Object.keys(puts[0]).sort()).toEqual([...KINDS].sort());
  expect(puts[0].PHONE).toBe("publik");
  expect(puts[0].NIK).toBe("rahasia");
  expect(await screen.findByRole("status")).toHaveTextContent("Aturan label disimpan.");
});

test("restore defaults mirrors backend default_label_for", async () => {
  renderApp("/admin/aturan-label");
  await screen.findByLabelText("Label NIK");
  await userEvent.selectOptions(screen.getByLabelText("Label Email"), "rahasia");
  await userEvent.click(screen.getByRole("button", { name: "Kembalikan bawaan" }));
  for (const k of ["Label NIK", "Label No. KK", "Label No. rekening", "Label NPWP"])
    expect(screen.getByLabelText(k)).toHaveValue("rahasia");
  for (const k of ["Label Email", "Label No. HP", "Label Nama pegawai", "Label NIP", "Label Nama warga", "Label Alamat", "Label Tanggal lahir"])
    expect(screen.getByLabelText(k)).toHaveValue("internal");
  expect(puts).toHaveLength(0); // belum tersimpan sampai Simpan
});

test("label rules 422 shows server message", async () => {
  server.use(http.put("/api/admin/label-rules", () => HttpResponse.json({ detail: "Aturan label tidak valid." }, { status: 422 })));
  renderApp("/admin/aturan-label");
  await screen.findByLabelText("Label NIK");
  await userEvent.click(screen.getByRole("button", { name: "Simpan" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Aturan label tidak valid.");
});
