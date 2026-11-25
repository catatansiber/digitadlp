export const FALLBACK_MESSAGE = "Terjadi kesalahan. Coba lagi.";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function url(path: string): string {
  // Absolut terhadap origin halaman agar juga berjalan di lingkungan tes.
  return new URL("/api" + path, window.location.href).toString();
}

async function errorFrom(res: Response): Promise<ApiError> {
  let detail = FALLBACK_MESSAGE;
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object" && "detail" in body) {
      const d = (body as { detail: unknown }).detail;
      if (typeof d === "string" && d) detail = d;
    }
  } catch {
    // body bukan JSON: pakai pesan umum
  }
  return new ApiError(res.status, detail);
}

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body != null && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  let res: Response;
  try {
    res = await fetch(url(path), { ...init, headers, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, FALLBACK_MESSAGE);
  }
  if (!res.ok) throw await errorFrom(res);
  return res;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await send(path, init);
  if (res.status === 204) return undefined as T;
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError(res.status, FALLBACK_MESSAGE);
  }
}

function filenameFrom(cd: string | null): string {
  if (!cd) return "unduhan";
  const star = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(cd);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      /* lanjut */
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(cd);
  return plain ? plain[1].trim() : "unduhan";
}

export async function apiBlob(path: string): Promise<{ blob: Blob; filename: string }> {
  const res = await send(path, { headers: { Accept: "*/*" } });
  return { blob: await res.blob(), filename: filenameFrom(res.headers.get("Content-Disposition")) };
}
