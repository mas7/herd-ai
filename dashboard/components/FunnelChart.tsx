"use client";
import { PipelineFunnel } from "@/lib/api";

const STAGES = [
  { key: "discovered", label: "Discovered", color: "bg-zinc-600" },
  { key: "passed_fast", label: "Fast Filter", color: "bg-blue-700" },
  { key: "deep_scored", label: "Deep Scored", color: "bg-blue-500" },
  { key: "bid_decided", label: "Bid Decided", color: "bg-violet-500" },
  { key: "proposed", label: "Proposed", color: "bg-amber-500" },
  { key: "submitted", label: "Submitted", color: "bg-emerald-600" },
  { key: "won", label: "Won", color: "bg-emerald-400" },
] as const;

export function FunnelChart({ data }: { data: PipelineFunnel }) {
  const max = data.discovered || 1;

  return (
    <div className="space-y-2">
      {STAGES.map(({ key, label, color }) => {
        const val = data[key] ?? 0;
        const pct = Math.round((val / max) * 100);
        return (
          <div key={key} className="flex items-center gap-3">
            <span className="text-xs text-zinc-500 w-24 shrink-0 text-right">{label}</span>
            <div className="flex-1 bg-zinc-800 rounded-full h-2.5 overflow-hidden">
              <div className={`${color} h-full rounded-full transition-all`} style={{ width: `${pct}%` }} />
            </div>
            <span className="text-xs tabular-nums text-zinc-400 w-8 text-right">{val}</span>
          </div>
        );
      })}
    </div>
  );
}
