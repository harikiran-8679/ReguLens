import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../client";
import { Button, Card, ErrorBox, Spinner, cn } from "../components/ui";

const SECTIONS = [
  "Inspection Information", "Product Information", "Applicable Rule Basis", "Final Assessment",
  "Compliance Summary", "Confirmed Findings", "Inconclusive Findings", "Font & Readability",
  "Placement & Format", "Evidence", "Inspector Observations", "Inspector Review", "Appendix",
];
const MANDATORY = new Set(["Applicable Rule Basis", "Final Assessment", "Confirmed Findings", "Inspector Review"]);

export default function ReportExport() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [reportType, setReportType] = useState<"pdf" | "docx">("pdf");
  const [sections, setSections] = useState<string[]>(SECTIONS);
  const [history, setHistory] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<any>(null);

  const load = async () => {
    const h = await api.get(`/inspections/${id}/reports`);
    setHistory(h.items);
  };
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [id]);

  const toggle = (s: string) => {
    if (MANDATORY.has(s)) return;
    setSections((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));
  };

  const generate = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.post(`/inspections/${id}/report/generate`, { report_type: reportType });
      setDone(r);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const download = async (rid: number) => {
    const res = await fetch(`/api/reports/${rid}/download`, { headers: { Authorization: `Bearer ${localStorage.getItem("lm_token")}` } });
    const blob = await res.blob();
    const a = document.createElement("a");
    const cd = res.headers.get("content-disposition") || "";
    const m = cd.match(/filename="?([^";]+)"?/);
    a.href = URL.createObjectURL(blob);
    a.download = m ? m[1] : "report." + (reportType === "pdf" ? "pdf" : "docx");
    a.click();
    URL.revokeObjectURL(a.href);
  };

  if (error) return <ErrorBox error={error} />;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-navy-800">REPORT EXPORT</h1>
          <p className="text-xs text-slate-500">Generated from the finalized inspection record. Exporting never re-runs analysis or changes the result.</p>
        </div>
        <Button variant="secondary" onClick={() => navigate(-1)}>← Back to Report</Button>
      </div>

      {done && (
        <Card className="mb-4 border-emerald-300 bg-emerald-50 p-5 text-center">
          <div className="text-lg font-extrabold text-emerald-800">✓ REPORT GENERATED</div>
          <div className="mt-1 text-xs text-emerald-700">
            {done.report_id} · v{done.report_version} · {done.report_type.toUpperCase()} · {new Date().toLocaleString("en-IN")}
          </div>
          <div className="mt-3 flex justify-center gap-2">
            <Button onClick={() => download(done.id)}>⬇ Download {done.report_type.toUpperCase()}</Button>
            <Button variant="secondary" onClick={() => { setDone(null); navigate("/inspector/dashboard"); }}>+ New Inspection</Button>
          </div>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Options */}
        <div className="space-y-4">
          <Card className="p-5">
            <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Select Format</div>
            <button onClick={() => setReportType("pdf")} className={cn("mb-2 w-full rounded-xl border-2 p-4 text-left", reportType === "pdf" ? "border-navy-700 bg-navy-50" : "border-slate-200")}>
              <div className="text-sm font-bold text-navy-800">◉ PDF Report</div>
              <div className="text-xs text-slate-500">Fixed-layout report for printing, sharing and official record storage.</div>
            </button>
            <button onClick={() => setReportType("docx")} className={cn("w-full rounded-xl border-2 p-4 text-left", reportType === "docx" ? "border-navy-700 bg-navy-50" : "border-slate-200")}>
              <div className="text-sm font-bold text-navy-800">○ Editable Report (DOCX)</div>
              <div className="text-xs text-slate-500">Editable document generated from the finalized inspection data.</div>
            </button>
            {reportType === "docx" && (
              <div className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
                ⚠ Changes made to an exported document do not update the official report stored in the system.
              </div>
            )}
          </Card>

          <Card className="p-5">
            <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Report History</div>
            {history.length === 0 ? (
              <div className="text-xs text-slate-400">No reports generated yet.</div>
            ) : (
              <div className="space-y-2">
                {history.map((r) => (
                  <div key={r.id} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-xs">
                    <div>
                      <div className="font-bold text-navy-800">{r.report_id} · {r.report_type.toUpperCase()} · v{r.report_version}</div>
                      <div className="text-slate-400">{r.generation_status}</div>
                    </div>
                    {r.generation_status === "generated" && (
                      <Button variant="secondary" className="px-2 py-1 text-[10px]" onClick={() => download(r.id)}>Download</Button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* Sections */}
        <Card className="p-5 lg:col-span-2">
          <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Included Sections</div>
          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            {SECTIONS.map((s) => {
              const mandatory = MANDATORY.has(s);
              const on = sections.includes(s);
              return (
                <button key={s} onClick={() => toggle(s)} className={cn("flex items-center justify-between rounded-lg border px-3 py-2 text-left text-xs font-semibold", on ? "border-navy-600 bg-navy-50 text-navy-800" : "border-slate-200 text-slate-500")}>
                  <span>{mandatory ? "🔒 " : on ? "☑ " : "☐ "}{s}</span>
                  {mandatory && <span className="text-[9px] uppercase text-slate-400">required</span>}
                </button>
              );
            })}
          </div>
          <div className="mt-5 border-t border-slate-200 pt-4 text-center">
            <Button onClick={generate} disabled={busy} className="px-10">
              {busy ? "⟳ Generating document…" : "⚙ GENERATE REPORT"}
            </Button>
            {!done && (
              <div className="mt-4">
                <Button variant="secondary" onClick={() => navigate("/inspector/dashboard")}>+ Start a New Inspection</Button>
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
