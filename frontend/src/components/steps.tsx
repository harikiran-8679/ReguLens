import { cn } from "./ui";

export const STEP_LABELS = [
  "Details",
  "Capture",
  "OCR & Extract",
  "Rule Analysis",
  "Result",
  "Findings",
  "Review & Report",
];

export function Stepper({ current, compact = false }: { current: number; compact?: boolean }) {
  return (
    <div className="mb-5 overflow-x-auto scroll-thin">
      <ol className="flex min-w-max items-center gap-1">
        {STEP_LABELS.map((label, i) => {
          const step = i + 1;
          const done = step < current;
          const active = step === current;
          return (
            <li key={label} className="flex items-center">
              <div className="flex items-center gap-1.5">
                <span
                  className={cn(
                    "flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold",
                    done && "bg-emerald-600 text-white",
                    active && "bg-navy-700 text-white ring-4 ring-navy-700/20",
                    !done && !active && "bg-slate-200 text-slate-500"
                  )}
                >
                  {done ? "✓" : step}
                </span>
                {!compact && (
                  <span
                    className={cn(
                      "text-xs font-semibold",
                      active ? "text-navy-800" : done ? "text-emerald-700" : "text-slate-400"
                    )}
                  >
                    {label}
                  </span>
                )}
              </div>
              {step < STEP_LABELS.length && (
                <div className={cn("mx-2 h-0.5 w-4 rounded", step <= current ? "bg-navy-600" : "bg-slate-200")} />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
