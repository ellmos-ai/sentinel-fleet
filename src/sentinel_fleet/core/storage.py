"""Pluggable Storage Engine for SentinelFleet (Local & Google Cloud Firestore)."""

import os
import json
import threading
from typing import TypeVar, Generic, Type, Dict, List, Optional, Any
from pydantic import BaseModel
from sentinel_fleet.core.config import settings

T = TypeVar("T", bound=BaseModel)


class BaseStore(Generic[T]):
    """Abstract interface for entity stores."""
    def get(self, key: str) -> Optional[T]:
        raise NotImplementedError

    def put(self, key: str, item: T) -> T:
        raise NotImplementedError

    def delete(self, key: str) -> bool:
        raise NotImplementedError

    def list_all(self) -> List[T]:
        raise NotImplementedError

    def count(self) -> int:
        raise NotImplementedError

    def clear(self):
        raise NotImplementedError


class LocalJsonStore(BaseStore[T]):
    """Thread-safe persistent JSON/In-Memory store for local development, tests and stateless fallback."""
    def __init__(self, collection_name: str, model_cls: Type[T], persistence_path: Optional[str] = None):
        self.collection_name = collection_name
        self.model_cls = model_cls
        self.persistence_path = persistence_path
        self._data: Dict[str, T] = {}
        self._lock = threading.RLock()
        self._load_from_disk()

    def _load_from_disk(self):
        if not self.persistence_path or not os.path.exists(self.persistence_path):
            return
        try:
            with open(self.persistence_path, "r", encoding="utf-8") as f:
                raw_dict = json.load(f)
                with self._lock:
                    for k, v in raw_dict.items():
                        self._data[k] = self.model_cls.model_validate(v)
        except Exception:
            pass

    def _save_to_disk(self):
        if not self.persistence_path:
            return
        try:
            os.makedirs(os.path.dirname(self.persistence_path), exist_ok=True)
            with self._lock:
                serialized = {k: v.model_dump() for k, v in self._data.items()}
            with open(self.persistence_path, "w", encoding="utf-8") as f:
                json.dump(serialized, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get(self, key: str) -> Optional[T]:
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, item: T) -> T:
        with self._lock:
            self._data[key] = item
            self._save_to_disk()
            return item

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._data:
                del self._data[key]
                self._save_to_disk()
                return True
            return False

    def list_all(self) -> List[T]:
        with self._lock:
            return list(self._data.values())

    def count(self) -> int:
        with self._lock:
            return len(self._data)

    def clear(self):
        with self._lock:
            self._data.clear()
            self._save_to_disk()


class StorageBackendError(RuntimeError):
    """The requested durable backend is unavailable or rejected an operation."""


class FirestoreStore(BaseStore[T]):
    """Strict Google Cloud Firestore store.

    Once cloud persistence is selected, losing it is a startup/runtime error. Falling back to
    an instance-local dictionary would acknowledge a write that another Cloud Run instance can
    never see and that a cold start erases.
    """
    def __init__(self, collection_name: str, model_cls: Type[T]):
        self.collection_name = collection_name
        self.model_cls = model_cls
        self._init_firestore()

    def _init_firestore(self):
        try:
            from google.cloud import firestore
            self._client = firestore.Client(project=settings.google_cloud_project)
        except Exception as exc:
            raise StorageBackendError(
                f"Firestore backend required for '{self.collection_name}' but initialization failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def get(self, key: str) -> Optional[T]:
        try:
            doc = self._client.collection(self.collection_name).document(key).get()
            return self.model_cls.model_validate(doc.to_dict()) if doc.exists else None
        except Exception as exc:
            raise StorageBackendError(f"Firestore read failed for {self.collection_name}/{key}: {exc}") from exc

    def put(self, key: str, item: T) -> T:
        try:
            self._client.collection(self.collection_name).document(key).set(item.model_dump())
            return item
        except Exception as exc:
            raise StorageBackendError(f"Firestore write failed for {self.collection_name}/{key}: {exc}") from exc

    def delete(self, key: str) -> bool:
        existed = self.get(key) is not None
        if not existed:
            return False
        try:
            self._client.collection(self.collection_name).document(key).delete()
            return True
        except Exception as exc:
            raise StorageBackendError(f"Firestore delete failed for {self.collection_name}/{key}: {exc}") from exc

    def list_all(self) -> List[T]:
        try:
            return [
                self.model_cls.model_validate(snapshot.to_dict())
                for snapshot in self._client.collection(self.collection_name).stream()
            ]
        except Exception as exc:
            raise StorageBackendError(f"Firestore list failed for {self.collection_name}: {exc}") from exc

    def count(self) -> int:
        return len(self.list_all())

    def clear(self):
        try:
            for snapshot in self._client.collection(self.collection_name).stream():
                snapshot.reference.delete()
        except Exception as exc:
            raise StorageBackendError(f"Firestore clear failed for {self.collection_name}: {exc}") from exc


def requested_backend() -> str:
    if (
        settings.environment == "production"
        or bool(os.getenv("K_SERVICE"))
        or os.getenv("USE_FIRESTORE", "false").lower() == "true"
    ):
        return "firestore"
    return "local-json"


def get_store(collection_name: str, model_cls: Type[T]) -> BaseStore[T]:
    """Factory creating appropriate storage engine based on settings."""
    if requested_backend() == "firestore":
        return FirestoreStore(collection_name, model_cls)
    
    # In local/test mode, use thread-safe LocalJsonStore
    data_dir = getattr(settings, "data_dir", "./data")
    file_path = os.path.join(data_dir, f"{collection_name}.json")
    return LocalJsonStore(collection_name, model_cls, persistence_path=file_path)
