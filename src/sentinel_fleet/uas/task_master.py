"""TaskMaster: Asynchronous Task Engine & Execution State Table."""

import time
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sentinel_fleet.core.storage import get_store
from sentinel_fleet.core.errors import TaskNotFoundError


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
        self._store = get_store("tasks", TaskRecord)

    def create_task(self, name: str, assigned_agent: str, input_data: Dict[str, Any]) -> TaskRecord:
        task_id = f"TASK-{self._store.count()+1:04d}"
        task = TaskRecord(
            task_id=task_id,
            name=name,
            assigned_agent=assigned_agent,
            state=TaskState.QUEUED,
            input_data=input_data
        )
        self._store.put(task_id, task)
        return task

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        return self._store.get(task_id)

    def update_task_state(
        self,
        task_id: str,
        state: TaskState,
        output_data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> TaskRecord:
        task = self._store.get(task_id)
        if not task:
            raise TaskNotFoundError(task_id)

        task.state = state
        task.updated_at = time.time()
        if output_data:
            task.output_data = output_data
        if error:
            task.error_message = error

        self._store.put(task_id, task)
        return task

    def list_all(self) -> List[TaskRecord]:
        tasks = self._store.list_all()
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks


task_master = TaskMaster()
