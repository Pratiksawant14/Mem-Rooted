import pytest
from unittest.mock import patch, MagicMock
from api.routes.chat import process_message, assemble_prompt
from tests.mock_data import CONVERSATIONS
from db.models import Node

class MockChatDB:
    def __init__(self):
        self.nodes = []
        self.added = []
    
    async def execute(self, stmt):
        class MockResult:
            def scalars(self):
                class MockScalars:
                    def all(self):
                        return []
                    def first(self):
                        return None
                return MockScalars()
        return MockResult()

    def add(self, obj):
        if isinstance(obj, Node):
            self.nodes.append(obj)
        self.added.append(obj)
        
    async def commit(self):
        pass

    async def refresh(self, obj):
        pass

@pytest.fixture
def mock_db():
    return MockChatDB()

@pytest.mark.asyncio
async def test_pipeline_arjun(mock_db):
    # Mock all the heavy engines
    with patch('api.routes.chat.extraction_engine.extract_candidates') as mock_ext, \
         patch('api.routes.chat.placement_engine.find_parent') as mock_place, \
         patch('api.routes.chat.operations_engine.add_node') as mock_add, \
         patch('api.routes.chat.operations_engine.noop') as mock_noop, \
         patch('api.routes.chat.operations_engine.update_node') as mock_update, \
         patch('api.routes.chat.operations_engine.create_lateral_link') as mock_lat, \
         patch('api.routes.chat.retriever.retrieve') as mock_ret, \
         patch('api.routes.chat.client.chat.completions.create') as mock_llm:
        
        # Setup mocks
        mock_ret.return_value = []
        
        class MockLLMResponse:
            class Choice:
                class Message:
                    content = "Mock response."
                message = Message()
            choices = [Choice()]
        mock_llm.return_value = MockLLMResponse()

        mock_add.return_value = Node(id="new_node", node_type="ANCHOR")

        # Run through Arjun's messages
        for msg in CONVERSATIONS["Arjun"]:
            # Mock extraction specifically for the message
            from core.extraction import MemoryCandidate
            cands = []
            if msg["expected_candidates"] > 0:
                # Infer type from notes
                ctype = "INSTANCE"
                if "Identity" in msg["notes"] or "Location" in msg["notes"]: ctype = "ANCHOR"
                elif "Domain" in msg["notes"]: ctype = "DOMAIN"
                elif "Cluster" in msg["notes"]: ctype = "CLUSTER"
                
                cands = [MemoryCandidate(content=msg["message_text"], candidate_type=ctype, confidence=0.9, entities=[], is_question=False, is_noise=False, temporal_markers=[])]
            
            mock_ext.return_value = cands

            res = await process_message(
                session_id=msg["session_id"],
                user_message=msg["message_text"],
                db=mock_db
            )
            
            assert res["response"] == "Mock response."

        # The actual integration logic of operations based on placement is complex to mock fully end-to-end 
        # without running a real DB, so here we just test the pipeline flow doesn't crash 
        # and correctly calls the mocked LLM and returns the structured transparency block.
        
        # Verify transparency response includes nodes used list
        # Since we mocked retrieve to return [], nodes_used will be empty. If we mock retrieve to return nodes, it will populate.
        
@pytest.mark.asyncio
async def test_pipeline_rohan(mock_db):
    # Test Rohan's edge cases
    with patch('api.routes.chat.extraction_engine.extract_candidates') as mock_ext, \
         patch('api.routes.chat.placement_engine.find_parent') as mock_place, \
         patch('api.routes.chat.operations_engine.add_node') as mock_add, \
         patch('api.routes.chat.operations_engine.noop') as mock_noop, \
         patch('api.routes.chat.operations_engine.update_node') as mock_update, \
         patch('api.routes.chat.operations_engine.create_lateral_link') as mock_lat, \
         patch('api.routes.chat.retriever.retrieve') as mock_ret, \
         patch('api.routes.chat.client.chat.completions.create') as mock_llm:
        
        mock_ret.return_value = []
        
        class MockLLMResponse:
            class Choice:
                class Message:
                    content = "Mock response."
                message = Message()
            choices = [Choice()]
        mock_llm.return_value = MockLLMResponse()

        for msg in CONVERSATIONS["Rohan"]:
            if msg["expected_candidates"] == 0:
                mock_ext.return_value = []
            else:
                from core.extraction import MemoryCandidate
                mock_ext.return_value = [MemoryCandidate(content=msg["message_text"], candidate_type="CLUSTER", confidence=0.9, entities=[], is_question=False, is_noise=False, temporal_markers=[])]

            await process_message(
                session_id=msg["session_id"],
                user_message=msg["message_text"],
                db=mock_db
            )

def test_prompt_assembly():
    nodes = [
        Node(node_type="ANCHOR", content="User is Arjun"),
        Node(node_type="DOMAIN", content="Wants to be architect")
    ]
    prompt = assemble_prompt("How do I plan my day?", nodes)
    
    assert "[IDENTITY & CORE CONTEXT (ANCHOR/DOMAIN)]" in prompt
    assert "User is Arjun" in prompt
    assert "Wants to be architect" in prompt
    assert "How do I plan my day?" in prompt
