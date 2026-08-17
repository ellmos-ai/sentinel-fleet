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
      statusDiv.innerHTML = `<span class="badge-status badge-danger">🛡️ ${data.reason || "Execution Blocked"}</span>`;
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

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme");
  const next = current === "light" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", next);
}
