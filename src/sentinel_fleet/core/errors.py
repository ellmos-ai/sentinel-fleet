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


class TemplateNotFoundError(SentinelFleetError):
    """Raised when a requested task template does not exist."""
    def __init__(self, template_id: str):
        super().__init__(
            f"Task template '{template_id}' was not found in the registry.", {"template_id": template_id}
        )


class TemplateHasBindingsError(SentinelFleetError):
    """A template stays a mere skeleton while a routine or schedule is still attached to it.

    Deleting it now would silently orphan the binding rows, so both must be removed first.
    """
    def __init__(self, template_id: str, bindings: list):
        super().__init__(
            f"Task template '{template_id}' still has bindings attached ({', '.join(bindings)}). "
            "Remove the routine and schedule bindings before deleting the template.",
            {"template_id": template_id, "bindings": bindings}
        )


class TemplatePermissionError(SentinelFleetError):
    """Raised when a non-owner tries to delete a shared template instead of only hiding it."""
    def __init__(self, template_id: str, requested_by: str, owner: str):
        super().__init__(
            f"'{requested_by}' cannot delete template '{template_id}': only its owner "
            f"('{owner}') may delete it. A shared template can only be removed from your own view.",
            {"template_id": template_id, "requested_by": requested_by, "owner": owner}
        )


class MemoryEntryNotFoundError(SentinelFleetError):
    """Raised when an edit or delete names a memory key the bank does not hold."""
    def __init__(self, key: str):
        super().__init__(
            f"Memory entry '{key}' does not exist.",
            {"key": key}
        )


class MemoryPermissionError(SentinelFleetError):
    """Raised when someone edits or deletes another operator's memory entry.

    Mirrors TemplatePermissionError: the owner decides. Seeded entries are the deliberate
    exception - they belong to the deployment rather than to a person, so anyone may curate
    them; see MemoryBank.
    """
    def __init__(self, key: str, requested_by: str, owner: str):
        super().__init__(
            f"'{requested_by}' cannot change memory entry '{key}': it belongs to '{owner}'.",
            {"key": key, "requested_by": requested_by, "owner": owner}
        )


class ComponentInUseError(SentinelFleetError):
    """Raised when a prompt, a prompt version or a skill is deleted while something still uses it.

    Deleting it quietly would leave a task template pointing at a prompt that no longer exists,
    or a recorded conversation citing a version nobody can read any more - a broken reference the
    operator would only meet at the next run. The refusal names every user instead.
    """
    def __init__(self, kind: str, component_id: str, used_by: list):
        super().__init__(
            f"Cannot delete {kind} '{component_id}': still used by {', '.join(used_by)}. "
            "Change or remove those references first.",
            {"kind": kind, "component_id": component_id, "used_by": used_by}
        )


class LastVersionError(SentinelFleetError):
    """Raised when the only remaining version of a prompt is deleted.

    A prompt without a version has no text to run, so it would be a name with nothing behind it.
    Delete the whole prompt instead.
    """
    def __init__(self, prompt_id: str):
        super().__init__(
            f"Cannot delete the last remaining version of '{prompt_id}': a prompt with no version "
            "has no text to run. Delete the prompt itself instead.",
            {"prompt_id": prompt_id}
        )


class PromptNotFoundError(SentinelFleetError):
    def __init__(self, prompt_id: str):
        super().__init__(f"Prompt '{prompt_id}' does not exist.", {"prompt_id": prompt_id})


class PromptVersionNotFoundError(SentinelFleetError):
    def __init__(self, prompt_id: str, version_number: str):
        super().__init__(
            f"Prompt '{prompt_id}' has no version '{version_number}'.",
            {"prompt_id": prompt_id, "version_number": version_number}
        )
