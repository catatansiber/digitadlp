import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { Route, Routes } from "react-router-dom";
import { ApiError } from "./api/client";
import { emitSessionExpired } from "./auth/sessionEvents";
import { RequireAuth } from "./auth/RequireAuth";
import { RequireRole } from "./auth/RequireRole";
import { Layout } from "./components/Layout";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { Upload } from "./pages/Upload";
import { Placeholder } from "./pages/Placeholder";
import { Review } from "./pages/Review";

function on401(err: unknown) {
  if (err instanceof ApiError && err.status === 401) emitSessionExpired();
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({ onError: on401 }),
    mutationCache: new MutationCache({ onError: on401 }),
    defaultOptions: {
      queries: { retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 2, refetchOnWindowFocus: false },
    },
  });
}

const admin = (title: string) => (
  <RequireRole roles={["admin"]}>
    <Placeholder title={title} />
  </RequireRole>
);

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/masuk" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route
          path="upload"
          element={
            <RequireRole roles={["pengunggah", "pemeriksa"]}>
              <Upload />
            </RequireRole>
          }
        />
        <Route path="dokumen/:id" element={<Review />} />
        <Route path="dokumen/:id/versi" element={<Placeholder title="Versi dokumen" />} />
        <Route path="admin/pengguna" element={admin("Pengguna")} />
        <Route path="admin/unit" element={admin("Unit")} />
        <Route path="admin/pegawai" element={admin("Pegawai")} />
        <Route path="admin/aturan-label" element={admin("Aturan label")} />
        <Route path="admin/audit" element={admin("Audit")} />
        <Route path="*" element={<Placeholder title="Halaman tidak ditemukan" />} />
      </Route>
    </Routes>
  );
}
