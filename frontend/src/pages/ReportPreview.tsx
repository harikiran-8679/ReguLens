import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, fileUrl } from "../client";
import { Badge, Button, Card, ErrorBox, Spinner } from "../components/ui";

const RESULT_TONE: Record<string, string> = {
  COMPLIANT: "bg-emerald-600", NON_COMPLIANT: "bg-red-700",
  MANUAL_REVIEW: "bg-amber-500", POTENTIAL_NON_COMPLIANCE: "bg-violet-600",
};

export default function ReportPreview() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get(`/inspections/${id}/report/preview`).then(setData).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner label="Assembling report…" />;

  const final = data.assessment.final_compliance_status || data.assessment.automated_result;
  const cs = data.compliance_summary;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-navy-800">FINAL REPORT PREVIEW</h1>
          <p className="text-xs text-slate-500">
            {data.inspection.inspection_id} · Report Status: 🟡 PREVIEW · Generated from the finalised inspection record — never from raw AI output.
          </p>
        </div>
        {!data.completeness.ready && (
          <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
            ⚠ Report incomplete: {data.completeness.missing.join(", ")}
          </div>
        )}
      </div>

      <Card className="mx-auto max-w-3xl overflow-hidden">
        {/* Paper header */}
        <div className="border-b-4 border-navy-700 bg-slate-50 px-8 py-4 text-center">
          <div className="text-sm font-extrabold tracking-widest text-navy-800">⚖️ LEGAL METROLOGY COMPLIANCE SYSTEM</div>
          <div className="text-lg font-extrabold text-navy-700">INSPECTION REPORT</div>
          <div className="mt-1 text-[10px] text-slate-500">
            {data.inspection.inspection_id} · {data.inspection.inspection_date} · Generated {data.meta.generated_date}
          </div>
        </div>

        <div className="space-y-5 p-6 text-sm">
          <section>
            <h3 className="mb-1 border-b border-slate-200 pb-1 text-xs font-extrabold uppercase tracking-widest text-navy-700">1. Inspection Information</h3>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
              <K k="Inspector" v={data.inspection.inspector_name || data.inspection.inspector} />
              <K k="Department" v={data.inspection.department} />
              <K k="Location" v={data.inspection.location} />
              <K k="Retailer / Store" v={data.inspection.retailer_store} />
              <K k="Inspection Date" v={data.inspection.inspection_date} />
              <K k="Status" v={data.inspection.status} />
            </div>
          </section>

          <section>
            <h3 className="mb-1 border-b border-slate-200 pb-1 text-xs font-extrabold uppercase tracking-widest text-navy-700">2. Product / Package Information</h3>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
              <K k="Product" v={data.product.product_name} />
              <K k="Brand" v={data.product.brand} />
              <K k="Category" v={data.product.category} />
              <K k="Package Type" v={data.product.package_type} />
              {data.product.fields.slice(0, 8).map((f: any) => <K key={f.field_name} k={f.label} v={f.value} />)}
            </div>
          </section>

          <section>
            <h3 className="mb-1 border-b border-slate-200 pb-1 text-xs font-extrabold uppercase tracking-widest text-navy-700">4. Applicable Legal / Rule Basis</h3>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
              <K k="Base Regulation" v={data.rule_basis.base_regulation} />
              <K k="Rule Set Version" v={data.rule_basis.rule_set_version} />
              <K k="Effective Date" v={data.rule_basis.effective_date} />
              <K k="Engine" v={data.rule_basis.engine_version} />
              <K k="Amendments" v={data.rule_basis.amendments.map((a: any) => a.name).join("; ") || "None"} wide />
            </div>
          </section>

          <section className="text-center">
            <h3 className="mb-2 border-b border-slate-200 pb-1 text-left text-xs font-extrabold uppercase tracking-widest text-navy-700">5. Final Inspection Assessment</h3>
            <div className={"inline-block rounded-lg px-8 py-3 text-lg font-extrabold text-white " + (RESULT_TONE[final || ""] || "bg-slate-500")}>
              {String(final || "PENDING").toUpperCase().replace(/_/g, "-")}
            </div>
            <div className="mt-1 text-[10px] text-slate-400">Automated (rule engine) result: {String(data.assessment.automated_result || "—").toUpperCase()} · final assessment recorded by inspector.</div>
          </section>

          <section>
            <h3 className="mb-1 border-b border-slate-200 pb-1 text-xs font-extrabold uppercase tracking-widest text-navy-700">6. Compliance Summary</h3>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {[["Rules Checked", cs.rules_checked], ["Compliant", cs.compliant], ["Non-Compliant", cs.non_compliant], ["Manual Review", cs.manual_review], ["Potential Non-Compliance", cs.potential_non_compliance]].map(([k, v]) => (
                <div key={k as string} className="rounded bg-slate-50 p-2 text-center"><div className="text-lg font-extrabold text-navy-800">{v}</div><div className="text-[9px] uppercase text-slate-400">{k}</div></div>
              ))}
            </div>
          </section>

          <section>
            <h3 className="mb-1 border-b border-slate-200 pb-1 text-xs font-extrabold uppercase tracking-widest text-navy-700">7. Confirmed Findings</h3>
            {data.findings.confirmed.length === 0 && <p className="text-xs text-slate-400">No confirmed findings.</p>}
            {data.findings.confirmed.map((f: any) => (
              <div key={f.finding_id} className="mb-1 rounded border border-red-100 bg-red-50 p-2 text-xs">
                <b className="text-red-800">{f.finding_id} — {f.requirement}</b>
                <div className="text-red-700">Observed: {f.detected} · Evidence: {f.evidence || "—"}</div>
                {f.note && <div className="mt-0.5 text-red-600">Inspector note: {f.note}</div>}
              </div>
            ))}
          </section>

          {data.findings.inconclusive.length > 0 && (
            <section>
              <h3 className="mb-1 border-b border-slate-200 pb-1 text-xs font-extrabold uppercase tracking-widest text-navy-700">8. Inconclusive / Review Items</h3>
              {data.findings.inconclusive.map((f: any) => (
                <div key={f.finding_id} className="mb-1 rounded border border-amber-200 bg-amber-50 p-2 text-xs">
                  <b className="text-amber-800">{f.finding_id}</b> — {f.requirement} · {f.reason}
                </div>
              ))}
            </section>
          )}

          <section>
            <h3 className="mb-1 border-b border-slate-200 pb-1 text-xs font-extrabold uppercase tracking-widest text-navy-700">9 / 10. Font & Placement Assessment</h3>
            <p className="text-xs text-slate-600">
              Font: {data.font.analysed} declarations analysed · {data.font.readable} readable · {data.font.review} manual review.
            </p>
            <p className="text-xs text-slate-500">{data.font.note}</p>
            <p className="mt-1 text-xs text-slate-600">Placement: {data.placement.checked} checked · {data.placement.passed} passed · {data.placement.review} review required.</p>
          </section>

          <section>
            <h3 className="mb-1 border-b border-slate-200 pb-1 text-xs font-extrabold uppercase tracking-widest text-navy-700">11. Evidence for Violations</h3>
            {(data.evidence.violations || []).length > 0 ? (
              <div className="space-y-3">
                {data.evidence.violations.map((v: any) => (
                  <div key={v.finding_id} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                    <div className="text-xs font-bold text-navy-800">
                      Evidence for: {v.rule_id || v.finding_id} — {v.title || v.requirement}
                    </div>
                    <div className="text-xs">
                      Source image: <b>{v.source_image?.image_id || "—"}</b>
                      {v.source_image?.side ? ` (${v.source_image.side})` : ""}
                    </div>
                    <div className="mt-0.5 text-xs text-amber-800">{v.description}</div>
                    <div className="mt-2 grid gap-2 sm:grid-cols-2">
                      {(v.evidence || []).filter((it: any) => it.source_image?.id).map((it: any) => (
                        <div key={it.evidence_id} className="rounded border border-slate-200 bg-white p-2">
                          <img
                            src={fileUrl(it.source_image.id)}
                            alt={`Evidence ${it.evidence_id} from ${it.source_image.image_id}`}
                            className="max-h-44 w-full rounded object-contain"
                          />
                          <div className="mt-1 text-[10px] text-slate-500">
                            {it.evidence_id} · {it.source_image.image_id} ({it.source_image.side})
                            {it.field_name ? ` · ${it.field_name}` : ""}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div>
                <p className="text-xs text-slate-600">{data.evidence.items} evidence item(s) recorded for this inspection.</p>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {data.evidence.rows.slice(0, 12).map((e: any) => (
                    <span key={e.evidence_id} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">{e.evidence_id}</span>
                  ))}
                </div>
              </div>
            )}
          </section>

          <section>
            <h3 className="mb-1 border-b border-slate-200 pb-1 text-xs font-extrabold uppercase tracking-widest text-navy-700">12. Inspector Observations</h3>
            <p className="text-xs text-slate-700">{data.observations.inspector_observation || "—"}</p>
            <p className="mt-1 text-xs text-slate-600"><b>Final remarks:</b> {data.observations.final_remarks || "—"}</p>
            <p className="mt-1 text-xs text-slate-500">Reviewed By: {data.observations.reviewed_by} · {data.observations.reviewed_at}</p>
          </section>
        </div>

        <div className="border-t border-slate-200 bg-slate-50 px-6 py-3 text-center text-[9px] text-slate-400">
          LEGAL METROLOGY COMPLIANCE SYSTEM · AI-assisted inspection • Rule-based validation • Evidence-based reporting
        </div>
      </Card>

      <div className="mx-auto mt-6 flex max-w-3xl flex-wrap items-center justify-between gap-3">
        <Button variant="secondary" onClick={() => navigate(`/inspector/inspections/${id}/review`)}>← Back to Inspector Review</Button>
        {data.completeness.ready && inspectionStatusReady(data) ? (
          <Button onClick={() => navigate(`/inspector/inspections/${id}/export`)}>Continue to Report Export →</Button>
        ) : (
          <Button disabled>Finalize the inspection before export</Button>
        )}
      </div>
    </div>
  );
}

function inspectionStatusReady(data: any): boolean {
  return data.inspection.status === "finalized";
}

function K({ k, v, wide }: { k: string; v: any; wide?: boolean }) {
  return (
    <div className={wide ? "col-span-2" : ""}>
      <span className="font-semibold text-slate-500">{k}: </span>
      <span className="text-slate-800">{v || "—"}</span>
    </div>
  );
}
