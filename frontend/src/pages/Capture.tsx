import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, fileUrl } from "../client";
import { FlowLoader, NavButtons } from "../components/flow";
import { QualityBadge, QualityChecks } from "../components/media";
import { Badge, Button, Card, Empty, ErrorBox, cn } from "../components/ui";

const SIDES = ["front", "back", "side", "top", "bottom", "declaration", "additional"];
const SIDE_LABEL: Record<string, string> = {
  front: "Front", back: "Back", side: "Side", top: "Top/Bottom",
  bottom: "Bottom", declaration: "Declaration Area", additional: "Additional",
};

export default function CapturePage() {
  const { id } = useParams();
  const navigate = useNavigate();
  return (
    <FlowLoader inspectionId={id} step={2} title="Image Capture / Upload" subtitle="Step 2 of 7 · Guidance before capture: this module helps you capture good evidence — compliance is decided later by the rule engine.">
      {({ inspection }) => <CaptureInner key={inspection.id} inspection={inspection} navigate={navigate} />}
    </FlowLoader>
  );
}

type FacingMode = "environment" | "user";

function CaptureInner({ inspection, navigate }: { inspection: any; navigate: (p: string) => void }) {
  const [mode, setMode] = useState<"camera" | "upload">("camera");
  const [images, setImages] = useState<any[]>([]);
  const [selectedSide, setSelectedSide] = useState("front");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastQuality, setLastQuality] = useState<any>(null);
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraError, setCameraError] = useState("");
  const [switchError, setSwitchError] = useState("");
  const [live, setLive] = useState<any>(null);
  const [fileName, setFileName] = useState("");

  // Camera switch state
  const [facingMode, setFacingMode] = useState<FacingMode>("environment"); // default: rear
  const [cameraCount, setCameraCount] = useState<number | null>(null); // null = not yet enumerated
  const [switching, setSwitching] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const liveTimer = useRef<number | null>(null);

  const load = useCallback(() => {
    api.get(`/inspections/${inspection.id}/images`).then((d) => setImages(d.images)).catch(() => {});
  }, [inspection.id]);

  useEffect(() => { load(); }, [load]);

  // Enumerate cameras once after permission is granted
  const enumerateCameras = async () => {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const count = devices.filter((d) => d.kind === "videoinput").length;
      setCameraCount(count);
    } catch {
      setCameraCount(1); // assume 1 on error — hide switch
    }
  };

  // Stop all tracks + live poll — prevents MediaStream leaks
  const stopCameraClean = () => {
    if (liveTimer.current) { window.clearInterval(liveTimer.current); liveTimer.current = null; }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setLive(null);
    setCameraOn(false);
  };

  // Cleanup on unmount
  useEffect(() => () => stopCameraClean(), []);

  const startCamera = async (facing: FacingMode = "environment") => {
    try {
      setCameraError("");
      setSwitchError("");
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: facing }, width: { ideal: 1920 }, height: { ideal: 1440 } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }
      setCameraOn(true);
      setFacingMode(facing);
      // Enumerate after first start (browser may need permission first)
      enumerateCameras();
      startLivePoll();
    } catch (e: any) {
      setCameraError("Camera unavailable — use the Upload option instead. (" + (e?.name || "error") + ")");
      setMode("upload");
    }
  };

  const stopCamera = () => stopCameraClean();

  // Switch front ↔ rear camera — stop old stream before starting new one
  const switchCamera = async () => {
    if (switching) return;
    setSwitching(true);
    setSwitchError("");
    const next: FacingMode = facingMode === "environment" ? "user" : "environment";
    const prev = facingMode;
    stopCameraClean(); // stop old stream NOW — no leak
    try {
      await startCamera(next);
    } catch {
      setSwitchError("Could not switch camera — your device may not support this. Keeping current camera.");
      try { await startCamera(prev); } catch { /* give up */ }
    } finally {
      setSwitching(false);
    }
  };

  // Live quality polling — runs on current videoRef stream
  const startLivePoll = () => {
    if (liveTimer.current) window.clearInterval(liveTimer.current);
    const t = window.setInterval(() => {
      const v = videoRef.current;
      if (!v || v.readyState < 2) return;
      const canvas = document.createElement("canvas");
      const s = 320;
      canvas.width = s;
      canvas.height = Math.round((s * v.videoHeight) / Math.max(v.videoWidth, 1));
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(v, 0, 0, canvas.width, canvas.height);
      const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      let sum = 0, bright = 0, sharp = 0;
      const n = imgData.length / 4;
      for (let i = 0; i < imgData.length; i += 4) {
        const lum = 0.2126 * imgData[i] + 0.7152 * imgData[i + 1] + 0.0722 * imgData[i + 2];
        sum += lum;
        if (lum > 240) bright++;
      }
      const mean = sum / n;
      for (let i = 4; i < imgData.length; i += 4) { sharp += Math.abs(imgData[i] - imgData[i - 4]); }
      const sScore = Math.min((sharp / n) / 18, 1);
      const checks = [
        liveCheck("lighting", mean > 55 && mean < 235 ? "good" : mean < 50 ? "fail" : "warn",
          mean < 50 ? "Move to a better-lit area — too dark for OCR." : mean > 235 ? "Overexposed — reduce the light / flash." : "Adequate lighting."),
        liveCheck("sharpness", sScore > 0.32 ? "good" : sScore > 0.16 ? "warn" : "fail",
          sScore <= 0.16 ? "Image is blurry — hold the device steady." : sScore <= 0.32 ? "Hold steady for a sharper image." : "Image appears sharp."),
        liveCheck("glare", bright / n < 0.1 ? "good" : bright / n < 0.3 ? "warn" : "fail",
          bright / n >= 0.3 ? "Strong reflection detected — tilt the package or change angle." : bright / n >= 0.1 ? "Some glare — adjust the angle slightly." : "No significant glare."),
        liveCheck("package_detection", "good", "Package area detected in frame."),
      ];
      setLive({ overall: checks.some((c) => c.status === "fail") ? "poor" : checks.some((c) => c.status === "warn") ? "acceptable" : "good", checks });
    }, 900);
    liveTimer.current = t;
  };

  function liveCheck(metric: string, status: string, message: string) {
    return { metric, status, message, score: status === "good" ? 1 : status === "warn" ? 0.6 : 0.2 };
  }

  const captureShot = async () => {
    const v = videoRef.current;
    if (!v) return;
    const canvas = document.createElement("canvas");
    canvas.width = v.videoWidth || 1280;
    canvas.height = v.videoHeight || 960;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(v, 0, 0);
    const blob: Blob = await new Promise((res) => canvas.toBlob((b) => res(b || new Blob()), "image/jpeg", 0.92));
    await upload(blob, selectedSide);
  };

  const upload = async (blob: Blob, side: string) => {
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("file", blob, "capture.jpg");
    form.append("side", side);
    form.append("source", "camera");
    try {
      const img = await api.upload(`/inspections/${inspection.id}/images/upload`, form);
      setLastQuality(img.quality);
      setImages((prev) => [...prev.filter((x) => x.id !== img.id), img]);
      if (img.is_duplicate) {
        setError(`Duplicate side detected — this looks like ${img.duplicate_of}. Capture a different panel.`);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const onPickFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFileName(f.name);
    upload(f, selectedSide);
  };

  const coverage: Record<string, any> = {};
  images.forEach((im) => { coverage[im.side] = im; });

  const nextHint = (() => {
    if (!coverage.front) return { msg: "Capture the FRONT panel first — product name, net quantity and MRP live here." };
    if (!coverage.back && !coverage.side) return { msg: "Now capture the BACK (or a SIDE) panel so presence checks have full coverage." };
    return { msg: "Need more? Capture a close-up of any declaration area, or press Continue." };
  })();

  // Show switch button only when camera is active AND multiple cameras are available
  const showSwitchBtn = cameraOn && (cameraCount === null || cameraCount > 1);

  return (
    <div>
      <ErrorBox error={error} />
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Camera / Upload card */}
        <Card className="p-4 sm:p-5 lg:col-span-2">
          {/* Mode + side selector */}
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <button
              id="btn-mode-camera"
              onClick={() => setMode("camera")}
              className={cn("rounded-lg px-3 py-2 text-sm font-semibold transition-colors",
                mode === "camera" ? "bg-navy-700 text-white shadow-sm" : "bg-slate-100 text-slate-600 hover:bg-slate-200")}
            >
              📷 Live Camera
            </button>
            <button
              id="btn-mode-upload"
              onClick={() => setMode("upload")}
              className={cn("rounded-lg px-3 py-2 text-sm font-semibold transition-colors",
                mode === "upload" ? "bg-navy-700 text-white shadow-sm" : "bg-slate-100 text-slate-600 hover:bg-slate-200")}
            >
              📁 Upload Image
            </button>
            <div className="ml-auto flex items-center gap-1.5">
              <span className="hidden text-xs font-medium text-slate-600 sm:inline">Side:</span>
              <select
                id="select-side"
                value={selectedSide}
                onChange={(e) => setSelectedSide(e.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-700 shadow-sm focus:border-navy-400 focus:outline-none focus:ring-1 focus:ring-navy-400"
              >
                {SIDES.map((s) => <option key={s} value={s}>{SIDE_LABEL[s]}</option>)}
              </select>
            </div>
          </div>

          {mode === "camera" ? (
            <div>
              {/* Camera viewport */}
              <div className="relative overflow-hidden rounded-xl bg-slate-900">
                <video ref={videoRef} playsInline muted className="mx-auto max-h-[420px] w-full object-contain" />

                {/* Guide/framing overlay */}
                {cameraOn && (
                  <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                    <div className="h-[72%] w-[88%] rounded-xl border-2 border-dashed border-white/40" />
                  </div>
                )}

                {/* ── CAMERA SWITCH BUTTON ───────────────────────────────────────
                    • Positioned top-right — doesn't overlap capture button (bottom-center)
                    • 48×48px (min 44px iOS HIG tap target) for one-handed use
                    • Hidden if only 1 camera or camera is off                   */}
                {showSwitchBtn && (
                  <button
                    id="btn-switch-camera"
                    onClick={switchCamera}
                    disabled={switching}
                    title={facingMode === "environment" ? "Switch to front camera" : "Switch to rear camera"}
                    aria-label={facingMode === "environment" ? "Switch to front camera" : "Switch to rear camera"}
                    className={cn(
                      "absolute right-3 top-3 z-10",
                      "flex h-12 w-12 items-center justify-center rounded-full",
                      "bg-black/50 text-white backdrop-blur-sm",
                      "transition-all hover:bg-black/70 active:scale-95",
                      "touch-manipulation select-none",
                      switching && "cursor-wait opacity-50"
                    )}
                  >
                    {switching
                      ? <span className="h-5 w-5 animate-spin rounded-full border-2 border-white border-t-transparent" />
                      : (
                        /* Standard flip-camera icon */
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-6 w-6">
                          <path d="M20 5h-3.17L15 3H9L7.17 5H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm-8 13a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-8a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"/>
                          <path d="M5.5 8L7 6.5m11.5 1.5L17 6.5" stroke="white" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
                        </svg>
                      )
                    }
                  </button>
                )}

                {/* Camera-off placeholder */}
                {!cameraOn && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-slate-300">
                    <div className="rounded-2xl border-2 border-dashed border-slate-600 px-8 py-6 text-center">
                      <div className="text-lg font-bold text-white">PLACE PACKAGE INSIDE FRAME</div>
                      <div className="mt-1 text-xs text-slate-400">Package detection · framing · lighting · sharpness</div>
                    </div>
                    {cameraError && (
                      <div className="max-w-xs px-3 py-1 text-center text-xs text-amber-300">{cameraError}</div>
                    )}
                    <Button id="btn-enable-camera" onClick={() => startCamera("environment")}>
                      Enable Camera
                    </Button>
                  </div>
                )}

                {/* Facing mode badge — bottom-left */}
                {cameraOn && (
                  <div className="absolute bottom-2 left-2 rounded-full bg-black/50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white/90 backdrop-blur-sm">
                    {facingMode === "environment" ? "🔭 Rear" : "🤳 Front"}
                  </div>
                )}
              </div>

              {/* Switch error (shown below camera, non-blocking) */}
              {switchError && (
                <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  ⚠️ {switchError}
                </div>
              )}

              {/* SCAN QUALITY panel */}
              {live && (
                <div className="mt-3 rounded-lg bg-slate-50 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-bold uppercase tracking-widest text-slate-500">SCAN QUALITY</span>
                    <QualityBadge overall={live.overall} />
                  </div>
                  <QualityChecks checks={live.checks} />
                </div>
              )}

              {/* Camera action buttons */}
              {cameraOn && (
                <div className="mt-4 flex flex-wrap items-center justify-center gap-3">
                  <Button id="btn-stop-camera" variant="secondary" onClick={stopCamera}>
                    Stop Camera
                  </Button>
                  <Button
                    id="btn-capture"
                    onClick={captureShot}
                    disabled={busy}
                    className="min-w-[160px] px-8 py-3 text-sm font-bold"
                  >
                    {busy ? "Uploading…" : "📷 CAPTURE IMAGE"}
                  </Button>
                </div>
              )}
            </div>
          ) : (
            /* Upload mode */
            <div>
              <label
                id="upload-drop-zone"
                className="flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 p-8 sm:p-10 text-center transition-colors hover:bg-slate-100"
              >
                <span className="text-4xl">📁</span>
                <span className="text-sm font-semibold text-slate-700">Drag &amp; drop image here — or browse files</span>
                <span className="text-xs text-slate-500">JPG · JPEG · PNG · max 15 MB</span>
                <input type="file" accept="image/*" className="hidden" onChange={onPickFile} />
                <Button variant="secondary" className="pointer-events-none mt-1">BROWSE FILES</Button>
              </label>
              {fileName && (
                <div className="mt-2 text-xs text-slate-500">
                  Selected: <span className="font-medium">{fileName}</span>{" "}
                  {busy && <span className="text-navy-600">(uploading…)</span>}
                </div>
              )}
            </div>
          )}

          {/* Post-upload quality report */}
          {lastQuality && (
            <div className="mt-4 rounded-lg border border-slate-200 p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-bold uppercase tracking-widest text-slate-500">Uploaded image validation</span>
                <QualityBadge overall={lastQuality.overall} />
              </div>
              <QualityChecks checks={lastQuality.checks} />
            </div>
          )}
        </Card>

        {/* Coverage + gallery */}
        <div className="space-y-4">
          <Card className="p-4 sm:p-5">
            <div className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-500">Coverage Tracking</div>
            <div className="grid grid-cols-3 gap-2">
              {["front", "back", "side", "top", "declaration", "additional"].map((s) => {
                const im = coverage[s];
                return (
                  <div key={s} className={cn("flex flex-col items-center rounded-lg border p-2 text-center transition-colors",
                    im ? "border-emerald-300 bg-emerald-50" : "border-slate-200 bg-slate-50")}>
                    <span className="text-lg">{im ? "✅" : "⬜"}</span>
                    <span className="mt-0.5 text-[10px] font-bold uppercase text-slate-600">{SIDE_LABEL[s]}</span>
                    {im && <span className="text-[9px] text-emerald-700">{im.image_id}</span>}
                  </div>
                );
              })}
            </div>
            <div className="mt-3 rounded-lg bg-navy-50 px-3 py-2 text-xs text-navy-700">
              <span className="font-bold">Suggested next shot:</span> {nextHint.msg}
            </div>
          </Card>

          <Card className="p-4 sm:p-5">
            <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">
              Captured Images ({images.length})
            </div>
            {images.length === 0 ? (
              <Empty icon="📷" text="No images captured yet." />
            ) : (
              <div className="grid grid-cols-2 gap-3">
                {images.map((im) => (
                  <div key={im.id} className="overflow-hidden rounded-lg border border-slate-200">
                    <img src={fileUrl(im.id)} alt={im.side} className="h-28 w-full object-cover" />
                    <div className="flex items-center justify-between px-2 py-1.5">
                      <span className="text-[10px] font-bold uppercase text-slate-600">{SIDE_LABEL[im.side]}</span>
                      <div className="flex items-center gap-1">
                        {im.is_duplicate && <Badge value="warn" label="dup" />}
                        <QualityBadge overall={im.quality?.overall} />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>

      <NavButtons
        backTo={`/inspector/dashboard`}
        backLabel="← Dashboard"
        continueLabel="Continue to OCR & Extraction →"
        disabled={images.length === 0}
        onContinue={async () => {
          await api.post(`/inspections/${inspection.id}/navigate`, { step: 3 });
          navigate(`/inspector/inspections/${inspection.id}/ocr`);
        }}
      />
    </div>
  );
}

