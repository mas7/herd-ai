import { apiFetch, DashboardSummary, PipelineFunnel } from "@/lib/api";
import { StatCard } from "@/components/StatCard";
import { StatusBadge } from "@/components/StatusBadge";
import { ScoreDistChart } from "@/components/ScoreDistChart";
import { FunnelChart } from "@/components/FunnelChart";

export const revalidate = 10;

function fmt(n: number | null, decimals = 1): string {
  if (n == null) return "—";
  return n.toFixed(decimals);
}

function winRate(stats: DashboardSummary["win_stats"]): string {
  if (!stats.total) return "—";
  return `${((stats.won / stats.total) * 100).toFixed(0)}%`;
}

export default async function OverviewPage() {
  let summary: DashboardSummary | null = null;
  let funnel: PipelineFunnel | null = null;
  let error = false;

  try {
    [summary, funnel] = await Promise.all([
      apiFetch<DashboardSummary>("/api/dashboard/summary"),
      apiFetch<PipelineFunnel>("/api/dashboard/pipeline"),
    ]);
  } catch {
    error = true;
  }

  if (error || !summary) {
    return (
      <div className="p-8">
        <div className="bg-rose-950/40 border border-rose-800 rounded-xl p-6 text-rose-400">
          <p className="font-medium">Cannot reach API</p>
          <p className="text-sm mt-1 text-rose-500">
            Start the backend: <code className="font-mono">uvicorn src.api.app:app --reload</code>
          </p>
        </div>
      </div>
    );
  }

  const { totals, score_distribution, recent_jobs, win_stats, avg_scores } = summary;

  return (
    <div className="p-8 space-y-8">
      <div>
        <h1 className="text-xl font-semibold">Overview</h1>
        <p className="text-sm text-zinc-500 mt-0.5">Pipeline snapshot — auto-refreshes every 10s</p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
        <StatCard label="Jobs Discovered" value={totals.jobs} accent="zinc" />
        <StatCard label="Deep Scored" value={totals.scored} accent="blue" />
        <StatCard label="Rejected" value={totals.rejected} accent="rose" />
        <StatCard label="Bid Decided" value={totals.bid_decided} accent="blue" />
        <StatCard label="Proposals" value={totals.proposal_drafted} accent="amber" />
        <StatCard label="Win Rate" value={winRate(win_stats)} sub={`${win_stats.won}W / ${win_stats.lost}L`} accent="emerald" />
      </div>

      {/* Avg scores row */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard
          label="Avg Final Score"
          value={fmt(avg_scores.avg_final_score)}
          sub="out of 100"
          accent="blue"
        />
        <StatCard
          label="Avg Win Probability"
          value={fmt(avg_scores.avg_win_probability)}
          sub="analyst estimate"
          accent="emerald"
        />
        <StatCard
          label="Avg Relevance"
          value={fmt(avg_scores.avg_relevance)}
          sub="skill match signal"
          accent="blue"
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-zinc-400 mb-4">Score Distribution</h2>
          <ScoreDistChart data={score_distribution} />
        </div>
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-zinc-400 mb-4">Pipeline Funnel</h2>
          {funnel ? <FunnelChart data={funnel} /> : <p className="text-zinc-600 text-sm">No data</p>}
        </div>
      </div>

      {/* Recent jobs */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-zinc-800">
          <h2 className="text-sm font-medium">Recent Jobs</h2>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-xs text-zinc-500 uppercase">
              <th className="px-5 py-3 text-left">Title</th>
              <th className="px-4 py-3 text-left">Status</th>
              <th className="px-4 py-3 text-right">Score</th>
              <th className="px-4 py-3 text-left">Rec.</th>
              <th className="px-4 py-3 text-left">Bid</th>
              <th className="px-4 py-3 text-right">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {recent_jobs.map((job) => (
              <tr key={job.id} className="border-b border-zinc-800/60 hover:bg-zinc-800/30 transition-colors">
                <td className="px-5 py-3 max-w-xs truncate font-medium text-zinc-200">{job.title}</td>
                <td className="px-4 py-3"><StatusBadge status={job.status} /></td>
                <td className="px-4 py-3 text-right tabular-nums text-zinc-400">
                  {job.final_score != null ? job.final_score.toFixed(1) : "—"}
                </td>
                <td className="px-4 py-3">
                  {job.recommendation ? <StatusBadge status={job.recommendation} /> : <span className="text-zinc-600">—</span>}
                </td>
                <td className="px-4 py-3">
                  {job.decision ? <StatusBadge status={job.decision} /> : <span className="text-zinc-600">—</span>}
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-zinc-400">
                  {job.bid_confidence != null ? `${job.bid_confidence.toFixed(0)}%` : "—"}
                </td>
              </tr>
            ))}
            {recent_jobs.length === 0 && (
              <tr>
                <td colSpan={6} className="px-5 py-8 text-center text-zinc-600">
                  No jobs yet — start the Recon department to discover jobs
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
