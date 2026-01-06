from typing import Optional


class MessageHistory:
    """Lightweight placeholder for message history used by the agent.

    The TS implementation provides conversation history management (model-aware).
    For now this stores a model id and a small list; it's enough for testing the
    orchestrator wiring.
    """

    def __init__(self, model: Optional[str] = None) -> None:
        self._model = model
        self._messages: list[str] = []

    def set_model(self, model: str) -> None:
        self._model = model

    def add(self, message: str) -> None:
        self._messages.append(message)

    def last(self) -> Optional[str]:
        return self._messages[-1] if self._messages else None

    def __repr__(self) -> str:
        return f"<MessageHistory model={self._model} messages={len(self._messages)}>"
