"""Bound public-demo resource use and isolate demonstrative quarantine state."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Literal, Optional, Tuple


UsageKind = Literal["write", "external"]


@dataclass(frozen=True)
class DemoUsageLease:
    workspace_id: str
    kind: UsageKind
    timestamp: float


class DemoUsageLimitError(RuntimeError):
    def __init__(self, retry_after: int):
        super().__init__("Public demo usage limit reached")
        self.retry_after = max(1, retry_after)


class DemoUsageGuard:
    """A bounded rolling window for the single-instance public showcase.

    The global bucket prevents cookie rotation from bypassing the cost ceiling; the workspace
    bucket keeps one visitor from using the whole allowance. This is intentionally not presented
    as distributed rate limiting.
    """

    def __init__(
        self,
        *,
        window_seconds: int = 3600,
        workspace_write_limit: int = 30,
        global_write_limit: int = 240,
        workspace_external_limit: int = 5,
        global_external_limit: int = 60,
        max_workspaces: int = 2048,
    ) -> None:
        self.window_seconds = window_seconds
        self.workspace_limits = {
            "write": workspace_write_limit,
            "external": workspace_external_limit,
        }
        self.global_limits = {
            "write": global_write_limit,
            "external": global_external_limit,
        }
        self.max_workspaces = max_workspaces
        self._global: Dict[UsageKind, Deque[float]] = {
            "write": deque(),
            "external": deque(),
        }
        self._workspaces: "OrderedDict[str, Dict[UsageKind, Deque[float]]]" = OrderedDict()
        self._quarantines: "OrderedDict[Tuple[str, str], Tuple[str, float]]" = OrderedDict()
        self._lock = threading.RLock()

    def _prune(self, rows: Deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while rows and rows[0] <= cutoff:
            rows.popleft()

    def _workspace_rows(self, workspace_id: str) -> Dict[UsageKind, Deque[float]]:
        rows = self._workspaces.pop(workspace_id, None)
        if rows is None:
            rows = {"write": deque(), "external": deque()}
        self._workspaces[workspace_id] = rows
        while len(self._workspaces) > self.max_workspaces:
            self._workspaces.popitem(last=False)
        return rows

    @staticmethod
    def _retry_after(rows: Deque[float], now: float, window_seconds: int) -> int:
        return int(max(1, (rows[0] + window_seconds) - now)) if rows else 1

    def reserve(
        self,
        workspace_id: str,
        kind: UsageKind,
        *,
        now: Optional[float] = None,
    ) -> DemoUsageLease:
        checked_at = time.monotonic() if now is None else now
        with self._lock:
            global_rows = self._global[kind]
            workspace_rows = self._workspace_rows(workspace_id)[kind]
            self._prune(global_rows, checked_at)
            self._prune(workspace_rows, checked_at)
            if len(global_rows) >= self.global_limits[kind]:
                raise DemoUsageLimitError(
                    self._retry_after(global_rows, checked_at, self.window_seconds)
                )
            if len(workspace_rows) >= self.workspace_limits[kind]:
                raise DemoUsageLimitError(
                    self._retry_after(workspace_rows, checked_at, self.window_seconds)
                )
            global_rows.append(checked_at)
            workspace_rows.append(checked_at)
            return DemoUsageLease(workspace_id, kind, checked_at)

    def release(self, lease: DemoUsageLease) -> None:
        """Roll back a reservation when no public-demo operation actually ran."""
        with self._lock:
            global_rows = self._global[lease.kind]
            workspace = self._workspaces.get(lease.workspace_id)
            workspace_rows = workspace[lease.kind] if workspace is not None else None
            try:
                global_rows.remove(lease.timestamp)
            except ValueError:
                pass
            if workspace_rows is not None:
                try:
                    workspace_rows.remove(lease.timestamp)
                except ValueError:
                    pass

    def quarantine(self, workspace_id: str, agent_id: str, reason: str) -> None:
        with self._lock:
            key = (workspace_id, agent_id)
            self._quarantines.pop(key, None)
            self._quarantines[key] = (reason, time.monotonic())
            while len(self._quarantines) > self.max_workspaces:
                self._quarantines.popitem(last=False)

    def quarantine_reason(self, workspace_id: str, agent_id: str) -> Optional[str]:
        with self._lock:
            row = self._quarantines.get((workspace_id, agent_id))
            return row[0] if row is not None else None

    def release_quarantine(self, workspace_id: str, agent_id: str) -> bool:
        with self._lock:
            return self._quarantines.pop((workspace_id, agent_id), None) is not None


demo_usage_guard = DemoUsageGuard()
