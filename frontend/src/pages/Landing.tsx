import { Link } from "react-router-dom";
import { Button } from "../components/ui";

const capabilities = [
  { icon: "📷", title: "Image Scanning", text: "Capture or upload package photographs for inspection." },
  { icon: "🔍", title: "OCR Extraction", text: "Extract product declarations and package information from images." },
  { icon: "⚖️", title: "Rule Validation", text: "Evaluate extracted information against applicable Legal Metrology requirements and rule versions." },
  { icon: "📄", title: "Inspection Reports", text: "Generate structured inspection reports with findings, observations and evidence." },
];

const checks = [
  "Mandatory Declarations", "Net Quantity", "MRP", "Manufacturer / Packer / Importer",
  "Consumer Care Details", "Date Declarations", "Font Size & Readability", "Placement & Format",
];

const flow = ["SCAN", "OCR / EXTRACT", "IDENTIFY RULES", "RULE ENGINE", "COMPLIANCE RESULT", "INSPECTOR REVIEW", "FINAL REPORT"];

export default function Landing() {
  return (
    <div className="min-h-screen bg-white text-slate-800">
      {/* Nav */}
      <nav className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-2xl">⚖️</span>
            <div className="leading-tight">
              <div className="text-sm font-extrabold tracking-wide text-navy-800">LEGAL METROLOGY</div>
              <div className="text-[10px] font-semibold tracking-[0.25em] text-slate-400">COMPLIANCE SYSTEM</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link to="/login/admin"><Button variant="secondary">Admin Login</Button></Link>
            <Link to="/login/inspector"><Button>Inspector Login</Button></Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative overflow-hidden bg-gradient-to-br from-navy-800 via-navy-700 to-navy-900 text-white">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 md:grid-cols-2 md:py-20">
          <div>
            <div className="mb-3 inline-block rounded-full bg-white/10 px-3 py-1 text-xs font-bold tracking-widest text-sky-200">
              AI-ASSISTED LEGAL METROLOGY INSPECTION
            </div>
            <h1 className="text-3xl font-extrabold leading-tight md:text-4xl">
              Smarter. Faster. Evidence-Based Package Inspection.
            </h1>
            <p className="mt-4 max-w-lg text-slate-300">
              Analyze packaged commodity labels using image processing, OCR and a version-aware
              Legal Metrology rule engine — where the AI assists the inspector, never replaces
              the final assessment.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link to="/login/inspector">
                <button className="inline-flex items-center gap-2 rounded-lg border border-white/30 bg-white/10 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white/20">
                  ⚖️ INSPECTOR LOGIN
                </button>
              </Link>
              <Link to="/login/admin">
                {/* Standalone raw button — no base component to conflict with */}
                <button
                  style={{ backgroundColor: "#ffffff", color: "#1a3a5c" }}
                  className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold shadow-sm transition hover:opacity-90"
                >
                  ⚙️ ADMIN LOGIN
                </button>
              </Link>
            </div>

          </div>
          {/* Hero visual */}
          <div className="rounded-2xl border border-white/15 bg-white/5 p-5 backdrop-blur">
            <div className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-300">Package Analysis</div>
            <div className="flex h-40 items-center justify-center rounded-xl bg-gradient-to-br from-sky-900/60 to-slate-900 text-6xl">
              📦
            </div>
            <div className="mt-3 divide-y divide-white/10 text-sm">
              {[
                ["Product Name", "✓", "text-emerald-400"],
                ["Net Quantity", "✓", "text-emerald-400"],
                ["MRP", "✓", "text-emerald-400"],
                ["Manufacturer Details", "✓", "text-emerald-400"],
                ["Consumer Care", "⚠", "text-amber-400"],
              ].map(([k, v, c]) => (
                <div key={k as string} className="flex items-center justify-between py-1.5 text-slate-200">
                  <span>{k}</span><span className={(c as string) + " font-bold"}>{v}</span>
                </div>
              ))}
            </div>
            <div className="mt-3 flex items-center justify-between rounded-lg bg-navy-900/70 px-3 py-2 text-xs">
              <span className="font-bold tracking-wide text-sky-200">OCR → RULE ENGINE</span>
              <span><span className="font-bold text-emerald-400">7 CHECKS PASSED</span> · <span className="font-bold text-amber-400">1 REVIEW REQUIRED</span></span>
            </div>
          </div>
        </div>
      </section>

      {/* Core capabilities */}
      <section className="mx-auto max-w-6xl px-4 py-14">
        <h2 className="text-center text-2xl font-extrabold text-navy-800">CORE CAPABILITIES</h2>
        <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {capabilities.map((c) => (
            <div key={c.title} className="rounded-xl border border-slate-200 bg-slate-50 p-5 text-center">
              <div className="text-3xl">{c.icon}</div>
              <div className="mt-2 font-bold text-navy-800">{c.title}</div>
              <p className="mt-1 text-xs text-slate-500">{c.text}</p>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="bg-slate-50 py-14">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="text-center text-2xl font-extrabold text-navy-800">HOW IT WORKS</h2>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-2">
            {flow.map((f, i) => (
              <div key={f} className="flex items-center gap-2">
                <div className="rounded-full bg-navy-700 px-4 py-2 text-xs font-bold text-white">{f}</div>
                {i < flow.length - 1 && <span className="text-slate-400">→</span>}
              </div>
            ))}
          </div>
          <p className="mt-6 text-center text-sm text-slate-500">
            The AI assists the inspector rather than replacing the inspector's final assessment.
          </p>
        </div>
      </section>

      {/* Version-aware engine */}
      <section className="mx-auto max-w-6xl px-4 py-14">
        <h2 className="text-center text-2xl font-extrabold text-navy-800">VERSION-AWARE RULE ENGINE</h2>
        <div className="mx-auto mt-6 max-w-3xl rounded-xl border border-slate-200 p-6 text-center">
          <div className="flex flex-wrap items-center justify-center gap-1 text-xs font-bold">
            {["2011 RULES", "AMENDMENTS", "VERSIONED RULES", "EFFECTIVE DATES", "APPLICABLE RULE", "RULE ENGINE", "COMPLIANCE RESULT"].map((s, i, a) => (
              <span key={s} className="flex items-center gap-1">
                <span className="rounded bg-navy-50 px-2 py-1 text-navy-700">{s}</span>
                {i < a.length - 1 && <span>→</span>}
              </span>
            ))}
          </div>
          <p className="mt-4 text-xs text-slate-500">
            The system maintains applicable rule versions and amendment history so package declarations
            are evaluated against the requirements in force on the inspection date.
          </p>
        </div>
      </section>

      {/* What the system checks */}
      <section className="bg-slate-50 py-14">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="text-center text-2xl font-extrabold text-navy-800">WHAT THE SYSTEM CHECKS</h2>
          <div className="mx-auto mt-8 grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {checks.map((c) => (
              <div key={c} className="rounded-lg border border-slate-200 bg-white p-4 text-center text-sm font-semibold text-navy-700">
                {c}
              </div>
            ))}
          </div>
          <p className="mt-4 text-center text-xs text-slate-500">
            Font &amp; readability results are estimates that flag potential issues for inspector review —
            they are never presented as automatically conclusive physical measurements.
          </p>
        </div>
      </section>

      {/* Roles */}
      <section className="mx-auto max-w-6xl px-4 py-14">
        <h2 className="text-center text-2xl font-extrabold text-navy-800">One Platform. Two Authorized Roles.</h2>
        <div className="mt-8 grid gap-6 md:grid-cols-2">
          <div className="rounded-xl border-2 border-slate-200 p-6">
            <div className="text-lg font-extrabold text-navy-800">⚙️ ADMIN</div>
            {/* C3: upgraded from text-slate-400 to text-slate-600 for 4.5:1 contrast on white */}
            <div className="text-xs font-semibold uppercase tracking-widest text-slate-600">System Administration</div>
            <ul className="mt-3 space-y-1.5 text-sm text-slate-700">
              <li>• Manage Inspector Access</li><li>• Create Inspector Accounts</li>
              <li>• Assign Roles &amp; Permissions</li><li>• Activate / Deactivate Access</li>
              <li>• Manage Rules &amp; Standards</li><li>• Monitor Activity &amp; Audit Logs</li>
            </ul>
          </div>
          <div className="rounded-xl border-2 border-navy-700 p-6">
            <div className="text-lg font-extrabold text-navy-800">⚖️ INSPECTOR</div>
            <div className="text-xs font-semibold uppercase tracking-widest text-slate-600">Field Inspection</div>
            <ul className="mt-3 space-y-1.5 text-sm text-slate-700">
              <li>• Create Inspections</li><li>• Capture Package Images</li>
              <li>• Run OCR &amp; Review Extracted Data</li><li>• Run Rule Analysis</li>
              <li>• Review Violations &amp; Add Evidence</li><li>• Generate Reports</li>
            </ul>
          </div>
        </div>
        <div className="mx-auto mt-10 max-w-2xl rounded-xl bg-navy-50 p-6 text-center border border-navy-200">
          <div className="text-sm font-bold uppercase tracking-widest text-navy-800">AUTHORIZED SYSTEM ACCESS</div>
          {/* C3: text-slate-500 → text-slate-700 on bg-navy-50 (light cream bg) */}
          <p className="mt-1 text-xs text-slate-700">
            Inspector accounts are provisioned and managed by authorized administrators. No public registration, no consumer portal.
          </p>
          <div className="mt-4 flex justify-center gap-3">
            <Link to="/login/admin"><Button variant="secondary">⚙️ Admin Login</Button></Link>
            <Link to="/login/inspector"><Button>⚖️ Inspector Login</Button></Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-slate-200 bg-navy-900 py-8 text-center text-slate-300">
        <div className="font-bold text-white">⚖️ LEGAL METROLOGY COMPLIANCE SYSTEM</div>
        <div className="mt-1 text-xs text-slate-300">AI-assisted inspection • Rule-based validation • Evidence-based reporting</div>
        <div className="mt-3 flex justify-center gap-4 text-xs text-slate-300">
          <Link to="/login/admin" className="hover:text-white transition-colors">Admin Login</Link>
          <Link to="/login/inspector" className="hover:text-white transition-colors">Inspector Login</Link>
        </div>
        <div className="mt-3 text-xs text-slate-400">&copy; 2026</div>
      </footer>
    </div>
  );
}
