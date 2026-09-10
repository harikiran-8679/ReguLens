import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { Button, ErrorBox } from "../components/ui";

export default function LoginPage({ mode }: { mode: "inspector" | "admin" }) {
  const isAdmin = mode === "admin";
  const { login } = useAuth();
  const navigate = useNavigate();
  const demoCreds = isAdmin
    ? { username: "admin@demo.com", password: "Admin@123", label: "Demo Admin" }
    : { username: "inspector@demo.com", password: "Inspector@123", label: "Demo Inspector" };
  // Inputs start empty — the demo credentials box below is a purely visual
  // reference (copyable text) and must never pre-fill or reset the real fields,
  // otherwise accounts created by Admin could not log in.
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const user = await login(username.trim(), password);
      navigate(user.role === "admin" ? "/admin/dashboard" : "/inspector/dashboard", { replace: true });
    } catch (err: any) {
      setError(err.message || "Login failed. Please verify your credentials and try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-slate-100">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
        <div className="flex items-center gap-2">
          <span className="text-2xl">⚖️</span>
          <div className="leading-tight">
            <div className="text-sm font-extrabold tracking-wide text-navy-800">LEGAL METROLOGY</div>
            <div className="text-[10px] font-semibold tracking-[0.25em] text-slate-400">COMPLIANCE SYSTEM</div>
          </div>
        </div>
        <Link to="/" className="text-xs font-semibold text-slate-500 hover:text-navy-700">← Back to Main Page</Link>
      </header>

      <div className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-md">
          <div className="mb-5 text-center">
            <div className="text-4xl">{isAdmin ? "⚙️" : "⚖️"}</div>
            <div className="mt-1 text-xs font-bold uppercase tracking-[0.3em] text-slate-400">
              {isAdmin ? "Administration Portal" : "Inspector Portal"}
            </div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-7 shadow-lg">
            <h1 className="text-xl font-extrabold text-navy-800">{isAdmin ? "Admin Login" : "Inspector Login"}</h1>
            <p className="mt-1 text-sm text-slate-500">
              {isAdmin
                ? "Sign in to manage inspector access, permissions, rules and system configuration."
                : "Sign in to access the inspection and compliance workspace."}
            </p>
            <ErrorBox error={error} />
            <form onSubmit={submit} className="mt-5 space-y-4">
              <div>
                <label className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-600">
                  {isAdmin ? "Admin ID" : "Inspector ID"}
                </label>
                <input
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-navy-600 focus:ring-2 focus:ring-navy-600/20"
                  placeholder={isAdmin ? "Enter Admin ID (e.g. ADM-001)" : "Enter Inspector ID (e.g. LM-INS-00125)"}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoFocus
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-600">Password</label>
                <div className="relative">
                  <input
                    type={showPw ? "text" : "password"}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 pr-10 text-sm outline-none focus:border-navy-600 focus:ring-2 focus:ring-navy-600/20"
                    placeholder="Enter Password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  <button type="button" onClick={() => setShowPw((v) => !v)} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400">
                    {showPw ? "🙈" : "👁"}
                  </button>
                </div>
              </div>
              <Button type="submit" disabled={busy} className="w-full py-2.5">
                {busy ? "⟳ AUTHENTICATING..." : `🔐 LOGIN`}
              </Button>
            </form>
            <div className="mt-4 rounded-lg bg-slate-50 px-3 py-2 text-center text-xs text-slate-500">
              🔒 {isAdmin ? "Authorized administrators only." : "Authorized inspectors only. Access is provisioned by an authorized administrator."}
            </div>
            <div className="mt-4 rounded-lg border border-dashed border-navy-300 bg-navy-50/60 px-3 py-2 text-center text-xs">
              <div className="font-extrabold uppercase tracking-widest text-navy-700">🔑 Demo {isAdmin ? "Admin" : "Inspector"} credentials</div>
              <div className="mt-1 font-mono text-[12px] text-navy-800">
                {demoCreds.username} / {demoCreds.password}
              </div>
              {!isAdmin && (
                <div className="mt-1 text-[10px] text-slate-500">Alt: LM-INS-00125 / inspector123 · LM-INS-00131 / inspector123</div>
              )}
              {isAdmin && (
                <div className="mt-1 text-[10px] text-slate-500">Alt: ADM-001 / admin123</div>
              )}
            </div>
          </div>
        </div>
      </div>
      <footer className="pb-4 text-center text-xs text-slate-400">© 2026 · Legal Metrology Compliance System</footer>
    </div>
  );
}
