"""
Production-ready message history system with:
- Separation of concerns (storage, summarization, embedding, formatting)
- Proper async/await throughout
- Thread-safe operations with locks
- Embedding caching and vectorization
- Bounded memory with pruning
- Pluggable backends
- Comprehensive error handling
"""

from typing import Optional, List, Protocol, Dict, Tuple
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
import asyncio
from asyncio import Lock
import numpy as np
from datetime import datetime
import structlog
from functools import lru_cache
import hashlib


# ============================================================================
# Core Data Models
# ============================================================================

@dataclass(frozen=True)
class Message:
    """Immutable message record representing a single conversation turn."""
    id: int
    query: str
    answer: str
    summary: str
    timestamp: datetime
    embedding_hash: Optional[str] = None  # Cache key for embeddings
    
    def __post_init__(self):
        """Validate on creation"""
        if not self.query or not isinstance(self.query, str):
            raise ValueError("query must be a non-empty string")
        if not self.answer or not isinstance(self.answer, str):
            raise ValueError("answer must be a non-empty string")
        if not isinstance(self.timestamp, datetime):
            raise ValueError("timestamp must be a datetime object")


@dataclass
class MessageWithEmbedding:
    """Message paired with its computed embedding vector."""
    message: Message
    embedding: np.ndarray
    
    @property
    def id(self) -> int:
        return self.message.id


@dataclass
class RelevanceConfig:
    """Configuration for message relevance selection."""
    max_messages: int = 10
    similarity_threshold: float = 0.3
    recency_weight: float = 0.3  # 0.0 = pure similarity, 1.0 = pure recency
    use_embeddings: bool = True


@dataclass
class HistoryConfig:
    """Configuration for message history management."""
    max_messages: int = 100  # Hard limit on stored messages
    prune_threshold: int = 120  # Trigger pruning when this is exceeded
    prune_to: int = 80  # Prune down to this many messages
    token_limit_per_message: int = 400  # Max tokens per message in formatting


# ============================================================================
# Abstract Interfaces (Protocols)
# ============================================================================

class Summarizer(Protocol):
    """Protocol for message summarization."""
    
    async def summarize(self, query: str, answer: str) -> str:
        """Generate a summary of a query-answer pair."""
        ...


class EmbeddingProvider(Protocol):
    """Protocol for embedding generation."""
    
    async def embed(self, text: str) -> np.ndarray:
        """Generate embedding vector for text."""
        ...
    
    async def embed_batch(self, texts: List[str]) -> List[np.ndarray]:
        """Generate embeddings for multiple texts (batched)."""
        ...


class MessageStore(Protocol):
    """Protocol for message persistence."""
    
    async def save(self, messages: List[Message]) -> None:
        """Persist messages to storage."""
        ...
    
    async def load(self) -> List[Message]:
        """Load messages from storage."""
        ...
    
    async def clear(self) -> None:
        """Clear all stored messages."""
        ...


# ============================================================================
# Concrete Implementations - Summarization
# ============================================================================

class SimpleSummarizer:
    """Fast fallback summarizer using text truncation."""
    
    def __init__(self, query_len: int = 60, answer_len: int = 80):
        self.query_len = query_len
        self.answer_len = answer_len
    
    async def summarize(self, query: str, answer: str) -> str:
        """Create simple truncated summary."""
        query_preview = query[:self.query_len].strip()
        answer_preview = answer[:self.answer_len].replace('\n', ' ').strip()
        
        if len(query) > self.query_len:
            query_preview += "..."
        if len(answer) > self.answer_len:
            answer_preview += "..."
        
        return f"{query_preview} → {answer_preview}"


class LLMSummarizer:
    """LLM-based summarization with fallback."""
    
    def __init__(self, llm_callable, fallback: Optional[Summarizer] = None):
        """
        Args:
            llm_callable: Async function that takes (prompt, max_tokens) and returns string
            fallback: Fallback summarizer if LLM fails
        """
        self.llm_callable = llm_callable
        self.fallback = fallback or SimpleSummarizer()
        self.logger = structlog.get_logger(__name__)
    
    async def summarize(self, query: str, answer: str) -> str:
        """Generate LLM-based summary with fallback."""
        try:
            # Truncate inputs to avoid excessive tokens
            answer_truncated = answer[:500]
            
            prompt = f"""Summarize this Q&A in 1-2 sentences (max 100 chars):
Q: {query}
A: {answer_truncated}"""
            
            summary = await self.llm_callable(prompt, max_tokens=100)
            return summary.strip()
            
        except Exception as e:
            self.logger.warning("llm_summarization_failed", error=str(e))
            return await self.fallback.summarize(query, answer)


# ============================================================================
# Concrete Implementations - Embeddings
# ============================================================================

class CachedEmbeddingProvider:
    """
    Embedding provider with caching and batching.
    Loads model once and reuses it.
    Caches embeddings by content hash.
    """
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self._cache: Dict[str, np.ndarray] = {}
        self._lock = Lock()
        self.logger = structlog.get_logger(__name__)
    
    def _get_cache_key(self, text: str) -> str:
        """Generate cache key from text content."""
        return hashlib.md5(text.encode('utf-8')).hexdigest()
    
    async def _load_model(self):
        """Load embedding model once (lazy loading)."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                # Load in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                self._model = await loop.run_in_executor(
                    None,
                    SentenceTransformer,
                    self.model_name
                )
                self.logger.info("embedding_model_loaded", model=self.model_name)
            except ImportError:
                raise ImportError(
                    "sentence-transformers required for embeddings. "
                    "Install: pip install sentence-transformers"
                )
    
    async def embed(self, text: str) -> np.ndarray:
        """Generate embedding with caching."""
        cache_key = self._get_cache_key(text)
        
        # Check cache first (no lock needed for read)
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Not in cache - compute with lock
        async with self._lock:
            # Double-check after acquiring lock
            if cache_key in self._cache:
                return self._cache[cache_key]
            
            await self._load_model()
            
            # Compute in thread pool
            loop = asyncio.get_event_loop()
            embedding = await loop.run_in_executor(
                None,
                self._model.encode,
                text
            )
            
            # Convert to numpy and cache
            embedding_array = np.array(embedding)
            self._cache[cache_key] = embedding_array
            
            return embedding_array
    
    async def embed_batch(self, texts: List[str]) -> List[np.ndarray]:
        """
        Batch embed multiple texts efficiently.
        Uses cache for known texts, computes only new ones.
        """
        if not texts:
            return []
        
        # Check which are already cached
        cache_keys = [self._get_cache_key(t) for t in texts]
        cached_indices = [i for i, k in enumerate(cache_keys) if k in self._cache]
        uncached_indices = [i for i, k in enumerate(cache_keys) if k not in self._cache]
        
        # Start with cached results
        results = [None] * len(texts)
        for i in cached_indices:
            results[i] = self._cache[cache_keys[i]]
        
        # Compute uncached in batch
        if uncached_indices:
            async with self._lock:
                await self._load_model()
                
                uncached_texts = [texts[i] for i in uncached_indices]
                
                # Batch encode in thread pool
                loop = asyncio.get_event_loop()
                embeddings = await loop.run_in_executor(
                    None,
                    self._model.encode,
                    uncached_texts
                )
                
                # Store results and update cache
                for idx, i in enumerate(uncached_indices):
                    embedding_array = np.array(embeddings[idx])
                    results[i] = embedding_array
                    self._cache[cache_keys[i]] = embedding_array
        
        return results
    
    def clear_cache(self):
        """Clear embedding cache (useful for memory management)."""
        self._cache.clear()
        self.logger.info("embedding_cache_cleared")


# ============================================================================
# Concrete Implementations - Storage
# ============================================================================

class InMemoryMessageStore:
    """Simple in-memory storage (no persistence)."""
    
    def __init__(self):
        self._messages: List[Message] = []
        self._lock = Lock()
    
    async def save(self, messages: List[Message]) -> None:
        """Store messages in memory."""
        async with self._lock:
            self._messages = messages.copy()
    
    async def load(self) -> List[Message]:
        """Load messages from memory."""
        async with self._lock:
            return self._messages.copy()
    
    async def clear(self) -> None:
        """Clear stored messages."""
        async with self._lock:
            self._messages.clear()


class FileMessageStore:
    """JSON file-based message storage."""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self._lock = Lock()
        self.logger = structlog.get_logger(__name__)
    
    async def save(self, messages: List[Message]) -> None:
        """Persist messages to JSON file."""
        import json
        import aiofiles
        
        async with self._lock:
            data = [
                {
                    'id': m.id,
                    'query': m.query,
                    'answer': m.answer,
                    'summary': m.summary,
                    'timestamp': m.timestamp.isoformat(),
                    'embedding_hash': m.embedding_hash,
                }
                for m in messages
            ]
            
            try:
                async with aiofiles.open(self.filepath, 'w') as f:
                    await f.write(json.dumps(data, indent=2))
                self.logger.info("messages_saved", filepath=self.filepath, count=len(messages))
            except Exception as e:
                self.logger.error("save_failed", error=str(e))
                raise
    
    async def load(self) -> List[Message]:
        """Load messages from JSON file."""
        import json
        import aiofiles
        from datetime import datetime
        
        async with self._lock:
            try:
                async with aiofiles.open(self.filepath, 'r') as f:
                    content = await f.read()
                    data = json.loads(content)
                
                messages = [
                    Message(
                        id=item['id'],
                        query=item['query'],
                        answer=item['answer'],
                        summary=item['summary'],
                        timestamp=datetime.fromisoformat(item['timestamp']),
                        embedding_hash=item.get('embedding_hash'),
                    )
                    for item in data
                ]
                
                self.logger.info("messages_loaded", filepath=self.filepath, count=len(messages))
                return messages
                
            except FileNotFoundError:
                self.logger.info("no_saved_messages", filepath=self.filepath)
                return []
            except Exception as e:
                self.logger.error("load_failed", error=str(e))
                return []
    
    async def clear(self) -> None:
        """Delete message file."""
        import os
        async with self._lock:
            try:
                if os.path.exists(self.filepath):
                    os.remove(self.filepath)
                self.logger.info("messages_cleared", filepath=self.filepath)
            except Exception as e:
                self.logger.error("clear_failed", error=str(e))


# ============================================================================
# Relevance Selection Engine
# ============================================================================

class RelevanceSelector:
    """
    Selects relevant messages using hybrid similarity + recency scoring.
    Fully vectorized for performance.
    """
    
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        config: RelevanceConfig
    ):
        self.embedding_provider = embedding_provider
        self.config = config
        self.logger = structlog.get_logger(__name__)
    
    async def select(
        self,
        current_query: str,
        messages: List[Message],
    ) -> List[Message]:
        """
        Select most relevant messages for current query.
        
        Uses hybrid scoring:
        - Semantic similarity (via embeddings)
        - Recency bias
        - Configurable threshold
        """
        if not messages:
            return []
        
        if len(messages) <= self.config.max_messages:
            return messages  # Return all if under limit
        
        if not self.config.use_embeddings:
            # Fallback: just return recent messages
            return messages[-self.config.max_messages:]
        
        try:
            return await self._select_by_hybrid_score(current_query, messages)
        except Exception as e:
            self.logger.warning("relevance_selection_failed", error=str(e))
            # Fallback to recency
            return messages[-self.config.max_messages:]
    
    async def _select_by_hybrid_score(
        self,
        current_query: str,
        messages: List[Message]
    ) -> List[Message]:
        """Select by hybrid similarity + recency score (vectorized)."""
        
        # Get embeddings (batch for efficiency)
        query_embedding = await self.embedding_provider.embed(current_query)
        
        # Use summaries for message embeddings (shorter, semantically rich)
        message_texts = [m.summary for m in messages]
        message_embeddings = await self.embedding_provider.embed_batch(message_texts)
        
        # Vectorized cosine similarity computation
        message_matrix = np.vstack(message_embeddings)  # Shape: (N, D)
        query_norm = np.linalg.norm(query_embedding)
        message_norms = np.linalg.norm(message_matrix, axis=1)  # Shape: (N,)
        
        # Cosine similarity: (query · messages) / (||query|| * ||messages||)
        similarities = (message_matrix @ query_embedding) / (query_norm * message_norms + 1e-8)
        
        # Recency scores (linear decay, normalized to [0, 1])
        positions = np.arange(len(messages))
        recency_scores = positions / (len(messages) - 1) if len(messages) > 1 else np.ones(1)
        
        # Hybrid score
        w = self.config.recency_weight
        hybrid_scores = (1 - w) * similarities + w * recency_scores
        
        # Filter by threshold
        valid_indices = np.where(similarities >= self.config.similarity_threshold)[0]
        
        if len(valid_indices) == 0:
            # No messages meet threshold - return most recent
            return messages[-self.config.max_messages:]
        
        # Sort valid messages by hybrid score (descending)
        valid_scores = hybrid_scores[valid_indices]
        sorted_indices = valid_indices[np.argsort(-valid_scores)]
        
        # Take top K
        top_indices = sorted_indices[:self.config.max_messages]
        
        # Return in chronological order
        top_indices_sorted = np.sort(top_indices)
        return [messages[i] for i in top_indices_sorted]


# ============================================================================
# Message Formatter
# ============================================================================

class MessageFormatter:
    """Formats messages for inclusion in prompts."""
    
    def __init__(self, config: HistoryConfig):
        self.config = config
    
    def format_for_planning(self, messages: List[Message]) -> str:
        """Format messages for planning/execution prompts."""
        if not messages:
            return ""
        
        lines = ["## Previous Conversation Context"]
        for i, msg in enumerate(messages, 1):
            lines.append(f"\n**Turn {i}:**")
            lines.append(f"- User: {msg.query}")
            
            # Truncate long answers
            answer_preview = msg.answer[:self.config.token_limit_per_message]
            if len(msg.answer) > self.config.token_limit_per_message:
                answer_preview += "..."
            lines.append(f"- Agent: {answer_preview}")
        
        lines.append("\n---\n")
        return "\n".join(lines)
    
    def format_for_context(self, messages: List[Message]) -> str:
        """Format messages for system-level context."""
        if not messages:
            return ""
        
        lines = ["## Conversation History"]
        for msg in messages:
            lines.append(f"\n**Turn {msg.id + 1}:**")
            lines.append(f"- Query: {msg.query}")
            lines.append(f"- Summary: {msg.summary}")
        
        return "\n".join(lines)


# ============================================================================
# Main MessageHistory Class
# ============================================================================

class MessageHistory:
    """
    Production-ready message history manager.
    
    Features:
    - Thread-safe operations with async locks
    - Pluggable backends (storage, summarization, embeddings)
    - Automatic pruning to prevent unbounded growth
    - Embedding caching for performance
    - Vectorized similarity computation
    - Hybrid relevance selection (similarity + recency)
    - Comprehensive error handling and logging
    """
    
    def __init__(
        self,
        model: Optional[str] = None,
        summarizer: Optional[Summarizer] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        message_store: Optional[MessageStore] = None,
        history_config: Optional[HistoryConfig] = None,
        relevance_config: Optional[RelevanceConfig] = None,
    ):
        """
        Initialize message history with pluggable components.
        
        Args:
            model: Model name for context
            summarizer: Message summarizer (defaults to SimpleSummarizer)
            embedding_provider: Embedding generator (defaults to CachedEmbeddingProvider)
            message_store: Persistence layer (defaults to InMemoryMessageStore)
            history_config: History management config
            relevance_config: Relevance selection config
        """
        self._model = model
        self._messages: List[Message] = []
        self._next_id = 0
        self._lock = Lock()
        
        # Pluggable components
        self.summarizer = summarizer or SimpleSummarizer()
        self.embedding_provider = embedding_provider or CachedEmbeddingProvider()
        self.message_store = message_store or InMemoryMessageStore()
        
        # Configuration
        self.history_config = history_config or HistoryConfig()
        self.relevance_config = relevance_config or RelevanceConfig()
        
        # Sub-components
        self.relevance_selector = RelevanceSelector(
            self.embedding_provider,
            self.relevance_config
        )
        self.formatter = MessageFormatter(self.history_config)
        
        # Logging
        self.logger = structlog.get_logger(__name__)
    
    async def initialize(self):
        """Load persisted messages on startup."""
        messages = await self.message_store.load()
        async with self._lock:
            self._messages = messages
            if messages:
                self._next_id = max(m.id for m in messages) + 1
        self.logger.info("history_initialized", message_count=len(messages))
    
    def set_model(self, model: str) -> None:
        """Update the model name."""
        self._model = model
    
    async def add_message(
        self,
        query: str,
        answer: str,
        custom_summary: Optional[str] = None
    ) -> Message:
        """
        Add a conversation turn to history.
        
        Thread-safe with automatic pruning and persistence.
        
        Args:
            query: User query
            answer: Agent answer
            custom_summary: Optional custom summary (auto-generated if not provided)
            
        Returns:
            The created Message object
        """
        if not query or not isinstance(query, str):
            raise ValueError("query must be a non-empty string")
        if not answer or not isinstance(answer, str):
            raise ValueError("answer must be a non-empty string")
        
        # Generate summary (outside lock for async LLM calls)
        if custom_summary:
            summary = custom_summary
        else:
            summary = await self.summarizer.summarize(query, answer)
        
        # Create message
        async with self._lock:
            message = Message(
                id=self._next_id,
                query=query,
                answer=answer,
                summary=summary,
                timestamp=datetime.now(),
                embedding_hash=None  # Set when embedding is computed
            )
            self._messages.append(message)
            self._next_id += 1
            
            current_count = len(self._messages)
        
        # Prune if necessary (outside lock)
        if current_count >= self.history_config.prune_threshold:
            await self._prune_messages()
        
        # Persist (outside lock for async I/O)
        await self._persist()
        
        self.logger.info("message_added", message_id=message.id, total=current_count)
        return message
    
    async def _prune_messages(self):
        """
        Prune old messages to prevent unbounded growth.
        Keeps most recent messages.
        """
        async with self._lock:
            if len(self._messages) <= self.history_config.prune_to:
                return
            
            # Keep most recent N messages
            removed_count = len(self._messages) - self.history_config.prune_to
            self._messages = self._messages[-self.history_config.prune_to:]
        
        self.logger.info("messages_pruned", removed=removed_count, remaining=self.history_config.prune_to)
        
        # Persist after pruning
        await self._persist()
    
    async def _persist(self):
        """Persist current messages to storage."""
        try:
            # Get snapshot (lock briefly)
            async with self._lock:
                messages_snapshot = self._messages.copy()
            
            # I/O outside lock
            await self.message_store.save(messages_snapshot)
        except Exception as e:
            self.logger.error("persist_failed", error=str(e))
    
    async def select_relevant_messages(self, current_query: str) -> List[Message]:
        """
        Select messages relevant to current query.
        
        Uses hybrid scoring: semantic similarity + recency.
        Thread-safe with embedding caching.
        """
        async with self._lock:
            messages_snapshot = self._messages.copy()
        
        if not messages_snapshot:
            return []
        
        relevant = await self.relevance_selector.select(current_query, messages_snapshot)
        
        self.logger.info(
            "relevant_messages_selected",
            query_length=len(current_query),
            total_messages=len(messages_snapshot),
            selected=len(relevant)
        )
        
        return relevant
    
    def format_for_planning(self, messages: Optional[List[Message]] = None) -> str:
        """Format messages for planning prompts."""
        if messages is None:
            # Use current messages (thread-safe read)
            messages = self._messages.copy()
        return self.formatter.format_for_planning(messages)
    
    def format_for_context(self) -> str:
        """Format full history for context."""
        messages = self._messages.copy()
        return self.formatter.format_for_context(messages)
    
    async def clear(self) -> None:
        """Clear all messages and reset."""
        async with self._lock:
            self._messages.clear()
            self._next_id = 0
        
        await self.message_store.clear()
        self.logger.info("history_cleared")
    
    # ========================================================================
    # Convenience accessors
    # ========================================================================
    
    def has_messages(self) -> bool:
        """Check if any messages exist."""
        return bool(self._messages)
    
    def last(self) -> Optional[Message]:
        """Get most recent message."""
        return self._messages[-1] if self._messages else None
    
    def get_messages(self) -> List[Message]:
        """Get all messages (returns copy)."""
        return self._messages.copy()
    
    def get_by_id(self, message_id: int) -> Optional[Message]:
        """Get message by ID."""
        for msg in self._messages:
            if msg.id == message_id:
                return msg
        return None
    
    def __len__(self) -> int:
        return len(self._messages)
    
    def __bool__(self) -> bool:
        return bool(self._messages)
    
    def __iter__(self):
        return iter(self._messages)
    
    def __repr__(self) -> str:
        return f"<MessageHistory model={self._model} messages={len(self._messages)}>"


# ============================================================================
# Factory Functions
# ============================================================================

async def create_message_history(
    model: str,
    persistence_path: Optional[str] = None,
    use_llm_summaries: bool = False,
    llm_callable = None,
    history_config: Optional[HistoryConfig] = None,
    relevance_config: Optional[RelevanceConfig] = None,
) -> MessageHistory:
    """
    Factory function to create a configured MessageHistory instance.
    
    Args:
        model: Model name
        persistence_path: Optional file path for persistence
        use_llm_summaries: Whether to use LLM for summarization
        llm_callable: Async LLM function for summaries
        history_config: History configuration
        relevance_config: Relevance selection configuration
        
    Returns:
        Initialized MessageHistory instance
    """
    # Configure components
    if use_llm_summaries and llm_callable:
        summarizer = LLMSummarizer(llm_callable, fallback=SimpleSummarizer())
    else:
        summarizer = SimpleSummarizer()
    
    embedding_provider = CachedEmbeddingProvider()
    
    if persistence_path:
        message_store = FileMessageStore(persistence_path)
    else:
        message_store = InMemoryMessageStore()
    
    # Create instance
    history = MessageHistory(
        model=model,
        summarizer=summarizer,
        embedding_provider=embedding_provider,
        message_store=message_store,
        history_config=history_config,
        relevance_config=relevance_config,
    )
    
    # Load persisted messages
    await history.initialize()
    
    return history