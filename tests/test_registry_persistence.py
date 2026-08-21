"""Operator-authored prompts and skills survive a new registry process."""

from sentinel_fleet.core.prompts import PromptItem, PromptRegistry
from sentinel_fleet.core.skills import AgentSkill, SkillRegistry
from sentinel_fleet.core.storage import LocalJsonStore


def test_prompt_registry_persists_created_prompt_and_new_version(tmp_path):
    path = tmp_path / "prompts.json"
    registry = PromptRegistry(LocalJsonStore("prompts", PromptItem, str(path)))
    created = registry.create_prompt(
        title="Durable prompt",
        purpose="Restart regression",
        category="test",
        text="First text",
        variables=[],
        tags=[],
    )
    registry.add_prompt_version(created.id, "1.1.0", "Second text", "Updated")

    restarted = PromptRegistry(LocalJsonStore("prompts", PromptItem, str(path)))
    loaded = restarted.get_prompt(created.id)
    assert loaded is not None
    assert loaded.active_version == "1.1.0"
    assert loaded.current_text == "Second text"


def test_operator_skill_persists_when_bundled_directory_is_unavailable(tmp_path):
    path = tmp_path / "skills.json"
    missing = tmp_path / "missing-skills"
    registry = SkillRegistry(
        skills_dir=str(missing),
        store=LocalJsonStore("skills", AgentSkill, str(path)),
    )
    created = registry.create_skill(
        name="Durable skill",
        pillar="dev",
        description="Restart regression",
        body="Use the durable method.",
    )

    restarted = SkillRegistry(
        skills_dir=str(missing),
        store=LocalJsonStore("skills", AgentSkill, str(path)),
    )
    loaded = restarted.get_skill(created.skill_id)
    assert loaded is not None
    assert loaded.body == "Use the durable method."
    assert loaded.origin == "operator"
