"""Tests for the module interdependency circuit.

The value of this view is that it is derived, not drawn. These tests hold it to that: every
node must be a file that exists and every wire must be an import that is really in the source.
"""

from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from sentinel_fleet.web.blueprint_graph import build_circuit, collect_graph
from sentinel_fleet.web.server import app

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "sentinel_fleet"

# The submodules the blueprint is expected to account for, by pillar.
EXPECTED_MODULES = [
    "core.gateway", "core.model_armor", "core.identity", "core.policies", "core.permissions",
    "core.telemetry", "core.storage", "core.skills", "core.prompts", "core.privacy_contacts",
    "uas.task_master", "uas.ticket_master",
    "conductor.lifecycle", "conductor.router", "conductor.swarm",
    "memory.bank", "memory.gardener_rag", "memory.hooker",
    "domains.omniledger.extractor", "domains.omniledger.compliance",
    "domains.omniledger.reconciliation", "domains.omniledger.dispute_loop",
    "chat.service",
]


def test_every_expected_submodule_is_a_node():
    circuit = build_circuit()
    ids = {node["id"] for node in circuit["nodes"]}
    missing = [module for module in EXPECTED_MODULES if module not in ids]
    assert not missing, f"modules absent from the circuit: {missing}"


def test_every_node_is_a_file_that_exists():
    circuit = build_circuit()
    for node in circuit["nodes"]:
        path = PACKAGE_ROOT / (node["id"].replace(".", "/") + ".py")
        assert path.exists(), f"{node['id']} is drawn but has no module on disk"


def test_every_wire_is_a_real_import_statement():
    """The guard against a decorative diagram: no edge may exist that the code does not."""
    _, edges = collect_graph()
    assert edges, "no import edges were found at all"

    for source, target in edges:
        source_file = PACKAGE_ROOT / (source.replace(".", "/") + ".py")
        text = source_file.read_text(encoding="utf-8")
        dotted = f"sentinel_fleet.{target}"
        package, _, leaf = target.rpartition(".")
        from_package = f"from sentinel_fleet.{package} import"

        assert dotted in text or (from_package in text and leaf in text), (
            f"{source} is wired to {target} but does not import it"
        )


def test_known_edges_are_present_and_known_non_edges_are_absent():
    _, edges = collect_graph()

    # The chat service really does route through the gateway; that claim is load bearing.
    assert ("chat.service", "core.gateway") in edges
    assert ("chat.service", "conductor.lifecycle") in edges
    assert ("core.gateway", "core.model_armor") in edges
    assert ("domains.omniledger.extractor", "core.config") in edges

    # config is a leaf: it must not import the modules that import it.
    outgoing_from_config = {target for source, target in edges if source == "core.config"}
    assert not outgoing_from_config, f"core.config should import nothing internal, found {outgoing_from_config}"
    assert ("core.model_armor", "chat.service") not in edges


def test_an_importer_is_laid_out_left_of_what_it_imports():
    circuit = build_circuit()
    position = {node["id"]: node["x"] for node in circuit["nodes"]}
    for wire in circuit["wires"]:
        assert position[wire["source"]] < position[wire["target"]], (
            f"{wire['source']} should sit left of {wire['target']}"
        )


def test_wires_are_orthogonal_paths():
    """Schematic traces: horizontal and vertical runs only, no curves."""
    circuit = build_circuit()
    for wire in circuit["wires"]:
        assert wire["path"].startswith("M ")
        assert "C" not in wire["path"] and "Q" not in wire["path"]
        assert "H" in wire["path"]


def test_pillars_are_assigned_from_the_package():
    circuit = build_circuit()
    by_id = {node["id"]: node for node in circuit["nodes"]}
    assert by_id["core.gateway"]["pillar"] == "control"
    assert by_id["memory.bank"]["pillar"] == "memory"
    assert by_id["uas.task_master"]["pillar"] == "uas"
    assert by_id["domains.omniledger.extractor"]["pillar"] == "domain"
    assert by_id["conductor.swarm"]["pillar"] == "conductor"
    assert by_id["web.server"]["pillar"] == "web"


def test_duplicate_basenames_get_distinguishing_labels():
    """Two packages define `models`; identical labels would make the diagram unreadable."""
    circuit = build_circuit()
    labels = [node["label"] for node in circuit["nodes"]]
    assert len(labels) == len(set(labels)), f"duplicate node labels: {sorted(labels)}"


@pytest.mark.asyncio
async def test_blueprint_serves_both_views_with_a_switcher():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/blueprint")
        assert response.status_code == 200
        body = response.text

    assert 'id="blueprint-view-flow"' in body
    assert 'id="blueprint-view-circuit"' in body
    assert "showBlueprintView('circuit')" in body
    # View one survives the addition, including the whitelisted component chip.
    assert 'chip-item">RechnungsSteller<' in body
    # The circuit really rendered: nodes, wires and the hover data the highlight needs.
    assert 'data-id="core.gateway"' in body
    assert 'data-neighbours=' in body
    assert body.count('class="node"') == build_circuit()["module_count"]


@pytest.mark.asyncio
async def test_legacy_schaltplan_route_still_redirects():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/schaltplan")
        assert response.status_code == 307
        assert response.headers["location"] == "/blueprint"
