const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

export interface DashboardSummary {
  totals: {
    jobs: number;
    scored: number;
    rejected: number;
    bid_decided: number;
    proposal_drafted: number;
    passed: number;
  };
  job_counts: Record<string, number>;
  proposal_counts: Record<string, number>;
  bid_counts: Record<string, number>;
  score_distribution: Record<string, number>;
  recent_jobs: RecentJob[];
  win_stats: { total: number; won: number; lost: number; no_response: number };
  avg_scores: {
    avg_final_score: number | null;
    avg_win_probability: number | null;
    avg_relevance: number | null;
  };
}

export interface PipelineFunnel {
  discovered: number;
  passed_fast: number;
  deep_scored: number;
  bid_decided: number;
  proposed: number;
  submitted: number;
  won: number;
}

export interface RecentJob {
  id: string;
  title: string;
  status: string;
  platform: string;
  posted_at: string;
  discovered_at: string;
  final_score: number | null;
  recommendation: string | null;
  decision: string | null;
  bid_amount: number | null;
  bid_confidence: number | null;
}

export interface Job {
  id: string;
  title: string;
  status: string;
  platform: string;
  platform_job_id: string;
  url: string;
  job_type: string;
  description: string;
  hourly_rate_min: number | null;
  hourly_rate_max: number | null;
  budget_min: number | null;
  budget_max: number | null;
  required_skills: string | null;
  client_country: string | null;
  client_rating: number | null;
  proposals_count: number | null;
  posted_at: string;
  discovered_at: string;
}

export interface Proposal {
  id: string;
  job_id: string;
  job_title: string;
  client_country: string | null;
  platform: string;
  bid_type: string;
  bid_amount: number;
  cover_letter: string;
  confidence: number | null;
  positioning_angle: string | null;
  status: string;
  created_at: string;
  submitted_at: string | null;
}
