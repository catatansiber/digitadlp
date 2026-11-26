import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { PageAreas } from "./PageAreas";

let areas: Record<string, unknown>[];
const posts: unknown[] = [];
const deletes: string[] = [];
let areaGets = 0;

beforeEach(() => {
  areas = [
    { id: "a1", page: 0, x0: 0.1, y0: 0.1, x1: 0.3, y1: 0.2 },
    { id: "a2", page: 1, x0: 0.5, y0: 0.5, x1: 0.6, y1: 0.7 },
  ];
  posts.length = 0;
  deletes.length = 0;
  areaGets = 0;
  server.use(
    http.get("/api/documents/d1/pages", () => HttpResponse.json({ count: 2, sizes: [[600, 800], [600, 800]] })),
    http.get("/api/documents/d1/areas", () => {
      areaGets++;
      return HttpResponse.json(areas);
    }),
    http.post("/api/documents/d1/areas", async ({ request }) => {
      const b = (await request.json()) as Record<string, unknown>;
      posts.push(b);
      const a = { id: "a3", ...b };
      areas = [...areas, a];
      return HttpResponse.json(a, { status: 201 });
    }),
    http.delete("/api/documents/d1/areas/:aid", ({ params }) => {
      deletes.push(String(params.aid));
      areas = areas.filter((a) => a.id !== params.aid);
      return new HttpResponse(null, { status: 204 });
    }),
  );
});

function show(canEdit: boolean, status = "menunggu_cek") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PageAreas docId="d1" ext="pdf" pageCount={2} canEdit={canEdit} status={status} />
    </QueryClientProvider>,
  );
}

test("owner draws box → POST with normalized coords", async () => {
  show(true);
  const img = await screen.findByRole("img", { name: "Halaman 1" });
  expect(img).toHaveAttribute("src", "/api/documents/d1/pages/0.png");
  const surface = screen.getByTestId("draw-surface");
  surface.getBoundingClientRect = () =>
    ({ left: 10, top: 20, width: 200, height: 400, right: 210, bottom: 420, x: 10, y: 20, toJSON() {} }) as DOMRect;
  fireEvent.pointerDown(surface, { pointerId: 1, button: 0, clientX: 110, clientY: 220 });
  fireEvent.pointerMove(surface, { pointerId: 1, clientX: 60, clientY: 120 });
  expect(screen.getByTestId("draw-preview")).toBeInTheDocument();
  fireEvent.pointerUp(surface, { pointerId: 1, clientX: 60, clientY: 120 });
  await waitFor(() => expect(posts).toEqual([{ page: 0, x0: 0.25, y0: 0.25, x1: 0.5, y1: 0.5 }]));
  expect(await screen.findByRole("button", { name: "Hapus area 3, halaman 1" })).toBeInTheDocument();
});

test("existing box positioned via CSS custom properties", async () => {
  show(false);
  await screen.findByRole("button", { name: /Halaman berikutnya/ });
  await waitFor(() => expect(document.querySelectorAll(".area-box")).toHaveLength(1));
  const box = document.querySelector(".area-box") as HTMLElement;
  expect(box.style.getPropertyValue("--x0")).toBe("10%");
  expect(box.getAttribute("style")).not.toBeNull(); // CSSOM, not JSX attr
});

test("unit mate sees boxes but cannot draw or delete", async () => {
  show(false);
  await screen.findByRole("img", { name: "Halaman 1" });
  await waitFor(() => expect(document.querySelectorAll(".area-box")).toHaveLength(1));
  expect(screen.queryByTestId("draw-surface")).toBeNull();
  expect(screen.queryByRole("button", { name: /Hapus area/ })).toBeNull();
  expect(screen.getByText(/Halaman 2/)).toBeInTheDocument();
});

test("delete calls DELETE and refetches", async () => {
  show(true);
  const list = await screen.findByRole("list", { name: "Daftar area" });
  await within(list).findByRole("button", { name: "Hapus area 2, halaman 2" });
  const before = areaGets;
  await userEvent.click(screen.getByRole("button", { name: "Hapus area 1, halaman 1" }));
  await waitFor(() => expect(deletes).toEqual(["a1"]));
  await waitFor(() => expect(areaGets).toBeGreaterThan(before));
  await waitFor(() => expect(screen.queryByRole("button", { name: /halaman 1$/ })).toBeNull());
});

test("page navigation and disetujui warning", async () => {
  show(true, "disetujui");
  expect(await screen.findByText("Mengubah area membatalkan persetujuan.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Halaman berikutnya" }));
  expect(screen.getByRole("img", { name: "Halaman 2" })).toHaveAttribute("src", "/api/documents/d1/pages/1.png");
  expect(screen.getByText("2 / 2")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Halaman berikutnya" })).toBeDisabled();
});
