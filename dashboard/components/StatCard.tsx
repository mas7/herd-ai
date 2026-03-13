interface StatCardProps {
  label: string;
  value: number | string;
  sub?: string;
  accent?: "emerald" | "blue" | "amber" | "rose" | "zinc";
}

const accents = {
  emerald: "text-emerald-400",
  blue: "text-blue-400",
  amber: "text-amber-400",
  rose: "text-rose-400",
  zinc: "text-zinc-400",
};

export function StatCard({ label, value, sub, accent = "zinc" }: StatCardProps) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
      <p className="text-xs text-zinc-500 uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-3xl font-bold tabular-nums ${accents[accent]}`}>{value}</p>
      {sub && <p className="text-xs text-zinc-600 mt-1">{sub}</p>}
    </div>
  );
}
