"""TaskMaster: Asynchronous Task Engine & Execution State Table."""

import time
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TaskState(str, Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskRecord(BaseModel):
    task_id: str
    name: str
    assigned_agent: str
    state: TaskState = TaskState.QUEUED
    input_data: Dict[str, Any] = Field(default_factory=dict)
    output_data: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    error_message: Optional[str] = None


class TaskMaster:
    def __init__(self):
        self._tasks: Dict[str, TaskRecord] = {}

    def create_task(self, name: str, assigned_agent: str, input_data: Dict[str, Any]) -> TaskRecord:
        task_id = f"TASK-{len(self._tasks)+1:04d}"
        task = TaskRecord(
            task_id=task_id,
            name=name,
            assigned_agent=assigned_agent,
            state=TaskState.QUEUED,
            input_data=input_data
        )
        self._tasks[task_id] = task
        return task

    def update_task_state(self, task_id: str, state: TaskState, output_data: Optional[Dict[str, Any]] = None, error: Optional[str] = None):
        task = self._tasks.get(task_id)
        if task:
            task.state = state
            task.updated_at = time.time()
            if output_data:
                task.output_data = output_data
            if error:
                task.error_message = error

    def list_all(self) -> List[TaskRecord]:
        return list(reversed(list(self._tasks.values())))


task_master = TaskMaster()
