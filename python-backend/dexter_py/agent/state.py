from __future__ import annotations
from typing import Optional, Dict
from enum import Enum
from pydantic import BaseModel, Field
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


class AgentState(BaseModel):
    query: str
    currentPhase: Phase
    understanding: Optional[Understanding] = None
    plan: Optional[Plan] = None
    taskResults: Dict[str, TaskResult] = Field(default_factory=dict)
    currentTaskId: Optional[str] = None


def create_initial_state(query: str) -> AgentState:
    return AgentState(query=query, currentPhase=Phase.understand)
