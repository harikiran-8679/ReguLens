import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../client";
import { FlowLoader, NavButtons } from "../components/flow";
import { OverlayImage } from "../components/media";
import { Badge, Button, Card, ErrorBox, Spinner, cn } from "../components/ui";

export default function FontPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  return (
    <FlowLoader
      inspectionId={id}
      step={6}
      title="Font & Readability Analysis"
      subtitle="AI-assisted measurement and review — never an automatic legal verdict on font size."
    >
      {({ inspection }) => <FontInner key={inspection.id} inspection={inspection} navigate={navigate} />}
    </FlowLoader>
  );
}

function FontInner({ inspection, navigate }: { inspection: any; navigate: (p: string) => void }) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [images, setImages] = useState<any[]>([]);
  const [fieldBboxes, setFieldBboxes] = useState<Record<string, any>>({});
  const [selected, setSelected] = useState<any>(null);
  const [decision, setDecision] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    Promise.all([
      api.get(`/inspections/${inspection.id}/font-analysis`),
      api.get(`/inspections/${inspection.id}/images`),
      api.get(`/inspections/${inspection.id}/fields`),
    ])
      .then(([f, im, fd]) => {
        setData(f);
        if (f.items.length) setSelected(f.items[0]);
        setImages(im.images);
        const map: Record<string, any> = {};
        (fd.groups || []).forEach((g: any) =>
          g.fields.forEach((x: any) => {
            if (x.bbox) map[x.field_name] = { image_public_id: x.image_public_id, bbox: x.bbox };
          })
        );
        setFieldBboxes(map);
      })
      .catch((e) => setError(e.message));
  }, [inspection.id]);

  const saveDecision = async () => {
    if (!selected) return;
    try {
      await api.patch(`/font-analyses/${selected.id}`, { inspector_result: decision, note });
      const f = await api.get(`/inspections/${inspection.id}/font-analysis`);
      setData(f);
      setSelected(f.items.find((x: any) => x.id === selected.id) || f.items[0]);
    } catch (e: any) {
      setError((e as any).message);
    }
  };

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner label="Loading font analysis…" />;
  const s = data.summary;
  const img = selected ? images.find((i) => i.image_id === selected.image_id) : null;

  return (
    <div>
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          ["Regions Analysed", s.analysed],
          ["Readable", s.readable],
          ["Review Required", s.review_required],
          ["Potential Issue", s.potential],
        ].map(([l, v]) => (
          <Card key={l as string} className="p-4 text-center">
            <div className="text-2xl font-extrabold text-navy-800">{v}</div>
            <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{l}</div>
          </Card>
        ))}
      </div>

      <Card className="mb-4 border-amber-200 bg-amber-50 p-4 text-xs text-amber-900">
        <b>Measurement caveat:</b> font assessment uses a <b>relative height estimate</b> (text-region height ÷
        captured-image height). A true millimetre measurement requires a calibration reference and is <b>not</b> claimed
        automatically — low-confidence or uncalibrated measurements are auto-flagged for manual review.
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Declaration list */}
        <Card className="p-4">
          <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Declarations Analysed</div>
          <div className="space-y-1.5">
            {data.items.map((it: any) => (
              <button key={it.id} onClick={() => { setSelected(it); setDecision(""); }} className={cn("flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left", selected?.id === it.id ? "border-navy-600 bg-navy-50" : "border-slate-200 hover:bg-slate-50")}>
                <div>
                  <div className="text-xs font-semibold text-slate-700">{it.field.replace(/_/g, " ").toUpperCase()}</div>
                  <div className="text-[11px] text-slate-400">{it.detected_text}</div>
                </div>
                <div className="text-right">
                  <Badge value={it.automated_result} label={it.automated_result === "potential_fail" ? "POTENTIAL" : it.automated_result.toUpperCase()} />
                  <div className="text-[10px] text-slate-400">{it.measurement_confidence} confidence</div>
                </div>
              </button>
            ))}
            {data.items.length === 0 && <div className="text-sm text-slate-400">No declarations available for font measurement.</div>}
          </div>
        </Card>

        {/* Detail */}
        {selected && (
          <div className="space-y-4">
            <Card className="p-4">
              <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Selected declaration — {selected.field.replace(/_/g, " ")}</div>
              {img ? (
                <OverlayImage
                  imageId={img.id}
                  highlight={
                    selected && fieldBboxes[selected.field]?.image_public_id === selected.image_id && fieldBboxes[selected.field]?.bbox
                      ? [{ bbox: fieldBboxes[selected.field].bbox, color: "#d97706", label: selected.field }]
                      : []
                  }
                />
              ) : (
                <div className="py-8 text-center text-xs text-slate-400">No source image for this measurement.</div>
              )}
            </Card>
            <Card className="p-4">
              <div className="grid gap-2 text-sm sm:grid-cols-2">
                <div><div className="text-[10px] font-bold uppercase text-slate-400">Detected text</div><div className="font-mono text-xs">{selected.detected_text}</div></div>
                <div><div className="text-[10px] font-bold uppercase text-slate-400">Readability</div><Badge value={selected.readability} /></div>
                <div><div className="text-[10px] font-bold uppercase text-slate-400">Estimated relative height</div><div className="font-bold text-navy-800">{selected.font_estimate != null ? selected.font_estimate.toFixed(4) + " × image height" : "not measured"}</div></div>
                <div><div className="text-[10px] font-bold uppercase text-slate-400">Required condition</div><div className="text-xs">{selected.required_condition}</div></div>
              </div>
              <div className="mt-2 rounded bg-slate-50 p-2 text-[11px] text-slate-500">{selected.measurement_method}</div>
            </Card>
            <Card className="p-4">
              <div className="text-xs font-bold uppercase tracking-widest text-slate-500">Inspector assessment</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {["satisfied", "not_satisfied", "inconclusive"].map((opt) => (
                  <button key={opt} onClick={() => setDecision(opt)} className={cn("rounded-lg border px-3 py-1.5 text-xs font-semibold", decision === opt ? "border-navy-700 bg-navy-700 text-white" : "border-slate-300 text-slate-600")}>
                    {opt === "satisfied" ? "🟢 Requirement satisfied" : opt === "not_satisfied" ? "🔴 Requirement not satisfied" : "⚪ Cannot determine"}
                  </button>
                ))}
              </div>
              {selected.inspector_result && (
                <div className="mt-2 text-xs text-slate-500">Saved assessment: <Badge value={selected.inspector_result} /></div>
              )}
              <textarea className="mt-3 w-full rounded-lg border border-slate-300 p-2 text-xs" rows={2} placeholder="Inspector observation…" value={note} onChange={(e) => setNote(e.target.value)} />
              <Button className="mt-2" disabled={!decision} onClick={saveDecision}>Save assessment</Button>
            </Card>
          </div>
        )}
      </div>

      <NavButtons
        backTo={`/inspector/inspections/${inspection.id}/findings`}
        continueLabel="Continue to Placement / Format →"
        onContinue={() => navigate(`/inspector/inspections/${inspection.id}/placement`)}
      />
    </div>
  );
}
