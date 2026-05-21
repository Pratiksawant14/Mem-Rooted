"""
Mem-Rooted — PostgreSQL Schema for the Hierarchical Node Network
Every memory node in the system is a row in the `nodes` table.
"""

import enum
import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


# ── Base ──────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Declarative base for all Mem-Rooted models."""
    pass


# ── Enums ─────────────────────────────────────────────────────────────────────

class NodeType(str, enum.Enum):
    """The four hierarchical node roles."""
    ANCHOR = "ANCHOR"
    DOMAIN = "DOMAIN"
    CLUSTER = "CLUSTER"
    INSTANCE = "INSTANCE"


class PriorityFlag(str, enum.Enum):
    """Priority classification for decay and retrieval."""
    IMMUTABLE = "IMMUTABLE"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ── User Model ────────────────────────────────────────────────────────────────

class User(Base):
    """A user of the Mem-Rooted system."""

    __tablename__ = "users"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    username = Column(String(255), unique=True, nullable=False, index=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    nodes = relationship("Node", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")


# ── Node Model ────────────────────────────────────────────────────────────────

class Node(Base):
    """
    Central table: every memory in Mem-Rooted is a Node.

    Hierarchy: ANCHOR → DOMAIN → CLUSTER → INSTANCE
    Nodes promote upward, decay over time, and link laterally.
    """

    __tablename__ = "nodes"

    # ── Identity ──────────────────────────────────────────────────────────────
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    name = Column(String(512), nullable=False, index=True)
    node_type = Column(
        Enum(NodeType, name="node_type_enum", create_constraint=True),
        nullable=False,
        index=True,
    )
    content = Column(Text, nullable=False)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Hierarchy ─────────────────────────────────────────────────────────────
    parent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tier_level = Column(
        Integer,
        nullable=False,
        default=0,
        comment="0=ANCHOR, 1=DOMAIN, 2=CLUSTER, 3=INSTANCE",
    )

    # ── Weightage System ──────────────────────────────────────────────────────
    physical_weight = Column(
        Float, nullable=False, default=0.0,
        comment="Count of descendant nodes below this node",
    )
    recall_weight = Column(
        Float, nullable=False, default=0.0,
        comment="Frequency-based weight, boosted by ANCHOR goal alignment",
    )
    semantic_weight = Column(
        Float, nullable=False, default=1.0,
        comment="Cosine similarity to parent embedding (1.0 = perfect fit)",
    )
    composite_weight = Column(
        Float, nullable=False, default=0.0,
        comment="Combined weight: f(physical, recall, semantic)",
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    decay_score = Column(
        Float, nullable=False, default=1.0,
        comment="1.0 = fresh, decays toward 0.0 over time",
    )
    promotion_score = Column(
        Float, nullable=False, default=0.0,
        comment="Accumulated score toward promotion threshold",
    )

    # ── Lateral Links ─────────────────────────────────────────────────────────
    lateral_links = Column(
        JSONB, nullable=False, default=list,
        comment='Array of {"target_id": uuid, "similarity": float, "created_at": iso}',
    )

    # ── Embedding ─────────────────────────────────────────────────────────────
    embedding = Column(
        Vector(384),
        nullable=True,
        comment="all-MiniLM-L6-v2 embedding (384 dimensions)",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_recalled_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last time this node was accessed/retrieved",
    )

    # ── Session Provenance ────────────────────────────────────────────────────
    source_session_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="Conversation session that created this node",
    )

    # ── Priority & Operations ─────────────────────────────────────────────────
    priority_flag = Column(
        Enum(PriorityFlag, name="priority_flag_enum", create_constraint=True),
        nullable=False,
        default=PriorityFlag.MEDIUM,
    )
    operation_log = Column(
        JSONB, nullable=False, default=list,
        comment='Array of {"op": str, "timestamp": iso, "details": dict}',
    )

    # ── Archival ──────────────────────────────────────────────────────────────
    is_archived = Column(
        Boolean, nullable=False, default=False,
        comment="Archived nodes are excluded from retrieval but never deleted",
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    parent = relationship(
        "Node",
        remote_side=[id],
        back_populates="children",
        lazy="selectin",
    )
    children = relationship(
        "Node",
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    user = relationship("User", back_populates="nodes")

    def __repr__(self) -> str:
        return (
            f"<Node(id={self.id!s:.8}, type={self.node_type.value}, "
            f"name={self.name!r}, tier={self.tier_level}, "
            f"cw={self.composite_weight:.3f}, archived={self.is_archived})>"
        )


# ── Sessions Table ────────────────────────────────────────────────────────────

class Session(Base):
    """Conversation session metadata for provenance tracking."""

    __tablename__ = "sessions"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    ended_at = Column(DateTime(timezone=True), nullable=True)
    message_count = Column(Integer, nullable=False, default=0)
    summary = Column(Text, nullable=True)

    user = relationship("User", back_populates="sessions")

    def __repr__(self) -> str:
        return f"<Session(id={self.id!s:.8}, messages={self.message_count})>"


# ── Messages Table ────────────────────────────────────────────────────────────

class Message(Base):
    """Individual chat messages within a session."""

    __tablename__ = "messages"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(
        String(20),
        nullable=False,
        comment="user | assistant | system",
    )
    content = Column(Text, nullable=False)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    node_ids_used = Column(
        JSONB, nullable=False, default=list,
        comment="Node IDs that influenced this response (memory transparency)",
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id!s:.8}, role={self.role})>"


# ── Indexes ───────────────────────────────────────────────────────────────────

# Composite index for active node retrieval (non-archived, by type)
Index(
    "ix_nodes_active_by_type",
    Node.user_id,
    Node.node_type,
    Node.is_archived,
    Node.composite_weight.desc(),
)

# Index for decay scanning (background job)
Index(
    "ix_nodes_decay_scan",
    Node.user_id,
    Node.is_archived,
    Node.decay_score,
    Node.node_type,
)

# Index for session message ordering
Index(
    "ix_messages_session_order",
    Message.session_id,
    Message.created_at,
)
