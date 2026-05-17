"use client";

interface Props {
  anchor_count: number;
  domain_count: number;
  retrieved_count: number;
  channels_used: string[];
}

const CHANNEL_COLORS: Record<string, string> = {
  semantic: "#7c6af7",
  bm25: "#6aaff7",
  graph: "#6af7c9",
  temporal: "#f7c96a",
};

const CHANNEL_LABELS: Record<string, string> = {
  semantic: "Semantic",
  bm25: "BM25",
  graph: "Graph",
  temporal: "Temporal",
};

export default function MemoryBadge({
  anchor_count,
  domain_count,
  retrieved_count,
  channels_used,
}: Props) {
  return (
    <div className="flex items-center gap-2 flex-wrap text-[11px] text-text-muted px-1">
      {/* Node counts */}
      <span className="flex items-center gap-1">
        <span className="w-1.5 h-1.5 rounded-full bg-anchor inline-block" />
        {anchor_count} anchor{anchor_count !== 1 ? "s" : ""}
      </span>
      <span className="text-text-muted">·</span>
      <span className="flex items-center gap-1">
        <span className="w-1.5 h-1.5 rounded-full bg-domain inline-block" />
        {domain_count} domain{domain_count !== 1 ? "s" : ""}
      </span>
      <span className="text-text-muted">·</span>
      <span className="flex items-center gap-1">
        <span className="w-1.5 h-1.5 rounded-full bg-cluster inline-block" />
        {retrieved_count} recalled
      </span>

      {/* Channel pills */}
      {channels_used.length > 0 && (
        <>
          <span className="text-text-muted">·</span>
          <span className="text-text-muted">via</span>
          {channels_used.map((ch) => (
            <span
              key={ch}
              className="flex items-center gap-1 px-1.5 py-0.5 rounded-md"
              style={{ backgroundColor: (CHANNEL_COLORS[ch] || "#555") + "18" }}
            >
              <span
                className="w-1.5 h-1.5 rounded-full inline-block"
                style={{ backgroundColor: CHANNEL_COLORS[ch] || "#555" }}
              />
              <span style={{ color: CHANNEL_COLORS[ch] || "#888" }}>
                {CHANNEL_LABELS[ch] || ch}
              </span>
            </span>
          ))}
        </>
      )}
    </div>
  );
}
