// SentinelFleet operator console.
// Values that came from an API are written with textContent, never interpolated into markup.

const state = {
  sessionId: "",
  sessions: [],
  chatMode: "chat",
  selectedSkills: new Set(),
  skills: [],
  prompts: []
};

document.addEventListener("DOMContentLoaded", () => {
  document.documentElement.setAttribute(
    "data-theme",
    localStorage.getItem("sentinel_theme") || "light"
  );
  switchTab(localStorage.getItem("sentinel_active_tab") || "tab-overview", false);

  state.prompts = readCatalog("prompt-catalog");
  state.skills = readCatalog("skill-catalog");
  if (document.getElementById("skill-picker")) {
    renderSkillPicker();
    loadSessions();
  }

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
    });

    const label = document.createElement("span");
    const name = document.createElement("span");
    name.textContent = skill.name;
    const pillar = document.createElement("span");
    pillar.className = "picker-pillar";
    pillar.textContent = ` ${skill.pillar} v${skill.version}`;
    label.append(name, pillar);

    row.append(box, label);
    picker.appendChild(row);
  });
}

function onPromptTemplateChange() {
  const promptId = document.getElementById("chat-prompt").value;
  const versionSelect = document.getElementById("chat-prompt-version");
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
  document.getElementById("chat-transcript").replaceChildren();
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

function updateExtractionModeBadge(mode) {
  const badge = document.getElementById("extraction-mode-badge");
  if (!badge || !mode) return;
  const isLive = mode !== "deterministic-demo";
  badge.className = `badge-status ${isLive ? "badge-ok" : "badge-warn"}`;
  badge.textContent = isLive ? mode : "Demo mode";
  badge.title = isLive
    ? `Last extraction produced by ${mode}`
    : "Last extraction produced by deterministic demo data (no live model call)";
}

async function dispatchInvoiceProcessing(formData, label) {
  setProcessStatus(`Dispatching ${label}`, "badge-warn");

  try {
    const res = await fetch("/api/omniledger/process", { method: "POST", body: formData });
    const data = await res.json();
    if (res.ok) {
      updateExtractionModeBadge(data.extraction_mode);
      setProcessStatus(`${data.invoice.status} / ${data.extraction_mode}`, "badge-ok");
      setTimeout(() => location.reload(), 1200);
    } else {
      setProcessStatus(data.reason || "Blocked by Model Armor", "badge-danger");
      setTimeout(() => location.reload(), 1800);
    }
  } catch (err) {
    setProcessStatus(err.message, "badge-danger");
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
const submitNewContact = e => submitForm(e, "/api/contacts/create", "Could not save the contact");
const submitNewSkill = e => submitForm(e, "/api/skills/create", "Could not create the skill");

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
