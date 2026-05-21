"""
Mem-Rooted — Placement Engine

Decides where every new node belongs in the hierarchy.
Zero LLM calls — pure embedding similarity with hierarchy-weighted scoring.

Pipeline: find_parent → find_lateral_links → sibling_vs_child → PlacementResult
"""

import logging
import uuid
from typing import Optional

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Node, NodeType, PriorityFlag
from graph.network import MemoryGraph

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Result Models
# ══════════════════════════════════════════════════════════════════════════════

class PlacementResult(BaseModel):
    """Result of the full placement pipeline."""
    parent_id: Optional[str] = None
    tier_level: int = 3
    lateral_links: list[tuple[str, float]] = Field(default_factory=list)
    created_new_domain: bool = False
    placement_confidence: float = 0.0


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


def _node_to_dict(node) -> dict:
    """Convert a SQLAlchemy Node (or dict) to a standardized dict."""
    if isinstance(node, dict):
        return node
    emb = None
    if node.embedding is not None:
        emb = list(node.embedding) if not isinstance(node.embedding, list) else node.embedding
    return {
        "id": str(node.id),
        "name": node.name,
        "node_type": node.node_type.value if hasattr(node.node_type, "value") else str(node.node_type),
        "content": node.content,
        "parent_id": str(node.parent_id) if node.parent_id else None,
        "tier_level": node.tier_level,
        "embedding": emb,
        "is_archived": node.is_archived,
        "composite_weight": node.composite_weight or 0.0,
    }


def _get_ancestor_chain(node_id: str, node_map: dict[str, dict]) -> set[str]:
    """Walk up the parent chain and return all ancestor IDs."""
    ancestors = set()
    current = node_id
    visited = set()
    while current in node_map:
        if current in visited:
            break
        visited.add(current)
        pid = node_map[current].get("parent_id")
        if not pid or pid not in node_map:
            break
        ancestors.add(pid)
        current = pid
    return ancestors


def _get_descendant_ids(node_id: str, node_map: dict[str, dict]) -> set[str]:
    """BFS down to collect all descendant IDs."""
    descendants = set()
    # Build children lookup
    children_of: dict[str, list[str]] = {}
    for nid, attrs in node_map.items():
        pid = attrs.get("parent_id")
        if pid:
            children_of.setdefault(pid, []).append(nid)

    queue = list(children_of.get(node_id, []))
    while queue:
        cid = queue.pop(0)
        if cid in descendants:
            continue
        descendants.add(cid)
        queue.extend(children_of.get(cid, []))
    return descendants


# ══════════════════════════════════════════════════════════════════════════════
# PlacementEngine
# ══════════════════════════════════════════════════════════════════════════════

class PlacementEngine:
    """
    Determines hierarchy placement for every new memory node.
    Pure embedding similarity — zero LLM calls.
    """

    # ──────────────────────────────────────────────────────────────────────
    # find_parent
    # ──────────────────────────────────────────────────────────────────────

    def find_parent(
        self,
        candidate_embedding: Optional[list[float]],
        candidate_type: str,
        all_nodes: list[dict],
        graph: MemoryGraph,
    ) -> tuple[Optional[str], float]:
        """
        Find the best parent node for a candidate.

        Returns (parent_id, confidence).
        - ANCHOR: parent_id = None
        - DOMAIN: best-matching ANCHOR
        - CLUSTER: best DOMAIN/CLUSTER with hierarchy weighting
        - INSTANCE: best CLUSTER
        """
        ctype = candidate_type if isinstance(candidate_type, str) else candidate_type.value

        # ── ANCHOR: no parent ────────────────────────────────────────────
        if ctype == "ANCHOR":
            return None, 1.0

        if candidate_embedding is None:
            return None, 0.0

        active_nodes = [n for n in all_nodes if not n.get("is_archived", False)]

        # ── DOMAIN: compare against ANCHORs only ────────────────────────
        if ctype == "DOMAIN":
            anchors = [n for n in active_nodes if n.get("node_type") == "ANCHOR"]
            if not anchors:
                return None, 0.3  # No ANCHOR exists yet

            best_id, best_sim = None, -1.0
            for node in anchors:
                sim = _cosine_sim(candidate_embedding, node.get("embedding"))
                if sim > best_sim:
                    best_sim = sim
                    best_id = node["id"]

            return best_id, max(0.0, best_sim)

        # ── CLUSTER: compare against DOMAINs and CLUSTERs ───────────────
        if ctype == "CLUSTER":
            targets = [
                n for n in active_nodes
                if n.get("node_type") in ("DOMAIN", "CLUSTER")
            ]
            if not targets:
                return None, 0.0

            # Hierarchy weight multiplier: DOMAIN=1.4×, CLUSTER=1.0×
            hierarchy_mult = {"DOMAIN": 1.4, "CLUSTER": 1.0}

            best_id, best_weighted_sim = None, -1.0
            best_raw_sim = 0.0
            for node in targets:
                raw_sim = _cosine_sim(candidate_embedding, node.get("embedding"))
                mult = hierarchy_mult.get(node.get("node_type"), 1.0)
                weighted_sim = raw_sim * mult
                if weighted_sim > best_weighted_sim:
                    best_weighted_sim = weighted_sim
                    best_raw_sim = raw_sim
                    best_id = node["id"]

            # Threshold check: weighted sim must be above 0.35
            if best_weighted_sim < 0.35:
                # No suitable parent — signal that create_domain_node is needed
                return "__CREATE_DOMAIN__", best_raw_sim

            return best_id, best_raw_sim

        # ── INSTANCE: compare against CLUSTERs only ─────────────────────
        if ctype == "INSTANCE":
            clusters = [n for n in active_nodes if n.get("node_type") == "CLUSTER"]
            if not clusters:
                # Fallback: try DOMAIN nodes
                domains = [n for n in active_nodes if n.get("node_type") == "DOMAIN"]
                if domains:
                    best_id, best_sim = None, -1.0
                    for node in domains:
                        sim = _cosine_sim(candidate_embedding, node.get("embedding"))
                        if sim > best_sim:
                            best_sim = sim
                            best_id = node["id"]
                    return best_id, max(0.0, best_sim)
                return None, 0.0

            best_id, best_sim = None, -1.0
            for node in clusters:
                sim = _cosine_sim(candidate_embedding, node.get("embedding"))
                if sim > best_sim:
                    best_sim = sim
                    best_id = node["id"]

            # Below 0.3: reclassify as CLUSTER (returned via special signal)
            if best_sim < 0.3:
                return "__RECLASSIFY_CLUSTER__", best_sim

            return best_id, max(0.0, best_sim)

        return None, 0.0

    # ──────────────────────────────────────────────────────────────────────
    # find_lateral_links
    # ──────────────────────────────────────────────────────────────────────

    def find_lateral_links(
        self,
        new_node_embedding: Optional[list[float]],
        new_node_id: str,
        all_nodes: list[dict],
        threshold: float = 0.65,
    ) -> list[tuple[str, float]]:
        """
        Find cross-branch nodes semantically similar to the new node.

        - Only nodes in different branches (different parent chain)
        - Excludes direct ancestors and descendants
        - Capped at 5 lateral links per node
        - Returns [(node_id, similarity)] sorted by similarity descending
        """
        if new_node_embedding is None:
            return []

        # Build node map for ancestor/descendant lookup
        node_map = {n["id"]: n for n in all_nodes if not n.get("is_archived", False)}

        # Get the new node's ancestor chain and descendants
        ancestors = _get_ancestor_chain(new_node_id, node_map)
        descendants = _get_descendant_ids(new_node_id, node_map)
        excluded = ancestors | descendants | {new_node_id}

        # Find the new node's root branch (topmost ancestor)
        new_node_branch_root = new_node_id
        current = new_node_id
        visited = set()
        while current in node_map:
            if current in visited:
                break
            visited.add(current)
            pid = node_map[current].get("parent_id")
            if not pid or pid not in node_map:
                new_node_branch_root = current
                break
            new_node_branch_root = pid
            current = pid

        candidates = []
        for nid, attrs in node_map.items():
            if nid in excluded:
                continue

            emb = attrs.get("embedding")
            if emb is None:
                continue

            sim = _cosine_sim(new_node_embedding, emb)
            if sim >= threshold:
                candidates.append((nid, round(sim, 6)))

        # Sort by similarity descending, cap at 5
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[:5]

    # ──────────────────────────────────────────────────────────────────────
    # create_domain_node
    # ──────────────────────────────────────────────────────────────────────

    async def create_domain_node(
        self,
        candidate_content: str,
        candidate_embedding: Optional[list[float]],
        anchor_nodes: list[dict],
        db: AsyncSession,
        graph: MemoryGraph,
        user_id: str,
    ) -> Optional[str]:
        """
        Create a new DOMAIN node when no suitable parent exists for a CLUSTER.

        - Content: short label from first 8 words of candidate
        - Placed under most semantically similar ANCHOR
        - Added to graph immediately
        - Returns new DOMAIN node_id
        """
        from core.operations import add_node

        # Derive domain label from candidate content
        words = candidate_content.split()
        label = " ".join(words[:8])
        if len(words) > 8:
            label += "..."

        # Find best ANCHOR parent
        best_anchor_id = None
        best_sim = -1.0
        for anchor in anchor_nodes:
            sim = _cosine_sim(candidate_embedding, anchor.get("embedding"))
            if sim > best_sim:
                best_sim = sim
                best_anchor_id = anchor["id"]

        parent_uuid = uuid.UUID(best_anchor_id) if best_anchor_id else None

        result = await add_node(
            db=db,
            name=label,
            content=f"Auto-discovered domain: {label}",
            node_type=NodeType.DOMAIN,
            parent_id=parent_uuid,
            embedding=candidate_embedding,
            user_id=user_id,
            priority=PriorityFlag.HIGH,
        )

        if result.success and result.node_id:
            # Add to graph immediately
            from sqlalchemy import select as sa_select
            node_result = await db.execute(
                sa_select(Node).where(Node.id == uuid.UUID(result.node_id))
            )
            new_node = node_result.scalar_one_or_none()
            if new_node:
                graph.add_node_to_graph(new_node, parent_uuid)

            logger.info(f"Auto-created DOMAIN node: {label} (id={result.node_id})")
            return result.node_id

        return None

    # ──────────────────────────────────────────────────────────────────────
    # should_create_sibling_vs_child
    # ──────────────────────────────────────────────────────────────────────

    def should_create_sibling_vs_child(
        self,
        new_embedding: Optional[list[float]],
        existing_node: dict,
        threshold: float = 0.6,
        new_node_type: str = "INSTANCE",
    ) -> str:
        """
        Decide depth placement during CLUSTER/INSTANCE placement.
        Enforces strict hierarchy: lower tiers MUST be children of higher tiers.
        """
        existing_type = existing_node.get("node_type", "INSTANCE")
        tier_map = {"ANCHOR": 0, "DOMAIN": 1, "CLUSTER": 2, "INSTANCE": 3}
        
        new_tier = tier_map.get(new_node_type, 3)
        existing_tier = tier_map.get(existing_type, 3)
        
        # Strict hierarchy rule: if candidate is a lower tier (higher number) 
        # than the existing node, it MUST become a child.
        if new_tier > existing_tier:
            return "child"

        if new_embedding is None:
            return "child"

        existing_emb = existing_node.get("embedding")
        sim = _cosine_sim(new_embedding, existing_emb)

        if sim > threshold:
            return "child"
        else:
            return "sibling"

    # ──────────────────────────────────────────────────────────────────────
    # run_placement — Full Pipeline
    # ──────────────────────────────────────────────────────────────────────

    async def run_placement(
        self,
        candidate_content: str,
        candidate_type: str,
        candidate_embedding: Optional[list[float]],
        all_nodes: list[dict],
        graph: MemoryGraph,
        db: AsyncSession,
        user_id: str,
    ) -> PlacementResult:
        """
        Orchestrate the full placement pipeline:
        1. find_parent (with reclassification and domain creation fallbacks)
        2. sibling_vs_child depth decision
        3. find_lateral_links
        4. Return PlacementResult
        """
        result = PlacementResult()
        ctype = candidate_type if isinstance(candidate_type, str) else candidate_type.value

        # ── Step 1: Find parent ──────────────────────────────────────────
        parent_id, confidence = self.find_parent(
            candidate_embedding, ctype, all_nodes, graph
        )

        # Handle ANCHOR — immediate return
        if ctype == "ANCHOR":
            result.parent_id = None
            result.tier_level = 0
            result.placement_confidence = 1.0
            return result

        # Handle CLUSTER that needs a new DOMAIN
        if parent_id == "__CREATE_DOMAIN__":
            anchor_nodes = [n for n in all_nodes if n.get("node_type") == "ANCHOR" and not n.get("is_archived")]
            new_domain_id = await self.create_domain_node(
                candidate_content, candidate_embedding, anchor_nodes, db, graph, user_id
            )
            if new_domain_id:
                result.parent_id = new_domain_id
                result.tier_level = 2  # CLUSTER under new DOMAIN
                result.created_new_domain = True
                result.placement_confidence = max(0.3, confidence)
            else:
                # Fallback: no parent
                result.parent_id = None
                result.tier_level = 2
                result.placement_confidence = 0.1
            # Find lateral links for the new node (use a temp ID)
            temp_id = str(uuid.uuid4())
            result.lateral_links = self.find_lateral_links(
                candidate_embedding, temp_id, all_nodes
            )
            return result

        # Handle INSTANCE reclassified as CLUSTER
        if parent_id == "__RECLASSIFY_CLUSTER__":
            logger.info("INSTANCE reclassified as CLUSTER — re-running placement")
            return await self.run_placement(
                candidate_content, "CLUSTER", candidate_embedding,
                all_nodes, graph, db, user_id
            )

        # ── Step 2: Sibling vs child (for CLUSTER placement) ─────────────
        if parent_id and ctype == "CLUSTER":
            node_map = {n["id"]: n for n in all_nodes}
            parent_node = node_map.get(parent_id)
            if parent_node:
                depth_decision = self.should_create_sibling_vs_child(
                    candidate_embedding, parent_node, new_node_type=ctype
                )
                if depth_decision == "sibling":
                    # Go to parent's parent instead
                    grandparent_id = parent_node.get("parent_id")
                    if grandparent_id:
                        parent_id = grandparent_id
                        # Tier stays at parent's tier (sibling level)
                        result.tier_level = parent_node.get("tier_level", 2)
                    else:
                        result.tier_level = parent_node.get("tier_level", 2)
                else:
                    # Child: tier = parent tier + 1
                    result.tier_level = parent_node.get("tier_level", 1) + 1
            else:
                result.tier_level = 2
        elif parent_id:
            # For DOMAIN and INSTANCE: tier = parent tier + 1
            node_map = {n["id"]: n for n in all_nodes}
            parent_node = node_map.get(parent_id)
            if parent_node:
                result.tier_level = parent_node.get("tier_level", 0) + 1
            else:
                tier_defaults = {"DOMAIN": 1, "INSTANCE": 3}
                result.tier_level = tier_defaults.get(ctype, 3)
        else:
            tier_defaults = {"ANCHOR": 0, "DOMAIN": 1, "CLUSTER": 2, "INSTANCE": 3}
            result.tier_level = tier_defaults.get(ctype, 3)

        result.parent_id = parent_id
        result.placement_confidence = max(0.0, confidence)

        # ── Step 3: Find lateral links ───────────────────────────────────
        temp_id = str(uuid.uuid4())
        result.lateral_links = self.find_lateral_links(
            candidate_embedding, temp_id, all_nodes
        )

        return result
