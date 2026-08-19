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


@pytest.mark.asyncio
async def test_task_card_renders_the_step_editor_modal():
    """The step editor (concept doc, section E.4 "Minimaler Ketten-Schnitt") is JS-rendered
    from the agent/model catalogs and the per-template step list - all three must ship with
    the page for openStepsModal() to have anything to work with."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    assert 'id="modal-steps"' in body
    assert 'id="steps-editor-list"' in body
    assert "openStepsModal(" in body
    assert 'id="agent-catalog"' in body
    assert 'id="model-catalog"' in body


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
async def test_copy_affordances_exist_on_prompts_skills_and_messages():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    # A prompt card copies the version the operator selected, not just the active one.
    assert "copySelectedPromptVersion(" in body
    assert 'data-prompt-id=' in body
    assert "copySkill(" in body

    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "navigator.clipboard" in app_js
    assert "execCommand(\"copy\")" in app_js, "the insecure-context fallback was removed"
    assert "copyText(message.content" in app_js, "chat turns lost their copy button"
    assert "copyText(lane.content" in app_js, "race lanes lost their copy button"


def test_transcript_children_keep_their_height():
    """Regression guard: without this rule a race block collapses once the transcript overflows."""
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert ".chat-transcript > * { flex: 0 0 auto; }" in css


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


# ---------------------------------------------------------------------------
# Overview cards as signposts. The first live walkthrough stalled here: the
# scenario tiles read as information cards rather than controls, and each pillar
# card showed a truncated list with no way out of it ("I cannot see the others,
# I cannot click, I cannot do anything with it"). These guard the fix.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_tiles_announce_that_they_run_something():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    assert body.count("trigger-run") == 4, "every scenario tile needs its run label"
    assert body.count('<use href="#i-play"/>') == 4, "every scenario tile needs the play mark"
    assert 'id="i-play"' in body, "the play glyph must ship with the sprite"
    assert "one click runs the entire pipeline" in body, \
        "the card heading must say that a single click runs the whole thing"


@pytest.mark.asyncio
async def test_every_overview_pillar_card_leads_into_its_tab():
    """A preview that cannot be opened is a dead end, which is how all four cards read."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    overview = body.split('id="tab-overview"')[1].split('id="tab-chat"')[0]
    for tab in ("tab-fleet", "tab-tickets", "tab-domains", "tab-memory"):
        assert f"switchTab('{tab}')" in overview, f"no way from the overview into {tab}"
    assert overview.count("card-foot") == 4, "each pillar card carries exactly one exit"
    assert overview.count("card-note") == 4, "each pillar card explains what it is"


@pytest.mark.asyncio
async def test_overview_cards_name_their_jargon_and_their_scope():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    # The title asks the operator's question; the note carries the architecture term and
    # explains it, so the console still maps onto the README, the manual and the video.
    for title in ("Your agents", "Waiting for your approval", "Processed documents",
                  "What the agents know"):
        assert f"> {title}</h3>" in body, f"the overview card {title!r} lost its plain title"
    assert "Universal Autonomous System" in body, "UAS must be spelled out where it is used"
    assert "the Control pillar" in body and "the Memory\n            pillar" in body
    assert "OmniLedger, the accounting domain" in body, "OmniLedger must explain itself"
    # 15 agents ship with the demo fleet, so this card is always a slice and must say so.
    assert "Showing 4 of" in body, "a truncated card must declare that it is truncated"


@pytest.mark.asyncio
async def test_the_web_reading_skill_has_a_visible_way_through():
    """Selecting google-web-reading promises network access the fleet withholds on purpose. The
    live test stalled exactly there: "security worked so well that I could not do my research".
    The refusal has to carry the route, and the route is the Web reader panel."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    assert 'id="web-reading-hint"' in body, "the skill needs an inline hint at the composer"
    assert 'id="web-reader-panel"' in body, "the hint has to point at an identifiable panel"
    assert "focusWebReader()" in body, "the hint must take the operator to the panel"
    assert "cannot reach the network by itself - by design" in body, \
        "the limit is a governance decision and must be named as one"
    assert "Web reader — how research gets in" in body, \
        "the panel must say what it is for, not just which agent runs it"


def test_the_hint_is_bound_to_the_web_reading_skill_id():
    """A hardcoded id that no longer matches a skill would fail silently - the hint would simply
    never appear again."""
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'WEB_READING_SKILL_ID = "skill:google-web-reading"' in script
    assert skill_registry.get_skill("skill:google-web-reading") is not None, \
        "app.js points the hint at a skill id the registry does not know"


@pytest.mark.asyncio
async def test_the_console_says_what_it_is_before_it_shows_anything():
    """A first-time reader met an empty evidence book for something they had not done yet."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text
        blueprint = (await client.get("/blueprint")).text

    assert "masthead-note" in body
    assert "Agents do the document work" in body
    assert "waits for your approval" in body
    # The masthead is shared; the sentence describes the console, so it must not leak.
    assert "masthead-note" not in blueprint, "the console's explainer must not render on /blueprint"


@pytest.mark.asyncio
async def test_the_scenarios_come_before_their_evidence():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    overview = body.split('id="tab-overview"')[1].split('id="tab-chat"')[0]
    assert overview.index("trigger-grid") < overview.index('class="ledger"'), \
        "the gate ledger must follow the scenarios that fill it"
    # Both surfaces point at each other; a move that leaves the wording behind is worse than
    # no wording at all. The ledger's own pointer only renders while it is empty, so it is
    # checked in the template rather than in a page whose store other tests have already filled.
    assert "lands in the gate ledger below" in overview
    template = (TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")
    assert "Run a scenario above" in template


@pytest.mark.asyncio
async def test_the_tab_rail_is_split_into_work_and_reference():
    """Ten equally weighted tabs told the operator nothing about where to start. The cut is by
    what they are there to do, which is why Approvals moves ahead of the reference tabs."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    rail = body.split('class="tab-rail"')[1].split("</nav>")[0]
    assert "tab-group-sep" in rail, "the two groups need a visible boundary"
    assert rail.index(">Work<") < rail.index(">Reference<")

    order = re.findall(r'id="btn-(tab-[a-z]+)"', rail)
    assert order == [
        "tab-overview", "tab-chat", "tab-tickets", "tab-fleet",
        "tab-domains", "tab-contacts", "tab-memory", "tab-prompts",
        "tab-telemetry", "tab-governance",
    ], "work tabs first, reference tabs after the divider"
    # switchTab derives the button id from the pane id, so a rename here breaks every tab.
    for tab in order:
        assert f"switchTab('{tab}')" in rail


@pytest.mark.asyncio
async def test_a_scenario_run_reports_what_it_decided():
    """The run reloads the page after about a second, which read as nothing having happened."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    assert 'id="scenario-band"' in body, "the overview needs somewhere to report a run"

    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "showScenarioRunning(" in script, "the run needs a visible in-flight state"
    assert "restoreScenarioBand()" in script, "the outcome has to survive the reload"
    assert "SCENARIO_BAND_KEY" in script and "sessionStorage" in script, \
        "the outcome crosses the reload client-side; nothing new is persisted server-side"
    # Each outcome names the tab that now holds the consequence.
    for tab in ("tab-tickets", "tab-fleet", "tab-telemetry"):
        assert f'"{tab}"' in script, f"no scenario outcome leads to {tab}"


def test_the_scenario_band_reads_the_response_that_already_exists():
    """The summary must come from the process response, not from a second request or a store."""
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    summary = script.split("function summariseScenario(")[1].split("\nasync function")[0]
    assert "invoice.compliance_violations" in summary
    assert "invoice.invoice_number" in summary
    assert 'invoice.status === "booked"' in summary
    assert "fetch(" not in summary, "the band must not make a request of its own"


@pytest.mark.asyncio
async def test_one_primary_way_to_create_a_task():
    """Two equally weighted create buttons sat side by side with nothing to tell them apart."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    header = body.split("<h3>Tasks</h3>")[1].split("</div>\n        <p")[0]
    assert 'btn-primary" onclick="openWizard()"' in header, "the wizard is the primary route"
    assert "btn-inline" in header and "or fill the form directly" in header, \
        "the quick form must read as a secondary route, not a rival"
    assert header.count("btn-primary") == 1, "only one primary button belongs in this header"
    # The wizard sells the walk, not the endpoint it happens to call.
    assert "name, prompt, skills, agent, then when it runs" in body
