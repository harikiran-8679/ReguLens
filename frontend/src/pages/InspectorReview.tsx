import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../client";
import { FlowLoader } from "../components/flow";
import { Badge, Button, Card, ErrorBox, Modal, Spinner, cn } from "../components/ui";

export default function ReviewPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  return (
    <FlowLoader
      inspectionId={id}
      step={7}
      title="Inspector Review"
      subtitle="The system generates findings — the inspector makes the final assessment. Both records are preserved."
    >
      {({ inspection, setInspection }) => (
        <ReviewInner key={inspection.id} inspection={inspection} setInspection={setInspection} navigate={navigate} />
      )}
    </FlowLoader>
  );
}

function ReviewInner({ inspection, setInspection, navigate }: {
  inspection: any; setInspection: (i: any) => void; navigate: (p: string) => void;
}) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [active, setActive] = useState<any>(null);
  const [decision, setDecision] = useState("");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [observation, setObservation] = useState("");
  const [finalStatus, setFinalStatus] = useState("");
  const [finalRemarks, setFinalRemarks] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [doneFlash, setDoneFlash] = useState(false);

  const load = async () => {
    const d = await api.get(`/inspections/${inspection.id}/review`);
    setData(d);
    setObservation(d.inspector_observation || "");
    if (!active && d.findings.length) setActive(d.findings[0]);
  };

  useEffect(() => {
    load().catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inspection.id]);

  const pending = useMemo(() => (data?.findings || []).filter((f: any) => f.inspector_status === "pending"), [data]);

  const saveDecision = async () => {
    if (!active || !decision) return;
    try {
      await api.patch(`/inspections/findings/${active.id}`, { inspector_result: decision, decision_reason: reason, note });
      setDecision("");
      setReason("");
      setNote("");
      await load();
      const rest = (data.findings || []).filter((f: any) => f.id !== active.id);
      // Refresh data first, then pick the next pending finding from fresh data
      const fresh = (await api.get(`/inspections/${inspection.id}/review`)).findings;
      const nextPending = fresh.find((f: any) => f.inspector_status === "pending" && f.id !== active.id);
      setActive(nextPending || fresh.find((f: any) => f.id !== active.id) || null);
    } catch (e: any) {
      setError(e.message);
    }
  };

  const saveObservation = async () => {
    try {
      await api.patch(`/inspections/${inspection.id}/observation`, { text: observation });
    } catch (e: any) {
      setError((e as any).message);
    }
  };

  const finalize = async () => {
    setBusy(true);
    setError("");
    try {
      const allowUnresolved = pending.length > 0;
      const res = await api.post(`/inspections/${inspection.id}/finalize`, {
        final_compliance_status: finalStatus,
        final_remarks: finalRemarks,
        allow_unresolved: allowUnresolved,
        unresolved_reason: allowUnresolved ? "Inspector elected to finalise after physical verification of the package." : "",
      });
      setInspection({ ...inspection, status: "finalized", final_compliance_status: res.final_compliance_status });
      setConfirmOpen(false);
      setDoneFlash(true);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner label="Loading review board…" />;
  const c = data.counts;

  if (doneFlash) {
    return (
      <Card className="mx-auto max-w-xl p-10 text-center">
        <div className="text-5xl">✅</div>
        <h2 className="mt-3 text-xl font-extrabold text-navy-800">INSPECTION FINALIZED</h2>
        <div className="mt-1 text-sm text-slate-500">Inspection {inspection.inspection_id}</div>
        <div className="mt-3 text-lg font-bold text-navy-700">
          Final assessment: <Badge value={inspection.final_compliance_status} />
        </div>
        <div className="mt-1 text-xs text-slate-500">Reviewed by {inspection.inspector} · {new Date().toLocaleString("en-IN")}</div>
        <div className="mt-6 flex justify-center gap-3">
          <Button variant="secondary" onClick={() => navigate(`/inspector/inspections/${inspection.id}/report`)}>View Final Report</Button>
          <Button onClick={() => navigate(`/inspector/inspections/${inspection.id}/export`)}>Generate & Export →</Button>
        </div>
      </Card>
    );
  }

  return (
    <div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          ["Rules Evaluated", c.evaluated], ["Passed", c.passed], ["Failed", c.failed], ["Review Required", c.review],
        ].map(([l, v]) => (
          <Card key={l as string} className="p-3 text-center">
            <div className="text-xl font-extrabold text-navy-800">{v}</div>
            <div className="text-[10px] font-bold uppercase text-slate-400">{l}</div>
          </Card>
        ))}
      </div>

      {/* progress */}
      <Card className="mt-4 p-4">
        <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
          <span className="font-bold uppercase tracking-widest">Inspector Review Progress</span>
          <span>{data.reviewed}/{data.total_findings} reviewed</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-slate-200">
          <div
            className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-emerald-600 transition-all"
            style={{ width: `${data.total_findings ? (data.reviewed / data.total_findings) * 100 : 0}%` }}
          />
        </div>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-5">
        {/* findings list */}
        <div className="lg:col-span-2">
          <Card className="p-4">
            <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Findings ({data.findings.length})</div>
            <div className="space-y-1.5">
              {(data.findings || []).map((f: any) => (
                <button key={f.id} onClick={() => { setActive(f); setDecision(""); setReason(""); setNote(""); }} className={cn("flex w-full items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left", active?.id === f.id ? "border-navy-600 bg-navy-50" : "border-slate-200 hover:bg-slate-50")}>
                  <div>
                    <div className="text-xs font-semibold text-slate-700">
                      {f.finding_id} <Badge value={f.engine_result} label={f.engine_result === "fail" ? "FAIL" : "REVIEW"} />
                    </div>
                    <div className="max-w-[220px] truncate text-[11px] text-slate-400">{f.requirement}</div>
                  </div>
                  <Badge value={f.inspector_status} label={f.inspector_status_label || f.inspector_status.toUpperCase()} />
                </button>
              ))}
            </div>
          </Card>
        </div>

        {/* finding detail */}
        <div className="lg:col-span-3">
          {active ? (
            <Card className="p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-extrabold text-navy-800">{active.finding_id} — {active.requirement}</span>
                <Badge value={active.severity} />
              </div>
              <div className="grid gap-2 rounded-lg bg-slate-50 p-3 text-xs sm:grid-cols-2">
                <div><span className="text-slate-400">Rule:</span> {active.rule_number} {active.sub_rule}</div>
                <div><span className="text-slate-400">Detected:</span> {active.detected_condition || "—"}</div>
                <div><span className="text-slate-400">Expected:</span> {active.expected_condition}</div>
                <div><span className="text-slate-400">Engine result:</span> <Badge value={active.engine_result} /></div>
              </div>
              <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500">
                <span>Evidence: {active.source_image_id || "—"}</span>
                {active.ocr_region_id && <span>· region {active.ocr_region_id}</span>}
                <span>· confidence {active.confidence ? Math.round(active.confidence * 100) + "%" : "—"}</span>
              </div>

              {active.inspector_status !== "pending" ? (
                <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs">
                  <div className="font-bold text-emerald-800">Inspector assessment: <Badge value={active.inspector_result || active.inspector_status} label={active.inspector_status_label || (active.inspector_result || active.inspector_status || "pending").toUpperCase()} /></div>
                  {active.decision_reason && <div className="mt-1 text-slate-600">Reason: {active.decision_reason}</div>}
                  {active.inspector_note && <div className="mt-1 text-slate-600">Note: {active.inspector_note}</div>}
                  <div className="mt-1 text-slate-400">Reviewed by {active.reviewed_by || "—"} · engine result preserved in audit trail.</div>
                </div>

              ) : (
                <div className="mt-3 rounded-lg border border-slate-200 p-3">
                  <div className="text-xs font-bold text-slate-600">Inspector decision</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button onClick={() => setDecision("satisfied")} className={cn("rounded-lg border px-3 py-1.5 text-xs font-semibold", decision === "satisfied" ? "border-emerald-600 bg-emerald-600 text-white" : "border-slate-300 text-slate-600")}>🟢 Requirement satisfied</button>
                    <button onClick={() => setDecision("not_satisfied")} className={cn("rounded-lg border px-3 py-1.5 text-xs font-semibold", decision === "not_satisfied" ? "border-red-600 bg-red-600 text-white" : "border-slate-300 text-slate-600")}>🔴 Requirement not satisfied</button>
                    <button onClick={() => setDecision("inconclusive")} className={cn("rounded-lg border px-3 py-1.5 text-xs font-semibold", decision === "inconclusive" ? "border-slate-500 bg-slate-500 text-white" : "border-slate-300 text-slate-600")}>⚪ Inconclusive</button>
                  </div>
                  {decision === "satisfied" && active.engine_result === "fail" && (
                    <div className="mt-2">
                      <label className="text-[11px] font-bold text-slate-500">Reason for overriding the automated finding (required)</label>
                      <select className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-xs" value={reason} onChange={(e) => setReason(e.target.value)}>
                        <option value="">Select…</option>
                        {["OCR error", "Incorrect rule applicability", "Image interpretation error", "Inspector verification", "Other"].map((r) => <option key={r}>{r}</option>)}
                      </select>
                    </div>
                  )}
                  <textarea className="mt-2 w-full rounded-lg border border-slate-300 p-2 text-xs" rows={2} placeholder="Inspector observation…" value={note} onChange={(e) => setNote(e.target.value)} />
                  <Button className="mt-2" disabled={!decision || (decision === "satisfied" && active.engine_result === "fail" && !reason)} onClick={saveDecision}>Save decision</Button>
                  {(!decision) && (
                    <p className="mt-1 text-[11px] text-amber-600">⚠ Select a decision above to enable Save.</p>
                  )}
                  {(decision === "satisfied" && active.engine_result === "fail" && !reason) && (
                    <p className="mt-1 text-[11px] text-amber-600">⚠ A reason is required to override an automated FAIL finding.</p>
                  )}
                </div>
              )}
            </Card>
          ) : (
            <Card className="p-10 text-center text-sm text-slate-400">Select a finding to review.</Card>
          )}
        </div>
      </div>

      {/* observation + final assessment */}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Inspector Observation</div>
          <textarea className="w-full rounded-lg border border-slate-300 p-2 text-xs" rows={4} value={observation} onChange={(e) => setObservation(e.target.value)} placeholder="Enter final inspection observations… (distinct from AI-generated text)" />
          <Button variant="secondary" className="mt-2" onClick={saveObservation}>Save observation</Button>
        </Card>

        <Card className="p-4">
          <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Final Inspector Assessment</div>
          {pending.length > 0 && (
            <div className="mb-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
              ⚠ {pending.length} item(s) still pending review. Finalising with unresolved items requires a reason.
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {[["COMPLIANT", "🟢 COMPLIANT"], ["NON_COMPLIANT", "🔴 NON-COMPLIANT"], ["MANUAL_REVIEW", "🟡 MANUAL REVIEW"]].map(([v, l]) => (
              <button key={v} onClick={() => setFinalStatus(v)} className={cn("rounded-lg border px-3 py-2 text-xs font-bold", finalStatus === v ? "border-navy-700 bg-navy-700 text-white" : "border-slate-300 text-slate-600")}>{l}</button>
            ))}
          </div>
          <textarea className="mt-3 w-full rounded-lg border border-slate-300 p-2 text-xs" rows={3} value={finalRemarks} onChange={(e) => setFinalRemarks(e.target.value)} placeholder="Final inspector remarks…" />
          <div className="mt-3 flex flex-wrap justify-between gap-2">
            <Button variant="secondary" onClick={() => navigate(`/inspector/inspections/${inspection.id}/evidence`)}>← Back to Evidence</Button>
            <Button disabled={!finalStatus || inspection.status === "finalized"} onClick={() => setConfirmOpen(true)}>Finalize Inspection</Button>
          </div>
        </Card>
      </div>

      <Modal open={confirmOpen} onClose={() => setConfirmOpen(false)} title="Finalize inspection?">
        <div className="text-sm text-slate-600">
          <p><b>Inspection:</b> {inspection.inspection_id}</p>
          <p className="mt-1"><b>Final assessment:</b> <Badge value={finalStatus} /></p>
          {pending.length > 0 && <p className="mt-1 text-amber-700">Note: {pending.length} unresolved automated finding(s) will be recorded as such and remain in the audit trail.</p>}
          <p className="mt-2 text-xs text-slate-500">Once finalized, the inspection becomes read-only except for authorized post-finalization procedures. The automated (rule engine) result is never overwritten.</p>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirmOpen(false)}>Cancel</Button>
          <Button onClick={finalize} disabled={busy}>{busy ? "Finalising…" : "Confirm & Finalize"}</Button>
        </div>
      </Modal>
    </div>
  );
}
