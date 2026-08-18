// SentinelFleet Enterprise Frontend Script (Light Default, Persistence & Full Governance)

document.addEventListener("DOMContentLoaded", () => {
  // 1. Initialize Theme (Default: Light)
  const savedTheme = localStorage.getItem("sentinel_theme") || "light";
  document.documentElement.setAttribute("data-theme", savedTheme);

  // 2. Initialize Active Tab / View
  const savedTab = localStorage.getItem("sentinel_active_tab") || "tab-overview";
  switchTab(savedTab, false);
});

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "light";
  const next = current === "light" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("sentinel_theme", next);
}

function switchTab(tabId, save = true) {
  document.querySelectorAll(".tab-pane").forEach(el => el.style.display = "none");
  document.querySelectorAll(".subnav-btn").forEach(el => el.classList.remove("active"));
  
  const target = document.getElementById(tabId);
  if (target) target.style.display = "block";
  
  const btn = document.getElementById("btn-" + tabId);
  if (btn) btn.classList.add("active");

  if (save) {
    localStorage.setItem("sentinel_active_tab", tabId);
  }
}

function toggleModal(modalId) {
  const m = document.getElementById(modalId);
  if (m) {
    m.style.display = m.style.display === "flex" ? "none" : "flex";
  }
}

// Live Showcase & Workflow Triggers
// API-supplied values are written via textContent, never interpolated into markup.
function setProcessStatus(text, badgeClass) {
  const statusDiv = document.getElementById("process-status");
  if (!statusDiv) return;
  statusDiv.replaceChildren();
  const badge = document.createElement("span");
  badge.className = `badge-status ${badgeClass}`;
  badge.textContent = text;
  statusDiv.appendChild(badge);
}

// Reflects whether the last extraction ran on Gemini or on deterministic demo data.
function updateExtractionModeBadge(mode) {
  const badge = document.getElementById("extraction-mode-badge");
  if (!badge || !mode) return;
  const isLive = mode !== "deterministic-demo";
  badge.className = `badge-status ${isLive ? "badge-ok" : "badge-warn"}`;
  badge.textContent = isLive ? "Gemini Live" : "Demo Mode";
  badge.title = isLive
    ? `Last extraction produced by ${mode}`
    : "Last extraction produced by deterministic demo data (no live model call)";
}

async function dispatchInvoiceProcessing(formData, label) {
  setProcessStatus(`⏳ Dispatching to Fleet: ${label}...`, "badge-warn");

  try {
    const res = await fetch("/api/omniledger/process", {
      method: "POST",
      body: formData
    });

    const data = await res.json();
    if (res.ok) {
      updateExtractionModeBadge(data.extraction_mode);
      setProcessStatus(
        `✅ Processed Task: ${data.task_id} (Status: ${data.invoice.status}, Mode: ${data.extraction_mode})`,
        "badge-ok"
      );
      setTimeout(() => location.reload(), 1200);
    } else {
      setProcessStatus(`🛡️ ${data.reason || "Execution Blocked by Model Armor"}`, "badge-danger");
      setTimeout(() => location.reload(), 1800);
    }
  } catch (err) {
    setProcessStatus(`❌ Error: ${err.message}`, "badge-danger");
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
    setProcessStatus("⚠️ Select a document first", "badge-warn");
    return;
  }
  const formData = new FormData();
  formData.append("file", input.files[0]);
  formData.append("preset_type", "upload");
  await dispatchInvoiceProcessing(formData, input.files[0].name);
}

// Ticket Master HITL Approvals
async function approveTicket(ticketId) {
  try {
    const res = await fetch(`/api/tickets/${ticketId}/approve`, { method: "POST" });
    if (res.ok) {
      location.reload();
    }
  } catch (err) {
    alert("Error approving ticket: " + err.message);
  }
}

async function rejectTicket(ticketId) {
  try {
    const res = await fetch(`/api/tickets/${ticketId}/reject`, { method: "POST" });
    if (res.ok) {
      location.reload();
    }
  } catch (err) {
    alert("Error rejecting ticket: " + err.message);
  }
}

async function releaseQuarantine(agentId) {
  try {
    const res = await fetch(`/api/agents/${agentId}/quarantine/release`, { method: "POST" });
    if (res.ok) {
      location.reload();
    }
  } catch (err) {
    alert("Error releasing quarantine: " + err.message);
  }
}

// Form Submissions for Tasks, Tickets, Memory & Contacts
async function submitNewTicket(event) {
  event.preventDefault();
  const formData = new FormData(event.target);
  try {
    const res = await fetch("/api/tickets/create", { method: "POST", body: formData });
    if (res.ok) location.reload();
  } catch (err) {
    alert("Error creating ticket: " + err.message);
  }
}

async function submitNewTask(event) {
  event.preventDefault();
  const formData = new FormData(event.target);
  try {
    const res = await fetch("/api/tasks/create", { method: "POST", body: formData });
    if (res.ok) location.reload();
  } catch (err) {
    alert("Error assigning task: " + err.message);
  }
}

async function submitNewMemory(event) {
  event.preventDefault();
  const formData = new FormData(event.target);
  try {
    const res = await fetch("/api/memory/create", { method: "POST", body: formData });
    if (res.ok) location.reload();
  } catch (err) {
    alert("Error storing memory: " + err.message);
  }
}

async function submitNewContact(event) {
  event.preventDefault();
  const formData = new FormData(event.target);
  try {
    const res = await fetch("/api/contacts/create", { method: "POST", body: formData });
    if (res.ok) location.reload();
  } catch (err) {
    alert("Error saving contact: " + err.message);
  }
}

async function optOutContact(contactId) {
  if (!confirm("Kontakt wirklich abmelden und Tombstone-Sperre aktivieren?")) return;
  try {
    const res = await fetch(`/api/contacts/${contactId}/opt-out`, { method: "POST" });
    if (res.ok) location.reload();
  } catch (err) {
    alert("Error setting opt-out: " + err.message);
  }
}

// Prompt & Skill Governance Forms
function openPromptVersionModal(promptId, title, currentText) {
  document.getElementById("pv-prompt-id").value = promptId;
  document.getElementById("pv-title").innerText = title;
  document.getElementById("pv-text").value = currentText;
  toggleModal("modal-prompt-version");
}

async function submitPromptVersion(event) {
  event.preventDefault();
  const form = event.target;
  const promptId = document.getElementById("pv-prompt-id").value;
  const formData = new FormData(form);

  try {
    const res = await fetch(`/api/prompts/${promptId}/version`, { method: "POST", body: formData });
    if (res.ok) location.reload();
  } catch (err) {
    alert("Error bumping prompt version: " + err.message);
  }
}

function openPromptPermsModal(promptId, title, visibility, reqApproval) {
  document.getElementById("pp-prompt-id").value = promptId;
  document.getElementById("pp-title").innerText = title;
  document.getElementById("pp-visibility").value = visibility;
  document.getElementById("pp-approval").checked = (reqApproval === 'true' || reqApproval === true);
  toggleModal("modal-prompt-perms");
}

async function submitPromptPerms(event) {
  event.preventDefault();
  const promptId = document.getElementById("pp-prompt-id").value;
  const formData = new FormData(event.target);

  try {
    const res = await fetch(`/api/prompts/${promptId}/permissions`, { method: "POST", body: formData });
    if (res.ok) location.reload();
  } catch (err) {
    alert("Error updating permissions: " + err.message);
  }
}

function openSkillVersionModal(skillId, name, tools) {
  document.getElementById("sv-skill-id").value = skillId;
  document.getElementById("sv-name").innerText = name;
  document.getElementById("sv-tools").value = tools;
  toggleModal("modal-skill-version");
}

async function submitSkillVersion(event) {
  event.preventDefault();
  const skillId = document.getElementById("sv-skill-id").value;
  const formData = new FormData(event.target);

  try {
    const res = await fetch(`/api/skills/${skillId}/version`, { method: "POST", body: formData });
    if (res.ok) location.reload();
  } catch (err) {
    alert("Error bumping skill version: " + err.message);
  }
}
