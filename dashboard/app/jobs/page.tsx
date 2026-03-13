import { apiFetch, Job } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import Link from "next/link";

export const revalidate = 10;

function budget(job: Job): string {
  if (job.job_type === "hourly") {
    const lo = job.hourly_rate_min ? `$${job.hourly_rate_min}` : "?";
    const hi = job.hourly_rate_max ? `$${job.hourly_rate_max}` : "?";
    return `${lo}–${hi}/hr`;
  }
  const lo = job.budget_min ? `$${job.budget_min}` : "?";
  const hi = job.budget_max ? `$${job.budget_max}` : "?";
  return `${lo}–${hi}`;
}

function skills(job: Job): string[] {
  if (!job.required_skills) return [];
  return job.required_skills.split(",").map((s) => s.trim()).filter(Boolean).slice(0, 4);
}

export default async function JobsPage() {
  let jobs: Job[] = [];
  let counts: Record<string, number> = {};

  try {
    [jobs, counts] = await Promise.all([
      apiFetch<Job[]>("/api/jobs?limit=100"),
      apiFetch<Record<string, number>>("/api/jobs/counts"),
    ]);
  } catch {
    /* API offline */
  }

  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Jobs</h1>
          <p className="text-sm text-zinc-500 mt-0.5">{total} total discovered</p>
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

      <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-xs text-zinc-500 uppercase">
              <th className="px-5 py-3 text-left">Title</th>
              <th className="px-4 py-3 text-left">Type</th>
              <th className="px-4 py-3 text-left">Budget</th>
              <th className="px-4 py-3 text-left">Skills</th>
              <th className="px-4 py-3 text-left">Status</th>
              <th className="px-4 py-3 text-left">Country</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id} className="border-b border-zinc-800/60 hover:bg-zinc-800/30 transition-colors">
                <td className="px-5 py-3">
                  <a
                    href={job.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-zinc-200 hover:text-emerald-400 transition-colors max-w-xs truncate block"
                  >
                    {job.title}
                  </a>
                </td>
                <td className="px-4 py-3 text-zinc-500 text-xs">{job.job_type}</td>
                <td className="px-4 py-3 text-zinc-400 text-xs tabular-nums whitespace-nowrap">{budget(job)}</td>
                <td className="px-4 py-3">
                  <div className="flex gap-1 flex-wrap">
                    {skills(job).map((s) => (
                      <span key={s} className="bg-zinc-800 text-zinc-400 text-xs px-1.5 py-0.5 rounded">{s}</span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3"><StatusBadge status={job.status} /></td>
                <td className="px-4 py-3 text-zinc-500 text-xs">{job.client_country ?? "—"}</td>
              </tr>
            ))}
            {jobs.length === 0 && (
              <tr>
                <td colSpan={6} className="px-5 py-10 text-center text-zinc-600">
                  No jobs discovered yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
