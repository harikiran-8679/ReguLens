import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, fileUrl } from "../client";
import { FlowLoader, NavButtons } from "../components/flow";
import { Badge, Button, Card, ErrorBox, Modal, Spinner, cn, inputCls } from "../components/ui";
import { OverlayImage } from "../components/media";

const EVIDENCE_TYPES: Record<string, string> = {
  source_image: "Source Image", evidence_region: "Evidence Region", ocr_region: "OCR Region",
  font_evidence: "Font Evidence", placement_evidence: "Placement Evidence",
  inspector_photo: "Inspector Photograph", additional: "Additional Evidence",
};

export default function EvidencePage() {
  const { id } = useParams();
  return (
    <FlowLoader
      inspectionId={id}
      step={6}
      title="Evidence Management"
      subtitle="Every finding traces back to an image, a region, an OCR value and a rule."
    >
      {({ inspection }) => <EvidenceInner key={inspection.id} inspection={inspection} />}
    </FlowLoader>
  );
}

function EvidenceInner({ inspection }: { inspection: any }) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<any>(null);
  const [observation, setObservation] = useState("");
  const [relevance, setRelevance] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [evidenceType, setEvidenceType] = useState("inspector_photo");
  const [findingId, setFindingId] = useState("");
  const [uploading, setUploading] = useState(false);
  const [images, setImages] = useState<any[]>([]);
  const [regionsByImage, setRegionsByImage] = useState<Record<number, any[]>>({});

  const load = () =>
    Promise.all([
      api.get(`/inspections/${inspection.id}/evidence`),
      api.get(`/inspections/${inspection.id}/images`),
      api.get(`/inspections/${inspection.id}/ocr`),
    ])
      .then(([ev, im, ocr]) => {
        setData(ev);
        setImages(im.images);
        const byImg: Record<number, any[]> = {};
        (ocr.regions || []).forEach((r: any) => {
          (byImg[r.image_id] = byImg[r.image_id] || []).push(r);
        });
        setRegionsByImage(byImg);
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inspection.id]);

  const saveNote = async () => {
    if (!selected) return;
    try {
      await api.patch(`/evidence/${selected.id}`, {
        observation, relevance: relevance || undefined,
      });
      setSelected(null);
      setObservation("");
      setRelevance("");
      await load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const uploadExtra = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    form.append("evidence_type", evidenceType);
    form.append("related_finding", findingId);
    form.append("description", "");
    try {
      await api.upload(`/inspections/${inspection.id}/evidence/upload`, form);
      setAddOpen(false);
      await load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  };

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner label="Loading evidence…" />;
  const s = data.summary;

  return (
    <div>
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          ["Images", s.images, "🗂"],
          ["Findings", s.findings, "🔎"],
          ["Evidence Linked", s.linked, "🔗"],
          ["Review Required", s.review, "🟡"],
        ].map(([l, v, icon]) => (
          <Card key={l as string} className="p-4 text-center">
            <div className="text-2xl font-extrabold text-navy-800">{icon} {v}</div>
            <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{l}</div>
          </Card>
        ))}
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        <Button onClick={() => setAddOpen(true)}>+ Add Evidence</Button>
        <Button variant="secondary" onClick={load}>↻ Refresh</Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Evidence list */}
        <div className="lg:col-span-2">
          <Card className="overflow-hidden">
            <div className="border-b border-slate-200 px-4 py-3 text-xs font-bold uppercase tracking-widest text-slate-500">Evidence List</div>
            <div className="divide-y divide-slate-100">
              {data.items.map((e: any) => (
                <button key={e.id} onClick={() => { setSelected(e); setObservation(e.observation || ""); setRelevance(e.relevance || ""); }} className={cn("flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-slate-50", selected?.id === e.id && "bg-navy-50")}>
                  <div>
                    <div className="flex items-center gap-2 text-sm font-semibold text-navy-800">
                      {e.evidence_id}
                      <span className="text-xs font-medium text-slate-400">{EVIDENCE_TYPES[e.evidence_type] || e.evidence_type}</span>
                    </div>
                    {e.violation && (
                      <div className="text-xs font-semibold text-navy-700">
                        Evidence for: {e.violation.finding_id} — {e.violation.rule_citation || e.violation.title}
                      </div>
                    )}
                    <div className="text-xs text-slate-500">
                      {e.source_image && (
                        <span className="font-medium text-slate-600">Source image: {e.source_image.image_id} ({e.source_image.side})</span>
                      )}
                      <div className="text-amber-800">{e.auto_description || e.description || "—"}</div>
                      {e.region_id && <span> · region {e.region_id}</span>}
                      {e.field_name && <span> · {e.field_name}</span>}
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    <Badge value={e.status} />
                    {e.finding_id && <span className="text-[10px] text-slate-400">for {e.finding_id}</span>}
                  </div>
                </button>
              ))}
              {data.items.length === 0 && <div className="p-8 text-center text-sm text-slate-400">No evidence items yet.</div>}
            </div>
          </Card>
        </div>

        {/* Evidence coverage */}
        <div className="space-y-4">
          <Card className="p-4">
            <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Finding → Evidence Coverage</div>
            <div className="space-y-1.5">
              {data.findings.map((f: any) => (
                <div key={f.finding_id} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-1.5 text-xs">
                  <span className="font-semibold text-slate-700">{f.finding_id}</span>
                  <span className="max-w-[220px] truncate text-slate-500">{f.requirement}</span>
                  <span className={f.supported ? "font-bold text-emerald-600" : "font-bold text-red-600"}>{f.supported ? "✓ Supported" : "🔴 Evidence required"}</span>
                </div>
              ))}
            </div>
          </Card>

          {selected && (() => {
            const img = images.find((i: any) => i.image_id === selected.source_image_id);
            const regs = img ? (regionsByImage[img.id] || []) : [];
            return (
              <Card className="p-4">
                <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">
                  Source image — {selected.source_image_id || "—"}
                  {selected.region_id && <span className="ml-1 text-slate-400">· {selected.region_id}</span>}
                </div>
                {img ? (
                  <OverlayImage
                    imageId={img.id}
                    regions={regs.map((r: any) => ({
                      region_id: r.region_id, text: r.text, bbox: r.bbox,
                      color: r.region_id === selected.region_id ? "#d97706" : "rgba(26,58,92,0.3)",
                    }))}
                  />
                ) : (
                  <div className="py-6 text-center text-xs text-slate-400">No source image file for this evidence item.</div>
                )}
              </Card>
            );
          })()}

          {selected && (
            <Card className="p-4">
              <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Evidence Traceability — {selected.evidence_id}</div>
              <div className="mb-2 grid gap-1 text-xs text-slate-600">
                {selected.violation && (
                  <div>Evidence for: <b>{selected.violation.finding_id} — {selected.violation.rule_citation || selected.violation.title}</b></div>
                )}
                <div>Source image: <b>{selected.source_image?.image_id || selected.source_image_id || "—"}{selected.source_image && ` (${selected.source_image.side})`}</b></div>
                <div className="text-amber-800">Description: <b>{selected.auto_description || selected.description || "—"}</b></div>
                <div>Region: <b>{selected.region_id || "—"}</b></div>
                <div>Rule: <b>{selected.rule_id || "—"}</b></div>
                <div>Captured by: <b>{selected.captured_by || "—"}</b></div>
              </div>
              <textarea className={inputCls + " text-xs"} rows={2} placeholder="Inspector observation (kept separate from AI findings)…" value={observation} onChange={(e) => setObservation(e.target.value)} />
              <div className="mt-2 flex gap-2 text-xs">
                {["relevant", "not_relevant", "inconclusive"].map((r) => (
                  <button key={r} onClick={() => setRelevance(r)} className={cn("rounded border px-2 py-1", relevance === r ? "border-navy-700 bg-navy-700 text-white" : "border-slate-300")}>{r}</button>
                ))}
              </div>
              <Button className="mt-3 w-full" onClick={saveNote}>Save observation</Button>
            </Card>
          )}
        </div>
      </div>

      <Modal open={addOpen} onClose={() => setAddOpen(false)} title="Add Evidence">
        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-bold text-slate-600">Evidence Type</label>
            <select className={inputCls} value={evidenceType} onChange={(e) => setEvidenceType(e.target.value)}>
              {Object.entries(EVIDENCE_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-bold text-slate-600">Link to Finding (optional)</label>
            <select className={inputCls} value={findingId} onChange={(e) => setFindingId(e.target.value)}>
              <option value="">— none —</option>
              {data.findings.map((f: any) => <option key={f.finding_id} value={f.finding_id}>{f.finding_id}</option>)}
            </select>
          </div>
          <label className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 hover:bg-slate-50">
            {uploading ? "Uploading…" : "📷 Capture / Upload photograph"}
            <input type="file" accept="image/*" className="hidden" onChange={uploadExtra} />
          </label>
        </div>
      </Modal>

      <NavButtons
        backTo={`/inspector/inspections/${inspection.id}/placement`}
        continueLabel="Continue to Inspector Review →"
        continueTo={`/inspector/inspections/${inspection.id}/review`}
      />
    </div>
  );
}
