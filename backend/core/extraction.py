"""
Mem-Rooted — Two-Stage Memory Extraction Pipeline

Stage 1: Fast Rule Gate (no LLM)
    - Filters noise, questions, and short messages
    - Extracts named entities via spaCy en_core_web_sm
    - Detects temporal markers and biases candidate_type accordingly
    - Produces rule-based MemoryCandidate classifications

Stage 2: LLM Structured Extraction (gpt-4o-mini)
    - Extracts atomic facts with structured JSON output
    - Classifies each fact as ANCHOR / DOMAIN / CLUSTER / INSTANCE
    - Assigns confidence 0.0–1.0

Merge: If both stages agree on type → confidence boosted.
       If they disagree → LLM wins, confidence capped at 0.6.
"""

import json
import logging
import os
import re
from enum import Enum
from typing import Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Pydantic Models
# ══════════════════════════════════════════════════════════════════════════════

class CandidateType(str, Enum):
    """The four hierarchical node roles."""
    ANCHOR = "ANCHOR"
    DOMAIN = "DOMAIN"
    CLUSTER = "CLUSTER"
    INSTANCE = "INSTANCE"


class MemoryCandidate(BaseModel):
    """A single structured memory candidate extracted from a user message."""
    content: str = Field(..., description="The atomic fact extracted")
    candidate_type: CandidateType = Field(..., description="ANCHOR / DOMAIN / CLUSTER / INSTANCE")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Extraction confidence")
    entities: list[str] = Field(default_factory=list, description="Named entities found")
    is_question: bool = Field(default=False, description="Whether this is a question")
    is_noise: bool = Field(default=False, description="Whether this is noise/filler")
    temporal_markers: list[str] = Field(default_factory=list, description="Time words found")
    source: str = Field(default="rule", description="Which stage produced this: rule | llm | merged")


class ExtractionResult(BaseModel):
    """Complete result of the two-stage extraction pipeline."""
    candidates: list[MemoryCandidate] = Field(default_factory=list)
    raw_message: str = Field(default="")
    stage1_passed: bool = Field(default=False, description="Whether the message passed the rule gate")
    stage2_called: bool = Field(default=False, description="Whether LLM extraction was invoked")


# ══════════════════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════════════════

NOISE_PATTERNS: set[str] = {
    "thanks", "thank you", "thx", "ty", "ok", "okay", "k",
    "lol", "lmao", "haha", "hehe", "xd",
    "got it", "sure", "yes", "no", "yep", "yeah", "nah", "nope",
    "cool", "nice", "great", "awesome", "amazing", "wow",
    "hmm", "hm", "uh", "um", "idk",
    "bye", "goodbye", "see ya", "later",
    "hi", "hello", "hey", "sup", "yo", "what's up",
}

# Temporal marker groups — each maps to a candidate_type bias
PERMANENT_MARKERS: list[str] = [
    "always", "forever", "my whole life", "since birth",
    "i am", "i'm from", "my name is", "i've always",
    "i will always", "i was born", "i identify as",
    "my religion", "my faith", "i believe in",
    "i'm called", "people call me", "my nationality",
]

LONGTERM_MARKERS: list[str] = [
    "i work", "i study", "my goal", "i want to become",
    "my job", "i'm studying", "my career", "i plan to",
    "my dream", "i majored in", "my profession",
    "i've been working", "my company", "my field",
    "i'm learning", "my hobby", "my passion",
    "i exercise", "my diet", "my routine",
]

SHORTTERM_MARKERS: list[str] = [
    "lately", "these days", "right now", "currently",
    "this week", "today", "recently", "at the moment",
    "just now", "this morning", "tonight", "yesterday",
    "last week", "this month", "at present", "for now",
    "temporarily", "this semester", "this quarter",
]

# Question patterns
QUESTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*(what|who|where|when|why|how|is|are|do|does|did|can|could|would|should|will|shall)\b", re.IGNORECASE),
    re.compile(r"\?\s*$"),
]


# ══════════════════════════════════════════════════════════════════════════════
# spaCy Model Loading
# ══════════════════════════════════════════════════════════════════════════════

_nlp = None


def _get_nlp():
    """Lazy-load spaCy model. Downloads en_core_web_sm if not present."""
    global _nlp
    if _nlp is not None:
        return _nlp

    try:
        import spacy
        try:
            _nlp = spacy.load("en_core_web_sm")
        except OSError:
            logger.warning("spaCy model 'en_core_web_sm' not found. Downloading...")
            from spacy.cli import download
            download("en_core_web_sm")
            _nlp = spacy.load("en_core_web_sm")
        return _nlp
    except ImportError:
        logger.error("spaCy is not installed. NER extraction will be skipped.")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# OpenAI Client
# ══════════════════════════════════════════════════════════════════════════════

_openai_client: Optional[AsyncOpenAI] = None


def _get_openai_client() -> AsyncOpenAI:
    """Lazy-initialize the async OpenAI client."""
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", ""),
        )
    return _openai_client


# ══════════════════════════════════════════════════════════════════════════════
# Stage 1 — Fast Rule Gate
# ══════════════════════════════════════════════════════════════════════════════

def _is_noise(message: str) -> bool:
    """Check if the message matches known noise/filler patterns."""
    cleaned = message.strip().lower().rstrip("!.,?")
    return cleaned in NOISE_PATTERNS


def _is_question_only(message: str) -> bool:
    """Check if the message is purely a question with no declarative facts."""
    sentences = re.split(r"[.!]", message)
    non_question_sentences = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        is_q = any(p.search(s) for p in QUESTION_PATTERNS)
        if not is_q:
            non_question_sentences.append(s)
    # If every sentence is a question, it's question-only
    return len(non_question_sentences) == 0


def _is_too_short(message: str) -> bool:
    """Check if the message has fewer than 4 meaningful tokens."""
    tokens = message.strip().split()
    return len(tokens) < 4


def _extract_entities(message: str) -> list[str]:
    """Extract named entities using spaCy. Returns entity text list."""
    nlp = _get_nlp()
    if nlp is None:
        return []

    doc = nlp(message)
    target_labels = {"PERSON", "GPE", "ORG", "DATE", "CARDINAL"}
    entities = []
    for ent in doc.ents:
        if ent.label_ in target_labels:
            entities.append(ent.text)
    return entities


def _detect_temporal_markers(message: str) -> tuple[list[str], Optional[CandidateType]]:
    """
    Scan message for temporal markers.
    Returns (found_markers, type_bias).
    type_bias is the candidate_type suggested by the strongest marker group.
    Priority: PERMANENT > LONGTERM > SHORTTERM
    """
    msg_lower = message.lower()
    found_markers: list[str] = []
    permanent_hits = 0
    longterm_hits = 0
    shortterm_hits = 0

    for marker in PERMANENT_MARKERS:
        if marker in msg_lower:
            found_markers.append(marker)
            permanent_hits += 1

    for marker in LONGTERM_MARKERS:
        if marker in msg_lower:
            found_markers.append(marker)
            longterm_hits += 1

    for marker in SHORTTERM_MARKERS:
        if marker in msg_lower:
            found_markers.append(marker)
            shortterm_hits += 1

    # Determine bias — strongest marker group wins
    if permanent_hits > 0 and permanent_hits >= longterm_hits and permanent_hits >= shortterm_hits:
        return found_markers, CandidateType.ANCHOR
    elif longterm_hits > 0 and longterm_hits >= shortterm_hits:
        # DOMAIN for broad life-direction markers, CLUSTER for sub-topic ones
        if any(m in msg_lower for m in ["my goal", "my career", "my dream", "my field", "my passion"]):
            return found_markers, CandidateType.DOMAIN
        return found_markers, CandidateType.CLUSTER
    elif shortterm_hits > 0:
        return found_markers, CandidateType.INSTANCE
    else:
        return found_markers, None


def _classify_by_rules(
    message: str,
    entities: list[str],
    temporal_bias: Optional[CandidateType],
    temporal_markers: list[str],
) -> list[MemoryCandidate]:
    """
    Rule-based classification of the message into memory candidates.
    Splits compound sentences into individual facts where possible.
    """
    # Split on sentence boundaries for multi-fact messages
    sentences = re.split(r"(?<=[.!])\s+", message.strip())
    sentences = [s.strip() for s in sentences if s.strip() and len(s.strip().split()) >= 3]

    # If no clean sentences, treat the whole message as one fact
    if not sentences:
        sentences = [message.strip()]

    candidates: list[MemoryCandidate] = []

    for sentence in sentences:
        # Skip pure questions within compound messages
        if any(p.search(sentence) for p in QUESTION_PATTERNS):
            continue

        sent_lower = sentence.lower()

        # Determine candidate type from rules
        candidate_type = CandidateType.INSTANCE  # default
        confidence = 0.5

        if temporal_bias is not None:
            candidate_type = temporal_bias
            confidence = 0.6

        # Override with stronger signal from sentence-level patterns
        # ANCHOR signals: identity statements
        anchor_patterns = [
            r"\bmy name is\b", r"\bi am\b(?!\s+going)", r"\bi'm from\b",
            r"\bi was born\b", r"\bi identify as\b", r"\bi believe in\b",
            r"\bmy religion\b", r"\bmy nationality\b",
        ]
        if any(re.search(p, sent_lower) for p in anchor_patterns):
            candidate_type = CandidateType.ANCHOR
            confidence = 0.8

        # DOMAIN signals: broad life direction
        domain_patterns = [
            r"\bmy career\b", r"\bmy goal\b", r"\bmy dream\b",
            r"\bi work (?:at|in|as)\b", r"\bi study\b", r"\bmy profession\b",
            r"\bmy passion\b", r"\bmy field\b",
        ]
        if any(re.search(p, sent_lower) for p in domain_patterns):
            candidate_type = CandidateType.DOMAIN
            confidence = 0.7

        # CLUSTER signals: specific sub-domain topics
        cluster_patterns = [
            r"\bi'm learning\b", r"\bi've been working on\b",
            r"\bmy project\b", r"\bmy hobby\b", r"\bmy routine\b",
            r"\bi'm studying\b", r"\bmy diet\b",
        ]
        if any(re.search(p, sent_lower) for p in cluster_patterns):
            candidate_type = CandidateType.CLUSTER
            confidence = 0.65

        # Detect question flag per sentence
        is_q = any(p.search(sentence) for p in QUESTION_PATTERNS)

        candidates.append(MemoryCandidate(
            content=sentence,
            candidate_type=candidate_type,
            confidence=confidence,
            entities=entities,
            is_question=is_q,
            is_noise=False,
            temporal_markers=temporal_markers,
            source="rule",
        ))

    return candidates


def run_stage1(message: str) -> tuple[bool, list[MemoryCandidate]]:
    """
    Stage 1 — Fast Rule Gate.
    Returns (passed: bool, candidates: list).
    If passed is False, the message should not proceed to Stage 2.
    """
    # Gate checks
    if _is_noise(message):
        return False, [MemoryCandidate(
            content=message,
            candidate_type=CandidateType.INSTANCE,
            confidence=0.0,
            is_noise=True,
            is_question=False,
            source="rule",
        )]

    if _is_too_short(message):
        return False, []

    if _is_question_only(message):
        return False, [MemoryCandidate(
            content=message,
            candidate_type=CandidateType.INSTANCE,
            confidence=0.0,
            is_question=True,
            is_noise=False,
            source="rule",
        )]

    # Extract features
    entities = _extract_entities(message)
    temporal_markers, temporal_bias = _detect_temporal_markers(message)

    # Classify
    candidates = _classify_by_rules(message, entities, temporal_bias, temporal_markers)

    return True, candidates


# ══════════════════════════════════════════════════════════════════════════════
# Stage 2 — LLM Structured Extraction
# ══════════════════════════════════════════════════════════════════════════════

_LLM_SYSTEM_PROMPT = """You are a memory extraction engine for an AI memory system called Mem-Rooted.

Your job: given a user message, extract ONLY atomic, storable facts. Ignore questions, filler, pleasantries, and noise.

For each fact, classify it into exactly one type:
- ANCHOR: Immutable identity facts. Name, nationality, core beliefs, permanent traits, gender, religion. Things that define WHO the person IS and will not change.
- DOMAIN: Major life directions. Career field, area of study, health goals, major hobbies, long-term projects. These are broad life themes.
- CLUSTER: Specific knowledge areas within a domain. A particular technology they're learning, a specific exercise routine, a sub-project, a course they're taking.
- INSTANCE: Ephemeral, time-bound facts from this moment. What they did today, how they're feeling right now, a temporary situation.

Rules:
1. Extract ONLY declarative facts. Skip questions entirely.
2. Each fact should be ONE atomic statement — not compound.
3. Assign confidence 0.0–1.0 based on how certain you are about the classification.
4. If the message contains no storable facts, return an empty facts array.
5. Prefer higher-tier classifications when evidence is strong (e.g., "my name is X" is clearly ANCHOR, not INSTANCE).
"""

_EXTRACTION_JSON_SCHEMA = {
    "name": "memory_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The atomic fact extracted from the message",
                        },
                        "candidate_type": {
                            "type": "string",
                            "enum": ["ANCHOR", "DOMAIN", "CLUSTER", "INSTANCE"],
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Classification confidence 0.0–1.0",
                        },
                    },
                    "required": ["content", "candidate_type", "confidence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["facts"],
        "additionalProperties": False,
    },
}


async def run_stage2(message: str) -> list[MemoryCandidate]:
    """
    Stage 2 — LLM Structured Extraction via gpt-4o-mini.
    Returns a list of MemoryCandidate objects from the LLM.
    """
    client = _get_openai_client()
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": _EXTRACTION_JSON_SCHEMA,
            },
            temperature=0.1,
            max_tokens=1024,
        )

        raw_content = response.choices[0].message.content
        if not raw_content:
            logger.warning("LLM returned empty content for extraction.")
            return []

        parsed = json.loads(raw_content)
        facts = parsed.get("facts", [])

        candidates: list[MemoryCandidate] = []
        for fact in facts:
            candidates.append(MemoryCandidate(
                content=fact["content"],
                candidate_type=CandidateType(fact["candidate_type"]),
                confidence=max(0.0, min(1.0, fact["confidence"])),
                entities=[],
                is_question=False,
                is_noise=False,
                temporal_markers=[],
                source="llm",
            ))

        return candidates

    except Exception as e:
        logger.error(f"LLM extraction failed: {e}", exc_info=True)
        return []


# ══════════════════════════════════════════════════════════════════════════════
# Merge Logic
# ══════════════════════════════════════════════════════════════════════════════

def _merge_candidates(
    stage1_candidates: list[MemoryCandidate],
    stage2_candidates: list[MemoryCandidate],
) -> list[MemoryCandidate]:
    """
    Merge rule-based (Stage 1) and LLM (Stage 2) candidates.

    Strategy:
    - For each LLM candidate, find the best-matching Stage 1 candidate by content overlap.
    - If both stages agree on candidate_type → confidence gets a 20% boost (capped at 0.95).
    - If they disagree → LLM type wins, but confidence is capped at 0.6.
    - LLM candidates with no Stage 1 match are kept as-is.
    - Stage 1 candidates with no LLM match are kept with reduced confidence.
    """
    if not stage2_candidates:
        return stage1_candidates
    if not stage1_candidates:
        return stage2_candidates

    merged: list[MemoryCandidate] = []
    used_stage1_indices: set[int] = set()

    for llm_cand in stage2_candidates:
        best_match_idx: Optional[int] = None
        best_overlap: float = 0.0

        # Find best-matching Stage 1 candidate by word overlap
        llm_words = set(llm_cand.content.lower().split())
        for i, rule_cand in enumerate(stage1_candidates):
            if i in used_stage1_indices:
                continue
            rule_words = set(rule_cand.content.lower().split())
            if not rule_words or not llm_words:
                continue
            overlap = len(llm_words & rule_words) / max(len(llm_words), len(rule_words))
            if overlap > best_overlap:
                best_overlap = overlap
                best_match_idx = i

        if best_match_idx is not None and best_overlap > 0.3:
            rule_cand = stage1_candidates[best_match_idx]
            used_stage1_indices.add(best_match_idx)

            # Merge entities and temporal markers from Stage 1
            merged_entities = list(set(llm_cand.entities + rule_cand.entities))
            merged_markers = list(set(llm_cand.temporal_markers + rule_cand.temporal_markers))

            # Agreement check
            if llm_cand.candidate_type == rule_cand.candidate_type:
                # Both agree — boost confidence by 20%, cap at 0.95
                boosted_confidence = min(0.95, max(llm_cand.confidence, rule_cand.confidence) * 1.2)
                merged.append(MemoryCandidate(
                    content=llm_cand.content,
                    candidate_type=llm_cand.candidate_type,
                    confidence=round(boosted_confidence, 3),
                    entities=merged_entities,
                    is_question=False,
                    is_noise=False,
                    temporal_markers=merged_markers,
                    source="merged",
                ))
            else:
                # Disagree — LLM wins, cap confidence at 0.6
                capped_confidence = min(0.6, llm_cand.confidence)
                merged.append(MemoryCandidate(
                    content=llm_cand.content,
                    candidate_type=llm_cand.candidate_type,
                    confidence=round(capped_confidence, 3),
                    entities=merged_entities,
                    is_question=False,
                    is_noise=False,
                    temporal_markers=merged_markers,
                    source="merged",
                ))
        else:
            # No Stage 1 match — keep LLM candidate as-is
            merged.append(llm_cand)

    # Keep unmatched Stage 1 candidates with reduced confidence
    for i, rule_cand in enumerate(stage1_candidates):
        if i not in used_stage1_indices and not rule_cand.is_noise and not rule_cand.is_question:
            rule_cand.confidence = round(rule_cand.confidence * 0.7, 3)
            rule_cand.source = "rule"
            merged.append(rule_cand)

    return merged


# ══════════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ══════════════════════════════════════════════════════════════════════════════

async def extract_memories(message: str) -> ExtractionResult:
    """
    Full two-stage extraction pipeline.

    1. Run Stage 1 (fast rule gate) — filter noise, extract entities, classify.
    2. If Stage 1 passes, run Stage 2 (LLM structured extraction).
    3. Merge both stages' results.
    4. Return ExtractionResult with all candidates.
    """
    result = ExtractionResult(raw_message=message)

    if not message or not message.strip():
        return result

    # ── Stage 1 ──────────────────────────────────────────────────────────
    stage1_passed, stage1_candidates = run_stage1(message)
    result.stage1_passed = stage1_passed

    if not stage1_passed:
        # Message is noise, question-only, or too short — no LLM call
        result.candidates = stage1_candidates
        return result

    # ── Stage 2 ──────────────────────────────────────────────────────────
    result.stage2_called = True
    stage2_candidates = await run_stage2(message)

    # ── Merge ────────────────────────────────────────────────────────────
    if stage2_candidates:
        result.candidates = _merge_candidates(stage1_candidates, stage2_candidates)
    else:
        # LLM failed or returned nothing — fall back to Stage 1 only
        result.candidates = stage1_candidates

    return result
