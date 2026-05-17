"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { searchMemory, SearchResult } from "@/lib/api";
import NodeDetailModal from "@/components/memory/NodeDetailModal";

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
   Shimmer Skeleton
   ═══════════════════════════════════════════════════════════════════════════ */

function SkeletonCard() {
  return (
    <div className="bg-surface rounded-xl border border-border p-4 space-y-3 overflow-hidden relative">
      <div className="shimmer-line h-4 w-2/3 rounded bg-surface-elevated" />
      <div className="shimmer-line h-3 w-full rounded bg-surface-elevated" />
      <div className="shimmer-line h-3 w-4/5 rounded bg-surface-elevated" />
      <div className="flex gap-4 mt-2">
        <div className="shimmer-line h-3 w-16 rounded bg-surface-elevated" />
        <div className="shimmer-line h-3 w-16 rounded bg-surface-elevated" />
      </div>
      <style jsx>{`
        .shimmer-line {
          background: linear-gradient(
            90deg,
            var(--surface-elevated) 25%,
            rgba(124, 106, 247, 0.06) 50%,
            var(--surface-elevated) 75%
          );
          background-size: 200% 100%;
          animation: shimmer 1.5s ease-in-out infinite;
        }
        @keyframes shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Empty States
   ═══════════════════════════════════════════════════════════════════════════ */

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <svg
        width="72"
        height="72"
        viewBox="0 0 72 72"
        fill="none"
        className="mb-5 opacity-30"
      >
        {/* Simple geometric brain shape */}
        <circle cx="36" cy="36" r="30" stroke="var(--primary)" strokeWidth="1.5" strokeDasharray="4 3" />
        <circle cx="28" cy="28" r="8" stroke="var(--anchor)" strokeWidth="1.5" />
        <circle cx="44" cy="28" r="6" stroke="var(--domain)" strokeWidth="1.5" />
        <circle cx="32" cy="44" r="7" stroke="var(--cluster)" strokeWidth="1.5" />
        <circle cx="46" cy="42" r="5" stroke="var(--instance)" strokeWidth="1.5" />
        <line x1="34" y1="30" x2="40" y2="28" stroke="var(--text-muted)" strokeWidth="1" />
        <line x1="30" y1="35" x2="32" y2="38" stroke="var(--text-muted)" strokeWidth="1" />
        <line x1="44" y1="34" x2="44" y2="38" stroke="var(--text-muted)" strokeWidth="1" />
        <line x1="38" y1="44" x2="42" y2="42" stroke="var(--text-muted)" strokeWidth="1" />
      </svg>
      <h3 className="text-base font-semibold text-text-primary mb-1">Search your memory</h3>
      <p className="text-sm text-text-muted max-w-xs">
        Find any fact, goal, or context from your conversations
      </p>
    </div>
  );
}

function NoResults({ query }: { query: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" className="mb-4 opacity-20">
        <circle cx="11" cy="11" r="8" stroke="var(--text-muted)" strokeWidth="1.5" />
        <path d="M21 21l-4.35-4.35" stroke="var(--text-muted)" strokeWidth="1.5" />
        <path d="M8 11h6" stroke="var(--text-muted)" strokeWidth="1.5" />
      </svg>
      <p className="text-sm text-text-secondary mb-1">
        No memories found for &ldquo;{query}&rdquo;
      </p>
      <p className="text-xs text-text-muted">Start a conversation to build your memory network</p>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SearchView
   ═══════════════════════════════════════════════════════════════════════════ */

export default function SearchView() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const doSearch = useCallback(async (q: string) => {
    if (q.length < 2) {
      setResults([]);
      setHasSearched(false);
      return;
    }
    setLoading(true);
    setHasSearched(true);
    try {
      const res = await searchMemory(q);
      setResults(res);
    } catch {
      setResults([]);
    }
    setLoading(false);
  }, []);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = e.target.value;
      setQuery(val);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => doSearch(val), 400);
    },
    [doSearch]
  );

  const handleClear = useCallback(() => {
    setQuery("");
    setResults([]);
    setHasSearched(false);
  }, []);

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6 max-w-3xl mx-auto">
        <h2 className="text-lg font-semibold text-text-primary mb-1">Search</h2>
        <p className="text-sm text-text-muted mb-5">Query your entire memory network</p>

        {/* ── Search Input ───────────────────────────────── */}
        <div className="relative mb-6">
          {/* Search icon */}
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--text-muted)"
            strokeWidth="2"
            className="absolute left-4 top-1/2 -translate-y-1/2 pointer-events-none"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="M21 21l-4.35-4.35" />
          </svg>

          <input
            type="text"
            value={query}
            onChange={handleChange}
            placeholder="Search your memory network..."
            className="w-full h-12 pl-12 pr-12 bg-surface border border-border rounded-xl
                       text-sm text-text-primary placeholder:text-text-muted
                       focus:border-primary focus:ring-1 focus:ring-primary-glow
                       transition-all"
          />

          {/* Clear button */}
          {query && (
            <button
              onClick={handleClear}
              className="absolute right-4 top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center
                         rounded-full text-text-muted hover:text-text-primary hover:bg-surface-elevated
                         transition-all"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>

        {/* ── Results ────────────────────────────────────── */}
        {loading && (
          <div className="space-y-3">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
        )}

        {!loading && !hasSearched && <EmptyState />}

        {!loading && hasSearched && results.length === 0 && <NoResults query={query} />}

        {!loading && results.length > 0 && (
          <div className="space-y-3">
            {results.map((result, i) => (
              <motion.button
                key={result.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, delay: i * 0.05 }}
                onClick={() => setSelectedNodeId(result.id)}
                className="w-full text-left bg-surface rounded-xl border border-border p-4
                           hover:border-primary/30 hover:-translate-y-[1px]
                           transition-all group relative overflow-hidden"
              >
                {/* Colored left accent */}
                <div
                  className="absolute left-0 top-0 bottom-0 w-[3px] rounded-l-xl"
                  style={{ backgroundColor: NODE_COLORS[result.node_type] || "#555" }}
                />

                {/* Top row */}
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-sm font-semibold text-text-primary group-hover:text-white transition-colors truncate flex-1">
                    {result.name}
                  </span>
                  <span
                    className="px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase shrink-0"
                    style={{
                      backgroundColor: NODE_BG[result.node_type] || "#1a1a24",
                      color: NODE_COLORS[result.node_type] || "#888",
                    }}
                  >
                    {result.node_type}
                  </span>
                </div>

                {/* Content */}
                <p className="text-xs text-text-secondary leading-relaxed mb-3 whitespace-pre-wrap">
                  {result.content_preview}
                </p>

                {/* Bottom row */}
                <div className="flex items-center gap-4 text-[10px] text-text-muted">
                  <span>wt: {result.composite_weight.toFixed(3)}</span>
                  <span className="flex items-center gap-1">
                    <span
                      className="w-1.5 h-1.5 rounded-full inline-block"
                      style={{ backgroundColor: decayColor(result.decay_score) }}
                    />
                    decay: {result.decay_score.toFixed(3)}
                  </span>
                </div>
              </motion.button>
            ))}
          </div>
        )}
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
