import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { api, fmtDate } from "../client";
import { useAuth } from "../auth";
import { Badge, Button, Card, Empty, ErrorBox, PageTitle, Spinner, Stat, Table } from "../components/ui";

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good Morning";
  if (h < 17) return "Good Afternoon";
  return "Good Evening";
}

const OUTCOME_COLORS: Record<string, string> = {
  COMPLIANT: "#16a34a",
  NON_COMPLIANT: "#dc2626",
  MANUAL_REVIEW: "#d97706",
  POTENTIAL_NON_COMPLIANCE: "#7c3aed",
};

export default function InspectorDashboard() {
  const { user } = useAuth();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get("/dashboard/inspector")
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner label="Loading dashboard…" />;
  const s = data.stats;
  const chart = Object.entries(data.outcome_chart || {}).map(([k, v]) => ({ name: k.replace(/_/g, " "), key: k, value: v as number }));

  return (
    <div>
      <PageTitle
        title={`${greeting()}, ${user?.full_name?.split(" ")[0] || "Inspector"}`}
        subtitle="Here's your inspection overview."
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat icon="📋" label="Total Inspections" value={s.total} sub="Your inspections" tone="navy" />
        <Stat icon="✓" label="Compliant" value={s.compliant} sub="Finalised assessment" tone="green" />
        <Stat icon="⚠" label="Non-Compliant" value={s.non_compliant} sub="Finalised assessment" tone="red" />
        <Stat icon="🕐" label="Pending Review" value={s.pending_review} sub="Require inspector review" tone="amber" />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-500">QUICK ACTIONS</div>
          <div className="grid grid-cols-2 gap-3">
            <Link to="/inspector/new" className="flex flex-col justify-center gap-1 rounded-xl bg-navy-700 p-4 text-white hover:bg-navy-800">
              <span className="text-2xl">➕</span>
              <span className="text-sm font-bold">NEW INSPECTION</span>
              <span className="text-[11px] text-slate-300">Start a package compliance inspection</span>
            </Link>
            <Link to="/inspector/pending" className="flex flex-col justify-center gap-1 rounded-xl bg-amber-500 p-4 text-white hover:bg-amber-600">
              <span className="text-2xl">🕐</span>
              <span className="text-sm font-bold">PENDING REVIEW</span>
              <span className="text-[11px] text-amber-50">Review inspections needing attention</span>
            </Link>
            <Link to="/inspector/my" className="flex flex-col justify-center gap-1 rounded-xl bg-slate-100 p-4 text-navy-800 hover:bg-slate-200">
              <span className="text-2xl">📋</span>
              <span className="text-sm font-bold">MY INSPECTIONS</span>
              <span className="text-[11px] text-slate-500">View inspection history</span>
            </Link>
            <Link to="/inspector/reports" className="flex flex-col justify-center gap-1 rounded-xl bg-slate-100 p-4 text-navy-800 hover:bg-slate-200">
              <span className="text-2xl">📄</span>
              <span className="text-sm font-bold">VIEW REPORTS</span>
              <span className="text-[11px] text-slate-500">Access generated reports</span>
            </Link>
          </div>
        </Card>

        <Card className="p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-500">COMPLIANCE OVERVIEW</div>
          {chart.length === 0 ? (
            <Empty icon="📊" text="No analysed inspections yet. Start a new inspection." />
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={chart} dataKey="value" nameKey="name" innerRadius={45} outerRadius={80} paddingAngle={3}>
                    {chart.map((c) => (
                      <Cell key={c.name} fill={OUTCOME_COLORS[c.key] || "#64748b"} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="mt-2 text-center text-xs text-slate-500">Total: {s.total} inspection(s) · outcomes by automated analysis</div>
        </Card>

        <Card className="p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-500">NOTIFICATIONS</div>
          <ul className="space-y-2">
            {(data.notifications || []).map((n: any, i: number) => (
              <li key={i} className="flex items-start gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-700">
                <span>{n.type === "warning" ? "⚠" : "ℹ"}</span> {n.text}
              </li>
            ))}
          </ul>
          <div className="mt-3 text-[11px] text-slate-400">Pending review items are kept separate from draft inspections.</div>
        </Card>
      </div>

      {/* Pending review strip */}
      {data.pending?.length > 0 && (
        <Card className="mt-6 p-5">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-widest text-slate-500">PENDING REVIEW</span>
            <Link to="/inspector/pending" className="text-xs font-semibold text-navy-700 hover:underline">VIEW ALL</Link>
          </div>
          <Table head={["Inspection", "Product", "Analysis", "Findings", "Status", "Action"]}>
            {data.pending.map((p: any) => (
              <tr key={p.id}>
                <td className="px-3 py-2 font-semibold text-navy-700">{p.inspection_id}</td>
                <td className="px-3 py-2">{p.product_name}</td>
                <td className="px-3 py-2"><Badge value={p.automated_result} /></td>
                <td className="px-3 py-2">
                  <span className="text-red-700 font-semibold">{p.violations_count} fail</span>
                  <span className="ml-2 text-amber-700 font-semibold">{p.review_count} review</span>
                </td>
                <td className="px-3 py-2"><Badge value={p.status} /></td>
                <td className="px-3 py-2">
                  <Link to={`/inspector/inspections/${p.id}/review`}>
                    <Button variant="secondary" className="px-3 py-1 text-xs">REVIEW</Button>
                  </Link>
                </td>
              </tr>
            ))}
          </Table>
        </Card>
      )}

      {/* Recent inspections */}
      <Card className="mt-6 p-5">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-xs font-bold uppercase tracking-widest text-slate-500">RECENT INSPECTIONS</span>
          <Link to="/inspector/my" className="text-xs font-semibold text-navy-700 hover:underline">VIEW ALL INSPECTIONS</Link>
        </div>
        {data.recent.length === 0 ? (
          <Empty icon="📦" text="No inspections yet." action={<Link to="/inspector/new"><Button>+ New Inspection</Button></Link>} />
        ) : (
          <Table head={["Inspection", "Product", "Date", "Status", "Result", "Violations"]}>
            {data.recent.map((r: any) => (
              <tr key={r.id} className="hover:bg-slate-50">
                <td className="px-3 py-2 font-semibold text-navy-700">
                  <Link to={stepLink(r)} className="hover:underline">{r.inspection_id}</Link>
                </td>
                <td className="px-3 py-2">{r.product_name || "—"}</td>
                <td className="px-3 py-2">{fmtDate(r.inspection_date)}</td>
                <td className="px-3 py-2"><Badge value={r.status} /></td>
                <td className="px-3 py-2"><Badge value={r.automated_result} /></td>
                <td className="px-3 py-2">
                  {r.status === "draft" ? (
                    <span className="text-slate-400">—</span>
                  ) : (
                    <span>
                      <span className="font-bold text-red-700">{r.violations_count}</span>
                      <span className="ml-2 font-bold text-amber-700">{r.review_count} rev.</span>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}

function stepLink(r: any): string {
  if (r.status === "draft") return `/inspector/inspections/${r.id}/capture`;
  if (r.status === "pending_review") return `/inspector/inspections/${r.id}/review`;
  if (r.status === "finalized") return `/inspector/inspections/${r.id}/report`;
  return `/inspector/inspections/${r.id}/ocr`;
}
