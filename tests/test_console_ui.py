"""Tests for the operator console shell: chat panel, icon set, bounded tables, skill authoring."""

import re
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from sentinel_fleet.core.skills import skill_registry
from sentinel_fleet.web.server import DASHBOARD_ROW_LIMIT, app

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "src" / "sentinel_fleet" / "web" / "templates"
STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "sentinel_fleet" / "web" / "static"

# Pictographs, dingbats and arrows. Emoji in a control surface render differently on every
# platform and carry colour the pillar index does not control, so the console uses SVG.
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF"
    "\U00002190-\U000021FF\U00002300-\U000023FF\U0000FE0F]"
)


@pytest.mark.asyncio
async def test_console_renders_the_chat_panel_with_its_controls():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    assert 'id="tab-chat"' in body
    assert 'id="chat-transcript"' in body
    assert 'id="skill-picker"' in body
    assert 'id="chat-prompt-version"' in body, "the version picker must ship with the template"
    assert 'onclick="setChatMode(\'race\')"' in body
    assert 'onclick="exportSession(\'pdf\')"' in body
    assert 'id="prompt-catalog"' in body and 'id="skill-catalog"' in body


@pytest.mark.asyncio
async def test_both_pages_use_the_shared_icon_sprite_and_no_emoji():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/", "/blueprint"):
            body = (await client.get(path)).text
            assert 'id="i-shield"' in body, f"{path} is missing the icon sprite"
            assert '<use href="#i-' in body, f"{path} does not reference any icon"
            found = EMOJI.findall(body)
            assert not found, f"{path} still renders emoji glyphs: {sorted(set(found))}"


def test_stylesheet_and_script_carry_no_emoji():
    for path in (STATIC_DIR / "style.css", STATIC_DIR / "app.js"):
        found = EMOJI.findall(path.read_text(encoding="utf-8"))
        assert not found, f"{path.name} still contains emoji: {sorted(set(found))}"


def test_light_theme_stays_the_default():
    """The operator's anchor: dark is available, light is what loads."""
    for name in ("index.html", "blueprint.html"):
        html = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
        assert 'data-theme="light"' in html, f"{name} does not open in the light theme"

    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'localStorage.getItem("sentinel_theme") || "light"' in app_js
    assert 'localStorage.getItem("sentinel_active_tab")' in app_js, "tab persistence was dropped"


def test_every_referenced_icon_exists_in_the_sprite():
    sprite = (TEMPLATE_DIR / "_icons.html").read_text(encoding="utf-8")
    defined = set(re.findall(r'<symbol id="(i-[a-z-]+)"', sprite))

    referenced = set()
    for name in ("index.html", "blueprint.html", "_masthead.html"):
        referenced |= set(re.findall(r'<use href="#(i-[a-z-]+)"', (TEMPLATE_DIR / name).read_text(encoding="utf-8")))
    referenced |= set(re.findall(r'<use href="#(i-[a-z-]+)"', (STATIC_DIR / "app.js").read_text(encoding="utf-8")))

    assert referenced, "no icons are referenced at all"
    assert not (referenced - defined), f"icons referenced but not defined: {sorted(referenced - defined)}"


@pytest.mark.asyncio
async def test_dashboard_tables_render_a_bounded_tail():
    """An unbounded table turns a long-running deployment's entry page into a huge document."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for index in range(DASHBOARD_ROW_LIMIT + 5):
            await client.post("/api/tasks/create", data={
                "name": f"Bounded render probe {index}",
                "assigned_agent": "agent:system-auditor"
            })

        body = (await client.get("/")).text

    # Count only the task table cells: the gate ledger shows the same names as span records.
    rendered = body.count("<b>Bounded render probe")
    assert rendered <= DASHBOARD_ROW_LIMIT, f"{rendered} task rows rendered, limit is {DASHBOARD_ROW_LIMIT}"
    assert "<b>Bounded render probe 0<" not in body, "the oldest task should have fallen out of the tail"
    assert f"of {DASHBOARD_ROW_LIMIT}" in body or "latest" in body, "the page must say the view is capped"


@pytest.mark.asyncio
async def test_create_skill_lands_in_the_registry_and_the_picker():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/skills/create", data={
            "name": "Vendor Risk Screener",
            "pillar": "domain",
            "description": "Screens a vendor against sanction lists before a booking is drafted.",
            "required_tools": "query_memory_bank, validate_tax_compliance",
            "body": "Check the vendor name against the sanctions corpus, then report the match."
        })
        assert response.status_code == 200
        skill = response.json()["skill"]
        assert skill["skill_id"] == "skill:vendor-risk-screener"
        assert skill["required_tools"] == ["query_memory_bank", "validate_tax_compliance"]

        detail = await client.get("/api/skills/skill:vendor-risk-screener")
        assert detail.status_code == 200
        assert "sanctions corpus" in detail.json()["body"]

        body = (await client.get("/")).text
        assert "vendor-risk-screener" in body, "a new skill must be selectable in the console"

    assert skill_registry.get_skill("skill:vendor-risk-screener") is not None


@pytest.mark.asyncio
async def test_create_skill_rejects_a_nameless_skill():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/skills/create", data={
            "name": "***",
            "pillar": "domain",
            "description": "No usable identifier"
        })
        assert response.status_code == 400


def test_skill_bodies_are_loaded_from_disk():
    """The chat system prompt injects these bodies, so an empty body is a silent downgrade."""
    sentry = skill_registry.get_skill("skill:model-armor-sentry")
    assert sentry is not None
    assert sentry.body, "SKILL.md body was not captured by the loader"
    assert "Purpose" in sentry.body
