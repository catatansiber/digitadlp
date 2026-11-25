import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";
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
import { Versions } from "./pages/Versions";
import { AdminLayout } from "./pages/admin/AdminLayout";
import { Audit } from "./pages/admin/Audit";
import { Employees } from "./pages/admin/Employees";
import { LabelRules } from "./pages/admin/LabelRules";
import { Units } from "./pages/admin/Units";
import { Users } from "./pages/admin/Users";

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
        <Route path="dokumen/:id/versi" element={<Versions />} />
        <Route
          path="admin"
          element={
            <RequireRole roles={["admin"]}>
              <AdminLayout />
            </RequireRole>
          }
        >
          <Route index element={<Navigate to="pengguna" replace />} />
          <Route path="pengguna" element={<Users />} />
          <Route path="unit" element={<Units />} />
          <Route path="pegawai" element={<Employees />} />
          <Route path="aturan-label" element={<LabelRules />} />
          <Route path="audit" element={<Audit />} />
        </Route>
        <Route path="*" element={<Placeholder title="Halaman tidak ditemukan" />} />
      </Route>
    </Routes>
  );
}
