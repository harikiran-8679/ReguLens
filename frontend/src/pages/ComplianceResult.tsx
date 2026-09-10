import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../client";
import { FlowLoader, NavButtons } from "../components/flow";
import { Badge, Button, Card, ErrorBox, Spinner, cn } from "../components/ui";

// Exactly four compliance states — nothing else is rendered on this page.
const STATUS_META: Record<string, { icon: string; label: string; blurb: string; cls: string }> = {
  COMPLIANT: { icon: "🟢", label: "COMPLIANT", blurb: "Rule requirement satisfied.", cls: "text-emerald-700 bg-emerald-50 border-emerald-200" },
  NON_COMPLIANT: { icon: "🔴", label: "NON-COMPLIANT", blurb: "A single rule failed with sufficient confidence and image coverage.", cls: "text-red-800 bg-red-50 border-red-200" },
  MANUAL_REVIEW: { icon: "🟡", label: "MANUAL REVIEW", blurb: "Low confidence, poor image quality or borderline measurement — never silently treated as compliant or a violation.", cls: "text-amber-800 bg-amber-50 border-amber-200" },
  POTENTIAL_NON_COMPLIANCE: { icon: "🟣", label: "POTENTIAL NON-COMPLIANCE", blurb: "Cross-field / cross-source mismatch — e.g. conflicting net quantity values or a package value that differs from the online listing.", cls: "text-violet-800 bg-violet-50 border-violet-200" },
};

const TONES: Record<string, { bg: string; ring: string; label: string; blurb: string }> = {
  COMPLIANT: { bg: "from-emerald-700 to-emerald-600", ring: "ring-emerald-500/30", label: "🟢 COMPLIANT", blurb: "All evaluated applicable requirements passed." },
  NON_COMPLIANT: { bg: "from-red-800 to-red-600", ring: "ring-red-500/30", label: "🔴 NON-COMPLIANT", blurb: "Automated analysis identified failed requirements. Inspector review is required before finalisation." },
  MANUAL_REVIEW: { bg: "from-amber-600 to-amber-500", ring: "ring-amber-500/30", label: "🟡 MANUAL REVIEW", blurb: "Automated analysis could not confidently determine one or more requirements." },
  POTENTIAL_NON_COMPLIANCE: { bg: "from-violet-700 to-violet-600", ring: "ring-violet-500/30", label: "🟣 POTENTIAL NON-COMPLIANCE", blurb: "A cross-field or cross-source mismatch was detected (e.g. conflicting net quantities, or a package value differing from an online listing)." },
};

export default function ResultPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  return (
    <FlowLoader inspectionId={id} step={5} title="Compliance Result" subtitle="Step 5 of 7 · Analysis result — not the final enforcement decision.">
      {({ inspection }) => <ResultInner key={inspection.id} inspection={inspection} navigate={navigate} />}
    </FlowLoader>
  );
}

function ResultInner({ inspection, navigate }: { inspection: any; navigate: (p: string) => void }) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [listingField, setListingField] = useState("net_quantity");
  const [listingValue, setListingValue] = useState("");
  const [listingSource, setListingSource] = useState("Online listing");
  const [savingListing, setSavingListing] = useState(false);

  const load = () => api.get(`/inspections/${inspection.id}/compliance`).then(setData);
  useEffect(() => {
    load().catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inspection.id]);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner label="Loading compliance result…" />;

  const tone = TONES[data.automated_result] || TONES.MANUAL_REVIEW;
  const summary = data.summary || {};
  const results: any[] = data.results || [];
  const hasNonCompliant = (data.failed || []).length > 0;
  const hasReview = (data.review || []).length > 0;
  const potentialResults = results.filter((r) => r.status === "POTENTIAL_NON_COMPLIANCE");
  const manualResults = results.filter((r) => r.status === "MANUAL_REVIEW");

  const saveListing = async () => {
    setSavingListing(true);
    setError("");
    try {
      const res = await api.post(`/inspections/${inspection.id}/online-listing`, {
        field: listingField, value: listingValue, source: listingSource,
      });
      await load();
      setListingValue("");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSavingListing(false);
    }
  };

  return (
    <div>
      {/* Main verdict */}
      <Card className={cn("overflow-hidden bg-gradient-to-r p-6 text-center text-white ring-4", tone.bg, tone.ring)}>
        <div className="text-2xl font-extrabold tracking-wide">{tone.label}</div>
        {data.automated_result === "NON_COMPLIANT" && (
          <div className="mt-1 text-sm font-semibold">{summary.non_compliant} rule(s) non-compliant · {summary.manual_review} item(s) require review</div>
        )}
        <p className="mx-auto mt-2 max-w-xl text-xs text-white/90">{tone.blurb}</p>
        <p className="mx-auto mt-1 max-w-xl text-xs text-white/75">
          This is an automated analysis result. The inspector performs the final assessment.
        </p>
      </Card>

      {/* Summary tiles — computed from the persisted results array */}
      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          ["Rules Checked", summary.rules_checked ?? 0, "text-navy-800"],
          ["Compliant", summary.compliant ?? 0, "text-emerald-700"],
          ["Non-Compliant", summary.non_compliant ?? 0, "text-red-700"],
          ["Manual Review", summary.manual_review ?? 0, "text-amber-700"],
          ["Potential Non-Compliance", summary.potential_non_compliance ?? 0, "text-violet-700"],
        ].map(([l, v, c]) => (
          <Card key={l as string} className="p-4 text-center">
            <div className={cn("text-2xl font-extrabold", c as string)}>{v}</div>
            <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{l}</div>
          </Card>
        ))}
      </div>

      {/* Results array — one card per rule result, four shapes only */}
      <Card className="mt-6 p-5">
        <div className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-500">
          Rule Results ({results.length}) — one of exactly four states
        </div>
        {results.length === 0 ? (
          <div className="text-xs text-slate-400">No applicable rules were evaluated yet. Run the Rule Engine Analysis first.</div>
        ) : (
          <div className="space-y-2">
            {results.map((r: any) => {
              const meta = STATUS_META[r.status] || STATUS_META.MANUAL_REVIEW;
              return (
                <div key={r.id} className={cn("rounded-lg border px-3 py-2.5 text-sm", meta.cls)}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-bold">
                      {meta.icon} {r.sub_rule ? `${r.sub_rule} — ` : ""}{r.title || r.category.replace(/_/g, " ")}
                    </span>
                    <Badge value={r.status} label={r.status.replace(/_/g, " ")} />
                  </div>
                  <div className="mt-1 text-xs opacity-90">
                    {r.status === "POTENTIAL_NON_COMPLIANCE" && r.observed?.value_1 && r.observed?.value_2 ? (
                      <span>
                        Package: <b>{r.observed.value_1.value}</b>
                        {r.observed.value_1.image_id ? ` (image ${r.observed.value_1.image_id})` : ""}
                        {"  ↔  "}
                        {r.observed.value_2.source
                          ? <>Listing: <b>{r.observed.value_2.value}</b> ({r.observed.value_2.source})</>
                          : <>Panel 2: <b>{r.observed.value_2.value}</b>{r.observed.value_2.image_id ? ` (image ${r.observed.value_2.image_id})` : ""}</>}
                      </span>
                    ) : (
                      <span>
                        {r.observed ? <ObservedInline observed={r.observed} /> : r.input_value || r.requirement}
                        {r.expected?.required === true && " · required" }
                        {r.expected?.minimum_ratio ? ` · expected ≥ ${r.expected.minimum_ratio}` : ""}
                      </span>
                    )}
                  </div>
                  {r.reason && <div className="mt-1 text-xs italic opacity-80">Reason: {r.reason}</div>}
                  {r.evidence?.image_id && (
                    <div className="mt-1 text-[10px] opacity-70">Evidence: {r.evidence.image_id}{r.evidence.bbox ? ` bbox ${JSON.stringify(r.evidence.bbox)}` : ""}</div>
                  )}
                  {r.evidence?.image_ids && (
                    <div className="mt-1 text-[10px] opacity-70">Evidence images: {r.evidence.image_ids.join(", ")}</div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* Non-compliant findings */}
      {hasNonCompliant && (
        <Card className="mt-4 p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-red-700">Failed Requirements ({data.failed.length})</div>
          <div className="space-y-2">
            {data.failed.map((f: any) => (
              <div key={f.id} className="flex items-center justify-between gap-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm">
                <div>
                  <span className="font-bold text-red-800">🔴 {f.rule_number} {f.sub_rule} — {f.requirement}</span>
                  <div className="text-xs text-red-700">{f.detected_condition} · evidence: {f.source_image_id || "—"} </div>
                </div>
                <Button variant="secondary" className="shrink-0 px-3 py-1 text-xs" onClick={() => navigate(`/inspector/inspections/${inspection.id}/findings`)}>View violation</Button>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Manual review items */}
      {manualResults.length > 0 && (
        <Card className="mt-4 p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-amber-700">Items Requiring Manual Review ({manualResults.length})</div>
          <div className="space-y-2">
            {manualResults.map((r: any) => (
              <div key={r.id} className="flex items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm">
                <div>
                  <span className="font-bold text-amber-800">🟡 {r.title || r.category.replace(/_/g, " ")}</span>
                  <div className="text-xs text-amber-700">{r.reason || r.note}</div>
                </div>
                <Badge value="MANUAL_REVIEW" label="REVIEW" />
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Cross-source comparison (online listing) */}
      <Card className="mt-4 p-5">
        <div className="mb-2 text-xs font-bold uppercase tracking-widest text-violet-700">
          Cross-Source Comparison — Online Listing vs Package
        </div>
        <p className="mb-3 text-xs text-slate-500">
          Enter a value from an online listing (e.g. the product page) for the same product. If it differs from the value
          printed on the package, the check flags <b>POTENTIAL_NON_COMPLIANCE</b> showing both values side by side.
        </p>
        {potentialResults.filter((r) => r.category === "cross_source_comparison").map((r: any) => (
          <div key={r.id} className="mb-3 rounded-lg border border-violet-200 bg-violet-50 px-4 py-3 text-sm">
            <div className="font-bold text-violet-800">🟣 {r.status.replace(/_/g, " ")}</div>
            <div className="mt-1 grid gap-2 text-xs sm:grid-cols-2">
              <div className="rounded bg-white/70 p-2">
                <div className="font-bold text-slate-500">PACKAGE</div>
                <div className="text-lg font-extrabold text-navy-800">{r.observed?.value_1?.value || "—"}</div>
                {r.observed?.value_1?.image_id && <div className="text-[10px] text-slate-500">image {r.observed.value_1.image_id}</div>}
              </div>
              <div className="rounded bg-white/70 p-2">
                <div className="font-bold text-slate-500">ONLINE LISTING</div>
                <div className="text-lg font-extrabold text-violet-800">{r.observed?.value_2?.value || "—"}</div>
                <div className="text-[10px] text-slate-500">{r.observed?.value_2?.source || ""}</div>
              </div>
            </div>
            <div className="mt-1 text-xs italic text-violet-700">{r.reason}</div>
          </div>
        ))}
        {data.online_listing && !potentialResults.some((r) => r.category === "cross_source_comparison") && (
          <div className="mb-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-xs text-emerald-800">
            ✅ Online listing ({data.online_listing.source}): {data.online_listing.value} — matches the package value.
          </div>
        )}
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="mb-1 block text-[10px] font-bold uppercase text-slate-500">Field</label>
            <select value={listingField} onChange={(e) => setListingField(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-xs">
              <option value="net_quantity">Net Quantity</option>
              <option value="mrp_value">MRP</option>
            </select>
          </div>
          <div className="flex-1 min-w-[140px]">
            <label className="mb-1 block text-[10px] font-bold uppercase text-slate-500">Listing value (e.g. 4 kg / ₹450)</label>
            <input value={listingValue} onChange={(e) => setListingValue(e.target.value)} placeholder="Value shown on the online listing…" className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-xs" />
          </div>
          <div className="flex-1 min-w-[140px]">
            <label className="mb-1 block text-[10px] font-bold uppercase text-slate-500">Source</label>
            <input value={listingSource} onChange={(e) => setListingSource(e.target.value)} className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-xs" />
          </div>
          <Button onClick={saveListing} disabled={savingListing || !listingValue.trim()} className="px-4 py-1.5 text-xs">
            {savingListing ? "Comparing…" : "Compare against package"}
          </Button>
        </div>
      </Card>

      {/* Rule basis */}
      {data.snapshot && (
        <Card className="mt-4 p-4 text-xs text-slate-600">
          <div className="mb-1 font-bold uppercase tracking-widest text-slate-500">Rule Basis</div>
          <div>{data.snapshot.base_regulation} · {data.snapshot.rule_set_version}</div>
          <div>Effective: {data.snapshot.effective_date} · Engine: {data.snapshot.engine_version}</div>
          {data.snapshot.coverage_note && <div className="mt-1 text-amber-700">Coverage note: {data.snapshot.coverage_note}</div>}
        </Card>
      )}

      <NavButtons
        backTo={`/inspector/inspections/${inspection.id}/rules`}
        continueLabel={hasNonCompliant || hasReview ? "Continue to Violation Details →" : "Continue to Inspector Review →"}
        onContinue={async () => {
          await api.post(`/inspections/${inspection.id}/navigate`, { step: 6 });
          navigate(hasNonCompliant || hasReview
            ? `/inspector/inspections/${inspection.id}/findings`
            : `/inspector/inspections/${inspection.id}/review`);
        }}
      />
    </div>
  );
}

function ObservedInline({ observed }: { observed: any }) {
  if (observed == null) return null;
  if (observed.status) return <span>{observed.status}</span>;
  if (observed.value != null) {
    const parts = [String(observed.value)];
    if (observed.unit) parts.push(observed.unit);
    if (observed.currency) parts.push(observed.currency);
    return <span><b>{parts.join(" ")}</b></span>;
  }
  if (observed.estimated_height_ratio != null) return <span>estimated height ratio <b>{observed.estimated_height_ratio}</b></span>;
  if (observed.panel) return <span>on <b>{observed.panel}</b> panel</span>;
  if (observed.online_listing) return <span>listing: <b>{observed.online_listing.value}</b></span>;
  return <span>{JSON.stringify(observed)}</span>;
}