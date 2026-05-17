"use client";

import { useCallback, useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  getMemoryTree,
  getMemoryStats,
  getSchedulerStatus,
  triggerSchedulerJob,
  MemoryTreeNode,
  MemoryStats,
  SchedulerStatus,
} from "@/lib/api";
import NodeDetailModal from "./NodeDetailModal";

/* ═══════════════════════════════════════════════════════════════════════════
   Types
   ═══════════════════════════════════════════════════════════════════════════ */

interface Props {
  transparency: {
    anchor_count: number;
    domain_count: number;
    retrieved_count: number;
    channels_used: string[];
    nodes_used: string[];
  } | null;
  onClose: () => void;
}

type Tab = "active" | "tree" | "stats";

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

function decayColor(score: number): string {
  if (score >= 0.6) return "var(--decay-healthy)";
  if (score >= 0.2) return "var(--decay-warning)";
  return "var(--decay-critical)";
}

/* ═══════════════════════════════════════════════════════════════════════════
   Active Tab — Nodes used in last response
   ═══════════════════════════════════════════════════════════════════════════ */

function ActiveTab({ nodesUsed }: { nodesUsed: string[] }) {
  if (!nodesUsed || nodesUsed.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-text-muted text-sm">
        <p>No memories accessed yet.</p>
        <p className="text-xs mt-1">Send a message to see which nodes are used.</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-text-muted mb-3">
        {nodesUsed.length} node{nodesUsed.length !== 1 ? "s" : ""} influenced the last response
      </p>
      {nodesUsed.map((nid) => (
        <div
          key={nid}
          className="flex items-center gap-2 px-3 py-2 rounded-lg bg-surface border border-border text-xs"
        >
          <span className="w-2 h-2 rounded-full bg-primary shrink-0" />
          <span className="text-text-secondary font-mono truncate">{nid.slice(0, 12)}...</span>
        </div>
      ))}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Tree Tab — Collapsible node hierarchy
   ═══════════════════════════════════════════════════════════════════════════ */

function TreeNode({
  node,
  depth,
  onSelectNode,
}: {
  node: MemoryTreeNode;
  depth: number;
  onSelectNode: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(depth < 2);
  const hasChildren = node.children && node.children.length > 0;

  return (
    <div>
      <div
        className="flex items-center gap-2 py-1.5 px-2 rounded-lg cursor-pointer
                   hover:bg-surface-elevated transition-colors group"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={() => onSelectNode(node.id)}
      >
        {/* Expand toggle */}
        {hasChildren ? (
          <button
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
            className="w-4 h-4 flex items-center justify-center text-text-muted
                       hover:text-text-primary transition-colors shrink-0"
          >
            <svg
              width="10"
              height="10"
              viewBox="0 0 10 10"
              fill="currentColor"
              className={`transition-transform duration-200 ${expanded ? "rotate-90" : ""}`}
            >
              <path d="M3 1l4 4-4 4z" />
            </svg>
          </button>
        ) : (
          <span className="w-4" />
        )}

        {/* Node type dot */}
        <span
          className="w-2.5 h-2.5 rounded-full shrink-0"
          style={{ backgroundColor: NODE_COLORS[node.node_type] || "#555" }}
        />

        {/* Name */}
        <span className="text-xs text-text-primary truncate flex-1 group-hover:text-white transition-colors">
          {node.name.length > 40 ? node.name.slice(0, 40) + "..." : node.name}
        </span>

        {/* Weight badge */}
        <span className="text-[10px] text-text-muted font-mono shrink-0">
          {(node.composite_weight || 0).toFixed(2)}
        </span>

        {/* Decay dot */}
        <span
          className="w-1.5 h-1.5 rounded-full shrink-0"
          style={{ backgroundColor: decayColor(node.decay_score || 1) }}
        />
      </div>

      {/* Children */}
      <AnimatePresence>
        {expanded && hasChildren && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            {node.children.map((child) => (
              <TreeNode
                key={child.id}
                node={child}
                depth={depth + 1}
                onSelectNode={onSelectNode}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function TreeTab({ onSelectNode }: { onSelectNode: (id: string) => void }) {
  const [tree, setTree] = useState<MemoryTreeNode[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getMemoryTree()
      .then(setTree)
      .catch(() => setTree([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="text-sm text-text-muted py-8 text-center">Loading memory tree...</div>;
  }

  if (tree.length === 0) {
    return (
      <div className="text-sm text-text-muted py-8 text-center">
        No memories stored yet. Start chatting to build your memory tree.
      </div>
    );
  }

  return (
    <div className="space-y-0.5">
      {tree.map((node) => (
        <TreeNode key={node.id} node={node} depth={0} onSelectNode={onSelectNode} />
      ))}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Stats Tab — Metrics + Scheduler
   ═══════════════════════════════════════════════════════════════════════════ */

function StatsTab() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null);
  const [triggering, setTriggering] = useState<string | null>(null);

  useEffect(() => {
    getMemoryStats().then(setStats).catch(() => {});
    getSchedulerStatus().then(setScheduler).catch(() => {});
  }, []);

  const handleTrigger = async (jobName: string) => {
    setTriggering(jobName);
    try {
      await triggerSchedulerJob(jobName);
      const fresh = await getSchedulerStatus();
      setScheduler(fresh);
    } catch {
      // ignore
    }
    setTriggering(null);
  };

  const JOB_LABELS: Record<string, string> = {
    decay_sweep: "Decay",
    promotion_sweep: "Promotion",
    merge_sweep: "Merge",
    split_sweep: "Split",
    lateral_link_refresh: "Lateral",
  };

  const TRIGGER_NAMES: Record<string, string> = {
    decay_sweep: "decay",
    promotion_sweep: "promotion",
    merge_sweep: "merge",
    split_sweep: "split",
    lateral_link_refresh: "lateral",
  };

  return (
    <div className="space-y-4">
      {/* Metric cards */}
      {stats && (
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-surface rounded-xl border border-border p-3">
            <p className="text-[10px] text-text-muted uppercase tracking-wider">Total Nodes</p>
            <p className="text-xl font-semibold text-text-primary mt-1">{stats.total_active}</p>
            <p className="text-[10px] text-text-muted">{stats.total_archived} archived</p>
          </div>
          <div className="bg-surface rounded-xl border border-border p-3">
            <p className="text-[10px] text-text-muted uppercase tracking-wider">Avg Decay</p>
            <p className="text-xl font-semibold text-text-primary mt-1">
              {stats.avg_decay_by_tier.INSTANCE != null
                ? stats.avg_decay_by_tier.INSTANCE.toFixed(2)
                : "—"}
            </p>
            <p className="text-[10px] text-text-muted">Instance tier</p>
          </div>
          <div className="bg-surface rounded-xl border border-border p-3">
            <p className="text-[10px] text-text-muted uppercase tracking-wider">Promotions</p>
            <p className="text-xl font-semibold text-text-primary mt-1">{stats.promotions_total}</p>
          </div>
          <div className="bg-surface rounded-xl border border-border p-3">
            <p className="text-[10px] text-text-muted uppercase tracking-wider">Top Node</p>
            <p className="text-xs font-medium text-text-primary mt-1 truncate">
              {stats.top_by_composite_weight[0]?.name || "—"}
            </p>
            <p className="text-[10px] text-text-muted">
              wt: {stats.top_by_composite_weight[0]?.composite_weight?.toFixed(2) || "—"}
            </p>
          </div>
        </div>
      )}

      {/* Node type breakdown */}
      {stats && (
        <div className="bg-surface rounded-xl border border-border p-3">
          <p className="text-[10px] text-text-muted uppercase tracking-wider mb-2">By Type</p>
          <div className="space-y-1.5">
            {Object.entries(stats.nodes_by_type).map(([type, count]) => (
              <div key={type} className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: NODE_COLORS[type] || "#555" }}
                />
                <span className="text-xs text-text-secondary flex-1">{type}</span>
                <span className="text-xs text-text-primary font-mono">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Scheduler jobs */}
      {scheduler && (
        <div className="bg-surface rounded-xl border border-border p-3">
          <p className="text-[10px] text-text-muted uppercase tracking-wider mb-2">
            Scheduler
            <span
              className="inline-block w-1.5 h-1.5 rounded-full ml-2"
              style={{
                backgroundColor: scheduler.scheduler_running
                  ? "var(--decay-healthy)"
                  : "var(--decay-critical)",
              }}
            />
          </p>
          <div className="space-y-2">
            {Object.entries(scheduler.jobs).map(([key, job]) => (
              <div key={key} className="flex items-center gap-2 text-xs">
                <span className="text-text-secondary flex-1">
                  {JOB_LABELS[key] || key}
                </span>
                <span className="text-text-muted font-mono text-[10px]">
                  {job.operations} ops
                </span>
                <button
                  onClick={() => handleTrigger(TRIGGER_NAMES[key] || key)}
                  disabled={triggering === (TRIGGER_NAMES[key] || key)}
                  className="px-2 py-0.5 rounded text-[10px] bg-surface-elevated border border-border
                             text-text-secondary hover:text-primary hover:border-primary
                             disabled:opacity-30 transition-all"
                >
                  {triggering === (TRIGGER_NAMES[key] || key) ? "..." : "Run"}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   TransparencyPanel — Main Component
   ═══════════════════════════════════════════════════════════════════════════ */

export default function TransparencyPanel({ transparency, onClose }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("active");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const tabs: { key: Tab; label: string }[] = [
    { key: "active", label: "Active" },
    { key: "tree", label: "Tree" },
    { key: "stats", label: "Stats" },
  ];

  return (
    <div className="flex flex-col h-full bg-bg">
      {/* ── Header ────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h2 className="text-sm font-semibold text-text-primary">Memory</h2>
        <button
          onClick={onClose}
          className="w-7 h-7 flex items-center justify-center rounded-lg
                     text-text-muted hover:text-text-primary hover:bg-surface-elevated
                     transition-all"
          title="Close panel"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* ── Tabs ──────────────────────────────────────── */}
      <div className="flex border-b border-border px-4">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-3 py-2.5 text-xs font-medium transition-all relative
              ${
                activeTab === tab.key
                  ? "text-primary"
                  : "text-text-muted hover:text-text-secondary"
              }`}
          >
            {tab.label}
            {activeTab === tab.key && (
              <motion.div
                layoutId="tab-indicator"
                className="absolute bottom-0 left-0 right-0 h-[2px] bg-primary rounded-full"
              />
            )}
          </button>
        ))}
      </div>

      {/* ── Content ───────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, x: 10 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -10 }}
            transition={{ duration: 0.15 }}
          >
            {activeTab === "active" && (
              <ActiveTab nodesUsed={transparency?.nodes_used || []} />
            )}
            {activeTab === "tree" && (
              <TreeTab onSelectNode={(id) => setSelectedNodeId(id)} />
            )}
            {activeTab === "stats" && <StatsTab />}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* ── Node Detail Modal ─────────────────────────── */}
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
