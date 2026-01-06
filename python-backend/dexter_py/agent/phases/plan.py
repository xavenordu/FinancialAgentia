from typing import Optional, Any
from dexter_py.model.llm import call_llm
from dexter_py.agent import schemas
from dexter_py.agent.schemas import Plan, PlanTask


class PlanPhase:
    """Ported PlanPhase: creates a structured plan using the LLM.

    This asks the model to return JSON matching the Plan schema and then
    post-processes IDs to avoid collisions with prior plans.
    """

    def __init__(self, model: str) -> None:
        self.model = model

    async def run(
        self,
        *,
        query: str,
        understanding: Any,
        prior_plans: Optional[list] = None,
        prior_results: Optional[dict] = None,
        guidance_from_reflection: Optional[str] = None,
    ) -> Plan:
        entities = understanding.entities if getattr(understanding, 'entities', None) else []
        entities_str = ', '.join([f"{e.type}: {e.value}" for e in entities]) if entities else 'None identified'

        prior_work_summary = None
        if prior_plans and len(prior_plans) > 0:
            prior_work_summary = self.format_prior_work(prior_plans, prior_results)

        # Import prompts lazily
        from dexter_py.agent import prompts as _prompts

        system_prompt = _prompts.getPlanSystemPrompt()
        user_prompt = _prompts.buildPlanUserPrompt(
            query,
            getattr(understanding, 'intent', ''),
            entities_str,
            prior_work_summary,
            guidance_from_reflection,
        )

        # Request structured Plan output via pydantic model
        result = await call_llm(user_prompt, model=self.model, system_prompt=system_prompt, output_model=schemas.Plan)

        # Ensure it's a Plan instance
        if isinstance(result, Plan):
            plan_obj: Plan = result
        else:
            plan_obj = Plan.parse_obj(result)

        # Generate unique task ids to avoid collisions with prior plans
        iteration = len(prior_plans) + 1 if prior_plans else 1
        id_prefix = f"iter{iteration}_"

        tasks = []
        for t in plan_obj.tasks:
            new_task = PlanTask(
                id=id_prefix + t.id,
                description=t.description,
                status=t.status,
                taskType=t.taskType,
                toolCalls=getattr(t, 'toolCalls', []),
                dependsOn=[id_prefix + d for d in getattr(t, 'dependsOn', [])],
            )
            tasks.append(new_task)

        return Plan(summary=plan_obj.summary, tasks=tasks)

    def format_prior_work(self, plans: list, task_results: Optional[dict]) -> str:
        parts = []
        for i, plan in enumerate(plans):
            parts.append(f"Pass {i+1}: {plan.summary}")
            for task in plan.tasks:
                result = None
                if task_results:
                    result = task_results.get(task.id)
                status = '✓' if result else '✗'
                parts.append(f"  {status} {task.description}")
        return '\n'.join(parts)
from typing import Optional, Any


class PlanPhase:
    def __init__(self, model: str) -> None:
        self.model = model

    async def run(self, *, query: str, understanding: Any, prior_plans: Optional[list] = None, prior_results: Optional[dict] = None, guidance_from_reflection: Optional[str] = None) -> dict:
        # Minimal stub: create a single no-op task plan
        return {"tasks": [{"id": "task-1", "description": f"Answer: {query}", "type": "final"}]}
