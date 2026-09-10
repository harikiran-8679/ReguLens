import { Fragment, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../client";
import { FlowLoader, NavButtons } from "../components/flow";
import { Badge, Button, Card, ErrorBox, Spinner, Table, cn } from "../components/ui";

export default function RulesPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  return (
    <FlowLoader
      inspectionId={id}
      step={4}
      title="Rule Engine Analysis"
      subtitle="Step 4 of 7 · Date-aware, deterministic evaluation against the applicable rule version."
    >
      {({ inspection }) => <RulesInner key={inspection.id} inspection={inspection} navigate={navigate} />}
    </FlowLoader>
  );
}

function RulesInner({ inspection, navigate }: { inspection: any; navigate: (p: string) => void }) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [ruleSet, setRuleSet] = useState<any>(null);
  const [results, setResults] = useState<any>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  // B4: prevent StrictMode double-mount from firing two concurrent analysis runs
  const ranRef = useRef(false);

  const loadAll = async () => {
    const [rs, rr] = await Promise.all([
      api.get(`/inspections/${inspection.id}/rule-set`),
      api.get(`/inspections/${inspection.id}/rule-results`).catch(() => null),
    ]);
    setRuleSet(rs);
    setResults(rr);
    return rr;
  };

  useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;
    // On mount: load persisted results; if none exist yet (e.g. the inspector
    // navigated straight here after OCR), run the rule evaluation automatically
    // so the page is never empty until a manual click. Re-run stays available
    // via the button for explicit re-evaluation after corrections.
    (async () => {
      try {
        const rr = await loadAll();
        if (!rr || !rr.results || rr.results.length === 0) {
          await run();
        }
      } catch (e: any) {
        setError(e.message);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inspection.id]);

  const run = async () => {
    setRunning(true);
    setError("");
    try {
      const data = await api.post(`/inspections/${inspection.id}/analysis/run`);
      await loadAll();
      await api.post(`/inspections/${inspection.id}/navigate`, { step: 4 });
      return data;
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  };

  const counts = results?.counts;

  return (
    <div>
      <ErrorBox error={error} />
      {/* Applicable rule set */}
      {ruleSet && (
        <Card className="mb-4 p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-500">Applicable Rule Set</div>
          <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div><div className="text-xs text-slate-400">Base Regulation</div><div className="font-semibold text-navy-800">Legal Metrology (Packaged Commodities) Rules, 2011</div></div>
            <div><div className="text-xs text-slate-400">Rule Version</div><div className="font-semibold text-navy-800">{ruleSet.rule_set_version}</div></div>
            <div><div className="text-xs text-slate-400">Effective Date</div><div className="font-semibold text-navy-800">{ruleSet.effective_date}</div></div>
            <div>
              <div className="text-xs text-slate-400">Rules Applicable</div>
              <div className="font-semibold text-navy-800">
                {ruleSet.rules_count} <span className="text-emerald-600">🟢 verified</span>
              </div>
              {ruleSet.rules_skipped > 0 && (
                <div className="text-[10px] text-slate-400 mt-0.5">{ruleSet.rules_skipped} not applicable to this product</div>
              )}
            </div>
          </div>
          <div className="mt-3 text-xs text-slate-500">
            Version-aware selection: only rules with <code>effective_from ≤ inspection date &lt; effective_to</code> (or still in force) and matching the product category are evaluated.
          </div>
        </Card>
      )}

      {/* Stat tiles */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {[
          ["Rules Evaluated", ruleSet?.rules_count ?? counts?.rules_checked ?? "—", "text-navy-800"],
          ["Compliant", counts?.compliant ?? "—", "text-emerald-700"],
          ["Non-Compliant", counts?.non_compliant ?? "—", "text-red-700"],
          ["Manual Review", counts?.manual_review ?? "—", "text-amber-700"],
          ["Potential Non-Compliance", counts?.potential_non_compliance ?? "—", "text-violet-700"],
        ].map(([l, v, c]) => (
          <Card key={l as string} className="p-4 text-center">
            <div className={cn("text-2xl font-extrabold", c as string)}>{v}</div>
            <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{l}</div>
          </Card>
        ))}
      </div>

      <div className="mt-4 text-center">
        <Button onClick={run} disabled={running} className="px-8">
          {running ? "⟳ Evaluating rules…" : results ? "↻ Re-run Rule Analysis" : "▶ Run Rule Engine Analysis"}
        </Button>
      </div>

      {running && (
        <Card className="mt-4 p-8">
          <Spinner label="Applicable rules loaded · evaluating declarations, quantity, price, font, placement…" />
        </Card>
      )}

      {results && !running && (
        <Card className="mt-4 overflow-hidden">
          <div className="border-b border-slate-200 px-4 py-3 text-xs font-bold uppercase tracking-widest text-slate-500">
            Rule Evaluation — {ruleSet?.rules_count ?? counts?.rules_checked} rules applicable · {counts?.compliant} compliant · {counts?.non_compliant} non-compliant · {counts?.manual_review} manual review · {counts?.potential_non_compliance} potential
          </div>
          <Table head={["Rule", "Requirement", "Input", "Result", "Confidence", ""]}>
            {results.results.map((r: any) => (
              <Fragment key={r.id}>
                <tr onClick={() => setExpanded(expanded === r.id ? null : r.id)} className="cursor-pointer hover:bg-slate-50">
                  <td className="px-3 py-2">
                    <span className="font-bold text-navy-700">{r.sub_rule}</span>
                    <div className="text-[10px] text-slate-400">{r.title}</div>
                  </td>
                  <td className="max-w-xs px-3 py-2 text-xs">{r.requirement}</td>
                  <td className="px-3 py-2 text-xs font-medium">{r.input_value}</td>
                  <td className="px-3 py-2"><Badge value={r.result} /></td>
                  <td className="px-3 py-2 text-xs">{r.confidence ? `${Math.round(r.confidence * 100)}%` : "—"}</td>
                  <td className="px-3 py-2 text-slate-400">{expanded === r.id ? "▴" : "▾"}</td>
                </tr>
                {expanded === r.id && (
                  <tr className="bg-slate-50">
                    <td colSpan={6} className="px-5 py-3">
                      <div className="grid gap-2 text-xs sm:grid-cols-2">
                        <div><span className="font-bold text-slate-500">Category:</span> {r.category} · {r.type}</div>
                        <div><span className="font-bold text-slate-500">Severity:</span> <Badge value={r.severity} /></div>
                        <div className="sm:col-span-2"><span className="font-bold text-slate-500">Why:</span> {r.note}</div>
                        <div className="sm:col-span-2"><span className="font-bold text-slate-500">Expected:</span> {r.expected_value}</div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </Table>
        </Card>
      )}

      <NavButtons
        backTo={`/inspector/inspections/${inspection.id}/ocr`}
        continueLabel="Continue to Compliance Result →"
        disabled={!results}
        onContinue={async () => {
          await api.post(`/inspections/${inspection.id}/navigate`, { step: 5 });
          navigate(`/inspector/inspections/${inspection.id}/result`);
        }}
      />
    </div>
  );
}
