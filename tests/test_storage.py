"""Unit tests for the pluggable storage engine (local JSON store and Firestore store)."""

import sys
import types

import pytest
from pydantic import BaseModel

from sentinel_fleet.core.storage import (
    FirestoreStore,
    LocalJsonStore,
    StorageBackendError,
    get_store,
    requested_backend,
)


class Sample(BaseModel):
    id: str
    label: str
    score: int = 0


# ---------------------------------------------------------
# LocalJsonStore
# ---------------------------------------------------------

def test_local_store_crud_roundtrip():
    store = LocalJsonStore("samples", Sample)

    assert store.get("a") is None
    assert store.count() == 0

    store.put("a", Sample(id="a", label="first"))
    store.put("b", Sample(id="b", label="second", score=7))

    assert store.count() == 2
    assert store.get("b").score == 7
    assert {s.id for s in store.list_all()} == {"a", "b"}

    assert store.delete("a") is True
    assert store.delete("a") is False
    assert store.count() == 1

    store.clear()
    assert store.list_all() == []


def test_local_store_persists_and_reloads(tmp_path):
    path = tmp_path / "nested" / "samples.json"

    writer = LocalJsonStore("samples", Sample, persistence_path=str(path))
    writer.put("a", Sample(id="a", label="persisted", score=3))
    assert path.exists()

    reader = LocalJsonStore("samples", Sample, persistence_path=str(path))
    restored = reader.get("a")
    assert restored is not None
    assert restored.label == "persisted"
    assert restored.score == 3

    reader.delete("a")
    assert LocalJsonStore("samples", Sample, persistence_path=str(path)).get("a") is None


def test_get_store_returns_local_store_outside_production(monkeypatch, tmp_path):
    monkeypatch.setenv("USE_FIRESTORE", "false")
    monkeypatch.setattr("sentinel_fleet.core.storage.settings.environment", "development", raising=False)
    monkeypatch.setattr("sentinel_fleet.core.storage.settings.data_dir", str(tmp_path), raising=False)

    store = get_store("samples", Sample)
    assert isinstance(store, LocalJsonStore)
    assert store.persistence_path.startswith(str(tmp_path))


# ---------------------------------------------------------
# FirestoreStore (google.cloud.firestore is mocked; the package is not installed)
# ---------------------------------------------------------

class _FakeSnapshot:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return self._data


class _FakeDocumentRef:
    def __init__(self, collection, key):
        self._collection = collection
        self._key = key

    def get(self):
        return _FakeSnapshot(self._collection.documents.get(self._key))

    def set(self, data):
        self._collection.documents[self._key] = data

    def delete(self):
        self._collection.documents.pop(self._key, None)


class _FakeCollection:
    def __init__(self):
        self.documents = {}

    def document(self, key):
        return _FakeDocumentRef(self, key)

    def stream(self):
        return [_FakeSnapshot(d) for d in self.documents.values()]


class _FakeFirestoreClient:
    def __init__(self, project=None):
        self.project = project
        self._collections = {}

    def collection(self, name):
        return self._collections.setdefault(name, _FakeCollection())


@pytest.fixture
def fake_firestore(monkeypatch):
    """Install a stand-in for google.cloud.firestore and make the store take the cloud path."""
    firestore_module = types.ModuleType("google.cloud.firestore")
    firestore_module.Client = _FakeFirestoreClient

    cloud_module = sys.modules.get("google.cloud") or types.ModuleType("google.cloud")
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_module)
    monkeypatch.setitem(sys.modules, "google.cloud.firestore", firestore_module)
    monkeypatch.setattr(cloud_module, "firestore", firestore_module, raising=False)

    # FirestoreStore only initialises a client when it believes it runs on GCP
    monkeypatch.setenv("K_SERVICE", "sentinel-fleet-test")
    return firestore_module


def test_firestore_store_uses_the_cloud_client(fake_firestore):
    store = FirestoreStore("samples", Sample)
    assert isinstance(store._client, _FakeFirestoreClient)

    store.put("a", Sample(id="a", label="cloud", score=1))

    # The document landed in the fake Firestore collection, not only in the local fallback
    assert store._client.collection("samples").documents["a"]["label"] == "cloud"

    fetched = store.get("a")
    assert fetched is not None and fetched.label == "cloud"

    assert store.count() == 1
    assert [s.id for s in store.list_all()] == ["a"]

    store.delete("a")
    assert store._client.collection("samples").documents == {}
    assert store.get("a") is None


def test_firestore_store_fails_closed_when_the_client_is_unavailable(monkeypatch):
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    monkeypatch.setitem(sys.modules, "google.cloud.firestore", None)
    with pytest.raises(StorageBackendError, match="initialization failed"):
        FirestoreStore("samples", Sample)


def test_firestore_store_fails_closed_on_a_cloud_write_error(fake_firestore, monkeypatch):
    store = FirestoreStore("samples", Sample)

    def _boom(*args, **kwargs):
        raise RuntimeError("firestore unavailable")

    monkeypatch.setattr(store._client, "collection", _boom)

    with pytest.raises(StorageBackendError, match="write failed"):
        store.put("a", Sample(id="a", label="degraded"))


def test_cloud_run_automatically_requests_firestore(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "sentinel-fleet")
    monkeypatch.setenv("USE_FIRESTORE", "false")
    monkeypatch.setattr("sentinel_fleet.core.storage.settings.environment", "development")
    assert requested_backend() == "firestore"
