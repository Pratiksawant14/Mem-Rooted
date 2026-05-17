"""
Mem-Rooted — In-Memory Graph (NetworkX)

Mirrors the PostgreSQL node hierarchy in a NetworkX DiGraph for fast
graph traversal: spreading activation, ancestor/subtree walks, merge/split
candidate detection, and temporal neighbor discovery.

Built once per session from DB, held in memory, updated incrementally.
"""

import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Optional

import networkx as nx
import numpy as np

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _cosine_sim(a: Optional[list], b: Optional[list]) -> float:
    """Cosine similarity between two embedding vectors."""
    if a is None or b is None:
        return 0.0
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _node_to_attrs(node) -> dict:
    """Extract serializable attributes from a SQLAlchemy Node object."""
    embedding = None
    if node.embedding is not None:
        embedding = list(node.embedding) if not isinstance(node.embedding, list) else node.embedding

    return {
        "id": str(node.id),
        "name": node.name,
        "node_type": node.node_type.value if hasattr(node.node_type, "value") else str(node.node_type),
        "content": node.content,
        "parent_id": str(node.parent_id) if node.parent_id else None,
        "tier_level": node.tier_level,
        "physical_weight": node.physical_weight or 0.0,
        "recall_weight": node.recall_weight or 0.0,
        "semantic_weight": node.semantic_weight or 0.0,
        "composite_weight": node.composite_weight or 0.0,
        "decay_score": node.decay_score or 1.0,
        "promotion_score": node.promotion_score or 0.0,
        "lateral_links": node.lateral_links or [],
        "embedding": embedding,
        "created_at": node.created_at,
        "last_recalled_at": node.last_recalled_at,
        "source_session_id": str(node.source_session_id) if node.source_session_id else None,
        "priority_flag": node.priority_flag.value if hasattr(node.priority_flag, "value") else str(node.priority_flag),
        "is_archived": node.is_archived,
    }


# ══════════════════════════════════════════════════════════════════════════════
# MemoryGraph
# ══════════════════════════════════════════════════════════════════════════════

class MemoryGraph:
    """
    In-memory NetworkX graph that mirrors the PostgreSQL node tree.

    - Directed edges: parent → child (hierarchy)
    - Undirected edges: lateral links with link_strength weights
    - Supports spreading activation, ancestor/subtree walks,
      merge/split candidate detection, and temporal neighbor discovery.
    """

    def __init__(self):
        self.graph: nx.DiGraph = nx.DiGraph()
        self._node_index: dict[str, dict] = {}  # id → attrs for fast lookup

    # ──────────────────────────────────────────────────────────────────────
    # Build from DB
    # ──────────────────────────────────────────────────────────────────────

    def build_from_db(self, nodes: list) -> None:
        """
        Construct directed graph from node list.

        - Each node becomes a graph node with all fields as attributes.
        - Parent → child relationships become directed edges.
        - Lateral links become undirected edges (added as bidirectional)
          with link_strength as edge weight.
        """
        self.graph.clear()
        self._node_index.clear()

        # Phase 1: Add all nodes
        for node in nodes:
            attrs = _node_to_attrs(node)
            nid = attrs["id"]
            self.graph.add_node(nid, **attrs)
            self._node_index[nid] = attrs

        # Phase 2: Add parent-child directed edges
        for nid, attrs in self._node_index.items():
            parent_id = attrs.get("parent_id")
            if parent_id and parent_id in self._node_index:
                # Edge direction: parent → child
                self.graph.add_edge(parent_id, nid, edge_type="hierarchy", weight=1.0)

        # Phase 3: Add lateral link edges (bidirectional for undirected semantics)
        seen_lateral = set()
        for nid, attrs in self._node_index.items():
            for link in attrs.get("lateral_links", []):
                target_id = link.get("target_id")
                strength = link.get("similarity", 0.5)
                if target_id and target_id in self._node_index:
                    pair = tuple(sorted([nid, target_id]))
                    if pair not in seen_lateral:
                        seen_lateral.add(pair)
                        # Add both directions for spreading activation
                        self.graph.add_edge(nid, target_id, edge_type="lateral", weight=strength)
                        self.graph.add_edge(target_id, nid, edge_type="lateral", weight=strength)

        logger.info(
            f"MemoryGraph built: {self.graph.number_of_nodes()} nodes, "
            f"{self.graph.number_of_edges()} edges"
        )

    # ──────────────────────────────────────────────────────────────────────
    # Spreading Activation
    # ──────────────────────────────────────────────────────────────────────

    def spreading_activation(
        self,
        seed_node_ids: list[str],
        decay_factor: float = 0.5,
        max_hops: int = 3,
    ) -> dict[str, float]:
        """
        Spreading activation from seed nodes through the graph.

        Algorithm:
        - Seed nodes start at activation 1.0
        - Each hop multiplies activation by decay_factor
        - Spreads along both hierarchy edges AND lateral edges
        - A node's final activation = sum of all incoming paths, capped at 1.0
        - Only returns nodes with activation > 0.05
        """
        activation: dict[str, float] = defaultdict(float)

        # BFS queue: (node_id, current_activation, hops_remaining)
        queue: deque[tuple[str, float, int]] = deque()

        # Seed all starting nodes
        for sid in seed_node_ids:
            if sid in self.graph:
                activation[sid] += 1.0
                queue.append((sid, 1.0, max_hops))

        visited_at_hop: dict[str, int] = {}  # track best hop level per node

        while queue:
            current_id, current_activation, hops_left = queue.popleft()

            if hops_left <= 0:
                continue

            next_activation = current_activation * decay_factor

            if next_activation < 0.01:
                continue

            # Spread to all neighbors (successors + predecessors for full spread)
            neighbors = set(self.graph.successors(current_id)) | set(self.graph.predecessors(current_id))

            for neighbor_id in neighbors:
                # Apply edge weight for lateral links
                edge_data = self.graph.get_edge_data(current_id, neighbor_id)
                if edge_data is None:
                    edge_data = self.graph.get_edge_data(neighbor_id, current_id) or {}
                edge_weight = edge_data.get("weight", 1.0)
                weighted_activation = next_activation * edge_weight

                activation[neighbor_id] += weighted_activation

                # Only re-queue if we haven't visited with more hops remaining
                prev_hop = visited_at_hop.get(neighbor_id, -1)
                remaining = hops_left - 1
                if remaining > prev_hop:
                    visited_at_hop[neighbor_id] = remaining
                    queue.append((neighbor_id, weighted_activation, remaining))

        # Cap at 1.0, filter > 0.05
        result = {}
        for nid, score in activation.items():
            capped = min(1.0, score)
            if capped > 0.05:
                result[nid] = round(capped, 6)

        return result

    # ──────────────────────────────────────────────────────────────────────
    # Temporal Neighbors
    # ──────────────────────────────────────────────────────────────────────

    def temporal_neighbors(
        self,
        node_id: str,
        days_window: int = 30,
    ) -> list[str]:
        """
        Find nodes created or last_recalled within days_window of this node
        that share at least one entity in their content (substring match).
        """
        if node_id not in self._node_index:
            return []

        target = self._node_index[node_id]
        target_time = target.get("last_recalled_at") or target.get("created_at")
        if target_time is None:
            return []

        # Make timezone-aware if needed
        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=timezone.utc)

        window = timedelta(days=days_window)
        target_content_lower = (target.get("content") or "").lower()

        # Extract simple "entity" words (capitalized words with 3+ chars) from target
        target_words = set()
        for word in (target.get("content") or "").split():
            cleaned = word.strip(".,!?;:\"'()[]")
            if len(cleaned) >= 3 and cleaned[0].isupper():
                target_words.add(cleaned.lower())

        if not target_words:
            # Fallback: use all words with 4+ chars
            target_words = {
                w.strip(".,!?;:\"'()[]").lower()
                for w in (target.get("content") or "").split()
                if len(w.strip(".,!?;:\"'()[]")) >= 4
            }

        neighbors = []
        for nid, attrs in self._node_index.items():
            if nid == node_id or attrs.get("is_archived"):
                continue

            node_time = attrs.get("last_recalled_at") or attrs.get("created_at")
            if node_time is None:
                continue
            if node_time.tzinfo is None:
                node_time = node_time.replace(tzinfo=timezone.utc)

            # Check time window
            if abs((node_time - target_time).total_seconds()) > window.total_seconds():
                continue

            # Check entity overlap (substring match)
            node_content_lower = (attrs.get("content") or "").lower()
            if any(word in node_content_lower for word in target_words):
                neighbors.append(nid)

        return neighbors

    # ──────────────────────────────────────────────────────────────────────
    # Ancestor / Subtree Walks
    # ──────────────────────────────────────────────────────────────────────

    def get_ancestors(self, node_id: str) -> list[str]:
        """Walk up the parent chain to ANCHOR level. Returns list of ancestor IDs."""
        ancestors = []
        current = node_id

        visited = set()
        while current in self._node_index:
            if current in visited:
                break  # cycle guard
            visited.add(current)

            parent_id = self._node_index[current].get("parent_id")
            if not parent_id or parent_id not in self._node_index:
                break
            ancestors.append(parent_id)
            current = parent_id

        return ancestors

    def get_subtree(self, node_id: str) -> list[str]:
        """BFS down from node_id, return all descendant IDs."""
        if node_id not in self.graph:
            return []

        descendants = []
        queue = deque()

        # Children are successors in our parent→child edge model
        for child in self.graph.successors(node_id):
            edge_data = self.graph.get_edge_data(node_id, child, {})
            if edge_data.get("edge_type") == "hierarchy":
                queue.append(child)

        visited = {node_id}
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            descendants.append(current)

            for child in self.graph.successors(current):
                edge_data = self.graph.get_edge_data(current, child, {})
                if edge_data.get("edge_type") == "hierarchy" and child not in visited:
                    queue.append(child)

        return descendants

    # ──────────────────────────────────────────────────────────────────────
    # Merge Candidates
    # ──────────────────────────────────────────────────────────────────────

    def find_merge_candidates(
        self,
        threshold: float = 0.85,
    ) -> list[tuple[str, str, float]]:
        """
        Find pairs of sibling nodes whose embeddings have cosine similarity
        above threshold.

        Returns list of (node_id_a, node_id_b, similarity_score) sorted by
        similarity descending.
        """
        # Group non-archived nodes by parent_id
        siblings_by_parent: dict[str, list[str]] = defaultdict(list)
        for nid, attrs in self._node_index.items():
            if attrs.get("is_archived"):
                continue
            pid = attrs.get("parent_id")
            if pid:
                siblings_by_parent[pid].append(nid)

        candidates = []
        for parent_id, siblings in siblings_by_parent.items():
            if len(siblings) < 2:
                continue

            for id_a, id_b in combinations(siblings, 2):
                emb_a = self._node_index[id_a].get("embedding")
                emb_b = self._node_index[id_b].get("embedding")
                sim = _cosine_sim(emb_a, emb_b)
                if sim >= threshold:
                    candidates.append((id_a, id_b, round(sim, 6)))

        # Sort by similarity descending
        candidates.sort(key=lambda x: x[2], reverse=True)
        return candidates

    # ──────────────────────────────────────────────────────────────────────
    # Split Candidates
    # ──────────────────────────────────────────────────────────────────────

    def find_split_candidates(
        self,
        max_children: int = 12,
        divergence_threshold: float = 0.4,
    ) -> list[str]:
        """
        Find nodes with more than max_children children where the average
        pairwise cosine similarity among children is below divergence_threshold.

        These nodes are overloaded and should be split.
        Returns list of node_ids.
        """
        candidates = []

        for nid, attrs in self._node_index.items():
            if attrs.get("is_archived"):
                continue

            # Get hierarchy children only
            children = []
            for succ in self.graph.successors(nid):
                edge_data = self.graph.get_edge_data(nid, succ, {})
                if edge_data.get("edge_type") == "hierarchy":
                    child_attrs = self._node_index.get(succ)
                    if child_attrs and not child_attrs.get("is_archived"):
                        children.append(succ)

            if len(children) <= max_children:
                continue

            # Compute average pairwise cosine similarity among children
            embeddings = []
            for cid in children:
                emb = self._node_index[cid].get("embedding")
                if emb is not None:
                    embeddings.append(emb)

            if len(embeddings) < 2:
                # Not enough embeddings to evaluate — flag by count alone
                candidates.append(nid)
                continue

            total_sim = 0.0
            pair_count = 0
            for i in range(len(embeddings)):
                for j in range(i + 1, len(embeddings)):
                    total_sim += _cosine_sim(embeddings[i], embeddings[j])
                    pair_count += 1

            avg_sim = total_sim / pair_count if pair_count > 0 else 1.0

            if avg_sim < divergence_threshold:
                candidates.append(nid)

        return candidates

    # ──────────────────────────────────────────────────────────────────────
    # Incremental Updates
    # ──────────────────────────────────────────────────────────────────────

    def update_node_in_graph(self, node) -> None:
        """
        Sync a single updated node back into the graph without full rebuild.
        Updates all attributes in place.
        """
        attrs = _node_to_attrs(node)
        nid = attrs["id"]

        if nid not in self.graph:
            logger.warning(f"update_node_in_graph: node {nid} not in graph, adding instead")
            self.add_node_to_graph(node, node.parent_id)
            return

        # Update node attributes
        for key, value in attrs.items():
            self.graph.nodes[nid][key] = value
        self._node_index[nid] = attrs

        # Update parent edge if parent changed
        old_parent = None
        for pred in self.graph.predecessors(nid):
            edge_data = self.graph.get_edge_data(pred, nid, {})
            if edge_data.get("edge_type") == "hierarchy":
                old_parent = pred
                break

        new_parent = attrs.get("parent_id")
        if old_parent != new_parent:
            if old_parent and self.graph.has_edge(old_parent, nid):
                self.graph.remove_edge(old_parent, nid)
            if new_parent and new_parent in self.graph:
                self.graph.add_edge(new_parent, nid, edge_type="hierarchy", weight=1.0)

        # Rebuild lateral links for this node
        # First remove old lateral edges involving this node
        edges_to_remove = []
        for succ in list(self.graph.successors(nid)):
            if self.graph.get_edge_data(nid, succ, {}).get("edge_type") == "lateral":
                edges_to_remove.append((nid, succ))
        for pred in list(self.graph.predecessors(nid)):
            if self.graph.get_edge_data(pred, nid, {}).get("edge_type") == "lateral":
                edges_to_remove.append((pred, nid))
        self.graph.remove_edges_from(edges_to_remove)

        # Add current lateral links
        for link in attrs.get("lateral_links", []):
            target_id = link.get("target_id")
            strength = link.get("similarity", 0.5)
            if target_id and target_id in self.graph:
                self.graph.add_edge(nid, target_id, edge_type="lateral", weight=strength)
                self.graph.add_edge(target_id, nid, edge_type="lateral", weight=strength)

    def add_node_to_graph(self, node, parent_id=None) -> None:
        """Add a single new node to the live graph with its parent edge."""
        attrs = _node_to_attrs(node)
        nid = attrs["id"]

        self.graph.add_node(nid, **attrs)
        self._node_index[nid] = attrs

        # Add parent → child edge
        pid = str(parent_id) if parent_id else attrs.get("parent_id")
        if pid and pid in self.graph:
            self.graph.add_edge(pid, nid, edge_type="hierarchy", weight=1.0)

        # Add lateral links
        for link in attrs.get("lateral_links", []):
            target_id = link.get("target_id")
            strength = link.get("similarity", 0.5)
            if target_id and target_id in self.graph:
                self.graph.add_edge(nid, target_id, edge_type="lateral", weight=strength)
                self.graph.add_edge(target_id, nid, edge_type="lateral", weight=strength)

        logger.debug(f"Added node {nid} ({attrs.get('name')}) to live graph")

    # ──────────────────────────────────────────────────────────────────────
    # Utility
    # ──────────────────────────────────────────────────────────────────────

    def get_node_attrs(self, node_id: str) -> Optional[dict]:
        """Get cached attributes for a node."""
        return self._node_index.get(node_id)

    def get_all_node_ids(self) -> list[str]:
        """Return all node IDs in the graph."""
        return list(self._node_index.keys())

    def node_count(self) -> int:
        """Total nodes in graph."""
        return self.graph.number_of_nodes()

    def edge_count(self) -> int:
        """Total edges in graph."""
        return self.graph.number_of_edges()
