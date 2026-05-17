"use client";

import { useState } from "react";
import Link from "next/link";
import ChatInterface from "@/components/chat/ChatInterface";
import TransparencyPanel from "@/components/memory/TransparencyPanel";

export default function Home() {
  const [panelOpen, setPanelOpen] = useState(true);
  const [lastTransparency, setLastTransparency] = useState<{
    anchor_count: number;
    domain_count: number;
    retrieved_count: number;
    channels_used: string[];
    nodes_used: string[];
  } | null>(null);

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      {/* Left: Chat Interface */}
      <div
        className="flex flex-col transition-all duration-300 ease-in-out"
        style={{ width: panelOpen ? "60%" : "100%" }}
      >
        <ChatInterface
          onTransparencyUpdate={setLastTransparency}
        />
      </div>

      {/* Right: Memory Transparency Panel */}
      {panelOpen && (
        <div
          className="flex flex-col border-l border-border transition-all duration-300 ease-in-out"
          style={{ width: "40%" }}
        >
          <TransparencyPanel
            transparency={lastTransparency}
            onClose={() => setPanelOpen(false)}
          />
        </div>
      )}

      {/* Panel toggle when collapsed */}
      {!panelOpen && (
        <button
          onClick={() => setPanelOpen(true)}
          className="fixed right-4 top-4 z-50 flex items-center gap-2 px-3 py-2 rounded-lg
                     bg-surface border border-border text-text-secondary text-sm
                     hover:bg-surface-elevated hover:text-text-primary transition-all"
          title="Show memory panel"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 12h18M3 6h18M3 18h18" />
          </svg>
          Memory
        </button>
      )}

      {/* Dashboard link */}
      <Link
        href="/dashboard"
        className="fixed bottom-6 left-6 z-50 flex items-center gap-2 px-4 py-2.5
                   rounded-xl bg-surface border border-border text-text-secondary text-sm font-medium
                   hover:bg-surface-elevated hover:text-primary hover:border-primary/40
                   shadow-lg shadow-black/30 transition-all group"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
        </svg>
        Dashboard
      </Link>
    </div>
  );
}
