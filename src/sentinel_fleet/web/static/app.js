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
async function processInvoicePreset(presetType) {
  const statusDiv = document.getElementById("process-status");
  statusDiv.innerHTML = `<span class="badge-status badge-warn">⏳ Dispatching to Fleet: ${presetType}...</span>`;

  const formData = new FormData();
  formData.append("preset_type", presetType);

  try {
    const res = await fetch("/api/omniledger/process", {
      method: "POST",
      body: formData
    });

    const data = await res.json();
    if (res.ok) {
      statusDiv.innerHTML = `<span class="badge-status badge-ok">✅ Processed Task: ${data.task_id} (Status: ${data.invoice.status})</span>`;
      setTimeout(() => location.reload(), 1200);
    } else {
      statusDiv.innerHTML = `<span class="badge-status badge-danger">🛡️ ${data.reason || "Execution Blocked by Model Armor"}</span>`;
      setTimeout(() => location.reload(), 1800);
    }
  } catch (err) {
    statusDiv.innerHTML = `<span class="badge-status badge-danger">❌ Error: ${err.message}</span>`;
  }
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

// Form Submissions for Tasks, Tickets & Memory
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
