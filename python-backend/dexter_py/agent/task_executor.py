from typing import Any, Dict, Optional, Callable, List


class TaskExecutor:
    def __init__(
        self,
        *,
        model: str,
        tool_executor: Any,
        execute_phase: Any,
        context_manager: Any
    ) -> None:
        self.model = model
        self.tool_executor = tool_executor
        self.execute_phase = execute_phase
        self.context_manager = context_manager

    async def execute_tasks(
        self,
        query: str,
        plan: Dict[str, Any],
        understanding: Any,
        task_results: Dict[str, Any],
        callbacks: Optional[Any] = None
    ) -> None:
        """
        Executes tasks listed in the plan sequentially.
        Each task is represented as a dict with at least an "id".
        Every task result is stored in task_results under its task_id key.

        This implementation is intentionally defensive:
        - gracefully handles missing fields
        - skips invalid tasks instead of raising exceptions
        - safeguards callback execution
        - isolates failure to each task
        """

        tasks = plan.get("tasks", [])

        # Soft validation: ensure tasks is an iterable list-like object
        if not isinstance(tasks, list):
            return

        for idx, task in enumerate(tasks):
            # Skip invalid task entries
            if not isinstance(task, dict):
                continue

            task_id = task.get("id")

            # Enforce a minimal task identifier; skip if missing
            if task_id is None:
                continue

            description = task.get("description", "")
            metadata = task.get("metadata", {})

            try:
                # Simulate doing actual work; extend this block for real execution logic
                result = {
                    "task_id": task_id,
                    "output": description,
                    "metadata": metadata,
                }

                # Store results
                task_results[task_id] = result

                # Safely call callback hooks
                if callbacks is not None and hasattr(callbacks, "on_task_complete"):
                    try:
                        callbacks.on_task_complete(task_id, result)
                    except Exception:
                        # Silent failure — callback should not break execution flow
                        pass

            except Exception as exc:
                # Capture error in results table for visibility
                task_results[task_id] = {
                    "task_id": task_id,
                    "error": str(exc),
                    "failed": True,
                }

                # Optional callback for failure (if implemented)
                if callbacks is not None and hasattr(callbacks, "on_task_error"):
                    try:
                        callbacks.on_task_error(task_id, exc)
                    except Exception:
                        pass
