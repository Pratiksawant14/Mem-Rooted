"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { getNodeDetail, archiveNode, NodeDetail } from "@/lib/api";

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

const OP_COLORS: Record<string, string> = {
  ADD: "#6af77a",
  UPDATE: "#6aaff7",
  NOOP: "#55556a",
  ARCHIVE: "#f76a6a",
  ARCHIVE_MANUAL: "#f76a6a",
  PROMOTE: "#f7c96a",
  DEMOTE: "#f7d06a",
  MERGE: "#6af7c9",
  SPLIT: "#a06af7",
  LATERAL_LINK: "#7c6af7",
};

function decayColor(score: number): string {
  if (score >= 0.6) return "var(--decay-healthy)";
  if (score >= 0.2) return "var(--decay-warning)";
  return "var(--decay-critical)";
}

interface Props {
  nodeId: string;
  onClose: () => void;
}

export default function NodeDetailModal({ nodeId, onClose }: Props) {
  const [node, setNode] = useState<NodeDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [archiving, setArchiving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getNodeDetail(nodeId)
      .then(setNode)
      .catch((e) => setError(e?.response?.data?.detail || "Failed to load node"))
      .finally(() => setLoading(false));
  }, [nodeId]);

  const handleArchive = async () => {
    if (!node) return;
    setArchiving(true);
    try {
      await archiveNode(node.id);
      onClose();
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Archive failed");
    }
    setArchiving(false);
  };

  const formatTimestamp = (ts: string) => {
    try {
      const d = new Date(ts);
      return d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return ts;
    }
  };

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <motion.div
        className="relative w-full max-w-lg max-h-[85vh] bg-surface rounded-2xl border border-border
                   shadow-2xl overflow-hidden flex flex-col"
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.95, opacity: 0 }}
        transition={{ duration: 0.2, ease: "easeOut" }}
      >
        {/* Loading / Error */}
        {loading && (
          <div className="p-8 text-center text-text-muted text-sm">Loading node...</div>
        )}
        {error && !loading && (
          <div className="p-8 text-center text-decay-critical text-sm">{error}</div>
        )}

        {node && !loading && (
          <>
            {/* ── Header ─────────────────────────────── */}
            <div className="px-5 pt-5 pb-3 border-b border-border">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span
                      className="px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wider"
                      style={{
                        backgroundColor: NODE_BG[node.node_type] || "#1a1a24",
                        color: NODE_COLORS[node.node_type] || "#888",
                      }}
                    >
                      {node.node_type}
                    </span>
                    <span className="text-[10px] text-text-muted">Tier {node.tier_level}</span>
                  </div>
                  <h3 className="text-base font-semibold text-text-primary leading-snug break-words">
                    {node.name}
                  </h3>
                </div>
                <button
                  onClick={onClose}
                  className="w-7 h-7 flex items-center justify-center rounded-lg shrink-0
                             text-text-muted hover:text-text-primary hover:bg-surface-elevated
                             transition-all"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 6L6 18M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>

            {/* ── Scrollable content ─────────────────── */}
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
              {/* Weight scores */}
              <div className="grid grid-cols-4 gap-2">
                {[
                  { label: "Physical", value: node.physical_weight },
                  { label: "Recall", value: node.recall_weight },
                  { label: "Semantic", value: node.semantic_weight },
                  { label: "Composite", value: node.composite_weight },
                ].map((w) => (
                  <div
                    key={w.label}
                    className="bg-surface-elevated rounded-lg border border-border p-2 text-center"
                  >
                    <p className="text-[9px] text-text-muted uppercase tracking-wider">{w.label}</p>
                    <p className="text-sm font-semibold text-text-primary mt-0.5">
                      {(w.value || 0).toFixed(2)}
                    </p>
                  </div>
                ))}
              </div>

              {/* Decay */}
              <div className="flex items-center gap-3 bg-surface-elevated rounded-lg border border-border p-3">
                <span className="text-xs text-text-muted">Decay Score</span>
                <div className="flex-1" />
                <span
                  className="w-2.5 h-2.5 rounded-full"
                  style={{ backgroundColor: decayColor(node.decay_score || 1) }}
                />
                <span className="text-sm font-mono font-semibold text-text-primary">
                  {(node.decay_score || 1).toFixed(4)}
                </span>
              </div>

              {/* Content */}
              <div>
                <p className="text-[10px] text-text-muted uppercase tracking-wider mb-1.5">Content</p>
                <p className="text-sm text-text-secondary leading-relaxed bg-surface-elevated rounded-lg border border-border p-3 whitespace-pre-wrap">
                  {node.content || "—"}
                </p>
              </div>

              {/* Parent */}
              {node.parent && (
                <div>
                  <p className="text-[10px] text-text-muted uppercase tracking-wider mb-1.5">Parent</p>
                  <div className="flex items-center gap-2 text-xs text-text-secondary bg-surface-elevated rounded-lg border border-border p-2.5">
                    <span
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ backgroundColor: NODE_COLORS[node.parent.node_type] || "#555" }}
                    />
                    {node.parent.name}
                  </div>
                </div>
              )}

              {/* Children */}
              {node.children && node.children.length > 0 && (
                <div>
                  <p className="text-[10px] text-text-muted uppercase tracking-wider mb-1.5">
                    Children ({node.children_count})
                  </p>
                  <div className="space-y-1">
                    {node.children.map((child: any) => (
                      <div
                        key={child.id}
                        className="flex items-center gap-2 text-xs text-text-secondary bg-surface-elevated rounded-lg border border-border p-2.5"
                      >
                        <span
                          className="w-2 h-2 rounded-full shrink-0"
                          style={{ backgroundColor: NODE_COLORS[child.node_type] || "#555" }}
                        />
                        <span className="flex-1 truncate">{child.name}</span>
                        <span className="text-text-muted font-mono text-[10px]">
                          wt: {(child.composite_weight || 0).toFixed(2)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Lateral Links */}
              {node.lateral_links && node.lateral_links.length > 0 && (
                <div>
                  <p className="text-[10px] text-text-muted uppercase tracking-wider mb-1.5">
                    Lateral Links ({node.lateral_links.length})
                  </p>
                  <div className="space-y-1">
                    {node.lateral_links.map((link, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-2 text-xs text-text-secondary bg-surface-elevated rounded-lg border border-border p-2.5"
                      >
                        <span className="w-2 h-2 rounded-full bg-primary shrink-0" />
                        <span className="font-mono truncate flex-1">
                          {(link.target_id || "").slice(0, 12)}...
                        </span>
                        <span className="text-text-muted font-mono text-[10px]">
                          sim: {(link.similarity || 0).toFixed(3)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Operation Log Timeline */}
              {node.operation_log && node.operation_log.length > 0 && (
                <div>
                  <p className="text-[10px] text-text-muted uppercase tracking-wider mb-2">
                    Operation Log ({node.operation_log.length})
                  </p>
                  <div className="relative pl-4 border-l border-border space-y-3">
                    {node.operation_log
                      .slice()
                      .reverse()
                      .map((entry, i) => (
                        <div key={i} className="relative">
                          {/* Timeline dot */}
                          <span
                            className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full border-2 border-surface"
                            style={{ backgroundColor: OP_COLORS[entry.op] || "#555" }}
                          />
                          <div className="text-xs">
                            <span
                              className="font-semibold"
                              style={{ color: OP_COLORS[entry.op] || "#888" }}
                            >
                              {entry.op}
                            </span>
                            <span className="text-text-muted ml-2 text-[10px]">
                              {formatTimestamp(entry.timestamp)}
                            </span>
                          </div>
                          {entry.details && Object.keys(entry.details).length > 0 && (
                            <p className="text-[11px] text-text-muted mt-0.5 leading-relaxed">
                              {JSON.stringify(entry.details).slice(0, 120)}
                              {JSON.stringify(entry.details).length > 120 ? "..." : ""}
                            </p>
                          )}
                        </div>
                      ))}
                  </div>
                </div>
              )}
            </div>

            {/* ── Footer ─────────────────────────────── */}
            <div className="px-5 py-3 border-t border-border flex items-center justify-between">
              <button
                onClick={handleArchive}
                disabled={archiving || node.priority_flag === "IMMUTABLE"}
                className="px-3 py-1.5 rounded-lg text-xs font-medium
                           bg-decay-critical/10 text-decay-critical border border-decay-critical/20
                           hover:bg-decay-critical/20 disabled:opacity-30 disabled:cursor-not-allowed
                           transition-all"
              >
                {archiving ? "Archiving..." : node.priority_flag === "IMMUTABLE" ? "IMMUTABLE" : "Archive Node"}
              </button>
              <button
                onClick={onClose}
                className="px-4 py-1.5 rounded-lg text-xs font-medium
                           bg-surface-elevated text-text-secondary border border-border
                           hover:text-text-primary transition-all"
              >
                Close
              </button>
            </div>
          </>
        )}
      </motion.div>
    </motion.div>
  );
}
