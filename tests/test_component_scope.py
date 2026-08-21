"""Tenant and creator isolation for durable prompt and skill components."""

import pytest

from sentinel_fleet.core.prompts import PromptItem, PromptRegistry
from sentinel_fleet.core.skills import AgentSkill, SkillRegistry
from sentinel_fleet.core.storage import LocalJsonStore


def _prompt_registry(tmp_path):
    return PromptRegistry(
        LocalJsonStore("scoped-prompts", PromptItem, str(tmp_path / "prompts.json"))
    )


def _skill_registry(tmp_path):
    missing = tmp_path / "missing-skills"
    return SkillRegistry(
        skills_dir=str(missing),
        store=LocalJsonStore("scoped-skills", AgentSkill, str(tmp_path / "skills.json")),
    )


def test_legacy_components_fail_closed_and_canonical_seeds_have_explicit_scope(tmp_path):
    legacy_prompt = PromptItem(
        id="prompt:legacy",
        title="Legacy",
        purpose="Old record",
        category="test",
        current_text="Do not expose this.",
    )
    legacy_skill = AgentSkill(
        skill_id="skill:legacy",
        name="legacy",
        pillar="test",
        description="Old record",
    )

    assert legacy_prompt.owner_id == "legacy-unassigned"
    assert legacy_prompt.organization_id == "legacy-unassigned"
    assert legacy_prompt.visibility == "private"
    assert legacy_skill.owner_id == "legacy-unassigned"
    assert legacy_skill.organization_id == "legacy-unassigned"
    assert legacy_skill.visibility == "private"
    assert not PromptRegistry.can_read(legacy_prompt, "anyone", "org-a")
    assert not SkillRegistry.can_read(legacy_skill, "anyone", "org-a")
    assert not PromptRegistry.can_read(
        legacy_prompt.model_copy(update={"visibility": "public"}), "anyone", "org-a"
    )

    prompts = _prompt_registry(tmp_path)
    skills = _skill_registry(tmp_path)
    prompt_seed = prompts.get_prompt("prompt:deep-task-solver")
    skill_seed = skills.get_skill("skill:model-armor-sentry")
    assert prompt_seed is not None
    assert prompt_seed.owner_id == "system:sentinel"
    assert prompt_seed.organization_id == "sentinel-demo"
    assert skill_seed is not None
    assert skill_seed.owner_id == "system:sentinel"
    assert skill_seed.organization_id == "sentinel-demo"


def test_canonical_prompt_seed_does_not_adopt_legacy_slug_collision(tmp_path):
    store = LocalJsonStore("scoped-prompts", PromptItem, str(tmp_path / "prompts.json"))
    collision = PromptItem(
        id="prompt:deep-task-solver",
        title="Deep Task Solver",
        purpose="Legacy operator prompt",
        category="test",
        current_text="attacker marker",
        visibility="organization",
    )
    store.put(collision.id, collision)

    registry = PromptRegistry(store)

    canonical = registry.get_prompt("prompt:deep-task-solver")
    assert canonical is not None
    assert canonical.current_text != "attacker marker"
    assert canonical.owner_id == "system:sentinel"
    assert canonical.organization_id == "sentinel-demo"

    quarantined = [
        prompt
        for prompt in registry.list_all()
        if prompt.id.startswith("prompt:deep-task-solver:legacy-collision:")
    ]
    assert len(quarantined) == 1
    assert quarantined[0].current_text == "attacker marker"
    assert quarantined[0].owner_id == "legacy-unassigned"
    assert quarantined[0].organization_id == "legacy-unassigned"
    assert quarantined[0].visibility == "private"
    assert not registry.can_read(quarantined[0], "other-workspace", "sentinel-demo")


def test_prompt_acl_blocks_cross_organization_and_filters_lists(tmp_path):
    registry = _prompt_registry(tmp_path)
    private = registry.create_prompt_authorized(
        title="Alice private",
        purpose="Private",
        category="test",
        text="private",
        variables=[],
        tags=[],
        owner_id="alice",
        organization_id="org-a",
    )
    department = registry.create_prompt_authorized(
        title="Finance shared",
        purpose="Department",
        category="test",
        text="department",
        variables=[],
        tags=[],
        owner_id="alice",
        organization_id="org-a",
        department_id="finance",
        visibility="department",
    )
    organization = registry.create_prompt_authorized(
        title="Org shared",
        purpose="Organization",
        category="test",
        text="organization",
        variables=[],
        tags=[],
        owner_id="alice",
        organization_id="org-a",
        visibility="organization",
    )
    restricted = registry.create_prompt_authorized(
        title="Auditor shared",
        purpose="Restricted",
        category="test",
        text="restricted",
        variables=[],
        tags=[],
        owner_id="alice",
        organization_id="org-a",
        visibility="restricted",
        allowed_roles=["auditor"],
    )

    assert registry.can_read(private, "alice", "org-a", "finance")
    assert not registry.can_read(private, "bob", "org-a", "finance")
    assert registry.can_read(department, "bob", "org-a", "finance")
    assert not registry.can_read(department, "bob", "org-a", "operations")
    assert registry.can_read(organization, "bob", "org-a", "operations")
    assert not registry.can_read(organization, "bob", "org-b", "operations")
    assert registry.can_read(restricted, "bob", "org-a", roles=["auditor"])
    assert not registry.can_read(restricted, "bob", "org-a", roles=["member"])
    assert not registry.can_read(restricted, "bob", "org-b", roles=["auditor"])

    visible = {
        item.id
        for item in registry.list_visible("bob", "org-a", "finance", roles=["member"])
    }
    assert department.id in visible
    assert organization.id in visible
    assert private.id not in visible
    assert restricted.id not in visible
    assert registry.get_visible(private.id, "bob", "org-a") is None

    restarted = _prompt_registry(tmp_path)
    persisted = restarted.get_prompt(department.id)
    assert persisted is not None
    assert persisted.organization_id == "org-a"
    assert restarted.get_visible(department.id, "bob", "org-b", "finance") is None


def test_prompt_authorized_mutations_require_owner_or_same_org_editor(tmp_path):
    registry = _prompt_registry(tmp_path)
    prompt = registry.create_prompt_authorized(
        title="Owned prompt",
        purpose="Owner checks",
        category="test",
        text="v1",
        variables=[],
        tags=[],
        owner_id="alice",
        organization_id="org-a",
    )

    with pytest.raises(PermissionError):
        registry.add_prompt_version_authorized(
            prompt.id, "1.1.0", "stolen", "foreign edit", "bob", "org-a"
        )
    with pytest.raises(PermissionError):
        registry.update_permissions_authorized(
            prompt.id, "organization", False, [], "mallory", "org-b",
            can_edit_foreign=True,
        )

    edited = registry.add_prompt_version_authorized(
        prompt.id, "1.1.0", "approved", "admin edit", "admin", "org-a",
        can_edit_foreign=True,
    )
    assert edited.current_text == "approved"
    shared = registry.update_permissions_authorized(
        prompt.id, "organization", False, [], "alice", "org-a"
    )
    assert shared.visibility == "organization"
    assert registry.delete_prompt_authorized(prompt.id, "alice", "org-a")


def test_skill_acl_and_authorized_mutations_are_tenant_scoped(tmp_path):
    registry = _skill_registry(tmp_path)
    skill = registry.create_skill_authorized(
        name="Scoped analyzer",
        pillar="dev",
        description="Only finance may see this.",
        owner_id="alice",
        organization_id="org-a",
        department_id="finance",
        visibility="department",
    )

    assert registry.can_read(skill, "bob", "org-a", "finance")
    assert not registry.can_read(skill, "bob", "org-a", "operations")
    assert not registry.can_read(skill, "bob", "org-b", "finance")
    assert registry.get_visible(skill.skill_id, "bob", "org-b", "finance") is None
    assert skill.skill_id in {
        item.skill_id for item in registry.list_visible("bob", "org-a", "finance")
    }

    restarted = _skill_registry(tmp_path)
    persisted = restarted.get_skill(skill.skill_id)
    assert persisted is not None
    assert persisted.organization_id == "org-a"
    assert restarted.get_visible(skill.skill_id, "bob", "org-b", "finance") is None

    with pytest.raises(PermissionError):
        registry.add_skill_version_authorized(
            skill.skill_id, "1.1.0", "stolen", [], "bob", "org-a"
        )
    with pytest.raises(PermissionError):
        registry.delete_skill_authorized(
            skill.skill_id, "admin-b", "org-b", can_edit_foreign=True
        )

    updated = registry.add_skill_version_authorized(
        skill.skill_id, "1.1.0", "same-org admin", [], "admin-a", "org-a",
        can_edit_foreign=True,
    )
    assert updated.version == "1.1.0"
    shared = registry.update_permissions_authorized(
        skill.skill_id, "organization", "ask_permission", "alice", "org-a"
    )
    assert shared.visibility == "organization"
    assert registry.delete_skill_authorized(skill.skill_id, "alice", "org-a")


def test_public_component_creation_requires_explicit_global_publish_permission(tmp_path):
    prompts = _prompt_registry(tmp_path)
    skills = _skill_registry(tmp_path)

    with pytest.raises(PermissionError):
        prompts.create_prompt_authorized(
            title="Accidentally public",
            purpose="Guard",
            category="test",
            text="no",
            variables=[],
            tags=[],
            owner_id="alice",
            organization_id="org-a",
            visibility="public",
        )
    with pytest.raises(PermissionError):
        skills.create_skill_authorized(
            name="Accidentally public",
            pillar="test",
            description="Guard",
            owner_id="alice",
            organization_id="org-a",
            visibility="public",
        )

    public_prompt = prompts.create_prompt_authorized(
        title="Deliberately public",
        purpose="Explicit global seed",
        category="test",
        text="yes",
        variables=[],
        tags=[],
        owner_id="publisher",
        organization_id="org-a",
        visibility="public",
        can_publish_global=True,
    )
    assert public_prompt.global_public
    assert prompts.can_read(public_prompt, "visitor", "org-b")

    public_skill = skills.create_skill_authorized(
        name="Deliberately public",
        pillar="test",
        description="Explicit global seed",
        owner_id="publisher",
        organization_id="org-a",
        visibility="public",
        can_publish_global=True,
    )
    assert public_skill.global_public
    assert skills.can_read(public_skill, "visitor", "org-b")
