"""
Mem-Rooted — Composite Weight System

Three weight components combine into a single Composite Weight (Cw)
that determines hierarchy position and triggers promotion/demotion.

    Physical Weight (Pw) = total descendant count
    Recall Weight (Rw)   = (direct_recalls + 0.4 × descendant_recalls) × goal_alignment
    Semantic Weight (Sw) = cosine_similarity(node_emb, parent_emb)
    Composite Weight (Cw) = 0.3×Pw + 0.5×Rw + 0.2×Sw
"""

import logging
from typing import Optional

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Node, NodeType

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def cosine_similarity(a: Optional[list], b: Optional[list]) -> float:
    """Cosine similarity between two embedding vectors via numpy."""
    if a is None or b is None:
        return 0.0
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


# ══════════════════════════════════════════════════════════════════════════════
# Physical Weight
# ══════════════════════════════════════════════════════════════════════════════

async def compute_physical_weight(node_id, db: AsyncSession) -> float:
    """
    Recursive descendant count from DB.
    Uses a recursive CTE for efficient counting across all depth levels.
    """
    from sqlalchemy import text

    query = text("""
        WITH RECURSIVE descendants AS (
            SELECT id FROM nodes WHERE parent_id = :nid AND is_archived = false
            UNION ALL
            SELECT n.id FROM nodes n
            INNER JOIN descendants d ON n.parent_id = d.id
            WHERE n.is_archived = false
        )
        SELECT COUNT(*) FROM descendants;
    """)

    result = await db.execute(query, {"nid": str(node_id)})
    count = result.scalar() or 0
    return float(count)


# ══════════════════════════════════════════════════════════════════════════════
# Recall Weight
# ══════════════════════════════════════════════════════════════════════════════

async def compute_recall_weight(node_id, db: AsyncSession) -> float:
    """
    Recall Weight = (direct_recall_count + 0.4 × descendant_recall_sum) × goal_alignment_multiplier

    goal_alignment_multiplier = 1.5 if node has a lateral link to any ANCHOR node, else 1.0
    """
    # Get this node's recall weight (direct recall count)
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        return 0.0

    direct_recall = node.recall_weight or 0.0

    # Sum descendant recall weights using recursive CTE
    from sqlalchemy import text
    desc_query = text("""
        WITH RECURSIVE descendants AS (
            SELECT id FROM nodes WHERE parent_id = :nid AND is_archived = false
            UNION ALL
            SELECT n.id FROM nodes n
            INNER JOIN descendants d ON n.parent_id = d.id
            WHERE n.is_archived = false
        )
        SELECT COALESCE(SUM(n.recall_weight), 0)
        FROM nodes n
        INNER JOIN descendants d ON n.id = d.id;
    """)
    desc_result = await db.execute(desc_query, {"nid": str(node_id)})
    descendant_recall_sum = float(desc_result.scalar() or 0.0)

    # Check goal alignment — does this node have a lateral link to any ANCHOR?
    goal_alignment_multiplier = 1.0
    lateral_links = node.lateral_links or []
    if lateral_links:
        linked_ids = [link.get("target_id") for link in lateral_links if link.get("target_id")]
        if linked_ids:
            anchor_check = await db.execute(
                select(func.count())
                .where(Node.id.in_(linked_ids), Node.node_type == NodeType.ANCHOR)
            )
            anchor_count = anchor_check.scalar() or 0
            if anchor_count > 0:
                goal_alignment_multiplier = 1.5

    raw_rw = (direct_recall + 0.4 * descendant_recall_sum) * goal_alignment_multiplier
    return raw_rw


# ══════════════════════════════════════════════════════════════════════════════
# Semantic Weight
# ══════════════════════════════════════════════════════════════════════════════

async def compute_semantic_weight(
    node_embedding: Optional[list],
    parent_embedding: Optional[list],
) -> float:
    """
    Cosine similarity between node and parent embeddings.
    If no parent (ANCHOR node): Sw = 1.0
    """
    if parent_embedding is None:
        return 1.0
    return cosine_similarity(node_embedding, parent_embedding)


# ══════════════════════════════════════════════════════════════════════════════
# Composite Weight
# ══════════════════════════════════════════════════════════════════════════════

async def compute_composite_weight(node_id, db: AsyncSession) -> float:
    """
    Composite Weight = (0.3 × Pw_normalized) + (0.5 × Rw_normalized) + (0.2 × Sw)

    Pw and Rw are normalized using log scaling to prevent large trees from dominating.
    """
    pw = await compute_physical_weight(node_id, db)
    rw = await compute_recall_weight(node_id, db)

    # Get node and parent embeddings for semantic weight
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        return 0.0

    parent_emb = None
    if node.parent_id:
        parent_result = await db.execute(select(Node.embedding).where(Node.id == node.parent_id))
        parent_emb_raw = parent_result.scalar_one_or_none()
        if parent_emb_raw is not None:
            parent_emb = list(parent_emb_raw)

    node_emb = list(node.embedding) if node.embedding is not None else None
    sw = await compute_semantic_weight(node_emb, parent_emb)

    # Normalize Pw and Rw with log scaling to keep them in reasonable range
    import math
    pw_norm = math.log1p(pw)    # log(1 + pw), maps 0→0, 10→2.4, 100→4.6
    rw_norm = math.log1p(rw)    # log(1 + rw)

    cw = (0.3 * pw_norm) + (0.5 * rw_norm) + (0.2 * sw)
    return round(cw, 6)


# ══════════════════════════════════════════════════════════════════════════════
# Batch Recomputation
# ══════════════════════════════════════════════════════════════════════════════

async def recompute_all_weights(db: AsyncSession) -> dict:
    """
    Batch recompute all weight components for every active (non-archived) node.
    Called by the background scheduler after structural changes.

    Returns stats dict with count of nodes processed.
    """
    result = await db.execute(
        select(Node).where(Node.is_archived == False).order_by(Node.tier_level.desc())
    )
    nodes = list(result.scalars().all())

    processed = 0
    errors = 0

    # Process bottom-up (INSTANCE first, then CLUSTER, DOMAIN, ANCHOR)
    # so that parent weights reflect updated children
    for node in nodes:
        try:
            pw = await compute_physical_weight(node.id, db)
            rw = await compute_recall_weight(node.id, db)

            parent_emb = None
            if node.parent_id:
                p_result = await db.execute(select(Node.embedding).where(Node.id == node.parent_id))
                p_emb_raw = p_result.scalar_one_or_none()
                if p_emb_raw is not None:
                    parent_emb = list(p_emb_raw)

            node_emb = list(node.embedding) if node.embedding is not None else None
            sw = await compute_semantic_weight(node_emb, parent_emb)

            import math
            pw_norm = math.log1p(pw)
            rw_norm = math.log1p(rw)
            cw = (0.3 * pw_norm) + (0.5 * rw_norm) + (0.2 * sw)

            node.physical_weight = pw
            node.recall_weight = rw if node.recall_weight == 0 else node.recall_weight  # preserve direct recalls
            node.semantic_weight = sw
            node.composite_weight = round(cw, 6)

            processed += 1
        except Exception as e:
            logger.error(f"Failed to recompute weights for node {node.id}: {e}")
            errors += 1

    await db.flush()

    return {
        "processed": processed,
        "errors": errors,
        "total": len(nodes),
    }
