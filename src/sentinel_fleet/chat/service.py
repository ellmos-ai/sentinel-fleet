"""Governed chat service.

Every model call in this file goes through `gateway.execute_tool_call`, exactly like the
OmniLedger tools do. Nothing here talks to a provider directly: the gateway is what applies
the agent's least-privilege scope, the PII sanitiser and the permission gate, so the chat
console inherits the same guarantees as the invoice pipeline instead of a parallel set.

Session shape and the store seam follow ellmos-chat: sessions hold an ordered message list,
persistence sits behind an injectable store rather than in the service body.
"""

import asyncio
import logging
import os
import time
from typing import List, Optional, Sequence, Tuple

from sentinel_fleet.chat.backends import (
    BackendReply,
    ModelBackend,
    SUPPORTED_MODELS,
    create_backend,
)
from sentinel_fleet.chat.models import (
    ChatMessage,
    ChatMode,
    ChatRole,
    ChatSession,
    RaceLane,
    RaceRecord,
    RaceVerdict,
)
from sentinel_fleet.conductor.lifecycle import lifecycle_manager
from sentinel_fleet.core.access import RequestPrincipal
from sentinel_fleet.core.gateway import gateway
from sentinel_fleet.core.prompts import prompt_registry
from sentinel_fleet.core.skills import skill_registry
from sentinel_fleet.core.storage import get_store
from sentinel_fleet.core.telemetry import telemetry

logger = logging.getLogger(__name__)

CHAT_AGENT_ID = "agent:chat-operator"
CHAT_TOOL_NAME = "chat_completion"

# Each race lane runs under its own agent identity. The gateway serialises calls per agent,
# so lanes sharing one identity would queue behind each other and the reported latencies
# would measure the queue rather than the models. Separate identities also keep a quarantined
# lane from taking the other lanes down with it.
RACE_LANE_AGENT_IDS = [
    "agent:race-lane-1",
    "agent:race-lane-2",
    "agent:race-lane-3",
    "agent:race-lane-4",
]
MAX_RACE_LANES = len(RACE_LANE_AGENT_IDS)

FLEET_BASE_PROMPT = (
    "You are the SentinelFleet operator console assistant. You support an enterprise fleet "
    "that processes documents under statutory compliance rules and a zero-trust governance "
    "model. Answer precisely and cite the constraint you are relying on. If an action would "
    "have external effect - sending mail, moving money, publishing a record - say that it "
    "requires operator approval instead of describing it as done."
)

# The compare-race rubric. Latency is one dimension among several and deliberately last:
# a fast wrong answer does not win a race.
RACE_DIMENSIONS = [
    "quality",
    "correctness",
    "completeness",
    "instruction fidelity",
    "latency",
]

JUDGE_INSTRUCTIONS = (
    "You are judging the answers below, which all responded to the same prompt.\n"
    "Fill in one row per model across these dimensions: "
    + ", ".join(RACE_DIMENSIONS)
    + ".\n"
    "Rules: every rating needs a criterion or a quote from the answer it rates - no rating "
    "without a source. The stopwatch is only one picture; latency is one dimension among "
    "several, not the ranking. If you are judging your own model family, say so and argue "
    "more strictly. Close with a winner and the reservations that come with it."
)


class ChatBlockedError(Exception):
    """Model Armor refused the message. Carries the patterns that matched, for the reply."""

    def __init__(self, patterns: List[str]):
        self.patterns = patterns
        super().__init__("Message blocked by Model Armor")


class ComponentAuthorizationError(ValueError):
    """A selected prompt or skill is not executable by the calling agent."""


def _new_id(prefix: str) -> str:
    return f"{prefix}-{os.urandom(5).hex().upper()}"


class ChatService:
    def __init__(self, store=None, backend: Optional[ModelBackend] = None):
        self._store = store if store is not None else get_store("chat_sessions", ChatSession)
        self._backend = backend

    @property
    def backend(self) -> ModelBackend:
        """Resolved per call so a key added at runtime is honoured without a restart."""
        return self._backend or create_backend()

    # -- sessions ---------------------------------------------------------------

    def create_session(
        self,
        title: str = "",
        owner_id: str = "operator",
        organization_id: str = "sentinel-demo",
    ) -> ChatSession:
        session = ChatSession(
            session_id=_new_id("chat"),
            title=title.strip() or "New conversation",
            owner_id=owner_id,
            organization_id=organization_id,
        )
        self._store.put(session.session_id, session)
        return session

    @staticmethod
    def can_read(
        session: ChatSession,
        requested_by: str,
        requested_department: Optional[str] = None,
        requested_organization: str = "sentinel-demo",
    ) -> bool:
        if session.organization_id in {"", "legacy-unassigned"}:
            return False
        if session.organization_id != requested_organization:
            return False
        return (
            session.owner_id == requested_by
            or (
                session.visibility == "organization"
            )
            or (
                requested_by in session.shared_with
            )
            or (
                session.visibility == "department"
                and bool(requested_department)
                and session.department_id == requested_department
            )
        )

    def get_session(
        self,
        session_id: str,
        requested_by: Optional[str] = None,
        requested_department: Optional[str] = None,
        requested_organization: str = "sentinel-demo",
    ) -> Optional[ChatSession]:
        session = self._store.get(session_id)
        if session is None:
            return None
        if requested_by is not None and not self.can_read(
            session, requested_by, requested_department, requested_organization
        ):
            return None
        return session

    def list_sessions(
        self,
        requested_by: Optional[str] = None,
        requested_department: Optional[str] = None,
        requested_organization: str = "sentinel-demo",
    ) -> List[ChatSession]:
        sessions = self._store.list_all()
        if requested_by is not None:
            sessions = [
                session for session in sessions
                if self.can_read(
                    session, requested_by, requested_department, requested_organization
                )
            ]
        return sorted(sessions, key=lambda s: s.updated_at, reverse=True)

    def update_sharing(
        self,
        session_id: str,
        *,
        requested_by: str,
        requested_organization: str = "sentinel-demo",
        requested_department: Optional[str] = None,
        visibility: str,
        shared_with: Sequence[str],
    ) -> ChatSession:
        session = self._store.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if session.owner_id != requested_by:
            raise PermissionError("Only the chat creator may change sharing")
        if session.organization_id != requested_organization:
            raise PermissionError("The chat belongs to another organization")
        if visibility not in {"private", "department", "organization"}:
            raise ValueError("visibility must be private, department or organization")
        if visibility == "department" and not requested_department:
            raise ValueError("A user without a department cannot use department sharing")
        session.visibility = visibility
        session.department_id = requested_department if visibility == "department" else None
        session.shared_with = []
        for value in shared_with:
            target = value.strip()
            if target and target != requested_by and len(target) <= 200 and target not in session.shared_with:
                session.shared_with.append(target)
            if len(session.shared_with) >= 50:
                break
        return self._persist(session)

    def _persist(self, session: ChatSession) -> ChatSession:
        session.updated_at = time.time()
        self._store.put(session.session_id, session)
        return session

    # -- prompt assembly --------------------------------------------------------

    def build_system_prompt(
        self,
        skill_ids: Sequence[str] = (),
        prompt_id: str = "",
        prompt_version: str = "",
        agent_id: str = CHAT_AGENT_ID,
        *,
        requested_by: str = "operator",
        organization_id: str = "sentinel-demo",
        department_id: Optional[str] = None,
        actor_roles: Optional[Sequence[str]] = None,
    ) -> Tuple[str, List[str]]:
        """Compose the system prompt from the fleet base, the loaded skills and one prompt version.

        Returns the prompt and a human-readable digest of what went into it, so both the demo
        backend and the UI can show the operator exactly which instructions were in force.
        """
        parts = [FLEET_BASE_PROMPT]
        digest: List[str] = []
        effective_roles = list(actor_roles) if actor_roles is not None else ["operator"]
        agent = lifecycle_manager.get_agent(agent_id)
        if agent is None:
            raise ComponentAuthorizationError(f"Agent '{agent_id}' is not registered.")

        loaded = []
        for skill_id in skill_ids:
            skill = skill_registry.get_visible(
                skill_id,
                requested_by=requested_by,
                organization_id=organization_id,
                department_id=department_id,
                roles=effective_roles,
            )
            if not skill:
                # Do not disclose whether an opaque foreign component identifier exists.
                raise ComponentAuthorizationError(
                    f"Skill '{skill_id}' is not registered or unavailable."
                )
            if skill.execution_gate != "auto":
                raise ComponentAuthorizationError(
                    f"Skill '{skill_id}' is {skill.execution_gate}; it is not approved for execution."
                )
            if "*" not in skill.allowed_agents and agent.agent_id not in skill.allowed_agents:
                raise ComponentAuthorizationError(
                    f"Skill '{skill_id}' is not allowed for agent '{agent.agent_id}'."
                )
            skill_inspection = gateway.model_armor.inspect_prompt(
                f"{skill.description}\n{skill.body}"
            )
            if not skill_inspection.is_safe:
                raise ComponentAuthorizationError(
                    f"Skill '{skill_id}' contains a blocked instruction pattern."
                )
            loaded.append(f"{skill.skill_id} v{skill.version}")
            block = [f"# Skill: {skill.name} (v{skill.version}, pillar {skill.pillar})",
                     skill.description]
            if skill.body:
                block.append(skill.body)
            parts.append("\n".join(block))
        digest.append(
            f"skills loaded        {len(loaded)}" + (f" ({', '.join(loaded)})" if loaded else "")
        )

        if prompt_id:
            prompt = prompt_registry.get_visible(
                prompt_id,
                requested_by=requested_by,
                organization_id=organization_id,
                department_id=department_id,
                roles=effective_roles,
            )
            if prompt:
                if prompt.requires_approval:
                    raise ComponentAuthorizationError(
                        f"Prompt '{prompt_id}' requires approval and has no approved execution grant."
                    )
                if agent.role.value not in prompt.allowed_roles:
                    raise ComponentAuthorizationError(
                        f"Prompt '{prompt_id}' is not allowed for role '{agent.role.value}'."
                    )
                version = (
                    prompt_registry.get_version(prompt_id, prompt_version)
                    if prompt_version else None
                )
                if prompt_version and version is None:
                    raise ComponentAuthorizationError(
                        f"Prompt '{prompt_id}' version '{prompt_version}' is unavailable."
                    )
                text = version.text if version else prompt.current_text
                inspection = gateway.model_armor.inspect_prompt(text)
                if not inspection.is_safe:
                    raise ComponentAuthorizationError(
                        f"Prompt '{prompt_id}' contains a blocked instruction pattern."
                    )
                shown = version.version_number if version else prompt.active_version
                parts.append(f"# Prompt template: {prompt.title} (v{shown})\n{text}")
                digest.append(f"prompt template      {prompt.id} v{shown}")
            else:
                raise ComponentAuthorizationError(f"Prompt '{prompt_id}' is unavailable.")
        else:
            digest.append("prompt template      none selected")

        return "\n\n".join(parts), digest

    # -- the single governed model call ----------------------------------------

    async def _chat_completion(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        config_digest: str = ""
    ) -> BackendReply:
        """The tool body the gateway invokes. Never called directly from a route."""
        return await self.backend.complete(
            system_prompt=system_prompt,
            user_message=user_message,
            model=model,
            config_digest=config_digest
        )

    async def _run_completion(
        self,
        agent_id: str,
        system_prompt: str,
        user_message: str,
        model: str,
        config_digest: str = "",
        principal: Optional[RequestPrincipal] = None,
    ) -> BackendReply:
        agent = lifecycle_manager.get_agent(agent_id)
        if agent is None:
            raise LookupError(f"Agent '{agent_id}' is not registered")

        result = await gateway.execute_tool_call(
            agent=agent,
            tool_name=CHAT_TOOL_NAME,
            tool_args={
                "system_prompt": system_prompt,
                "user_message": user_message,
                "model": model,
                "config_digest": config_digest
            },
            tool_func=self._chat_completion,
            principal=principal,
        )
        if not result.success:
            return BackendReply(
                content=f"The gateway refused this call: {result.error}",
                model=model,
                mode=ChatMode.DETERMINISTIC_DEMO,
                error=result.error or "gateway refusal"
            )
        return result.output

    def _guard(self, message: str) -> None:
        inspection = gateway.model_armor.inspect_prompt(message)
        if not inspection.is_safe:
            raise ChatBlockedError(inspection.blocked_patterns)

    @staticmethod
    def _blocked_message(patterns: List[str], model: str) -> ChatMessage:
        """A refusal is an answer: it names what matched, so the operator can act on it."""
        return ChatMessage(
            message_id=_new_id("msg"),
            role=ChatRole.ASSISTANT,
            content=(
                "Blocked by Model Armor. This message matched a prompt injection pattern, "
                "so it was never sent to a model.\n\n"
                "Matched patterns:\n"
                + "\n".join(f"  - {p}" for p in patterns)
                + "\n\nRephrase the request without instructions that try to override the "
                  "system prompt, and send it again."
            ),
            model=model,
            mode=ChatMode.BLOCKED,
            blocked_patterns=patterns
        )

    # -- public API -------------------------------------------------------------

    async def send(
        self,
        message: str,
        session_id: str = "",
        model: str = "",
        skill_ids: Optional[Sequence[str]] = None,
        prompt_id: str = "",
        prompt_version: str = "",
        owner_id: str = "operator",
        organization_id: str = "sentinel-demo",
        department_id: Optional[str] = None,
        actor_roles: Optional[Sequence[str]] = None,
    ) -> Tuple[ChatSession, ChatMessage]:
        model = model or SUPPORTED_MODELS[0]
        skill_ids = list(skill_ids or [])

        session = self._store.get(session_id) if session_id else None
        if session_id and (session is None or session.owner_id != owner_id):
            raise PermissionError("Chat session does not exist or belongs to another workspace.")
        if session is not None and session.organization_id != organization_id:
            raise PermissionError("Chat session belongs to another organization.")
        if session is None:
            session = self.create_session(
                title=message[:60], owner_id=owner_id, organization_id=organization_id
            )

        session.messages.append(ChatMessage(
            message_id=_new_id("msg"),
            role=ChatRole.USER,
            content=message
        ))

        telemetry_principal = RequestPrincipal(
            user_id=owner_id,
            data_owner_id=owner_id,
            authenticated=False,
            department=department_id,
            organization_id=organization_id,
        )
        span = telemetry.start_span(
            "chat:send", CHAT_AGENT_ID, {"model": model}, principal=telemetry_principal
        )
        try:
            self._guard(message)
        except ChatBlockedError as blocked:
            telemetry.end_span(span, status="BLOCKED", error="Model Armor intercepted the message")
            reply = self._blocked_message(blocked.patterns, model)
            session.messages.append(reply)
            self._persist(session)
            return session, reply

        system_prompt, digest = self.build_system_prompt(
            skill_ids,
            prompt_id,
            prompt_version,
            requested_by=owner_id,
            organization_id=organization_id,
            department_id=department_id,
            actor_roles=actor_roles,
        )
        backend_reply = await self._run_completion(
            agent_id=CHAT_AGENT_ID,
            system_prompt=system_prompt,
            user_message=message,
            model=model,
            config_digest="\n".join(digest),
            principal=telemetry_principal,
        )
        telemetry.end_span(span, status="OK")

        reply = ChatMessage(
            message_id=_new_id("msg"),
            role=ChatRole.ASSISTANT,
            content=backend_reply.content,
            model=backend_reply.model,
            mode=backend_reply.mode,
            latency_s=backend_reply.latency_s,
            latency_simulated=backend_reply.latency_simulated,
            skill_ids=skill_ids,
            prompt_id=prompt_id,
            prompt_version=prompt_version
        )
        session.messages.append(reply)
        self._persist(session)
        return session, reply

    async def race(
        self,
        message: str,
        models: Sequence[str],
        judge: bool = False,
        session_id: str = "",
        skill_ids: Optional[Sequence[str]] = None,
        prompt_id: str = "",
        prompt_version: str = "",
        owner_id: str = "operator",
        organization_id: str = "sentinel-demo",
        department_id: Optional[str] = None,
        actor_roles: Optional[Sequence[str]] = None,
    ) -> Tuple[ChatSession, RaceRecord]:
        """Send one prompt to several models at once and record every lane.

        Race structure follows compare-race: the lanes are the measurement, the judge is a
        separate opinion on top of them, and latency is one rubric dimension rather than the
        result.
        """
        models = list(dict.fromkeys(models))
        skill_ids = list(skill_ids or [])
        if len(models) < 2:
            raise ValueError("A race needs at least two models")
        if len(models) > MAX_RACE_LANES:
            raise ValueError(f"A race runs at most {MAX_RACE_LANES} lanes")

        session = self._store.get(session_id) if session_id else None
        if session_id and (session is None or session.owner_id != owner_id):
            raise PermissionError("Chat session does not exist or belongs to another workspace.")
        if session is not None and session.organization_id != organization_id:
            raise PermissionError("Chat session belongs to another organization.")
        if session is None:
            session = self.create_session(
                title=f"Race: {message[:48]}",
                owner_id=owner_id,
                organization_id=organization_id,
            )

        record = RaceRecord(race_id=_new_id("race"), prompt=message)

        try:
            self._guard(message)
        except ChatBlockedError as blocked:
            for index, model in enumerate(models):
                record.lanes.append(RaceLane(
                    model=model,
                    agent_id=RACE_LANE_AGENT_IDS[index],
                    content=self._blocked_message(blocked.patterns, model).content,
                    mode=ChatMode.BLOCKED
                ))
            record.verdict = RaceVerdict(
                judge_model=models[0],
                dimensions=RACE_DIMENSIONS,
                evaluated=False,
                summary="No lane ran: Model Armor blocked the prompt before dispatch."
            )
            session.races.append(record)
            self._persist(session)
            return session, record

        system_prompt, digest = self.build_system_prompt(
            skill_ids,
            prompt_id,
            prompt_version,
            requested_by=owner_id,
            organization_id=organization_id,
            department_id=department_id,
            actor_roles=actor_roles,
        )
        config_digest = "\n".join(digest)

        span = telemetry.start_span(
            "chat:race",
            CHAT_AGENT_ID,
            {"lanes": str(len(models))},
            principal=RequestPrincipal(
                user_id=owner_id,
                data_owner_id=owner_id,
                authenticated=False,
                department=department_id,
                organization_id=organization_id,
            ),
        )
        replies = await asyncio.gather(*[
            self._run_completion(
                agent_id=RACE_LANE_AGENT_IDS[index],
                system_prompt=system_prompt,
                user_message=message,
                model=model,
                config_digest=config_digest,
                principal=RequestPrincipal(
                    user_id=owner_id,
                    data_owner_id=owner_id,
                    authenticated=False,
                    department=department_id,
                    organization_id=organization_id,
                ),
            )
            for index, model in enumerate(models)
        ])
        telemetry.end_span(span, status="OK")

        for index, (model, reply) in enumerate(zip(models, replies)):
            record.lanes.append(RaceLane(
                model=model,
                agent_id=RACE_LANE_AGENT_IDS[index],
                content=reply.content,
                mode=reply.mode,
                latency_s=reply.latency_s,
                latency_simulated=reply.latency_simulated,
                error=reply.error
            ))

        if judge:
            record.verdict = await self._judge(record)

        session.races.append(record)
        self._persist(session)
        return session, record

    async def _judge(self, record: RaceRecord) -> RaceVerdict:
        """Score the lanes with the first model, through the gateway like every other call."""
        judge_model = record.lanes[0].model

        if all(lane.mode is not ChatMode.GEMINI_LIVE for lane in record.lanes):
            # No model produced these answers, so no model can score them. Returning invented
            # ratings here would be fabricated evaluation, not a labelled placeholder.
            return RaceVerdict(
                judge_model=judge_model,
                mode=ChatMode.DETERMINISTIC_DEMO,
                evaluated=False,
                dimensions=RACE_DIMENSIONS,
                rows=[
                    {"model": lane.model, **{dim: "not evaluated" for dim in RACE_DIMENSIONS}}
                    for lane in record.lanes
                ],
                summary=(
                    "Not judged. The lanes ran in demo mode, so there is no model output to "
                    "rate. Set GEMINI_API_KEY to score a live race."
                )
            )

        transcript = [f"Prompt under test:\n{record.prompt}", ""]
        for lane in record.lanes:
            transcript.append(
                f"## Answer from {lane.model} (latency {lane.latency_s:.3f}s)\n{lane.content}"
            )

        reply = await self._run_completion(
            agent_id=CHAT_AGENT_ID,
            system_prompt=JUDGE_INSTRUCTIONS,
            user_message="\n\n".join(transcript),
            model=judge_model
        )
        return RaceVerdict(
            judge_model=judge_model,
            mode=reply.mode,
            evaluated=reply.mode is ChatMode.GEMINI_LIVE,
            dimensions=RACE_DIMENSIONS,
            rows=[],
            summary=reply.content
        )


chat_service = ChatService()
