"""
Mem-Rooted — Background Scheduler (Moving Memory Engine)

Five async jobs that keep the memory network self-organizing:
    Job 1: Decay sweep       — every 6 hours
    Job 2: Promotion sweep   — every 12 hours
    Job 3: Merge sweep       — every 24 hours
    Job 4: Split sweep       — every 24 hours (offset +30 min from merge)
    Job 5: Lateral link refresh — every 48 hours

Uses APScheduler AsyncIOScheduler. Never blocks the API.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import Node, NodeType
from graph.network import MemoryGraph

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Scheduler State Singleton
# ══════════════════════════════════════════════════════════════════════════════

class SchedulerState:
    """
    Singleton tracking scheduler health and job statistics.
    Exposed via get_status() for the memory dashboard API.
    """

    _instance: Optional["SchedulerState"] = None

    def __new__(cls) -> "SchedulerState":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.jobs: dict[str, dict[str, Any]] = {
            "decay_sweep": {"last_run": None, "operations": 0, "errors": 0, "details": {}},
            "promotion_sweep": {"last_run": None, "operations": 0, "errors": 0, "details": {}},
            "merge_sweep": {"last_run": None, "operations": 0, "errors": 0, "details": {}},
            "split_sweep": {"last_run": None, "operations": 0, "errors": 0, "details": {}},
            "lateral_link_refresh": {"last_run": None, "operations": 0, "errors": 0, "details": {}},
        }
        self.scheduler_running: bool = False
        self.started_at: Optional[datetime] = None

    def record_run(self, job_name: str, operations: int, errors: int, details: Optional[dict] = None):
        """Record a completed job run."""
        if job_name in self.jobs:
            self.jobs[job_name]["last_run"] = datetime.now(timezone.utc).isoformat()
            self.jobs[job_name]["operations"] += operations
            self.jobs[job_name]["errors"] += errors
            if details:
                self.jobs[job_name]["details"] = details

    def get_status(self) -> dict:
        """Return full scheduler status as a dict for the API."""
        return {
            "scheduler_running": self.scheduler_running,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "jobs": dict(self.jobs),
        }


# ══════════════════════════════════════════════════════════════════════════════
# Job Implementations
# ══════════════════════════════════════════════════════════════════════════════

async def _job_decay_sweep(session_factory: async_sessionmaker, graph: MemoryGraph):
    """
    Job 1 — Decay sweep.
    Apply exponential decay to all non-ANCHOR nodes, archive those below threshold.
    """
    state = SchedulerState()
    logger.info("[Scheduler] Starting decay sweep...")

    try:
        async with session_factory() as db:
            from core.decay import apply_decay_to_all
            result = await apply_decay_to_all(db)
            await db.commit()

            ops = result.get("decayed", 0) + result.get("archived", 0)
            state.record_run("decay_sweep", operations=ops, errors=0, details=result)
            logger.info(
                f"[Scheduler] Decay sweep complete: "
                f"{result.get('decayed', 0)} decayed, "
                f"{result.get('archived', 0)} archived, "
                f"{result.get('total_scanned', 0)} scanned"
            )
    except Exception as e:
        state.record_run("decay_sweep", operations=0, errors=1, details={"error": str(e)})
        logger.error(f"[Scheduler] Decay sweep failed: {e}", exc_info=True)


async def _job_promotion_sweep(session_factory: async_sessionmaker, graph: MemoryGraph):
    """
    Job 2 — Promotion sweep.
    Recompute all weights, then promote/demote qualifying nodes.
    Rebuilds graph after structural changes.
    """
    state = SchedulerState()
    logger.info("[Scheduler] Starting promotion sweep...")

    try:
        async with session_factory() as db:
            # Step 1: Recompute all weights
            from core.weightage import recompute_all_weights
            weight_result = await recompute_all_weights(db)
            await db.flush()

            # Step 2: Apply promotions and demotions
            from core.decay import apply_promotions_to_all
            promo_result = await apply_promotions_to_all(db)
            await db.commit()

            total_changes = promo_result.get("promoted", 0) + promo_result.get("demoted", 0)

            # Step 3: Rebuild graph if structural changes occurred
            if total_changes > 0:
                all_nodes_result = await db.execute(
                    select(Node).where(Node.is_archived == False)
                )
                all_nodes = list(all_nodes_result.scalars().all())
                graph.build_from_db(all_nodes)
                logger.info(f"[Scheduler] Graph rebuilt after {total_changes} structural changes")

            details = {**weight_result, **promo_result}
            state.record_run(
                "promotion_sweep",
                operations=total_changes,
                errors=promo_result.get("errors", 0),
                details=details,
            )
            logger.info(
                f"[Scheduler] Promotion sweep complete: "
                f"{promo_result.get('promoted', 0)} promoted, "
                f"{promo_result.get('demoted', 0)} demoted"
            )
    except Exception as e:
        state.record_run("promotion_sweep", operations=0, errors=1, details={"error": str(e)})
        logger.error(f"[Scheduler] Promotion sweep failed: {e}", exc_info=True)


async def _job_merge_sweep(session_factory: async_sessionmaker, graph: MemoryGraph):
    """
    Job 3 — Merge sweep.
    Find sibling nodes with high embedding similarity and merge them.
    """
    state = SchedulerState()
    logger.info("[Scheduler] Starting merge sweep...")

    try:
        candidates = graph.find_merge_candidates(threshold=0.85)
        merged_count = 0
        errors = 0

        if candidates:
            async with session_factory() as db:
                from core.operations import merge_nodes

                for node_id_a, node_id_b, similarity in candidates:
                    try:
                        result = await merge_nodes(
                            db,
                            uuid.UUID(node_id_a),
                            uuid.UUID(node_id_b),
                        )
                        if result.success:
                            merged_count += 1
                    except Exception as e:
                        errors += 1
                        logger.warning(f"[Scheduler] Merge failed for {node_id_a}+{node_id_b}: {e}")

                await db.commit()

                # Rebuild graph after merges
                if merged_count > 0:
                    all_nodes_result = await db.execute(
                        select(Node).where(Node.is_archived == False)
                    )
                    all_nodes = list(all_nodes_result.scalars().all())
                    graph.build_from_db(all_nodes)

        state.record_run(
            "merge_sweep",
            operations=merged_count,
            errors=errors,
            details={"candidates_found": len(candidates), "merged": merged_count},
        )
        logger.info(f"[Scheduler] Merge sweep complete: {merged_count} merged from {len(candidates)} candidates")
    except Exception as e:
        state.record_run("merge_sweep", operations=0, errors=1, details={"error": str(e)})
        logger.error(f"[Scheduler] Merge sweep failed: {e}", exc_info=True)


async def _job_split_sweep(session_factory: async_sessionmaker, graph: MemoryGraph):
    """
    Job 4 — Split sweep.
    Find overloaded nodes with divergent children and split them.
    """
    state = SchedulerState()
    logger.info("[Scheduler] Starting split sweep...")

    try:
        candidates = graph.find_split_candidates(max_children=12, divergence_threshold=0.4)
        split_count = 0
        errors = 0

        if candidates:
            async with session_factory() as db:
                from core.operations import split_node

                for node_id in candidates:
                    try:
                        result = await split_node(db, uuid.UUID(node_id))
                        if result.success:
                            split_count += 1
                    except Exception as e:
                        errors += 1
                        logger.warning(f"[Scheduler] Split failed for {node_id}: {e}")

                await db.commit()

                # Rebuild graph after splits
                if split_count > 0:
                    all_nodes_result = await db.execute(
                        select(Node).where(Node.is_archived == False)
                    )
                    all_nodes = list(all_nodes_result.scalars().all())
                    graph.build_from_db(all_nodes)

        state.record_run(
            "split_sweep",
            operations=split_count,
            errors=errors,
            details={"candidates_found": len(candidates), "split": split_count},
        )
        logger.info(f"[Scheduler] Split sweep complete: {split_count} split from {len(candidates)} candidates")
    except Exception as e:
        state.record_run("split_sweep", operations=0, errors=1, details={"error": str(e)})
        logger.error(f"[Scheduler] Split sweep failed: {e}", exc_info=True)


async def _job_lateral_link_refresh(session_factory: async_sessionmaker, graph: MemoryGraph):
    """
    Job 5 — Lateral link refresh.
    Recompute lateral links for CLUSTER and DOMAIN nodes.
    Add new, strengthen existing, weaken stale links.
    """
    state = SchedulerState()
    logger.info("[Scheduler] Starting lateral link refresh...")

    try:
        async with session_factory() as db:
            from core.placement import PlacementEngine
            from datetime import timedelta

            engine = PlacementEngine()
            now = datetime.now(timezone.utc)
            stale_cutoff = now - timedelta(days=30)

            # Load CLUSTER and DOMAIN nodes
            result = await db.execute(
                select(Node).where(
                    Node.is_archived == False,
                    Node.node_type.in_([NodeType.CLUSTER, NodeType.DOMAIN]),
                )
            )
            target_nodes = list(result.scalars().all())

            # Load all nodes for comparison
            all_result = await db.execute(select(Node).where(Node.is_archived == False))
            all_nodes_raw = list(all_result.scalars().all())
            all_nodes_dicts = []
            for n in all_nodes_raw:
                emb = list(n.embedding) if n.embedding is not None else None
                all_nodes_dicts.append({
                    "id": str(n.id),
                    "name": n.name,
                    "node_type": n.node_type.value,
                    "content": n.content,
                    "parent_id": str(n.parent_id) if n.parent_id else None,
                    "tier_level": n.tier_level,
                    "embedding": emb,
                    "is_archived": n.is_archived,
                })

            links_added = 0
            links_strengthened = 0
            links_weakened = 0

            for node in target_nodes:
                node_emb = list(node.embedding) if node.embedding is not None else None
                nid = str(node.id)

                # Find fresh lateral links
                new_links = engine.find_lateral_links(
                    node_emb, nid, all_nodes_dicts, threshold=0.65
                )
                new_link_targets = {lid for lid, _ in new_links}

                # Current lateral links
                current_links = list(node.lateral_links or [])
                current_targets = {l.get("target_id") for l in current_links}

                updated_links = []

                # Process existing links: strengthen if reinforced, weaken if stale
                for link in current_links:
                    tid = link.get("target_id")
                    if tid in new_link_targets:
                        # Reinforce: bump strength by 0.1, cap at 1.0
                        old_strength = link.get("similarity", 0.5)
                        new_strength = min(1.0, old_strength + 0.1)
                        link["similarity"] = round(new_strength, 4)
                        link["last_reinforced"] = now.isoformat()
                        updated_links.append(link)
                        links_strengthened += 1
                    else:
                        # Check staleness
                        last_reinforced_str = link.get("last_reinforced") or link.get("created_at")
                        is_stale = True
                        if last_reinforced_str:
                            try:
                                last_dt = datetime.fromisoformat(last_reinforced_str)
                                if last_dt.tzinfo is None:
                                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                                is_stale = last_dt < stale_cutoff
                            except (ValueError, TypeError):
                                pass

                        if is_stale:
                            old_strength = link.get("similarity", 0.5)
                            weakened = max(0.0, old_strength - 0.05)
                            if weakened > 0.1:  # Keep if still meaningful
                                link["similarity"] = round(weakened, 4)
                                updated_links.append(link)
                                links_weakened += 1
                            # else: drop the link entirely
                        else:
                            updated_links.append(link)

                # Add truly new links
                for tid, sim in new_links:
                    if tid not in current_targets:
                        updated_links.append({
                            "target_id": tid,
                            "similarity": round(sim, 4),
                            "created_at": now.isoformat(),
                            "last_reinforced": now.isoformat(),
                        })
                        links_added += 1

                # Cap at 10 lateral links per node
                if len(updated_links) > 10:
                    updated_links.sort(key=lambda l: l.get("similarity", 0), reverse=True)
                    updated_links = updated_links[:10]

                node.lateral_links = updated_links

            await db.commit()

            # Rebuild graph to reflect new lateral links
            all_fresh = await db.execute(select(Node).where(Node.is_archived == False))
            graph.build_from_db(list(all_fresh.scalars().all()))

        state.record_run(
            "lateral_link_refresh",
            operations=links_added + links_strengthened + links_weakened,
            errors=0,
            details={
                "added": links_added,
                "strengthened": links_strengthened,
                "weakened": links_weakened,
                "nodes_scanned": len(target_nodes),
            },
        )
        logger.info(
            f"[Scheduler] Lateral link refresh complete: "
            f"{links_added} added, {links_strengthened} strengthened, {links_weakened} weakened"
        )
    except Exception as e:
        state.record_run("lateral_link_refresh", operations=0, errors=1, details={"error": str(e)})
        logger.error(f"[Scheduler] Lateral link refresh failed: {e}", exc_info=True)


# ══════════════════════════════════════════════════════════════════════════════
# MemoryScheduler
# ══════════════════════════════════════════════════════════════════════════════

class MemoryScheduler:
    """
    Moving Memory engine. Runs 5 background jobs via APScheduler AsyncIOScheduler.
    Never blocks the API — all jobs run in the async event loop.
    """

    def __init__(self):
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._session_factory: Optional[async_sessionmaker] = None
        self._graph: Optional[MemoryGraph] = None
        self._state = SchedulerState()

    def start(self, session_factory: async_sessionmaker, graph: MemoryGraph) -> None:
        """Initialize all 5 jobs and start the scheduler."""
        self._session_factory = session_factory
        self._graph = graph

        self._scheduler = AsyncIOScheduler(
            timezone="UTC",
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
        )

        # Job 1: Decay sweep — every 6 hours
        self._scheduler.add_job(
            _job_decay_sweep,
            trigger=IntervalTrigger(hours=6),
            args=[session_factory, graph],
            id="decay_sweep",
            name="Decay Sweep",
        )

        # Job 2: Promotion sweep — every 12 hours
        self._scheduler.add_job(
            _job_promotion_sweep,
            trigger=IntervalTrigger(hours=12),
            args=[session_factory, graph],
            id="promotion_sweep",
            name="Promotion Sweep",
        )

        # Job 3: Merge sweep — every 24 hours
        self._scheduler.add_job(
            _job_merge_sweep,
            trigger=IntervalTrigger(hours=24),
            args=[session_factory, graph],
            id="merge_sweep",
            name="Merge Sweep",
        )

        # Job 4: Split sweep — every 24 hours, offset by 30 minutes from merge
        self._scheduler.add_job(
            _job_split_sweep,
            trigger=IntervalTrigger(hours=24, minutes=30),
            args=[session_factory, graph],
            id="split_sweep",
            name="Split Sweep",
        )

        # Job 5: Lateral link refresh — every 48 hours
        self._scheduler.add_job(
            _job_lateral_link_refresh,
            trigger=IntervalTrigger(hours=48),
            args=[session_factory, graph],
            id="lateral_link_refresh",
            name="Lateral Link Refresh",
        )

        self._scheduler.start()
        self._state.scheduler_running = True
        self._state.started_at = datetime.now(timezone.utc)
        logger.info("[Scheduler] MemoryScheduler started with 5 background jobs")

    def stop(self) -> None:
        """Graceful shutdown — waits for running jobs to complete."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            self._state.scheduler_running = False
            logger.info("[Scheduler] MemoryScheduler stopped gracefully")

    def get_status(self) -> dict:
        """Return scheduler status for the dashboard API."""
        return self._state.get_status()

    def trigger_job(self, job_name: str) -> bool:
        """Manually trigger a specific job (for testing/admin)."""
        if self._scheduler and job_name in [j.id for j in self._scheduler.get_jobs()]:
            self._scheduler.modify_job(job_name, next_run_time=datetime.now(timezone.utc))
            logger.info(f"[Scheduler] Manually triggered job: {job_name}")
            return True
        return False
