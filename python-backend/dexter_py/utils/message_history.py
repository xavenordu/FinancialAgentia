from typing import Optional, List
from dataclasses import dataclass, field


@dataclass
class Message:
    """Represents a single conversation turn (query + answer + summary)"""
    id: int
    query: str
    answer: str
    summary: str = ""  # LLM-generated summary of the answer


class MessageHistory:
    """Manages conversation history for multi-turn interactions.
    
    Stores user queries, agent answers, and LLM-generated summaries for relevance matching.
    Provides methods to:
    - Add messages (query + answer pairs)
    - Select relevant messages for the current query
    - Format messages for prompt inclusion
    - Check if messages exist
    """

    def __init__(self, model: Optional[str] = None) -> None:
        self._model = model
        self._messages: List[Message] = []

    def set_model(self, model: str) -> None:
        """Updates the model used for LLM calls (e.g., when user switches models)"""
        self._model = model

    def add_user_message(self, query: str) -> None:
        """Records a user query (called before the agent responds)"""
        # This is tracked as part of add_agent_message with both query and answer
        pass

    def add_agent_message(self, query: str, answer: str, summary: str = "") -> None:
        """Adds a complete conversation turn (query + answer + optional summary)"""
        message = Message(
            id=len(self._messages),
            query=query,
            answer=answer,
            summary=summary or self._generate_summary(query, answer)
        )
        self._messages.append(message)

    def _generate_summary(self, query: str, answer: str) -> str:
        """Generate a brief summary (placeholder - can be enhanced with LLM)"""
        # Simple fallback: use query as summary
        # In production, this could call the LLM for better summaries
        return f"Query: {query[:80]}"

    async def select_relevant_messages(self, current_query: str) -> List[Message]:
        """Returns messages relevant to the current query.
        
        In a basic implementation, returns all messages. Can be enhanced with:
        - Semantic similarity matching
        - LLM-based relevance scoring
        - Recency weighting
        """
        return self._messages.copy()

    def format_for_planning(self, messages: Optional[List[Message]] = None) -> str:
        """Formats messages for inclusion in planning prompts.
        
        Returns a formatted string with conversation history that can be
        included in prompts to give the agent context.
        """
        if not messages:
            messages = self._messages

        if not messages:
            return ""

        lines = ["Previous conversation:"]
        for msg in messages:
            lines.append(f"\nUser: {msg.query}")
            lines.append(f"Agent: {msg.answer[:500]}{'...' if len(msg.answer) > 500 else ''}")

        return "\n".join(lines)

    def format_for_context(self) -> str:
        """Formats full message history for inclusion in system prompts"""
        if not self._messages:
            return ""

        lines = ["## Conversation History"]
        for msg in self._messages:
            lines.append(f"\n**Turn {msg.id + 1}:**")
            lines.append(f"- **Query:** {msg.query}")
            lines.append(f"- **Summary:** {msg.summary}")

        return "\n".join(lines)

    def has_messages(self) -> bool:
        """Returns True if there are any messages in history"""
        return len(self._messages) > 0

    def last(self) -> Optional[Message]:
        """Returns the most recent message"""
        return self._messages[-1] if self._messages else None

    def get_all(self) -> List[Message]:
        """Returns all messages in order"""
        return self._messages.copy()

    def clear(self) -> None:
        """Clears the message history"""
        self._messages.clear()

    def __len__(self) -> int:
        """Returns the number of messages"""
        return len(self._messages)

    def __repr__(self) -> str:
        return f"<MessageHistory model={self._model} turns={len(self._messages)}>"
