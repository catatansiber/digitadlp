import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server, uploader } from "../test/server";
import { renderApp } from "../test/render";

async function fill() {
  const u = userEvent.setup();
  await u.type(await screen.findByLabelText("Nama pengguna"), "budi");
  await u.type(screen.getByLabelText("Kata sandi"), "rahasia");
  await u.click(screen.getByRole("button", { name: "Masuk" }));
}

test("login success shows dashboard", async () => {
  server.use(http.post("/api/auth/login", () => HttpResponse.json(uploader)));
  renderApp("/masuk");
  await fill();
  expect(await screen.findByRole("heading", { name: "Beranda" })).toBeInTheDocument();
  expect(screen.getByText("Bagian Umum · Budi Santoso")).toBeInTheDocument();
});

test('login 401 shows "Nama pengguna atau kata sandi salah."', async () => {
  server.use(
    http.post("/api/auth/login", () =>
      HttpResponse.json({ detail: "Nama pengguna atau kata sandi salah." }, { status: 401 }),
    ),
  );
  renderApp("/masuk");
  await fill();
  expect(await screen.findByRole("alert")).toHaveTextContent("Nama pengguna atau kata sandi salah.");
});

test("429 message shown", async () => {
  server.use(
    http.post("/api/auth/login", () =>
      HttpResponse.json({ detail: "Terlalu banyak percobaan. Coba lagi dalam 15 menit." }, { status: 429 }),
    ),
  );
  renderApp("/masuk");
  await fill();
  expect(await screen.findByRole("alert")).toHaveTextContent("Terlalu banyak percobaan. Coba lagi dalam 15 menit.");
});

test("no localStorage writes", async () => {
  const spy = vi.spyOn(Storage.prototype, "setItem");
  server.use(http.post("/api/auth/login", () => HttpResponse.json(uploader)));
  renderApp("/masuk");
  await fill();
  await screen.findByRole("heading", { name: "Beranda" });
  expect(spy).not.toHaveBeenCalled();
  spy.mockRestore();
});
