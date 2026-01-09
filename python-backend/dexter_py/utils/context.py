from typing import Any, Optional
import threading
import json
import os


class ToolContextManager:
    """Enhanced ToolContextManager for orchestrator.

    Features:
    - Thread-safe in-memory store
    - Optional JSON file persistence
    - Namespaced keys per tool or module
    - Graceful error handling
    """

    def __init__(self, path: str, model: str, persist: bool = False) -> None:
        self.path = path
        self.model = model
        self.persist = persist
        self._lock = threading.RLock()
        self._store: dict[str, Any] = {}

        if self.persist:
            os.makedirs(self.path, exist_ok=True)
            self._load_store()

    def _load_store(self) -> None:
        """Load persisted context from disk if available."""
        try:
            file_path = os.path.join(self.path, f"{self.model}_context.json")
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._store = data
        except Exception as exc:
            # Fail silently, store will start empty
            print(f"[ToolContextManager] Warning: failed to load context: {exc}")

    def _persist_store(self) -> None:
        """Persist current context to disk."""
        if not self.persist:
            return
        try:
            file_path = os.path.join(self.path, f"{self.model}_context.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self._store, f, indent=2)
        except Exception as exc:
            print(f"[ToolContextManager] Warning: failed to persist context: {exc}")

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        """Thread-safe retrieval of a value, with optional default."""
        with self._lock:
            return self._store.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Thread-safe setting of a value."""
        with self._lock:
            self._store[key] = value
            self._persist_store()

    def delete(self, key: str) -> None:
        """Remove a key from the store if it exists."""
        with self._lock:
            self._store.pop(key, None)
            self._persist_store()

    def clear(self) -> None:
        """Clear all stored context."""
        with self._lock:
            self._store.clear()
            self._persist_store()

    def keys(self) -> list[str]:
        """Return a list of all keys."""
        with self._lock:
            return list(self._store.keys())

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._store

    def __repr__(self) -> str:
        with self._lock:
            return f"<ToolContextManager path={self.path} model={self.model} keys={len(self._store)}>"
