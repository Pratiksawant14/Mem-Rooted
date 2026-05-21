"""
Mem-Rooted — Memory Inspection & Management API Routes

Dashboard endpoints for exploring the node network, viewing stats,
managing scheduler jobs, searching memories, and archiving nodes.
"""

import logging
import uuid
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.retrieval import HybridRetriever
from core.scheduler import SchedulerState
from db.connection import get_session
from db.models import Node, NodeType, PriorityFlag
from api.routes.auth import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _node_to_dict(node: Node, include_log: bool = False) -> dict:
    """Convert a Node ORM object to a JSON-serializable dict."""
    d = {
        "id": str(node.id),
        "name": node.name,
        "node_type": node.node_type.value,
        "tier_level": node.tier_level,
        "content": node.content,
        "parent_id": str(node.parent_id) if node.parent_id else None,
        "physical_weight": node.physical_weight,
        "recall_weight": node.recall_weight,
        "semantic_weight": node.semantic_weight,
        "composite_weight": node.composite_weight,
        "decay_score": node.decay_score,
        "promotion_score": node.promotion_score,
        "is_archived": node.is_archived,
        "priority_flag": node.priority_flag.value if node.priority_flag else None,
        "lateral_links": node.lateral_links or [],
        "created_at": node.created_at.isoformat() if node.created_at else None,
        "last_recalled_at": node.last_recalled_at.isoformat() if node.last_recalled_at else None,
        "source_session_id": str(node.source_session_id) if node.source_session_id else None,
    }
    if include_log:
        d["operation_log"] = node.operation_log or []
    return d


def _build_tree(nodes: list[Node]) -> list[dict]:
    """Build nested tree structure from flat node list. ANCHOR nodes at root."""
    node_map: dict[str, dict] = {}
    for n in nodes:
        d = _node_to_dict(n)
        d["children"] = []
        node_map[d["id"]] = d

    roots = []
    for nid, nd in node_map.items():
        pid = nd.get("parent_id")
        if pid and pid in node_map:
            node_map[pid]["children"].append(nd)
        else:
            roots.append(nd)

    # Sort roots by node_type priority (ANCHOR first)
    type_order = {"ANCHOR": 0, "DOMAIN": 1, "CLUSTER": 2, "INSTANCE": 3}
    roots.sort(key=lambda x: type_order.get(x.get("node_type", ""), 99))

    return roots


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/memory/tree
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/tree")
async def get_memory_tree(user_id: str = Depends(get_current_user_id)):
    """
    Full node tree as nested JSON.
    ANCHOR nodes at root, children nested recursively.
    """
    async with get_session() as db:
        result = await db.execute(
            select(Node).where(Node.is_archived == False, Node.user_id == uuid.UUID(user_id)).order_by(Node.tier_level.asc())
        )
        nodes = list(result.scalars().all())
        tree = _build_tree(nodes)
        return {"tree": tree, "total_nodes": len(nodes)}


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/memory/node/{node_id}
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/node/{node_id}")
async def get_node_detail(node_id: str, user_id: str = Depends(get_current_user_id)):
    """Full node details including complete operation_log history."""
    async with get_session() as db:
        result = await db.execute(select(Node).where(Node.id == uuid.UUID(node_id), Node.user_id == uuid.UUID(user_id)))
        node = result.scalar_one_or_none()

        if not node:
            raise HTTPException(status_code=404, detail="Node not found")

        detail = _node_to_dict(node, include_log=True)

        # Also fetch children summary
        children_result = await db.execute(
            select(Node).where(Node.parent_id == node.id, Node.is_archived == False)
        )
        children = children_result.scalars().all()
        detail["children"] = [
            {
                "id": str(c.id),
                "name": c.name,
                "node_type": c.node_type.value,
                "composite_weight": c.composite_weight,
                "decay_score": c.decay_score,
            }
            for c in children
        ]
        detail["children_count"] = len(children)

        # Fetch parent info
        if node.parent_id:
            parent_result = await db.execute(select(Node).where(Node.id == node.parent_id))
            parent = parent_result.scalar_one_or_none()
            if parent:
                detail["parent"] = {
                    "id": str(parent.id),
                    "name": parent.name,
                    "node_type": parent.node_type.value,
                }

        return detail


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/memory/stats
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/stats")
async def get_memory_stats(user_id: str = Depends(get_current_user_id)):
    """
    Aggregate statistics:
    - Total nodes by type
    - Average decay score by tier
    - Promotion/demotion counts from scheduler
    - Top 5 by composite weight
    - Top 5 by recall weight
    """
    async with get_session() as db:
        # Total nodes by type
        type_counts = {}
        for nt in NodeType:
            count_result = await db.execute(
                select(func.count()).where(Node.node_type == nt, Node.is_archived == False, Node.user_id == uuid.UUID(user_id))
            )
            type_counts[nt.value] = count_result.scalar() or 0

        # Archived count
        archived_result = await db.execute(
            select(func.count()).where(Node.is_archived == True, Node.user_id == uuid.UUID(user_id))
        )
        archived_count = archived_result.scalar() or 0

        # Average decay score by tier
        avg_decay_by_tier = {}
        for tier in range(4):
            avg_result = await db.execute(
                select(func.avg(Node.decay_score)).where(
                    Node.tier_level == tier, Node.is_archived == False, Node.user_id == uuid.UUID(user_id)
                )
            )
            avg = avg_result.scalar()
            tier_names = {0: "ANCHOR", 1: "DOMAIN", 2: "CLUSTER", 3: "INSTANCE"}
            avg_decay_by_tier[tier_names.get(tier, str(tier))] = round(float(avg), 4) if avg else None

        # Top 5 by composite weight
        top_cw_result = await db.execute(
            select(Node)
            .where(Node.is_archived == False, Node.user_id == uuid.UUID(user_id))
            .order_by(Node.composite_weight.desc())
            .limit(5)
        )
        top_by_weight = [
            {"id": str(n.id), "name": n.name, "node_type": n.node_type.value,
             "composite_weight": round(n.composite_weight or 0, 4)}
            for n in top_cw_result.scalars().all()
        ]

        # Top 5 by recall weight
        top_rw_result = await db.execute(
            select(Node)
            .where(Node.is_archived == False, Node.user_id == uuid.UUID(user_id))
            .order_by(Node.recall_weight.desc())
            .limit(5)
        )
        top_by_recall = [
            {"id": str(n.id), "name": n.name, "node_type": n.node_type.value,
             "recall_weight": round(n.recall_weight or 0, 4)}
            for n in top_rw_result.scalars().all()
        ]

        # Scheduler stats
        scheduler_state = SchedulerState()
        promo_job = scheduler_state.jobs.get("promotion_sweep", {})
        promo_details = promo_job.get("details", {})

        return {
            "nodes_by_type": type_counts,
            "total_active": sum(type_counts.values()),
            "total_archived": archived_count,
            "avg_decay_by_tier": avg_decay_by_tier,
            "promotions_total": promo_details.get("promoted", 0),
            "demotions_total": promo_details.get("demoted", 0),
            "top_by_composite_weight": top_by_weight,
            "top_by_recall_weight": top_by_recall,
        }


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/memory/scheduler/status
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/scheduler/status")
async def get_scheduler_status():
    """Returns scheduler state: running, job stats, last run times."""
    state = SchedulerState()
    return state.get_status()


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/memory/scheduler/trigger/{job_name}
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/scheduler/trigger/{job_name}")
async def trigger_scheduler_job(job_name: str, request: Request):
    """
    Manually trigger a scheduler job.
    Valid names: decay, promotion, merge, split, lateral
    """
    job_map = {
        "decay": "decay_sweep",
        "promotion": "promotion_sweep",
        "merge": "merge_sweep",
        "split": "split_sweep",
        "lateral": "lateral_link_refresh",
    }

    scheduler_id = job_map.get(job_name)
    if not scheduler_id:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid job name '{job_name}'. Valid: {list(job_map.keys())}",
        )

    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not available")

    triggered = scheduler.trigger_job(scheduler_id)
    if not triggered:
        raise HTTPException(status_code=500, detail=f"Failed to trigger job '{job_name}'")

    state = SchedulerState()
    job_state = state.jobs.get(scheduler_id, {})

    return {
        "triggered": True,
        "job_name": job_name,
        "last_run": job_state.get("last_run"),
        "total_operations": job_state.get("operations", 0),
    }


# ══════════════════════════════════════════════════════════════════════════════
# DELETE /api/memory/node/{node_id}
# ══════════════════════════════════════════════════════════════════════════════

@router.delete("/node/{node_id}")
async def archive_node_endpoint(node_id: str, user_id: str = Depends(get_current_user_id)):
    """
    Soft-archive a node (set is_archived=True). Never hard deletes.
    Blocks if node is ANCHOR with IMMUTABLE priority.
    """
    async with get_session() as db:
        result = await db.execute(select(Node).where(Node.id == uuid.UUID(node_id), Node.user_id == uuid.UUID(user_id)))
        node = result.scalar_one_or_none()

        if not node:
            raise HTTPException(status_code=404, detail="Node not found")

        if node.priority_flag == PriorityFlag.IMMUTABLE:
            raise HTTPException(
                status_code=403,
                detail="Cannot archive IMMUTABLE node (ANCHOR identity fact)",
            )

        node.is_archived = True
        log = list(node.operation_log or [])
        from datetime import datetime, timezone
        log.append({
            "op": "ARCHIVE_MANUAL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": {"source": "dashboard_api"},
        })
        node.operation_log = log

        return {"success": True, "node_id": node_id}


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/memory/search
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/search")
async def search_memories(request: Request, q: str = Query(..., min_length=2), user_id: str = Depends(get_current_user_id)):
    """
    Run full hybrid retrieval on query string.
    Returns nodes with content previews for dashboard search.
    """
    graph = request.app.state.graph
    retriever: HybridRetriever = request.app.state.retriever

    async with get_session() as db:
        retrieval = await retriever.retrieve(
            query=q,
            db=db,
            graph=graph,
            user_id=user_id,
        )

        # Combine all result nodes into a search results list
        seen = set()
        results = []

        for node_list in [retrieval.anchor_nodes, retrieval.domain_nodes,
                          retrieval.retrieved_nodes, retrieval.lateral_context]:
            for n in node_list:
                nid = n.get("id")
                if nid and nid not in seen:
                    seen.add(nid)
                    content = n.get("content", "")
                    results.append({
                        "id": nid,
                        "name": n.get("name", ""),
                        "node_type": n.get("node_type", ""),
                        "content_preview": content[:200] + ("..." if len(content) > 200 else ""),
                        "composite_weight": n.get("composite_weight", 0),
                        "decay_score": n.get("decay_score", 1.0),
                    })

        return {
            "query": q,
            "results": results,
            "total": len(results),
            "channels_used": retrieval.used_channels,
            "tokens_estimated": retrieval.total_tokens_estimated,
        }
