from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field, field_validator


# ---------- BASE ----------

class StrictBase(BaseModel):
    """Shared config enforcing stricter typing and serialization."""
    model_config = {
        "extra": "forbid",
        "validate_assignment": True,
        "use_enum_values": True,
        "populate_by_name": True,
    }


# ---------- ENUMS ----------

class PlanState(str, Enum):
    PLANNING = "planning"
    AWAITING_USER = "awaiting_user"
    EXECUTING = "executing"
    COMPLETE = "complete"
    FAILED = "failed"


class StepType(str, Enum):
    ACTION = "action"
    SELECTION_REQUIRED = "selection_required"
    CONFIRMATION_REQUIRED = "confirmation_required"
    ERROR = "error"


class ActionType(str, Enum):
    TOOL = "tool"
    TOOL_RESPONSE = "tool_response"
    LLM = "llm"


# ---------- CORE MODELS ----------

class Understanding(StrictBase):
    """Extracted understanding from user query (intent + entities)."""
    intent: str = Field(description="The identified user intent from the query.")
    entities: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Extracted entities relevant to the query (e.g., tickers, time periods)."
    )


class Step(StrictBase):
    step_type: StepType = Field(description="Categorizes the step behavior for the UI.")
    name: str = Field(description="Unique name identifier for the step.")
    description: str = Field(description="Human-readable explanation of what the step does.")
    action_type: Optional[ActionType] = Field(
        None, description="The execution type associated with the step."
    )

    @field_validator("name")
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Step name cannot be empty.")
        return v


class ToolConfig(StrictBase):
    useTool: str = Field(description="Name of the tool to invoke.")
    parameters: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("useTool")
    def tool_name_valid(cls, v):
        if " " in v:
            raise ValueError("Tool names must not contain spaces.")
        return v


class ActionInput(StrictBase):
    type: str = Field(description="The action type descriptor string.")
    input: Dict[str, Any] = Field(default_factory=dict)
    tool: Optional[ToolConfig] = Field(
        None,
        description="Tool configuration if type references a TOOL action.",
    )


class ActionStep(StrictBase):
    id: str = Field(description="Unique step identifier for execution tracking.")
    name: str = Field(description="User-friendly name for the step.")
    action_input: ActionInput = Field(description="Execution instructions for the step.")


class Plan(StrictBase):
    plan_id: str = Field(description="Unique ID for the entire plan workflow.")
    steps: List[Step] = Field(default_factory=list)
    state: PlanState = PlanState.PLANNING
    current_step: int = 0
    errors: List[str] = Field(default_factory=list)
    summary: Optional[str] = Field(None, description="One sentence summary of the plan.")
    tasks: List['PlanTask'] = Field(default_factory=list, description="List of tasks in the plan.")

    # --- Helpers ---

    @property
    def is_complete(self) -> bool:
        return self.state == PlanState.COMPLETE

    @property
    def is_failed(self) -> bool:
        return self.state == PlanState.FAILED

    def next_step(self) -> Optional[Step]:
        if self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return None

    def advance(self) -> None:
        """Move to the next step safely."""
        if self.is_complete:
            raise RuntimeError("Cannot advance; plan already complete.")
        self.current_step += 1
        if self.current_step >= len(self.steps):
            self.state = PlanState.COMPLETE


class PlanTask(StrictBase):
    """A single task within a plan."""
    id: str = Field(description="Unique task identifier (e.g., 'task_1').")
    description: str = Field(description="Short task description (under 10 words).")
    taskType: Optional[str] = Field(None, description="Task type: 'use_tools' or 'reason'.")
    status: Optional[str] = Field(None, description="Task status: pending, running, complete, failed.")
    dependsOn: List[str] = Field(default_factory=list, description="IDs of tasks this depends on.")
    toolCalls: List[Dict[str, Any]] = Field(default_factory=list, description="Tool calls made by this task.")


class ReadOnlyPlan(StrictBase):
    plan: Plan
    allow_partial: bool = False


class PlanDict(StrictBase):
    plan_id: str
    steps: List[ActionStep]


class ExecutionState(StrictBase):
    execution_id: str
    status: str
    progress: Optional[str] = None

# Update forward references for Pydantic
Plan.model_rebuild()