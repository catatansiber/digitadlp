import { ApiError, FALLBACK_MESSAGE } from "./client";

/** Unggah dengan progres (fetch tidak punya progres unggah). Pemetaan galat sama dengan api(). */
const UPLOAD_TIMEOUT_MS = 10 * 60 * 1000;

export function uploadDocument<T>(
  file: File,
  onProgress?: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    if (signal?.aborted) return reject(new ApiError(0, FALLBACK_MESSAGE));
    const xhr = new XMLHttpRequest();
    xhr.timeout = UPLOAD_TIMEOUT_MS;
    xhr.ontimeout = () => reject(new ApiError(0, "Unggahan terlalu lama. Coba lagi."));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.open("POST", new URL("/api/documents", window.location.href).toString());
    xhr.setRequestHeader("Accept", "application/json");
    xhr.withCredentials = true;
    xhr.responseType = "text";
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) onProgress?.(e.loaded / e.total);
    };
    xhr.onerror = () => reject(new ApiError(0, FALLBACK_MESSAGE));
    xhr.onabort = () => reject(new ApiError(0, FALLBACK_MESSAGE));
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* bukan JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        if (body == null) return reject(new ApiError(xhr.status, FALLBACK_MESSAGE));
        return resolve(body as T);
      }
      let detail = FALLBACK_MESSAGE;
      if (body && typeof body === "object" && "detail" in body) {
        const d = (body as { detail: unknown }).detail;
        if (typeof d === "string" && d) detail = d;
      }
      reject(new ApiError(xhr.status, detail));
    };
    const fd = new FormData();
    fd.append("file", file);
    xhr.send(fd);
  });
}
