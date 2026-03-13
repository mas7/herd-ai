"use client";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

const COLORS: Record<string, string> = {
  strong_pursue: "#34d399",
  pursue: "#60a5fa",
  maybe: "#fbbf24",
  skip: "#71717a",
};

interface Props {
  data: Record<string, number>;
}

export function ScoreDistChart({ data }: Props) {
  const chartData = Object.entries(data).map(([bucket, count]) => ({
    name: bucket.replace(/_/g, " "),
    count,
    key: bucket,
  }));

  if (!chartData.length) {
    return <p className="text-zinc-600 text-sm">No scored jobs yet</p>;
  }

  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={chartData} barSize={32}>
        <XAxis dataKey="name" tick={{ fill: "#71717a", fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fill: "#71717a", fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
        <Tooltip
          contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 }}
          cursor={{ fill: "#ffffff08" }}
        />
        <Bar dataKey="count" radius={[4, 4, 0, 0]}>
          {chartData.map((entry) => (
            <Cell key={entry.key} fill={COLORS[entry.key] ?? "#71717a"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
