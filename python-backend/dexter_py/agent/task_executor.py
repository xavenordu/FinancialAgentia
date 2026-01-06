from typing import Any, Dict, Callable, Optional


class TaskExecutor:
    def __init__(self, *, model: str, tool_executor: Any, execute_phase: Any, context_manager: Any) -> None:
        self.model = model
        self.tool_executor = tool_executor
        self.execute_phase = execute_phase
        self.context_manager = context_manager

    async def execute_tasks(self, query: str, plan: dict, understanding: Any, task_results: Dict[str, Any], callbacks: Optional[Any] = None) -> None:
        # Minimal executor: run each task in the plan sequentially and store a trivial result
        tasks = plan.get("tasks", [])
        for t in tasks:
            task_id = t.get("id")
            # Simulate calling a tool or performing work
            result = {"task_id": task_id, "output": t.get("description")}
            task_results[task_id] = result
            # If callback hook exists, call it for task completion
            if callbacks is not None and hasattr(callbacks, "on_task_complete"):
                try:
                    callbacks.on_task_complete(task_id, result)
                except Exception:
                    pass
