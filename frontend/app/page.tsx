"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
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
  }, [router]);

  if (!username) return null; // Wait for redirect or load

  const handleLogout = () => {
    localStorage.removeItem("mem_user_id");
    localStorage.removeItem("mem_username");
    router.push("/login");
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      {/* Left: Chat Interface */}
      <div
        className="flex flex-col transition-all duration-300 ease-in-out"
        style={{ width: panelOpen ? "60%" : "100%" }}
      >
        <ChatInterface
          username={username}
          onLogout={handleLogout}
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
      )}
    </div>
  );
}
