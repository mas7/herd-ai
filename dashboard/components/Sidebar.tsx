"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Briefcase, FileText, GitBranch, Activity } from "lucide-react";

const nav = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/pipeline", label: "Pipeline", icon: GitBranch },
  { href: "/jobs", label: "Jobs", icon: Briefcase },
  { href: "/proposals", label: "Proposals", icon: FileText },
];

export function Sidebar() {
  const path = usePathname();
  return (
    <aside className="w-56 border-r border-zinc-800 flex flex-col bg-zinc-900/50">
      <div className="px-5 py-5 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <Activity className="text-emerald-400" size={18} />
          <span className="font-semibold tracking-tight text-sm">Herd AI</span>
        </div>
        <p className="text-xs text-zinc-500 mt-0.5">Mission Control</p>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {nav.map(({ href, label, icon: Icon }) => {
          const active = path === href;
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors ${
                active
                  ? "bg-zinc-800 text-zinc-100"
                  : "text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/50"
              }`}
            >
              <Icon size={15} />
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="px-5 py-3 border-t border-zinc-800">
        <p className="text-xs text-zinc-600">v0.1.0</p>
      </div>
    </aside>
  );
}
