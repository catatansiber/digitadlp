import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { admin, meAs, server } from "../../test/server";
import { renderApp } from "../../test/render";

test("units list and create", async () => {
  const posts: unknown[] = [];
  let list = [{ id: "u1", name: "Bagian Umum" }];
  server.use(
    meAs(admin),
    http.get("/api/admin/units", () => HttpResponse.json(list)),
    http.post("/api/admin/units", async ({ request }) => {
      posts.push(await request.json());
      list = [...list, { id: "u2", name: "Keuangan" }];
      return HttpResponse.json(list[1], { status: 201 });
    }),
  );
  renderApp("/admin/unit");
  await screen.findByText("Bagian Umum");
  await userEvent.type(screen.getByLabelText("Nama unit"), "Keuangan");
  await userEvent.click(screen.getByRole("button", { name: "Tambah unit" }));
  await waitFor(() => expect(posts).toEqual([{ name: "Keuangan" }]));
  expect(await screen.findByText("Keuangan")).toBeInTheDocument();
});

test("unit 409 shows server message", async () => {
  server.use(
    meAs(admin),
    http.get("/api/admin/units", () => HttpResponse.json([])),
    http.post("/api/admin/units", () => HttpResponse.json({ detail: "Unit kerja sudah ada." }, { status: 409 })),
  );
  renderApp("/admin/unit");
  await userEvent.type(await screen.findByLabelText("Nama unit"), "X");
  await userEvent.click(screen.getByRole("button", { name: "Tambah unit" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Unit kerja sudah ada.");
});
