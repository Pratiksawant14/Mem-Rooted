"""
Mem-Rooted — Four-Way Hybrid Retrieval with Reciprocal Rank Fusion

The most critical file in the project. Directly determines benchmark
performance on LOCOMO and LongMemEval.

Pipeline:
    Step 1: Query preparation (embed, BM25 terms, temporal flags, entities)
    Step 2: Four parallel retrieval channels (semantic, BM25, graph, temporal)
    Step 3: Reciprocal Rank Fusion across all channels
    Step 4: Tiered mandatory injection (ANCHOR + DOMAIN always included)
    Step 5: Token budget filter (2000 token cap)
    Step 6: Assemble structured context block
"""

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
from pydantic import BaseModel, Field
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Node, NodeType
from graph.network import MemoryGraph

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Result Models
# ══════════════════════════════════════════════════════════════════════════════

class RetrievalResult(BaseModel):
    """Structured context block returned by the retrieval engine."""
    anchor_nodes: list[dict] = Field(default_factory=list)
    domain_nodes: list[dict] = Field(default_factory=list)
    retrieved_nodes: list[dict] = Field(default_factory=list, description="Top RRF results post-budget")
    lateral_context: list[dict] = Field(default_factory=list, description="Spreading activation extras")
    used_channels: list[str] = Field(default_factory=list)
    total_tokens_estimated: int = 0
    nodes_used_ids: list[str] = Field(default_factory=list, description="All node IDs for memory transparency")


class QueryContext(BaseModel):
    """Prepared query with all features extracted."""
    raw_query: str
    query_embedding: Optional[list[float]] = None
    bm25_terms: list[str] = Field(default_factory=list)
    temporal_query: bool = False
    temporal_window_days: Optional[int] = None
    entities: list[str] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════════════════

STOPWORDS: set[str] = {
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it", "they",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "into", "about", "like", "through", "after", "over", "between",
    "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most",
    "other", "some", "such", "no", "than", "too", "very",
    "that", "this", "these", "those", "what", "which", "who", "whom",
    "how", "when", "where", "why", "if", "then", "just", "also",
}

TEMPORAL_PATTERNS: list[tuple[re.Pattern, int]] = [
    (re.compile(r"\byesterday\b", re.I), 1),
    (re.compile(r"\btoday\b", re.I), 1),
    (re.compile(r"\blast\s+week\b", re.I), 7),
    (re.compile(r"\bthis\s+week\b", re.I), 7),
    (re.compile(r"\blast\s+month\b", re.I), 30),
    (re.compile(r"\brecently\b", re.I), 14),
    (re.compile(r"\ba\s+few\s+days\s+ago\b", re.I), 5),
    (re.compile(r"\bcoupl?e?\s+of\s+days\b", re.I), 3),
    (re.compile(r"\blast\s+year\b", re.I), 365),
    (re.compile(r"\bwhen\s+did\b", re.I), 90),
    (re.compile(r"\bbefore\b", re.I), 60),
    (re.compile(r"\bearlier\b", re.I), 30),
]

RRF_K: int = 60           # RRF constant
TOP_K_PER_CHANNEL: int = 20
TOP_RRF_RESULTS: int = 8
TOKEN_BUDGET: int = 2000
DEFAULT_RANK: int = 1000   # rank for nodes absent from a channel


# ══════════════════════════════════════════════════════════════════════════════
# Lazy-loaded Models
# ══════════════════════════════════════════════════════════════════════════════

_embedding_model = None
_spacy_nlp = None


def _get_embedding_model():
    """Lazy-load sentence-transformers model."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Loaded embedding model: all-MiniLM-L6-v2")
    return _embedding_model


def _get_spacy():
    """Lazy-load spaCy for entity extraction."""
    global _spacy_nlp
    if _spacy_nlp is None:
        import spacy
        try:
            _spacy_nlp = spacy.load("en_core_web_sm")
        except OSError:
            from spacy.cli import download
            download("en_core_web_sm")
            _spacy_nlp = spacy.load("en_core_web_sm")
    return _spacy_nlp


def _embed_text(text: str) -> list[float]:
    """Embed a single text string."""
    model = _get_embedding_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


# ══════════════════════════════════════════════════════════════════════════════
# HybridRetriever
# ══════════════════════════════════════════════════════════════════════════════

class HybridRetriever:
    """
    Four-way parallel retrieval fused via Reciprocal Rank Fusion.
    Channels: Semantic (vector), BM25 (keyword), Graph (spreading activation), Temporal.
    """

    def __init__(self):
        self._preload_cache: dict[str, list[str]] = {}  # session_id → preloaded node_ids

    # ──────────────────────────────────────────────────────────────────────
    # Step 1 — Query Preparation
    # ──────────────────────────────────────────────────────────────────────

    def prepare_query(self, query: str) -> QueryContext:
        """
        Prepare query: embed, extract BM25 terms, detect temporal expressions,
        extract entity names via spaCy.
        """
        # Embed
        query_embedding = _embed_text(query)

        # BM25 terms: tokenize, lowercase, remove stopwords
        tokens = re.findall(r"\b[a-zA-Z]+\b", query.lower())
        bm25_terms = [t for t in tokens if t not in STOPWORDS and len(t) >= 2]

        # Temporal detection
        temporal_query = False
        temporal_window_days = None
        for pattern, days in TEMPORAL_PATTERNS:
            if pattern.search(query):
                temporal_query = True
                temporal_window_days = days
                break

        # Entity extraction via spaCy
        entities = []
        try:
            nlp = _get_spacy()
            doc = nlp(query)
            entities = [ent.text for ent in doc.ents if ent.label_ in {"PERSON", "GPE", "ORG", "DATE", "CARDINAL"}]
        except Exception as e:
            logger.warning(f"Entity extraction failed: {e}")

        return QueryContext(
            raw_query=query,
            query_embedding=query_embedding,
            bm25_terms=bm25_terms,
            temporal_query=temporal_query,
            temporal_window_days=temporal_window_days,
            entities=entities,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Step 2 — Four Parallel Retrieval Channels
    # ──────────────────────────────────────────────────────────────────────

    def _semantic_channel(
        self,
        query_embedding: list[float],
        nodes: list[dict],
    ) -> list[tuple[str, float]]:
        """
        Channel 1 — Semantic (vector cosine similarity).
        Returns top-20 by cosine similarity as [(node_id, score)].
        """
        if not query_embedding:
            return []

        q_vec = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q_vec)
        if q_norm == 0:
            return []

        scored = []
        for node in nodes:
            emb = node.get("embedding")
            if emb is None:
                continue
            n_vec = np.array(emb, dtype=np.float32)
            n_norm = np.linalg.norm(n_vec)
            if n_norm == 0:
                continue
            sim = float(np.dot(q_vec, n_vec) / (q_norm * n_norm))
            scored.append((node["id"], sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:TOP_K_PER_CHANNEL]

    def _bm25_channel(
        self,
        query_terms: list[str],
        nodes: list[dict],
    ) -> list[tuple[str, float]]:
        """
        Channel 2 — Keyword (BM25Okapi).
        Returns top-20 by BM25 score as [(node_id, score)].
        """
        if not query_terms or not nodes:
            return []

        # Build corpus
        corpus = []
        node_ids = []
        for node in nodes:
            content = (node.get("content") or "").lower()
            tokens = re.findall(r"\b[a-zA-Z]+\b", content)
            corpus.append(tokens)
            node_ids.append(node["id"])

        if not corpus:
            return []

        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(query_terms)

        scored = [(node_ids[i], float(scores[i])) for i in range(len(node_ids)) if scores[i] > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:TOP_K_PER_CHANNEL]

    def _graph_channel(
        self,
        query_entities: list[str],
        semantic_top3: list[str],
        graph: MemoryGraph,
    ) -> list[tuple[str, float]]:
        """
        Channel 3 — Graph spreading activation.
        Seeds: nodes whose content contains query entities.
        Fallback seeds: top-3 from semantic channel.
        Returns all activated nodes as [(node_id, activation_score)].
        """
        # Find seed nodes by entity match
        seed_ids = []
        if query_entities:
            for nid in graph.get_all_node_ids():
                attrs = graph.get_node_attrs(nid)
                if attrs and not attrs.get("is_archived"):
                    content_lower = (attrs.get("content") or "").lower()
                    if any(ent.lower() in content_lower for ent in query_entities):
                        seed_ids.append(nid)

        # Fallback: use top-3 semantic results
        if not seed_ids:
            seed_ids = semantic_top3[:3]

        if not seed_ids:
            return []

        activation = graph.spreading_activation(seed_ids, decay_factor=0.5, max_hops=3)
        return [(nid, score) for nid, score in activation.items()]

    def _temporal_channel(
        self,
        temporal_query: bool,
        temporal_window_days: Optional[int],
        nodes: list[dict],
    ) -> list[tuple[str, float]]:
        """
        Channel 4 — Temporal.
        If temporal_query: nodes recalled/created within the inferred window.
        Otherwise: 10 most recently recalled nodes.
        Returns [(node_id, recency_score)] where recency_score = 1/(1+days_since).
        """
        now = datetime.now(timezone.utc)

        if temporal_query and temporal_window_days:
            cutoff = now - timedelta(days=temporal_window_days)
            scored = []
            for node in nodes:
                ts = node.get("last_recalled_at") or node.get("created_at")
                if ts is None:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    days_since = max(0.01, (now - ts).total_seconds() / 86400.0)
                    score = 1.0 / (1.0 + days_since)
                    scored.append((node["id"], score))
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:TOP_K_PER_CHANNEL]
        else:
            # Most recently recalled
            timed = []
            for node in nodes:
                ts = node.get("last_recalled_at") or node.get("created_at")
                if ts is None:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                days_since = max(0.01, (now - ts).total_seconds() / 86400.0)
                score = 1.0 / (1.0 + days_since)
                timed.append((node["id"], score))
            timed.sort(key=lambda x: x[1], reverse=True)
            return timed[:10]

    # ──────────────────────────────────────────────────────────────────────
    # Step 3 — Reciprocal Rank Fusion
    # ──────────────────────────────────────────────────────────────────────

    def _reciprocal_rank_fusion(
        self,
        channels: dict[str, list[tuple[str, float]]],
    ) -> list[tuple[str, float]]:
        """
        RRF_score(node) = sum over channels of: 1 / (K + rank_in_channel)
        Nodes not in a channel get rank = DEFAULT_RANK (1000).
        """
        # Build rank maps per channel
        rank_maps: dict[str, dict[str, int]] = {}
        for ch_name, ch_results in channels.items():
            rank_map = {}
            for rank, (nid, _score) in enumerate(ch_results, start=1):
                rank_map[nid] = rank
            rank_maps[ch_name] = rank_map

        # Collect all node IDs that appeared in any channel
        all_node_ids: set[str] = set()
        for rm in rank_maps.values():
            all_node_ids.update(rm.keys())

        # Compute RRF score
        rrf_scores: list[tuple[str, float]] = []
        for nid in all_node_ids:
            score = 0.0
            for ch_name in channels:
                rank = rank_maps[ch_name].get(nid, DEFAULT_RANK)
                score += 1.0 / (RRF_K + rank)
            rrf_scores.append((nid, score))

        rrf_scores.sort(key=lambda x: x[1], reverse=True)
        return rrf_scores

    # ──────────────────────────────────────────────────────────────────────
    # Steps 4–6 — Assembly
    # ──────────────────────────────────────────────────────────────────────

    def _estimate_tokens(self, content: str) -> int:
        """Rough token estimate: len(content) / 4."""
        return max(1, len(content) // 4)

    async def retrieve(
        self,
        query: str,
        db: AsyncSession,
        graph: MemoryGraph,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> RetrievalResult:
        """
        Full retrieval pipeline: prepare → 4 channels → RRF → inject → budget → assemble.
        """
        # ── Step 1: Query preparation ────────────────────────────────────
        ctx = self.prepare_query(query)

        # ── Load nodes from DB ───────────────────────────────────────────
        import uuid
        result = await db.execute(select(Node).where(Node.is_archived == False, Node.user_id == uuid.UUID(user_id)))
        db_nodes = list(result.scalars().all())

        # Convert to dicts for channel processing
        node_dicts: list[dict] = []
        node_map: dict[str, dict] = {}
        for n in db_nodes:
            d = {
                "id": str(n.id),
                "name": n.name,
                "node_type": n.node_type.value,
                "content": n.content,
                "parent_id": str(n.parent_id) if n.parent_id else None,
                "tier_level": n.tier_level,
                "composite_weight": n.composite_weight or 0.0,
                "decay_score": n.decay_score or 1.0,
                "embedding": list(n.embedding) if n.embedding is not None else None,
                "created_at": n.created_at,
                "last_recalled_at": n.last_recalled_at,
                "lateral_links": n.lateral_links or [],
            }
            node_dicts.append(d)
            node_map[d["id"]] = d

        # Warm from preload cache if available
        preloaded_ids = []
        if session_id and session_id in self._preload_cache:
            preloaded_ids = self._preload_cache[session_id]

        # ── Step 2: Four channels ────────────────────────────────────────
        used_channels = []

        # Channel 1: Semantic
        semantic_results = self._semantic_channel(ctx.query_embedding, node_dicts)
        if semantic_results:
            used_channels.append("semantic")

        # Boost preloaded nodes in semantic results
        if preloaded_ids:
            preloaded_set = set(preloaded_ids)
            boosted = []
            for nid, score in semantic_results:
                if nid in preloaded_set:
                    boosted.append((nid, min(1.0, score * 1.15)))
                else:
                    boosted.append((nid, score))
            semantic_results = sorted(boosted, key=lambda x: x[1], reverse=True)

        # Channel 2: BM25
        bm25_results = self._bm25_channel(ctx.bm25_terms, node_dicts)
        if bm25_results:
            used_channels.append("bm25")

        # Channel 3: Graph spreading activation
        semantic_top3 = [nid for nid, _ in semantic_results[:3]]
        graph_results = self._graph_channel(ctx.entities, semantic_top3, graph)
        if graph_results:
            used_channels.append("graph")

        # Channel 4: Temporal
        temporal_results = self._temporal_channel(
            ctx.temporal_query, ctx.temporal_window_days, node_dicts
        )
        if temporal_results:
            used_channels.append("temporal")

        # ── Step 3: Reciprocal Rank Fusion ───────────────────────────────
        channels = {
            "semantic": semantic_results,
            "bm25": bm25_results,
            "graph": graph_results,
            "temporal": temporal_results,
        }
        rrf_ranked = self._reciprocal_rank_fusion(channels)

        # ── Step 4: Tiered mandatory injection ───────────────────────────
        anchor_nodes = []
        domain_nodes = []
        rrf_node_ids = set()

        for d in node_dicts:
            if d["node_type"] == "ANCHOR":
                anchor_nodes.append(d)
                rrf_node_ids.add(d["id"])
            elif d["node_type"] == "DOMAIN":
                domain_nodes.append(d)
                rrf_node_ids.add(d["id"])

        # Top RRF results (exclude already-injected ANCHOR/DOMAIN)
        top_rrf = []
        for nid, score in rrf_ranked:
            if nid not in rrf_node_ids and len(top_rrf) < TOP_RRF_RESULTS:
                if nid in node_map:
                    top_rrf.append(node_map[nid])
                    rrf_node_ids.add(nid)

        # Lateral context: activated nodes not in top-8
        lateral_context = []
        for nid, score in graph_results:
            if nid not in rrf_node_ids and nid in node_map:
                lateral_context.append(node_map[nid])

        # ── Step 5: Token budget filter ──────────────────────────────────
        total_tokens = 0
        for n in anchor_nodes + domain_nodes:
            total_tokens += self._estimate_tokens(n.get("content", ""))

        # Add top RRF nodes within budget
        budgeted_rrf = []
        for n in top_rrf:
            t = self._estimate_tokens(n.get("content", ""))
            if total_tokens + t <= TOKEN_BUDGET:
                budgeted_rrf.append(n)
                total_tokens += t
            else:
                break  # Stop adding — nodes are already sorted by RRF score

        # Add lateral context within remaining budget
        budgeted_lateral = []
        for n in lateral_context[:5]:  # cap lateral at 5
            t = self._estimate_tokens(n.get("content", ""))
            if total_tokens + t <= TOKEN_BUDGET:
                budgeted_lateral.append(n)
                total_tokens += t

        # ── Step 6: Assemble ─────────────────────────────────────────────
        all_used_ids = (
            [n["id"] for n in anchor_nodes]
            + [n["id"] for n in domain_nodes]
            + [n["id"] for n in budgeted_rrf]
            + [n["id"] for n in budgeted_lateral]
        )

        return RetrievalResult(
            anchor_nodes=anchor_nodes,
            domain_nodes=domain_nodes,
            retrieved_nodes=budgeted_rrf,
            lateral_context=budgeted_lateral,
            used_channels=used_channels,
            total_tokens_estimated=total_tokens,
            nodes_used_ids=all_used_ids,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Next-Scene Preloader
    # ──────────────────────────────────────────────────────────────────────

    async def preload_next_scene(
        self,
        last_3_messages: list[str],
        graph: MemoryGraph,
        db: AsyncSession,
        user_id: str,
        session_id: str,
    ) -> list[str]:
        """
        Predict which nodes will be needed next and cache them.

        Embeds the last 3 messages concatenated, runs semantic retrieval only,
        stores top-5 results in a dict cache keyed by session_id.
        Called after every response, used at the start of next retrieval.
        """
        if not last_3_messages:
            return []

        combined = " ".join(last_3_messages[-3:])
        query_embedding = _embed_text(combined)

        # Load active nodes
        import uuid
        result = await db.execute(select(Node).where(Node.is_archived == False, Node.user_id == uuid.UUID(user_id)))
        db_nodes = list(result.scalars().all())

        node_dicts = []
        for n in db_nodes:
            node_dicts.append({
                "id": str(n.id),
                "content": n.content,
                "embedding": list(n.embedding) if n.embedding is not None else None,
            })

        # Semantic-only retrieval
        semantic_results = self._semantic_channel(query_embedding, node_dicts)

        # Cache top-5
        preloaded = [nid for nid, _score in semantic_results[:5]]
        self._preload_cache[session_id] = preloaded

        logger.debug(f"Preloaded {len(preloaded)} nodes for session {session_id}")
        return preloaded
