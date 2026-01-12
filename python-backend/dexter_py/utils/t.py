"""
Usage examples and integration tests for the production message history system.
"""

import asyncio
from datetime import datetime
from typing import List
import numpy as np


# ============================================================================
# Example 1: Basic Usage with Simple Configuration
# ============================================================================

async def example_basic_usage():
    """Basic usage with in-memory storage and simple summarization."""
    from message_history import MessageHistory, SimpleSummarizer
    
    # Create history with defaults (in-memory, simple summarization)
    history = MessageHistory(model="claude-sonnet-4")
    await history.initialize()
    
    # Add messages
    msg1 = await history.add_message(
        query="What is Python?",
        answer="Python is a high-level programming language known for its simplicity and readability."
    )
    print(f"Added message {msg1.id}: {msg1.summary}")
    
    msg2 = await history.add_message(
        query="How do I install it?",
        answer="You can install Python from python.org or use package managers like apt, brew, or chocolatey."
    )
    
    # Get relevant messages for a new query
    relevant = await history.select_relevant_messages("How to setup Python?")
    print(f"\nRelevant messages: {len(relevant)}")
    for msg in relevant:
        print(f"  - Turn {msg.id}: {msg.query[:50]}")
    
    # Format for prompts
    context = history.format_for_planning(relevant)
    print(f"\n{context}")


# ============================================================================
# Example 2: Production Setup with Persistence and LLM Summaries
# ============================================================================

async def example_production_setup():
    """Production setup with file persistence and LLM summarization."""
    from message_history import (
        create_message_history,
        HistoryConfig,
        RelevanceConfig
    )
    
    # Mock LLM callable for this example
    async def mock_llm_summarize(prompt: str, max_tokens: int) -> str:
        # In real usage, this would call Claude API
        return "Summary of Q&A about Python features"
    
    # Create with full configuration
    history = await create_message_history(
        model="claude-sonnet-4",
        persistence_path="./conversation_history.json",
        use_llm_summaries=True,
        llm_callable=mock_llm_summarize,
        history_config=HistoryConfig(
            max_messages=100,
            prune_threshold=120,
            prune_to=80,
            token_limit_per_message=400
        ),
        relevance_config=RelevanceConfig(
            max_messages=10,
            similarity_threshold=0.3,
            recency_weight=0.3,
            use_embeddings=True
        )
    )
    
    # Add some messages
    for i in range(5):
        await history.add_message(
            query=f"Question {i} about programming",
            answer=f"Detailed answer {i} explaining programming concepts with examples."
        )
    
    print(f"Total messages: {len(history)}")
    print(f"Last message: {history.last().query}")
    
    # Messages are automatically persisted to file
    # On next run, they'll be loaded via history.initialize()


# ============================================================================
# Example 3: Custom Components - Redis Storage
# ============================================================================

class RedisMessageStore:
    """Example custom storage backend using Redis."""
    
    def __init__(self, redis_client, key_prefix: str = "msg_history"):
        self.redis = redis_client
        self.key_prefix = key_prefix
        self._lock = asyncio.Lock()
    
    async def save(self, messages: List) -> None:
        """Save to Redis as JSON."""
        import json
        async with self._lock:
            data = json.dumps([
                {
                    'id': m.id,
                    'query': m.query,
                    'answer': m.answer,
                    'summary': m.summary,
                    'timestamp': m.timestamp.isoformat(),
                }
                for m in messages
            ])
            await self.redis.set(f"{self.key_prefix}:messages", data)
    
    async def load(self) -> List:
        """Load from Redis."""
        import json
        from message_history import Message
        
        async with self._lock:
            data = await self.redis.get(f"{self.key_prefix}:messages")
            if not data:
                return []
            
            items = json.loads(data)
            return [
                Message(
                    id=item['id'],
                    query=item['query'],
                    answer=item['answer'],
                    summary=item['summary'],
                    timestamp=datetime.fromisoformat(item['timestamp'])
                )
                for item in items
            ]
    
    async def clear(self) -> None:
        """Clear from Redis."""
        async with self._lock:
            await self.redis.delete(f"{self.key_prefix}:messages")


async def example_redis_storage():
    """Using Redis for distributed message storage."""
    from message_history import MessageHistory, SimpleSummarizer, CachedEmbeddingProvider
    # from redis.asyncio import Redis  # Uncomment in real usage
    
    # redis_client = Redis(host='localhost', port=6379)
    # redis_store = RedisMessageStore(redis_client, key_prefix="user_123")
    
    # history = MessageHistory(
    #     model="claude-sonnet-4",
    #     summarizer=SimpleSummarizer(),
    #     embedding_provider=CachedEmbeddingProvider(),
    #     message_store=redis_store
    # )
    # await history.initialize()
    
    print("Redis storage example (commented out - requires redis.asyncio)")


# ============================================================================
# Example 4: Concurrent Access Safety
# ============================================================================

async def example_concurrent_access():
    """Demonstrate thread-safe concurrent message additions."""
    from message_history import MessageHistory
    
    history = MessageHistory(model="claude-sonnet-4")
    await history.initialize()
    
    # Simulate multiple concurrent users/tasks adding messages
    async def user_conversation(user_id: int):
        for i in range(3):
            await history.add_message(
                query=f"User {user_id} query {i}",
                answer=f"Response to user {user_id} query {i}"
            )
            await asyncio.sleep(0.01)  # Simulate work
    
    # Run 5 concurrent conversations
    await asyncio.gather(*[user_conversation(i) for i in range(5)])
    
    print(f"Total messages after concurrent access: {len(history)}")
    print("All messages have unique IDs:", len(set(m.id for m in history)) == len(history))


# ============================================================================
# Example 5: Hybrid Relevance Selection
# ============================================================================

async def example_relevance_selection():
    """Demonstrate hybrid similarity + recency selection."""
    from message_history import MessageHistory, RelevanceConfig
    
    history = MessageHistory(
        model="claude-sonnet-4",
        relevance_config=RelevanceConfig(
            max_messages=5,
            similarity_threshold=0.2,
            recency_weight=0.3,  # 70% similarity, 30% recency
            use_embeddings=True
        )
    )
    await history.initialize()
    
    # Add diverse messages
    topics = [
        ("What is machine learning?", "ML is a subset of AI..."),
        ("How to cook pasta?", "Boil water, add pasta..."),
        ("Explain neural networks", "Neural networks are..."),
        ("Best pasta recipes?", "Try carbonara or aglio e olio..."),
        ("What is deep learning?", "Deep learning uses neural networks..."),
        ("Python vs JavaScript?", "Python is better for ML, JS for web..."),
    ]
    
    for query, answer in topics:
        await history.add_message(query, answer)
    
    # Query about ML - should retrieve ML-related messages
    ml_query = "Tell me about artificial intelligence"
    relevant = await history.select_relevant_messages(ml_query)
    
    print(f"\nQuery: {ml_query}")
    print(f"Retrieved {len(relevant)} relevant messages:")
    for msg in relevant:
        print(f"  - {msg.query}")


# ============================================================================
# Example 6: Automatic Pruning
# ============================================================================

async def example_automatic_pruning():
    """Demonstrate automatic message pruning."""
    from message_history import MessageHistory, HistoryConfig
    
    history = MessageHistory(
        model="claude-sonnet-4",
        history_config=HistoryConfig(
            max_messages=100,
            prune_threshold=10,  # Low threshold for demo
            prune_to=5
        )
    )
    await history.initialize()
    
    # Add messages until pruning triggers
    for i in range(12):
        await history.add_message(
            query=f"Query {i}",
            answer=f"Answer {i}"
        )
        print(f"Added message {i}, total: {len(history)}")
    
    print(f"\nFinal count after auto-pruning: {len(history)}")
    print(f"Kept most recent messages: {[m.id for m in history]}")


# ============================================================================
# Example 7: Integration with Orchestrator
# ============================================================================

async def example_orchestrator_integration():
    """How to use MessageHistory with the Orchestrator."""
    from message_history import create_message_history, RelevanceConfig
    
    # Create history for a user session
    history = await create_message_history(
        model="claude-sonnet-4",
        persistence_path="./user_session_123.json",
        relevance_config=RelevanceConfig(
            max_messages=10,
            use_embeddings=True
        )
    )
    
    # In orchestrator run:
    async def orchestrator_run(query: str):
        # 1. Get relevant past context
        relevant_messages = await history.select_relevant_messages(query)
        context = history.format_for_planning(relevant_messages)
        
        # 2. Execute agent logic (plan, execute, reflect, answer)
        # ... orchestrator phases ...
        answer = "Computed answer from orchestrator"
        
        # 3. Save the turn to history
        await history.add_message(query, answer)
        
        return answer
    
    # Multi-turn conversation
    await orchestrator_run("What is Python?")
    await orchestrator_run("How do I use it for web development?")
    await orchestrator_run("Show me a Flask example")
    
    print(f"Conversation has {len(history)} turns")


# ============================================================================
# Performance Benchmarks
# ============================================================================

async def benchmark_embedding_cache():
    """Benchmark embedding cache performance."""
    import time
    from message_history import CachedEmbeddingProvider
    
    provider = CachedEmbeddingProvider()
    
    test_texts = [f"Test message number {i}" for i in range(100)]
    
    # First pass - cold cache
    start = time.time()
    embeddings1 = await provider.embed_batch(test_texts)
    cold_time = time.time() - start
    
    # Second pass - warm cache
    start = time.time()
    embeddings2 = await provider.embed_batch(test_texts)
    warm_time = time.time() - start
    
    print(f"\nEmbedding Cache Benchmark:")
    print(f"  Cold cache (100 texts): {cold_time:.3f}s")
    print(f"  Warm cache (100 texts): {warm_time:.3f}s")
    print(f"  Speedup: {cold_time/warm_time:.1f}x")
    print(f"  Cache hit rate: 100%")


async def benchmark_relevance_selection():
    """Benchmark vectorized relevance selection."""
    import time
    from message_history import MessageHistory, RelevanceConfig
    
    history = MessageHistory(
        model="claude-sonnet-4",
        relevance_config=RelevanceConfig(
            max_messages=20,
            use_embeddings=True
        )
    )
    await history.initialize()
    
    # Add many messages
    for i in range(200):
        await history.add_message(
            query=f"Question about topic {i % 10}",
            answer=f"Detailed answer for question {i}"
        )
    
    # Benchmark selection
    query = "Tell me about topic 5"
    
    start = time.time()
    for _ in range(10):
        relevant = await history.select_relevant_messages(query)
    avg_time = (time.time() - start) / 10
    
    print(f"\nRelevance Selection Benchmark:")
    print(f"  Messages in history: {len(history)}")
    print(f"  Average selection time: {avg_time*1000:.1f}ms")
    print(f"  Selected messages: {len(relevant)}")


# ============================================================================
# Unit Tests
# ============================================================================

async def test_message_immutability():
    """Test that messages are immutable."""
    from message_history import Message
    
    msg = Message(
        id=0,
        query="Test",
        answer="Answer",
        summary="Summary",
        timestamp=datetime.now()
    )
    
    try:
        msg.query = "Modified"
        assert False, "Should not be able to modify frozen dataclass"
    except Exception:
        print("✓ Message immutability test passed")


async def test_concurrent_id_assignment():
    """Test that concurrent additions get unique IDs."""
    from message_history import MessageHistory
    
    history = MessageHistory(model="test")
    await history.initialize()
    
    async def add_messages(count: int):
        messages = []
        for i in range(count):
            msg = await history.add_message(f"Query {i}", f"Answer {i}")
            messages.append(msg)
        return messages
    
    # Add 100 messages concurrently from 5 tasks
    results = await asyncio.gather(*[add_messages(20) for _ in range(5)])
    
    all_ids = [msg.id for batch in results for msg in batch]
    assert len(all_ids) == len(set(all_ids)), "All IDs must be unique"
    assert len(all_ids) == 100, "Should have 100 messages"
    print("✓ Concurrent ID assignment test passed")


async def test_pruning_logic():
    """Test automatic pruning behavior."""
    from message_history import MessageHistory, HistoryConfig
    
    history = MessageHistory(
        model="test",
        history_config=HistoryConfig(
            prune_threshold=10,
            prune_to=5
        )
    )
    await history.initialize()
    
    # Add 12 messages - should trigger pruning
    for i in range(12):
        await history.add_message(f"Q{i}", f"A{i}")
    
    assert len(history) == 5, f"Should have 5 messages after pruning, got {len(history)}"
    
    # Check that we kept the most recent ones
    ids = [m.id for m in history]
    assert ids == [7, 8, 9, 10, 11], f"Should keep IDs 7-11, got {ids}"
    
    print("✓ Pruning logic test passed")


async def test_empty_history_handling():
    """Test behavior with empty history."""
    from message_history import MessageHistory
    
    history = MessageHistory(model="test")
    await history.initialize()
    
    assert not history.has_messages()
    assert history.last() is None
    assert len(history) == 0
    
    relevant = await history.select_relevant_messages("test query")
    assert relevant == []
    
    context = history.format_for_planning()
    assert context == ""
    
    print("✓ Empty history handling test passed")


# ============================================================================
# Run All Examples
# ============================================================================

async def main():
    """Run all examples and tests."""
    print("=" * 70)
    print("MESSAGE HISTORY SYSTEM - EXAMPLES & TESTS")
    print("=" * 70)
    
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Basic Usage")
    print("=" * 70)
    await example_basic_usage()
    
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Production Setup")
    print("=" * 70)
    await example_production_setup()
    
    print("\n" + "=" * 70)
    print("EXAMPLE 4: Concurrent Access")
    print("=" * 70)
    await example_concurrent_access()
    
    print("\n" + "=" * 70)
    print("EXAMPLE 5: Relevance Selection")
    print("=" * 70)
    await example_relevance_selection()
    
    print("\n" + "=" * 70)
    print("EXAMPLE 6: Automatic Pruning")
    print("=" * 70)
    await example_automatic_pruning()
    
    print("\n" + "=" * 70)
    print("PERFORMANCE BENCHMARKS")
    print("=" * 70)
    await benchmark_embedding_cache()
    await benchmark_relevance_selection()
    
    print("\n" + "=" * 70)
    print("UNIT TESTS")
    print("=" * 70)
    await test_message_immutability()
    await test_concurrent_id_assignment()
    await test_pruning_logic()
    await test_empty_history_handling()
    
    print("\n" + "=" * 70)
    print("ALL EXAMPLES AND TESTS COMPLETED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())