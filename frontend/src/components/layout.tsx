import React, { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { cn } from "./ui";

interface NavItem {
  to: string;
  icon: string;
  label: string;
  end?: boolean;
}

const INSPECTOR_NAV: NavItem[] = [
  { to: "/inspector/dashboard", icon: "🏠", label: "Dashboard" },
  { to: "/inspector/new", icon: "➕", label: "New Inspection" },
  { to: "/inspector/my", icon: "📋", label: "My Inspections" },
  { to: "/inspector/pending", icon: "🕐", label: "Pending Review" },
  { to: "/inspector/reports", icon: "📄", label: "Reports" },
  { to: "/inspector/rules", icon: "⚖️", label: "Rules & Standards" },
];

const ADMIN_NAV: NavItem[] = [
  { to: "/admin/dashboard", icon: "🏠", label: "Dashboard" },
  { to: "/admin/inspectors", icon: "👮", label: "Inspectors" },
  { to: "/admin/rules", icon: "⚖️", label: "Rules & Standards" },
  { to: "/admin/audit", icon: "📋", label: "Audit Logs" },
];

function Brand() {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xl">⚖️</span>
      <div className="leading-tight">
        <div className="text-sm font-extrabold tracking-wide text-white">LEGAL METROLOGY</div>
        <div className="text-[11px] font-semibold tracking-[0.2em] text-slate-300">COMPLIANCE SYSTEM</div>
      </div>
    </div>
  );
}

export function Shell({ role }: { role: "inspector" | "admin" }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  if (!user || user.role !== role) return null;
  const nav = role === "inspector" ? INSPECTOR_NAV : ADMIN_NAV;
  const portal = role === "inspector" ? "Inspector Portal" : "Administration Portal";

  const sidebar = (
    <div className="flex h-full flex-col bg-navy-800">
      <div className="border-b border-white/10 p-4"><Brand /></div>
      <div className="px-4 pt-3 text-[10px] font-bold uppercase tracking-widest text-slate-400">{portal}</div>
      <nav className="flex-1 space-y-0.5 overflow-y-auto p-2 scroll-thin">
        {nav.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={() => setMobileOpen(false)}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
                isActive ? "bg-white/15 text-white" : "text-slate-300 hover:bg-white/5 hover:text-white"
              )
            }
          >
            <span>{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-white/10 p-3 text-[11px] text-slate-400">
        Legal Metrology (Packaged Commodities) Rules, 2011 · v1.0
      </div>
    </div>
  );

  return (
    <div className="flex h-screen overflow-hidden max-w-full">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 md:block">{sidebar}</aside>
      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-slate-900/60" onClick={() => setMobileOpen(false)} />
          <aside className="absolute left-0 top-0 h-full w-60">{sidebar}</aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 shadow-sm">
          <div className="flex items-center gap-2 md:hidden">
            <button onClick={() => setMobileOpen(true)} className="rounded p-1 text-xl">☰</button>
            <span className="text-xs font-extrabold tracking-wide text-navy-800">LM SYSTEM</span>
          </div>
          <div className="hidden text-xs font-semibold text-slate-400 md:block">
            {user.full_name || user.username} · {user.department || portal}
          </div>
          <div className="relative">
            <button
              onClick={() => setMenuOpen((v) => !v)}
              className="flex items-center gap-2 rounded-lg px-2 py-1 hover:bg-slate-100"
            >
              <span>🔔</span>
              <span className="hidden text-sm font-semibold text-navy-800 sm:inline">
                {user.username} ▾
              </span>
            </button>
            {menuOpen && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                <div className="absolute right-0 z-20 mt-1 w-48 rounded-lg border border-slate-200 bg-white py-1 shadow-xl">
                  <div className="border-b border-slate-100 px-3 py-2 text-xs text-slate-500">
                    {user.full_name}
                    <div className="font-semibold text-navy-800">{user.username}</div>
                  </div>
                  <button
                    className="block w-full px-3 py-2 text-left text-sm text-red-700 hover:bg-red-50"
                    onClick={() => {
                      logout();
                      navigate("/");
                    }}
                  >
                    🚪 Logout
                  </button>
                </div>
              </>
            )}
          </div>
        </header>
        <main className="flex-1 overflow-y-auto overflow-x-hidden bg-slate-100 p-4 md:p-6">
          <div className="mx-auto max-w-6xl min-w-0">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

export function RequireAuth({ role, children }: { role: "inspector" | "admin"; children: React.ReactNode }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  if (!user) {
    navigate(`/login/${role}`, { replace: true });
    return null;
  }
  if (user.role !== role) {
    navigate(user.role === "admin" ? "/admin/dashboard" : "/inspector/dashboard", { replace: true });
    return null;
  }
  return <>{children}</>;
}
