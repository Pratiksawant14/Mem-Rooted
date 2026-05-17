"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { getSchedulerStatus, triggerSchedulerJob, SchedulerStatus, SchedulerJob } from "@/lib/api";

/* ═══════════════════════════════════════════════════════════════════════════ */

const JOB_CONFIG: Record<
  string,
  { name: string; description: string; interval: string; color: string }
> = {
  decay_sweep: {
    name: "Decay Sweep",
    description: "Apply exponential decay to all non-ANCHOR nodes, archive dead memories",
    interval: "Every 6 hours",
    color: "var(--decay-critical)",
  },
  promotion_sweep: {
    name: "Promotion Sweep",
    description: "Recompute weights, promote high-value nodes, demote fading ones",
    interval: "Every 12 hours",
    color: "var(--anchor)",
  },
  merge_sweep: {
    name: "Merge Sweep",
    description: "Find and merge semantically similar sibling nodes",
    interval: "Every 24 hours",
    color: "var(--domain)",
  },
  split_sweep: {
    name: "Split Sweep",
    description: "Split overloaded nodes with divergent children",
    interval: "Every 24 hours",
    color: "var(--instance)",
  },
  lateral_link_refresh: {
    name: "Lateral Link Refresh",
    description: "Discover new cross-branch connections, strengthen or weaken existing links",
    interval: "Every 48 hours",
    color: "var(--primary)",
  },
};

const TRIGGER_MAP: Record<string, string> = {
  decay_sweep: "decay",
  promotion_sweep: "promotion",
  merge_sweep: "merge",
  split_sweep: "split",
  lateral_link_refresh: "lateral",
};

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h ago`;
  return `${Math.floor(mins / 1440)}d ago`;
}

function estimateNextRun(key: string, lastRun: string | null): string {
  if (!lastRun) return "pending";
  const intervals: Record<string, number> = {
    decay_sweep: 6 * 60,
    promotion_sweep: 12 * 60,
    merge_sweep: 24 * 60,
    split_sweep: 24 * 60 + 30,
    lateral_link_refresh: 48 * 60,
  };
  const intervalMin = intervals[key] || 360;
  const d = new Date(lastRun);
  const nextMs = d.getTime() + intervalMin * 60000;
  const diff = nextMs - Date.now();
  if (diff <= 0) return "overdue";
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `in ${mins}m`;
  return `in ${Math.floor(mins / 60)}h`;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Job Card
   ═══════════════════════════════════════════════════════════════════════════ */

function JobCard({
  jobKey,
  job,
  onTrigger,
}: {
  jobKey: string;
  job: SchedulerJob;
  onTrigger: (key: string) => Promise<void>;
}) {
  const [triggering, setTriggering] = useState(false);
  const [result, setResult] = useState<number | null>(null);
  const config = JOB_CONFIG[jobKey];

  const handleTrigger = async () => {
    setTriggering(true);
    setResult(null);
    try {
      await onTrigger(jobKey);
      setResult(job.operations);
    } catch {
      setResult(-1);
    }
    setTriggering(false);
    // Clear result after 3s
    setTimeout(() => setResult(null), 3000);
  };

  const hasError = job.errors > 0;
  const hasRun = job.last_run !== null;

  return (
    <div className="bg-surface rounded-xl border border-border p-4 relative overflow-hidden">
      {/* Color accent */}
      <div
        className="absolute left-0 top-0 bottom-0 w-[3px] rounded-l-xl"
        style={{ backgroundColor: config?.color || "var(--primary)" }}
      />

      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">{config?.name || jobKey}</h3>
          <p className="text-[10px] text-text-muted mt-0.5">{config?.interval || "—"}</p>
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className="w-2 h-2 rounded-full"
            style={{
              backgroundColor: hasError
                ? "var(--decay-critical)"
                : hasRun
                ? "var(--decay-healthy)"
                : "var(--text-muted)",
            }}
          />
          <span className="text-[10px] text-text-muted">
            {hasError ? "Error" : hasRun ? "Idle" : "Pending"}
          </span>
        </div>
      </div>

      {/* Description */}
      <p className="text-xs text-text-secondary leading-relaxed mb-4">
        {config?.description || ""}
      </p>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-2 mb-4">
        <div className="bg-surface-elevated rounded-lg p-2">
          <p className="text-[9px] text-text-muted uppercase">Last Run</p>
          <p className="text-xs text-text-primary font-mono mt-0.5">
            {relativeTime(job.last_run)}
          </p>
        </div>
        <div className="bg-surface-elevated rounded-lg p-2">
          <p className="text-[9px] text-text-muted uppercase">Next Run</p>
          <p className="text-xs text-text-primary font-mono mt-0.5">
            {estimateNextRun(jobKey, job.last_run)}
          </p>
        </div>
        <div className="bg-surface-elevated rounded-lg p-2">
          <p className="text-[9px] text-text-muted uppercase">Operations</p>
          <p className="text-xs text-text-primary font-mono mt-0.5">{job.operations}</p>
        </div>
      </div>

      {/* Trigger button */}
      <button
        onClick={handleTrigger}
        disabled={triggering}
        className="w-full flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-medium
                   border border-primary/30 text-primary
                   hover:bg-primary/10 hover:border-primary/50
                   disabled:opacity-50 disabled:cursor-wait
                   transition-all"
      >
        {triggering ? (
          <>
            <svg className="animate-spin w-3.5 h-3.5" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
              <path
                d="M12 2a10 10 0 019.95 9"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
              />
            </svg>
            Running...
          </>
        ) : result !== null ? (
          <span className={result >= 0 ? "text-decay-healthy" : "text-decay-critical"}>
            {result >= 0 ? `✓ Complete` : "✗ Failed"}
          </span>
        ) : (
          "Trigger Now"
        )}
      </button>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Operation Log Table
   ═══════════════════════════════════════════════════════════════════════════ */

function OperationLog({ scheduler }: { scheduler: SchedulerStatus }) {
  // Extract log entries from job details
  const entries: { job: string; type: string; count: number; timestamp: string }[] = [];

  const JOB_NAMES: Record<string, string> = {
    decay_sweep: "Decay",
    promotion_sweep: "Promotion",
    merge_sweep: "Merge",
    split_sweep: "Split",
    lateral_link_refresh: "Lateral",
  };

  for (const [key, job] of Object.entries(scheduler.jobs)) {
    if (!job.last_run || job.operations === 0) continue;
    const details = job.details as Record<string, unknown>;
    for (const [detailKey, value] of Object.entries(details)) {
      if (
        typeof value === "number" &&
        value > 0 &&
        !["total_scanned", "nodes_scanned", "errors"].includes(detailKey)
      ) {
        entries.push({
          job: JOB_NAMES[key] || key,
          type: detailKey,
          count: value,
          timestamp: job.last_run,
        });
      }
    }
  }

  entries.sort((a, b) => (b.timestamp > a.timestamp ? 1 : -1));

  const OP_COLORS: Record<string, string> = {
    promoted: "var(--anchor)",
    demoted: "var(--decay-warning)",
    merged: "var(--domain)",
    split: "var(--instance)",
    decayed: "var(--cluster)",
    archived: "var(--decay-critical)",
    added: "var(--decay-healthy)",
    strengthened: "var(--domain)",
    weakened: "var(--decay-warning)",
  };

  if (entries.length === 0) {
    return (
      <p className="text-xs text-text-muted text-center py-8">
        No operations recorded yet
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border">
            <th className="text-left text-text-muted font-medium uppercase tracking-wider text-[10px] py-2 px-3">
              Timestamp
            </th>
            <th className="text-left text-text-muted font-medium uppercase tracking-wider text-[10px] py-2 px-3">
              Job
            </th>
            <th className="text-left text-text-muted font-medium uppercase tracking-wider text-[10px] py-2 px-3">
              Operation
            </th>
            <th className="text-right text-text-muted font-medium uppercase tracking-wider text-[10px] py-2 px-3">
              Count
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.slice(0, 50).map((entry, i) => (
            <tr
              key={i}
              className="border-b border-border/50 hover:bg-surface-elevated transition-colors"
            >
              <td className="py-2.5 px-3 text-text-muted font-mono">
                {relativeTime(entry.timestamp)}
              </td>
              <td className="py-2.5 px-3 text-text-secondary">{entry.job}</td>
              <td className="py-2.5 px-3">
                <span
                  className="px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase"
                  style={{
                    backgroundColor: (OP_COLORS[entry.type] || "#555") + "20",
                    color: OP_COLORS[entry.type] || "#888",
                  }}
                >
                  {entry.type}
                </span>
              </td>
              <td className="py-2.5 px-3 text-right text-text-primary font-mono">
                {entry.count}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SchedulerView
   ═══════════════════════════════════════════════════════════════════════════ */

export default function SchedulerView() {
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const s = await getSchedulerStatus();
      setScheduler(s);
    } catch {
      // ignore
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Auto-refresh
  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(fetchStatus, 30000);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [autoRefresh, fetchStatus]);

  const handleTrigger = useCallback(
    async (jobKey: string) => {
      const triggerName = TRIGGER_MAP[jobKey] || jobKey;
      await triggerSchedulerJob(triggerName);
      // Refresh status after trigger
      setTimeout(fetchStatus, 1000);
    },
    [fetchStatus]
  );

  const JOB_ORDER = [
    "decay_sweep",
    "promotion_sweep",
    "merge_sweep",
    "split_sweep",
    "lateral_link_refresh",
  ];

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6 max-w-5xl">
        {/* ── Header ──────────────────────────────────── */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-lg font-semibold text-text-primary mb-0.5">Scheduler</h2>
            <p className="text-sm text-text-muted">Background memory maintenance jobs</p>
          </div>

          <div className="flex items-center gap-3">
            {/* Status */}
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface border border-border text-xs">
              <span
                className="w-2 h-2 rounded-full"
                style={{
                  backgroundColor: scheduler?.scheduler_running
                    ? "var(--decay-healthy)"
                    : "var(--decay-critical)",
                }}
              />
              <span className="text-text-secondary">
                {scheduler?.scheduler_running ? "Running" : "Stopped"}
              </span>
            </div>

            {/* Auto-refresh toggle */}
            <button
              onClick={() => setAutoRefresh(!autoRefresh)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                autoRefresh
                  ? "bg-primary/10 border-primary/30 text-primary"
                  : "bg-surface border-border text-text-muted hover:text-text-secondary"
              }`}
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className={autoRefresh ? "animate-spin" : ""}
                style={{ animationDuration: "3s" }}
              >
                <path d="M21 12a9 9 0 11-2.636-6.364" />
                <path d="M21 3v5h-5" />
              </svg>
              Auto-refresh
            </button>
          </div>
        </div>

        {/* ── Job Cards Grid ─────────────────────────── */}
        {scheduler && (
          <div className="grid grid-cols-2 gap-3 mb-6">
            {JOB_ORDER.slice(0, 4).map((key) => {
              const job = scheduler.jobs[key];
              if (!job) return null;
              return (
                <motion.div
                  key={key}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2 }}
                >
                  <JobCard jobKey={key} job={job} onTrigger={handleTrigger} />
                </motion.div>
              );
            })}
            {/* Last card full width */}
            {scheduler.jobs[JOB_ORDER[4]] && (
              <motion.div
                className="col-span-2"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2, delay: 0.1 }}
              >
                <JobCard
                  jobKey={JOB_ORDER[4]}
                  job={scheduler.jobs[JOB_ORDER[4]]}
                  onTrigger={handleTrigger}
                />
              </motion.div>
            )}
          </div>
        )}

        {/* ── Operation Log ──────────────────────────── */}
        <div className="bg-surface rounded-xl border border-border p-4">
          <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider mb-3">
            Operation Log
          </h3>
          {scheduler ? (
            <OperationLog scheduler={scheduler} />
          ) : (
            <p className="text-xs text-text-muted text-center py-8">Loading...</p>
          )}
        </div>
      </div>
    </div>
  );
}
