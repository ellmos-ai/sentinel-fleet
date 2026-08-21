"""Durable result-document storage and creator-owned access contracts."""

import hashlib
import json

import pytest
from httpx import ASGITransport, AsyncClient

from sentinel_fleet.core.artifacts import (
    ArtifactAccessError,
    ArtifactBackendError,
    ArtifactNotFoundError,
    ArtifactRecord,
    ArtifactService,
    LocalBlobStore,
)
from sentinel_fleet.core.storage import LocalJsonStore
from sentinel_fleet.uas.task_master import TaskMaster, TaskRecord, TaskState
from sentinel_fleet.web.server import app


def _service(tmp_path):
    metadata_path = tmp_path / "artifacts.json"
    blob_root = tmp_path / "blobs"
    return (
        ArtifactService(
            metadata_store=LocalJsonStore("artifacts", ArtifactRecord, str(metadata_path)),
            blob_store=LocalBlobStore(blob_root),
        ),
        metadata_path,
        blob_root,
    )


def test_result_survives_service_restart_and_is_private_by_default(tmp_path):
    service, metadata_path, blob_root = _service(tmp_path)
    created = service.store_result(
        content=b"durable result",
        filename="result.txt",
        media_type="text/plain",
        creator_id="workspace:alice",
        source_kind="test",
        source_ref="run-1",
    )

    restarted = ArtifactService(
        metadata_store=LocalJsonStore("artifacts", ArtifactRecord, str(metadata_path)),
        blob_store=LocalBlobStore(blob_root),
    )
    record, content = restarted.download(created.artifact_id, "workspace:alice")

    assert content == b"durable result"
    assert record.visibility == "private"
    assert record.sha256 == hashlib.sha256(content).hexdigest()
    with pytest.raises(ArtifactNotFoundError):
        restarted.download(created.artifact_id, "workspace:bob")


def test_only_creator_changes_sharing_and_named_or_org_recipients_can_read(tmp_path):
    service, _, _ = _service(tmp_path)
    created = service.store_result(
        content=b"shared result",
        filename="shared.txt",
        media_type="text/plain",
        creator_id="workspace:alice",
    )

    with pytest.raises(ArtifactAccessError):
        service.update_sharing(
            created.artifact_id,
            requested_by="workspace:bob",
            visibility="organization",
            shared_with=[],
        )

    service.update_sharing(
        created.artifact_id,
        requested_by="workspace:alice",
        visibility="private",
        shared_with=["workspace:bob"],
    )
    assert service.download(created.artifact_id, "workspace:bob")[1] == b"shared result"

    service.update_sharing(
        created.artifact_id,
        requested_by="workspace:alice",
        visibility="organization",
        shared_with=[],
    )
    assert service.download(created.artifact_id, "workspace:carol")[1] == b"shared result"


def test_department_share_is_limited_to_the_creators_department(tmp_path):
    service, _, _ = _service(tmp_path)
    created = service.store_result(
        content=b"department result",
        filename="department.txt",
        media_type="text/plain",
        creator_id="alice",
        creator_department="finance",
    )
    service.update_sharing(
        created.artifact_id,
        requested_by="alice",
        requested_department="finance",
        visibility="department",
        shared_with=[],
    )

    assert service.download(created.artifact_id, "bob", "finance")[1] == b"department result"
    with pytest.raises(ArtifactNotFoundError):
        service.download(created.artifact_id, "carol", "operations")


def test_organization_share_never_crosses_the_organization_boundary(tmp_path):
    service, _, _ = _service(tmp_path)
    created = service.store_result(
        content=b"organization result",
        filename="organization.txt",
        media_type="text/plain",
        creator_id="alice",
        creator_organization="org-a",
    )
    service.update_sharing(
        created.artifact_id,
        requested_by="alice",
        requested_organization="org-a",
        visibility="organization",
        shared_with=[],
    )

    assert service.download(
        created.artifact_id, "bob", requested_organization="org-a"
    )[1] == b"organization result"
    with pytest.raises(ArtifactNotFoundError):
        service.download(created.artifact_id, "mallory", requested_organization="org-b")


def test_download_detects_blob_tampering(tmp_path):
    service, _, blob_root = _service(tmp_path)
    created = service.store_result(
        content=b"original",
        filename="proof.bin",
        media_type="application/octet-stream",
        creator_id="workspace:alice",
    )
    (blob_root / "results" / f"{created.artifact_id}.bin").write_bytes(b"tampered")

    with pytest.raises(ArtifactBackendError, match="integrity"):
        service.download(created.artifact_id, "workspace:alice")


def test_only_creator_can_delete_and_deleted_result_keeps_an_audit_tombstone(tmp_path):
    service, _, blob_root = _service(tmp_path)
    created = service.store_result(
        content=b"delete me",
        filename="delete.txt",
        media_type="text/plain",
        creator_id="alice",
    )
    with pytest.raises(ArtifactAccessError):
        service.delete_result(created.artifact_id, requested_by="bob")

    tombstone = service.delete_result(created.artifact_id, requested_by="alice")
    assert tombstone.deleted_at is not None
    assert tombstone.deletion_requested_by == "alice"
    assert not (blob_root / "results" / f"{created.artifact_id}.bin").exists()
    assert not service.list_visible("alice")
    with pytest.raises(ArtifactNotFoundError):
        service.download(created.artifact_id, "alice")


def test_retention_and_legal_hold_are_enforced_not_just_described(tmp_path):
    service, _, _ = _service(tmp_path)
    created = service.store_result(
        content=b"retain me",
        filename="retained.txt",
        media_type="text/plain",
        creator_id="alice",
        creator_organization="org-a",
    )
    service.set_retention(
        created.artifact_id,
        requested_organization="org-a",
        policy="retain_until",
        retain_until=10_000_000_000.0,
    )
    with pytest.raises(ArtifactAccessError, match="retained"):
        service.delete_result(
            created.artifact_id,
            requested_by="alice",
            requested_organization="org-a",
        )
    service.set_legal_hold(
        created.artifact_id, requested_organization="org-a", enabled=True
    )
    with pytest.raises(ArtifactAccessError, match="Legal hold"):
        service.set_retention(
            created.artifact_id,
            requested_organization="org-a",
            policy="creator_managed",
            retain_until=None,
        )


def test_completed_task_output_is_linked_to_a_private_downloadable_artifact(
    tmp_path, monkeypatch
):
    from sentinel_fleet.core import artifacts as artifacts_module

    service = ArtifactService(
        metadata_store=LocalJsonStore(
            "task-result-artifacts",
            ArtifactRecord,
            str(tmp_path / "task-result-artifacts.json"),
        ),
        blob_store=LocalBlobStore(tmp_path / "task-result-blobs"),
    )
    monkeypatch.setattr(artifacts_module, "artifact_service", service)
    tasks = TaskMaster()
    tasks._store = LocalJsonStore(
        "task-result-tasks",
        TaskRecord,
        str(tmp_path / "task-result-tasks.json"),
    )
    task = tasks.create_task(
        name="Generate report",
        assigned_agent="agent:task-solver",
        input_data={},
        owner_id="alice",
        organization_id="org-a",
        visibility="private",
    )

    completed = tasks.update_task_state(
        task.task_id,
        TaskState.COMPLETED,
        output_data={"summary": "ready"},
    )

    assert completed.result_artifact_id
    artifact, content = service.download(
        completed.result_artifact_id,
        requested_by="alice",
        requested_organization="org-a",
    )
    assert artifact.source_kind == "task_result"
    assert json.loads(content) == {"summary": "ready"}
    with pytest.raises(ArtifactNotFoundError):
        service.download(
            completed.result_artifact_id,
            requested_by="bob",
            requested_organization="org-a",
        )

@pytest.mark.asyncio
async def test_chat_export_is_saved_then_shareable_by_its_creator():
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as alice,
        AsyncClient(transport=transport, base_url="http://test") as bob,
    ):
        alice_id = (await alice.get("/api/access/me")).json()["share_id"]
        bob_id = (await bob.get("/api/access/me")).json()["share_id"]
        assert alice_id != bob_id

        created = await alice.post("/api/chat/send", json={"message": "Persist this result"})
        session_id = created.json()["session_id"]
        exported = await alice.get(f"/api/chat/sessions/{session_id}/export?format=md")
        assert exported.status_code == 200
        artifact_id = exported.headers["x-sentinel-artifact-id"]

        alice_documents = (await alice.get("/api/artifacts")).json()
        assert any(item["artifact_id"] == artifact_id for item in alice_documents)
        assert (await bob.get(f"/api/artifacts/{artifact_id}/download")).status_code == 404

        shared = await alice.put(
            f"/api/artifacts/{artifact_id}/sharing",
            json={"visibility": "private", "shared_with": [bob_id]},
        )
        assert shared.status_code == 200
        assert (await bob.get(f"/api/artifacts/{artifact_id}/download")).content == exported.content

        forbidden = await bob.put(
            f"/api/artifacts/{artifact_id}/sharing",
            json={"visibility": "organization", "shared_with": []},
        )
        assert forbidden.status_code == 403
