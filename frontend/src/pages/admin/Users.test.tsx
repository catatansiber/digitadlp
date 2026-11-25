import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { admin, meAs, server } from "../../test/server";
import { renderApp } from "../../test/render";

// id admin = id baris "sari" (string hex 32 karakter seperti dari server).
const units = [
  { id: "u1", name: "Bagian Umum" },
  { id: "u2", name: "Diskominfo" },
];
let users: Record<string, unknown>[];
let posts: Record<string, unknown>[];
let patches: { id: string; body: Record<string, unknown> }[];

beforeEach(() => {
  users = [
    { id: "00000000000000000000000000000002", username: "sari", full_name: "Sari Admin", role: "admin", unit_id: "u2", unit: "Diskominfo", active: true },
    { id: "5", username: "budi", full_name: "Budi", role: "pengunggah", unit_id: "u1", unit: "Bagian Umum", active: true },
  ];
  posts = [];
  patches = [];
  server.use(
    meAs(admin),
    http.get("/api/admin/units", () => HttpResponse.json(units)),
    http.get("/api/admin/users", () => HttpResponse.json(users)),
    http.post("/api/admin/users", async ({ request }) => {
      posts.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ ...users[1], id: "9" }, { status: 201 });
    }),
    http.patch("/api/admin/users/:id", async ({ request, params }) => {
      patches.push({ id: String(params.id), body: (await request.json()) as Record<string, unknown> });
      return HttpResponse.json(users[1]);
    }),
  );
});

async function open() {
  renderApp("/admin/pengguna");
  await screen.findByText("budi");
}
const rowOf = (name: string) => screen.getByText(name).closest("tr") as HTMLElement;

test("create user validates password length client-side", async () => {
  await open();
  await userEvent.type(screen.getByLabelText("Nama pengguna"), "ani");
  await userEvent.type(screen.getByLabelText("Nama lengkap"), "Ani");
  const pw = screen.getByLabelText("Kata sandi");
  expect(pw).toHaveAttribute("type", "password");
  expect(pw).toHaveAttribute("autocomplete", "new-password");
  await userEvent.type(pw, "pendek");
  await userEvent.click(screen.getByRole("button", { name: "Tambah pengguna" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Kata sandi minimal 10 karakter.");
  expect(posts).toHaveLength(0);
  await userEvent.clear(pw);
  await userEvent.type(pw, "sandi-panjang-1");
  await userEvent.click(screen.getByRole("button", { name: "Tambah pengguna" }));
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0]).toMatchObject({ username: "ani", full_name: "Ani", unit_id: "u1", role: "pengunggah", password: "sandi-panjang-1" });
  await waitFor(() => expect(screen.getByLabelText("Kata sandi")).toHaveValue(""));
});

test("own row cannot demote or deactivate", async () => {
  await open();
  const row = rowOf("sari");
  expect(within(row).getByLabelText("Peran sari")).toBeDisabled();
  expect(within(row).getByRole("button", { name: "Nonaktifkan" })).toBeDisabled();
  expect(within(row).getByText(/akun Anda sendiri/i)).toBeInTheDocument();
  expect(within(rowOf("budi")).getByLabelText("Peran budi")).toBeEnabled();
});

test("deactivate calls PATCH active=false", async () => {
  await open();
  await userEvent.click(within(rowOf("budi")).getByRole("button", { name: "Nonaktifkan" }));
  await waitFor(() => expect(patches).toHaveLength(1));
  expect(patches[0]).toEqual({ id: "5", body: { active: false } });
});

test("role and unit changes send PATCH", async () => {
  await open();
  await userEvent.selectOptions(within(rowOf("budi")).getByLabelText("Peran budi"), "pemeriksa");
  await waitFor(() => expect(patches).toHaveLength(1));
  expect(patches[0].body).toEqual({ role: "pemeriksa" });
  await userEvent.selectOptions(within(rowOf("budi")).getByLabelText("Unit budi"), "u2");
  await waitFor(() => expect(patches).toHaveLength(2));
  expect(patches[1].body).toEqual({ unit_id: "u2" });
});

test("reset password dialog validates, sends, and clears", async () => {
  await open();
  await userEvent.click(within(rowOf("budi")).getByRole("button", { name: "Reset sandi" }));
  const dlg = await screen.findByRole("dialog");
  const pw = within(dlg).getByLabelText("Kata sandi baru");
  expect(pw).toHaveAttribute("type", "password");
  expect(pw).toHaveAttribute("autocomplete", "new-password");
  await userEvent.type(pw, "pendek");
  await userEvent.click(within(dlg).getByRole("button", { name: "Simpan sandi" }));
  expect(await within(dlg).findByRole("alert")).toHaveTextContent("Kata sandi minimal 10 karakter.");
  expect(patches).toHaveLength(0);
  await userEvent.clear(pw);
  await userEvent.type(pw, "sandi-baru-123");
  await userEvent.click(within(dlg).getByRole("button", { name: "Simpan sandi" }));
  await waitFor(() => expect(patches).toHaveLength(1));
  expect(patches[0].body).toEqual({ password: "sandi-baru-123" });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

test("409 from server is shown", async () => {
  server.use(
    http.patch("/api/admin/users/:id", () =>
      HttpResponse.json({ detail: "Admin tidak bisa menonaktifkan atau menurunkan peran akunnya sendiri." }, { status: 409 }),
    ),
  );
  await open();
  await userEvent.click(within(rowOf("budi")).getByRole("button", { name: "Nonaktifkan" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Admin tidak bisa menonaktifkan");
});
