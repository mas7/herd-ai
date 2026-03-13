import { apiFetch, Proposal } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";

export const revalidate = 10;

export default async function ProposalsPage() {
  let proposals: Proposal[] = [];
  let counts: Record<string, number> = {};

  try {
    [proposals, counts] = await Promise.all([
      apiFetch<Proposal[]>("/api/proposals?limit=100"),
      apiFetch<Record<string, number>>("/api/proposals/counts"),
    ]);
  } catch {
    /* API offline */
  }

  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Proposals</h1>
          <p className="text-sm text-zinc-500 mt-0.5">{total} total generated</p>
        </div>
        <div className="flex gap-2 flex-wrap justify-end">
          {Object.entries(counts).map(([status, count]) => (
            <span key={status} className="flex items-center gap-1.5 text-xs text-zinc-400">
              <StatusBadge status={status} />
              <span className="text-zinc-600">{count}</span>
            </span>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        {proposals.map((p) => (
          <div key={p.id} className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-3">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="font-medium text-zinc-200">{p.job_title}</p>
                <p className="text-xs text-zinc-500 mt-0.5">
                  {p.client_country ?? "Unknown"} · {p.bid_type} · ${p.bid_amount}
                  {p.bid_type === "hourly" ? "/hr" : " fixed"}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {p.confidence != null && (
                  <span className="text-xs text-zinc-500">
                    {p.confidence.toFixed(0)}% confidence
                  </span>
                )}
                <StatusBadge status={p.status} />
              </div>
            </div>

            {p.positioning_angle && (
              <p className="text-xs text-emerald-400 italic">"{p.positioning_angle}"</p>
            )}

            <div className="bg-zinc-950 rounded-lg p-4">
              <p className="text-xs text-zinc-500 mb-2 uppercase tracking-wider">Cover Letter</p>
              <p className="text-sm text-zinc-300 leading-relaxed whitespace-pre-wrap">{p.cover_letter}</p>
            </div>

            <p className="text-xs text-zinc-600">
              Generated {new Date(p.created_at).toLocaleString()}
              {p.submitted_at && ` · Submitted ${new Date(p.submitted_at).toLocaleString()}`}
            </p>
          </div>
        ))}

        {proposals.length === 0 && (
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-10 text-center text-zinc-600">
            No proposals generated yet
          </div>
        )}
      </div>
    </div>
  );
}
