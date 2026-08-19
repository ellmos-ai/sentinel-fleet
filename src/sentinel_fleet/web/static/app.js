// SentinelFleet operator console.
// Values that came from an API are written with textContent, never interpolated into markup.

const state = {
  sessionId: "",
  sessions: [],
  chatMode: "chat",
  selectedSkills: new Set(),
  skills: [],
  prompts: [],
  agents: [],
  models: [],
  // Working copy of the template currently open in the step editor (concept doc, section
  // E.4): { templateId, steps: [...] }. Null while the modal is closed.
  stepsEditor: null,
  // Working copy of the task wizard's in-progress form (concept doc, section D Phase 2). Null
  // while the modal is closed - see defaultWizardState()/openWizard().
  wizard: null,
  // The run console's xterm.js instance, its live WebSocket and the run it is currently
  // showing (concept doc, section C.7, variant (b), the web console). `term` is created once and
  // reused across opens (`term.reset()`, see openConsoleModal); `ws` and `taskId` are null
  // whenever the modal is closed.
  runConsole: { term: null, ws: null, taskId: null }
};

document.addEventListener("DOMContentLoaded", () => {
  document.documentElement.setAttribute(
    "data-theme",
    localStorage.getItem("sentinel_theme") || "light"
  );
  switchTab(localStorage.getItem("sentinel_active_tab") || "tab-overview", false);

  state.prompts = readCatalog("prompt-catalog");
  state.skills = readCatalog("skill-catalog");
  state.agents = readCatalog("agent-catalog");
  state.models = readCatalog("model-catalog");
  if (document.getElementById("skill-picker")) {
    renderSkillPicker();
    loadSessions();
    const model = document.getElementById("chat-model");
    if (model) model.addEventListener("change", updateComposerSetupSummary);
    updateComposerSetupSummary();
  }

  // An action that reloads the page has to leave its outcome behind, or it looks like
  // nothing happened.
  restoreBands();

  renderTemplateTable(1);

  const input = document.getElementById("chat-input");
  if (input) {
    // Enter sends, shift+Enter keeps writing - the convention everywhere else in a chat.
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendChat();
      }
    });
  }
});

function readCatalog(elementId) {
  const node = document.getElementById(elementId);
  if (!node) return [];
  try {
    return JSON.parse(node.textContent) || [];
  } catch (err) {
    return [];
  }
}

function toggleTheme() {
  const next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("sentinel_theme", next);
}

function switchTab(tabId, save = true) {
  document.querySelectorAll(".tab-pane").forEach(el => { el.style.display = "none"; });
  document.querySelectorAll(".tab-btn").forEach(el => el.classList.remove("active"));

  const target = document.getElementById(tabId);
  if (target) target.style.display = "block";
  const btn = document.getElementById("btn-" + tabId);
  if (btn) btn.classList.add("active");

  if (save) localStorage.setItem("sentinel_active_tab", tabId);
}

function jumpToSection(sectionId) {
  const target = document.getElementById(sectionId);
  if (target) target.scrollIntoView({ block: "start" });
}

// ---------------------------------------------------------------------------
// Template table: filter and pager over the rows the server already rendered. Client-side on
// purpose - the rows are on the page, so a second request would buy nothing, and the history
// panel each row can open has to stay attached to its own row through both operations.
// ---------------------------------------------------------------------------

const TEMPLATE_PAGE_SIZE = 25;

function templateRows() {
  const table = document.getElementById("template-table");
  if (!table) return [];
  return Array.from(table.querySelectorAll("tbody tr.template-row"));
}

function renderTemplateTable(page = 1) {
  const rows = templateRows();
  if (rows.length === 0) return;

  const needle = (document.getElementById("template-filter")?.value || "").trim().toLowerCase();
  const matches = rows.filter(row => !needle || (row.dataset.templateName || "").includes(needle));
  const pageCount = Math.max(1, Math.ceil(matches.length / TEMPLATE_PAGE_SIZE));
  const current = Math.min(Math.max(1, page), pageCount);
  const first = (current - 1) * TEMPLATE_PAGE_SIZE;
  const visible = new Set(matches.slice(first, first + TEMPLATE_PAGE_SIZE));

  rows.forEach(row => {
    const shown = visible.has(row);
    row.style.display = shown ? "" : "none";
    // A row's history panel is a sibling row; hiding one without the other leaves an orphaned
    // panel under an unrelated template.
    const history = row.nextElementSibling;
    if (history && history.classList.contains("history-row") && !shown) {
      history.style.display = "none";
    }
  });

  const count = document.getElementById("template-count");
  if (count) {
    count.textContent = matches.length === rows.length
      ? `${rows.length} templates`
      : `${matches.length} of ${rows.length} templates`;
  }

  renderTemplatePager(current, pageCount);
}

function renderTemplatePager(current, pageCount) {
  const pager = document.getElementById("template-pager");
  if (!pager) return;
  pager.replaceChildren();
  if (pageCount <= 1) return;

  const back = document.createElement("button");
  back.className = "btn btn-sm";
  back.textContent = "Previous";
  back.disabled = current === 1;
  back.onclick = () => renderTemplateTable(current - 1);

  const where = document.createElement("span");
  where.className = "item-meta numeric";
  where.textContent = `page ${current} of ${pageCount}`;

  const next = document.createElement("button");
  next.className = "btn btn-sm";
  next.textContent = "Next";
  next.disabled = current === pageCount;
  next.onclick = () => renderTemplateTable(current + 1);

  pager.append(back, where, next);
}

function toggleModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) modal.style.display = modal.style.display === "flex" ? "none" : "flex";
}

function showToast(text) {
  document.querySelectorAll(".toast").forEach(el => el.remove());
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = text;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 1600);
}

// ---------------------------------------------------------------------------
// Copy to clipboard. The async clipboard API needs a secure context, so a plain
// http:// deployment falls back to a hidden textarea and execCommand.
// ---------------------------------------------------------------------------

async function copyText(text, button) {
  let copied = false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      copied = true;
    }
  } catch (err) {
    copied = false;
  }

  if (!copied) {
    const scratch = document.createElement("textarea");
    scratch.value = text;
    scratch.setAttribute("readonly", "");
    scratch.style.position = "fixed";
    scratch.style.opacity = "0";
    document.body.appendChild(scratch);
    scratch.select();
    try {
      copied = document.execCommand("copy");
    } catch (err) {
      copied = false;
    }
    scratch.remove();
  }

  if (button) {
    button.classList.toggle("is-done", copied);
    setTimeout(() => button.classList.remove("is-done"), 1400);
  }
  showToast(copied ? "Copied" : "Copy failed, select the text instead");
}

function copyFromAttribute(button) {
  copyText(button.getAttribute("data-copy-text") || "", button);
}

// Skill bodies are fetched on demand rather than inlined into every card, which kept
// roughly 200KB of markdown out of the initial page.
async function copySkill(skillId, button) {
  try {
    const res = await fetch(`/api/skills/${encodeURIComponent(skillId)}`);
    if (!res.ok) throw new Error("Skill not found");
    const skill = await res.json();
    const parts = [`${skill.name} (v${skill.version}, pillar ${skill.pillar})`, skill.description];
    if (skill.body) parts.push("", skill.body);
    await copyText(parts.join("\n"), button);
  } catch (err) {
    showToast(`Could not copy the skill: ${err.message}`);
  }
}

function copySelectedPromptVersion(selectId, button) {
  const select = document.getElementById(selectId);
  if (select) copyText(select.value, button);
}

// ---------------------------------------------------------------------------
// Chat console
// ---------------------------------------------------------------------------

function setChatMode(mode) {
  state.chatMode = mode;
  document.getElementById("mode-chat").classList.toggle("active", mode === "chat");
  document.getElementById("mode-race").classList.toggle("active", mode === "race");
  const raceControls = document.getElementById("race-controls");
  if (raceControls) raceControls.style.display = mode === "race" ? "flex" : "none";
  updateComposerSetupSummary();
}

function renderSkillPicker() {
  const picker = document.getElementById("skill-picker");
  if (!picker) return;
  const needle = (document.getElementById("skill-filter").value || "").toLowerCase();
  const matches = state.skills.filter(skill =>
    !needle || skill.name.toLowerCase().includes(needle) || skill.pillar.toLowerCase().includes(needle)
  );

  picker.replaceChildren();
  if (matches.length === 0) {
    const none = document.createElement("div");
    none.className = "picker-option";
    none.textContent = "No skill matches that filter.";
    picker.appendChild(none);
    return;
  }

  matches.slice(0, 60).forEach(skill => {
    const row = document.createElement("label");
    row.className = "picker-option";

    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = skill.skill_id;
    box.checked = state.selectedSkills.has(skill.skill_id);
    box.addEventListener("change", () => {
      if (box.checked) state.selectedSkills.add(skill.skill_id);
      else state.selectedSkills.delete(skill.skill_id);
      updateWebReadingHint();
      updateComposerSetupSummary();
    });

    const name = document.createElement("span");
    name.className = "picker-name";
    name.textContent = skill.name;

    const pillar = document.createElement("span");
    pillar.className = "picker-pillar";
    pillar.textContent = `${skill.pillar} v${skill.version}`;

    row.append(box, name, pillar);
    picker.appendChild(row);
  });

  updateWebReadingHint();
  updateComposerSetupSummary();
}

// ---------------------------------------------------------------------------
// Composer setup. Model, prompt, skills, the web reader and the race lanes all govern the
// answer, but they are setup: they used to push the message field - the one control the
// operator came for - off the bottom of the panel. Collapsed by default and deliberately not
// remembered, so a fresh visit always opens on the message.
//
// The toggle carries a summary of what is in force, because a collapsed panel that hides an
// active race mode or a pinned template would be worse than the crowding it fixes.
// ---------------------------------------------------------------------------

function setComposerSetupOpen(open) {
  const body = document.getElementById("composer-setup-body");
  const toggle = document.getElementById("composer-setup-toggle");
  if (!body || !toggle) return;
  body.style.display = open ? "block" : "none";
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
  toggle.classList.toggle("is-open", open);
}

function composerSetupIsOpen() {
  const body = document.getElementById("composer-setup-body");
  return !!body && body.style.display !== "none";
}

function toggleComposerSetup() {
  setComposerSetupOpen(!composerSetupIsOpen());
}

function updateComposerSetupSummary() {
  const summary = document.getElementById("composer-setup-summary");
  if (!summary) return;

  const parts = [];
  const model = document.getElementById("chat-model");
  if (model && model.value) parts.push(model.value);

  const skillCount = state.selectedSkills.size;
  if (skillCount) parts.push(`${skillCount} skill${skillCount === 1 ? "" : "s"}`);

  const prompt = document.getElementById("chat-prompt");
  if (prompt && prompt.value) {
    const entry = state.prompts.find(p => p.id === prompt.value);
    parts.push(entry ? entry.title : prompt.value);
  }

  if (state.chatMode === "race") parts.push("race mode");

  summary.textContent = parts.join(" / ");
}

// The one skill whose name promises something the fleet refuses to do on its own. Selecting it
// used to produce a dead end: the agent answered that it cannot fetch, and the panel that does
// the fetching sat unlabelled further down the composer. The hint sits outside the collapsible
// setup so it is visible the moment the skill is picked, and its button opens the setup.
const WEB_READING_SKILL_ID = "skill:google-web-reading";

function updateWebReadingHint() {
  const hint = document.getElementById("web-reading-hint");
  if (!hint) return;
  const active = state.selectedSkills.has(WEB_READING_SKILL_ID);
  hint.style.display = active ? "flex" : "none";
  const panel = document.getElementById("web-reader-panel");
  if (panel) panel.classList.toggle("is-called-for", active);
}

function focusWebReader() {
  // The panel lives inside the collapsed setup; focusing a hidden field would do nothing.
  setComposerSetupOpen(true);
  const input = document.getElementById("web-read-url");
  if (!input) return;
  input.scrollIntoView({ block: "center" });
  input.focus();
}

function onPromptTemplateChange() {
  const promptId = document.getElementById("chat-prompt").value;
  const versionSelect = document.getElementById("chat-prompt-version");
  versionSelect.replaceChildren();

  const prompt = state.prompts.find(p => p.id === promptId);
  if (!prompt) {
    versionSelect.disabled = true;
    versionSelect.appendChild(new Option("Pick a template first", ""));
    updateComposerSetupSummary();
    return;
  }

  versionSelect.disabled = false;
  prompt.versions.forEach(version => {
    const option = new Option(`v${version.version_number}`, version.version_number);
    option.selected = version.version_number === prompt.active_version;
    versionSelect.appendChild(option);
  });
  updateComposerSetupSummary();
}

async function loadSessions() {
  try {
    const res = await fetch("/api/chat/sessions");
    if (!res.ok) return;
    state.sessions = await res.json();
    renderSessionList();
  } catch (err) {
    /* the sidebar simply stays empty; the composer still works */
  }
}

function renderSessionList() {
  const list = document.getElementById("session-list");
  if (!list) return;
  list.replaceChildren();

  if (state.sessions.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.style.border = "none";
    empty.style.background = "transparent";
    const heading = document.createElement("h4");
    heading.textContent = "No conversations yet";
    const hint = document.createElement("p");
    hint.textContent = "Your first message starts one.";
    empty.append(heading, hint);
    list.appendChild(empty);
    return;
  }

  state.sessions.forEach(session => {
    const button = document.createElement("button");
    button.className = "session-item" + (session.session_id === state.sessionId ? " active" : "");
    button.addEventListener("click", () => openSession(session.session_id));

    const title = document.createElement("span");
    title.className = "session-item-title";
    title.textContent = session.title;

    const meta = document.createElement("span");
    meta.className = "session-item-meta";
    const turns = session.messages.length;
    const races = session.races.length;
    meta.textContent = `${turns} messages${races ? ` / ${races} races` : ""}`;

    button.append(title, meta);
    list.appendChild(button);
  });
}

function startNewSession() {
  state.sessionId = "";
  document.getElementById("chat-title").textContent = "New conversation";
  const transcript = document.getElementById("chat-transcript");
  transcript.replaceChildren();
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.id = "chat-empty";
  const heading = document.createElement("h4");
  heading.textContent = "Nothing sent yet";
  const hint = document.createElement("p");
  hint.textContent = "Pick the skills and prompt version that should govern the answer, then send a message.";
  empty.append(heading, hint);
  transcript.appendChild(empty);
  renderSessionList();
  document.getElementById("chat-input").focus();
}

async function openSession(sessionId) {
  const res = await fetch(`/api/chat/sessions/${sessionId}`);
  if (!res.ok) return;
  const session = await res.json();

  state.sessionId = session.session_id;
  document.getElementById("chat-title").textContent = session.title;

  const transcript = document.getElementById("chat-transcript");
  transcript.replaceChildren();
  session.messages.forEach(message => transcript.appendChild(renderTurn(message)));
  session.races.forEach(race => transcript.appendChild(renderRace(race)));
  transcript.scrollTop = transcript.scrollHeight;
  renderSessionList();
}

function modeStamp(mode) {
  const stamp = document.createElement("span");
  stamp.className = "badge-status " + (
    mode === "gemini-live" ? "badge-ok" : mode === "blocked-by-model-armor" ? "badge-danger" : "badge-warn"
  );
  stamp.textContent = mode === "gemini-live" ? "live" : mode === "blocked-by-model-armor" ? "blocked" : "demo";
  stamp.title = mode === "gemini-live"
    ? "Produced by a live model call"
    : mode === "blocked-by-model-armor"
      ? "Model Armor refused this message; no model was called"
      : "Produced without calling a model";
  return stamp;
}

function clearChatPlaceholder() {
  document.getElementById("chat-empty")?.remove();
}

function renderTurn(message) {
  const wrap = document.createElement("div");
  const isUser = message.role === "user";
  wrap.className = "turn " + (isUser ? "turn-user" : "turn-assistant");
  if (message.mode === "blocked-by-model-armor") wrap.classList.add("is-blocked");

  const head = document.createElement("div");
  head.className = "turn-head";
  const who = document.createElement("span");
  who.className = "turn-who";
  who.textContent = isUser ? "Operator" : "Assistant";
  head.appendChild(who);

  if (!isUser) {
    head.appendChild(modeStamp(message.mode));
    if (message.model) {
      const model = document.createElement("span");
      model.className = "item-meta numeric";
      model.textContent = message.model;
      head.appendChild(model);
    }
    if (message.latency_s) {
      const latency = document.createElement("span");
      latency.className = "item-meta numeric";
      latency.textContent = `${message.latency_s.toFixed(3)}s${message.latency_simulated ? " (simulated)" : ""}`;
      head.appendChild(latency);
    }
    const copy = document.createElement("button");
    copy.className = "btn btn-sm btn-icon";
    copy.title = "Copy this answer";
    copy.innerHTML = '<svg class="icon"><use href="#i-copy"/></svg>';
    copy.addEventListener("click", () => copyText(message.content, copy));
    head.appendChild(copy);
  }

  const body = document.createElement("div");
  body.className = "turn-body";
  body.textContent = message.content;

  wrap.append(head, body);
  return wrap;
}

function renderRace(race) {
  const block = document.createElement("div");
  block.className = "race-block";

  const head = document.createElement("div");
  head.className = "race-head";
  const eyebrow = document.createElement("div");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = `Race / ${race.lanes.length} lanes`;
  const prompt = document.createElement("div");
  prompt.className = "item-desc";
  prompt.textContent = race.prompt;
  head.append(eyebrow, prompt);

  const lanes = document.createElement("div");
  lanes.className = "race-lanes";
  const slowest = Math.max(...race.lanes.map(lane => lane.latency_s || 0), 0.001);

  race.lanes.forEach(lane => {
    const card = document.createElement("div");
    card.className = "lane" + (lane.latency_simulated ? " is-simulated" : "");

    const laneHead = document.createElement("div");
    laneHead.className = "lane-head";
    const model = document.createElement("span");
    model.className = "lane-model";
    model.textContent = lane.model;
    laneHead.append(model, modeStamp(lane.mode));

    const latency = document.createElement("div");
    latency.className = "lane-latency numeric";
    latency.textContent = (lane.latency_s || 0).toFixed(3);
    const unit = document.createElement("small");
    unit.textContent = lane.latency_simulated ? "s simulated" : "s measured";
    latency.appendChild(unit);

    const bar = document.createElement("div");
    bar.className = "lane-bar";
    const fill = document.createElement("span");
    fill.style.width = `${Math.max(4, ((lane.latency_s || 0) / slowest) * 100)}%`;
    bar.appendChild(fill);

    const answer = document.createElement("div");
    answer.className = "lane-answer";
    answer.textContent = lane.error ? `${lane.error}\n\n${lane.content}` : lane.content;

    const copy = document.createElement("button");
    copy.className = "btn btn-sm btn-icon";
    copy.title = "Copy this answer";
    copy.innerHTML = '<svg class="icon"><use href="#i-copy"/></svg>';
    copy.addEventListener("click", () => copyText(lane.content, copy));
    laneHead.appendChild(copy);

    card.append(laneHead, latency, bar, answer);
    lanes.appendChild(card);
  });

  block.append(head, lanes);

  if (race.verdict) {
    const verdict = document.createElement("div");
    verdict.className = "verdict";

    const label = document.createElement("div");
    label.className = "eyebrow";
    label.textContent = race.verdict.evaluated
      ? `Rubric / judged by ${race.verdict.judge_model}`
      : "Rubric / not scored";
    verdict.appendChild(label);

    const dims = document.createElement("div");
    dims.className = "verdict-dims";
    race.verdict.dimensions.forEach(dimension => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = dimension;
      dims.appendChild(chip);
    });
    verdict.appendChild(dims);

    const summary = document.createElement("div");
    summary.className = "verdict-summary";
    summary.textContent = race.verdict.summary;
    verdict.appendChild(summary);

    block.appendChild(verdict);
  }

  return block;
}

function setChatError(text) {
  const box = document.getElementById("chat-error");
  if (!box) return;
  box.textContent = text || "";
  box.style.display = text ? "block" : "none";
}

function pendingTurn(label) {
  const wrap = document.createElement("div");
  wrap.className = "turn turn-assistant";
  wrap.id = "pending-turn";
  const head = document.createElement("div");
  head.className = "turn-head";
  const spinner = document.createElement("span");
  spinner.className = "spinner";
  const who = document.createElement("span");
  who.className = "turn-who";
  who.textContent = label;
  head.append(spinner, who);
  wrap.appendChild(head);
  return wrap;
}

function collectComposer() {
  const promptId = document.getElementById("chat-prompt").value;
  const versionSelect = document.getElementById("chat-prompt-version");
  return {
    session_id: state.sessionId,
    skill_ids: Array.from(state.selectedSkills),
    prompt_id: promptId,
    prompt_version: promptId && !versionSelect.disabled ? versionSelect.value : ""
  };
}

// Web reader: fetch a public page through the gateway and offer its text to the composer.
// The operator, not the model, decides what enters the prompt - the fleet has no autonomous
// browsing loop, and this panel is the whole of what google-web-reading can do.
async function readWebPage() {
  const input = document.getElementById("web-read-url");
  const output = document.getElementById("web-read-result");
  if (!input || !output) return;

  const url = (input.value || "").trim();
  if (!url) {
    output.textContent = "Enter a URL first.";
    return;
  }

  output.textContent = `Fetching ${url} through agent:web-reader`;
  const body = new FormData();
  body.append("url", url);

  try {
    const res = await fetch("/api/web/read", { method: "POST", body });
    const data = await res.json();
    if (!res.ok) {
      output.replaceChildren();
      const badge = document.createElement("span");
      badge.className = "badge-status badge-danger";
      badge.textContent = "Refused";
      output.append(badge, ` ${data.reason || "the reader gave no reason"}`);
      return;
    }

    const page = data.page;
    output.replaceChildren();
    const badge = document.createElement("span");
    badge.className = `badge-status ${page.armor_safe ? "badge-ok" : "badge-danger"}`;
    badge.textContent = page.armor_safe ? "Model Armor: clean" : "Model Armor: flagged";
    badge.title = page.armor_safe
      ? "No injection pattern found in the fetched text"
      : `Patterns found: ${(page.armor_patterns || []).join(", ")}`;

    const summary = document.createElement("span");
    summary.textContent =
      ` ${page.title || page.url} / ${page.characters} characters` +
      (page.redirects && page.redirects.length ? ` / ${page.redirects.length} redirect(s)` : "") +
      (page.text_truncated ? " / truncated" : "");

    const insert = document.createElement("button");
    insert.className = "btn btn-sm";
    insert.style.marginLeft = "var(--s-2)";
    insert.textContent = "Insert into message";
    insert.onclick = () => {
      const composer = document.getElementById("chat-input");
      if (!composer) return;
      const header = `Source: ${page.url}\n\n`;
      composer.value = `${composer.value}${composer.value ? "\n\n" : ""}${header}${page.text}`;
      composer.focus();
    };

    output.append(badge, summary, insert);
  } catch (err) {
    output.textContent = err.message;
  }
}

async function sendChat() {
  const input = document.getElementById("chat-input");
  const message = (input.value || "").trim();
  if (!message) {
    setChatError("Write a message before sending.");
    return;
  }

  const sendButton = document.getElementById("chat-send");
  const transcript = document.getElementById("chat-transcript");
  setChatError("");
  sendButton.disabled = true;

  clearChatPlaceholder();
  transcript.appendChild(renderTurn({ role: "user", content: message }));
  const isRace = state.chatMode === "race";
  transcript.appendChild(pendingTurn(isRace ? "Running the lanes" : "Routing through the gateway"));
  transcript.scrollTop = transcript.scrollHeight;
  input.value = "";

  try {
    const payload = collectComposer();
    payload.message = message;

    let response;
    if (isRace) {
      payload.models = Array.from(document.querySelectorAll(".race-model:checked")).map(el => el.value);
      payload.judge = document.getElementById("race-judge").checked;
      if (payload.models.length < 2) {
        throw new Error("Pick at least two models for a race.");
      }
      response = await fetch("/api/chat/race", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    } else {
      payload.model = document.getElementById("chat-model").value;
      response = await fetch("/api/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    }

    const data = await response.json();
    document.getElementById("pending-turn")?.remove();

    if (!response.ok) {
      throw new Error(data.detail || data.error || "The request was refused.");
    }

    state.sessionId = data.session_id;
    if (isRace) {
      transcript.appendChild(renderRace(data.race));
    } else {
      transcript.appendChild(renderTurn(data.message));
      if (data.title) document.getElementById("chat-title").textContent = data.title;
    }
    transcript.scrollTop = transcript.scrollHeight;
    loadSessions();
  } catch (err) {
    document.getElementById("pending-turn")?.remove();
    setChatError(err.message);
  } finally {
    sendButton.disabled = false;
  }
}

function exportSession(format) {
  if (!state.sessionId) {
    setChatError("Send a message first: there is nothing to export yet.");
    switchTab("tab-chat");
    return;
  }
  window.location.href = `/api/chat/sessions/${state.sessionId}/export?format=${format}`;
}

// ---------------------------------------------------------------------------
// OmniLedger showcase
// ---------------------------------------------------------------------------

function setProcessStatus(text, badgeClass) {
  const statusDiv = document.getElementById("process-status");
  if (!statusDiv) return;
  statusDiv.replaceChildren();
  const badge = document.createElement("span");
  badge.className = `badge-status ${badgeClass}`;
  badge.textContent = text;
  statusDiv.appendChild(badge);
}

// One entry per backend the extractor can declare. A two-way "live or demo" split would stamp
// the local text-layer path green as if a model had read the document, which is the opposite of
// what that mode says about itself.
const EXTRACTION_MODE_BADGES = {
  "gemini-3.5": {
    cls: "badge-ok",
    label: "gemini-3.5",
    title: "Last extraction produced by a live Gemini 3.5 vision call",
  },
  "local-text-layer": {
    cls: "badge-purple",
    label: "Local text layer",
    title:
      "Last extraction read the document's own text layer locally: real values, no model call, " +
      "no line items. See the extraction notes for what could not be found.",
  },
  "deterministic-demo": {
    cls: "badge-warn",
    label: "Demo mode",
    title: "Last extraction served fixed demo data (no live model call, no uploaded document)",
  },
};

function updateExtractionModeBadge(mode) {
  const badge = document.getElementById("extraction-mode-badge");
  if (!badge || !mode) return;
  const entry = EXTRACTION_MODE_BADGES[mode] || {
    cls: "badge-warn",
    label: mode,
    title: `Last extraction reported an unknown backend: ${mode}`,
  };
  badge.className = `badge-status ${entry.cls}`;
  badge.textContent = entry.label;
  badge.title = entry.title;
}

// ---------------------------------------------------------------------------
// Bands. A console action often finishes in about a second and then reloads the page, so
// without this the surface looked untouched and the operator could not tell what had been
// decided or where the consequence landed. Nothing new is persisted server-side: the outcome is
// built from the response already returned and handed across the reload in sessionStorage.
//
// Two bands use this: the overview's scenario band and the fleet band that reports a dispatched
// or refused run. A band jumps either to another tab or to a section of the current one.
// ---------------------------------------------------------------------------

const BAND_KEY_PREFIX = "sentinel_band:";
const BAND_SLOTS = ["scenario-band", "fleet-band"];

const SCENARIO_STAGES = "guardrail scan, gateway, extraction, § 14 UStG audit";

function showScenarioRunning(label) {
  const band = document.getElementById("scenario-band");
  if (!band) return;
  band.className = "scenario-band is-running";
  band.style.display = "flex";
  band.replaceChildren();

  const spinner = document.createElement("span");
  spinner.className = "spinner";

  const text = document.createElement("div");
  const head = document.createElement("b");
  head.textContent = `Running ${label}`;
  const detail = document.createElement("span");
  detail.textContent = ` ${SCENARIO_STAGES}, then a booking or a correction letter.`;
  text.append(head, detail);

  band.append(spinner, text);
}

function arrowIcon() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icon");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", "#i-arrow-right");
  svg.appendChild(use);
  return svg;
}

function renderBand(elementId, result) {
  const band = document.getElementById(elementId);
  if (!band || !result) return;
  band.className = `scenario-band tone-${result.tone || "ok"}`;
  band.style.display = "flex";
  band.replaceChildren();

  const mark = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  mark.setAttribute("class", "icon");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", result.tone === "danger" ? "#i-alert" : "#i-check");
  mark.appendChild(use);

  const text = document.createElement("div");
  const head = document.createElement("b");
  head.textContent = result.headline;
  const detail = document.createElement("span");
  detail.textContent = ` ${result.detail}`;
  text.append(head, detail);

  band.append(mark, text);

  if (result.tab) {
    const jump = document.createElement("button");
    jump.className = "btn btn-sm";
    jump.onclick = () => switchTab(result.tab);
    const label = document.createElement("span");
    label.textContent = result.tabLabel;
    jump.append(label, arrowIcon());
    band.appendChild(jump);
  } else if (result.section) {
    const jump = document.createElement("button");
    jump.className = "btn btn-sm";
    jump.onclick = () => jumpToSection(result.section);
    const label = document.createElement("span");
    label.textContent = result.sectionLabel;
    jump.append(label, arrowIcon());
    band.appendChild(jump);
  }
}

// Read once and clear: a band reports the action the operator just took, not every one since.
function restoreBands() {
  BAND_SLOTS.forEach(slot => {
    let stored = null;
    try {
      stored = sessionStorage.getItem(BAND_KEY_PREFIX + slot);
      sessionStorage.removeItem(BAND_KEY_PREFIX + slot);
    } catch (err) {
      return;
    }
    if (!stored) return;
    try {
      renderBand(slot, JSON.parse(stored));
    } catch (err) {
      // A malformed entry is not worth an error state; the run itself is in the gate ledger.
    }
  });
}

function rememberBand(slot, result) {
  try {
    sessionStorage.setItem(BAND_KEY_PREFIX + slot, JSON.stringify(result));
  } catch (err) {
    // Private-mode storage refusals must not swallow the run.
  }
}

function summariseScenario(data, label) {
  const invoice = data.invoice || {};
  const number = invoice.invoice_number || label;
  const violations = invoice.compliance_violations || [];

  if (invoice.status === "booked") {
    return {
      tone: "ok",
      headline: `Invoice ${number} processed and booked.`,
      detail: "No § 14 UStG defect, so the reconciler wrote it straight into the ledger store.",
      tab: "tab-telemetry",
      tabLabel: "See every call in Telemetry"
    };
  }

  return {
    tone: "warn",
    headline: `Invoice ${number} processed, § 14 UStG defect found.`,
    detail: violations.length
      ? `${violations.join(", ")}. The correction letter is drafted and waiting for your approval.`
      : "The correction letter is drafted and waiting for your approval.",
    tab: "tab-tickets",
    tabLabel: "Open Approvals"
  };
}

async function dispatchInvoiceProcessing(formData, label) {
  setProcessStatus(`Dispatching ${label}`, "badge-warn");
  showScenarioRunning(label);

  try {
    const res = await fetch("/api/omniledger/process", { method: "POST", body: formData });
    const data = await res.json();
    if (res.ok) {
      updateExtractionModeBadge(data.extraction_mode);
      setProcessStatus(`${data.invoice.status} / ${data.extraction_mode}`, "badge-ok");
      rememberBand("scenario-band", summariseScenario(data, label));
      setTimeout(() => location.reload(), 1200);
    } else {
      setProcessStatus(data.reason || "Blocked by Model Armor", "badge-danger");
      rememberBand("scenario-band", {
        tone: "danger",
        headline: `${label} stopped before extraction.`,
        detail: `${data.reason || "Model Armor refused the document"}. The agent that touched it `
          + `is quarantined until you release it.`,
        tab: "tab-fleet",
        tabLabel: "Open Fleet"
      });
      setTimeout(() => location.reload(), 1800);
    }
  } catch (err) {
    setProcessStatus(err.message, "badge-danger");
    renderBand("scenario-band", {
      tone: "danger",
      headline: "The run did not reach the fleet.",
      detail: err.message,
      tab: "",
      tabLabel: ""
    });
  }
}

async function processInvoicePreset(presetType) {
  const formData = new FormData();
  formData.append("preset_type", presetType);
  await dispatchInvoiceProcessing(formData, presetType);
}

async function processInvoiceUpload() {
  const input = document.getElementById("invoice-upload");
  if (!input || !input.files || input.files.length === 0) {
    setProcessStatus("Choose a document first", "badge-warn");
    return;
  }
  const formData = new FormData();
  formData.append("file", input.files[0]);
  formData.append("preset_type", "upload");
  await dispatchInvoiceProcessing(formData, input.files[0].name);
}

// ---------------------------------------------------------------------------
// Approvals, quarantine and the registry forms
// ---------------------------------------------------------------------------

async function postAndReload(url, options, failure) {
  try {
    const res = await fetch(url, options);
    if (res.ok) {
      location.reload();
      return;
    }
    const data = await res.json().catch(() => ({}));
    showToast(data.detail || data.error || failure);
  } catch (err) {
    showToast(`${failure}: ${err.message}`);
  }
}

const approveTicket = id => postAndReload(`/api/tickets/${id}/approve`, { method: "POST" }, "Could not approve the ticket");
const rejectTicket = id => postAndReload(`/api/tickets/${id}/reject`, { method: "POST" }, "Could not reject the ticket");
const releaseQuarantine = id => postAndReload(`/api/agents/${id}/quarantine/release`, { method: "POST" }, "Could not release the agent");

function optOutContact(contactId) {
  if (!confirm("Opt this contact out and leave a tombstone that blocks future contact?")) return;
  postAndReload(`/api/contacts/${contactId}/opt-out`, { method: "POST" }, "Could not record the opt-out");
}

function submitForm(event, url, failure) {
  event.preventDefault();
  postAndReload(url, { method: "POST", body: new FormData(event.target) }, failure);
}

const submitNewTicket = e => submitForm(e, "/api/tickets/create", "Could not create the ticket");
const submitNewTask = e => submitForm(e, "/api/tasks/create", "Could not queue the task");
const submitNewMemory = e => submitForm(e, "/api/memory/create", "Could not store the entry");

// ---------------------------------------------------------------------------
// Memory entries are correctable. They were not, and the live test read that as the same
// powerlessness the overview cards caused: "if CEO is filed under the wrong category, there is
// nothing I can do". The key stays fixed because it is what agents retrieve by; everything else
// is editable, seeded entries included - with the consequence stated rather than hidden.
// ---------------------------------------------------------------------------

function openMemoryEditor(key, category, content, isSeed) {
  document.getElementById("memory-edit-key").value = key;
  document.getElementById("memory-edit-category").value = category;
  document.getElementById("memory-edit-content").value = content;
  const note = document.getElementById("memory-edit-seed-note");
  if (note) note.style.display = isSeed ? "block" : "none";
  toggleModal("modal-memory-edit");
}

function submitMemoryEdit(event) {
  event.preventDefault();
  const key = document.getElementById("memory-edit-key").value;
  postAndReload(
    `/api/memory/${encodeURIComponent(key)}`,
    {
      method: "PUT",
      body: new URLSearchParams({
        category: document.getElementById("memory-edit-category").value,
        content: document.getElementById("memory-edit-content").value
      })
    },
    "Could not save the entry"
  );
}

function deleteMemoryEntry(key, isSeed) {
  const warning = isSeed
    ? `Delete "${key}"?\n\nThis entry shipped with the demo, so it is recreated the next time `
      + "the app starts - that key belongs to the seed. Edit it instead if you want your version "
      + "to stand."
    : `Delete "${key}"? Agents will stop retrieving it.`;
  if (!confirm(warning)) return;
  postAndReload(
    `/api/memory/${encodeURIComponent(key)}`,
    { method: "DELETE" },
    "Could not delete the entry"
  );
}
const submitNewContact = e => submitForm(e, "/api/contacts/create", "Could not save the contact");
const submitNewSkill = e => submitForm(e, "/api/skills/create", "Could not create the skill");
const submitNewPrompt = e => submitForm(e, "/api/prompts/create", "Could not create the prompt");

// ---------------------------------------------------------------------------
// Deleting a prompt, a version or a skill. The server refuses while a task template or a
// recorded conversation still points at it and answers 409 naming every user; that message is
// what the operator needs to see, so it is shown rather than replaced by a generic failure.
// ---------------------------------------------------------------------------

async function deleteComponent(url, confirmation, failure) {
  if (!confirm(confirmation)) return;
  try {
    const res = await fetch(url, { method: "DELETE" });
    if (res.ok) {
      location.reload();
      return;
    }
    const data = await res.json().catch(() => ({}));
    showToast(data.error || data.detail || failure);
  } catch (err) {
    showToast(err.message || failure);
  }
}

function deletePrompt(promptId, title) {
  deleteComponent(
    `/api/prompts/${encodeURIComponent(promptId)}`,
    `Delete the prompt "${title}" and every one of its versions?`,
    "Could not delete the prompt"
  );
}

function deletePromptVersion(promptId, selectId) {
  const select = document.getElementById(selectId);
  if (!select) return;
  // The copy picker's options carry the version text as their value, so the number comes from
  // the label - the same place the operator read it.
  const label = select.options[select.selectedIndex].textContent.trim();
  const version = label.split(" ")[0].replace(/^v/, "");
  deleteComponent(
    `/api/prompts/${encodeURIComponent(promptId)}/versions/${encodeURIComponent(version)}`,
    `Delete version ${version}? The prompt keeps its other versions.`,
    "Could not delete the version"
  );
}

function deleteSkill(skillId, name) {
  deleteComponent(
    `/api/skills/${encodeURIComponent(skillId)}`,
    `Delete the skill "${name}"?\n\nA skill that ships as a SKILL.md file on disk returns the `
      + "next time the registry reloads - that file is where it comes from.",
    "Could not delete the skill"
  );
}

function openPromptVersionModal(promptId, title, currentText) {
  document.getElementById("pv-prompt-id").value = promptId;
  document.getElementById("pv-title").textContent = title;
  document.getElementById("pv-text").value = currentText;
  toggleModal("modal-prompt-version");
}

function submitPromptVersion(event) {
  event.preventDefault();
  const promptId = document.getElementById("pv-prompt-id").value;
  postAndReload(
    `/api/prompts/${promptId}/version`,
    { method: "POST", body: new FormData(event.target) },
    "Could not save the version"
  );
}

function openPromptPermsModal(promptId, title, visibility, reqApproval) {
  document.getElementById("pp-prompt-id").value = promptId;
  document.getElementById("pp-title").textContent = title;
  document.getElementById("pp-visibility").value = visibility;
  document.getElementById("pp-approval").checked = (reqApproval === "true" || reqApproval === true);
  toggleModal("modal-prompt-perms");
}

function submitPromptPerms(event) {
  event.preventDefault();
  const promptId = document.getElementById("pp-prompt-id").value;
  postAndReload(
    `/api/prompts/${promptId}/permissions`,
    { method: "POST", body: new FormData(event.target) },
    "Could not update the permissions"
  );
}

function openSkillVersionModal(skillId, name, tools) {
  document.getElementById("sv-skill-id").value = skillId;
  document.getElementById("sv-name").textContent = name;
  document.getElementById("sv-tools").value = tools;
  toggleModal("modal-skill-version");
}

function submitSkillVersion(event) {
  event.preventDefault();
  const skillId = document.getElementById("sv-skill-id").value;
  postAndReload(
    `/api/skills/${skillId}/version`,
    { method: "POST", body: new FormData(event.target) },
    "Could not save the skill version"
  );
}

// ---------------------------------------------------------------------------
// Task templates: the "everything is a task" foundation, plus the routine and schedule
// bindings that make one recurring or dated. A template never becomes a different kind of
// object - see the "Tasks & Routines" concept doc, section A.1.
// ---------------------------------------------------------------------------

function submitFormWithMethod(event, url, method, failure) {
  event.preventDefault();
  postAndReload(url, { method, body: new FormData(event.target) }, failure);
}

function onTemplatePromptSourceChange() {
  const isLibrary = document.getElementById("ntt-prompt-source").value === "library";
  document.getElementById("ntt-custom-group").style.display = isLibrary ? "none" : "block";
  document.getElementById("ntt-library-group").style.display = isLibrary ? "block" : "none";
}

function onTemplateLibraryPromptChange() {
  const promptId = document.getElementById("ntt-prompt-id").value;
  const versionSelect = document.getElementById("ntt-prompt-version");
  versionSelect.replaceChildren();

  const prompt = state.prompts.find(p => p.id === promptId);
  if (!prompt) {
    versionSelect.disabled = true;
    versionSelect.appendChild(new Option("Pick a template first", ""));
    return;
  }

  versionSelect.disabled = false;
  prompt.versions.forEach(version => {
    const option = new Option(`v${version.version_number}`, version.version_number);
    option.selected = version.version_number === prompt.active_version;
    versionSelect.appendChild(option);
  });
  updateComposerSetupSummary();
}

function submitNewTaskTemplate(event) {
  const ids = Array.from(document.querySelectorAll(".ntt-skill-box:checked")).map(box => box.value);
  document.getElementById("ntt-skill-ids").value = ids.join(",");
  submitFormWithMethod(event, "/api/task-templates", "POST", "Could not create the task template");
}

// A run the gateway refuses answers 403 and used to leave only a toast, so an operator whose
// task was stopped by Model Armor had no idea the agent was now locked, let alone where to
// unlock it. The band says both and carries the jump.
async function enqueueTaskTemplate(templateId) {
  try {
    const res = await fetch(`/api/task-templates/${templateId}/enqueue`, { method: "POST" });
    if (res.ok) {
      rememberBand("fleet-band", {
        tone: "ok",
        headline: "Run dispatched.",
        detail: "It is in the task queue above with its state and its evidence."
      });
      location.reload();
      return;
    }

    const data = await res.json().catch(() => ({}));
    const blocked = res.status === 403;
    rememberBand("fleet-band", {
      tone: blocked ? "danger" : "warn",
      headline: blocked ? "The gateway refused this run." : "The run could not be dispatched.",
      detail: blocked
        ? `${data.error || "The agent is locked."} The run is recorded as failed, not left `
          + "hanging - release the agent in the Fleet directory, then run it again from the queue."
        : (data.error || data.detail || "No reason was returned."),
      section: blocked ? "fleet-directory" : "",
      sectionLabel: blocked ? "Go to the Fleet directory" : ""
    });
    location.reload();
  } catch (err) {
    showToast(err.message || "Could not enqueue the template");
  }
}

// Releasing an agent deliberately does not re-dispatch what its quarantine stopped; this is
// how the operator gives that decision after the fact.
function runTemplateAgain(templateId) {
  enqueueTaskTemplate(templateId);
}

// ---------------------------------------------------------------------------
// Intervening in the queue. The live test ended up with two identical tasks after a quarantine
// hang and had no way to touch either of them. Cancelling settles a task that has not run;
// removing clears a settled record. There is no pause: a run in flight is synchronous and over
// in seconds, so a pause button would offer control that does not exist.
// ---------------------------------------------------------------------------

function cancelTask(taskId, name) {
  if (!confirm(`Cancel "${name}"?

It stays in the queue as cancelled - the record and its `
      + "history remain, only its outcome changes.")) return;
  postAndReload(
    `/api/tasks/${encodeURIComponent(taskId)}/cancel`,
    { method: "POST", body: new URLSearchParams({ reason: "Cancelled by the operator" }) },
    "Could not cancel the task"
  );
}

function deleteTask(taskId, name) {
  deleteComponent(
    `/api/tasks/${encodeURIComponent(taskId)}`,
    `Remove the record of "${name}" from the queue?

This one does erase: the run and its `
      + "outcome are gone from the queue. The gate ledger keeps what the run actually did.",
    "Could not remove the task"
  );
}

function deleteTaskTemplate(templateId, owner) {
  if (!confirm("Delete this task template? Remove its routine and schedule bindings first if this fails.")) return;
  postAndReload(
    `/api/task-templates/${templateId}?requested_by=${encodeURIComponent(owner)}`,
    { method: "DELETE" },
    "Could not delete the template"
  );
}

function openRoutineModal(templateId, name) {
  document.getElementById("rt-template-id").value = templateId;
  document.getElementById("rt-template-name").textContent = name;
  onRoutineKindChange();
  toggleModal("modal-routine");
}

function onRoutineKindChange() {
  const kind = document.getElementById("rt-kind").value;
  document.getElementById("rt-interval-group").style.display = kind === "interval" ? "block" : "none";
  document.getElementById("rt-daily-group").style.display = kind === "daily" ? "block" : "none";
  document.getElementById("rt-cron-group").style.display = kind === "cron" ? "block" : "none";
  document.getElementById("rt-timezone-group").style.display = kind === "interval" ? "none" : "block";
}

function submitRoutineBinding(event) {
  const templateId = document.getElementById("rt-template-id").value;
  submitFormWithMethod(event, `/api/task-templates/${templateId}/routine`, "PUT", "Could not save the routine");
}

function removeRoutineBinding(templateId) {
  postAndReload(`/api/task-templates/${templateId}/routine`, { method: "DELETE" }, "Could not remove the routine");
}

function openScheduleModal(templateId, name) {
  document.getElementById("sc-template-id").value = templateId;
  document.getElementById("sc-template-name").textContent = name;
  toggleModal("modal-schedule");
}

function submitScheduleBinding(event) {
  const templateId = document.getElementById("sc-template-id").value;
  submitFormWithMethod(event, `/api/task-templates/${templateId}/schedule`, "PUT", "Could not save the schedule");
}

function removeScheduleBinding(templateId) {
  postAndReload(`/api/task-templates/${templateId}/schedule`, { method: "DELETE" }, "Could not remove the schedule");
}

// ---------------------------------------------------------------------------
// Per-viewer hide/restore (concept doc, section A.4/D Phase 2 "removed_by"). Hiding a shared
// template never touches the template itself - only this one viewer's own listing changes,
// via the `viewer` query string on `/` (see server.py's index_view docstring for why that,
// not localStorage, is the identity source here).
// ---------------------------------------------------------------------------

function hideTemplateForViewer(templateId, viewer) {
  postAndReload(
    `/api/task-templates/${templateId}/remove-for-me`,
    { method: "POST", body: new URLSearchParams({ viewer }) },
    "Could not hide the template"
  );
}

function restoreTemplateForViewer(templateId, viewer) {
  postAndReload(
    `/api/task-templates/${templateId}/restore-for-me`,
    { method: "POST", body: new URLSearchParams({ viewer }) },
    "Could not restore the template"
  );
}

// ---------------------------------------------------------------------------
// Run history ("Verlauf", concept doc section A.3/D Phase 2): every TaskRecord this template
// ever produced, not only the schedule-triggered ones the doc's Phase-2 bullet names first -
// a bare "enqueue now" and a routine-triggered run go through the identical QUEUED -> ...
// path (A.5), so excluding them would just hide real history behind an arbitrary filter. Each
// row still carries `triggered_by`, so a reader can tell manual, routine and schedule runs
// apart at a glance. Lazily loaded per template from the existing
// GET /api/task-templates/{id} - no new endpoint, no second store.
// ---------------------------------------------------------------------------

const historyLoaded = new Set();

async function toggleHistoryPanel(templateId, name) {
  const row = document.getElementById(`history-row-${templateId}`);
  if (!row) return;
  const isOpen = row.style.display !== "none";
  if (isOpen) {
    row.style.display = "none";
    return;
  }
  row.style.display = "table-row";
  if (!historyLoaded.has(templateId)) {
    await loadHistoryPanel(templateId, name);
    historyLoaded.add(templateId);
  }
}

function historyStatusBadgeClass(state) {
  if (state === "completed") return "badge-ok";
  if (state === "failed") return "badge-danger";
  if (state === "queued") return "badge-info";
  return "badge-warn";
}

function formatRunTime(epochSeconds) {
  if (!epochSeconds) return "-";
  return new Date(epochSeconds * 1000).toISOString().replace("T", " ").slice(0, 19) + " UTC";
}

function buildHistoryRun(run) {
  const card = document.createElement("div");
  card.className = "history-run";

  const head = document.createElement("div");
  head.className = "history-run-head";

  const id = document.createElement("code");
  id.textContent = run.task_id;
  head.appendChild(id);

  const status = document.createElement("span");
  status.className = `badge-status ${historyStatusBadgeClass(run.state)}`;
  status.textContent = run.state;
  head.appendChild(status);

  const trigger = document.createElement("span");
  trigger.className = "chip";
  trigger.textContent = run.triggered_by;
  head.appendChild(trigger);

  const when = document.createElement("span");
  when.className = "item-meta numeric";
  when.textContent = formatRunTime(run.created_at);
  head.appendChild(when);

  const view = document.createElement("button");
  view.type = "button";
  view.className = "btn btn-sm";
  view.textContent = "View run";
  view.onclick = () => openConsoleModal(run.task_id, run.name);
  head.appendChild(view);

  card.appendChild(head);

  const steps = run.output_data && Array.isArray(run.output_data.steps) ? run.output_data.steps : null;
  if (steps && steps.length > 0) {
    const list = document.createElement("div");
    list.className = "history-step-list";
    steps.forEach((step, index) => {
      const stepRow = document.createElement("div");
      stepRow.className = "history-step-row";
      const label = step.error
        ? `step ${index + 1} '${step.step_id}': ${step.status} - ${step.error}`
        : `step ${index + 1} '${step.step_id}': ${step.status}${step.model ? ` (model=${step.model})` : ""}`;
      stepRow.textContent = label;
      list.appendChild(stepRow);
    });
    card.appendChild(list);
  }

  return card;
}

async function loadHistoryPanel(templateId, name) {
  const container = document.getElementById(`history-content-${templateId}`);
  if (!container) return;
  container.replaceChildren();
  const loading = document.createElement("div");
  loading.className = "item-meta";
  loading.textContent = "Loading history ...";
  container.appendChild(loading);

  try {
    const res = await fetch(`/api/task-templates/${templateId}`);
    if (!res.ok) throw new Error("Template not found");
    const data = await res.json();
    const runs = data.runs || [];

    container.replaceChildren();

    const makeRoutine = document.createElement("button");
    makeRoutine.type = "button";
    makeRoutine.className = "btn btn-sm";
    makeRoutine.textContent = "Make this a routine";
    makeRoutine.style.marginBottom = "var(--s-2)";
    makeRoutine.onclick = () => openRoutineModal(templateId, name);
    container.appendChild(makeRoutine);

    if (runs.length === 0) {
      const empty = document.createElement("div");
      empty.className = "item-meta";
      empty.textContent = "No runs yet.";
      container.appendChild(empty);
      return;
    }

    runs.forEach(run => container.appendChild(buildHistoryRun(run)));
  } catch (err) {
    container.replaceChildren();
    const error = document.createElement("div");
    error.className = "item-meta";
    error.textContent = `Could not load the history: ${err.message}`;
    container.appendChild(error);
  }
}

// ---------------------------------------------------------------------------
// Step editor: add/change/remove/reorder a template's steps (concept doc, section E.4
// "Minimaler Ketten-Schnitt"). One step is an ordinary task; more than one runs as a chain.
// Every field not exposed here (skill_ids, prompt library refs, ...) is kept from the loaded
// step and carried through unmodified on save - this editor only ever touches agent, prompt
// text and execution pattern.
// ---------------------------------------------------------------------------

function openStepsModal(templateId, name, steps) {
  state.stepsEditor = {
    templateId,
    // Deep copy: editing must not mutate the row data still on screen behind the modal.
    steps: steps.map(step => JSON.parse(JSON.stringify(step)))
  };
  document.getElementById("steps-template-name").textContent = name;
  renderStepsEditor();
  toggleModal("modal-steps");
}

function renderStepsEditor() {
  const container = document.getElementById("steps-editor-list");
  container.replaceChildren();
  state.stepsEditor.steps.forEach((step, index) => container.appendChild(buildStepRow(step, index)));
}

function buildStepRow(step, index) {
  const stepCount = state.stepsEditor.steps.length;
  const row = document.createElement("div");
  row.className = "record pillar-uas";

  const top = document.createElement("div");
  top.className = "item-top";
  const title = document.createElement("span");
  title.className = "item-title";
  title.textContent = `Step ${index + 1}`;
  top.appendChild(title);

  const actions = document.createElement("div");
  actions.className = "item-actions";
  actions.style.margin = "0";

  const up = document.createElement("button");
  up.type = "button";
  up.className = "btn btn-sm";
  up.title = "Move earlier in the chain";
  up.textContent = "Move up";
  up.disabled = index === 0;
  up.onclick = () => moveStepRow(index, -1);
  actions.appendChild(up);

  const down = document.createElement("button");
  down.type = "button";
  down.className = "btn btn-sm";
  down.title = "Move later in the chain";
  down.textContent = "Move down";
  down.disabled = index === stepCount - 1;
  down.onclick = () => moveStepRow(index, 1);
  actions.appendChild(down);

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "btn btn-sm btn-reject";
  remove.textContent = "Remove";
  remove.title = stepCount <= 1 ? "A template needs at least one step" : "Remove this step";
  remove.disabled = stepCount <= 1;
  remove.onclick = () => removeStepRow(index);
  actions.appendChild(remove);

  top.appendChild(actions);
  row.appendChild(top);

  const agentGroup = document.createElement("div");
  agentGroup.className = "form-group";
  const agentLabel = document.createElement("label");
  agentLabel.textContent = "Agent";
  agentGroup.appendChild(agentLabel);
  const agentSelect = document.createElement("select");
  agentSelect.className = "select-input";
  state.agents.forEach(agent => {
    // Every identity carries an explicit tool scope, and a single-agent step is executed under
    // `execute_template` - an agent without it in scope is refused at the gateway and
    // quarantined for having tried. The choice stays open (the narrow scope is the design, and
    // the Governance tab shows the whole matrix); it is only labelled, so the operator learns it
    // here rather than from a failed run.
    const label = agent.can_execute_template === false
      ? `${agent.name} (${agent.agent_id}) — no execute_template scope`
      : `${agent.name} (${agent.agent_id})`;
    const option = new Option(label, agent.agent_id);
    option.selected = agent.agent_id === step.assigned_agent;
    agentSelect.appendChild(option);
  });
  agentGroup.appendChild(agentSelect);

  const scopeNote = document.createElement("div");
  scopeNote.className = "item-meta";
  const refreshScopeNote = () => {
    const agent = state.agents.find(a => a.agent_id === step.assigned_agent);
    // A race step never runs as this agent: chain_runner hands it to the race lanes, which carry
    // chat_completion instead. So the warning applies to single-agent steps only.
    const blocked = agent && agent.can_execute_template === false && step.execution_pattern !== "race";
    scopeNote.textContent = blocked
      ? "This agent has no execute_template scope. The gateway will refuse a single-agent step "
        + "that runs as it, and quarantine the agent. Choose an agent that carries the tool, or "
        + "run this step as a race."
      : "";
  };
  agentSelect.addEventListener("change", event => {
    step.assigned_agent = event.target.value;
    refreshScopeNote();
  });
  agentGroup.appendChild(scopeNote);
  row.appendChild(agentGroup);

  const promptGroup = document.createElement("div");
  promptGroup.className = "form-group";
  const promptLabel = document.createElement("label");
  promptLabel.textContent = "Prompt / instructions";
  promptGroup.appendChild(promptLabel);
  const promptInput = document.createElement("textarea");
  promptInput.className = "textarea-input";
  promptInput.value = step.custom_prompt_text || "";
  promptInput.addEventListener("input", event => { step.custom_prompt_text = event.target.value; });
  promptGroup.appendChild(promptInput);
  row.appendChild(promptGroup);

  const patternGroup = document.createElement("div");
  patternGroup.className = "form-group";
  const patternLabel = document.createElement("label");
  patternLabel.textContent = "Execution pattern";
  patternGroup.appendChild(patternLabel);
  const patternSelect = document.createElement("select");
  patternSelect.className = "select-input";
  patternSelect.appendChild(new Option("Single agent", "single"));
  patternSelect.appendChild(new Option(`Race (all ${state.models.length} supported models)`, "race"));
  patternSelect.value = step.execution_pattern === "race" ? "race" : "single";
  patternSelect.disabled = state.models.length < 2;
  patternSelect.addEventListener("change", event => {
    step.execution_pattern = event.target.value;
    // Switching to a race takes the step off this agent entirely, so the scope note follows.
    refreshScopeNote();
  });
  patternGroup.appendChild(patternSelect);
  if (state.models.length < 2) {
    const note = document.createElement("div");
    note.className = "item-meta";
    note.textContent = "Race needs at least two supported models - only one is configured here.";
    patternGroup.appendChild(note);
  }
  row.appendChild(patternGroup);

  // Both controls are in place now, so the note can be filled for the step as loaded.
  refreshScopeNote();
  return row;
}

function addStepRow() {
  state.stepsEditor.steps.push({ assigned_agent: "agent:task-solver", custom_prompt_text: "", execution_pattern: "single" });
  renderStepsEditor();
}

function removeStepRow(index) {
  if (state.stepsEditor.steps.length <= 1) return;
  state.stepsEditor.steps.splice(index, 1);
  renderStepsEditor();
}

function moveStepRow(index, delta) {
  const steps = state.stepsEditor.steps;
  const target = index + delta;
  if (target < 0 || target >= steps.length) return;
  [steps[index], steps[target]] = [steps[target], steps[index]];
  renderStepsEditor();
}

function submitStepsEditor() {
  const templateId = state.stepsEditor.templateId;
  const payload = state.stepsEditor.steps.map((step, index) => ({
    ...step,
    // Ids are regenerated from the final on-screen order, not kept from the loaded step - the
    // client always resubmits the whole array, position = index (concept doc, section E.4),
    // so a stable id scheme derived straight from that order is simpler than tracking renames
    // across add/remove/reorder.
    step_id: `step-${index + 1}`,
    position: index,
    // Race models are always every model this deployment supports, never hand-picked here
    // (SUPPORTED_MODELS has exactly the 2-4 race() already needs) - and explicitly cleared
    // when a step is not a race step, so switching a step away from "race" cannot leave a
    // stale race_models list that Step's own validator would then reject.
    race_models: step.execution_pattern === "race" ? state.models : []
  }));
  postAndReload(
    `/api/task-templates/${templateId}/steps`,
    { method: "PUT", body: new URLSearchParams({ steps: JSON.stringify(payload) }) },
    "Could not save the steps"
  );
}

// ---------------------------------------------------------------------------
// Task wizard: a guided walk to the same `/api/task-templates` create call the quick form
// (submitNewTaskTemplate above) already makes, plus the optional routine/schedule bindings -
// no new persistence path (concept doc, section D Phase 2 "Wizard-UI"). Always submits its one
// step through the `steps` JSON array, never the flat fields, so there is a single code path
// for "one step" whether it came from this wizard or from `openStepsModal` later.
//
// `add_prompt_version()`/`add_skill_version()` wiring (D Phase 2 "Versions-Verdrahtung"): the
// wizard calls the same `/api/prompts/{id}/version` and `/api/skills/{id}/version` endpoints
// the Prompts/Skills tabs already use - never a second copy of that versioning logic.
// ---------------------------------------------------------------------------

const WIZARD_STEP_COUNT = 6;

function defaultWizardState() {
  return {
    step: 0,
    name: "", owner: "operator", group: "", visibility: "own", requiresApproval: false,
    promptMode: "custom",
    customPromptText: "",
    promptId: "", promptVersion: "", promptOriginalText: "",
    promptForkText: "", promptForkVersion: "", promptForkSummary: "Forked from the task wizard",
    skillIds: new Set(),
    skillForks: [],
    agentId: "agent:task-solver",
    pattern: "single",
    bindRoutine: false,
    routine: { kind: "interval", intervalSeconds: 3600, dailyTime: "04:00", cron: "", timezone: "UTC", missPolicy: "skip" },
    bindSchedule: false,
    schedule: { dueAt: "", missPolicy: "skip" }
  };
}

function openWizard(prefill) {
  state.wizard = Object.assign(defaultWizardState(), prefill || {});
  document.getElementById("wz-name").value = state.wizard.name;
  document.getElementById("wz-owner").value = state.wizard.owner;
  document.getElementById("wz-group").value = state.wizard.group;
  document.getElementById("wz-visibility").value = state.wizard.visibility;
  document.getElementById("wz-requires-approval").checked = state.wizard.requiresApproval;
  document.getElementById("wz-prompt-source").value = state.wizard.promptMode;
  document.getElementById("wz-custom-prompt").value = state.wizard.customPromptText;
  document.querySelectorAll(".wz-skill-box").forEach(box => { box.checked = state.wizard.skillIds.has(box.value); });
  onWizardPromptSourceChange();
  renderWizardSkillForks();
  onWizardPatternChange();
  onWizardBindingToggle();
  goToWizardStep(0);
  toggleModal("modal-wizard");
}

function openWizardFromChat() {
  const promptId = document.getElementById("chat-prompt")?.value || "";
  const promptText = document.getElementById("chat-input")?.value || "";
  const prefill = {
    skillIds: new Set(state.selectedSkills),
    agentId: "agent:task-solver"
  };
  if (promptId) {
    const versionSelect = document.getElementById("chat-prompt-version");
    prefill.promptMode = "library";
    prefill.promptId = promptId;
    prefill.promptVersion = versionSelect && !versionSelect.disabled ? versionSelect.value : "";
    if (promptText) {
      // The chat message is not the library text itself, so it cannot silently overwrite a
      // shared prompt version - it is carried over as the task's own custom instructions
      // alongside the picked prompt/skills, not folded into a prompt fork.
      prefill.customPromptText = promptText;
    }
  } else {
    prefill.promptMode = "custom";
    prefill.customPromptText = promptText;
  }
  openWizard(prefill);
}

function closeWizard() {
  toggleModal("modal-wizard");
  state.wizard = null;
}

function goToWizardStep(step) {
  state.wizard.step = step;
  document.querySelectorAll(".wizard-pane").forEach((pane, index) => pane.classList.toggle("is-active", index === step));
  document.querySelectorAll(".wizard-step-dot").forEach(dot => {
    const dotStep = Number(dot.getAttribute("data-wizard-step"));
    dot.classList.toggle("is-active", dotStep === step);
    dot.classList.toggle("is-done", dotStep < step);
  });
  document.getElementById("wz-back-btn").style.display = step === 0 ? "none" : "inline-flex";
  document.getElementById("wz-next-btn").style.display = step === WIZARD_STEP_COUNT - 1 ? "none" : "inline-flex";
  document.getElementById("wz-create-btn").style.display = step === WIZARD_STEP_COUNT - 1 ? "inline-flex" : "none";
  if (step === WIZARD_STEP_COUNT - 1) renderWizardSummary();
}

function collectWizardStep(step) {
  const w = state.wizard;
  if (step === 0) {
    w.name = document.getElementById("wz-name").value.trim();
    w.owner = document.getElementById("wz-owner").value.trim() || "operator";
    w.group = document.getElementById("wz-group").value.trim();
    w.visibility = document.getElementById("wz-visibility").value;
    w.requiresApproval = document.getElementById("wz-requires-approval").checked;
  } else if (step === 1) {
    w.promptMode = document.getElementById("wz-prompt-source").value;
    w.customPromptText = document.getElementById("wz-custom-prompt").value;
    w.promptId = document.getElementById("wz-prompt-id").value;
    w.promptVersion = document.getElementById("wz-prompt-version").value;
    w.promptForkText = document.getElementById("wz-prompt-fork-text").value;
    w.promptForkVersion = document.getElementById("wz-prompt-fork-version").value.trim();
    w.promptForkSummary = document.getElementById("wz-prompt-fork-summary").value.trim();
  } else if (step === 2) {
    w.skillIds = new Set(Array.from(document.querySelectorAll(".wz-skill-box:checked")).map(box => box.value));
  } else if (step === 3) {
    w.agentId = document.getElementById("wz-agent").value;
    w.pattern = document.getElementById("wz-pattern").value;
  } else if (step === 4) {
    w.bindRoutine = document.getElementById("wz-bind-routine").checked;
    w.routine = {
      kind: document.getElementById("wz-routine-kind").value,
      intervalSeconds: document.getElementById("wz-routine-interval").value,
      dailyTime: document.getElementById("wz-routine-daily-time").value,
      cron: document.getElementById("wz-routine-cron").value,
      timezone: document.getElementById("wz-routine-timezone").value || "UTC",
      missPolicy: document.getElementById("wz-routine-miss-policy").value
    };
    w.bindSchedule = document.getElementById("wz-bind-schedule").checked;
    w.schedule = {
      dueAt: document.getElementById("wz-schedule-due-at").value,
      missPolicy: document.getElementById("wz-schedule-miss-policy").value
    };
  }
}

function wizardNext() {
  collectWizardStep(state.wizard.step);
  if (state.wizard.step === 0 && !state.wizard.name) {
    showToast("Give the task a name first.");
    return;
  }
  if (state.wizard.step < WIZARD_STEP_COUNT - 1) goToWizardStep(state.wizard.step + 1);
}

function wizardBack() {
  collectWizardStep(state.wizard.step);
  if (state.wizard.step > 0) goToWizardStep(state.wizard.step - 1);
}

function onWizardPromptSourceChange() {
  const isLibrary = document.getElementById("wz-prompt-source").value === "library";
  document.getElementById("wz-custom-group").style.display = isLibrary ? "none" : "block";
  document.getElementById("wz-library-group").style.display = isLibrary ? "block" : "none";
  if (isLibrary && state.wizard.promptId) {
    document.getElementById("wz-prompt-id").value = state.wizard.promptId;
    onWizardLibraryPromptChange();
  }
}

function onWizardLibraryPromptChange() {
  const promptId = document.getElementById("wz-prompt-id").value;
  const versionSelect = document.getElementById("wz-prompt-version");
  versionSelect.replaceChildren();

  const prompt = state.prompts.find(p => p.id === promptId);
  if (!prompt) {
    versionSelect.disabled = true;
    versionSelect.appendChild(new Option("Pick a template first", ""));
    document.getElementById("wz-prompt-fork-text").value = "";
    return;
  }

  versionSelect.disabled = false;
  prompt.versions.forEach(version => {
    const option = new Option(`v${version.version_number}`, version.version_number);
    option.selected = state.wizard.promptVersion
      ? version.version_number === state.wizard.promptVersion
      : version.version_number === prompt.active_version;
    versionSelect.appendChild(option);
  });
  onWizardPromptVersionChange();
}

function onWizardPromptVersionChange() {
  const promptId = document.getElementById("wz-prompt-id").value;
  const versionNumber = document.getElementById("wz-prompt-version").value;
  const prompt = state.prompts.find(p => p.id === promptId);
  const version = prompt ? prompt.versions.find(v => v.version_number === versionNumber) : null;
  const text = version ? version.text : (prompt ? prompt.current_text : "");
  state.wizard.promptOriginalText = text;
  document.getElementById("wz-prompt-fork-text").value = text;
  onWizardPromptForkTextChange();
}

function onWizardPromptForkTextChange() {
  const changed = document.getElementById("wz-prompt-fork-text").value !== state.wizard.promptOriginalText;
  document.getElementById("wz-prompt-fork-fields").style.display = changed ? "block" : "none";
}

function onWizardPatternChange() {
  const isRace = document.getElementById("wz-pattern").value === "race";
  document.getElementById("wz-pattern-note").style.display = isRace ? "block" : "none";
}

function onWizardBindingToggle() {
  document.getElementById("wz-routine-fields").style.display = document.getElementById("wz-bind-routine").checked ? "block" : "none";
  document.getElementById("wz-schedule-fields").style.display = document.getElementById("wz-bind-schedule").checked ? "block" : "none";
}

function onWizardRoutineKindChange() {
  const kind = document.getElementById("wz-routine-kind").value;
  document.getElementById("wz-routine-interval-group").style.display = kind === "interval" ? "block" : "none";
  document.getElementById("wz-routine-daily-group").style.display = kind === "daily" ? "block" : "none";
  document.getElementById("wz-routine-cron-group").style.display = kind === "cron" ? "block" : "none";
  document.getElementById("wz-routine-timezone-group").style.display = kind === "interval" ? "none" : "block";
}

// Fork-before-attach staging list (D Phase 2 "add_skill_version() im Wizard-Flow"). Mirrors the
// step editor's own add/remove-row idiom (addStepRow/removeStepRow) rather than inventing a
// second array-builder pattern.

function addWizardSkillFork() {
  state.wizard.skillForks.push({ skill_id: state.skills[0] ? state.skills[0].skill_id : "", new_version_number: "", change_summary: "", required_tools: "" });
  renderWizardSkillForks();
}

function removeWizardSkillFork(index) {
  state.wizard.skillForks.splice(index, 1);
  renderWizardSkillForks();
}

function renderWizardSkillForks() {
  const container = document.getElementById("wz-skill-forks");
  container.replaceChildren();
  state.wizard.skillForks.forEach((fork, index) => container.appendChild(buildWizardSkillForkRow(fork, index)));
}

function buildWizardSkillForkRow(fork, index) {
  const row = document.createElement("div");
  row.className = "wizard-fork-row";

  const skillGroup = document.createElement("div");
  skillGroup.className = "form-group";
  const skillLabel = document.createElement("label");
  skillLabel.textContent = "Skill to fork";
  skillGroup.appendChild(skillLabel);
  const skillSelect = document.createElement("select");
  skillSelect.className = "select-input";
  state.skills.forEach(skill => {
    const option = new Option(`${skill.name} (v${skill.version})`, skill.skill_id);
    option.selected = skill.skill_id === fork.skill_id;
    skillSelect.appendChild(option);
  });
  skillSelect.addEventListener("change", event => { fork.skill_id = event.target.value; });
  skillGroup.appendChild(skillSelect);
  row.appendChild(skillGroup);

  const versionGroup = document.createElement("div");
  versionGroup.className = "form-group";
  const versionLabel = document.createElement("label");
  versionLabel.textContent = "New version number";
  versionGroup.appendChild(versionLabel);
  const versionInput = document.createElement("input");
  versionInput.className = "text-input";
  versionInput.placeholder = "1.1.0";
  versionInput.value = fork.new_version_number;
  versionInput.addEventListener("input", event => { fork.new_version_number = event.target.value; });
  versionGroup.appendChild(versionInput);
  row.appendChild(versionGroup);

  const summaryGroup = document.createElement("div");
  summaryGroup.className = "form-group";
  const summaryLabel = document.createElement("label");
  summaryLabel.textContent = "What changed";
  summaryGroup.appendChild(summaryLabel);
  const summaryInput = document.createElement("input");
  summaryInput.className = "text-input";
  summaryInput.value = fork.change_summary;
  summaryInput.addEventListener("input", event => { fork.change_summary = event.target.value; });
  summaryGroup.appendChild(summaryInput);
  row.appendChild(summaryGroup);

  const toolsGroup = document.createElement("div");
  toolsGroup.className = "form-group";
  const toolsLabel = document.createElement("label");
  toolsLabel.textContent = "Required tools (comma separated)";
  toolsGroup.appendChild(toolsLabel);
  const toolsInput = document.createElement("input");
  toolsInput.className = "text-input";
  toolsInput.value = fork.required_tools;
  toolsInput.addEventListener("input", event => { fork.required_tools = event.target.value; });
  toolsGroup.appendChild(toolsInput);
  row.appendChild(toolsGroup);

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "btn btn-sm btn-reject";
  remove.textContent = "Remove this fork";
  remove.onclick = () => removeWizardSkillFork(index);
  row.appendChild(remove);

  return row;
}

function wizardSummaryRow(dl, term, value) {
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = value;
  dl.append(dt, dd);
}

function renderWizardSummary() {
  const w = state.wizard;
  const dl = document.getElementById("wz-summary");
  dl.replaceChildren();
  wizardSummaryRow(dl, "Name", w.name || "(not set)");
  wizardSummaryRow(dl, "Owner / group", `${w.owner}${w.group ? ` / ${w.group}` : ""}`);
  wizardSummaryRow(dl, "Visibility", w.visibility + (w.requiresApproval ? ", requires approval" : ""));
  wizardSummaryRow(
    dl, "Prompt",
    w.promptMode === "library"
      ? `library (${w.promptId || "none"}), forked=${w.promptForkText !== w.promptOriginalText}`
      : `custom (${(w.customPromptText || "").length} chars)`
  );
  wizardSummaryRow(dl, "Skills", w.skillIds.size ? Array.from(w.skillIds).join(", ") : "none");
  if (w.skillForks.length > 0) {
    wizardSummaryRow(dl, "Skill forks", w.skillForks.map(f => `${f.skill_id} -> v${f.new_version_number || "?"}`).join(", "));
  }
  wizardSummaryRow(dl, "Agent / pattern", `${w.agentId} / ${w.pattern}`);
  wizardSummaryRow(
    dl, "When it runs",
    [w.bindRoutine ? `recurring (${w.routine.kind})` : null, w.bindSchedule ? `once, at ${w.schedule.dueAt || "no date set"}` : null]
      .filter(Boolean).join(", ") || "only when you start it"
  );
}

function wizardRoutineForm(routine) {
  return new URLSearchParams({
    kind: routine.kind,
    interval_seconds: routine.intervalSeconds,
    daily_time: routine.dailyTime,
    cron_expression: routine.cron,
    timezone_name: routine.timezone,
    miss_policy: routine.missPolicy,
    enabled: "true"
  });
}

function wizardScheduleForm(schedule) {
  return new URLSearchParams({ due_at: schedule.dueAt, has_time: "true", miss_policy: schedule.missPolicy });
}

async function submitWizard() {
  collectWizardStep(state.wizard.step);
  const w = state.wizard;
  if (!w.name) {
    showToast("Give the task a name first.");
    goToWizardStep(0);
    return;
  }
  if (w.bindSchedule && !w.schedule.dueAt) {
    showToast("Pick a due date for the schedule binding, or turn it off.");
    goToWizardStep(4);
    return;
  }

  // Stage 1/2: version forks (add_skill_version / add_prompt_version), before anything is
  // created - a fork failure here means nothing else runs, exactly like the quick form's own
  // "Could not ..." refusals elsewhere on this page.
  let promptVersion = w.promptMode === "library" ? w.promptVersion : "";
  try {
    for (const fork of w.skillForks) {
      if (!fork.skill_id || !fork.new_version_number) continue;
      const res = await fetch(`/api/skills/${fork.skill_id}/version`, {
        method: "POST",
        body: new URLSearchParams({
          new_version_number: fork.new_version_number,
          change_summary: fork.change_summary || "Forked from the task wizard",
          required_tools: fork.required_tools
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(`Skill fork for ${fork.skill_id} failed: ${data.detail || res.statusText}`);
    }

    if (w.promptMode === "library" && w.promptId && w.promptForkText !== w.promptOriginalText) {
      if (!w.promptForkVersion) throw new Error("Give the forked prompt a new version number, or restore its original text.");
      const res = await fetch(`/api/prompts/${w.promptId}/version`, {
        method: "POST",
        body: new URLSearchParams({
          new_version_number: w.promptForkVersion,
          new_text: w.promptForkText,
          change_summary: w.promptForkSummary || "Forked from the task wizard"
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(`Prompt fork failed: ${data.detail || res.statusText}`);
      promptVersion = data.prompt.active_version;
    }
  } catch (err) {
    showToast(err.message);
    return;
  }

  // Stage 3: create the template - the one point of no return. Every failure after this one
  // is reported and the page still reloads, because the template itself now exists.
  let templateId;
  try {
    const step = {
      step_id: "step-1",
      position: 0,
      assigned_agent: w.agentId,
      skill_ids: Array.from(w.skillIds),
      prompt_source: w.promptMode,
      prompt_id: w.promptMode === "library" ? (w.promptId || null) : null,
      prompt_version: w.promptMode === "library" ? (promptVersion || null) : null,
      custom_prompt_text: w.promptMode === "custom" ? w.customPromptText : null,
      execution_pattern: w.pattern,
      race_models: w.pattern === "race" ? state.models : []
    };
    const res = await fetch("/api/task-templates", {
      method: "POST",
      body: new URLSearchParams({
        name: w.name,
        owner: w.owner,
        visibility: w.visibility,
        requires_approval: w.requiresApproval ? "true" : "false",
        group: w.group,
        steps: JSON.stringify([step])
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not create the task template");
    templateId = data.template.template_id;
  } catch (err) {
    showToast(err.message);
    return;
  }

  // Stage 4/5: bindings, best-effort - the template already exists either way.
  const bindingErrors = [];
  if (w.bindRoutine) {
    const res = await fetch(`/api/task-templates/${templateId}/routine`, { method: "PUT", body: wizardRoutineForm(w.routine) });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      bindingErrors.push(`routine binding failed: ${data.detail || res.statusText}`);
    }
  }
  if (w.bindSchedule) {
    const res = await fetch(`/api/task-templates/${templateId}/schedule`, { method: "PUT", body: wizardScheduleForm(w.schedule) });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      bindingErrors.push(`schedule binding failed: ${data.detail || res.statusText}`);
    }
  }
  if (bindingErrors.length > 0) showToast(`Task created, but ${bindingErrors.join("; ")}.`);
  location.reload();
}

// ---------------------------------------------------------------------------
// Run console: a read-only replay/live log of one run over /ws/run/{run_id} (concept doc,
// section C.7, variant (b), the web console). xterm.js is vendored (static/vendor/xterm/), never
// loaded from a CDN - version/source/license are in that directory's own header comments.
//
// Nothing this panel does ever sends anything back over the socket: `disableStdin` keeps xterm
// itself from capturing keystrokes, and the WebSocket is only ever read (`onmessage`), never
// written to - the same read-only boundary the server side of this route documents.
// ---------------------------------------------------------------------------

function ensureRunConsoleTerminal() {
  if (state.runConsole.term) return state.runConsole.term;
  const term = new Terminal({
    convertEol: true,
    disableStdin: true,
    cursorBlink: false,
    fontFamily: "'IBM Plex Mono', 'SF Mono', Consolas, monospace",
    fontSize: 13,
    theme: { background: "#0b0f14", foreground: "#e8edf2" }
  });
  term.open(document.getElementById("console-terminal"));
  state.runConsole.term = term;
  return term;
}

function openConsoleModal(taskId, name) {
  document.getElementById("console-task-name").textContent = `${name} (${taskId})`;
  const term = ensureRunConsoleTerminal();
  term.reset();
  term.writeln(`Connecting to run ${taskId} ...`);

  // Close out any previous run's socket first - opening a second console while one is still
  // live must not leave the earlier WebSocket running in the background.
  if (state.runConsole.ws) {
    state.runConsole.ws.onclose = null;
    state.runConsole.ws.close();
  }

  state.runConsole.taskId = taskId;
  const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${wsProtocol}//${location.host}/ws/run/${encodeURIComponent(taskId)}`);
  state.runConsole.ws = ws;

  ws.onopen = () => term.writeln("Connected.");
  ws.onmessage = event => term.writeln(event.data);
  ws.onclose = () => {
    term.writeln("");
    term.writeln("-- run finished, connection closed --");
  };
  ws.onerror = () => term.writeln("-- connection error --");

  toggleModal("modal-console");
}

function closeConsoleModal() {
  if (state.runConsole.ws) {
    // Detach onclose first: this is the operator dismissing the panel, not the server ending
    // the run, so the "connection closed" line in the terminal (still visible behind the
    // modal-overlay's fade, and again the next time this taskId is opened) should not claim
    // the run itself is over.
    state.runConsole.ws.onclose = null;
    state.runConsole.ws.onerror = null;
    state.runConsole.ws.close();
    state.runConsole.ws = null;
  }
  state.runConsole.taskId = null;
  toggleModal("modal-console");
}

// ---------------------------------------------------------------------------
// Blueprint circuit. Hovering a module isolates the modules it is wired to.
// ---------------------------------------------------------------------------

function showBlueprintView(view) {
  const flow = document.getElementById("blueprint-view-flow");
  const circuit = document.getElementById("blueprint-view-circuit");
  if (!flow || !circuit) return;

  const isCircuit = view === "circuit";
  flow.style.display = isCircuit ? "none" : "block";
  circuit.style.display = isCircuit ? "block" : "none";
  document.getElementById("view-btn-flow").classList.toggle("active", !isCircuit);
  document.getElementById("view-btn-circuit").classList.toggle("active", isCircuit);

  const caption = document.getElementById("blueprint-caption");
  if (caption) {
    caption.textContent = isCircuit
      ? "The architecture itself: which module imports which, parsed from the source tree on every request."
      : "One invoice's path through the gates: ingestion, guardrail, gateway, conductor, memory, ledger, trace. For the architecture itself, switch to the module circuit.";
  }
  localStorage.setItem("sentinel_blueprint_view", view);
}

function initCircuit() {
  const svg = document.getElementById("circuit-svg");
  if (!svg) return;

  const nodes = Array.from(svg.querySelectorAll(".node"));
  const wires = Array.from(svg.querySelectorAll(".wire"));

  const info = document.getElementById("circuit-info");
  const infoIdle = info ? info.innerHTML : "";

  const clear = () => {
    svg.classList.remove("has-focus");
    nodes.forEach(n => n.classList.remove("is-focus", "is-neighbour"));
    wires.forEach(w => w.classList.remove("is-linked"));
    if (info) info.innerHTML = infoIdle;
  };

  // The panel is filled with textContent, never markup: a module docstring is source text and
  // has no business being parsed as HTML.
  const describe = (node) => {
    if (!info) return;
    info.replaceChildren();

    const name = document.createElement("span");
    name.className = "eyebrow";
    name.textContent = node.getAttribute("data-id");

    const summary = document.createElement("p");
    const text = (node.getAttribute("data-summary") || "").trim();
    summary.textContent = text || "This module carries no docstring, so it has nothing to say here yet.";
    if (!text) summary.classList.add("is-missing");

    const wiring = document.createElement("p");
    wiring.className = "item-meta numeric";
    wiring.textContent = `imports ${node.getAttribute("data-imports")} / `
      + `imported by ${node.getAttribute("data-imported-by")}`;

    info.append(name, summary, wiring);
  };

  nodes.forEach(node => {
    const id = node.getAttribute("data-id");
    const neighbours = new Set((node.getAttribute("data-neighbours") || "").split(" ").filter(Boolean));

    const focus = () => {
      svg.classList.add("has-focus");
      describe(node);
      nodes.forEach(other => {
        const otherId = other.getAttribute("data-id");
        other.classList.toggle("is-focus", otherId === id);
        other.classList.toggle("is-neighbour", neighbours.has(otherId));
      });
      wires.forEach(wire => {
        wire.classList.toggle(
          "is-linked",
          wire.getAttribute("data-source") === id || wire.getAttribute("data-target") === id
        );
      });
    };

    node.addEventListener("mouseenter", focus);
    node.addEventListener("focus", focus);
    node.addEventListener("mouseleave", clear);
    node.addEventListener("blur", clear);
    // Reachable by keyboard, so the highlight is not mouse-only.
    node.setAttribute("tabindex", "0");
  });

  svg.addEventListener("mouseleave", clear);
  showBlueprintView(localStorage.getItem("sentinel_blueprint_view") || "flow");
}

document.addEventListener("DOMContentLoaded", initCircuit);
