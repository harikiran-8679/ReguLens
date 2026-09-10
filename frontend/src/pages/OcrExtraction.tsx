import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../client";
import { FlowLoader, NavButtons } from "../components/flow";
import { OverlayImage } from "../components/media";
import { Badge, Button, Card, ErrorBox, Spinner, confColor, confLabel, inputCls } from "../components/ui";

type FieldRow = any;
type Group = { category: string; label: string; fields: FieldRow[] };

// Engine codes -> display labels. Demo mode is labelled as simulated PaddleOCR so
// the UI stays consistent with the real primary/fallback design (paddle -> tesseract).
const ENGINE_LABELS: Record<string, string> = {
  paddle: "PaddleOCR",
  tesseract: "Tesseract",
  demo: "PaddleOCR (simulated)",
};

const engineBadge = (code?: string, fallback?: boolean) => {
  if (!code) return null;
  const label = ENGINE_LABELS[code] || code;
  return (
    <span
      className={"inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold " +
        (fallback
          ? "bg-amber-100 text-amber-800 border border-amber-300"
          : "bg-emerald-50 text-emerald-800 border border-emerald-200")}
      title={fallback ? "Primary engine (PaddleOCR) was replaced — fallback engine used for this image." : ""}
    >
      {fallback && <span>⚠</span>} {label}
      {fallback && <span className="font-semibold">(fallback)</span>}
    </span>
  );
};

export default function OcrPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  return (
    <FlowLoader
      inspectionId={id}
      step={3}
      title="OCR & Data Extraction"
      subtitle="Step 3 of 7 · OCR extracts information — it does not decide compliance. Verify low-confidence fields before the rule engine runs."
    >
      {({ inspection }) => <OcrInner key={inspection.id} inspection={inspection} navigate={navigate} />}
    </FlowLoader>
  );
}

function OcrInner({ inspection, navigate }: { inspection: any; navigate: (p: string) => void }) {
  const [groups, setGroups] = useState<Group[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [images, setImages] = useState<any[]>([]);
  const [regionsByImage, setRegionsByImage] = useState<Record<number, any[]>>({});
  const [processing, setProcessing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState<"structured" | "raw">("structured");
  const [selectedField, setSelectedField] = useState<FieldRow | null>(null);
  const [editValue, setEditValue] = useState("");
  const [editReason, setEditReason] = useState("OCR correction");
  const [verified, setVerified] = useState(false);

  const load = async () => {
    const [f, o] = await Promise.all([
      api.get(`/inspections/${inspection.id}/fields`),
      api.get(`/inspections/${inspection.id}/ocr`),
    ]);
    setGroups(f.groups);
    setSummary(f.summary);
    const byImg: Record<number, any[]> = {};
    (o.regions || []).forEach((r: any) => {
      (byImg[r.image_id] = byImg[r.image_id] || []).push(r);
    });
    setImages(o.images || []);
    setRegionsByImage(byImg);
    setVerified(f.summary.verified > 0);
  };

  useEffect(() => {
    load().catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inspection.id]);

  const runOcr = async () => {
    setProcessing(true);
    setError("");
    try {
      await api.post(`/inspections/${inspection.id}/ocr/run`);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setProcessing(false);
    }
  };

  const needsVerification = useMemo(
    () => groups.flatMap((g) => g.fields).filter((f: any) => f.status === "UNCERTAIN"),
    [groups]
  );
  const notFound = useMemo(
    () => groups.flatMap((g) => g.fields).filter((f: any) => f.status === "NOT_DETECTED"),
    [groups]
  );

  const imageFor = (field: FieldRow) => images.find((i) => i.id === field.image_id);
  const openField = (field: FieldRow) => {
    setSelectedField(field);
    setEditValue(field.value);
  };

  const saveCorrection = async () => {
    if (!selectedField) return;
    try {
      await api.patch(`/extracted-fields/${selectedField.id}`, { value: editValue, reason: editReason });
      setSelectedField(null);
      await load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const verifyAll = async () => {
    setBusy(true);
    setError("");
    try {
      await api.post(`/inspections/${inspection.id}/fields/verify`, {});
      setVerified(true);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const countDots = (f: FieldRow) => {
    const c = confColor(f.confidence);
    return <span className="text-xs font-bold" style={{ color: c }}>{confLabel(f.confidence)} {Math.round(f.confidence * 100)}%</span>;
  };

  return (
    <div>
      <ErrorBox error={error} />
      {/* Action bar */}
      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        <Button onClick={runOcr} disabled={processing}>
          {processing ? "⟳ Running OCR…" : "Run OCR / Re-extract"}
        </Button>
        <div className="flex rounded-lg border border-slate-200 overflow-hidden">
          <button onClick={() => setView("structured")} className={view === "structured" ? "bg-navy-700 px-3 py-1.5 text-xs font-bold text-white" : "bg-white px-3 py-1.5 text-xs text-slate-600"}>STRUCTURED VIEW</button>
          <button onClick={() => setView("raw")} className={view === "raw" ? "bg-navy-700 px-3 py-1.5 text-xs font-bold text-white" : "bg-white px-3 py-1.5 text-xs text-slate-600"}>RAW OCR VIEW</button>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-3 text-xs text-slate-600">
          {summary && (
            <>
              {Object.entries(summary.engine_counts || {}).map(([code, n]) => (
                <span key={code} className="inline-flex items-center gap-1">
                  {engineBadge(code)}
                  <span className="text-[10px] text-slate-400">×{n as number}</span>
                </span>
              ))}
              {(summary.fallback_images || []).length > 0 && (
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-800 border border-amber-300">
                  ⚠ Fallback OCR engine used on {(summary.fallback_images || []).length} image(s)
                </span>
              )}
              <span
                className={"rounded px-1.5 py-0.5 text-[10px] font-bold border " + ((summary as any).matcher_mode === "ollama"
                  ? "bg-violet-100 text-violet-800 border-violet-300"
                  : "bg-slate-100 text-slate-600 border-slate-300")}
                title={"Field matcher: " + (summary as any).matcher_label}
              >
                {(summary as any).matcher_mode === "ollama" ? "🧠 LLM field-matcher (Ollama/Qwen)" : "⚙️ Simulated field-matcher (deterministic)"}
              </span>
              <span>🖼 {summary.images_processed}/{summary.images_total} images</span>
              <span>▦ {summary.text_regions} regions</span>
              <span>✏️ {summary.fields_identified} fields</span>
              <span className="font-bold text-emerald-700">🟢 {summary.high_confidence} high</span>
              <span className="font-bold text-amber-700">🟡 {summary.needs_verification} review</span>
              <span className="font-bold text-slate-500">⚪ {summary.not_detected} not detected</span>
            </>
          )}
        </div>
      </Card>

      {summary?.fields_identified === 0 && summary?.text_regions === 0 && !processing && (
        <Card className="p-8 text-center">
          <div className="text-3xl">🤖</div>
          <p className="mt-2 text-sm text-slate-600">No OCR results yet.</p>
          <p className="text-xs text-slate-400">Press “Run OCR / Re-extract” to process the captured images through the pipeline.</p>
        </Card>
      )}

      {view === "raw" && (
        <Card className="p-5">
          <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Raw OCR per image — the actual image the OCR ran on</div>
          {images.map((im) => (
            <div key={im.id} className="mb-4 rounded-lg border border-slate-200 p-3">
              <div className="mb-2 flex items-center gap-2 text-xs font-bold text-navy-700">
                {im.image_id} · {im.side} <Badge value={im.ocr_suitability} />
                {engineBadge(im.ocr_engine, im.ocr_fallback_used)}
              </div>
              <OverlayImage
                imageId={im.id}
                regions={(regionsByImage[im.id] || []).map((r) => ({
                  region_id: r.region_id, text: r.text, bbox: r.bbox, color: "rgba(26,58,92,0.4)",
                }))}
              />
              <pre className="mt-3 whitespace-pre-wrap rounded bg-slate-50 p-3 font-mono text-xs text-slate-700">
                {(regionsByImage[im.id] || [])
                  .slice()
                  .sort((a: any, b: any) => a.bbox.y - b.bbox.y || a.bbox.x - b.bbox.x)
                  .map((r: any) => r.text)
                  .join("\n")}
              </pre>
            </div>
          ))}
        </Card>
      )}

      {view === "structured" && (
        <div className="grid gap-4 lg:grid-cols-5">
          {/* Extracted categories */}
          <div className="space-y-4 lg:col-span-3">
            {groups.map((g) => (
              <Card key={g.category} className="p-4">
                <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">{g.label}</div>
                {g.fields.length === 0 && <div className="text-xs text-slate-400">Nothing extracted in this category.</div>}
                {g.fields.map((f) => (
                  <button key={f.id} onClick={() => openField(f)} className="flex w-full items-center justify-between gap-2 border-t border-slate-100 py-2 text-left first:border-0 hover:bg-slate-50">
                    <div>
                      <div className="text-xs font-semibold text-slate-700">{f.label}</div>
                      <div className="text-sm font-medium text-navy-800">
                        {f.value || <span className="text-slate-300">—</span>}
                        {f.original_value && <span className="ml-1 text-[10px] text-slate-400">(was: {f.original_value})</span>}
                      </div>
                      <div className="text-[10px] text-slate-400">
                        {f.source === "inspector" && <span className="font-semibold text-sky-600">Inspector-verified · </span>}
                        {f.raw_text && <span>“{f.raw_text.slice(0, 60)}”</span>}
                        {f.image_public_id && <span> · {f.image_public_id} {f.region_id}</span>}
                      </div>
                    </div>
                    <div className="text-right">
                      <Badge value={f.status} />
                      <div className="mt-0.5">{f.confidence ? countDots(f) : <span className="text-[10px] text-slate-400">no OCR match</span>}</div>
                    </div>
                  </button>
                ))}
              </Card>
            ))}
          </div>

          {/* Right: package image + verify checklist */}
          <div className="space-y-4 lg:col-span-2">
            <Card className="p-4">
              <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Package evidence</div>
              {selectedField && imageFor(selectedField) ? (
                <OverlayImage
                  imageId={imageFor(selectedField).id}
                  regions={(regionsByImage[imageFor(selectedField).id] || []).map((r) => ({
                    region_id: r.region_id, text: r.text, bbox: r.bbox,
                    color: r.region_id === selectedField.region_id ? "#d97706" : "rgba(26,58,92,0.35)",
                  }))}
                />
              ) : images.length ? (
                <OverlayImage imageId={images[0].id} regions={(regionsByImage[images[0].id] || []).map((r) => ({ region_id: r.region_id, text: r.text, bbox: r.bbox, color: "rgba(26,58,92,0.4)" }))} />
              ) : (
                <div className="py-8 text-center text-xs text-slate-400">No image available</div>
              )}
              <div className="mt-2 text-[10px] text-slate-400">Click any extracted field to see its source region highlighted.</div>
            </Card>

            {needsVerification.length > 0 && (
              <Card className="border-amber-200 bg-amber-50 p-4">
                <div className="text-xs font-bold text-amber-800">🟡 {needsVerification.length} field(s) require verification</div>
                <ul className="mt-1 list-inside list-disc text-xs text-amber-900">
                  {needsVerification.slice(0, 5).map((f) => <li key={f.id}>{f.label} — {f.value || "(possibly present)"} ({Math.round(f.confidence * 100)}%)</li>)}
                </ul>
              </Card>
            )}
            {notFound.length > 0 && (
              <Card className="p-4">
                <div className="text-xs font-bold text-slate-600">⚪ Not detected by OCR — not automatically “missing”</div>
                <ul className="mt-1 list-inside list-disc text-xs text-slate-500">
                  {notFound.map((f) => <li key={f.id}>{f.label} — not detected across available images. The rule engine only treats this as a potential violation after adequate coverage.</li>)}
                </ul>
              </Card>
            )}

            <Card className="border-emerald-200 bg-emerald-50 p-4">
              <div className="mb-1 text-xs font-bold text-emerald-900">INSPECTOR VERIFICATION</div>
              <ul className="space-y-1 text-xs text-emerald-900">
                <li>{verified ? "☑" : "☐"} I have reviewed the extracted information.</li>
                <li>{verified ? "☑" : "☐"} OCR corrections have been applied where necessary.</li>
                <li>{verified ? "☑" : "☐"} Low-confidence fields were checked against the image.</li>
              </ul>
              <Button onClick={verifyAll} disabled={busy || verified} className="mt-3 w-full bg-emerald-600 hover:bg-emerald-700">
                {verified ? "✓ Verified — continue" : busy ? "Verifying…" : "VERIFY DATA & CONTINUE"}
              </Button>
            </Card>
          </div>
        </div>
      )}

      {/* Edit correction modal */}
      {selectedField && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4" onClick={() => setSelectedField(null)}>
          <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-1 text-xs font-bold uppercase tracking-widest text-slate-500">Field: {selectedField.label}</div>
            <div className="text-sm text-slate-600">
              OCR value: <span className="font-mono">{selectedField.raw_text || "—"}</span> ({Math.round(selectedField.confidence * 100)}%)
            </div>
            {selectedField.image_public_id && <div className="text-[10px] text-slate-400">Source: {selectedField.image_public_id} {selectedField.region_id}</div>}
            <label className="mt-3 block text-xs font-bold text-slate-600">Inspector correction</label>
            <input className={inputCls + " mt-1"} value={editValue} onChange={(e) => setEditValue(e.target.value)} />
            <label className="mt-3 block text-xs font-bold text-slate-600">Reason</label>
            <select className={inputCls + " mt-1"} value={editReason} onChange={(e) => setEditReason(e.target.value)}>
              {["OCR correction", "Image interpretation", "Field not on package", "Other"].map((r) => <option key={r}>{r}</option>)}
            </select>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setSelectedField(null)}>Cancel</Button>
              <Button onClick={saveCorrection}>Save Correction</Button>
            </div>
          </div>
        </div>
      )}

      <NavButtons
        backTo={`/inspector/inspections/${inspection.id}/capture`}
        continueLabel="Verify & Continue to Rule Analysis →"
        disabled={!verified}
        onContinue={async () => {
          if (!verified) {
            await api.post(`/inspections/${inspection.id}/fields/verify`, {});
          }
          await api.post(`/inspections/${inspection.id}/navigate`, { step: 4 });
          navigate(`/inspector/inspections/${inspection.id}/rules`);
        }}
      />
    </div>
  );
}
