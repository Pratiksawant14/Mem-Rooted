"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { sendMessage, ChatResponse, MemoryTransparency } from "@/lib/api";
import MemoryBadge from "./MemoryBadge";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  transparency?: MemoryTransparency;
  nodes_used?: string[];
}

interface Props {
  onTransparencyUpdate: (data: {
    anchor_count: number;
    domain_count: number;
    retrieved_count: number;
    channels_used: string[];
    nodes_used: string[];
  } | null) => void;
}

export default function ChatInterface({ onTransparencyUpdate }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId] = useState(() =>
    typeof window !== "undefined" ? crypto.randomUUID() : "init"
  );

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll on new message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputValue(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }, []);

  const handleSubmit = useCallback(async () => {
    const trimmed = inputValue.trim();
    if (!trimmed || isLoading) return;

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInputValue("");
    setIsLoading(true);

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    try {
      const res: ChatResponse = await sendMessage(trimmed, sessionId);
      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: res.response,
        timestamp: new Date(),
        transparency: res.memory_transparency,
        nodes_used: res.nodes_used,
      };
      setMessages((prev) => [...prev, assistantMsg]);

      onTransparencyUpdate({
        ...res.memory_transparency,
        nodes_used: res.nodes_used,
      });
    } catch (err) {
      const errorMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "Sorry, I couldn't process that. Please try again.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  }, [inputValue, isLoading, sessionId, onTransparencyUpdate]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  const formatTime = (date: Date) =>
    date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div className="flex flex-col h-full bg-bg">
      {/* ── Header ──────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-border">
        <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
            <circle cx="12" cy="12" r="3" />
            <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
          </svg>
        </div>
        <div>
          <h1 className="text-base font-semibold text-text-primary">Mem-Rooted</h1>
          <p className="text-xs text-text-muted">Hierarchical Memory AI</p>
        </div>
      </div>

      {/* ── Messages ────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-16 h-16 rounded-2xl bg-surface-elevated flex items-center justify-center mb-4 glow-primary">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="1.5">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
              </svg>
            </div>
            <h2 className="text-lg font-medium text-text-primary mb-1">
              Start a conversation
            </h2>
            <p className="text-sm text-text-muted max-w-xs">
              Every message builds your personal memory network.
              Share anything about yourself to begin.
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <motion.div
            key={msg.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}
          >
            <div
              className={`max-w-[80%] px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
                msg.role === "user"
                  ? "bg-primary text-white rounded-2xl rounded-br-md"
                  : "bg-surface-elevated text-text-primary rounded-2xl rounded-bl-md border border-border"
              }`}
            >
              {msg.content}
            </div>

            <span className="text-[11px] text-text-muted mt-1 px-1">
              {formatTime(msg.timestamp)}
            </span>

            {msg.role === "assistant" && msg.transparency && (
              <div className="mt-1">
                <MemoryBadge
                  anchor_count={msg.transparency.anchor_count}
                  domain_count={msg.transparency.domain_count}
                  retrieved_count={msg.transparency.retrieved_count}
                  channels_used={msg.transparency.channels_used}
                />
              </div>
            )}
          </motion.div>
        ))}

        {/* Loading indicator */}
        {isLoading && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-start"
          >
            <div className="bg-surface-elevated rounded-2xl rounded-bl-md border border-border px-4 py-3 flex items-center gap-1.5">
              {[0, 1, 2].map((i) => (
                <motion.div
                  key={i}
                  className="w-2 h-2 rounded-full bg-primary"
                  animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1, 0.8] }}
                  transition={{
                    duration: 1,
                    repeat: Infinity,
                    delay: i * 0.2,
                    ease: "easeInOut",
                  }}
                />
              ))}
            </div>
          </motion.div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* ── Input Area ──────────────────────────────────── */}
      <div className="border-t border-border px-6 py-3 bg-bg">
        <div className="flex items-end gap-3 max-w-full">
          <textarea
            ref={textareaRef}
            value={inputValue}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder="Talk to Mem-Rooted..."
            rows={1}
            className="flex-1 bg-surface border border-border rounded-xl px-4 py-3 text-sm
                       text-text-primary placeholder:text-text-muted resize-none
                       focus:border-primary focus:ring-1 focus:ring-primary-glow
                       transition-all max-h-[120px] overflow-y-auto"
          />
          <button
            onClick={handleSubmit}
            disabled={isLoading || !inputValue.trim()}
            className="flex items-center justify-center w-10 h-10 rounded-xl
                       bg-primary text-white hover:bg-primary-hover
                       disabled:opacity-30 disabled:cursor-not-allowed
                       transition-all shrink-0"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <path d="M22 2L11 13" />
              <path d="M22 2L15 22L11 13L2 9L22 2Z" />
            </svg>
          </button>
        </div>
        <p className="text-[10px] text-text-muted mt-2 text-center">
          Shift+Enter for newline · Memory is extracted from every message
        </p>
      </div>
    </div>
  );
}
