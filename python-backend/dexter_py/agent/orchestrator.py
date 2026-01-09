from typing import Any, Dict, List, Optional
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
    on_phase_start: Optional[callable] = None
    on_phase_complete: Optional[callable] = None
    on_understanding_complete: Optional[callable] = None
    on_plan_created: Optional[callable] = None
    on_reflection_complete: Optional[callable] = None
    on_iteration_start: Optional[callable] = None
    on_answer_start: Optional[callable] = None
    on_answer_stream: Optional[callable] = None


@dataclass
class AgentOptions:
    model: str
    callbacks: Optional[AgentCallbacks] = None
    max_iterations: Optional[int] = None


class Agent:
    """Agent - port of the TypeScript orchestrator with conversation context management.

    This class wires phases, executors and context management together, maintaining
    conversation history across multiple queries for multi-turn interactions.
    
    Key features:
    - Multi-phase execution: Understand → Plan → Execute → Reflect → Answer
    - Persistent message history for multi-turn conversations
    - Iterative refinement loop with reflection feedback
    - Callback system for monitoring and UI updates
    """

    def __init__(self, options: AgentOptions) -> None:
        self.model = options.model
        self.callbacks = options.callbacks or AgentCallbacks()
        self.max_iterations = options.max_iterations or DEFAULT_MAX_ITERATIONS

        # Persistent conversation context maintained across queries
        self.message_history = MessageHistory(model=self.model)

        self.context_manager = ToolContextManager('.dexter/context', self.model)

        self.understand_phase = UnderstandPhase(model=self.model)
        self.plan_phase = PlanPhase(model=self.model)
        self.execute_phase = ExecutePhase(model=self.model)
        self.reflect_phase = ReflectPhase(model=self.model, max_iterations=self.max_iterations)
        self.answer_phase = AnswerPhase(model=self.model, context_manager=self.context_manager)

        tool_executor = ToolExecutor(tools=TOOLS, context_manager=self.context_manager)

        self.task_executor = TaskExecutor(
            model=self.model,
            tool_executor=tool_executor,
            execute_phase=self.execute_phase,
            context_manager=self.context_manager,
        )

    def _safe_callback(self, callback, *args) -> None:
        if callable(callback):
            try:
                callback(*args)
            except Exception:
                # Silent containment—callbacks should never interrupt control flow
                pass

    async def _safe_phase_run(self, phase, **kwargs) -> Any:
        try:
            return await phase.run(**kwargs)
        except Exception as exc:
            return {"error": str(exc), "failed": True}

    async def run(self, query: str, message_history: Optional[MessageHistory] = None) -> str:
        """Run the agent with a query, maintaining persistent conversation context.
        
        If message_history is not provided, uses the agent's internal message_history.
        Updates message_history with the answer upon completion.
        
        Args:
            query: The user's query
            message_history: Optional MessageHistory for multi-turn conversations
            
        Returns:
            The final answer as a string
        """
        # Use provided history or agent's persistent history
        history = message_history or self.message_history
        
        task_results: Dict[str, Any] = {}
        completed_plans: List[dict] = []

        self._safe_callback(self.callbacks.on_phase_start, 'understand')

        # Phase 1: UNDERSTAND - Pass conversation context
        understanding = await self._safe_phase_run(
            self.understand_phase,
            query=query,
            conversation_history=history  # Pass history for context
        )

        self._safe_callback(self.callbacks.on_understanding_complete, understanding)
        self._safe_callback(self.callbacks.on_phase_complete, 'understand')

        iteration = 1
        guidance_from_reflection: Optional[str] = None

        # Iterative Plan -> Execute -> Reflect loop
        while iteration <= self.max_iterations:
            self._safe_callback(self.callbacks.on_iteration_start, iteration)

            # Phase 2: PLAN
            self._safe_callback(self.callbacks.on_phase_start, 'plan')

            plan = await self._safe_phase_run(
                self.plan_phase,
                query=query,
                understanding=understanding,
                prior_plans=completed_plans if completed_plans else None,
                prior_results=task_results if task_results else None,
                guidance_from_reflection=guidance_from_reflection,
            )

            self._safe_callback(self.callbacks.on_plan_created, plan, iteration)
            self._safe_callback(self.callbacks.on_phase_complete, 'plan')

            # Phase 3: EXECUTE
            self._safe_callback(self.callbacks.on_phase_start, 'execute')

            try:
                await self.task_executor.execute_tasks(
                    query=query,
                    plan=plan,
                    understanding=understanding,
                    task_results=task_results,
                    callbacks=self.callbacks
                )
            except Exception as exc:
                task_results[f"__executor_error_iter_{iteration}"] = {
                    "error": str(exc),
                    "failed": True,
                }

            self._safe_callback(self.callbacks.on_phase_complete, 'execute')

            completed_plans.append(plan)

            # Phase 4: REFLECT
            self._safe_callback(self.callbacks.on_phase_start, 'reflect')

            reflection = await self._safe_phase_run(
                self.reflect_phase,
                query=query,
                understanding=understanding,
                completed_plans=completed_plans,
                task_results=task_results,
                iteration=iteration,
            )

            self._safe_callback(self.callbacks.on_reflection_complete, reflection, iteration)
            self._safe_callback(self.callbacks.on_phase_complete, 'reflect')

            # Stop condition: if reflection says we have enough data
            if isinstance(reflection, dict) and reflection.get('is_complete'):
                break

            guidance_from_reflection = self.reflect_phase.build_planning_guidance(reflection)
            iteration += 1

        # Phase 5: ANSWER - Include conversation context
        self._safe_callback(self.callbacks.on_phase_start, 'answer')
        self._safe_callback(self.callbacks.on_answer_start)

        stream = await self._safe_phase_run(
            self.answer_phase,
            query=query,
            completed_plans=completed_plans,
            task_results=task_results,
            message_history=history,  # Pass history for context-aware answering
        )

        # Collect the final answer from the stream
        final_answer = ""
        if isinstance(stream, str):
            final_answer = stream
        elif hasattr(stream, '__aiter__'):
            # Async generator: collect all chunks
            async for chunk in stream:
                if isinstance(chunk, str):
                    final_answer += chunk

        if callable(self.callbacks.on_answer_stream):
            try:
                self.callbacks.on_answer_stream(stream)
            except Exception:
                pass

        # Update message history with the completed turn
        # This allows future queries to reference this conversation
        history.add_agent_message(query, final_answer)

        self._safe_callback(self.callbacks.on_phase_complete, 'answer')

        return final_answer
