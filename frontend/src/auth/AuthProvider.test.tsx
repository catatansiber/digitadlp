import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useQuery } from "@tanstack/react-query";
import { Route, Routes, useLocation } from "react-router-dom";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { admin, meAs, server, uploader } from "../test/server";
import { renderApp } from "../test/render";
import { makeQueryClient } from "../App";
import { AuthProvider } from "./AuthProvider";
import { api } from "../api/client";
import { Login } from "../pages/Login";
import { emitSessionExpired } from "./sessionEvents";

function Probe() {
  const q = useQuery({ queryKey: ["probe"], queryFn: () => api("/probe") });
  return <p>{q.isError ? "gagal" : "memuat"}</p>;
}
function Where() {
  const l = useLocation();
  return <div data-testid="loc">{l.pathname + l.search}</div>;
}

test("401 during session redirects to /masuk?kembali=…", async () => {
  server.use(
    meAs(uploader),
    http.get("/api/probe", () => HttpResponse.json({ detail: "Sesi berakhir. Silakan masuk lagi." }, { status: 401 })),
  );
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={["/dokumen/7"]}>
        <AuthProvider>
          <Routes>
            <Route path="/dokumen/:id" element={<Probe />} />
            <Route path="/masuk" element={<><Where /><Login /></>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByTestId("loc")).toHaveTextContent("/masuk?kembali=%2Fdokumen%2F7");
  expect(screen.getByRole("status")).toHaveTextContent("Sesi berakhir. Silakan masuk lagi.");
});

test("unauthenticated visit redirects to login", async () => {
  renderApp("/upload");
  expect(await screen.findByLabelText("Nama pengguna")).toBeInTheDocument();
});

test("pengguna does not see Admin tab", async () => {
  server.use(meAs(uploader));
  renderApp("/");
  await screen.findByRole("heading", { name: "Beranda" });
  expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
  expect(screen.getByRole("link", { name: "Unggah" })).toBeInTheDocument();
});

test("admin sees Admin tab", async () => {
  server.use(meAs(admin));
  renderApp("/");
  expect(await screen.findByRole("link", { name: "Admin" })).toBeInTheDocument();
});

test("RequireRole blocks pengguna from admin pages", async () => {
  server.use(meAs(uploader));
  renderApp("/admin/pengguna");
  expect(await screen.findByText("Anda tidak punya akses ke halaman ini.")).toBeInTheDocument();
});

test("logout returns to login", async () => {
  let loggedOut = false;
  server.use(
    http.get("/api/auth/me", () =>
      loggedOut ? HttpResponse.json({ detail: "x" }, { status: 401 }) : HttpResponse.json(uploader),
    ),
    http.post("/api/auth/logout", () => {
      loggedOut = true;
      return HttpResponse.json({ ok: true });
    }),
  );
  renderApp("/");
  await userEvent.setup().click(await screen.findByRole("button", { name: "Keluar" }));
  expect(await screen.findByLabelText("Nama pengguna")).toBeInTheDocument();
  expect(loggedOut).toBe(true);
});

test("401 mid-session through real App shows expired message on /masuk", async () => {
  server.use(
    meAs(uploader),
    http.post("/api/auth/logout", () => HttpResponse.json({ ok: true })),
  );
  renderApp("/dokumen/9#temuan");
  await screen.findByRole("heading", { name: "Cek temuan" });
  emitSessionExpired();
  expect(await screen.findByRole("status")).toHaveTextContent("Sesi berakhir. Silakan masuk lagi.");
  expect(screen.getByLabelText("Nama pengguna")).toBeInTheDocument();
});

test("401 return path keeps hash", async () => {
  server.use(
    meAs(uploader),
    http.get("/api/probe", () => HttpResponse.json({ detail: "x" }, { status: 401 })),
  );
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={["/dokumen/7?a=1#h"]}>
        <AuthProvider>
          <Routes>
            <Route path="/dokumen/:id" element={<Probe />} />
            <Route path="/masuk" element={<Where />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByTestId("loc")).toHaveTextContent(
    "/masuk?kembali=" + encodeURIComponent("/dokumen/7?a=1#h"),
  );
});

test("admin nav has no Pegawai", async () => {
  server.use(meAs(admin), http.get("/api/admin/users", () => HttpResponse.json([])), http.get("/api/admin/units", () => HttpResponse.json([])));
  renderApp("/admin/pengguna");
  await screen.findByRole("navigation", { name: "Menu admin" });
  expect(screen.queryByRole("link", { name: "Pegawai" })).toBeNull();
});
