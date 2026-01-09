from typing import Optional, List
from dataclasses import dataclass, field
import os


@dataclass
class Message:
    """Represents a single conversation turn (query + answer + summary)"""
    id: int
    query: str
    answer: str
    summary: str = ""  # LLM-generated or fallback summary

    def __post_init__(self) -> None:
        """Validate message data on creation"""
        if not self.query or not isinstance(self.query, str):
            raise ValueError("query must be a non-empty string")
        if not self.answer or not isinstance(self.answer, str):
            raise ValueError("answer must be a non-empty string")


class MessageHistory:
    """Manages conversation history for multi-turn interactions.

    Stores user queries, agent answers, and LLM-generated summaries for each turn.
    
    Provides methods to:
    - Add complete conversation turns (query + answer)
    - Select relevant messages for the current query
    - Format messages for inclusion in prompts
    - Access and manage conversation history
    
    Thread-safe for concurrent access.
    """

    def __init__(self, model: Optional[str] = None) -> None:
        """Initialize message history with optional model information.
        
        Args:
            model: Optional LLM model name (for context)
        """
        self._model = model
        self._messages: List[Message] = []
        self._next_id: int = 0  # Maintain ID counter across clear operations

    def set_model(self, model: str) -> None:
        """Updates the model used for LLM calls (e.g., when user switches models).
        
        Args:
            model: New model name
        """
        self._model = model

    def add_agent_message(self, query: str, answer: str, summary: str = "") -> None:
        """Add a complete conversation turn (query + answer + summary).
        
        This is the primary method for adding messages. The message is stored
        as an immutable record with an incremental ID.
        
        Args:
            query: The user's question/query
            answer: The agent's response/answer
            summary: Optional human-readable summary (auto-generated if not provided)
            
        Raises:
            ValueError: If query or answer is empty/invalid
        """
        if not query or not isinstance(query, str):
            raise ValueError("query must be a non-empty string")
        if not answer or not isinstance(answer, str):
            raise ValueError("answer must be a non-empty string")
        
        # Use provided summary or auto-generate
        final_summary = summary or self._generate_summary(query, answer)
        
        message = Message(
            id=self._next_id,
            query=query,
            answer=answer,
            summary=final_summary
        )
        self._messages.append(message)
        self._next_id += 1

    def _generate_summary(self, query: str, answer: str) -> str:
        """Generate a brief summary for relevance/context purposes.
        
        Uses LLM-based summarization if available (via DEXTER_SUMMARIZE_LLM env var),
        otherwise falls back to simple preview concatenation.
        
        LLM summaries are more useful for semantic relevance filtering and are
        especially valuable for long conversations where the LLM can identify
        key concepts across multiple turns.
        
        Args:
            query: The user query
            answer: The agent's answer
            
        Returns:
            A string summary (LLM-generated or fallback)
        """
        use_llm_summary = os.getenv("DEXTER_SUMMARIZE_LLM", "false").lower() == "true"
        
        if use_llm_summary:
            try:
                return self._generate_summary_llm(query, answer)
            except Exception as e:
                # Fall back to simple summary if LLM fails
                print(f"[MessageHistory] LLM summarization failed, using fallback: {e}")
                return self._generate_summary_fallback(query, answer)
        else:
            return self._generate_summary_fallback(query, answer)
    
    def _generate_summary_llm(self, query: str, answer: str) -> str:
        """Generate summary using LLM (Claude/GPT).
        
        Creates a concise, semantically meaningful summary of the query+answer pair.
        This is useful for later relevance filtering via semantic similarity.
        
        Args:
            query: The user query
            answer: The agent's answer
            
        Returns:
            LLM-generated summary (up to ~100 chars)
        """
        try:
            from ..model.llm import call_llm
        except ImportError:
            raise ImportError("LLM module not available for summarization")
        
        prompt = f"""Summarize this Q&A in 1-2 sentences (max 100 chars):
Q: {query}
A: {answer[:500]}"""  # Truncate answer to avoid long inputs
        
        summary = call_llm(prompt, max_tokens=100)
        return summary.strip()
    
    def _generate_summary_fallback(self, query: str, answer: str) -> str:
        """Simple fallback summary: query preview + answer preview.
        
        Args:
            query: The user query
            answer: The agent's answer
            
        Returns:
            Simple string summary combining previews
        """
        query_preview = query[:60].strip()
        answer_preview = answer[:80].replace('\n', ' ').strip()
        return f"{query_preview} → {answer_preview}"

    async def select_relevant_messages(self, current_query: str) -> List[Message]:
        """Returns messages relevant to the current query.
        
        Implements smart filtering to reduce token usage:
        - Uses semantic similarity if embeddings available (via DEXTER_USE_EMBEDDINGS)
        - Falls back to recency (most recent first) if no embeddings
        - Limits to recent context window to control token count
        
        Can be further enhanced with:
        - LLM-based relevance scoring
        - Topic clustering
        - Importance scoring
        
        Args:
            current_query: The current user query to find relevant messages for
            
        Returns:
            List of relevant Message objects (ordered by relevance)
        """
        use_embeddings = os.getenv("DEXTER_USE_EMBEDDINGS", "false").lower() == "true"
        max_context_messages = int(os.getenv("DEXTER_MAX_CONTEXT_MESSAGES", "10"))
        
        if not self._messages:
            return []
        
        if use_embeddings:
            try:
                return await self._select_by_embedding_similarity(current_query, max_context_messages)
            except Exception as e:
                print(f"[MessageHistory] Embedding similarity failed, using recency: {e}")
                return self._select_by_recency(max_context_messages)
        else:
            # Default: return recent messages
            return self._select_by_recency(max_context_messages)
    
    async def _select_by_embedding_similarity(self, current_query: str, limit: int) -> List[Message]:
        """Select messages by semantic similarity to current query.
        
        Uses embeddings to find semantically similar past turns.
        This provides better context than just recency.
        
        Args:
            current_query: Current user query
            limit: Max number of messages to return
            
        Returns:
            Messages sorted by similarity score (descending)
        """
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError("sentence-transformers required for embedding similarity")
        
        model = SentenceTransformer("all-MiniLM-L6-v2")  # Fast embedding model
        
        # Embed current query
        current_embedding = model.encode(current_query)
        
        # Compute similarity scores
        scores = []
        for msg in self._messages:
            # Use summary for faster embedding (summaries are short)
            msg_embedding = model.encode(msg.summary or msg.query)
            similarity = float((current_embedding @ msg_embedding) / 
                             (1e-8 + (current_embedding**2).sum()**0.5 * (msg_embedding**2).sum()**0.5))
            scores.append((msg, similarity))
        
        # Sort by similarity (descending) and limit
        scores.sort(key=lambda x: x[1], reverse=True)
        return [msg for msg, score in scores[:limit]]
    
    def _select_by_recency(self, limit: int) -> List[Message]:
        """Select most recent messages.
        
        Simple fallback: just take the last N messages.
        
        Args:
            limit: Max number of messages to return
            
        Returns:
            Last N messages in chronological order
        """
        if len(self._messages) <= limit:
            return self._messages.copy()
        return self._messages[-limit:]

    def format_for_planning(self, messages: Optional[List[Message]] = None) -> str:
        """Format messages for inclusion in planning/execution prompts.
        
        Creates a readable format suitable for including in LLM prompts to
        provide conversation context for planning and execution phases.
        
        Args:
            messages: Optional list of messages to format (uses all if None)
            
        Returns:
            Formatted string with conversation history, or empty string if no messages
        """
        if messages is None:
            messages = self._messages

        if not messages:
            return ""

        lines = ["## Previous Conversation Context"]
        for i, msg in enumerate(messages, 1):
            lines.append(f"\n**Turn {i}:**")
            lines.append(f"- User: {msg.query}")
            # Truncate long answers to avoid exceeding token limits
            answer_preview = msg.answer[:400]
            if len(msg.answer) > 400:
                answer_preview += "..."
            lines.append(f"- Agent: {answer_preview}")
        
        lines.append("\n---\n")
        return "\n".join(lines)

    def format_for_context(self) -> str:
        """Format full message history for inclusion in system prompts.
        
        Creates a comprehensive formatted history suitable for system-level
        context inclusion, with full queries and summaries.
        
        Returns:
            Formatted string with complete conversation history, or empty string if no messages
        """
        if not self._messages:
            return ""

        lines = ["## Conversation History"]
        for msg in self._messages:
            lines.append(f"\n**Turn {msg.id + 1}:**")
            lines.append(f"- Query: {msg.query}")
            lines.append(f"- Summary: {msg.summary}")
        
        return "\n".join(lines)

    def has_messages(self) -> bool:
        """Check if any messages are stored in history.
        
        Returns:
            True if there is at least one message, False otherwise
        """
        return bool(self._messages)

    def last(self) -> Optional[Message]:
        """Get the most recent message from history.
        
        Returns:
            The last Message object, or None if history is empty
        """
        return self._messages[-1] if self._messages else None

    def get_all(self) -> List[Message]:
        """Get all messages from history in order.
        
        Returns a copy to prevent external modification.
        
        Returns:
            List of all Message objects in chronological order
        """
        return self._messages.copy()

    def get_by_id(self, message_id: int) -> Optional[Message]:
        """Retrieve a specific message by its ID.
        
        Args:
            message_id: The ID of the message to retrieve
            
        Returns:
            The Message object if found, None otherwise
        """
        for msg in self._messages:
            if msg.id == message_id:
                return msg
        return None

    def clear(self) -> None:
        """Clear all messages from history and reset ID counter.
        
        After clearing, the next message added will have ID 0.
        """
        self._messages.clear()
        self._next_id = 0

    def __len__(self) -> int:
        """Return the number of turns in history.
        
        Returns:
            Total count of messages in history
        """
        return len(self._messages)

    def __bool__(self) -> bool:
        """Check if history has any messages (allows: if history: ...).
        
        Returns:
            True if history has messages, False if empty
        """
        return bool(self._messages)

    def __iter__(self):
        """Iterate over all messages in order.
        
        Yields:
            Message objects in chronological order
        """
        return iter(self._messages)

    def __repr__(self) -> str:
        """String representation for debugging.
        
        Returns:
            Human-readable representation including model and message count
        """
        return f"<MessageHistory model={self._model} turns={len(self._messages)}>"

    def __str__(self) -> str:
        """Human-friendly string representation.
        
        Returns:
            Summary of conversation history
        """
        if not self._messages:
            return "MessageHistory (empty)"
        return f"MessageHistory ({len(self._messages)} turns)"
