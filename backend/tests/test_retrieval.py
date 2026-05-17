import pytest
from core.retrieval import HybridRetriever
from graph.network import MemoryGraph
from db.models import Node
from tests.mock_data import MOCK_ANCHOR_NODES, MOCK_DOMAIN_NODES, MOCK_CLUSTER_NODES, MOCK_INSTANCE_NODES

@pytest.fixture
def mock_nodes():
    nodes = []
    for data in MOCK_ANCHOR_NODES + MOCK_DOMAIN_NODES + MOCK_CLUSTER_NODES + MOCK_INSTANCE_NODES:
        n = Node(**data)
        nodes.append(n)
    return nodes

@pytest.fixture
def graph(mock_nodes):
    g = MemoryGraph()
    g.build_from_db(mock_nodes)
    return g

@pytest.fixture
def retriever(graph):
    # Mock embedding model
    class MockModel:
        def encode(self, text):
            return [0.1] * 384
    
    return HybridRetriever(db_session=None, embedding_model=MockModel(), graph=graph)

@pytest.mark.asyncio
async def test_semantic_channel(retriever, mock_nodes):
    # We mock the semantic search to return the domain node
    retriever._semantic_search = lambda q, n, e: [n for n in mock_nodes if n.node_type == "DOMAIN"]
    
    results = await retriever.retrieve("software architecture career", session_id="test")
    # Due to mandatory injection, ANCHOR should also be there, plus DOMAIN
    assert any(r.node_type == "DOMAIN" for r in results)

@pytest.mark.asyncio
async def test_bm25_channel(retriever, mock_nodes):
    # Mock bm25 to return cluster 1
    retriever._bm25_search = lambda q, n: [n for n in mock_nodes if n.id == "node_cluster_1"]
    
    results = await retriever.retrieve("cycling", session_id="test")
    assert any(r.id == "node_cluster_1" for r in results)

@pytest.mark.asyncio
async def test_graph_channel(retriever, mock_nodes):
    # Mock entity extraction and graph
    retriever._graph_search = lambda e, g, n: [n for n in mock_nodes if n.node_type == "DOMAIN"]
    
    results = await retriever.retrieve("Arjun", session_id="test")
    assert any(r.node_type == "DOMAIN" for r in results)

@pytest.mark.asyncio
async def test_temporal_channel(retriever, mock_nodes):
    retriever._temporal_search = lambda q, n: [n for n in mock_nodes if n.node_type == "INSTANCE"]
    
    results = await retriever.retrieve("what did I say lately", session_id="test")
    assert any(r.node_type == "INSTANCE" for r in results)

@pytest.mark.asyncio
async def test_mandatory_injection(retriever, mock_nodes):
    # Even if all searches return empty, ANCHOR and DOMAIN should be injected
    retriever._semantic_search = lambda q, n, e: []
    retriever._bm25_search = lambda q, n: []
    retriever._graph_search = lambda e, g, n: []
    retriever._temporal_search = lambda q, n: []
    
    # We need to mock db query for mandatory nodes
    retriever.db = type('MockDB', (), {'execute': lambda self, stmt: type('Result', (), {'scalars': lambda: type('Scalars', (), {'all': lambda: [n for n in mock_nodes if n.node_type in ["ANCHOR", "DOMAIN"]]})})()})()
    
    results = await retriever.retrieve("what is 2+2", session_id="test")
    types = [r.node_type for r in results]
    assert "ANCHOR" in types
    assert "DOMAIN" in types

@pytest.mark.asyncio
async def test_token_budget(retriever, mock_nodes):
    # If budget exceeded, lowest ranked instance/cluster dropped
    # We pass mock nodes through _enforce_token_budget
    
    # Let's say max_tokens is 50, and each node is 20
    # 5 nodes = 100 tokens -> needs drop
    
    dropped = retriever._enforce_token_budget(mock_nodes, max_tokens=50)
    # Should keep ANCHOR and DOMAIN, drop INSTANCE/CLUSTER
    assert len(dropped) < len(mock_nodes)
    assert any(n.node_type == "ANCHOR" for n in dropped)
    assert not any(n.node_type == "INSTANCE" for n in dropped) # Because it ranks lowest

@pytest.mark.asyncio
async def test_preloader(retriever, mock_nodes):
    await retriever.preload_next_scene(mock_nodes, session_id="test")
    assert "test" in retriever.preload_cache
    assert len(retriever.preload_cache["test"]) > 0
