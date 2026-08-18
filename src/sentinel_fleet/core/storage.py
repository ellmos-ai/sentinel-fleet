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


class FirestoreStore(BaseStore[T]):
    """Google Cloud Firestore entity store with local fallback."""
    def __init__(self, collection_name: str, model_cls: Type[T]):
        self.collection_name = collection_name
        self.model_cls = model_cls
        self._fallback_store = LocalJsonStore(collection_name, model_cls)
        self._client = None
        self._init_firestore()

    def _init_firestore(self):
        # Attempt to initialize Firestore if environment is production or gcp project is set
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("K_SERVICE"):
            try:
                from google.cloud import firestore
                self._client = firestore.Client(project=settings.google_cloud_project)
            except Exception:
                self._client = None

    def get(self, key: str) -> Optional[T]:
        if self._client:
            try:
                doc_ref = self._client.collection(self.collection_name).document(key)
                doc = doc_ref.get()
                if doc.exists:
                    return self.model_cls.model_validate(doc.to_dict())
                return None
            except Exception:
                pass
        return self._fallback_store.get(key)

    def put(self, key: str, item: T) -> T:
        if self._client:
            try:
                doc_ref = self._client.collection(self.collection_name).document(key)
                doc_ref.set(item.model_dump())
            except Exception:
                pass
        return self._fallback_store.put(key, item)

    def delete(self, key: str) -> bool:
        if self._client:
            try:
                self._client.collection(self.collection_name).document(key).delete()
            except Exception:
                pass
        return self._fallback_store.delete(key)

    def list_all(self) -> List[T]:
        if self._client:
            try:
                docs = self._client.collection(self.collection_name).stream()
                results = []
                for d in docs:
                    results.append(self.model_cls.model_validate(d.to_dict()))
                return results
            except Exception:
                pass
        return self._fallback_store.list_all()

    def count(self) -> int:
        if self._client:
            try:
                return len(list(self._client.collection(self.collection_name).stream()))
            except Exception:
                pass
        return self._fallback_store.count()

    def clear(self):
        self._fallback_store.clear()


def get_store(collection_name: str, model_cls: Type[T]) -> BaseStore[T]:
    """Factory creating appropriate storage engine based on settings."""
    if settings.environment == "production" or os.getenv("USE_FIRESTORE", "false").lower() == "true":
        return FirestoreStore(collection_name, model_cls)
    
    # In local/test mode, use thread-safe LocalJsonStore
    data_dir = getattr(settings, "data_dir", "./data")
    file_path = os.path.join(data_dir, f"{collection_name}.json")
    return LocalJsonStore(collection_name, model_cls, persistence_path=file_path)
