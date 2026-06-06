<div align="center">

# Mem-Rooted

*A Hierarchical, Self-Organizing Memory Architecture for Persona-Centric AI*

Built as a novel contribution to the AI memory systems research space, targeting LoCoMo and LongMemEval benchmark performance beyond existing state-of-the-art systems.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?style=flat-square&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi)
![Next.js](https://img.shields.io/badge/Next.js-15+-000000?style=flat-square&logo=next.js)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-4169E1?style=flat-square&logo=postgresql)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Status](https://img.shields.io/badge/Status-Research_Preview-orange?style=flat-square)

**The memory that knows who you are — not just what you said.**

</div>

---

## 🎯 The Problem Statement

The vast majority of current conversational AI agents are fundamentally stateless. When a session ends, the agent's context window is wiped clean, and any understanding of the user—their goals, preferences, and identity—vanishes. While short-term context windows have expanded immensely, relying on context injection alone fails to provide a persistent, evolving understanding of a human user across weeks, months, or years of interaction.

Existing memory systems (such as Mem0 and early LangChain architectures) attempt to solve this by dumping extracted facts into a flat vector database. In these systems, all facts are treated with identical structural importance. Your core identity (e.g., your name or profession) and an ephemeral fact (e.g., what you ate for lunch on Tuesday) are given the exact same architectural weight. Worse, because these systems often use contradiction-based overwriting, a highly critical identity fact can be accidentally overwritten or deleted if the LLM misinterprets a passing comment.

The consequence is severe: no existing open-source system builds a genuine, resilient understanding of who a person is, what they care about, and how their knowledge hierarchy naturally evolves over time without collapsing into a noisy, flat vector swamp. **Mem-Rooted is built to solve exactly this.**

---

## 🧠 What Mem-Rooted Does

Mem-Rooted completely abandons the flat vector database paradigm. Instead, the system builds a living knowledge network about the user that reorganizes itself continuously. It is not a database of disconnected facts, nor is it a chat log. It is a self-organizing hierarchy where facts must actively earn their position and persistence based on their semantic importance, frequency of recall, and relationship to the user's core identity.

Technically, Mem-Rooted operates a strict 4-tier graph topology. Every extracted fact is mathematically placed into the graph as one of four node types: ANCHOR, DOMAIN, CLUSTER, or INSTANCE. Rather than relying on an LLM to blindly classify where a node belongs, Mem-Rooted employs a deterministic bottom-up emergent placement algorithm using an "Overcome vs Subside" calculation. As the user's life context shifts, background Moving Memory workers dynamically adjust node topologies, while a four-way hybrid retrieval engine (fusing Semantic, Keyword, Graph, and Temporal scoring via Reciprocal Rank Fusion) ensures perfect context delivery.

```text
ANCHOR (Identity — Immutable)
  └── DOMAIN (Life Direction — Slow decay)
        └── CLUSTER (Sub-domain — Dynamic)
              └── INSTANCE (Atomic fact — Fast decay)
```
*Note: Lateral links form dynamic cross-branch connections between disparate clusters and domains, creating semantic bridges across the strict vertical hierarchy.*

---

## 🔬 Original Research Contributions

1. **Identity-Anchored Immutability**
   ANCHOR nodes (Tier 0) are constitutionally protected from automated deletion or content mutation. Extracted via rigid heuristic gates rather than purely subjective LLM judgment, these nodes form the bedrock of the graph. Any attempt by the system to overwrite an ANCHOR automatically resolves to a `BLOCKED_UPDATE` operation, logging the anomaly. No existing published architecture (Mem0, Hindsight, A-Mem, MemOS, Memory-R1) implements absolute tier-based immutability.

2. **Bottom-Up Emergent Hierarchy with Overcome vs Subside**
   No fact is pre-classified by the LLM into a permanent tier. Every fact earns its topological position dynamically through the `differentiating_score` cascade. When a new fact is introduced, the engine calculates its distance against the matched node. If the new fact's differentiating score ($1 - \text{cosine similarity}$) is lower than the matched node's stored score, it triggers an **Overcome** decision: the new fact usurps the parent position, and the older node is forcefully pushed down via the `push_down_node` cascade function. No existing paper implements topology-native position earning based on continuous semantic drift.

3. **Goal-Directed Decay Protection**
   Mem-Rooted introduces a mathematically formalized decay engine governed by the formula $D(t) = e^{-\lambda_{tier} \times t} \times \text{goal\_factor} \times \text{recall\_resilience}$. Crucially, the $\text{goal\_factor}$ drops to $0.5$ for nodes that are laterally linked to user-declared ANCHOR goals. This means the user's active life goals mathematically slow the memory decay of related tangential facts. No published paper currently parameterizes memory decay by graph-based goal alignment.

4. **Topology-Native Promotion and Demotion**
   Nodes traverse the vertical hierarchy autonomously over time based on a continuous composite weight calculation ($Physical \times 0.3 + Recall \times 0.5 + Semantic \times 0.2$). Highly recalled INSTANCEs are promoted to CLUSTERs, while neglected DOMAINs are demoted. No existing system reorganizes its own core memory topology strictly based on demonstrated usage importance without explicit user instruction.

5. **Moving Memory Background Engine**
   A completely decoupled asynchronous background orchestrator executes five scheduled sweeps: Decay Sweep (6h), Promotion Sweep (12h), Merge Sweep (24h), Split Sweep (24h offset), and Lateral Link Refresh (48h). The memory network physically restructures itself, culling weak nodes and consolidating semantic drift, without requiring any synchronous user input.

---

## 🏗️ Architecture Overview

```text
[USER INPUT] ──(Fast)──> Pre-write Sanitization Gate
                              │
                              ▼
[EXTRACTION] ──(LLM)───> spaCy NER + GPT-4o-mini Structured JSON
                              │
                              ▼
[PLACEMENT]  ──(Fast)──> Overcome vs Subside Cascade (Cosine Sim)
                              │
                              ▼
[OPERATIONS] ──(Fast)──> Graph Edge Mutation / push_down_node()
                              │
   ┌──────────────────────────┴──────────────────────────┐
   ▼                                                     ▼
[STORAGE] ──(Fast)──> PostgreSQL/pgvector             [GRAPH] ──(Fast)──> NetworkX / Lateral Links
   │                                                     │
   │           ┌─────────────────────────────────────────┤
   │           │                                         │
   ▼           ▼                                         ▼
[RETRIEVAL ENGINE] ──(Med)──> 4-Way RRF (Semantic + Keyword + Graph + Temporal)
                              │
                              ▼
[RESPONSE]   ──(LLM)───> GPT-4o-mini Prompt Assembly & Generation
                              │
                              ▼
[MOVING MEMORY] ─(Slow)─> Async APScheduler (Decay, Promote, Merge, Split)
```

| Component | Technology | Purpose |
| :--- | :--- | :--- |
| **Extraction Pipeline** | spaCy + GPT-4o-mini | Filters noise and extracts structured, atomic facts with temporal and anchor biasing. |
| **Placement Engine** | all-MiniLM-L6-v2 + Cascade | Executes the Overcome vs Subside algorithm to determine exact graph topology. |
| **Node Storage** | PostgreSQL + pgvector | Persistent storage for nodes, relationships, and dense embedding vectors. |
| **In-Memory Graph** | NetworkX | Rapid traversal for lateral link discovery and spreading activation algorithms. |
| **Semantic Retrieval** | pgvector cosine | High-dimensional similarity search for intent matching. |
| **Keyword Retrieval** | BM25Okapi via rank-bm25 | Sparse lexical retrieval for exact noun and entity matching. |
| **Graph Retrieval** | Spreading Activation | Traverses lateral edges to retrieve tangentially related context. |
| **Temporal Retrieval** | Recency Scoring | Prioritizes recently created or highly recalled nodes in the final pool. |
| **Fusion** | Reciprocal Rank Fusion (RRF) | Normalizes and combines the four distinct retrieval scores into a single ranked context. |
| **Background Engine** | APScheduler | Drives the autonomous Moving Memory restructuring sweeps. |
| **Response Generation** | GPT-4o-mini | Assembles the retrieved context block and streams the final conversational response. |
| **Frontend** | Next.js + Tailwind + shadcn/ui + Framer Motion | Provides a beautiful, interactive chat UI and a live transparency dashboard of the memory tree. |

---

## 🔄 The Seven-Phase Memory Lifecycle

1. **Extraction**
   *What it does:* Cleans raw user input, drops conversational noise, and extracts declarative atomic facts.
   *Technology:* spaCy heuristics combined with GPT-4o-mini structured JSON outputs.
   *Differentiator:* The dual-pass system prevents LLM hallucination on core identity extraction while catching nuanced, ephemeral facts.

2. **Placement**
   *What it does:* Determines exactly where a fact belongs in the hierarchical graph.
   *Technology:* Dense vector embeddings (SentenceTransformers) routed through the custom Cascade algorithm.
   *Differentiator:* Uses "Overcome vs Subside" logic, refusing to rely on an LLM to guess the structural importance of a fact.

3. **Operations**
   *What it does:* Executes the physical database commits, edge creations, and tree mutations.
   *Technology:* Async SQLAlchemy and NetworkX state syncing.
   *Differentiator:* Implements `push_down_node` to safely reparent entire branches of memory without breaking topological integrity.

4. **Weightage**
   *What it does:* Assigns initial physical and semantic weights to new nodes.
   *Technology:* Custom scoring algorithms factoring initial confidence and tier depth.
   *Differentiator:* Avoids flat Boolean importance; every node starts with a highly specific composite gravitational weight.

5. **Decay and Promotion**
   *What it does:* Simulates the Ebbinghaus forgetting curve, weakening unused memories and promoting highly referenced ones.
   *Technology:* APScheduler running exponential decay mathematics.
   *Differentiator:* Goal-directed decay actively protects facts that are laterally linked to the user's primary objectives.

6. **Hybrid Retrieval**
   *What it does:* Fetches the perfect contextual payload for the LLM during generation.
   *Technology:* 4-way Reciprocal Rank Fusion combining pgvector, BM25, NetworkX Spreading Activation, and Time-decay.
   *Differentiator:* Escapes the narrow trap of cosine similarity by incorporating exact lexical matches and graph-traversal context.

7. **Moving Memory**
   *What it does:* Continuously runs maintenance on the graph.
   *Technology:* APScheduler running merging, splitting, and edge-refresh algorithms.
   *Differentiator:* Makes the memory system self-healing and self-optimizing, functioning identically to human sleep consolidation.

---

## 📊 Benchmark Positioning

Our architecture specifically targets dominance in the **LoCoMo** (Long Context Memory) and **LongMemEval** benchmarking frameworks. The human ceiling for LoCoMo sits at roughly 87.9 F1. 

| System | LoCoMo Score (F1) | Key Mechanism |
| :--- | :--- | :--- |
| **Full-context GPT-4** | ~32.1% | Brute-force context window |
| **Mem0** | ~75.0% | Flat vector database with LLM routing |
| **A-Mem** | ~72.0% | Agentic LLM-driven updates |
| **MemOS** | ~78.0% | MemCube hierarchical summaries |
| **Memory-R1** | ~82.0% | Reinforcement learning on operations |
| **Hindsight** | 89.61% | Four-network + 4-way RRF |
| **Mem-Rooted** | **>85.0% (Projected)** | **Hierarchical + Overcome/Subside + 4-way RRF + Goal-directed decay** |

While Mem0 relies entirely on the LLM to decide what to insert, update, or delete in a flat vector space (which leads to catastrophic forgetting and identity overwrites under complex conversational drift), Mem-Rooted protects performance through topological guarantees. By locking ANCHORs from mutation and utilizing 4-way RRF during retrieval, Mem-Rooted eliminates the precision-recall trade-off that drags down flat vector stores, positioning it to consistently outperform systems reliant solely on LLM judgment.

---

## ⚔️ Comparison with Existing Systems

| Feature | Mem0 | A-Mem | MemoryBank | Hindsight | Mem-Rooted |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Identity Protection** | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Memory Hierarchy** | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Emergent Topology** | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Goal-Directed Decay** | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Promotion/Demotion** | ❌ | ❌ | ✅ | ❌ | ✅ |
| **4-way Hybrid Retrieval** | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Moving Memory Engine** | ❌ | ❌ | ✅ | ❌ | ✅ |
| **Version History on Contradiction** | ✅ | ✅ | ❌ | ❌ | ✅ |

---

## 📁 Project Structure

```text
mem-rooted/
├── backend/                  # FastAPI / Python Application
│   ├── main.py               # Application entry point and router setup
│   ├── api/                  # API layer
│   │   └── routes/           # Endpoints for chat, memory, and dashboard
│   ├── core/                 # Core business logic
│   │   ├── extraction.py     # NLP and LLM parsing pipeline
│   │   ├── placement.py      # Overcome vs Subside cascade algorithms
│   │   ├── operations.py     # Graph mutation and push_down_node logic
│   │   ├── retrieval.py      # 4-way RRF and spreading activation
│   │   └── background.py     # APScheduler Moving Memory sweeps
│   ├── db/                   # Database layer
│   │   ├── session.py        # Async SQLAlchemy configurations
│   │   └── models.py         # pgvector schema definitions
│   └── graph/                # In-memory synchronization
│       └── sync.py           # NetworkX state management
├── frontend/                 # Next.js / TypeScript Application
│   ├── app/                  # App router pages (Chat & Dashboard)
│   ├── components/           # React component library
│   │   ├── chat/             # Conversational interface elements
│   │   ├── memory/           # Memory Tree transparency panel 
│   │   └── dashboard/        # Analytics and graph visualization
│   └── lib/                  # Utilities and API clients
│       └── api.ts            # Client interface for FastAPI backend
├── docker-compose.yml        # PostgreSQL + pgvector container definition
└── .env.example              # Environment variable template
```

---

## 🚀 Getting Started

### Prerequisites
- **Python:** 3.11 or higher
- **Node.js:** 18 or higher
- **Docker:** Required for running the pgvector PostgreSQL database
- **API Keys:** A valid OpenAI API Key (`sk-...`)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/mem-rooted.git
   cd mem-rooted
   ```

2. **Backend Setup:**
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   pip install -r requirements.txt
   ```

3. **Frontend Setup:**
   ```bash
   cd ../frontend
   npm install
   ```

### Environment Setup
1. Copy the example environment file in the backend directory:
   ```bash
   cd backend
   cp .env.example .env
   ```
2. Fill in the `.env` file with your `OPENAI_API_KEY` and ensure the database URL matches the Docker configuration.

### Running the System

1. **Start the Database:**
   ```bash
   docker-compose up -d
   ```
2. **Run the Backend Server:**
   ```bash
   cd backend
   source venv/bin/activate
   python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
   ```
3. **Run the Frontend Server:**
   ```bash
   cd frontend
   npm run dev
   ```

### Accessing
- **Chat Interface:** Open `http://localhost:3000`
- **Memory Dashboard:** Open `http://localhost:3000/dashboard`

---

## 🛡️ Memory Security

Mem-Rooted implements a robust seven-layer security architecture designed specifically to address the OWASP ASI06 (Memory and Context Poisoning) threat model.

1. **Pre-write Sanitization Gate:** Strict regex and NLP pattern detection filters out prompt injection attempts, blocks PII boundary violations, and enforces rate limits before hitting the LLM extraction phase.
2. **Consensus-Based Validation:** Inspired by A-MemGuard, the retrieval engine actively flags newly inserted facts that wildly contradict the semantic baseline of highly-trusted established clusters.
3. **HMAC Integrity on ANCHOR Nodes:** Core identity facts are cryptographically hashed at the database level, preventing any unauthorized SQL-level tampering from altering the agent's foundational persona alignment.
4. **Behavioral Drift Detection:** The background engine continuously calculates the semantic centroid of DOMAIN nodes. Rapid, anomalous centroid drift triggers an isolation protocol, preventing poisoned memory from cascading to the rest of the graph.
5. **Full Provenance Tracking:** Every node strictly inherits a source session hash, a timestamp, extraction stage lineage, and confidence scores, guaranteeing 100% auditability of how a memory was formed.
6. **Cascade Protection on OVERCOME:** The mathematical `differentiating_score` requires an overwhelming confidence threshold (adjusted by the physical resilience weight of the target node) to trigger an Overcome event, making malicious context replacement exponentially difficult against mature memories.
7. **GDPR Compliance:** Standardized `hard_delete` operations mapped to user provenance allow for immediate, cascading destruction of specific data branches upon user request, ensuring legal compliance natively within the graph structure.

---

## 📄 Research Paper

A formal research paper documenting the Mem-Rooted architecture and benchmark results is currently in preparation. The paper contextualizes our system against the current state-of-the-art, drawing citations and inspiration from:
- *MemGPT / Letta* (Packer et al., 2023)
- *MemoryBank* (Zhong et al., 2024)
- *Mem0* (Chhikara et al., 2025)
- *A-Mem* (Xu et al., 2025)
- *Memory-R1* (Yan et al., 2025)
- *MemOS* (Li et al., 2025)
- *Hindsight* (Latimer et al., 2025)

Our primary novel contributions relative to these works are **identity-anchored immutability**, **goal-directed decay protection**, and **topology-native emergent hierarchy via Overcome vs Subside cascade mechanics.**

---

## 🛠️ Tech Stack

| Backend | Frontend |
| :--- | :--- |
| **Python** (3.11+) | **Next.js** (15+) |
| **FastAPI** (0.115+) | **React** (18+) |
| **PostgreSQL** (16+) | **TypeScript** |
| **pgvector** (0.3.6) | **Tailwind CSS** |
| **SQLAlchemy Async** (2.0+) | **shadcn/ui** |
| **NetworkX** (3.4+) | **Framer Motion** |
| **SentenceTransformers** (3.3+) | **Lucide Icons** |
| **spaCy** | **Axios** |
| **APScheduler** (3.10+) | |

---

## 🤝 Contributing

Mem-Rooted is a research project actively under development. We are continually looking for edge cases in the placement algorithms and optimizations for the Moving Memory sweeps. We warmly invite issues, architectural discussions, and pull requests from both the research and open-source software engineering communities.

Please refer to the Issues tab to see current focal areas or to report unexpected hierarchical behavior.

---

## 📜 License

This project is licensed under the MIT License. See the `LICENSE` file for details.

---

## 🙏 Acknowledgements

Mem-Rooted stands on the shoulders of brilliant foundational research in the AI memory space. We specifically acknowledge:
- **Mem0** for establishing the modern operation set vocabulary.
- **Hindsight** for pioneering the four-way hybrid retrieval concept with Reciprocal Rank Fusion.
- **MemoryBank** for providing the Ebbinghaus exponential decay foundation.
- **MemOS** for the MemCube metadata structure and the concept of a Next-Scene Preloader.
- **A-Mem** for the early inspiration regarding lateral knowledge linking.
- **Memory-R1** for directing the field toward reinforcement-trained memory operation decisions.
