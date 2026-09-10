import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../client";
import { FlowLoader, NavButtons } from "../components/flow";
import { Badge, Button, Card, ErrorBox, Spinner, cn } from "../components/ui";

export default function PlacementPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  return (
    <FlowLoader
      inspectionId={id}
      step={6}
      title="Placement / Format Analysis"
      subtitle="Is the declaration located and presented as required? Visual analysis — final word remains with the inspector."
    >
      {({ inspection }) => <PlacementInner key={inspection.id} inspection={inspection} navigate={navigate} />}
    </FlowLoader>
  );
}

// Per-item decision state: { [itemId]: { decision: string; note: string } }
type ItemDecision = { decision: string; note: string };

function PlacementInner({ inspection, navigate }: { inspection: any; navigate: (p: string) => void }) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState<number | null>(null);
  // Per-item decision state — keyed by placement analysis row id
  const [decisions, setDecisions] = useState<Record<number, ItemDecision>>({});

  const setItemDecision = (id: number, field: keyof ItemDecision, value: string) =>
    setDecisions((prev) => ({
      ...prev,
      [id]: { ...{ decision: "", note: "" }, ...(prev[id] || {}), [field]: value },
    }));

  useEffect(() => {
    api.get(`/inspections/${inspection.id}/placement-analysis`).then(setData).catch((e) => setError(e.message));
  }, [inspection.id]);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner label="Loading placement analysis…" />;
  const s = data.summary;

  const save = async (itemId: number) => {
    const { decision, note } = decisions[itemId] || {};
    if (!decision) return;
    setSaving(itemId);
    try {
      await api.patch(`/placement-analyses/${itemId}`, { inspector_result: decision, note: note || "" });
      const d = await api.get(`/inspections/${inspection.id}/placement-analysis`);
      setData(d);
      // Clear the decision for this item after saving
      setDecisions((prev) => {
        const next = { ...prev };
        delete next[itemId];
        return next;
      });
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(null);
    }
  };

  return (
    <div>
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          ["Declarations Checked", s.declarations_analysed ?? s.checked],
          ["Pass", s.placement_acceptable ?? s.passed],
          ["Review Required", s.manual_review_required ?? s.review_required],
          ["Potential Issue", s.potential_issues ?? s.potential],
        ].map(([l, v]) => (
          <Card key={l as string} className="p-4 text-center">
            <div className="text-2xl font-extrabold text-navy-800">{v ?? 0}</div>
            <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{l}</div>
          </Card>
        ))}
      </div>

      <Card className="mb-4 p-4">
        <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Placement / Format Checks</div>
        <div className="space-y-2">
          {data.items.map((it: any) => {
            const itemState = decisions[it.id] || { decision: "", note: "" };
            const isSaving = saving === it.id;
            return (
              <div key={it.id} className={cn("rounded-lg border p-3", it.automated_result === "pass" ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50")}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="font-bold text-navy-800">{it.field.replace(/_/g, " ").toUpperCase()}</span>
                    <Badge value={it.automated_result} label={it.automated_result === "potential_issue" ? "POTENTIAL ISSUE" : it.automated_result.toUpperCase()} />
                  </div>
                  <span className="text-xs text-slate-500">
                    {it.detected_location ? `Location: ${it.detected_location} panel · ` : ""}position confidence: <Badge value={it.position_confidence} />
                  </span>
                </div>
                <div className="mt-1 grid gap-1 text-xs text-slate-600 sm:grid-cols-3">
                  <div><span className="text-slate-400">Requirement:</span> {it.requirement}</div>
                  <div><span className="text-slate-400">Detected:</span> {it.detected_condition || it.detected_location || "—"}</div>
                  <div><span className="text-slate-400">Expected:</span> {it.expected_condition}</div>
                </div>
                {it.inspector_result ? (
                  <div className="mt-2 text-xs text-slate-600">Inspector: <Badge value={it.inspector_result} /></div>
                ) : (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {["satisfied", "not_satisfied", "inconclusive"].map((opt) => (
                      <button
                        key={opt}
                        onClick={() => setItemDecision(it.id, "decision", itemState.decision === opt ? "" : opt)}
                        className={cn(
                          "rounded-lg border px-2 py-1 text-[11px] font-semibold transition-colors",
                          itemState.decision === opt
                            ? "border-navy-700 bg-navy-700 text-white"
                            : "border-slate-300 bg-white text-slate-600 hover:border-navy-400"
                        )}
                      >
                        {opt === "satisfied" ? "✓ Satisfied" : opt === "not_satisfied" ? "✕ Not satisfied" : "⚪ Inconclusive"}
                      </button>
                    ))}
                    <input
                      className="w-40 rounded border border-slate-300 px-2 py-1 text-xs"
                      placeholder="Note…"
                      value={itemState.note}
                      onChange={(e) => setItemDecision(it.id, "note", e.target.value)}
                    />
                    <Button
                      variant="secondary"
                      className="px-2 py-1 text-[11px]"
                      disabled={!itemState.decision || isSaving}
                      onClick={() => save(it.id)}
                    >
                      {isSaving ? "Saving…" : "Save"}
                    </Button>
                  </div>
                )}
              </div>
            );
          })}
          {data.items.length === 0 && <div className="text-sm text-slate-400">No placement records — run the rule analysis first.</div>}
        </div>
      </Card>

      <Card className="border-slate-200 p-4 text-xs text-slate-500">
        <b>Safe-by-design:</b> a declaration not identified in one image is checked across every relevant
        captured panel. When coverage is insufficient the item stays <Badge value="manual_review" label="REVIEW" /> — it is
        never silently converted into a placement violation.
      </Card>

      <NavButtons
        backTo={`/inspector/inspections/${inspection.id}/font`}
        continueLabel="Continue to Evidence →"
        onContinue={() => navigate(`/inspector/inspections/${inspection.id}/evidence`)}
      />
    </div>
  );
}
