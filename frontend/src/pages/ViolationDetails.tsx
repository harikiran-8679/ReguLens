import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../client";
import { FlowLoader, NavButtons } from "../components/flow";
import { OverlayImage } from "../components/media";
import { Badge, Button, Card, ErrorBox, Spinner } from "../components/ui";

export default function FindingsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  return (
    <FlowLoader inspectionId={id} step={6} title="Violation Details" subtitle="Automated findings — confirmed only after inspector review.">
      {({ inspection }) => <FindingsInner key={inspection.id} inspection={inspection} navigate={navigate} />}
    </FlowLoader>
  );
}

function FindingsInner({ inspection, navigate }: { inspection: any; navigate: (p: string) => void }) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    api.get(`/inspections/${inspection.id}/findings`).then(setData).catch((e) => setError(e.message));
  }, [inspection.id]);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner label="Loading findings…" />;
  const c = data.counts;

  return (
    <div>
      <Card className="mb-4 grid grid-cols-2 gap-3 p-4 sm:grid-cols-4">
        {[
          ["🔴 Non-Compliant", c.non_compliant, "text-red-700"],
          ["🟡 Manual Review", c.manual_review, "text-amber-700"],
          ["🟢 Compliant", c.compliant, "text-emerald-700"],
          ["🟣 Potential Non-Compliance", c.potential_non_compliance, "text-violet-700"],
        ].map(([l, v, col]) => (
          <div key={l as string} className="text-center">
            <div className={"text-2xl font-extrabold " + col}>{v}</div>
            <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{l}</div>
          </div>
        ))}
      </Card>

      {/* Failed cards */}
      <div className="mb-5 text-xs font-bold uppercase tracking-widest text-red-700">Failed Requirements ({data.failed.length})</div>
      {data.failed.length === 0 && <div className="mb-4 text-sm text-slate-400">No failed requirements detected by the rule engine.</div>}
      <div className="mb-6 space-y-3">
        {data.failed.map((f: any, i: number) => (
          <Card key={f.id} className="overflow-hidden">
            <button onClick={() => setOpen(open === f.id ? null : f.id)} className="flex w-full items-center justify-between gap-3 bg-red-50 px-4 py-3 text-left">
              <div className="flex items-center gap-2">
                <span className="font-bold text-red-800">🔴 FINDING #{String(i + 1).padStart(2, "0")}</span>
                <Badge value={f.severity} />
                <span className="hidden text-xs text-slate-500 sm:inline">Rule {f.rule_number} {f.sub_rule}</span>
              </div>
              <span className="text-slate-400">{open === f.id ? "▴" : "▾"}</span>
            </button>
            {open === f.id && (
              <div className="grid gap-4 p-5 text-sm sm:grid-cols-2">
                <div>
                  <div className="text-[10px] font-bold uppercase text-slate-400">Requirement</div>
                  <div className="font-semibold text-slate-800">{f.requirement}</div>
                  <div className="mt-3 text-[10px] font-bold uppercase text-slate-400">Detected condition</div>
                  <div className="font-mono text-xs text-slate-700">{f.detected_condition || "—"}</div>
                  <div className="mt-3 text-[10px] font-bold uppercase text-slate-400">Expected / required</div>
                  <div className="text-xs text-slate-700">{f.expected_condition}</div>
                </div>
                <div>
                  <div className="text-[10px] font-bold uppercase text-slate-400">Evidence for</div>
                  <div className="text-sm font-bold text-navy-800">
                    {f.rule_id || f.rule_citation || "Violation"}{f.title && <span> — {f.title}</span>}
                  </div>
                  <div className="mt-1 text-xs">
                    Source image: <span className="font-semibold">{f.source_image?.image_id || f.source_image_id || "—"}{f.source_image && ` (${f.source_image.side})`}</span>
                  </div>
                  <div className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    {f.violation_description || "⚠ Automated finding — verify against the package image before confirming."}
                  </div>
                  {f.source_image?.id && (
                    <OverlayImage
                      imageId={f.source_image.id}
                      regions={f.bbox_normalized ? [{ region_id: f.ocr_region_id || "evidence-region", text: f.detected_condition, bbox: f.bbox_normalized, color: "#d97706" }] : []}
                      alt={`Source image ${f.source_image.image_id}`}
                      className="mt-3 w-full rounded-lg border border-slate-200"
                    />
                  )}
                </div>
                <div className="sm:col-span-2">
                  <Button variant="secondary" className="px-3 py-1 text-xs" onClick={() => navigate(`/inspector/inspections/${inspection.id}/evidence`)}>Manage evidence</Button>
                  <Button variant="secondary" className="ml-2 px-3 py-1 text-xs" onClick={() => navigate(`/inspector/inspections/${inspection.id}/review`)}>Review finding</Button>
                </div>
              </div>
            )}
          </Card>
        ))}
      </div>

      {/* Review items */}
      <div className="mb-3 text-xs font-bold uppercase tracking-widest text-amber-700">Review Required ({data.review.length})</div>
      <div className="mb-6 space-y-2">
        {data.review.map((f: any, i: number) => (
          <Card key={f.id} className="flex items-center justify-between gap-3 px-4 py-3">
            <div>
              <div className="text-sm font-semibold text-amber-800">🟡 {f.finding_type.replace(/_/g, " ")} — {f.requirement}</div>
              <div className="text-xs text-slate-500">{f.detected_condition} · {f.expected_condition}</div>
            </div>
            <Button variant="secondary" className="shrink-0 px-3 py-1 text-xs" onClick={() => navigate(`/inspector/inspections/${inspection.id}/review`)}>REVIEW</Button>
          </Card>
        ))}
        {data.review.length === 0 && <div className="text-sm text-slate-400">No review-required items.</div>}
      </div>

      <NavButtons
        backTo={`/inspector/inspections/${inspection.id}/result`}
        continueLabel="Continue to Font & Readability →"
        onContinue={async () => {
          const hasFont = data.review.some((f: any) => f.finding_type === "font_readability");
          navigate(hasFont
            ? `/inspector/inspections/${inspection.id}/font`
            : `/inspector/inspections/${inspection.id}/placement`);
        }}
      />
    </div>
  );
}
