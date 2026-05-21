"""
Mem-Rooted — Chat API Routes

Single endpoint that runs the full Mem-Rooted pipeline per message:
Extract → Gate → Embed → Place + Operate → Retrieve → Prompt → LLM → Preload → Save
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.extraction import CandidateType, ExtractionResult, MemoryCandidate, extract_memories
from core.operations import add_node, create_lateral_link, noop, update_node
from core.placement import PlacementEngine
from core.retrieval import HybridRetriever, RetrievalResult
from core.placement import PlacementEngine
from core.retrieval import HybridRetriever, RetrievalResult
from db.connection import get_session
from db.models import Message, Node, NodeType, Session
from api.routes.auth import get_current_user_id

logger = logging.getLogger(__name__)

def is_additive_fact(new_content: str, old_content: str) -> bool:
    """Heuristic to determine if a new fact is additive rather than a replacement."""
    add_markers = ["also", "another", "too", "as well", "additionally"]
    new_lower = new_content.lower()
    return any(marker in new_lower for marker in add_markers)

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════════════
# Request / Response Models
# ══════════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class MemoryTransparency(BaseModel):
    anchor_count: int = 0
    domain_count: int = 0
    retrieved_count: int = 0
    channels_used: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    response: str
    session_id: str
    nodes_used: list[str] = Field(default_factory=list)
    memory_transparency: MemoryTransparency = Field(default_factory=MemoryTransparency)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _cosine_sim(a: list, b: list) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _candidate_type_to_node_type(ct: CandidateType) -> NodeType:
    return NodeType(ct.value)


def _build_context_prompt(retrieval: RetrievalResult) -> str:
    """Assemble structured context block from retrieval results."""
    parts = []

    # ANCHOR section
    if retrieval.anchor_nodes:
        parts.append("[IDENTITY — ALWAYS APPLY]")
        for node in retrieval.anchor_nodes:
            parts.append(f"- {node.get('content', '')}")
        parts.append("")

    # DOMAIN section
    if retrieval.domain_nodes:
        parts.append("[LIFE DIRECTIONS — DOMAIN]")
        for node in retrieval.domain_nodes:
            parts.append(f"- {node.get('content', '')}")
        parts.append("")

    # RETRIEVED section
    if retrieval.retrieved_nodes:
        parts.append("[RELEVANT CONTEXT]")
        for node in retrieval.retrieved_nodes:
            name = node.get("name", "Memory")
            content = node.get("content", "")
            parts.append(f"### {name}")
            parts.append(content)
            parts.append("")

    # LATERAL section
    if retrieval.lateral_context:
        parts.append("[LATERAL CONNECTIONS]")
        for node in retrieval.lateral_context:
            parts.append(f"- {node.get('name', '')}: {node.get('content', '')}")
        parts.append("")

    return "\n".join(parts)


async def _get_or_create_session(db: AsyncSession, sid: str, user_id: str) -> Session:
    """Retrieve existing session or create a new one."""
    try:
        session_uuid = uuid.UUID(sid)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id format (must be UUID)")

    result = await db.execute(select(Session).where(Session.id == session_uuid))
    session = result.scalar_one_or_none()

    if not session:
        session = Session(id=session_uuid, user_id=uuid.UUID(user_id))
        db.add(session)
        await db.commit()
        await db.refresh(session)
    return session


async def _get_last_messages(db: AsyncSession, session_id: str, count: int = 3) -> list[str]:
    """Get last N messages from the session for preloading."""
    sid = uuid.UUID(session_id)
    result = await db.execute(
        select(Message.content)
        .where(Message.session_id == sid)
        .order_by(Message.created_at.desc())
        .limit(count)
    )
    return [row[0] for row in result.all()][::-1]  # reverse to chronological


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/chat/message
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/message", response_model=ChatResponse)
async def send_message(
    body: ChatRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id)
):
    """
    Full Mem-Rooted pipeline per message:
    1. Extract → 2. Gate → 3. Embed → 4. Place+Operate →
    5. Retrieve → 6. Prompt → 7. LLM → 8. Preload → 9. Save
    """
    graph = request.app.state.graph
    retriever: HybridRetriever = request.app.state.retriever
    placement: PlacementEngine = request.app.state.placement_engine
    emb_model = request.app.state.embedding_model

    async with get_session() as db:
        session = await _get_or_create_session(db, body.session_id, user_id)
        session_uuid = session.id

        # ── 1. Extract ───────────────────────────────────────────────────
        extraction: ExtractionResult = await extract_memories(body.message)
        logger.info(
            f"[Chat] Extracted {len(extraction.candidates)} candidates "
            f"(stage1={'pass' if extraction.stage1_passed else 'fail'}, "
            f"stage2={'called' if extraction.stage2_called else 'skipped'})"
        )

        # ── 2. Gate ──────────────────────────────────────────────────────
        viable = [
            c for c in extraction.candidates
            if not c.is_noise and not (c.is_question and c.confidence < 0.5)
        ]
        logger.info(f"[Chat] {len(viable)} candidates passed gate (from {len(extraction.candidates)})")

        # ── 3. Embed candidates ──────────────────────────────────────────
        embedded_candidates: list[tuple[MemoryCandidate, list[float]]] = []
        for cand in viable:
            vec = emb_model.encode(cand.content, normalize_embeddings=True)
            embedded_candidates.append((cand, vec.tolist()))

        # ── 4. Place + Operate ───────────────────────────────────────────
        # Load all active nodes for placement comparison FOR THIS USER ONLY
        all_nodes_result = await db.execute(
            select(Node).where(
                Node.is_archived == False,
                Node.user_id == uuid.UUID(user_id)
            )
        )
        all_db_nodes = list(all_nodes_result.scalars().all())
        all_nodes_dicts = []
        for n in all_db_nodes:
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
                "composite_weight": n.composite_weight or 0.0,
            })

        for cand, cand_emb in embedded_candidates:
            node_type = _candidate_type_to_node_type(cand.candidate_type)

            # Run placement
            place_result = await placement.run_placement(
                candidate_content=cand.content,
                candidate_type=cand.candidate_type.value,
                candidate_embedding=cand_emb,
                all_nodes=all_nodes_dicts,
                graph=graph,
                db=db,
                user_id=user_id,
            )

            # Check for semantically similar existing node (cosine > 0.88)
            best_match_id = None
            best_match_sim = 0.0
            best_match_content = ""
            for nd in all_nodes_dicts:
                # 1. Exact Name Match (Highest priority for structured extraction)
                if cand.name and nd.get("name") and cand.name.strip().lower() == nd.get("name").strip().lower():
                    best_match_sim = 1.0
                    best_match_id = nd["id"]
                    best_match_content = nd.get("content", "")
                    break
                    
                # 2. Semantic Embedding Match (Fallback)
                nd_emb = nd.get("embedding")
                if nd_emb is None:
                    continue
                sim = _cosine_sim(cand_emb, nd_emb)
                if sim > best_match_sim:
                    best_match_sim = sim
                    best_match_id = nd["id"]
                    best_match_content = nd.get("content", "")

            threshold = 0.60 if node_type.value == "ANCHOR" else 0.65
            if best_match_sim > threshold and best_match_id:
                # Existing node found — noop or update
                content_differs = cand.content.strip().lower() != best_match_content.strip().lower()
                if content_differs:
                    if is_additive_fact(cand.content, best_match_content):
                        # Treat as ADD — create new sibling node, do not update existing
                        parent_uuid = uuid.UUID(place_result.parent_id) if place_result.parent_id else None
                        op_result = await add_node(
                            db=db,
                            name=cand.name if cand.name else cand.content[:80],
                            content=cand.content,
                            node_type=node_type,
                            parent_id=parent_uuid,
                            embedding=cand_emb,
                            user_id=user_id,
                            session_id=session_uuid,
                        )
                        logger.info(f"[Chat] Additive fact detected: added new node instead of updating {best_match_id[:8]}")
                    else:
                        # genuine update/contradiction
                        op_result = await update_node(db, uuid.UUID(best_match_id), cand.content)
                        if not op_result.success and op_result.operation_type == "BLOCKED_UPDATE":
                            fallback_name = f"Update: {cand.name}" if cand.name else "Identity Update"
                            await add_node(
                                db=db,
                                name=fallback_name[:50],
                                content=cand.content,
                                node_type=NodeType.INSTANCE,
                                parent_id=uuid.UUID(best_match_id),
                                embedding=cand_emb,
                                user_id=user_id,
                                session_id=session_uuid,
                            )
                            logger.info(f"[Chat] Fallback: Created INSTANCE child under IMMUTABLE node {best_match_id[:8]}")
                        else:
                            logger.info(f"[Chat] Updated existing node {best_match_id[:8]} (sim={best_match_sim:.3f})")
                else:
                    await noop(db, uuid.UUID(best_match_id))
                    logger.info(f"[Chat] NOOP on existing node {best_match_id[:8]} (sim={best_match_sim:.3f})")
            else:
                # New node
                parent_uuid = uuid.UUID(place_result.parent_id) if place_result.parent_id else None
                op_result = await add_node(
                    db=db,
                    name=cand.name if cand.name else cand.content[:80],
                    content=cand.content,
                    node_type=node_type,
                    parent_id=parent_uuid,
                    embedding=cand_emb,
                    user_id=user_id,
                    session_id=session_uuid,
                )
                logger.info(
                    f"[Chat] Added {node_type.value} node (confidence={cand.confidence:.2f}, "
                    f"parent={'root' if not parent_uuid else str(parent_uuid)[:8]})"
                )

                # Create lateral links from placement
                if op_result.success and op_result.node_id:
                    new_node_uuid = uuid.UUID(op_result.node_id)
                    for link_target_id, link_sim in place_result.lateral_links:
                        try:
                            await create_lateral_link(
                                db, new_node_uuid, uuid.UUID(link_target_id), link_sim
                            )
                        except Exception as e:
                            logger.warning(f"[Chat] Lateral link failed: {e}")

                    # Add to live graph
                    node_result = await db.execute(select(Node).where(Node.id == new_node_uuid))
                    new_node = node_result.scalar_one_or_none()
                    if new_node:
                        graph.add_node_to_graph(new_node, parent_uuid)

                        # Refresh node dicts for subsequent candidates
                        emb = list(new_node.embedding) if new_node.embedding is not None else None
                        all_nodes_dicts.append({
                            "id": str(new_node.id),
                            "name": new_node.name,
                            "node_type": new_node.node_type.value,
                            "content": new_node.content,
                            "parent_id": str(new_node.parent_id) if new_node.parent_id else None,
                            "tier_level": new_node.tier_level,
                            "embedding": emb,
                            "is_archived": False,
                            "composite_weight": new_node.composite_weight or 0.0,
                        })

        # ── 5. Retrieve ──────────────────────────────────────────────────
        retrieval: RetrievalResult = await retriever.retrieve(
            query=body.message,
            db=db,
            graph=graph,
            user_id=user_id,
            session_id=body.session_id,
        )
        logger.info(
            f"[Chat] Retrieved: {len(retrieval.anchor_nodes)} anchors, "
            f"{len(retrieval.domain_nodes)} domains, "
            f"{len(retrieval.retrieved_nodes)} context nodes, "
            f"channels={retrieval.used_channels}"
        )

        # ── 6. Assemble prompt ───────────────────────────────────────────
        context_block = _build_context_prompt(retrieval)

        system_prompt = (
            "You are a deeply personalized AI. You know this person. "
            "Use the memory context below to respond in a way that reflects "
            "genuine understanding of who they are. Be natural, not clinical. "
            "Reference their goals, preferences, and history when relevant, "
            "but don't list memories robotically."
        )

        user_content = f"{context_block}\n\nUser: {body.message}"

        # ── 7. LLM response ─────────────────────────────────────────────
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            api_key=os.getenv("OPENAI_API_KEY", "")
        )
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        try:
            llm_response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=500,
                temperature=0.7,
            )
            assistant_text = llm_response.choices[0].message.content or "I'm here for you."
        except Exception as e:
            logger.error(f"[Chat] LLM call failed: {e}")
            assistant_text = "I encountered an issue generating a response. Please try again."

        # ── 8. Preload (fire and forget) ─────────────────────────────────
        last_msgs = await _get_last_messages(db, body.session_id, count=3)
        last_msgs.append(body.message)

        async def _preload():
            try:
                async with get_session() as preload_db:
                    await retriever.preload_next_scene(last_msgs, graph, preload_db, user_id, body.session_id)
            except Exception as e:
                logger.warning(f"[Chat] Preload failed: {e}")

        asyncio.create_task(_preload())

        # ── 9. Save messages ─────────────────────────────────────────────
        user_msg = Message(
            session_id=session_uuid,
            role="user",
            content=body.message,
            user_id=uuid.UUID(user_id),
            node_ids_used=[],
        )
        assistant_msg = Message(
            session_id=session_uuid,
            role="assistant",
            content=assistant_text,
            user_id=uuid.UUID(user_id),
            node_ids_used=retrieval.nodes_used_ids,
        )
        db.add(user_msg)
        db.add(assistant_msg)

        session.message_count = (session.message_count or 0) + 2
        await db.flush()

        # ── Build response ───────────────────────────────────────────────
        return ChatResponse(
            response=assistant_text,
            session_id=body.session_id,
            nodes_used=retrieval.nodes_used_ids,
            memory_transparency=MemoryTransparency(
                anchor_count=len(retrieval.anchor_nodes),
                domain_count=len(retrieval.domain_nodes),
                retrieved_count=len(retrieval.retrieved_nodes),
                channels_used=retrieval.used_channels,
            ),
        )


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/chat/sessions
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/sessions")
async def list_sessions(user_id: str = Depends(get_current_user_id)):
    """List all conversation sessions for the user."""
    async with get_session() as db:
        result = await db.execute(
            select(Session).where(Session.user_id == uuid.UUID(user_id)).order_by(Session.started_at.desc()).limit(50)
        )
        sessions = result.scalars().all()
        return [
            {
                "id": str(s.id),
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "message_count": s.message_count,
                "summary": s.summary,
            }
            for s in sessions
        ]


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/chat/sessions/{session_id}/messages
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, user_id: str = Depends(get_current_user_id)):
    """Get history for a specific session."""
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    async with get_session() as db:
        result = await db.execute(
            select(Message)
            .where(Message.session_id == session_uuid)
            .where(Message.user_id == uuid.UUID(user_id))
            .order_by(Message.created_at.asc())
        )
        messages = result.scalars().all()
        return [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "node_ids_used": m.node_ids_used,
            }
            for m in messages
        ]
