import { apiFetch, PipelineFunnel } from "@/lib/api";
import { FunnelChart } from "@/components/FunnelChart";

export const revalidate = 10;

const STAGE_DESCRIPTIONS: Record<string, string> = {
  discovered: "Jobs scraped from Upwork by the Recon department",
  passed_fast: "Passed the rule-based fast filter (<100ms, no LLM cost)",
  deep_scored: "Received full LLM deep analysis and scoring",
  bid_decided: "BizDev decided to bid (pricing + positioning angle set)",
  proposed: "Content department generated a cover letter via RAG + LLM",
  submitted: "Execution department submitted the proposal on Upwork",
  won: "Client accepted — contract awarded",
};

export default async function PipelinePage() {
  let funnel: PipelineFunnel | null = null;

  try {
    funnel = await apiFetch<PipelineFunnel>("/api/dashboard/pipeline");
  } catch {
    /* API offline */
  }

  const stages = [
    { key: "discovered", label: "Discovered" },
    { key: "passed_fast", label: "Fast Filter Pass" },
    { key: "deep_scored", label: "Deep Scored" },
    { key: "bid_decided", label: "Bid Decided" },
    { key: "proposed", label: "Proposed" },
    { key: "submitted", label: "Submitted" },
    { key: "won", label: "Won" },
  ] as const;

  return (
    <div className="p-8 space-y-8">
      <div>
        <h1 className="text-xl font-semibold">Pipeline</h1>
        <p className="text-sm text-zinc-500 mt-0.5">End-to-end funnel — Recon → Analyst → BizDev → Content → Execution</p>
      </div>

      {/* Visual funnel */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
        <h2 className="text-sm font-medium text-zinc-400 mb-5">Funnel</h2>
        {funnel ? <FunnelChart data={funnel} /> : (
          <p className="text-zinc-600 text-sm">API offline — start the backend to see data</p>
        )}
      </div>

      {/* Stage breakdown table */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-zinc-800">
          <h2 className="text-sm font-medium">Stage Breakdown</h2>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-xs text-zinc-500 uppercase">
              <th className="px-5 py-3 text-left">Stage</th>
              <th className="px-4 py-3 text-right">Count</th>
              <th className="px-4 py-3 text-right">Drop-off</th>
              <th className="px-4 py-3 text-left">Department</th>
              <th className="px-5 py-3 text-left">Description</th>
            </tr>
          </thead>
          <tbody>
            {stages.map(({ key, label }, i) => {
              const val = funnel?.[key] ?? 0;
              const prev = i === 0 ? val : (funnel?.[stages[i - 1].key] ?? 0);
              const dropoff = prev > 0 ? Math.round(((prev - val) / prev) * 100) : 0;
              const depts = ["Recon", "Analyst", "Analyst", "BizDev", "Content", "Execution", "—"];
              return (
                <tr key={key} className="border-b border-zinc-800/60">
                  <td className="px-5 py-3 font-medium text-zinc-200">{label}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-zinc-300">{val}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-xs">
                    {i > 0 && dropoff > 0 ? (
                      <span className="text-rose-400">−{dropoff}%</span>
                    ) : (
                      <span className="text-zinc-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-zinc-500">{depts[i]}</td>
                  <td className="px-5 py-3 text-xs text-zinc-500">{STAGE_DESCRIPTIONS[key]}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
