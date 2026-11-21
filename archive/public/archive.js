"use strict";
const panels = [...document.querySelectorAll("[data-panel]")];
function showPanel(id) {
  const match = panels.find(panel => panel.id === id) || panels[0];
  panels.forEach(panel => { panel.hidden = panel !== match; });
  document.querySelectorAll("[data-tab]").forEach(link => link.setAttribute("aria-current", link.dataset.tab === match.id ? "page" : "false"));
}
function navigate() { showPanel(location.hash.replace(/^#(?:tab-)?/, "") || "overview"); }
window.addEventListener("hashchange", navigate);
navigate();
document.querySelectorAll("[data-simulate]").forEach(button => button.addEventListener("click", () => {
  const result = document.getElementById("simulation-result");
  result.textContent = button.dataset.simulate + " — simulation complete. No agent ran, no data was uploaded and nothing was sent.";
  result.scrollIntoView({behavior: "smooth", block: "nearest"});
}));
const form = document.getElementById("demo-form");
if (form) form.addEventListener("submit", event => {
  event.preventDefault();
  const result = document.getElementById("simulation-result");
  result.textContent = "Local example: invoice EXAMPLE-1042 → extraction → validation → approval draft. This is a fixed, simulated trace. Your text stays in this page and is discarded on reload.";
});
