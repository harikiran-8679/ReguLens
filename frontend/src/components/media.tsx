import React from "react";
import { fileUrl } from "../client";
import { Dot, qualityColor } from "./ui";

/** Image with optional normalised (0..1) bounding-box overlays. */
export function OverlayImage({
  imageId,
  regions,
  selectedRegion,
  alt = "Package image",
  className = "",
  highlight = [],
}: {
  imageId: number;
  regions?: Array<{ region_id?: string; text?: string; bbox?: any; color?: string; label?: string }>;
  selectedRegion?: string;
  alt?: string;
  className?: string;
  highlight?: Array<{ bbox: any; color: string; label?: string }>;
}) {
  return (
    <div className="relative w-full">
      <img src={fileUrl(imageId)} alt={alt} className={className || "w-full rounded-lg"} />
      <div className="pointer-events-none absolute inset-0">
        {(regions || []).map((r, i) => {
          const b = r.bbox;
          if (!b) return null;
          const active = selectedRegion && r.region_id === selectedRegion;
          return (
            <div
              key={`${r.region_id || i}-reg`}
              title={`${r.region_id || ""} ${r.text || ""}`}
              className="absolute border-2"
              style={{
                left: `${b.x * 100}%`,
                top: `${b.y * 100}%`,
                width: `${b.width * 100}%`,
                height: `${b.height * 100}%`,
                borderColor: r.color || (active ? "#d97706" : "#1a3a5c"),
                background: active ? "rgba(217,119,6,0.15)" : "rgba(26,58,92,0.08)",
              }}
            />
          );
        })}
        {highlight.map((h, i) => {
          const b = h.bbox;
          if (!b) return null;
          return (
            <div
              key={`hl-${i}`}
              title={h.label}
              className="absolute border-2"
              style={{
                left: `${b.x * 100}%`,
                top: `${b.y * 100}%`,
                width: `${b.width * 100}%`,
                height: `${b.height * 100}%`,
                borderColor: h.color,
                background: `${h.color}22`,
              }}
            />
          );
        })}
      </div>
    </div>
  );
}

export function QualityChecks({ checks }: { checks?: Array<{ metric: string; status: string; message: string; score: number }> }) {
  if (!checks || checks.length === 0) return null;
  const icon: Record<string, string> = { good: "✓", warn: "!", fail: "✕" };
  return (
    <div className="space-y-1.5">
      {checks.map((c, i) => (
        <div key={i} className="flex items-start gap-2 text-xs">
          <Dot color={qualityColor(c.status)} />
          <div>
            <span className="font-semibold text-slate-700">{c.metric.replace(/_/g, " ")}</span>{" "}
            <span className="text-slate-500">— {c.message}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export function QualityBadge({ overall }: { overall?: string }) {
  if (!overall) return null;
  const color: Record<string, string> = { good: "#16a34a", acceptable: "#d97706", poor: "#dc2626" };
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold">
      <Dot color={color[overall] || "#6b7280"} />
      {overall.toUpperCase()}
    </span>
  );
}
