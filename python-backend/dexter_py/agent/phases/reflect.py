import json
from typing import Any, Dict, List, Optional, AsyncGenerator
from ...model.llm import call_llm_stream
from ..schemas import Plan, PlanTask
import re


class ReflectPhase:
    """
    ReflectPhase (streaming): Uses the LLM to analyze completed plans and task results
    and generate guidance for subsequent planning iterations.
    """

    def __init__(self, model: str, max_iterations: int = 5) -> None:
        self.model = model
        self.max_iterations = max_iterations

    async def run(
        self,
        *,
        query: str,
        understanding: Any,
        completed_plans: List[Plan],
        task_results: Dict[str, Any],
        iteration: int,
    ) -> Dict[str, Any]:
        """
        Produce a reflection using streamed LLM reasoning.
        Returns:
            Dict with keys: is_complete, reasoning, missing_info, suggested_next_steps
        """
        collected_output = ""
        async for token in self.stream(
            query=query,
            understanding=understanding,
            completed_plans=completed_plans,
            task_results=task_results,
            iteration=iteration
        ):
            collected_output += token

        # Attempt to parse JSON from streamed output
        try:
            json_text = self._extract_json(collected_output)
            reflection_dict = json.loads(json_text)
        except Exception:
            # Fallback heuristic reflection
            missing_tasks = self._identify_missing_tasks(completed_plans, task_results)
            reflection_dict = {
                "is_complete": not bool(missing_tasks),
                "reasoning": "Fallback reflection due to LLM or parsing failure.",
                "missing_info": missing_tasks,
                "suggested_next_steps": "Focus on incomplete tasks: " + ", ".join(missing_tasks)
            }

        return {
            "is_complete": reflection_dict.get("isComplete", False),
            "reasoning": reflection_dict.get("reasoning", ""),
            "missing_info": reflection_dict.get("missingInfo", []),
            "suggested_next_steps": reflection_dict.get("suggestedNextSteps")
        }

    async def stream(
        self,
        *,
        query: str,
        understanding: Any,
        completed_plans: List[Plan],
        task_results: Dict[str, Any],
        iteration: int,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming generator: yields tokens from the LLM as they arrive.
        """
        # Stop if max iterations reached
        if iteration >= self.max_iterations:
            yield json.dumps({
                "isComplete": True,
                "reasoning": f"Maximum iterations {self.max_iterations} reached.",
                "missingInfo": [],
                "suggestedNextSteps": ""
            })
            return

        # Build textual summary
        completed_summary_text = self._build_completed_summary(completed_plans, task_results)

        system_prompt = (
            "You are FinancialAgentia, an expert financial research agent. "
            "Review the completed research tasks, identify any missing or incomplete work, "
            "and provide reasoning and next-step guidance."
        )

        user_prompt = (
            f"User Query: {query}\n"
            f"Understanding: {getattr(understanding, 'intent', 'Unknown intent')}\n"
            f"Completed Work:\n{completed_summary_text}\n"
            f"Iteration: {iteration}\n\n"
            "Tasks marked with ✗ are incomplete or failed. "
            "Please provide:\n"
            "1. Reasoning about completeness.\n"
            "2. List of missing information.\n"
            "3. Suggested next steps for the next planning iteration.\n"
            "Return the result as a JSON object with keys: isComplete, reasoning, missingInfo, suggestedNextSteps."
        )

        try:
            async for token in call_llm_stream(prompt=user_prompt, model=self.model, system_prompt=system_prompt):
                yield token
        except Exception:
            # Fallback minimal JSON
            missing_tasks = self._identify_missing_tasks(completed_plans, task_results)
            yield json.dumps({
                "isComplete": not bool(missing_tasks),
                "reasoning": "Fallback reflection due to LLM error.",
                "missingInfo": missing_tasks,
                "suggestedNextSteps": "Focus on incomplete tasks: " + ", ".join(missing_tasks)
            })

    # ----------------------------
    # Helpers
    # ----------------------------
    def build_planning_guidance(self, reflection: Dict[str, Any]) -> Optional[str]:
        return reflection.get("suggested_next_steps")

    def _extract_json(self, text: str) -> str:
        """
        Extract the first JSON object from streamed text.
        """
        pattern = re.compile(r"\{.*\}", re.DOTALL)
        match = pattern.search(text)
        if match:
            return match.group(0)
        # fallback minimal JSON
        return json.dumps({
            "isComplete": False,
            "reasoning": "No JSON extracted",
            "missingInfo": [],
            "suggestedNextSteps": None
        })

    def _identify_missing_tasks(self, completed_plans: List[Plan], task_results: Dict[str, Any]) -> List[str]:
        missing_tasks = []
        for plan in completed_plans:
            for task in plan.tasks:
                result = task_results.get(task.id)
                if not result or result.get("failed") or result.get("output") is None:
                    missing_tasks.append(task.description)
        return missing_tasks

    def _build_completed_summary(self, completed_plans: List[Plan], task_results: Dict[str, Any]) -> str:
        lines = []
        for plan in completed_plans:
            lines.append(f"Plan: {plan.summary}")
            for task in plan.tasks:
                result = task_results.get(task.id)
                status = "✓" if result and not result.get("failed") and result.get("output") else "✗"
                lines.append(f"{status} {task.description}")
        return "\n".join(lines) if lines else "No completed plans."
