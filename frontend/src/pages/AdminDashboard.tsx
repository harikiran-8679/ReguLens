import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, fmtDateTime } from "../client";
import { Badge, Button, Card, Empty, ErrorBox, PageTitle, Spinner, Stat, Table } from "../components/ui";

export default function AdminDashboard() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.get("/dashboard/admin").then(setData).catch((e) => setError(e.message));
  }, []);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner label="Loading admin dashboard…" />;
  const s = data.stats;
  const catData = Object.entries(data.inspections_by_category || {}).map(([k, v]) => ({
    name: k.replace(/_/g, " "),
    value: v as number,
  }));

  return (
    <div>
      <PageTitle title="Admin Dashboard" subtitle="Overview of system activity and inspector access" />
      {/* C2: sm:grid-cols-2 for 2-up at 640px, lg:grid-cols-5 for full row */}
      <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-5">
        <Stat icon="👮" label="Total Inspectors" value={s.total_inspectors} sub="Registered in system" />
        <Stat icon="🟢" label="Active Inspectors" value={s.active_inspectors} sub="Currently authorized" tone="green" />
        <Stat icon="🕐" label="Pending Access" value={s.pending_access} sub="Awaiting activation" tone="amber" />
        <Stat icon="📋" label="Total Inspections" value={s.total_inspections} sub="Across the system" tone="sky" />
        <Stat icon="⚠" label="System Alerts" value={s.system_alerts} sub="Require attention" tone="red" />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <span className="text-xs font-bold uppercase tracking-widest text-slate-500">INSPECTOR ACCESS</span>
            <Link to="/admin/inspectors"><Button variant="secondary" className="px-3 py-1 text-xs">+ Add</Button></Link>
          </div>
          {/* C2: horizontal scroll on narrow viewports */}
          <div className="overflow-x-auto -mx-4 px-4">
            <Table head={["Inspector", "Status", "Inspections", "Review"]}>
              {(data.inspector_access || []).map((u: any) => (
                <tr key={u.username}>
                  <td className="px-3 py-2 min-w-[120px]">
                    <div className="font-semibold text-navy-700 text-xs sm:text-sm">{u.username}</div>
                    <div className="text-[10px] sm:text-xs text-slate-400 hidden sm:block">{u.full_name}</div>
                  </td>
                  <td className="px-3 py-2"><Badge value={u.status} /></td>
                  <td className="px-3 py-2 text-center">{u.inspections}</td>
                  <td className="px-3 py-2 text-center">{u.pending_review}</td>
                </tr>
              ))}
            </Table>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Link to="/admin/inspectors"><Button variant="secondary" className="px-3 py-1 text-xs">VIEW ALL INSPECTORS</Button></Link>
            <Link to="/admin/inspectors"><Button className="px-3 py-1 text-xs">+ ADD INSPECTOR</Button></Link>
          </div>
        </Card>

        <Card className="p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-500">INSPECTIONS BY CATEGORY</div>
          {catData.length === 0 ? (
            <Empty icon="📊" text="No inspections recorded yet." />
          ) : (
            <div className="overflow-x-auto">
              <div className="h-60 min-w-[260px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={catData} layout="vertical" margin={{ left: 10, right: 8 }}>
                    <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10 }} />
                    <YAxis type="category" dataKey="name" width={90} tick={{ fontSize: 10 }} />
                    <Tooltip />
                    <Bar dataKey="value" fill="#1a3a5c" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
            <div><div className="font-bold text-emerald-700">{s.compliant}</div><div className="text-slate-400">Compliant</div></div>
            <div><div className="font-bold text-red-700">{s.non_compliant}</div><div className="text-slate-400">Non-Compliant</div></div>
            <div><div className="font-bold text-amber-600">{s.pending_review}</div><div className="text-slate-400">Pending Review</div></div>
          </div>
        </Card>
      </div>

      <Card className="mt-6 p-5">
        <div className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-500">RECENT SYSTEM ACTIVITY</div>
        {data.activity.length === 0 ? (
          <Empty icon="🪵" text="No activity recorded yet." />
        ) : (
          <ul className="space-y-2">
            {data.activity.map((a: any) => (
              <li key={a.id} className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-1 sm:gap-4 rounded-lg bg-slate-50 px-3 py-2 text-sm">
                <div className="min-w-0">
                  <span className="font-semibold text-navy-700 break-words">{a.action.replace(/_/g, " ")}</span>
                  {a.entity_id && <span className="text-slate-500"> — <span className="break-all">{a.entity_id}</span></span>}
                  <div className="text-xs text-slate-400">by {a.actor} ({a.actor_role})</div>
                </div>
                <div className="shrink-0 text-xs text-slate-400">{fmtDateTime(a.created_at)}</div>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3">
          <Link to="/admin/audit"><Button variant="secondary" className="px-3 py-1 text-xs">VIEW AUDIT LOGS</Button></Link>
        </div>
      </Card>
    </div>
  );
}
