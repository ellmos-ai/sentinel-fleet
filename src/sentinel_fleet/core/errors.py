"""Enterprise Exception Hierarchy for SentinelFleet."""


class SentinelFleetError(Exception):
    """Base exception for all SentinelFleet errors."""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class TaskNotFoundError(SentinelFleetError):
    """Raised when a requested task does not exist."""
    def __init__(self, task_id: str):
        super().__init__(f"Task '{task_id}' was not found in TaskMaster registry.", {"task_id": task_id})


class TaskStateTransitionError(SentinelFleetError):
    """Raised on invalid task state transitions."""
    def __init__(self, task_id: str, current_state: str, target_state: str):
        super().__init__(
            f"Invalid state transition for task '{task_id}': cannot move from '{current_state}' to '{target_state}'.",
            {"task_id": task_id, "current_state": current_state, "target_state": target_state}
        )


class TicketNotFoundError(SentinelFleetError):
    """Raised when a requested HITL ticket does not exist."""
    def __init__(self, ticket_id: str):
        super().__init__(f"Ticket '{ticket_id}' was not found in TicketMaster registry.", {"ticket_id": ticket_id})


class TicketResolutionError(SentinelFleetError):
    """Raised when a ticket cannot be resolved or transitioned."""
    def __init__(self, ticket_id: str, reason: str):
        super().__init__(f"Ticket '{ticket_id}' resolution failed: {reason}", {"ticket_id": ticket_id, "reason": reason})


class ContactNotFoundError(SentinelFleetError):
    """Raised when a privacy contact is not found."""
    def __init__(self, contact_id: str):
        super().__init__(f"Privacy contact '{contact_id}' not found.", {"contact_id": contact_id})


class ContactOptOutViolationError(SentinelFleetError):
    """Raised when attempting to communicate with a tombstoned or opted-out contact."""
    def __init__(self, email: str, reason: str):
        super().__init__(f"GDPR / DSGVO Violation: Cannot contact '{email}'. Reason: {reason}", {"email": email, "reason": reason})


class SkillNotFoundError(SentinelFleetError):
    """Raised when a skill ID is not registered."""
    def __init__(self, skill_id: str):
        super().__init__(f"Skill '{skill_id}' not found in registry.", {"skill_id": skill_id})


class SkillSchemaValidationError(SentinelFleetError):
    """Raised when a skill fails Component-v1 YAML schema validation."""
    def __init__(self, skill_name: str, error: str):
        super().__init__(f"Skill '{skill_name}' failed schema validation: {error}", {"skill_name": skill_name, "error": error})


class SecurityViolationError(SentinelFleetError):
    """Raised on zero-trust policy violations or unauthorized tool invocations."""
    def __init__(self, agent_id: str, tool_name: str, reason: str):
        super().__init__(
            f"Security Violation: Agent '{agent_id}' attempted unauthorized tool '{tool_name}'. {reason}",
            {"agent_id": agent_id, "tool_name": tool_name, "reason": reason}
        )


class QuarantineLockError(SentinelFleetError):
    """Raised when an agent in quarantine attempts an action."""
    def __init__(self, agent_id: str, reason: str):
        super().__init__(f"Agent '{agent_id}' is locked in QUARANTINE: {reason}", {"agent_id": agent_id, "reason": reason})
