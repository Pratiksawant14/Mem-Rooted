import axios from "axios";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
  timeout: 30000,
});

api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const userId = localStorage.getItem("mem_user_id");
    if (userId) {
      config.headers["x-user-id"] = userId;
    }
  }
  return config;
});

/* ═══════════════════════════════════════════════════════════════════════════
   TypeScript Interfaces (matching backend response shapes exactly)
   ═══════════════════════════════════════════════════════════════════════════ */

export interface MemoryTransparency {
  anchor_count: number;
  domain_count: number;
  retrieved_count: number;
  channels_used: string[];
}

export interface ChatResponse {
  response: string;
  session_id: string;
  nodes_used: string[];
  memory_transparency: MemoryTransparency;
}

export interface MemoryTreeNode {
  id: string;
  name: string;
  node_type: "ANCHOR" | "DOMAIN" | "CLUSTER" | "INSTANCE";
  tier_level: number;
  content: string;
  composite_weight: number;
  decay_score: number;
  is_archived: boolean;
  lateral_links: LateralLink[];
  children: MemoryTreeNode[];
  parent_id: string | null;
  physical_weight: number;
  recall_weight: number;
  semantic_weight: number;
  priority_flag: string | null;
  created_at: string | null;
  last_recalled_at: string | null;
}

export interface LateralLink {
  target_id: string;
  similarity: number;
  created_at: string;
}

export interface NodeDetail extends MemoryTreeNode {
  operation_log: OperationLogEntry[];
  children_count: number;
  parent?: { id: string; name: string; node_type: string };
}

export interface OperationLogEntry {
  op: string;
  timestamp: string;
  details: Record<string, unknown>;
}

export interface MemoryStats {
  nodes_by_type: Record<string, number>;
  total_active: number;
  total_archived: number;
  avg_decay_by_tier: Record<string, number | null>;
  promotions_total: number;
  demotions_total: number;
  top_by_composite_weight: { id: string; name: string; node_type: string; composite_weight: number }[];
  top_by_recall_weight: { id: string; name: string; node_type: string; recall_weight: number }[];
}

export interface SchedulerJob {
  last_run: string | null;
  operations: number;
  errors: number;
  details: Record<string, unknown>;
}

export interface SchedulerStatus {
  scheduler_running: boolean;
  started_at: string | null;
  jobs: Record<string, SchedulerJob>;
}

export interface JobResult {
  triggered: boolean;
  job_name: string;
  last_run: string | null;
  total_operations: number;
}

export interface SearchResult {
  id: string;
  name: string;
  node_type: string;
  content_preview: string;
  composite_weight: number;
  decay_score: number;
}

export interface SessionInfo {
  id: string;
  started_at: string | null;
  message_count: number;
  summary: string | null;
}

export interface MessageInfo {
  id: string;
  role: string;
  content: string;
  created_at: string | null;
  node_ids_used: string[];
}

/* ═══════════════════════════════════════════════════════════════════════════
   API Functions
   ═══════════════════════════════════════════════════════════════════════════ */

export async function sendMessage(message: string, sessionId: string): Promise<ChatResponse> {
  const { data } = await api.post<ChatResponse>("/api/chat/message", {
    message,
    session_id: sessionId,
  });
  return data;
}

export async function getMemoryTree(): Promise<MemoryTreeNode[]> {
  const { data } = await api.get<{ tree: MemoryTreeNode[]; total_nodes: number }>("/api/memory/tree");
  return data.tree;
}

export async function getMemoryStats(): Promise<MemoryStats> {
  const { data } = await api.get<MemoryStats>("/api/memory/stats");
  return data;
}

export async function getNodeDetail(nodeId: string): Promise<NodeDetail> {
  const { data } = await api.get<NodeDetail>(`/api/memory/node/${nodeId}`);
  return data;
}

export async function getSchedulerStatus(): Promise<SchedulerStatus> {
  const { data } = await api.get<SchedulerStatus>("/api/memory/scheduler/status");
  return data;
}

export async function triggerSchedulerJob(jobName: string): Promise<JobResult> {
  const { data } = await api.post<JobResult>(`/api/memory/scheduler/trigger/${jobName}`);
  return data;
}

export async function archiveNode(nodeId: string): Promise<{ success: boolean; node_id: string }> {
  const { data } = await api.delete<{ success: boolean; node_id: string }>(`/api/memory/node/${nodeId}`);
  return data;
}

export async function searchMemory(query: string): Promise<SearchResult[]> {
  const { data } = await api.get<{ results: SearchResult[] }>("/api/memory/search", {
    params: { q: query },
  });
  return data.results;
}

export async function getSessions(): Promise<SessionInfo[]> {
  const { data } = await api.get<SessionInfo[]>("/api/chat/sessions");
  return data;
}

export async function getSessionMessages(sessionId: string): Promise<MessageInfo[]> {
  const { data } = await api.get<MessageInfo[]>(`/api/chat/sessions/${sessionId}/messages`);
  return data;
}
