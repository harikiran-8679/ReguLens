import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, fmtDate } from "../client";
import { Badge, Button, Card, Empty, ErrorBox, PageTitle, Spinner, Table, inputCls } from "../components/ui";

const STATUS_FILTERS = ["", "draft", "pending_review", "analysis_complete", "finalized"];

export default function MyInspections() {
  const navigate = useNavigate();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");

  const load = () => {
    setLoading(true);
    api.get(`/inspections?q=${encodeURIComponent(q)}&status=${status}`)
      .then((d) => setItems(d.items))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, status]);

  const stepPath = (r: any) => {
    if (r.status === "draft") return `/inspector/inspections/${r.id}/capture`;
    if (r.status === "pending_review") return `/inspector/inspections/${r.id}/review`;
    if (r.status === "finalized") return `/inspector/inspections/${r.id}/report`;
    return `/inspector/inspections/${r.id}/ocr`;
  };

  return (
    <div>
      <PageTitle
        title="My Inspections"
        subtitle="History scoped to your account — searchable and queryable per inspector."
        right={<Link to="/inspector/new"><Button>+ New Inspection</Button></Link>}
      />
      <ErrorBox error={error} />
      <Card className="mb-4 flex flex-wrap items-center gap-3 p-3">
        <input className={inputCls + " max-w-xs"} placeholder="🔍 Search by ID or product…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className={inputCls + " max-w-[200px]"} value={status} onChange={(e) => setStatus(e.target.value)}>
          {STATUS_FILTERS.map((s) => <option key={s} value={s}>{s ? s.replace(/_/g, " ").toUpperCase() : "ALL STATUSES"}</option>)}
        </select>
      </Card>
      <Card className="overflow-hidden">
        {loading ? (
          <Spinner />
        ) : items.length === 0 ? (
          <Empty icon="📋" text="No inspections found." action={<Link to="/inspector/new"><Button>Start a new inspection</Button></Link>} />
        ) : (
          <Table head={["Inspection ID", "Product", "Date", "Status", "Result", "Findings", ""]}>
            {items.map((r) => (
              <tr key={r.id} className="hover:bg-slate-50">
                <td className="px-3 py-2 font-semibold text-navy-700">{r.inspection_id}</td>
                <td className="px-3 py-2">{r.product_name || "—"}</td>
                <td className="px-3 py-2">{fmtDate(r.inspection_date)}</td>
                <td className="px-3 py-2"><Badge value={r.status} /></td>
                <td className="px-3 py-2">
                  <Badge value={r.status === "finalized" && r.final_compliance_status ? r.final_compliance_status : r.automated_result} />
                </td>
                <td className="px-3 py-2 text-xs">
                  {r.status === "draft" ? "—" : <><b className="text-red-700">{r.violations_count}</b> / <b className="text-amber-700">{r.review_count}</b></>}
                </td>
                <td className="px-3 py-2">
                  <Button variant="secondary" className="px-3 py-1 text-xs" onClick={() => navigate(stepPath(r))}>Open</Button>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
