"""
Mem-Rooted — FastAPI Application Entry Point

Wires all engines into a running HTTP server:
- DB pool + pgvector initialization
- Embedding model preload
- MemoryGraph initial build
- MemoryScheduler startup
- CORS for frontend
- Route mounting
"""

import logging
import sys
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from api.routes import chat, memory, auth
from core.placement import PlacementEngine
from core.retrieval import HybridRetriever
from core.scheduler import MemoryScheduler, SchedulerState
from db.connection import async_session_factory, close_db, engine, init_db
from db.models import Node
from graph.network import MemoryGraph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("mem-rooted")


# ══════════════════════════════════════════════════════════════════════════════
# Lifespan
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup:
        1. Initialize DB connection pool + pgvector extension + tables
        2. Load all-MiniLM-L6-v2 embedding model
        3. Build initial MemoryGraph from DB
        4. Start MemoryScheduler (5 background jobs)
        5. Download spaCy model if not present
        6. Initialize shared engines on app.state
    Shutdown:
        1. Stop scheduler gracefully
        2. Close DB connection pool
    """
    logger.info("═" * 60)
    logger.info("  Mem-Rooted — Starting up")
    logger.info("═" * 60)

    # ── 1. Database ──────────────────────────────────────────────────────
    logger.info("[Startup] Initializing database...")
    await init_db()
    app.state.db_connected = True
    logger.info("[Startup] Database initialized (pgvector enabled, tables created)")

    # ── 2. Embedding model ───────────────────────────────────────────────
    logger.info("[Startup] Loading embedding model (all-MiniLM-L6-v2)...")
    from sentence_transformers import SentenceTransformer
    app.state.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    app.state.model_loaded = True
    logger.info("[Startup] Embedding model loaded")

    # ── 3. spaCy model ───────────────────────────────────────────────────
    logger.info("[Startup] Checking spaCy model...")
    try:
        import spacy
        try:
            spacy.load("en_core_web_sm")
            logger.info("[Startup] spaCy en_core_web_sm already available")
        except OSError:
            logger.info("[Startup] Downloading spaCy en_core_web_sm...")
            from spacy.cli import download
            download("en_core_web_sm")
            logger.info("[Startup] spaCy model downloaded")
    except ImportError:
        logger.warning("[Startup] spaCy not installed — NER will be limited")

    # ── 4. MemoryGraph ───────────────────────────────────────────────────
    logger.info("[Startup] Building initial MemoryGraph...")
    app.state.graph = MemoryGraph()
    async with async_session_factory() as db:
        result = await db.execute(select(Node).where(Node.is_archived == False))
        all_nodes = list(result.scalars().all())
        app.state.graph.build_from_db(all_nodes)
    logger.info(f"[Startup] Graph built: {app.state.graph.node_count()} nodes, {app.state.graph.edge_count()} edges")

    # ── 5. Shared engines ────────────────────────────────────────────────
    app.state.retriever = HybridRetriever()
    app.state.placement_engine = PlacementEngine()
    logger.info("[Startup] Retriever and PlacementEngine initialized")

    # ── 6. Scheduler ─────────────────────────────────────────────────────
    logger.info("[Startup] Starting MemoryScheduler...")
    app.state.scheduler = MemoryScheduler()
    app.state.scheduler.start(async_session_factory, app.state.graph)
    logger.info("[Startup] Scheduler running with 5 background jobs")

    logger.info("═" * 60)
    logger.info("  Mem-Rooted — Ready")
    logger.info("═" * 60)

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────
    logger.info("[Shutdown] Stopping scheduler...")
    app.state.scheduler.stop()
    logger.info("[Shutdown] Closing database pool...")
    await close_db()
    logger.info("[Shutdown] Mem-Rooted shut down cleanly")


# ══════════════════════════════════════════════════════════════════════════════
# App
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Mem-Rooted API",
    description="Persona-centric hierarchical memory system for AI conversations",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ───────────────────────────────────────────────────────────────────# Mount Routes
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(memory.router, prefix="/api/memory", tags=["Memory"])


# ── Health Check ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check(request: Request):
    """System health check for monitoring."""
    db_ok = getattr(request.app.state, "db_connected", False)
    model_ok = getattr(request.app.state, "model_loaded", False)
    scheduler_state = SchedulerState()
    graph = getattr(request.app.state, "graph", None)

    return {
        "status": "healthy" if (db_ok and model_ok) else "degraded",
        "db_connected": db_ok,
        "model_loaded": model_ok,
        "scheduler_running": scheduler_state.scheduler_running,
        "node_count": graph.node_count() if graph else 0,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
