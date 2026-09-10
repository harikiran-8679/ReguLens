import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmtDate } from "../client";
import { Badge, Button, Spinner, ErrorBox } from "./ui";
import { Stepper } from "./steps";

export function useInspection(inspectionId: string | undefined) {
  const [inspection, setInspection] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = async () => {
    try {
      setLoading(true);
      setError("");
      const data = await api.get(`/inspections/${inspectionId}`);
      setInspection(data);
    } catch (e: any) {
      setError(e.message || "Failed to load inspection");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (inspectionId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inspectionId]);

  const navigateStep = async (step: number) => {
    if (!inspection) return;
    const data = await api.post(`/inspections/${inspection.id}/navigate`, { step });
    setInspection(data);
  };

  return { inspection, setInspection, loading, error, load, navigateStep };
}

export function FlowHeader({
  inspection,
  step,
  title,
  subtitle,
}: {
  inspection: any;
  step: number;
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="mb-4">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-xs font-bold uppercase tracking-widest text-navy-600">{title}</div>
          <div className="text-lg font-bold text-navy-800">
            {inspection.product_name || "New Inspection"}
            <span className="ml-2 text-sm font-semibold text-slate-400">
              Inspection ID: {inspection.inspection_id} · {fmtDate(inspection.inspection_date)}
            </span>
          </div>
          {subtitle && <div className="text-xs text-slate-500">{subtitle}</div>}
        </div>
        <div className="flex items-center gap-2">
          <Badge value={inspection.status} />
          <Badge value={inspection.automated_result} />
        </div>
      </div>
      <Stepper current={Math.max(step, inspection.current_step || 1)} />
    </div>
  );
}

export function FlowLoader({ inspectionId, step, children, title, subtitle }: {
  inspectionId: string | undefined;
  step: number;
  children: (ctx: any) => React.ReactNode;
  title: string;
  subtitle?: string;
}) {
  const { inspection, loading, error, setInspection } = useInspection(inspectionId);
  if (loading) return <Spinner label="Loading inspection…" />;
  if (error || !inspection) return <ErrorBox error={error || "Inspection not found"} />;
  return (
    <div>
      <FlowHeader inspection={inspection} step={step} title={title} subtitle={subtitle} />
      {children({ inspection, setInspection })}
    </div>
  );
}

export function NavButtons({
  backLabel = "← Back",
  backTo,
  onBack,
  continueLabel = "Continue →",
  continueTo,
  onContinue,
  disabled = false,
  extra,
}: {
  backLabel?: string;
  backTo?: string;
  onBack?: () => void;
  continueLabel?: string;
  continueTo?: string;
  onContinue?: () => void;
  disabled?: boolean;
  extra?: React.ReactNode;
}) {
  const navigate = useNavigate();
  return (
    <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4">
      <Button variant="secondary" onClick={onBack || (() => navigate(backTo || "..", { relative: "route" }))}>
        {backLabel}
      </Button>
      <div className="flex items-center gap-2">
        {extra}
        <Button
          disabled={disabled}
          onClick={onContinue || (() => navigate(continueTo || ""))}
        >
          {continueLabel}
        </Button>
      </div>
    </div>
  );
}
