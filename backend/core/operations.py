"""
Mem-Rooted — Nine Memory Operations

Each operation takes a candidate/node and current state, returns an OperationResult.
Operations: ADD, UPDATE, NOOP, ARCHIVE, PROMOTE, DEMOTE, MERGE, LATERAL_LINK, SPLIT.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Node, NodeType, PriorityFlag


# ══════════════════════════════════════════════════════════════════════════════
# Result Model
# ══════════════════════════════════════════════════════════════════════════════

class OperationResult(BaseModel):
    """Result of any memory operation."""
    operation_type: str
    node_id: Optional[str] = None
    message: str = ""
    success: bool = True


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log_entry(op: str, details: Optional[dict] = None) -> dict:
    return {"op": op, "timestamp": _now().isoformat(), "details": details or {}}


def _cosine_similarity(a: Optional[list], b: Optional[list]) -> float:
    """Cosine similarity between two embedding vectors."""
    if a is None or b is None:
        return 0.0
    va, vb = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    norm_a, norm_b = np.linalg.norm(va), np.linalg.norm(vb)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


# ══════════════════════════════════════════════════════════════════════════════
# 1. ADD NODE
# ══════════════════════════════════════════════════════════════════════════════

async def add_node(
    db: AsyncSession,
    name: str,
    content: str,
    node_type: NodeType,
    parent_id: Optional[uuid.UUID],
    embedding: Optional[list[float]],
    user_id: str,
    session_id: Optional[uuid.UUID] = None,
    priority: PriorityFlag = PriorityFlag.MEDIUM,
) -> OperationResult:
    """Create a new node in the hierarchy with initial weights."""
    tier_map = {
        NodeType.ANCHOR: 0,
        NodeType.DOMAIN: 1,
        NodeType.CLUSTER: 2,
        NodeType.INSTANCE: 3,
    }

    # Compute initial semantic weight against parent
    semantic_weight = 1.0
    if parent_id and embedding:
        result = await db.execute(select(Node.embedding).where(Node.id == parent_id))
        parent_emb = result.scalar_one_or_none()
        if parent_emb is not None:
            semantic_weight = _cosine_similarity(embedding, list(parent_emb))

    # Set priority for ANCHOR nodes
    if node_type == NodeType.ANCHOR:
        priority = PriorityFlag.IMMUTABLE

    node = Node(
        name=name,
        content=content,
        node_type=node_type,
        parent_id=parent_id,
        tier_level=tier_map.get(node_type, 3),
        physical_weight=0.0,
        recall_weight=0.0,
        semantic_weight=semantic_weight,
        composite_weight=0.2 * semantic_weight,  # initial Cw
        decay_score=1.0,
        promotion_score=0.0,
        lateral_links=[],
        embedding=embedding,
        source_session_id=session_id,
        user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
        priority_flag=priority,
        operation_log=[_log_entry("ADD", {"initial_type": node_type.value})],
        is_archived=False,
    )
    db.add(node)
    await db.flush()

    return OperationResult(
        operation_type="ADD",
        node_id=str(node.id),
        message=f"Created {node_type.value} node: {name}",
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2. UPDATE NODE
# ══════════════════════════════════════════════════════════════════════════════

async def update_node(
    db: AsyncSession,
    node_id: uuid.UUID,
    new_content: str,
) -> OperationResult:
    """Update node content, preserving old content as version history."""
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        return OperationResult(operation_type="UPDATE", success=False, message="Node not found")

    if node.node_type == NodeType.ANCHOR and node.priority_flag == PriorityFlag.IMMUTABLE:
        log = list(node.operation_log or [])
        log.append(_log_entry("BLOCKED_UPDATE", {
            "attempted_new_content": new_content,
            "reason": "IMMUTABLE anchor protection"
        }))
        node.operation_log = log
        node.recall_weight = (node.recall_weight or 0.0) + 1.0
        node.last_recalled_at = _now()
        await db.flush()
        return OperationResult(
            operation_type="BLOCKED_UPDATE",
            success=False,
            message="Cannot mutate IMMUTABLE ANCHOR node content. Attempted change logged to history."
        )

    old_content = node.content
    log = list(node.operation_log or [])
    log.append(_log_entry("UPDATE", {
        "old_content": old_content,
        "new_content": new_content,
    }))

    node.content = new_content
    node.operation_log = log
    node.last_recalled_at = _now()
    await db.flush()

    return OperationResult(
        operation_type="UPDATE",
        node_id=str(node_id),
        message=f"Updated node, preserved version history (v{len([l for l in log if l.get('op') == 'UPDATE'])})",
    )


# ══════════════════════════════════════════════════════════════════════════════
# 3. NOOP
# ══════════════════════════════════════════════════════════════════════════════

async def noop(
    db: AsyncSession,
    node_id: uuid.UUID,
) -> OperationResult:
    """Increment recall weight and update last_recalled_at without storing new data."""
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        return OperationResult(operation_type="NOOP", success=False, message="Node not found")

    node.recall_weight = (node.recall_weight or 0.0) + 1.0
    node.last_recalled_at = _now()
    await db.flush()

    return OperationResult(
        operation_type="NOOP",
        node_id=str(node_id),
        message=f"Recall weight incremented to {node.recall_weight:.1f}",
    )


# ══════════════════════════════════════════════════════════════════════════════
# 4. ARCHIVE NODE
# ══════════════════════════════════════════════════════════════════════════════

async def archive_node(
    db: AsyncSession,
    node_id: uuid.UUID,
) -> OperationResult:
    """Soft-archive a node. Never hard-deletes."""
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        return OperationResult(operation_type="ARCHIVE", success=False, message="Node not found")

    if node.priority_flag == PriorityFlag.IMMUTABLE:
        return OperationResult(
            operation_type="ARCHIVE", node_id=str(node_id),
            success=False, message="Cannot archive IMMUTABLE node",
        )

    node.is_archived = True
    log = list(node.operation_log or [])
    log.append(_log_entry("ARCHIVE", {"decay_score_at_archive": node.decay_score}))
    node.operation_log = log
    await db.flush()

    return OperationResult(
        operation_type="ARCHIVE",
        node_id=str(node_id),
        message="Node archived",
    )


# ══════════════════════════════════════════════════════════════════════════════
# 5. PROMOTE NODE
# ══════════════════════════════════════════════════════════════════════════════

async def promote_node(
    db: AsyncSession,
    node_id: uuid.UUID,
) -> OperationResult:
    """Promote node up one tier: INSTANCE→CLUSTER, CLUSTER→DOMAIN, DOMAIN→ANCHOR."""
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        return OperationResult(operation_type="PROMOTE", success=False, message="Node not found")

    if node.tier_level <= 0:
        return OperationResult(
            operation_type="PROMOTE", node_id=str(node_id),
            success=False, message="Already at ANCHOR tier, cannot promote further",
        )

    old_tier = node.tier_level
    tier_to_type = {0: NodeType.ANCHOR, 1: NodeType.DOMAIN, 2: NodeType.CLUSTER, 3: NodeType.INSTANCE}

    # Move to grandparent
    grandparent_id = None
    if node.parent_id:
        parent_result = await db.execute(select(Node.parent_id).where(Node.id == node.parent_id))
        grandparent_id = parent_result.scalar_one_or_none()

    new_tier = old_tier - 1
    node.tier_level = new_tier
    node.node_type = tier_to_type.get(new_tier, NodeType.INSTANCE)
    node.parent_id = grandparent_id

    # Recalculate semantic weight against new parent
    if grandparent_id and node.embedding:
        gp_result = await db.execute(select(Node.embedding).where(Node.id == grandparent_id))
        gp_emb = gp_result.scalar_one_or_none()
        if gp_emb is not None:
            node.semantic_weight = _cosine_similarity(list(node.embedding), list(gp_emb))
    elif grandparent_id is None:
        node.semantic_weight = 1.0  # No parent (became ANCHOR-adjacent)

    if new_tier == 0:
        node.priority_flag = PriorityFlag.IMMUTABLE

    log = list(node.operation_log or [])
    log.append(_log_entry("PROMOTE", {"from_tier": old_tier, "to_tier": new_tier}))
    node.operation_log = log
    await db.flush()

    return OperationResult(
        operation_type="PROMOTE",
        node_id=str(node_id),
        message=f"Promoted from tier {old_tier} to tier {new_tier} ({node.node_type.value})",
    )


# ══════════════════════════════════════════════════════════════════════════════
# 6. DEMOTE NODE
# ══════════════════════════════════════════════════════════════════════════════

async def demote_node(
    db: AsyncSession,
    node_id: uuid.UUID,
) -> OperationResult:
    """Demote node down one tier. New parent = sibling with highest composite weight."""
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        return OperationResult(operation_type="DEMOTE", success=False, message="Node not found")

    if node.priority_flag == PriorityFlag.IMMUTABLE:
        return OperationResult(
            operation_type="DEMOTE", node_id=str(node_id),
            success=False, message="Cannot demote IMMUTABLE node",
        )

    if node.tier_level >= 3:
        return OperationResult(
            operation_type="DEMOTE", node_id=str(node_id),
            success=False, message="Already at INSTANCE tier, cannot demote further",
        )

    old_tier = node.tier_level
    tier_to_type = {0: NodeType.ANCHOR, 1: NodeType.DOMAIN, 2: NodeType.CLUSTER, 3: NodeType.INSTANCE}

    # Find sibling with highest composite weight to become new parent
    siblings_result = await db.execute(
        select(Node)
        .where(Node.parent_id == node.parent_id, Node.id != node_id, Node.is_archived == False)
        .order_by(Node.composite_weight.desc())
        .limit(1)
    )
    best_sibling = siblings_result.scalar_one_or_none()

    new_tier = old_tier + 1
    node.tier_level = new_tier
    node.node_type = tier_to_type.get(new_tier, NodeType.INSTANCE)

    if best_sibling:
        node.parent_id = best_sibling.id
        if node.embedding and best_sibling.embedding:
            node.semantic_weight = _cosine_similarity(list(node.embedding), list(best_sibling.embedding))
    # If no sibling found, keep current parent

    log = list(node.operation_log or [])
    log.append(_log_entry("DEMOTE", {
        "from_tier": old_tier, "to_tier": new_tier,
        "new_parent": str(best_sibling.id) if best_sibling else None,
    }))
    node.operation_log = log
    await db.flush()

    return OperationResult(
        operation_type="DEMOTE",
        node_id=str(node_id),
        message=f"Demoted from tier {old_tier} to tier {new_tier} ({node.node_type.value})",
    )


# ══════════════════════════════════════════════════════════════════════════════
# 7. MERGE NODES
# ══════════════════════════════════════════════════════════════════════════════

async def merge_nodes(
    db: AsyncSession,
    node_id_a: uuid.UUID,
    node_id_b: uuid.UUID,
) -> OperationResult:
    """Merge two nodes into one. Content concatenated, children pooled, weights summed."""
    res_a = await db.execute(select(Node).where(Node.id == node_id_a))
    res_b = await db.execute(select(Node).where(Node.id == node_id_b))
    node_a = res_a.scalar_one_or_none()
    node_b = res_b.scalar_one_or_none()

    if not node_a or not node_b:
        return OperationResult(operation_type="MERGE", success=False, message="One or both nodes not found")

    # Distill content
    node_a.content = f"{node_a.content}\n---\n{node_b.content}"
    node_a.name = f"{node_a.name} + {node_b.name}"

    # Sum weights
    node_a.physical_weight += node_b.physical_weight
    node_a.recall_weight += node_b.recall_weight
    node_a.composite_weight += node_b.composite_weight

    # Merge lateral links (deduplicate)
    existing_targets = {link.get("target_id") for link in (node_a.lateral_links or [])}
    for link in (node_b.lateral_links or []):
        if link.get("target_id") not in existing_targets and link.get("target_id") != str(node_id_a):
            node_a.lateral_links = list(node_a.lateral_links or []) + [link]

    # Average embeddings
    if node_a.embedding and node_b.embedding:
        avg = (np.array(list(node_a.embedding)) + np.array(list(node_b.embedding))) / 2.0
        avg = avg / (np.linalg.norm(avg) + 1e-10)  # re-normalize
        node_a.embedding = avg.tolist()

    # Reparent node_b's children under node_a
    await db.execute(
        update(Node).where(Node.parent_id == node_id_b).values(parent_id=node_id_a)
    )

    # Archive node_b
    node_b.is_archived = True
    log_b = list(node_b.operation_log or [])
    log_b.append(_log_entry("MERGE", {"merged_into": str(node_id_a)}))
    node_b.operation_log = log_b

    # Log on surviving node
    log_a = list(node_a.operation_log or [])
    log_a.append(_log_entry("MERGE", {"absorbed": str(node_id_b)}))
    node_a.operation_log = log_a

    await db.flush()

    return OperationResult(
        operation_type="MERGE",
        node_id=str(node_id_a),
        message=f"Merged {node_id_b} into {node_id_a}",
    )


# ══════════════════════════════════════════════════════════════════════════════
# 8. CREATE LATERAL LINK
# ══════════════════════════════════════════════════════════════════════════════

async def create_lateral_link(
    db: AsyncSession,
    node_id_a: uuid.UUID,
    node_id_b: uuid.UUID,
    link_strength: float,
) -> OperationResult:
    """Create a bidirectional lateral link between two nodes."""
    res_a = await db.execute(select(Node).where(Node.id == node_id_a))
    res_b = await db.execute(select(Node).where(Node.id == node_id_b))
    node_a = res_a.scalar_one_or_none()
    node_b = res_b.scalar_one_or_none()

    if not node_a or not node_b:
        return OperationResult(operation_type="LATERAL_LINK", success=False, message="One or both nodes not found")

    now_iso = _now().isoformat()
    link_a_to_b = {"target_id": str(node_id_b), "similarity": link_strength, "created_at": now_iso}
    link_b_to_a = {"target_id": str(node_id_a), "similarity": link_strength, "created_at": now_iso}

    # Append to node_a (avoid duplicates)
    links_a = list(node_a.lateral_links or [])
    if not any(l.get("target_id") == str(node_id_b) for l in links_a):
        links_a.append(link_a_to_b)
        node_a.lateral_links = links_a

    # Append to node_b
    links_b = list(node_b.lateral_links or [])
    if not any(l.get("target_id") == str(node_id_a) for l in links_b):
        links_b.append(link_b_to_a)
        node_b.lateral_links = links_b

    await db.flush()

    return OperationResult(
        operation_type="LATERAL_LINK",
        node_id=str(node_id_a),
        message=f"Lateral link created (strength={link_strength:.3f})",
    )


# ══════════════════════════════════════════════════════════════════════════════
# 9. SPLIT NODE
# ══════════════════════════════════════════════════════════════════════════════

async def split_node(
    db: AsyncSession,
    node_id: uuid.UUID,
) -> OperationResult:
    """
    Split a node into two siblings by dividing children via semantic similarity.
    Uses the two most dissimilar children as seeds, then assigns others by proximity.
    """
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        return OperationResult(operation_type="SPLIT", success=False, message="Node not found")

    # Get children with embeddings
    children_result = await db.execute(
        select(Node).where(Node.parent_id == node_id, Node.is_archived == False)
    )
    children = list(children_result.scalars().all())

    if len(children) < 2:
        return OperationResult(
            operation_type="SPLIT", node_id=str(node_id),
            success=False, message="Need at least 2 children to split",
        )

    # Find two most dissimilar children as seeds
    children_with_emb = [(c, list(c.embedding)) for c in children if c.embedding is not None]
    if len(children_with_emb) < 2:
        # Fallback: split by index if no embeddings
        mid = len(children) // 2
        group_a, group_b = children[:mid], children[mid:]
    else:
        min_sim = float("inf")
        seed_a_idx, seed_b_idx = 0, 1
        for i in range(len(children_with_emb)):
            for j in range(i + 1, len(children_with_emb)):
                sim = _cosine_similarity(children_with_emb[i][1], children_with_emb[j][1])
                if sim < min_sim:
                    min_sim = sim
                    seed_a_idx, seed_b_idx = i, j

        seed_a_emb = children_with_emb[seed_a_idx][1]
        seed_b_emb = children_with_emb[seed_b_idx][1]

        group_a, group_b = [], []
        for child in children:
            if child.embedding is not None:
                sim_a = _cosine_similarity(list(child.embedding), seed_a_emb)
                sim_b = _cosine_similarity(list(child.embedding), seed_b_emb)
                if sim_a >= sim_b:
                    group_a.append(child)
                else:
                    group_b.append(child)
            else:
                group_a.append(child)  # default group for missing embeddings

    # Create two new sibling nodes
    content_parts = node.content.split("\n---\n") if "\n---\n" in node.content else [node.content, node.content]
    half = len(node.content) // 2

    sibling_a = Node(
        name=f"{node.name} (A)",
        content=node.content[:half] if len(content_parts) < 2 else content_parts[0],
        node_type=node.node_type,
        parent_id=node.parent_id,
        tier_level=node.tier_level,
        physical_weight=float(len(group_a)),
        recall_weight=node.recall_weight / 2.0,
        semantic_weight=node.semantic_weight,
        composite_weight=node.composite_weight / 2.0,
        decay_score=node.decay_score,
        promotion_score=0.0,
        lateral_links=[],
        embedding=node.embedding,  # inherit parent embedding initially
        source_session_id=node.source_session_id,
        user_id=node.user_id,
        priority_flag=node.priority_flag,
        operation_log=[_log_entry("SPLIT", {"origin": str(node_id), "group": "A"})],
        is_archived=False,
    )
    sibling_b = Node(
        name=f"{node.name} (B)",
        content=node.content[half:] if len(content_parts) < 2 else content_parts[-1],
        node_type=node.node_type,
        parent_id=node.parent_id,
        tier_level=node.tier_level,
        physical_weight=float(len(group_b)),
        recall_weight=node.recall_weight / 2.0,
        semantic_weight=node.semantic_weight,
        composite_weight=node.composite_weight / 2.0,
        decay_score=node.decay_score,
        promotion_score=0.0,
        lateral_links=[],
        embedding=node.embedding,
        source_session_id=node.source_session_id,
        user_id=node.user_id,
        priority_flag=node.priority_flag,
        operation_log=[_log_entry("SPLIT", {"origin": str(node_id), "group": "B"})],
        is_archived=False,
    )
    db.add(sibling_a)
    db.add(sibling_b)
    await db.flush()

    # Reparent children
    for child in group_a:
        child.parent_id = sibling_a.id
    for child in group_b:
        child.parent_id = sibling_b.id

    # Archive original node
    node.is_archived = True
    log = list(node.operation_log or [])
    log.append(_log_entry("SPLIT", {"into": [str(sibling_a.id), str(sibling_b.id)]}))
    node.operation_log = log

    await db.flush()

    return OperationResult(
        operation_type="SPLIT",
        node_id=str(node_id),
        message=f"Split into {sibling_a.id} ({len(group_a)} children) and {sibling_b.id} ({len(group_b)} children)",
    )
