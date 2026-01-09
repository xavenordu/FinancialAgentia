from typing import Optional, Any, List, AsyncGenerator
from ...model.llm import call_llm_stream
from .. import schemas
from ..schemas import Plan, PlanTask
import json
import re


class PlanPhase:
    """
    Generates a structured Plan using the LLM with streaming support.

    Features:
    - Yields partial plan text as tokens
    - Returns final Plan object
    - Handles errors and fallbacks
    - Generates unique task IDs per iteration
    """

    def __init__(self, model: str) -> None:
        self.model = model

    async def run(
        self,
        *,
        query: str,
        understanding: Any,
        prior_plans: Optional[List[Plan]] = None,
        prior_results: Optional[dict] = None,
        guidance_from_reflection: Optional[str] = None,
    ) -> Plan:
        """
        Generate a final Plan object by collecting streamed LLM tokens.
        """
        # Collect tokens into buffer
        collected_output = ""
        async for token in self.stream(
            query=query,
            understanding=understanding,
            prior_plans=prior_plans,
            prior_results=prior_results,
            guidance_from_reflection=guidance_from_reflection
        ):
            collected_output += token

        # Attempt to extract JSON
        try:
            json_text = self._extract_json(collected_output)
            plan_obj = Plan.parse_raw(json_text)
        except Exception:
            # Fallback minimal plan
            plan_obj = Plan(
                summary="Fallback plan due to LLM or parsing error",
                tasks=[PlanTask(id="task-1", description=f"Answer query: {query}")]
            )

        # Generate unique task IDs
        iteration = len(prior_plans) + 1 if prior_plans else 1
        id_prefix = f"iter{iteration}_"
        tasks: List[PlanTask] = []
        for t in plan_obj.tasks:
            tasks.append(
                PlanTask(
                    id=id_prefix + t.id,
                    description=t.description,
                    status=t.status,
                    taskType=getattr(t, "taskType", None),
                    toolCalls=getattr(t, "toolCalls", []),
                    dependsOn=[id_prefix + d for d in getattr(t, "dependsOn", [])],
                )
            )

        return Plan(summary=plan_obj.summary, tasks=tasks)

    async def stream(
        self,
        *,
        query: str,
        understanding: Any,
        prior_plans: Optional[List[Plan]] = None,
        prior_results: Optional[dict] = None,
        guidance_from_reflection: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Streaming version: yields tokens from the LLM as they arrive.
        """
        # ----------------------------
        # Extract entities
        # ----------------------------
        entities = getattr(understanding, "entities", []) or []
        entities_str = ", ".join([f"{e.type}: {e.value}" for e in entities]) if entities else "None identified"

        # ----------------------------
        # Format prior work
        # ----------------------------
        prior_work_summary = None
        if prior_plans:
            prior_work_summary = self._format_prior_work(prior_plans, prior_results)

        # ----------------------------
        # Build prompts
        # ----------------------------
        try:
            from .. import prompts as _prompts
            system_prompt = _prompts.getPlanSystemPrompt()
            user_prompt = _prompts.buildPlanUserPrompt(
                query=query,
                intent=getattr(understanding, "intent", ""),
                entities=entities_str,
                prior_work_summary=prior_work_summary,
                guidance_from_reflection=guidance_from_reflection,
            )
        except Exception:
            system_prompt = "You are a financial research assistant."
            user_prompt = f"Create a plan for query: {query}"

        # ----------------------------
        # Stream LLM tokens
        # ----------------------------
        try:
            async for token in call_llm_stream(prompt=user_prompt, model=self.model, system_prompt=system_prompt):
                yield token
        except Exception:
            # Fallback: yield minimal JSON for plan
            fallback_plan = {
                "summary": "Fallback plan due to LLM error",
                "tasks": [{"id": "task-1", "description": f"Answer query: {query}"}]
            }
            yield json.dumps(fallback_plan)

    def _extract_json(self, text: str) -> str:
        """
        Extract the first JSON object from streamed LLM output.
        """
        json_pattern = re.compile(r"\{.*\}", re.DOTALL)
        match = json_pattern.search(text)
        if match:
            return match.group(0)
        # Fallback minimal JSON
        return json.dumps({"summary": "Fallback plan", "tasks": [{"id": "task-1", "description": "Answer query"}]})

    def _format_prior_work(self, plans: List[Plan], task_results: Optional[dict]) -> str:
        """
        Format summaries of prior plans and task results.
        """
        parts: List[str] = []
        for i, plan in enumerate(plans):
            parts.append(f"Pass {i+1}: {plan.summary}")
            for task in plan.tasks:
                result = task_results.get(task.id) if task_results else None
                status = "✓" if result else "✗"
                parts.append(f"  {status} {task.description}")
        return "\n".join(parts)
