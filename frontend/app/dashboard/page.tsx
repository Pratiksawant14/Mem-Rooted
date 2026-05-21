"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { getMemoryStats, getSchedulerStatus, MemoryStats, SchedulerStatus } from "@/lib/api";
import OverviewView from "@/components/dashboard/OverviewView";
import SearchView from "@/components/dashboard/SearchView";
import NetworkView from "@/components/dashboard/NetworkView";
import SchedulerView from "@/components/dashboard/SchedulerView";

type View = "overview" | "search" | "network" | "scheduler";

const NAV_ITEMS: { key: View; label: string; icon: JSX.Element }[] = [
  {
    key: "overview",
    label: "Overview",
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </svg>
    ),
  },
  {
    key: "search",
    label: "Search",
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="11" cy="11" r="8" />
        <path d="M21 21l-4.35-4.35" />
      </svg>
    ),
  },
  {
    key: "network",
    label: "Network",
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="5" r="3" />
        <circle cx="5" cy="19" r="3" />
        <circle cx="19" cy="19" r="3" />
        <path d="M12 8v3M9.5 14.5L7 17M14.5 14.5L17 17" />
      </svg>
    ),
  },
  {
    key: "scheduler",
    label: "Scheduler",
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
    ),
  },
];

export default function DashboardPage() {
  const [activeView, setActiveView] = useState<View>("overview");
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [schedulerStatus, setSchedulerStatus] = useState<SchedulerStatus | null>(null);

  const router = useRouter();
  const [username, setUsername] = useState<string | null>(null);

  useEffect(() => {
    const userId = localStorage.getItem("mem_user_id");
    const uname = localStorage.getItem("mem_username");
    if (!userId) {
      router.push("/login");
    } else {
      setUsername(uname);
    }
    
    getMemoryStats().then(setStats).catch(() => {});
    getSchedulerStatus().then(setSchedulerStatus).catch(() => {});
  }, [router]);

  if (!username) return null;

  // Derive last run
  let lastRunLabel = "—";
  if (schedulerStatus) {
    const times = Object.values(schedulerStatus.jobs)
      .map((j) => j.last_run)
      .filter(Boolean) as string[];
    if (times.length > 0) {
      const latest = times.sort().reverse()[0];
      const d = new Date(latest);
      const mins = Math.floor((Date.now() - d.getTime()) / 60000);
      if (mins < 1) lastRunLabel = "just now";
      else if (mins < 60) lastRunLabel = `${mins}m ago`;
      else lastRunLabel = `${Math.floor(mins / 60)}h ago`;
    }
  }

  return (
    <div className="flex h-full">
      {/* ══════ Left Sidebar ══════ */}
      <aside
        className="flex flex-col h-full border-r border-border bg-surface shrink-0"
        style={{ width: 220 }}
      >
        {/* Logo */}
        <div className="px-5 py-5 border-b border-border mb-2">
          <Link href="/" className="hover:opacity-80 transition-opacity block mb-3">
            <h1 className="text-base font-semibold text-primary tracking-tight">Mem-Rooted</h1>
            <p className="text-[10px] text-text-muted mt-0.5">← Back to Chat</p>
          </Link>
          <div className="flex items-center justify-between">
            <div className="px-2 py-1 rounded bg-surface-elevated text-xs text-text-secondary border border-border">
              <span className="text-primary mr-1">●</span> {username}
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 space-y-0.5">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              onClick={() => setActiveView(item.key)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium
                transition-all ${
                  activeView === item.key
                    ? "bg-primary/10 text-primary"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface-elevated"
                }`}
            >
              <span className={activeView === item.key ? "text-primary" : "text-text-muted"}>
                {item.icon}
              </span>
              {item.label}
            </button>
          ))}
        </nav>

        {/* Bottom stats */}
        <div className="px-5 py-4 border-t border-border space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-text-muted">Nodes</span>
            <span className="text-text-primary font-mono font-medium">
              {stats?.total_active ?? "—"}
            </span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-text-muted">Last job</span>
            <span className="text-text-secondary font-mono">{lastRunLabel}</span>
          </div>
        </div>
      </aside>

      {/* ══════ Main Content ══════ */}
      <main className="flex-1 h-full overflow-hidden">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeView}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.15 }}
            className="h-full"
          >
            {activeView === "overview" && <OverviewView />}
            {activeView === "search" && <SearchView />}
            {activeView === "network" && <NetworkView />}
            {activeView === "scheduler" && <SchedulerView />}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
