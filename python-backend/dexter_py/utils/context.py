from typing import Any


class ToolContextManager:
    """Minimal stub of the ToolContextManager used by the orchestrator.

    In the TS version this manages a filesystem-backed context store. Here it's
    a lightweight in-memory placeholder; when porting the real implementation
    we can add persistence and locking.
    """

    def __init__(self, path: str, model: str) -> None:
        self.path = path
        self.model = model
        self._store: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self._store.get(key)

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value

    def __repr__(self) -> str:
        return f"<ToolContextManager path={self.path} model={self.model}>"
