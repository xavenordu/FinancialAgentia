from typing import Any, Dict, List, Optional, AsyncGenerator
from dataclasses import dataclass

from ..utils.context import ToolContextManager
from ..utils.message_history import MessageHistory
from ..tools import TOOLS
from .phases.understand import UnderstandPhase
from .phases.plan import PlanPhase
from .phases.execute import ExecutePhase
from .phases.reflect import ReflectPhase
from .phases.answer import AnswerPhase
from .tool_executor import ToolExecutor
from .task_executor import TaskExecutor


DEFAULT_MAX_ITERATIONS = 5


@dataclass
class AgentCallbacks:
    # Phase transitions
    on_phase_start: Optional[callable] = None
    on_phase_complete: Optional[callable] = None
    # Understanding
    on_understanding_complete: Optional[callable] = None
    # Planning
    on_plan_created: Optional[callable] = None
    # Reflection
    on_reflection_complete: Optional[callable] = None
    on_iteration_start: Optional[callable] = None
    # Answer
    on_answer_start: Optional[callable] = None
    on_answer_stream: Optional[callable] = None


@dataclass
class AgentOptions:
    model: str
    callbacks: Optional[AgentCallbacks] = None
    max_iterations: Optional[int] = None


class Agent:
    """Agent - port of the TypeScript orchestrator.

    This class wires phases, executors and context management together. The
    concrete phase implementations are placeholders; we'll incrementally port
    full behavior from the TypeScript source.
    """

    def __init__(self, options: AgentOptions) -> None:
        self.model = options.model
        self.callbacks = options.callbacks or AgentCallbacks()
        self.max_iterations = options.max_iterations or DEFAULT_MAX_ITERATIONS

        # Context manager (stub)
        self.context_manager = ToolContextManager('.dexter/context', self.model)

        # Initialize phases
        self.understand_phase = UnderstandPhase(model=self.model)
        self.plan_phase = PlanPhase(model=self.model)
        self.execute_phase = ExecutePhase(model=self.model)
        self.reflect_phase = ReflectPhase(model=self.model, max_iterations=self.max_iterations)
        self.answer_phase = AnswerPhase(model=self.model, context_manager=self.context_manager)

        # Executors
        tool_executor = ToolExecutor(tools=TOOLS, context_manager=self.context_manager)

        self.task_executor = TaskExecutor(
            model=self.model,
            tool_executor=tool_executor,
            execute_phase=self.execute_phase,
            context_manager=self.context_manager,
        )

    async def run(self, query: str, message_history: Optional[MessageHistory] = None) -> str:
        task_results: Dict[str, Any] = {}
        completed_plans: List[dict] = []

        # Phase 1: Understand
        if callable(self.callbacks.on_phase_start):
            self.callbacks.on_phase_start('understand')

        understanding = await self.understand_phase.run(query=query, conversation_history=message_history)

        if callable(self.callbacks.on_understanding_complete):
            self.callbacks.on_understanding_complete(understanding)

        if callable(self.callbacks.on_phase_complete):
            self.callbacks.on_phase_complete('understand')

        # Iterative Plan -> Execute -> Reflect loop
        iteration = 1
        guidance_from_reflection: Optional[str] = None

        while iteration <= self.max_iterations:
            if callable(self.callbacks.on_iteration_start):
                self.callbacks.on_iteration_start(iteration)

            # Plan
            if callable(self.callbacks.on_phase_start):
                self.callbacks.on_phase_start('plan')

            plan = await self.plan_phase.run(
                query=query,
                understanding=understanding,
                prior_plans=completed_plans if completed_plans else None,
                prior_results=task_results if task_results else None,
                guidance_from_reflection=guidance_from_reflection,
            )

            if callable(self.callbacks.on_plan_created):
                self.callbacks.on_plan_created(plan, iteration)

            if callable(self.callbacks.on_phase_complete):
                self.callbacks.on_phase_complete('plan')

            # Execute
            if callable(self.callbacks.on_phase_start):
                self.callbacks.on_phase_start('execute')

            await self.task_executor.execute_tasks(query, plan, understanding, task_results, self.callbacks)

            if callable(self.callbacks.on_phase_complete):
                self.callbacks.on_phase_complete('execute')

            completed_plans.append(plan)

            # Reflect
            if callable(self.callbacks.on_phase_start):
                self.callbacks.on_phase_start('reflect')

            reflection = await self.reflect_phase.run(
                query=query,
                understanding=understanding,
                completed_plans=completed_plans,
                task_results=task_results,
                iteration=iteration,
            )

            if callable(self.callbacks.on_reflection_complete):
                self.callbacks.on_reflection_complete(reflection, iteration)

            if callable(self.callbacks.on_phase_complete):
                self.callbacks.on_phase_complete('reflect')

            if reflection.get('is_complete'):
                break

            guidance_from_reflection = self.reflect_phase.build_planning_guidance(reflection)
            iteration += 1

        # Answer
        if callable(self.callbacks.on_phase_start):
            self.callbacks.on_phase_start('answer')

        if callable(self.callbacks.on_answer_start):
            self.callbacks.on_answer_start()

        stream = await self.answer_phase.run(query=query, completed_plans=completed_plans, task_results=task_results)

        if callable(self.callbacks.on_answer_stream):
            # Pass the async generator through
            self.callbacks.on_answer_stream(stream)

        if callable(self.callbacks.on_phase_complete):
            self.callbacks.on_phase_complete('answer')

        # For compatibility with the TS version, return an empty string for now.
        return ""
