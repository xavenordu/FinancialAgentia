from __future__ import annotations
from typing import Optional, Dict
from enum import Enum
from pydantic import BaseModel, Field, validator
from .schemas import Understanding, Plan


class Phase(str, Enum):
    understand = 'understand'
    plan = 'plan'
    execute = 'execute'
    reflect = 'reflect'
    answer = 'answer'
    complete = 'complete'


class TaskResult(BaseModel):
    taskId: str
    output: Optional[str] = None

    @validator("taskId")
    def validate_task_id(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError("taskId must be a non-empty string")
        return v


class AgentState(BaseModel):
    query: str
    currentPhase: Phase
    understanding: Optional[Understanding] = None
    plan: Optional[Plan] = None
    taskResults: Dict[str, TaskResult] = Field(default_factory=dict)
    currentTaskId: Optional[str] = None

    @validator("query")
    def validate_query(cls, v):
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Query must be a non-empty string")
        return v

    @validator("taskResults", pre=True)
    def ensure_dict_of_taskresults(cls, v):
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("taskResults must be a dict")
        return v

    def add_task_result(self, task_id: str, output: Optional[str]) -> None:
        """Safely insert or update a task result."""
        self.taskResults[task_id] = TaskResult(taskId=task_id, output=output)

    def set_phase(self, phase: Phase) -> None:
        """Update the phase with type safety."""
        self.currentPhase = phase

    def mark_task_active(self, task_id: Optional[str]) -> None:
        """Update the currently active task ID."""
        self.currentTaskId = task_id

    def merge_results(self, new_results: Dict[str, TaskResult]) -> None:
        """Merge external results dict into internal store safely."""
        if not new_results:
            return
        for tid, res in new_results.items():
            if isinstance(res, TaskResult):
                self.taskResults[tid] = res

    class Config:
        validate_assignment = True
        use_enum_values = True
