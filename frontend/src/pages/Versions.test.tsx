import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Link } from "react-router-dom";
import { render } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { AppRoutes, makeQueryClient } from "../App";
import { AuthProvider } from "../auth/AuthProvider";
import { meAs, server, uploader } from "../test/server";
import { renderApp } from "../test/render";
import type { Me } from "../api/types";

const mate: Me = { id: "00000000000000000000000000000009", full_name: "Rina Rekan", role: "pengguna", unit: "Bagian Umum" };
const adminU: Me = { id: "00000000000000000000000000000002", full_name: "Sari Admin", role: "admin", unit: "Diskominfo" };

let doc: Record<string, unknown>;
let downloads: string[];
let releases: number;
let versionReply: (v: string) => Response;

const okBlob = (v: string) =>
  new HttpResponse("isi", {
    headers: { "Content-Disposition": `attachment; filename="d1-${v}.pdf"`, "Content-Type": "application/pdf" },
  });

function handlers() {
  return [
    http.get("/api/documents/d1", () => HttpResponse.json(doc)),
    http.get("/api/documents/d1/versions/:v", ({ params }) => {
      downloads.push(String(params.v));
      return versionReply(String(params.v));
    }),
    http.post("/api/documents/d1/release", () => {
      releases++;
      doc = { ...doc, status: "dirilis" };
      return HttpResponse.json(doc);
    }),
  ];
}

let created: Blob[];
let revoked: string[];
let clicked: { href: string; download: string }[];

beforeEach(() => {
  doc = { id: "d1", title: "SK Bansos.pdf", ext: "pdf", status: "disetujui", owner_id: "00000000000000000000000000000001" };
  downloads = [];
  releases = 0;
  created = [];
  revoked = [];
  clicked = [];
  versionReply = (v) => okBlob(v) as unknown as Response;
  URL.createObjectURL = ((b: Blob) => {
    created.push(b);
    return "blob:fake";
  }) as typeof URL.createObjectURL;
  URL.revokeObjectURL = ((u: string) => {
    revoked.push(u);
  }) as typeof URL.revokeObjectURL;
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push({ href: this.href, download: this.download });
  });
});
afterEach(() => vi.restoreAllMocks());

async function open(me: Me) {
  server.use(meAs(me), ...handlers());
  renderApp("/dokumen/d1/versi");
  await screen.findByRole("heading", { name: "SK Bansos.pdf" });
}
const card = (name: string) => screen.getByRole("group", { name });

test("download calls versions endpoint and creates blob URL", async () => {
  await open(uploader);
  await userEvent.click(within(card("Versi Internal")).getByRole("button", { name: "Unduh" }));
  await waitFor(() => expect(clicked).toHaveLength(1));
  expect(downloads).toEqual(["internal"]);
  expect(created).toHaveLength(1);
  expect(clicked[0].download).toBe("d1-internal.pdf");
  expect(clicked[0].href).toBe("blob:fake");
  await waitFor(() => expect(revoked).toEqual(["blob:fake"]));
});

test("403 shows server message on that card only", async () => {
  versionReply = (v) =>
    (v === "rahasia"
      ? HttpResponse.json({ detail: "Anda tidak berhak mengunduh versi ini." }, { status: 403 })
      : okBlob(v)) as Response;
  await open(uploader);
  await userEvent.click(within(card("Versi Rahasia")).getByRole("button", { name: "Unduh" }));
  expect(await within(card("Versi Rahasia")).findByText("Anda tidak berhak mengunduh versi ini.")).toBeInTheDocument();
  expect(within(card("Versi Rahasia")).getByRole("button", { name: "Unduh" })).toBeDisabled();
  expect(within(card("Versi Publik")).getByRole("button", { name: "Unduh" })).toBeEnabled();
  expect(within(card("Versi Internal")).queryByText(/berhak/)).toBeNull();
  expect(downloads).toEqual(["rahasia"]);
});

test("404 disables that card with server message", async () => {
  versionReply = () => HttpResponse.json({ detail: "Versi belum tersedia." }, { status: 404 }) as Response;
  await open(uploader);
  await userEvent.click(within(card("Versi Publik")).getByRole("button", { name: "Unduh" }));
  expect(await within(card("Versi Publik")).findByText("Versi belum tersedia.")).toBeInTheDocument();
  expect(within(card("Versi Publik")).getByRole("button", { name: "Unduh" })).toBeDisabled();
});

test("release needs confirm step", async () => {
  await open(uploader);
  await userEvent.click(screen.getByRole("button", { name: "Rilis versi Publik" }));
  expect(releases).toBe(0);
  const dlg = screen.getByRole("dialog");
  await userEvent.click(within(dlg).getByRole("button", { name: "Batal" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(releases).toBe(0);
  await userEvent.click(screen.getByRole("button", { name: "Rilis versi Publik" }));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Ya, rilis" }));
  await waitFor(() => expect(releases).toBe(1));
  expect(await screen.findByText("Versi Publik dirilis.")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("button", { name: "Rilis versi Publik" })).toBeNull());
});

test("release shown for admin", async () => {
  await open(adminU);
  expect(screen.getByRole("button", { name: "Rilis versi Publik" })).toBeInTheDocument();
});

test("release shown for admin of another unit (metadata only, rahasia denied)", async () => {
  doc = { ...doc, unit_id: "u-lain", unit_name: "Dinas Lain", owner_name: "Budi" };
  versionReply = (v) =>
    (v === "rahasia"
      ? HttpResponse.json({ detail: "Anda tidak punya akses ke versi ini." }, { status: 403 })
      : okBlob(v)) as unknown as Response;
  await open(adminU);
  await userEvent.click(screen.getByRole("button", { name: "Rilis versi Publik" }));
  await userEvent.click(screen.getByRole("button", { name: "Ya, rilis" }));
  await waitFor(() => expect(releases).toBe(1));
});

test("versions: owner can release; unit mate cannot", async () => {
  await open(uploader);
  expect(screen.getByRole("button", { name: "Rilis versi Publik" })).toBeInTheDocument();
});

test("release hidden for non-owner pengguna", async () => {
  await open(mate);
  expect(screen.queryByRole("button", { name: "Rilis versi Publik" })).toBeNull();
});

test("release error shows server detail", async () => {
  await open(uploader);
  server.use(
    http.post("/api/documents/d1/release", () =>
      HttpResponse.json({ detail: "Status dokumen tidak sesuai." }, { status: 409 }),
    ),
  );
  await userEvent.click(screen.getByRole("button", { name: "Rilis versi Publik" }));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Ya, rilis" }));
  expect(await screen.findByText("Status dokumen tidak sesuai.")).toBeInTheDocument();
});

test("status not ready shows message and back link, no cards", async () => {
  doc = { ...doc, status: "menunggu_cek" };
  await open(uploader);
  expect(screen.getByText("Versi belum tersedia. Dokumen berstatus Menunggu cek.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Kembali ke cek temuan/ })).toHaveAttribute("href", "/dokumen/d1");
  expect(screen.queryByRole("button", { name: "Unduh" })).toBeNull();
});

test("no text preview rendered", async () => {
  await open(uploader);
  expect(downloads).toEqual([]);
});

test("blocked state resets when navigating to another document", async () => {
  versionReply = () => HttpResponse.json({ detail: "Anda tidak berhak mengunduh versi ini." }, { status: 403 }) as Response;
  server.use(
    meAs(uploader),
    ...handlers(),
    http.get("/api/documents/d2", () => HttpResponse.json({ ...doc, id: "d2", title: "Lain.pdf" })),
  );
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={["/dokumen/d1/versi"]}>
        <AuthProvider>
          <Link to="/dokumen/d2/versi">ke d2</Link>
          <AppRoutes />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { name: "SK Bansos.pdf" });
  await userEvent.click(within(card("Versi Rahasia")).getByRole("button", { name: "Unduh" }));
  expect(await screen.findByText("Anda tidak berhak mengunduh versi ini.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("link", { name: "ke d2" }));
  await screen.findByRole("heading", { name: "Lain.pdf" });
  expect(screen.queryByText("Anda tidak berhak mengunduh versi ini.")).toBeNull();
  expect(within(card("Versi Rahasia")).getByRole("button", { name: "Unduh" })).toBeEnabled();
});
