import React, { useEffect } from "react";

export function cn(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

/* ------------------------------------------------------------------ */
/* Badges & status pills                                               */
/* ------------------------------------------------------------------ */
const STATUS_STYLES: Record<string, string> = {
  // inspection lifecycle
  draft: "bg-slate-200 text-slate-700",
  under_analysis: "bg-sky-100 text-sky-800",
  analysis_complete: "bg-indigo-100 text-indigo-800",
  pending_review: "bg-amber-100 text-amber-800",
  finalized: "bg-emerald-100 text-emerald-800",
  // automated / final compliance — the four-state vocabulary
  compliant: "bg-emerald-100 text-emerald-800",
  non_compliant: "bg-red-100 text-red-800",
  review_required: "bg-amber-100 text-amber-800",
  inconclusive: "bg-slate-200 text-slate-700",
  manual_review: "bg-amber-100 text-amber-900",
  potential_non_compliance: "bg-violet-100 text-violet-800",
  // results (legacy aliases)
  pass: "bg-emerald-100 text-emerald-800",
  fail: "bg-red-100 text-red-800",
  review: "bg-amber-100 text-amber-900",
  not_applicable: "bg-slate-200 text-slate-600",
  not_evaluated: "bg-slate-100 text-slate-500",
  // field states — DETECTED / UNCERTAIN / NOT_DETECTED
  detected: "bg-emerald-100 text-emerald-800",
  uncertain: "bg-amber-100 text-amber-900",
  not_detected: "bg-slate-200 text-slate-500",
  // users
  active: "bg-emerald-100 text-emerald-800",
  pending: "bg-amber-100 text-amber-800",
  inactive: "bg-red-100 text-red-800",
  // findings inspector states
  confirmed: "bg-emerald-100 text-emerald-800",
  rejected: "bg-rose-100 text-rose-800",
  modified: "bg-sky-100 text-sky-800",
  // quality
  good: "bg-emerald-100 text-emerald-800",
  warn: "bg-amber-100 text-amber-900",
  poor: "bg-red-100 text-red-800",
  acceptable: "bg-amber-100 text-amber-900",
  linked: "bg-sky-100 text-sky-800",
  available: "bg-emerald-100 text-emerald-800",
  not_used: "bg-slate-200 text-slate-600",
  insufficient: "bg-red-100 text-red-800",
  satisfied: "bg-emerald-100 text-emerald-800",
  not_satisfied: "bg-red-100 text-red-800",
  superseded: "bg-slate-200 text-slate-600",
  // severity
  critical: "bg-red-100 text-red-800",
  major: "bg-orange-100 text-orange-800",
  minor: "bg-amber-100 text-amber-800",
  high: "bg-red-100 text-red-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-slate-200 text-slate-600",
  generated: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-800",
  queued: "bg-slate-200 text-slate-600",
};

export function humanize(key?: string | null): string {
  if (!key) return "—";
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function Badge({ value, label }: { value?: string | null; label?: string }) {
  const text = label ?? humanize(value);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap",
        STATUS_STYLES[(value || "").toLowerCase()] || "bg-slate-100 text-slate-600"
      )}
    >
      {text}
    </span>
  );
}

export function Dot({ color = "#22c55e", title }: { color?: string; title?: string }) {
  return (
    <span
      title={title}
      className="inline-block h-2.5 w-2.5 rounded-full"
      style={{ background: color }}
    />
  );
}

export function qualityColor(status: string): string {
  if (status === "good") return "#16a34a";
  if (status === "warn") return "#d97706";
  return "#dc2626";
}

export function confColor(conf: number): string {
  if (conf >= 0.9) return "#16a34a";
  if (conf >= 0.65) return "#d97706";
  return "#dc2626";
}

export function confLabel(conf: number): string {
  if (conf >= 0.9) return "High";
  if (conf >= 0.65) return "Medium";
  return "Low";
}

/* ------------------------------------------------------------------ */
/* Cards, stats, buttons                                               */
/* ------------------------------------------------------------------ */
export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>{children}</div>
  );
}

export function Stat({ icon, label, value, sub, tone = "navy" }: {
  icon?: string; label: string; value: React.ReactNode; sub?: string; tone?: string;
}) {
  const tones: Record<string, string> = {
    navy: "from-navy-700 to-navy-800",
    green: "from-emerald-600 to-emerald-700",
    red: "from-red-600 to-red-700",
    amber: "from-amber-500 to-amber-600",
    slate: "from-slate-500 to-slate-600",
    sky: "from-sky-600 to-sky-700",
  };
  return (
    <Card className="overflow-hidden">
      <div className="p-4">
        <div className="flex items-center justify-between">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
          {icon && <div className="text-lg">{icon}</div>}
        </div>
        <div className="mt-1 text-3xl font-bold text-navy-800">{value}</div>
        {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
      </div>
      <div className={cn("h-1 w-full bg-gradient-to-r", tones[tone] || tones.navy)} />
    </Card>
  );
}

type BtnVariant = "primary" | "secondary" | "danger" | "ghost" | "success";
const BTN: Record<BtnVariant, string> = {
  primary: "bg-navy-700 text-white hover:bg-navy-800 shadow-sm",
  secondary: "bg-white text-navy-700 border border-slate-300 hover:bg-slate-50",
  danger: "bg-red-700 text-white hover:bg-red-800",
  success: "bg-emerald-600 text-white hover:bg-emerald-700",
  ghost: "text-navy-700 hover:bg-slate-100",
};

export function Button({ children, variant = "primary", className = "", ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant }) {
  return (
    <button
      {...rest}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50",
        BTN[variant],
        className
      )}
    >
      {children}
    </button>
  );
}

export function PageTitle({ title, subtitle, right }: { title: string; subtitle?: string; right?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-bold text-navy-800">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {right && <div className="flex items-center gap-2">{right}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Form controls                                                       */
/* ------------------------------------------------------------------ */
export function Label({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-600">
      {children}
      {hint && <span className="ml-1 font-normal normal-case text-slate-400">({hint})</span>}
    </label>
  );
}

export const inputCls =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-navy-600 focus:ring-2 focus:ring-navy-600/20";

export function Field({ label, children, hint }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <Label hint={hint}>{label}</Label>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Modal                                                               */
/* ------------------------------------------------------------------ */
export function Modal({ open, onClose, title, children, wide = false }: {
  open: boolean; onClose: () => void; title: string; children: React.ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    const fn = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4" onClick={onClose}>
      <div
        className={cn("max-h-[90vh] w-full overflow-y-auto rounded-xl bg-white shadow-2xl", wide ? "max-w-4xl" : "max-w-xl")}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h3 className="text-sm font-bold text-navy-800">{title}</h3>
          <button onClick={onClose} className="rounded p-1 text-slate-500 hover:bg-slate-100">✕</button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-slate-500">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-navy-600 border-t-transparent" />
      <div className="text-sm">{label || "Loading…"}</div>
    </div>
  );
}

export function Empty({ icon = "🗂", text, action }: { icon?: string; text: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 py-14 text-center">
      <div className="text-4xl">{icon}</div>
      <div className="max-w-sm text-sm text-slate-500">{text}</div>
      {action}
    </div>
  );
}

export function ErrorBox({ error }: { error: string }) {
  if (!error) return null;
  return (
    <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      ⚠ {error}
    </div>
  );
}

/* Small table wrapper */
export function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto scroll-thin">
      <table className="w-full min-w-[560px] text-left text-sm">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
            {head.map((h) => (
              <th key={h} className="px-3 py-2 font-semibold">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">{children}</tbody>
      </table>
    </div>
  );
}
