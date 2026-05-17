"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import dynamic from "next/dynamic";
import { getMemoryTree, MemoryTreeNode } from "@/lib/api";
import NodeDetailModal from "@/components/memory/NodeDetailModal";

// Dynamic import to avoid SSR issues with canvas
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

/* ═══════════════════════════════════════════════════════════════════════════ */

const NODE_COLORS: Record<string, string> = {
  ANCHOR: "#f7c96a",
  DOMAIN: "#6af7c9",
  CLUSTER: "#6aaff7",
  INSTANCE: "#a06af7",
};

const TYPE_ORDER = ["ANCHOR", "DOMAIN", "CLUSTER", "INSTANCE"];

interface GraphNode {
  id: string;
  name: string;
  node_type: string;
  content: string;
  composite_weight: number;
  decay_score: number;
  is_archived: boolean;
  tier_level: number;
  val: number; // size
  color: string;
}

interface GraphLink {
  source: string;
  target: string;
  type: "parent" | "lateral";
  color: string;
  opacity: number;
  dashed: boolean;
  width: number;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Tree → Graph Data Transformer
   ═══════════════════════════════════════════════════════════════════════════ */

function flattenTree(
  nodes: MemoryTreeNode[],
  allNodes: GraphNode[],
  allLinks: GraphLink[],
  parentId?: string
) {
  for (const node of nodes) {
    const size = Math.min(20, 4 + (node.composite_weight || 0) * 2);
    allNodes.push({
      id: node.id,
      name: node.name,
      node_type: node.node_type,
      content: node.content,
      composite_weight: node.composite_weight || 0,
      decay_score: node.decay_score || 1,
      is_archived: node.is_archived,
      tier_level: node.tier_level,
      val: size,
      color: NODE_COLORS[node.node_type] || "#555",
    });

    // Parent-child link
    if (parentId) {
      allLinks.push({
        source: parentId,
        target: node.id,
        type: "parent",
        color: NODE_COLORS[node.node_type] || "#555",
        opacity: 0.4,
        dashed: false,
        width: 1,
      });
    }

    // Lateral links
    if (node.lateral_links) {
      for (const link of node.lateral_links) {
        allLinks.push({
          source: node.id,
          target: link.target_id,
          type: "lateral",
          color: "#7c6af7",
          opacity: 0.6,
          dashed: true,
          width: Math.max(0.5, (link.similarity || 0.5) * 2),
        });
      }
    }

    // Recurse children
    if (node.children && node.children.length > 0) {
      flattenTree(node.children, allNodes, allLinks, node.id);
    }
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   NetworkView
   ═══════════════════════════════════════════════════════════════════════════ */

export default function NetworkView() {
  const [tree, setTree] = useState<MemoryTreeNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [showArchived, setShowArchived] = useState(false);
  const [typeFilter, setTypeFilter] = useState<Record<string, boolean>>({
    ANCHOR: true,
    DOMAIN: true,
    CLUSTER: true,
    INSTANCE: true,
  });
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });
  const graphRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  useEffect(() => {
    getMemoryTree()
      .then(setTree)
      .catch(() => setTree([]))
      .finally(() => setLoading(false));
  }, []);

  // Measure container
  useEffect(() => {
    if (containerRef.current) {
      const { width, height } = containerRef.current.getBoundingClientRect();
      setDimensions({ width, height: height - 52 }); // subtract controls bar
    }
    const onResize = () => {
      if (containerRef.current) {
        const { width, height } = containerRef.current.getBoundingClientRect();
        setDimensions({ width, height: height - 52 });
      }
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // Build graph data
  const graphData = useMemo(() => {
    const allNodes: GraphNode[] = [];
    const allLinks: GraphLink[] = [];
    flattenTree(tree, allNodes, allLinks);

    // Filter
    const nodeIds = new Set<string>();
    const filteredNodes = allNodes.filter((n) => {
      if (!showArchived && n.is_archived) return false;
      if (!typeFilter[n.node_type]) return false;
      nodeIds.add(n.id);
      return true;
    });

    const filteredLinks = allLinks.filter(
      (l) => nodeIds.has(l.source as string) && nodeIds.has(l.target as string)
    );

    return { nodes: filteredNodes, links: filteredLinks };
  }, [tree, showArchived, typeFilter]);

  const handleFitView = useCallback(() => {
    if (graphRef.current) {
      graphRef.current.zoomToFit(400, 40);
    }
  }, []);

  const toggleType = (type: string) => {
    setTypeFilter((prev) => ({ ...prev, [type]: !prev[type] }));
  };

  // Custom node canvas render
  const nodeCanvasObject = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const size = node.val || 4;
      const x = node.x || 0;
      const y = node.y || 0;
      const alpha = node.is_archived ? 0.4 : 1;

      ctx.globalAlpha = alpha;

      // ANCHOR outer ring
      if (node.node_type === "ANCHOR") {
        ctx.beginPath();
        ctx.arc(x, y, size + 3, 0, 2 * Math.PI);
        ctx.strokeStyle = NODE_COLORS.ANCHOR;
        ctx.lineWidth = 1.5 / globalScale;
        ctx.stroke();
      }

      // Main circle
      ctx.beginPath();
      ctx.arc(x, y, size, 0, 2 * Math.PI);
      ctx.fillStyle = node.color || "#555";
      ctx.fill();

      // Label (only at reasonable zoom)
      if (globalScale > 0.6) {
        const label = (node.name || "").slice(0, 20);
        const fontSize = Math.max(10 / globalScale, 3);
        ctx.font = `${fontSize}px Inter, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle = "rgba(240,240,255,0.7)";
        ctx.fillText(label, x, y + size + 4 / globalScale);
      }

      ctx.globalAlpha = 1;
    },
    []
  );

  // Custom link canvas render (for dashed lateral links)
  const linkCanvasObject = useCallback(
    (link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const src = link.source;
      const tgt = link.target;
      if (!src || !tgt || src.x == null || tgt.x == null) return;

      ctx.beginPath();
      ctx.globalAlpha = link.opacity || 0.4;
      ctx.strokeStyle = link.color || "#555";
      ctx.lineWidth = (link.width || 1) / globalScale;

      if (link.dashed) {
        ctx.setLineDash([3 / globalScale, 3 / globalScale]);
      } else {
        ctx.setLineDash([]);
      }

      ctx.moveTo(src.x, src.y);
      ctx.lineTo(tgt.x, tgt.y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    },
    []
  );

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-text-muted text-sm">
        Loading network graph...
      </div>
    );
  }

  if (graphData.nodes.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-center">
        <svg width="64" height="64" viewBox="0 0 24 24" fill="none" className="mb-4 opacity-20">
          <circle cx="12" cy="5" r="3" stroke="var(--text-muted)" strokeWidth="1.5" />
          <circle cx="5" cy="19" r="3" stroke="var(--text-muted)" strokeWidth="1.5" />
          <circle cx="19" cy="19" r="3" stroke="var(--text-muted)" strokeWidth="1.5" />
          <path d="M12 8v3M9.5 14.5L7 17M14.5 14.5L17 17" stroke="var(--text-muted)" strokeWidth="1.5" />
        </svg>
        <p className="text-sm text-text-secondary">No memory nodes to visualize</p>
        <p className="text-xs text-text-muted mt-1">Start chatting to build your network</p>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="h-full flex flex-col relative">
      {/* ── Controls Bar ──────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border bg-surface shrink-0">
        <h2 className="text-sm font-semibold text-text-primary mr-2">Network</h2>

        <button
          onClick={handleFitView}
          className="px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-elevated border border-border
                     text-text-secondary hover:text-primary hover:border-primary/40 transition-all"
        >
          Fit View
        </button>

        <div className="w-px h-5 bg-border" />

        {/* Show Archived toggle */}
        <button
          onClick={() => setShowArchived(!showArchived)}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
            showArchived
              ? "bg-primary/10 border-primary/30 text-primary"
              : "bg-surface-elevated border-border text-text-muted hover:text-text-secondary"
          }`}
        >
          Archived
        </button>

        <div className="w-px h-5 bg-border" />

        {/* Type filters */}
        {TYPE_ORDER.map((type) => (
          <button
            key={type}
            onClick={() => toggleType(type)}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium border transition-all ${
              typeFilter[type]
                ? "border-border text-text-primary"
                : "border-transparent text-text-muted opacity-40"
            }`}
          >
            <span
              className="w-2 h-2 rounded-full"
              style={{
                backgroundColor: NODE_COLORS[type],
                opacity: typeFilter[type] ? 1 : 0.3,
              }}
            />
            {type}
          </button>
        ))}

        <span className="ml-auto text-[10px] text-text-muted">
          {graphData.nodes.length} nodes · {graphData.links.length} links
        </span>
      </div>

      {/* ── Graph ─────────────────────────────────────── */}
      <div className="flex-1 relative">
        <ForceGraph2D
          ref={graphRef}
          graphData={graphData}
          width={dimensions.width}
          height={dimensions.height}
          backgroundColor="#0a0a0f"
          nodeCanvasObject={nodeCanvasObject}
          nodePointerAreaPaint={(node: any, color: string, ctx: CanvasRenderingContext2D) => {
            ctx.beginPath();
            ctx.arc(node.x, node.y, (node.val || 4) + 4, 0, 2 * Math.PI);
            ctx.fillStyle = color;
            ctx.fill();
          }}
          linkCanvasObject={linkCanvasObject}
          onNodeClick={(node: any) => setSelectedNodeId(node.id)}
          onNodeHover={(node: any, prevNode: any) => {
            setHoveredNode(node || null);
          }}
          d3AlphaDecay={0.02}
          d3VelocityDecay={0.3}
          cooldownTicks={150}
          enableZoomInteraction={true}
          enablePanInteraction={true}
        />

        {/* Tooltip */}
        {hoveredNode && (
          <div
            className="absolute z-20 pointer-events-none px-3 py-2.5 rounded-lg
                       bg-surface border border-border shadow-xl max-w-xs"
            style={{ left: 16, bottom: 80 }}
          >
            <div className="flex items-center gap-2 mb-1">
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: NODE_COLORS[hoveredNode.node_type] || "#555" }}
              />
              <span className="text-xs font-semibold text-text-primary truncate">
                {hoveredNode.name}
              </span>
            </div>
            <p className="text-[11px] text-text-secondary leading-relaxed">
              {(hoveredNode.content || "").slice(0, 60)}
              {(hoveredNode.content || "").length > 60 ? "..." : ""}
            </p>
            <p className="text-[10px] text-text-muted mt-1">
              wt: {hoveredNode.composite_weight.toFixed(3)}
            </p>
          </div>
        )}

        {/* Legend */}
        <div
          className="absolute bottom-4 left-4 z-10 bg-surface/80 backdrop-blur-sm rounded-lg
                     border border-border px-3 py-2.5 space-y-1.5"
        >
          {TYPE_ORDER.map((type) => (
            <div key={type} className="flex items-center gap-2 text-[10px]">
              <span
                className="w-2.5 h-2.5 rounded-full"
                style={{ backgroundColor: NODE_COLORS[type] }}
              />
              <span className="text-text-secondary">{type}</span>
            </div>
          ))}
          <div className="border-t border-border my-1 pt-1">
            <div className="flex items-center gap-2 text-[10px]">
              <span className="w-4 h-px bg-text-muted" />
              <span className="text-text-muted">Hierarchy</span>
            </div>
            <div className="flex items-center gap-2 text-[10px] mt-0.5">
              <span className="w-4 border-t border-dashed border-primary" />
              <span className="text-text-muted">Lateral</span>
            </div>
          </div>
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
