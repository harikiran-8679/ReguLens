import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmtDateTime } from "../client";
import { Button, Card, Empty, ErrorBox, PageTitle, Spinner, Table, Badge } from "../components/ui";

export default function ReportsList() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<any[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    (async () => {
      try {
        const d = await api.get("/inspections?limit=100");
        const rows: any[] = [];
        for (const insp of d.items) {
          const h = await api.get(`/inspections/${insp.id}/reports`);
          h.items.forEach((r: any) => rows.push({ ...r, inspection_id: insp.inspection_id, product: insp.product_name }));
        }
        setRows(rows.sort((a, b) => (b.generated_at || "").localeCompare(a.generated_at || "")));
      } catch (e: any) {
        setError(e.message);
      }
    })();
  }, []);

  const download = async (rid: number) => {
    const res = await fetch(`/api/reports/${rid}/download`, { headers: { Authorization: `Bearer ${localStorage.getItem("lm_token")}` } });
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "report";
    a.click();
  };

  return (
    <div>
      <PageTitle title="Reports" subtitle="Generated reports across your inspections (per-inspector scope)." />
      <ErrorBox error={error} />
      <Card className="overflow-hidden">
        {rows.length === 0 && !error ? (
          <Empty icon="📄" text="No reports yet. Finalize an inspection and export its report." />
        ) : (
          <Table head={["Report", "Inspection", "Product", "Type", "Version", "Generated", "Status", "Action"]}>
            {rows.map((r) => (
              <tr key={r.id} className="hover:bg-slate-50">
                <td className="px-3 py-2 font-semibold text-navy-700">{r.report_id}</td>
                <td className="px-3 py-2">{r.inspection_id}</td>
                <td className="px-3 py-2 text-xs">{r.product || "—"}</td>
                <td className="px-3 py-2 uppercase">{r.report_type}</td>
                <td className="px-3 py-2">v{r.report_version}</td>
                <td className="px-3 py-2 text-xs">{fmtDateTime(r.generated_at)}</td>
                <td className="px-3 py-2"><Badge value={r.generation_status} /></td>
                <td className="px-3 py-2">
                  {r.generation_status === "generated" && (
                    <Button variant="secondary" className="px-3 py-1 text-xs" onClick={() => download(r.id)}>Download</Button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      <div className="mt-4">
        <Button onClick={() => navigate("/inspector/my")}>← View Inspections</Button>
      </div>
    </div>
  );
}
