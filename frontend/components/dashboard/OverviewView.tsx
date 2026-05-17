"use client";

import { useEffect, useState } from "react";
import { AnimatePresence } from "framer-motion";
import {
  getMemoryStats,
  getSchedulerStatus,
  MemoryStats,
  SchedulerStatus,
} from "@/lib/api";
import NodeDetailModal from "@/components/memory/NodeDetailModal";

/* ═══════════════════════════════════════════════════════════════════════════ */

const NODE_COLORS: Record<string, string> = {
  ANCHOR: "var(--anchor)",
  DOMAIN: "var(--domain)",
  CLUSTER: "var(--cluster)",
  INSTANCE: "var(--instance)",
};

const NODE_BG: Record<string, string> = {
  ANCHOR: "rgba(247,201,106,0.12)",
  DOMAIN: "rgba(106,247,201,0.12)",
  CLUSTER: "rgba(106,175,247,0.12)",
  INSTANCE: "rgba(160,106,247,0.12)",
};

function decayLabel(score: number): { text: string; color: string } {
  if (score >= 0.7) return { text: "Healthy", color: "var(--decay-healthy)" };
  if (score >= 0.3) return { text: "Moderate", color: "var(--decay-warning)" };
  return { text: "Critical", color: "var(--decay-critical)" };
}

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const mins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h ago`;
  return `${Math.floor(mins / 1440)}d ago`;
}

const OP_COLORS: Record<string, string> = {
  PROMOTE: "var(--anchor)",
  DEMOTE: "var(--decay-warning)",
  MERGE: "var(--domain)",
  SPLIT: "var(--instance)",
  DECAY: "var(--decay-critical)",
  ARCHIVE: "var(--decay-critical)",
  ADD: "var(--decay-healthy)",
};

/* ═══════════════════════════════════════════════════════════════════════════ */

export default function OverviewView() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  useEffect(() => {
    getMemoryStats().then(setStats).catch(() => {});
    getSchedulerStatus().then(setScheduler).catch(() => {});
  }, []);

  // Compute derived values
  const totalOps = scheduler
    ? Object.values(scheduler.jobs).reduce((s, j) => s + j.operations, 0)
    : 0;

  const avgDecay = stats
    ? (() => {
        const vals = Object.values(stats.avg_decay_by_tier).filter((v) => v !== null) as number[];
        return vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
      })()
    : 0;

  const decayInfo = decayLabel(avgDecay);

  // Build recent ops from scheduler details
  const recentOps: { type: string; job: string; timestamp: string }[] = [];
  if (scheduler) {
    const JOB_NAMES: Record<string, string> = {
      decay_sweep: "Decay",
      promotion_sweep: "Promotion",
      merge_sweep: "Merge",
      split_sweep: "Split",
      lateral_link_refresh: "Lateral",
    };
    for (const [key, job] of Object.entries(scheduler.jobs)) {
      if (job.last_run && job.operations > 0) {
        const details = job.details as Record<string, unknown>;
        // Extract ops from details
        for (const [detailKey, count] of Object.entries(details)) {
          if (typeof count === "number" && count > 0 && detailKey !== "total_scanned" && detailKey !== "nodes_scanned") {
            recentOps.push({
              type: detailKey.toUpperCase(),
              job: JOB_NAMES[key] || key,
              timestamp: job.last_run,
            });
          }
        }
      }
    }
  }
  recentOps.sort((a, b) => (b.timestamp > a.timestamp ? 1 : -1));

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6 max-w-5xl">
        <h2 className="text-lg font-semibold text-text-primary mb-1">Overview</h2>
        <p className="text-sm text-text-muted mb-6">Your memory network at a glance</p>

        {/* ── Stat Cards ─────────────────────────────────── */}
        <div className="grid grid-cols-4 gap-3 mb-6">
          {/* Total Nodes */}
          <div className="bg-surface-elevated rounded-xl border border-border p-4 relative overflow-hidden">
            <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-primary rounded-l-xl" />
            <p className="text-[10px] text-text-muted uppercase tracking-wider font-medium">Total Nodes</p>
            <p className="text-2xl font-bold text-text-primary mt-2">
              {stats?.total_active ?? "—"}
            </p>
            {stats && (
              <p className="text-[10px] text-text-muted mt-1.5 leading-relaxed">
                {stats.nodes_by_type.ANCHOR || 0} anchors · {stats.nodes_by_type.DOMAIN || 0} domains
                <br />
                {stats.nodes_by_type.CLUSTER || 0} clusters · {stats.nodes_by_type.INSTANCE || 0} instances
              </p>
            )}
          </div>

          {/* Average Decay */}
          <div className="bg-surface-elevated rounded-xl border border-border p-4 relative overflow-hidden">
            <div
              className="absolute left-0 top-0 bottom-0 w-[3px] rounded-l-xl"
              style={{ backgroundColor: decayInfo.color }}
            />
            <p className="text-[10px] text-text-muted uppercase tracking-wider font-medium">Avg Decay</p>
            <p className="text-2xl font-bold text-text-primary mt-2">
              {stats ? avgDecay.toFixed(3) : "—"}
            </p>
            <p className="text-[10px] mt-1.5" style={{ color: decayInfo.color }}>
              {decayInfo.text}
            </p>
          </div>

          {/* Memory Operations */}
          <div className="bg-surface-elevated rounded-xl border border-border p-4 relative overflow-hidden">
            <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-domain rounded-l-xl" />
            <p className="text-[10px] text-text-muted uppercase tracking-wider font-medium">Operations</p>
            <p className="text-2xl font-bold text-text-primary mt-2">{totalOps}</p>
            <p className="text-[10px] text-text-muted mt-1.5">Across all scheduler jobs</p>
          </div>

          {/* Strongest Memory */}
          <div className="bg-surface-elevated rounded-xl border border-border p-4 relative overflow-hidden">
            <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-anchor rounded-l-xl" />
            <p className="text-[10px] text-text-muted uppercase tracking-wider font-medium">Strongest</p>
            <p className="text-sm font-semibold text-text-primary mt-2 leading-snug line-clamp-2">
              {stats?.top_by_composite_weight[0]?.name || "—"}
            </p>
            <p className="text-[10px] text-text-muted mt-1.5">
              wt: {stats?.top_by_composite_weight[0]?.composite_weight?.toFixed(3) || "—"}
            </p>
          </div>
        </div>

        {/* ── Two Columns ────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-4 mb-6">
          {/* Memory by Type */}
          <div className="bg-surface rounded-xl border border-border p-4">
            <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider mb-4">
              Memory by Type
            </h3>
            {stats && (
              <div className="space-y-3">
                {(["ANCHOR", "DOMAIN", "CLUSTER", "INSTANCE"] as const).map((type) => {
                  const count = stats.nodes_by_type[type] || 0;
                  const total = stats.total_active || 1;
                  const pct = (count / total) * 100;
                  return (
                    <div key={type} className="flex items-center gap-3">
                      <span
                        className="w-2.5 h-2.5 rounded-full shrink-0"
                        style={{ backgroundColor: NODE_COLORS[type] }}
                      />
                      <span className="text-xs text-text-secondary w-16">{type}</span>
                      <div className="flex-1 h-2 bg-surface-elevated rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all duration-500"
                          style={{
                            width: `${Math.max(pct, 2)}%`,
                            backgroundColor: NODE_COLORS[type],
                            opacity: 0.7,
                          }}
                        />
                      </div>
                      <span className="text-xs text-text-primary font-mono w-8 text-right">
                        {count}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
            {!stats && (
              <p className="text-xs text-text-muted">Loading...</p>
            )}
          </div>

          {/* Top Nodes by Weight */}
          <div className="bg-surface rounded-xl border border-border p-4">
            <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider mb-4">
              Top Nodes by Weight
            </h3>
            {stats && stats.top_by_composite_weight.length > 0 ? (
              <div className="space-y-1.5">
                {stats.top_by_composite_weight.map((node, i) => (
                  <button
                    key={node.id}
                    onClick={() => setSelectedNodeId(node.id)}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg
                               hover:bg-surface-elevated transition-all text-left group"
                  >
                    <span className="text-xs text-text-muted w-4 font-mono">{i + 1}</span>
                    <span className="text-xs text-text-primary flex-1 truncate group-hover:text-white transition-colors">
                      {node.name}
                    </span>
                    <span
                      className="px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase"
                      style={{
                        backgroundColor: NODE_BG[node.node_type] || "#1a1a24",
                        color: NODE_COLORS[node.node_type] || "#888",
                      }}
                    >
                      {node.node_type}
                    </span>
                    <span className="text-[11px] text-text-muted font-mono w-10 text-right">
                      {node.composite_weight.toFixed(2)}
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-xs text-text-muted">No nodes yet</p>
            )}
          </div>
        </div>

        {/* ── Recent Operations ───────────────────────────── */}
        <div className="bg-surface rounded-xl border border-border p-4">
          <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider mb-4">
            Recent Operations
          </h3>
          {recentOps.length > 0 ? (
            <div className="relative pl-4 border-l border-border space-y-3 max-h-60 overflow-y-auto">
              {recentOps.slice(0, 10).map((op, i) => (
                <div key={i} className="relative">
                  <span
                    className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full border-2 border-surface"
                    style={{ backgroundColor: OP_COLORS[op.type] || "var(--text-muted)" }}
                  />
                  <div className="flex items-center gap-2 text-xs">
                    <span
                      className="px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase"
                      style={{
                        backgroundColor: (OP_COLORS[op.type] || "#555") + "20",
                        color: OP_COLORS[op.type] || "#888",
                      }}
                    >
                      {op.type}
                    </span>
                    <span className="text-text-secondary">{op.job}</span>
                    <span className="text-text-muted ml-auto">{relativeTime(op.timestamp)}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-text-muted">No operations recorded yet. Scheduler will populate this automatically.</p>
          )}
        </div>
      </div>

      {/* Node Detail Modal */}
      <AnimatePresence>
        {selectedNodeId && (
          <NodeDetailModal
            nodeId={selectedNodeId}
            onClose={() => setSelectedNodeId(null)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
