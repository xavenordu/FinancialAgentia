from typing import Any, Dict, List, Optional, Protocol, AsyncIterator
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
import asyncio
from asyncio import Lock, TimeoutError as AsyncTimeoutError
from time import time
from xml.parsers.expat import model
import structlog
from enum import Enum
import uuid

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

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


# Constants
DEFAULT_MAX_ITERATIONS = 5
MAX_HISTORY_MESSAGES = 20
HISTORY_SUMMARY_THRESHOLD = 15

# Phase timeouts in seconds
PHASE_TIMEOUTS = {
    'understand': 30,
    'plan': 45,
    'execute': 300,
    'reflect': 30,
    'answer': 60,
}


class StopReason(Enum):
    """Enumeration of reasons for stopping the iteration loop"""
    REFLECTION_COMPLETE = "reflection_complete"
    MAX_ITERATIONS = "max_iterations"
    NO_PROGRESS = "no_progress"
    HIGH_CONFIDENCE = "high_confidence"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class RunMetrics:
    """Metrics collected during a single orchestrator run"""
    run_id: str
    query: str
    start_time: float = field(default_factory=time)
    end_time: Optional[float] = None
    iterations: int = 0
    phase_timings: Dict[str, float] = field(default_factory=dict)
    phase_attempts: Dict[str, int] = field(default_factory=dict)
    tool_calls: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    stop_reason: Optional[StopReason] = None
    
    def record_phase(self, phase: str, duration: float, success: bool = True):
        """Record phase execution metrics"""
        self.phase_timings[phase] = self.phase_timings.get(phase, 0) + duration
        self.phase_attempts[phase] = self.phase_attempts.get(phase, 0) + 1
        
    def record_error(self, phase: str, error: str, context: Optional[dict] = None):
        """Record an error occurrence"""
        self.errors.append({
            'phase': phase,
            'error': error,
            'context': context or {},
            'timestamp': time()
        })
        
    def finalize(self, stop_reason: StopReason):
        """Finalize metrics at end of run"""
        self.end_time = time()
        self.stop_reason = stop_reason
        
    def to_dict(self) -> dict:
        """Export metrics as dictionary"""
        return {
            'run_id': self.run_id,
            'query': self.query,
            'duration': self.end_time - self.start_time if self.end_time else None,
            'iterations': self.iterations,
            'phase_timings': self.phase_timings,
            'phase_attempts': self.phase_attempts,
            'tool_calls': self.tool_calls,
            'error_count': len(self.errors),
            'errors': self.errors,
            'stop_reason': self.stop_reason.value if self.stop_reason else None
        }


class SessionStore(Protocol):
    """Protocol for session storage backends"""
    
    async def get(self, key: str) -> Optional[MessageHistory]:
        """Retrieve message history for a session"""
        ...
    
    async def set(self, key: str, value: MessageHistory) -> None:
        """Store message history for a session"""
        ...
    
    async def delete(self, key: str) -> None:
        """Delete a session"""
        ...
    
    def get_lock(self, key: str) -> Lock:
        """Get an async lock for a session key"""
        ...


class InMemorySessionStore:
    """Simple in-memory session store implementation"""
    
    def __init__(self):
        self._store: Dict[str, MessageHistory] = {}
        self._locks: Dict[str, Lock] = {}
        
    async def get(self, key: str) -> Optional[MessageHistory]:
        return self._store.get(key)
    
    async def set(self, key: str, value: MessageHistory) -> None:
        self._store[key] = value
    
    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self._locks.pop(key, None)
    
    def get_lock(self, key: str) -> Lock:
        if key not in self._locks:
            self._locks[key] = Lock()
        return self._locks[key]


class Phase(ABC):
    """Abstract base class for orchestrator phases"""
    
    @abstractmethod
    async def run(self, **kwargs) -> Any:
        """Execute the phase logic"""
        pass


class ReflectionAnalyzer:
    """Analyzes reflection output to determine iteration stopping conditions"""
    
    @staticmethod
    def should_continue(
        reflection: dict,
        iteration: int,
        max_iterations: int,
        task_results: dict,
        previous_results_snapshot: Optional[dict] = None
    ) -> tuple[bool, StopReason]:
        """
        Determines if iteration loop should continue.
        
        Returns:
            (should_continue, stop_reason)
        """
        # Explicit completion signal from reflection
        if isinstance(reflection, dict) and reflection.get('is_complete'):
            return False, StopReason.REFLECTION_COMPLETE
        
        # Max iterations reached
        if iteration >= max_iterations:
            return False, StopReason.MAX_ITERATIONS
        
        # Check for progress: did we get new results this iteration?
        if iteration > 1 and previous_results_snapshot:
            new_keys = set(task_results.keys()) - set(previous_results_snapshot.keys())
            if not new_keys:
                return False, StopReason.NO_PROGRESS
        
        # High confidence threshold
        if isinstance(reflection, dict):
            confidence = reflection.get('confidence', 0)
            if confidence > 0.9:
                return False, StopReason.HIGH_CONFIDENCE
        
        return True, None


class HistorySummarizer:
    """Handles message history summarization and pruning"""
    
    def __init__(self, model: str, max_messages: int = MAX_HISTORY_MESSAGES):
        self.model = model
        self.max_messages = max_messages
    
    async def get_context_window(self, history: MessageHistory) -> List[dict]:
        """
        Returns pruned/summarized history that fits context window.
        Keeps recent messages, summarizes older ones.
        """
        messages = history.get_messages()
        
        if len(messages) <= self.max_messages:
            return messages
        
        # Keep recent messages, summarize older ones
        recent_count = min(10, self.max_messages // 2)
        recent = messages[-recent_count:]
        older = messages[:-recent_count]
        
        # Create summary of older messages
        summary = await self._summarize_messages(older)
        
        summary_message = {
            "role": "system",
            "content": f"Previous conversation summary: {summary}"
        }
        
        return [summary_message] + recent
    
    async def _summarize_messages(self, messages: List[dict]) -> str:
        """Summarize a list of messages into a concise overview"""
        # Simple implementation - could be enhanced with LLM summarization
        if not messages:
            return "No previous context."
        
        user_queries = [m['content'] for m in messages if m.get('role') == 'user']
        assistant_responses = [m['content'] for m in messages if m.get('role') == 'assistant']
        
        summary_parts = []
        if user_queries:
            summary_parts.append(f"User asked about: {', '.join(user_queries[:3])}")
        if assistant_responses:
            summary_parts.append(f"Assistant provided {len(assistant_responses)} responses")
        
        return ". ".join(summary_parts) + "."


@dataclass
class AgentCallbacks:
    """Callbacks for monitoring agent execution"""
    on_phase_start: Optional[callable] = None
    on_phase_complete: Optional[callable] = None
    on_understanding_complete: Optional[callable] = None
    on_plan_created: Optional[callable] = None
    on_reflection_complete: Optional[callable] = None
    on_iteration_start: Optional[callable] = None
    on_answer_start: Optional[callable] = None
    on_answer_stream: Optional[callable] = None
    on_metrics_update: Optional[callable] = None


@dataclass
class AgentOptions:
    """Configuration options for the orchestrator"""
    model: str
    callbacks: Optional[AgentCallbacks] = None
    max_iterations: Optional[int] = None
    session_store: Optional[SessionStore] = None
    enable_history_summarization: bool = True
    phase_timeouts: Optional[Dict[str, int]] = None
    custom_phases: Optional[Dict[str, Phase]] = None


class Orchestrator:
    """
    Production-ready orchestrator with:
    - Isolated message history per run
    - Structured logging & metrics
    - Phase timeouts
    - Strong concurrency model
    - Iteration convergence heuristics
    - Tool sandboxing and retries
    - History summarization
    - Pluggable phases
    """

    def __init__(self, options: AgentOptions) -> None:
        self.model = options.model
        self.llm_client = None  # Placeholder for LLM client initialization
        self.callbacks = options.callbacks or AgentCallbacks()
        self.max_iterations = options.max_iterations or DEFAULT_MAX_ITERATIONS
        self.phase_timeouts = options.phase_timeouts or PHASE_TIMEOUTS
        
        # Session management
        self.session_store = options.session_store or InMemorySessionStore()
        
        # Logging
        self.logger = structlog.get_logger(__name__)
        
        # Context management
        self.context_manager = ToolContextManager('.dexter/context', self.model)
        
        # History management
        self.history_summarizer = HistorySummarizer(self.model) if options.enable_history_summarization else None
        
        # Initialize phases (allow custom implementations)
        custom_phases = options.custom_phases or {}
        
        self.phases = {
            'understand': custom_phases.get('understand', UnderstandPhase(model=self.model)),
            'plan': custom_phases.get('plan', PlanPhase(model=self.model)),
            'execute': custom_phases.get('execute', ExecutePhase(model=self.model)),
            'reflect': custom_phases.get('reflect', ReflectPhase(model=self.model, max_iterations=self.max_iterations)),
            'answer': custom_phases.get('answer', AnswerPhase(model=self.model, context_manager=self.context_manager, llm_client=self.llm_client)),
        }
        
        # Tool execution with retry logic
        tool_executor = ToolExecutor(tools=TOOLS, context_manager=self.context_manager)
        self.tool_executor_with_retry = self._wrap_tool_executor_with_retry(tool_executor)
        
        self.task_executor = TaskExecutor(
            model=self.model,
            tool_executor=self.tool_executor_with_retry,
            execute_phase=self.phases['execute'],
            context_manager=self.context_manager,
        )

    def _wrap_tool_executor_with_retry(self, tool_executor: ToolExecutor) -> ToolExecutor:
        """Wrap tool executor methods with retry logic"""
        
        original_execute = tool_executor.execute_tool
        
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type((ConnectionError, TimeoutError)),
            reraise=True
        )
        async def execute_with_retry(tool_name: str, params: dict, context: Any = None):
            self.logger.info("tool_execute_attempt", tool=tool_name)
            return await original_execute(tool_name, params, context)
        
        tool_executor.execute_tool = execute_with_retry
        return tool_executor

    def _safe_callback(self, callback: Optional[callable], *args) -> None:
        """Execute callback with error containment"""
        if callable(callback):
            try:
                callback(*args)
            except Exception as exc:
                self.logger.warning("callback_failed", error=str(exc))

    async def _run_phase_with_timeout(
        self,
        phase_name: str,
        phase: Phase,
        metrics: RunMetrics,
        **kwargs
    ) -> Any:
        """
        Execute a phase with timeout and metrics collection.
        
        Args:
            phase_name: Name of the phase for logging
            phase: Phase instance to execute
            metrics: RunMetrics instance for recording
            **kwargs: Arguments to pass to phase.run()
            
        Returns:
            Phase result or error dict
        """
        timeout = self.phase_timeouts.get(phase_name, 60)
        start = time()
        
        self.logger.info(
            "phase_start",
            phase=phase_name,
            run_id=metrics.run_id,
            timeout=timeout
        )
        
        try:
            result = await asyncio.wait_for(phase.run(**kwargs), timeout=timeout)
            duration = time() - start
            
            metrics.record_phase(phase_name, duration, success=True)
            
            self.logger.info(
                "phase_complete",
                phase=phase_name,
                run_id=metrics.run_id,
                duration=duration
            )
            
            return result
            
        except AsyncTimeoutError:
            duration = time() - start
            error_msg = f"{phase_name} phase timeout after {timeout}s"
            
            metrics.record_phase(phase_name, duration, success=False)
            metrics.record_error(phase_name, error_msg)
            
            self.logger.error(
                "phase_timeout",
                phase=phase_name,
                run_id=metrics.run_id,
                timeout=timeout
            )
            
            return {"error": error_msg, "failed": True, "timeout": True}
            
        except Exception as exc:
            duration = time() - start
            error_msg = str(exc)
            
            metrics.record_phase(phase_name, duration, success=False)
            metrics.record_error(phase_name, error_msg, {'exception_type': type(exc).__name__})
            
            self.logger.error(
                "phase_failed",
                phase=phase_name,
                run_id=metrics.run_id,
                error=error_msg,
                duration=duration
            )
            
            return {"error": error_msg, "failed": True}

    async def _get_or_create_history(
        self,
        session_id: Optional[str],
        run_id: str
    ) -> MessageHistory:
        """
        Get existing history from session store or create new one.
        Thread-safe with session locking.
        """
        if not session_id:
            # No session - create isolated history for this run
            self.logger.info("creating_isolated_history", run_id=run_id)
            return MessageHistory(model=self.model)
        
        # Session-based history with locking
        lock = self.session_store.get_lock(session_id)
        
        async with lock:
            history = await self.session_store.get(session_id)
            
            if history is None:
                self.logger.info(
                    "creating_new_session",
                    session_id=session_id,
                    run_id=run_id
                )
                history = MessageHistory(model=self.model)
                await self.session_store.set(session_id, history)
            else:
                self.logger.info(
                    "loaded_existing_session",
                    session_id=session_id,
                    run_id=run_id,
                    message_count=len(history.get_messages())
                )
            
            return history

    async def _save_history(
        self,
        session_id: Optional[str],
        history: MessageHistory,
        run_id: str
    ) -> None:
        """Save history back to session store if session_id provided"""
        if not session_id:
            return
        
        lock = self.session_store.get_lock(session_id)
        
        async with lock:
            await self.session_store.set(session_id, history)
            self.logger.info(
                "saved_session",
                session_id=session_id,
                run_id=run_id,
                message_count=len(history.get_messages())
            )

    async def run(
        self,
        query: str,
        session_id: Optional[str] = None,
        skip_phases: Optional[List[str]] = None,
    ) -> str:
        """
        Run the agent with a query.
        
        Args:
            query: The user's query
            session_id: Optional session ID for persistent conversation
            skip_phases: Optional list of phase names to skip
            
        Returns:
            The final answer as a string
        """
        # Generate unique run ID
        run_id = str(uuid.uuid4())
        
        # Initialize metrics
        metrics = RunMetrics(run_id=run_id, query=query)
        
        self.logger.info(
            "run_start",
            run_id=run_id,
            query=query,
            session_id=session_id,
            max_iterations=self.max_iterations
        )
        
        try:
            # Get or create isolated history for this run
            history = await self._get_or_create_history(session_id, run_id)
            
            # Apply history summarization if enabled
            if self.history_summarizer:
                context_messages = await self.history_summarizer.get_context_window(history)
                # Create a context-aware history view
                working_history = MessageHistory(model=self.model)
                for msg in context_messages:
                    working_history._messages.append(msg)
            else:
                working_history = history
            
            # Initialize execution state
            task_results: Dict[str, Any] = {}
            completed_plans: List[dict] = []
            skip_phases = skip_phases or []
            
            # Phase 1: UNDERSTAND
            if 'understand' not in skip_phases:
                self._safe_callback(self.callbacks.on_phase_start, 'understand')
                
                understanding = await self._run_phase_with_timeout(
                    'understand',
                    self.phases['understand'],
                    metrics,
                    query=query,
                    conversation_history=working_history
                )
                
                self._safe_callback(self.callbacks.on_understanding_complete, understanding)
                self._safe_callback(self.callbacks.on_phase_complete, 'understand')
            else:
                understanding = {"query": query, "skipped": True}
            
            iteration = 1
            guidance_from_reflection: Optional[str] = None
            previous_results_snapshot: Optional[dict] = None
            
            # Iterative Plan -> Execute -> Reflect loop
            while iteration <= self.max_iterations:
                metrics.iterations = iteration
                
                self.logger.info("iteration_start", run_id=run_id, iteration=iteration)
                self._safe_callback(self.callbacks.on_iteration_start, iteration)
                
                # Snapshot results for progress detection
                previous_results_snapshot = dict(task_results)
                
                # Phase 2: PLAN
                if 'plan' not in skip_phases:
                    self._safe_callback(self.callbacks.on_phase_start, 'plan')
                    
                    plan = await self._run_phase_with_timeout(
                        'plan',
                        self.phases['plan'],
                        metrics,
                        query=query,
                        understanding=understanding,
                        prior_plans=completed_plans if completed_plans else None,
                        prior_results=task_results if task_results else None,
                        guidance_from_reflection=guidance_from_reflection,
                        conversation_history=working_history,
                    )
                    
                    self._safe_callback(self.callbacks.on_plan_created, plan, iteration)
                    self._safe_callback(self.callbacks.on_phase_complete, 'plan')
                else:
                    plan = {"skipped": True}
                
                # Phase 3: EXECUTE
                if 'execute' not in skip_phases:
                    self._safe_callback(self.callbacks.on_phase_start, 'execute')
                    
                    try:
                        await self.task_executor.execute_tasks(
                            query=query,
                            plan=plan,
                            understanding=understanding,
                            task_results=task_results,
                            callbacks=self.callbacks
                        )
                        
                        # Count tool calls
                        metrics.tool_calls = len([k for k in task_results.keys() if not k.startswith('__')])
                        
                    except Exception as exc:
                        error_key = f"__executor_error_iter_{iteration}"
                        task_results[error_key] = {
                            "error": str(exc),
                            "failed": True,
                        }
                        metrics.record_error('execute', str(exc), {'iteration': iteration})
                    
                    self._safe_callback(self.callbacks.on_phase_complete, 'execute')
                
                completed_plans.append(plan)
                
                # Phase 4: REFLECT
                if 'reflect' not in skip_phases:
                    self._safe_callback(self.callbacks.on_phase_start, 'reflect')
                    
                    reflection = await self._run_phase_with_timeout(
                        'reflect',
                        self.phases['reflect'],
                        metrics,
                        query=query,
                        understanding=understanding,
                        completed_plans=completed_plans,
                        task_results=task_results,
                        iteration=iteration,
                    )
                    
                    self._safe_callback(self.callbacks.on_reflection_complete, reflection, iteration)
                    self._safe_callback(self.callbacks.on_phase_complete, 'reflect')
                    
                    # Check if we should continue iterating
                    should_continue, stop_reason = ReflectionAnalyzer.should_continue(
                        reflection=reflection,
                        iteration=iteration,
                        max_iterations=self.max_iterations,
                        task_results=task_results,
                        previous_results_snapshot=previous_results_snapshot
                    )
                    
                    if not should_continue:
                        self.logger.info(
                            "iteration_stopped",
                            run_id=run_id,
                            iteration=iteration,
                            reason=stop_reason.value
                        )
                        metrics.finalize(stop_reason)
                        break
                    
                    # Build guidance for next iteration
                    guidance_from_reflection = self.phases['reflect'].build_planning_guidance(reflection)
                
                iteration += 1
            
            # Finalize metrics if not already done
            if not metrics.stop_reason:
                metrics.finalize(StopReason.MAX_ITERATIONS)
            
            # Phase 5: ANSWER
            if 'answer' not in skip_phases:
                self._safe_callback(self.callbacks.on_phase_start, 'answer')
                self._safe_callback(self.callbacks.on_answer_start)
                
                stream = await self._run_phase_with_timeout(
                    'answer',
                    self.phases['answer'],
                    metrics,
                    query=query,
                    completed_plans=completed_plans,
                    task_results=task_results,
                    message_history=working_history,
                )
                
                # Collect the final answer from the stream
                final_answer = ""
                if isinstance(stream, str):
                    final_answer = stream
                elif hasattr(stream, '__aiter__'):
                    async for chunk in stream:
                        if isinstance(chunk, str):
                            final_answer += chunk
                
                self._safe_callback(self.callbacks.on_answer_stream, stream)
                self._safe_callback(self.callbacks.on_phase_complete, 'answer')
            else:
                final_answer = "Answer phase skipped"
            
            # Update the actual history (not the summarized working history)
            history.add_agent_message(query, final_answer)
            
            # Save history back to session store
            await self._save_history(session_id, history, run_id)
            
            # Emit final metrics
            self._safe_callback(self.callbacks.on_metrics_update, metrics)
            
            self.logger.info(
                "run_complete",
                run_id=run_id,
                metrics=metrics.to_dict()
            )
            
            return final_answer
            
        except Exception as exc:
            metrics.record_error('orchestrator', str(exc))
            metrics.finalize(StopReason.ERROR)
            
            self.logger.error(
                "run_failed",
                run_id=run_id,
                error=str(exc),
                metrics=metrics.to_dict()
            )
            
            # Re-raise to caller
            raise

    async def clear_session(self, session_id: str) -> None:
        """Clear a session from the store"""
        await self.session_store.delete(session_id)
        self.logger.info("session_cleared", session_id=session_id)