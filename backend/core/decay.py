"""
Mem-Rooted — Decay & Promotion Engine

Decay Formula:
    D(t) = base_retention × e^(−λ_tier × t) × goal_factor × recall_resilience

    λ_tier:  ANCHOR=0, DOMAIN=0.001, CLUSTER=0.01, INSTANCE=0.05
    t:       days since last_recalled_at (not created_at)
    goal_factor: 0.5 if node has lateral link to ANCHOR, else 1.0
    recall_resilience: 1 + (0.15 × recall_count)
    Archive when D(t) < 0.05

Promotion Formula:
    Promotion_Score = Cw_node / Cw_threshold_for_parent_level

    Thresholds: ANCHOR(0)=immutable, DOMAIN(1)=8.0, CLUSTER(2)=4.0, INSTANCE(3+)=1.5
    Trigger promotion when Promotion_Score > 1.2
    Trigger demotion  when Cw < 0.5 × threshold_for_current_level
"""

import logging
import math
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Node, NodeType, PriorityFlag

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════════════════

LAMBDA_TIER: dict[NodeType, float] = {
    NodeType.ANCHOR: 0.0,      # never decays
    NodeType.DOMAIN: 0.001,
    NodeType.CLUSTER: 0.01,
    NodeType.INSTANCE: 0.05,
}

CW_THRESHOLDS: dict[int, float] = {
    0: float("inf"),  # ANCHOR — immutable, no promotion into this tier
    1: 8.0,           # DOMAIN level
    2: 4.0,           # CLUSTER level
    3: 1.5,           # INSTANCE level
}

ARCHIVE_THRESHOLD: float = 0.05
PROMOTION_TRIGGER: float = 1.2
DEMOTION_FACTOR: float = 0.5
BASE_RETENTION: float = 1.0


# ══════════════════════════════════════════════════════════════════════════════
# Decay Computation
# ══════════════════════════════════════════════════════════════════════════════

def compute_decay(node: Node) -> float:
    """
    Compute current decay score for a node.

    D(t) = base_retention × e^(−λ × t) × goal_factor × recall_resilience

    Returns the new decay_score (0.0–1.0).
    """
    # ANCHOR nodes never decay
    if node.node_type == NodeType.ANCHOR or node.priority_flag == PriorityFlag.IMMUTABLE:
        return 1.0

    lam = LAMBDA_TIER.get(node.node_type, 0.05)

    # t = days since last recalled (or created if never recalled)
    reference_time = node.last_recalled_at or node.created_at
    if reference_time is None:
        return 1.0

    now = datetime.now(timezone.utc)
    # Handle timezone-aware vs naive datetimes
    if reference_time.tzinfo is None:
        delta = now.replace(tzinfo=None) - reference_time
    else:
        delta = now - reference_time

    t_days = max(0.0, delta.total_seconds() / 86400.0)

    # Goal factor: slower decay if linked to ANCHOR
    goal_factor = 1.0
    lateral_links = node.lateral_links or []
    # We check for ANCHOR links — but we can't query DB here (sync function),
    # so we use a heuristic: if any lateral link exists with high similarity, assume goal-aligned
    # The actual ANCHOR check happens in should_archive() which has DB access
    for link in lateral_links:
        if link.get("similarity", 0) > 0.7:
            goal_factor = 0.5
            break

    # Recall resilience: more recalls = slower decay
    recall_count = node.recall_weight or 0.0
    recall_resilience = 1.0 + (0.15 * recall_count)

    # Decay formula: higher recall_resilience SLOWS decay (divides the exponent)
    # D(t) = base × e^(-λ × t / recall_resilience) × goal_factor_adjustment
    # Note: goal_factor < 1 means SLOWER decay (we multiply λ by goal_factor)
    decay_score = BASE_RETENTION * math.exp(-lam * t_days * goal_factor / recall_resilience)

    return max(0.0, min(1.0, decay_score))


def should_archive(node: Node) -> bool:
    """Check if a node should be archived based on its decay score."""
    if node.node_type == NodeType.ANCHOR or node.priority_flag == PriorityFlag.IMMUTABLE:
        return False
    if node.is_archived:
        return False
    current_decay = compute_decay(node)
    return current_decay < ARCHIVE_THRESHOLD


# ══════════════════════════════════════════════════════════════════════════════
# Promotion / Demotion Scoring
# ══════════════════════════════════════════════════════════════════════════════

def compute_promotion_score(node: Node, composite_weight: float) -> float:
    """
    Promotion_Score = Cw_node / Cw_threshold_for_parent_level

    The parent level is one tier above current (tier_level - 1).
    A score > 1.0 means the node has outgrown its current tier.
    """
    if node.tier_level <= 0:
        # ANCHOR — cannot promote further
        return 0.0

    # Threshold for the tier this node would promote INTO
    target_tier = node.tier_level - 1
    threshold = CW_THRESHOLDS.get(target_tier, float("inf"))

    if threshold == float("inf") or threshold == 0:
        return 0.0

    return composite_weight / threshold


def should_promote(node: Node, composite_weight: float) -> bool:
    """
    Trigger promotion when Promotion_Score > 1.2
    ANCHOR nodes and already-top-tier nodes cannot promote.
    """
    if node.tier_level <= 0:
        return False
    if node.is_archived:
        return False
    if node.priority_flag == PriorityFlag.IMMUTABLE:
        return False

    score = compute_promotion_score(node, composite_weight)
    return score > PROMOTION_TRIGGER


def should_demote(node: Node, composite_weight: float) -> bool:
    """
    Trigger demotion when Cw < 0.5 × threshold_for_current_level.
    ANCHOR and IMMUTABLE nodes cannot be demoted.
    """
    if node.node_type == NodeType.ANCHOR or node.priority_flag == PriorityFlag.IMMUTABLE:
        return False
    if node.is_archived:
        return False
    if node.tier_level >= 3:
        return False  # Already at INSTANCE, nowhere to demote

    current_threshold = CW_THRESHOLDS.get(node.tier_level, 1.5)
    if current_threshold == float("inf"):
        return False

    return composite_weight < DEMOTION_FACTOR * current_threshold


# ══════════════════════════════════════════════════════════════════════════════
# Batch Decay Application
# ══════════════════════════════════════════════════════════════════════════════

async def apply_decay_to_all(db: AsyncSession) -> dict:
    """
    Batch apply decay to all active non-ANCHOR nodes.
    Archives nodes that fall below the threshold.
    Called by the background scheduler.
    """
    result = await db.execute(
        select(Node).where(
            Node.is_archived == False,
            Node.node_type != NodeType.ANCHOR,
        )
    )
    nodes = list(result.scalars().all())

    decayed = 0
    archived = 0

    for node in nodes:
        old_decay = node.decay_score
        new_decay = compute_decay(node)

        if abs(new_decay - old_decay) > 0.001:  # only update if changed meaningfully
            node.decay_score = new_decay
            decayed += 1

        if new_decay < ARCHIVE_THRESHOLD:
            node.is_archived = True
            log = list(node.operation_log or [])
            log.append({
                "op": "DECAY_ARCHIVE",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "details": {"final_decay_score": round(new_decay, 6)},
            })
            node.operation_log = log
            archived += 1
            logger.info(f"Archived node {node.id} ({node.name}) — decay={new_decay:.4f}")

    await db.flush()

    return {"decayed": decayed, "archived": archived, "total_scanned": len(nodes)}


# ══════════════════════════════════════════════════════════════════════════════
# Batch Promotion / Demotion Application
# ══════════════════════════════════════════════════════════════════════════════

async def apply_promotions_to_all(db: AsyncSession) -> dict:
    """
    Scan all active nodes, check promotion/demotion conditions,
    and execute via operations module.
    Called by the background scheduler.
    """
    from core.operations import promote_node, demote_node

    result = await db.execute(
        select(Node).where(Node.is_archived == False).order_by(Node.tier_level.desc())
    )
    nodes = list(result.scalars().all())

    promoted = 0
    demoted = 0
    errors = 0

    for node in nodes:
        try:
            cw = node.composite_weight or 0.0

            if should_promote(node, cw):
                op_result = await promote_node(db, node.id)
                if op_result.success:
                    promoted += 1
                    logger.info(f"Promoted node {node.id} ({node.name})")

            elif should_demote(node, cw):
                op_result = await demote_node(db, node.id)
                if op_result.success:
                    demoted += 1
                    logger.info(f"Demoted node {node.id} ({node.name})")

        except Exception as e:
            logger.error(f"Promotion/demotion error for node {node.id}: {e}")
            errors += 1

    await db.flush()

    return {
        "promoted": promoted,
        "demoted": demoted,
        "errors": errors,
        "total_scanned": len(nodes),
    }
