// SentinelFleet Interactive Frontend Script

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

async function submitNewTicket(event) {
  event.preventDefault();
  const form = event.target;
  const formData = new FormData(form);

  try {
    const res = await fetch("/api/tickets/create", {
      method: "POST",
      body: formData
    });
    if (res.ok) {
      location.reload();
    }
  } catch (err) {
    alert("Error creating ticket: " + err.message);
  }
}

async function submitNewTask(event) {
  event.preventDefault();
  const form = event.target;
  const formData = new FormData(form);

  try {
    const res = await fetch("/api/tasks/create", {
      method: "POST",
      body: formData
    });
    if (res.ok) {
      location.reload();
    }
  } catch (err) {
    alert("Error assigning task: " + err.message);
  }
}

async function submitNewMemory(event) {
  event.preventDefault();
  const form = event.target;
  const formData = new FormData(form);

  try {
    const res = await fetch("/api/memory/create", {
      method: "POST",
      body: formData
    });
    if (res.ok) {
      location.reload();
    }
  } catch (err) {
    alert("Error storing memory: " + err.message);
  }
}

function switchTab(tabId) {
  document.querySelectorAll(".tab-pane").forEach(el => el.style.display = "none");
  document.querySelectorAll(".subnav-btn").forEach(el => el.classList.remove("active"));
  
  const target = document.getElementById(tabId);
  if (target) target.style.display = "block";
  
  const btn = document.getElementById("btn-" + tabId);
  if (btn) btn.classList.add("active");
}

function toggleModal(modalId) {
  const m = document.getElementById(modalId);
  if (m) {
    m.style.display = m.style.display === "flex" ? "none" : "flex";
  }
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme");
  const next = current === "light" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", next);
}
