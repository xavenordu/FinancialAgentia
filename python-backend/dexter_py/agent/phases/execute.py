from typing import Any, Dict, List, Optional


class ExecutePhase:
    """
    ExecutePhase: Coordinates task execution for the agent.
    
    Responsibilities:
    - Delegates tasks to TaskExecutor
    - Tracks individual task results and statuses
    - Handles exceptions without breaking the agent loop
    - Reports progress via optional callbacks
    """

    def __init__(self, model: str, task_executor: Any = None) -> None:
        self.model = model
        self.task_executor = task_executor

    async def run(
        self,
        query: str,
        plan: dict,
        understanding: Any,
        task_results: Optional[Dict[str, Any]] = None,
        callbacks: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Execute all tasks in a plan using TaskExecutor.

        Args:
            query: User query string
            plan: Dict containing the plan with tasks
            understanding: Output from UnderstandPhase
            task_results: Existing task results to update
            callbacks: Optional callback object with hooks

        Returns:
            Updated task_results dict
        """
        if task_results is None:
            task_results = {}

        tasks: List[dict] = plan.get("tasks", [])
        if not isinstance(tasks, list):
            # Malformed plan
            task_results["__error__"] = {
                "error": "Plan.tasks must be a list",
                "failed": True
            }
            return task_results

        # Execute each task safely
        for t in tasks:
            task_id = t.get("id")
            description = t.get("description", "")

            if not task_id:
                # Skip tasks without IDs
                continue

            # Call pre-task callback if available
            if callbacks and hasattr(callbacks, "on_task_start"):
                try:
                    callbacks.on_task_start(task_id, t)
                except Exception:
                    pass

            # Execute task via TaskExecutor if available
            try:
                if self.task_executor:
                    await self.task_executor.execute_tasks(
                        query=query,
                        plan={"tasks": [t]},
                        understanding=understanding,
                        task_results=task_results,
                        callbacks=callbacks,
                    )
                else:
                    # Fallback: minimal stub execution
                    task_results[task_id] = {"task_id": task_id, "output": description}

            except Exception as exc:
                # Catch errors and continue
                task_results[task_id] = {"task_id": task_id, "error": str(exc), "failed": True}

            # Call post-task callback if available
            if callbacks and hasattr(callbacks, "on_task_complete"):
                try:
                    callbacks.on_task_complete(task_id, task_results.get(task_id))
                except Exception:
                    pass

        return task_results
