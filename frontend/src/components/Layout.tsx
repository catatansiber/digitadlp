import { NavLink, Outlet } from "react-router-dom";
import type { Role } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { Button } from "./Button";

const TABS: { to: string; label: string; roles: Role[]; end?: boolean }[] = [
  { to: "/", label: "Beranda", roles: ["pengunggah", "pemeriksa", "admin"], end: true },
  { to: "/upload", label: "Unggah", roles: ["pengunggah", "pemeriksa"] },
  { to: "/admin/pengguna", label: "Admin", roles: ["admin"] },
];

export function Layout() {
  const { user, logout } = useAuth();
  if (!user) return null;
  return (
    <div className="app">
      <header className="bar">
        <span className="logo">DigitaDLP</span>
        <span className="who">
          {user.unit} · {user.full_name}
        </span>
        <nav className="tabs" aria-label="Menu utama">
          {TABS.filter((t) => t.roles.includes(user.role)).map((t) => (
            <NavLink key={t.to} to={t.to} end={t.end}>
              {t.label}
            </NavLink>
          ))}
        </nav>
        <Button onClick={() => void logout()}>Keluar</Button>
      </header>
      <main className="screen">
        <Outlet />
      </main>
    </div>
  );
}
