from __future__ import annotations
from typing import List, Dict
from enum import Enum
from pydantic import BaseModel


class EntityType(str, Enum):
    ticker = 'ticker'
    date = 'date'
    metric = 'metric'
    company = 'company'
    period = 'period'
    other = 'other'


class Entity(BaseModel):
    type: EntityType
    value: str


class Understanding(BaseModel):
    intent: str
    entities: List[Entity]


class TaskType(str, Enum):
    use_tools = 'use_tools'
    reason = 'reason'


class TaskStatus(str, Enum):
    pending = 'pending'
    in_progress = 'in_progress'
    completed = 'completed'
    failed = 'failed'


class ToolCall(BaseModel):
    tool: str
    args: Dict[str, object]


class ToolCallStatus(ToolCall):
    status: str  # 'pending' | 'running' | 'completed' | 'failed'


class PlanTask(BaseModel):
    id: str
    description: str
    status: TaskStatus = TaskStatus.pending
    taskType: TaskType | None = None
    toolCalls: List[ToolCallStatus] = []
    dependsOn: List[str] = []


class Plan(BaseModel):
    summary: str
    tasks: List[PlanTask]


class ReflectionResult(BaseModel):
    isComplete: bool
    reasoning: str
    missingInfo: List[str]
    suggestedNextSteps: str


class ToolSummary(BaseModel):
    id: str
    toolName: str
    args: Dict[str, object]
    summary: str
