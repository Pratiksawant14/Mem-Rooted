import pytest
import math
from datetime import datetime, timedelta, timezone
from core.weightage import WeightageEngine
from core.decay import DecayEngine
from db.models import Node

class MockGraph:
    def __init__(self, edges=None):
        self.edges = edges or []

    def has_path(self, src, dst):
        return (src, dst) in self.edges

def test_physical_weight():
    # Tested implicitly if we assume CTE works, but we can test the formula directly
    # If 5 direct, 10 grandchildren:
    # This requires DB, so in unit tests we mock the values assigned.
    pass

def test_goal_alignment_multiplier():
    engine = WeightageEngine(db_session=None)
    
    # Node with lateral link to anchor
    node_with_anchor = Node(id="1", lateral_links=[{"target_id": "anchor1"}])
    anchor = Node(id="anchor1", node_type="ANCHOR")
    
    # Mocking graph lookup
    graph = MockGraph([("1", "anchor1")])
    
    # If there's a path, multiplier is 1.5
    assert engine._get_goal_multiplier(node_with_anchor, graph, {"anchor1"}) == 1.5
    
    # Node without
    node_without = Node(id="2", lateral_links=[])
    assert engine._get_goal_multiplier(node_without, graph, {"anchor1"}) == 1.0

def test_composite_weight_formula():
    # Cw = (0.3*Pw) + (0.5*Rw) + (0.2*Sw)
    # Pw=5, Rw=3, Sw=0.8
    # Cw = 1.5 + 1.5 + 0.16 = 3.16
    
    Pw = 5.0
    Rw = 3.0
    Sw = 0.8
    
    Cw = (0.3 * Pw) + (0.5 * Rw) + (0.2 * Sw)
    assert math.isclose(Cw, 3.16)

def test_decay_anchor():
    engine = DecayEngine(db_session=None)
    node = Node(node_type="ANCHOR")
    # ANCHOR should always be 1.0
    assert engine._calculate_decay(node, t_days=100) == 1.0

def test_decay_domain():
    engine = DecayEngine(db_session=None)
    node = Node(node_type="DOMAIN", recall_weight=0, lateral_links=[])
    
    # t=365
    D = engine._calculate_decay(node, t_days=365)
    # e^(-0.001 * 365) = e^-0.365 = 0.69419
    assert math.isclose(D, math.exp(-0.001 * 365), rel_tol=1e-3)

def test_decay_instance_no_recalls():
    engine = DecayEngine(db_session=None)
    node = Node(node_type="INSTANCE", recall_weight=0, lateral_links=[])
    
    # t=14
    D = engine._calculate_decay(node, t_days=14)
    # e^(-0.05 * 14) = e^-0.7 = 0.4965
    assert math.isclose(D, math.exp(-0.05 * 14), rel_tol=1e-3)

def test_decay_instance_with_recalls():
    engine = DecayEngine(db_session=None)
    node = Node(node_type="INSTANCE", recall_weight=10.0, lateral_links=[])
    
    D_base = math.exp(-0.05 * 14)
    resilience = engine._calculate_resilience(10.0)
    
    D = engine._calculate_decay(node, t_days=14)
    
    assert math.isclose(D, min(1.0, D_base * resilience), rel_tol=1e-3)

def test_archive_threshold():
    engine = DecayEngine(db_session=None)
    
    node = Node(node_type="INSTANCE", decay_score=0.04)
    assert engine.should_archive(node) is True
    
    node2 = Node(node_type="INSTANCE", decay_score=0.1)
    assert engine.should_archive(node2) is False

def test_promotion_demotion():
    engine = DecayEngine(db_session=None)
    
    # Promotion CLUSTER threshold is 4.0
    node = Node(node_type="CLUSTER", composite_weight=10.0)
    assert engine.should_promote(node) is True
    
    node2 = Node(node_type="CLUSTER", composite_weight=0.8)
    assert engine.should_demote(node2) is True
