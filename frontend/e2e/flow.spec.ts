import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const PY = resolve(HERE, "../../backend/.venv/bin/python");
const NIK = "6474015203880002";
const NAMA = "Siti Rahmawati";
const SHOTS = resolve(HERE, "../test-results");
const tmp = mkdtempSync(join(tmpdir(), "digitadlp-e2e-"));

function py(code: string, ...args: string[]): string {
  return execFileSync(PY, ["-I", "-c", code, ...args], { encoding: "utf8" });
}

function makePdf(): string {
  const out = join(tmp, "surat-keterangan.pdf");
  py(
    `import sys, pymupdf as fitz
d = fitz.open(); p = d.new_page()
p.insert_text((72, 100), "Surat Keterangan Domisili", fontsize=14)
p.insert_text((72, 140), "NIK ${NIK}", fontsize=11)
p.insert_text((72, 160), "Diajukan oleh ${NAMA}", fontsize=11)
d.save(sys.argv[1])`,
    out,
  );
  return out;
}

function pdfText(path: string): string {
  return py("import sys, pymupdf as fitz\nprint(''.join(p.get_text() for p in fitz.open(sys.argv[1])))", path);
}

const shot = (page: Page, name: string) => page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });

async function login(page: Page, username: string, password: string) {
  await page.goto("/masuk");
  await page.getByLabel("Nama pengguna").fill(username);
  await page.getByLabel("Kata sandi").fill(password);
  await page.getByRole("button", { name: "Masuk" }).click();
  await expect(page.getByRole("button", { name: "Keluar" })).toBeVisible();
}

async function logout(page: Page) {
  await page.getByRole("button", { name: "Keluar" }).click();
  await expect(page).toHaveURL(/\/masuk/);
}

async function download(page: Page, version: string): Promise<string> {
  const [dl] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("group", { name: `Versi ${version}` }).getByRole("button", { name: "Unduh" }).click(),
  ]);
  const path = join(tmp, `${version}-${dl.suggestedFilename()}`);
  await dl.saveAs(path);
  return path;
}

test("alur lengkap: admin, unggah, tandai nama, buat versi, unduh, rilis, audit", async ({ page }) => {
  const pw = "sandi-e2e-123";

  // 1. Admin membuat unit dan satu pengguna.
  await login(page, "admin", "admin-e2e-123");
  await page.goto("/admin/unit");
  await page.getByLabel("Nama unit").fill("Bidang Pelayanan");
  await page.getByRole("button", { name: "Tambah unit" }).click();
  await expect(page.getByRole("cell", { name: "Bidang Pelayanan" })).toBeVisible();

  await page.goto("/admin/pengguna");
  const form = page.locator("form.form-grid");
  await form.getByLabel("Nama pengguna").fill("rina");
  await form.getByLabel("Nama lengkap").fill("Rina Pengguna");
  await form.getByLabel("Peran").selectOption("pengguna");
  await form.getByLabel("Unit").selectOption({ label: "Bidang Pelayanan" });
  await form.getByLabel("Kata sandi").fill(pw);
  await form.getByRole("button", { name: "Tambah pengguna" }).click();
  await expect(page.getByRole("cell", { name: "rina", exact: true })).toBeVisible();
  await shot(page, "01-admin-pengguna");
  await logout(page);

  // 2. Rina mengunggah PDF.
  await login(page, "rina", pw);
  await page.goto("/upload");
  await page.locator('input[type="file"]').setInputFiles(makePdf());
  await expect(page).toHaveURL(/\/dokumen\/[^/]+$/);

  // 3. Menunggu cek: NIK terdeteksi, nama tidak.
  await expect(page.getByText("Menunggu cek")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Saran label: Rahasia")).toBeVisible();
  await expect(page.getByLabel("Teks dokumen").locator("mark", { hasText: NIK })).toBeVisible();
  await expect(page.getByLabel("Teks dokumen").locator("mark", { hasText: "Rahmawati" })).toHaveCount(0);

  // 4. Rina menandai nama secara manual.
  await page.getByRole("button", { name: "+ Tandai manual" }).click();
  const manual = page.locator("form.manual");
  await manual.getByLabel("Teks").fill(NAMA);
  await manual.getByRole("button", { name: "Simpan temuan" }).click();
  await expect(page.getByLabel("Teks dokumen").locator("mark", { hasText: "Rahmawati" })).toBeVisible();
  await shot(page, "02-rina-tandai-nama");

  // 5. Buat versi; unduh Publik (tanpa NIK dan nama) dan Rahasia (kontrol positif).
  await page.getByRole("button", { name: "Buat versi" }).click();
  await expect(page.locator(".chip", { hasText: "Disetujui" }).first()).toBeVisible({ timeout: 60_000 });
  await page.getByRole("link", { name: "Lihat tiga versi" }).click();
  await expect(page.getByRole("heading", { name: "Tiga versi" })).toBeVisible();
  const publik = pdfText(await download(page, "Publik"));
  const rahasia = pdfText(await download(page, "Rahasia"));
  expect(rahasia).toContain(NIK);
  expect(rahasia).toContain(NAMA);
  expect(publik).not.toContain(NIK);
  expect(publik).not.toContain("Rahmawati");
  expect(publik).toContain("Surat Keterangan");
  await shot(page, "03-rina-tiga-versi");

  // 6. Rilis.
  await page.getByRole("button", { name: "Rilis versi Publik" }).click();
  await page.getByRole("button", { name: "Ya, rilis" }).click();
  await expect(page.getByText("Versi Publik dirilis.")).toBeVisible();
  await expect(page.locator(".chip", { hasText: "Dirilis" })).toBeVisible();
  await shot(page, "04-rina-dirilis");
  await logout(page);

  // 7. Admin melihat aksi unduh di Audit.
  await login(page, "admin", "admin-e2e-123");
  await page.goto("/admin/audit");
  await expect(page.getByRole("cell", { name: "Unduh versi" }).first()).toBeVisible();
  await expect(page.getByRole("cell", { name: "Rilis versi Publik" })).toBeVisible();
  await shot(page, "05-admin-audit");
});

test("sensor area: kotak digambar di atas nama, Publik bersih, Rahasia utuh", async ({ page }) => {
  await login(page, "rina", "sandi-e2e-123");
  await page.goto("/upload");
  await page.locator('input[type="file"]').setInputFiles(makePdf());
  await expect(page).toHaveURL(/\/dokumen\/[^/]+$/);
  await expect(page.getByText("Menunggu cek")).toBeVisible({ timeout: 60_000 });
  // Nama tidak ditandai sebagai temuan; hanya area yang menutupnya.
  await page.getByRole("tab", { name: "Halaman" }).click();
  const img = page.getByRole("img", { name: "Halaman 1" });
  await expect(img).toBeVisible();
  await expect.poll(() => img.evaluate((e: HTMLImageElement) => e.complete && e.naturalWidth > 0)).toBe(true);
  const bb = (await img.boundingBox())!;
  // Fixture A4 (595x842 pt): nama pada baseline y=160, x mulai 72, ukuran 11.
  const fx = (x: number) => bb.x + (x / 595) * bb.width;
  const fy = (y: number) => bb.y + (y / 842) * bb.height;
  await page.mouse.move(fx(60), fy(148));
  await page.mouse.down();
  await page.mouse.move(fx(130), fy(158), { steps: 5 });
  await page.mouse.move(fx(200), fy(166), { steps: 5 });
  await page.mouse.up();
  await expect(page.getByText("Area 1 · Halaman 1")).toBeVisible();
  await expect(page.locator(".area-box")).toHaveCount(1);
  await shot(page, "06-halaman-area");
  await page.getByRole("tab", { name: "Teks" }).click();

  await page.getByRole("button", { name: "Buat versi" }).click();
  await expect(page.locator(".chip", { hasText: "Disetujui" }).first()).toBeVisible({ timeout: 60_000 });
  await page.getByRole("link", { name: "Lihat tiga versi" }).click();
  await expect(page.getByRole("heading", { name: "Tiga versi" })).toBeVisible();
  const publik = pdfText(await download(page, "Publik"));
  const rahasia = pdfText(await download(page, "Rahasia"));
  expect(rahasia).toContain(NAMA);
  expect(publik).not.toContain("Rahmawati");
  expect(publik).not.toContain(NIK);
  expect(publik).toContain("Surat Keterangan");
});

test("layar ponsel 400px tanpa gulir horizontal", async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 800 });
  await login(page, "admin", "admin-e2e-123");
  for (const path of ["/", "/admin/audit", "/admin/pengguna"]) {
    await page.goto(path);
    await expect(page.getByRole("button", { name: "Keluar" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    const { sw, cw } = await page.evaluate(() => ({
      sw: document.documentElement.scrollWidth,
      cw: document.documentElement.clientWidth,
    }));
    expect(sw, path).toBeLessThanOrEqual(cw);
  }
});
