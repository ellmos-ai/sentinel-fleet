"""Regression tests for the SkillRegistry path resolution.

Found live on Cloud Run: a container built with a plain `pip install .` runs skills.py
from site-packages, where the source-tree-relative `../../../skills` points into the
interpreter tree - the registry then silently seeded 3 fallback skills instead of the 32
bundled ones, and nothing logged why. These tests pin the candidate chain (explicit arg >
SENTINEL_SKILLS_DIR env > source tree > cwd) and the now-loud fallback.
"""

import logging

from sentinel_fleet.core.skills import SkillRegistry

MINI_SKILL = """---
name: test-mini-skill
pillar: dev
version: 9.9.9
description: A minimal component-v1 skill used only by the path-resolution tests.
required_tools: []
tags: [test]
---
Body of the mini skill.
"""


def _write_mini_skill(directory):
    skill_dir = directory / "mini"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(MINI_SKILL, encoding="utf-8")


def test_env_var_overrides_default_skills_dir(tmp_path, monkeypatch):
    _write_mini_skill(tmp_path)
    monkeypatch.setenv("SENTINEL_SKILLS_DIR", str(tmp_path))
    registry = SkillRegistry()
    assert registry._skills_dir == str(tmp_path)
    assert "skill:test-mini-skill" in registry._skills


def test_missing_directory_falls_back_to_seeds_and_warns(tmp_path, caplog):
    missing = tmp_path / "does-not-exist"
    with caplog.at_level(logging.WARNING, logger="sentinel_fleet.core.skills"):
        registry = SkillRegistry(skills_dir=str(missing))
    assert len(registry._skills) == 3
    assert any("falling back" in record.message for record in caplog.records)


def test_source_checkout_loads_the_full_bundled_library():
    # In a source checkout (and in an editable install) the default resolution must find
    # the real bundled library - the README and the DevPost text both promise 32 skills.
    registry = SkillRegistry()
    assert len(registry._skills) >= 30
