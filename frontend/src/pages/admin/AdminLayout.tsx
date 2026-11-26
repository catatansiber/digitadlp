import { NavLink, Outlet } from "react-router-dom";

const TABS = [
  { to: "/admin/pengguna", label: "Pengguna" },
  { to: "/admin/unit", label: "Unit" },
  { to: "/admin/aturan-label", label: "Aturan label" },
  { to: "/admin/audit", label: "Audit" },
];

export function AdminLayout() {
  return (
    <div className="page">
      <nav className="tabs subnav" aria-label="Menu admin">
        {TABS.map((t) => (
          <NavLink key={t.to} to={t.to}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
