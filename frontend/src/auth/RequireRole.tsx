import type { ReactNode } from "react";
import type { Role } from "../api/types";
import { useAuth } from "./AuthProvider";

export function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user } = useAuth();
  if (!user || !roles.includes(user.role)) {
    return (
      <section className="page">
        <p className="notice" role="alert">
          Anda tidak punya akses ke halaman ini.
        </p>
      </section>
    );
  }
  return <>{children}</>;
}
