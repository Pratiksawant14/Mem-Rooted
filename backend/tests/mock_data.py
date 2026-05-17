import uuid
from datetime import datetime, timezone

# ════════════════════════════════════════════════════════════════════════════
# Conversation Sets
# ════════════════════════════════════════════════════════════════════════════

CONVERSATIONS = {
    "Arjun": [
        # Session 1
        {"session_id": "arjun_s1", "message_text": "Hi, I'm Arjun. I live in Pune.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Identity/Location"},
        {"session_id": "arjun_s1", "message_text": "I am an engineering student studying computer science.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Domain/Education"},
        {"session_id": "arjun_s1", "message_text": "I really want to become a software architect one day.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Domain/Career Goal"},
        {"session_id": "arjun_s1", "message_text": "Right now, I'm building a backend API for a college project.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Cluster/Project"},
        {"session_id": "arjun_s1", "message_text": "It's taking up a lot of my time lately.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Time"},
        # Session 2
        {"session_id": "arjun_s2", "message_text": "I went cycling today morning.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Cluster/Hobby"},
        {"session_id": "arjun_s2", "message_text": "I always try to cycle on weekends.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Cluster/Hobby"},
        {"session_id": "arjun_s2", "message_text": "Cycling helps me clear my head when I'm stressed.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Stress"},
        {"session_id": "arjun_s2", "message_text": "Lately I've been stressed about exams.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Stress"},
        {"session_id": "arjun_s2", "message_text": "I need to pass my distributed systems exam to be a software architect.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Goal Link"},
        # Session 3
        {"session_id": "arjun_s3", "message_text": "I'm trying to improve my diet right now.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Diet"},
        {"session_id": "arjun_s3", "message_text": "Eating too much junk food lately while coding.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Diet"},
        {"session_id": "arjun_s3", "message_text": "I need to eat more protein.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Diet"},
        {"session_id": "arjun_s3", "message_text": "My backend API project is finally working!", "expected_candidates": 1, "expected_operations": ["NOOP", "UPDATE"], "notes": "Cluster/Project update"},
        {"session_id": "arjun_s3", "message_text": "I used FastAPI for the backend.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Project Detail"},
        # Session 4
        {"session_id": "arjun_s4", "message_text": "I'm looking for internships in Pune.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Domain/Career"},
        {"session_id": "arjun_s4", "message_text": "I want to work on large-scale systems.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Domain/Career"},
        {"session_id": "arjun_s4", "message_text": "I went cycling again this weekend.", "expected_candidates": 1, "expected_operations": ["NOOP"], "notes": "Cluster/Hobby repeated"},
        {"session_id": "arjun_s4", "message_text": "The distributed systems exam went well.", "expected_candidates": 1, "expected_operations": ["ADD", "UPDATE"], "notes": "Instance/Exam"},
        {"session_id": "arjun_s4", "message_text": "I'm one step closer to being a software architect.", "expected_candidates": 1, "expected_operations": ["NOOP"], "notes": "Domain/Goal repeated"},
    ],
    "Priya": [
        # Session 1
        {"session_id": "priya_s1", "message_text": "Hey, I'm Priya.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Identity"},
        {"session_id": "priya_s1", "message_text": "I'm based in Mumbai.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Location"},
        {"session_id": "priya_s1", "message_text": "I work as a UI/UX designer.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Domain/Career"},
        {"session_id": "priya_s1", "message_text": "My ultimate goal is to start my own design studio.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Domain/Goal"},
        {"session_id": "priya_s1", "message_text": "I always prefer minimalist aesthetics in my work.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Cluster/Preference"},
        # Session 2
        {"session_id": "priya_s2", "message_text": "Right now, I'm working on a freelance project for a fintech startup.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Cluster/Project"},
        {"session_id": "priya_s2", "message_text": "The client is very demanding.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Client"},
        {"session_id": "priya_s2", "message_text": "They want everything to be bright and colorful, which goes against my minimalist style.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Conflict"},
        {"session_id": "priya_s2", "message_text": "It's quite frustrating lately.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Emotion"},
        {"session_id": "priya_s2", "message_text": "I'm learning some advanced Figma features to speed up my workflow.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Learning"},
        # Session 3
        {"session_id": "priya_s3", "message_text": "Figma's new variables feature is amazing.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Tool"},
        {"session_id": "priya_s3", "message_text": "I managed to convince the fintech client to use a cleaner, minimalist design.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Resolution"},
        {"session_id": "priya_s3", "message_text": "I feel much better about the project now.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Emotion"},
        {"session_id": "priya_s3", "message_text": "I need to start building my portfolio for my future studio.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Domain/Goal Action"},
        {"session_id": "priya_s3", "message_text": "I love creating dark mode interfaces.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Cluster/Preference"},
        # Session 4
        {"session_id": "priya_s4", "message_text": "I finished the fintech freelance project.", "expected_candidates": 1, "expected_operations": ["ADD", "UPDATE"], "notes": "Cluster/Project Update"},
        {"session_id": "priya_s4", "message_text": "The client loved it.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Client Feedback"},
        {"session_id": "priya_s4", "message_text": "I'm taking a break from freelance for a week.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Break"},
        {"session_id": "priya_s4", "message_text": "I want to focus on my minimalist portfolio.", "expected_candidates": 1, "expected_operations": ["NOOP"], "notes": "Cluster/Preference repeated"},
        {"session_id": "priya_s4", "message_text": "Mumbai traffic is terrible today.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Instance/Observation"},
    ],
    "Rohan": [
        # Edge cases and stress tests
        {"session_id": "rohan_s1", "message_text": "I love drinking coffee every morning.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Fact 1"},
        {"session_id": "rohan_s1", "message_text": "I drink coffee.", "expected_candidates": 1, "expected_operations": ["NOOP"], "notes": "Fact 1 repeated"},
        {"session_id": "rohan_s1", "message_text": "Coffee is my favorite.", "expected_candidates": 1, "expected_operations": ["NOOP"], "notes": "Fact 1 repeated"},
        {"session_id": "rohan_s1", "message_text": "I need my morning coffee.", "expected_candidates": 1, "expected_operations": ["NOOP"], "notes": "Fact 1 repeated"},
        {"session_id": "rohan_s1", "message_text": "Can't start the day without coffee.", "expected_candidates": 1, "expected_operations": ["NOOP"], "notes": "Fact 1 repeated"},
        {"session_id": "rohan_s2", "message_text": "I stopped drinking coffee entirely.", "expected_candidates": 1, "expected_operations": ["UPDATE"], "notes": "Contradiction to Fact 1"},
        {"session_id": "rohan_s2", "message_text": "ok", "expected_candidates": 0, "expected_operations": [], "notes": "Noise"},
        {"session_id": "rohan_s2", "message_text": "lol", "expected_candidates": 0, "expected_operations": [], "notes": "Noise"},
        {"session_id": "rohan_s2", "message_text": "thanks", "expected_candidates": 0, "expected_operations": [], "notes": "Noise"},
        {"session_id": "rohan_s3", "message_text": "I go to the gym.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Branch A"},
        {"session_id": "rohan_s3", "message_text": "I am on a keto diet.", "expected_candidates": 1, "expected_operations": ["ADD"], "notes": "Branch B"},
        {"session_id": "rohan_s3", "message_text": "My keto diet is giving me great energy for the gym.", "expected_candidates": 2, "expected_operations": ["ADD", "LATERAL"], "notes": "Lateral Link A <-> B"},
        {"session_id": "rohan_s4", "message_text": "I'm Rohan, a doctor from Delhi, and lately I've been stressed about my keto diet.", "expected_candidates": 3, "expected_operations": ["ADD", "ADD", "ADD"], "notes": "Multi-fact, multi-tier"},
        {"session_id": "rohan_s4", "message_text": "sure", "expected_candidates": 0, "expected_operations": [], "notes": "Noise"},
        {"session_id": "rohan_s4", "message_text": "How do I plan my day?", "expected_candidates": 0, "expected_operations": [], "notes": "Question only"},
    ]
}


# ════════════════════════════════════════════════════════════════════════════
# Mock Database Nodes
# ════════════════════════════════════════════════════════════════════════════

MOCK_ANCHOR_NODES = [
    {
        "id": "node_anchor_1",
        "name": "User Identity",
        "content": "User is named Arjun, living in Pune.",
        "node_type": "ANCHOR",
        "tier_level": 1,
        "is_archived": False,
        "embedding": [0.1] * 384,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "parent_id": None,
        "semantic_weight": 1.0,
        "recall_weight": 5.0,
        "physical_weight": 2.0,
        "composite_weight": 8.0,
        "decay_score": 1.0,
        "lateral_links": []
    }
]

MOCK_DOMAIN_NODES = [
    {
        "id": "node_domain_1",
        "name": "Career Goal",
        "content": "Wants to become a software architect.",
        "node_type": "DOMAIN",
        "tier_level": 2,
        "is_archived": False,
        "embedding": [0.2] * 384,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "parent_id": "node_anchor_1",
        "semantic_weight": 0.8,
        "recall_weight": 2.0,
        "physical_weight": 1.0,
        "composite_weight": 3.5,
        "decay_score": 0.95,
        "lateral_links": []
    }
]

MOCK_CLUSTER_NODES = [
    {
        "id": "node_cluster_1",
        "name": "Cycling Hobby",
        "content": "Enjoys cycling on weekends.",
        "node_type": "CLUSTER",
        "tier_level": 3,
        "is_archived": False,
        "embedding": [0.3] * 384,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "parent_id": "node_domain_1", # Technically hobbies might link elsewhere, but for testing tree structure
        "semantic_weight": 0.7,
        "recall_weight": 1.5,
        "physical_weight": 0.0,
        "composite_weight": 2.2,
        "decay_score": 0.8,
        "lateral_links": [{"target_id": "node_instance_1", "similarity": 0.85, "created_at": datetime.now(timezone.utc).isoformat()}]
    },
    {
        "id": "node_cluster_2",
        "name": "Backend Project",
        "content": "Building a backend API for a college project.",
        "node_type": "CLUSTER",
        "tier_level": 3,
        "is_archived": False,
        "embedding": [0.4] * 384,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "parent_id": "node_domain_1",
        "semantic_weight": 0.9,
        "recall_weight": 3.0,
        "physical_weight": 1.0,
        "composite_weight": 4.5,
        "decay_score": 0.9,
        "lateral_links": []
    }
]

MOCK_INSTANCE_NODES = [
    {
        "id": "node_instance_1",
        "name": "Exam Stress",
        "content": "Lately stressed about distributed systems exam.",
        "node_type": "INSTANCE",
        "tier_level": 4,
        "is_archived": False,
        "embedding": [0.5] * 384,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "parent_id": "node_cluster_2",
        "semantic_weight": 0.6,
        "recall_weight": 0.5,
        "physical_weight": 0.0,
        "composite_weight": 1.1,
        "decay_score": 0.6,
        "lateral_links": [{"target_id": "node_cluster_1", "similarity": 0.85, "created_at": datetime.now(timezone.utc).isoformat()}]
    },
    {
        "id": "node_instance_2",
        "name": "FastAPI usage",
        "content": "Using FastAPI for the backend project.",
        "node_type": "INSTANCE",
        "tier_level": 4,
        "is_archived": False,
        "embedding": [0.6] * 384,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "parent_id": "node_cluster_2",
        "semantic_weight": 0.7,
        "recall_weight": 1.0,
        "physical_weight": 0.0,
        "composite_weight": 1.5,
        "decay_score": 0.7,
        "lateral_links": []
    }
]
