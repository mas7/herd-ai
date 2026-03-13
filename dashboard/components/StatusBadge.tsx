const STATUS_STYLES: Record<string, string> = {
  discovered: "bg-zinc-800 text-zinc-400",
  scored: "bg-blue-950 text-blue-400",
  rejected: "bg-rose-950 text-rose-400",
  bid_decided: "bg-violet-950 text-violet-400",
  proposal_drafted: "bg-amber-950 text-amber-400",
  proposal_submitted: "bg-emerald-950 text-emerald-400",
  passed: "bg-zinc-800 text-zinc-500",
  won: "bg-emerald-950 text-emerald-300",
  lost: "bg-rose-950 text-rose-300",
  no_response: "bg-zinc-800 text-zinc-400",
  bid: "bg-violet-950 text-violet-400",
  pass: "bg-zinc-800 text-zinc-500",
  strong_pursue: "bg-emerald-950 text-emerald-400",
  pursue: "bg-blue-950 text-blue-400",
  maybe: "bg-amber-950 text-amber-400",
  skip: "bg-zinc-800 text-zinc-500",
};

export function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status] ?? "bg-zinc-800 text-zinc-400";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}
