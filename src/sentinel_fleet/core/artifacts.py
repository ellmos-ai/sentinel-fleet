"""Durable result documents with creator-owned sharing controls.

Metadata lives in the configured entity store (Firestore in production, JSON locally). Binary
content lives in a private Cloud Storage bucket in production and below DATA_DIR locally. Files
are always downloaded through the API so the same access decision guards metadata and bytes.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from sentinel_fleet.core.config import settings
from sentinel_fleet.core.storage import BaseStore, get_store, requested_backend


ArtifactVisibility = Literal["private", "department", "organization"]


class ArtifactRecord(BaseModel):
    artifact_id: str
    filename: str
    media_type: str
    byte_size: int
    sha256: str
    creator_id: str
    visibility: ArtifactVisibility = "private"
    department_id: Optional[str] = None
    shared_with: List[str] = Field(default_factory=list)
    source_kind: str = "generated"
    source_ref: str = ""
    created_at: float = Field(default_factory=time.time)
    retention_policy: str = "creator_managed_no_automatic_expiry"
    encryption: str = ""
    legal_hold: bool = False
    deleted_at: Optional[float] = None
    deletion_requested_by: Optional[str] = None

    @model_validator(mode="after")
    def _scope_is_coherent(self) -> "ArtifactRecord":
        if self.visibility == "department" and not self.department_id:
            raise ValueError("department-visible result needs a department_id")
        if self.visibility != "department":
            self.department_id = None
        return self


class ArtifactNotFoundError(LookupError):
    pass


class ArtifactAccessError(PermissionError):
    pass


class ArtifactBackendError(RuntimeError):
    pass


class BlobStore:
    def put(self, object_key: str, content: bytes, media_type: str) -> None:
        raise NotImplementedError

    def get(self, object_key: str) -> bytes:
        raise NotImplementedError

    def delete(self, object_key: str) -> None:
        raise NotImplementedError


_SAFE_OBJECT_KEY = re.compile(r"^[A-Za-z0-9._/-]+$")


def _check_object_key(object_key: str) -> str:
    if not object_key or not _SAFE_OBJECT_KEY.fullmatch(object_key) or ".." in object_key:
        raise ArtifactBackendError("Unsafe artifact object key")
    return object_key


class LocalBlobStore(BlobStore):
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, object_key: str) -> Path:
        return self.root / _check_object_key(object_key)

    def put(self, object_key: str, content: bytes, media_type: str) -> None:
        target = self._path(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except Exception as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise ArtifactBackendError(f"Local artifact write failed: {exc}") from exc

    def get(self, object_key: str) -> bytes:
        try:
            return self._path(object_key).read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactBackendError("Artifact bytes are missing") from exc
        except OSError as exc:
            raise ArtifactBackendError(f"Local artifact read failed: {exc}") from exc

    def delete(self, object_key: str) -> None:
        try:
            self._path(object_key).unlink(missing_ok=True)
        except OSError as exc:
            raise ArtifactBackendError(f"Local artifact delete failed: {exc}") from exc


class CloudStorageBlobStore(BlobStore):
    """Private Google Cloud Storage object store.

    The bucket is supplied by deployment configuration and is never made public by this app.
    Downloads are proxied through the authorized API instead of using public or signed URLs.
    """

    def __init__(self, bucket_name: str):
        if not bucket_name.strip():
            raise ArtifactBackendError(
                "RESULT_BUCKET is required for durable result documents in production"
            )
        try:
            from google.cloud import storage

            client = storage.Client(project=settings.google_cloud_project)
            self._bucket = client.bucket(bucket_name)
        except Exception as exc:
            raise ArtifactBackendError(
                f"Cloud Storage initialization failed: {type(exc).__name__}: {exc}"
            ) from exc

    def _blob(self, object_key: str):
        return self._bucket.blob(_check_object_key(object_key))

    def put(self, object_key: str, content: bytes, media_type: str) -> None:
        try:
            # Artifact IDs are unique. This precondition prevents an accidental overwrite.
            self._blob(object_key).upload_from_string(
                content,
                content_type=media_type,
                if_generation_match=0,
            )
        except Exception as exc:
            raise ArtifactBackendError(f"Cloud Storage artifact write failed: {exc}") from exc

    def get(self, object_key: str) -> bytes:
        try:
            return self._blob(object_key).download_as_bytes()
        except Exception as exc:
            raise ArtifactBackendError(f"Cloud Storage artifact read failed: {exc}") from exc

    def delete(self, object_key: str) -> None:
        try:
            self._blob(object_key).delete()
        except Exception as exc:
            try:
                from google.api_core.exceptions import NotFound

                if isinstance(exc, NotFound):
                    return
            except ImportError:
                pass
            raise ArtifactBackendError(f"Cloud Storage artifact delete failed: {exc}") from exc


def get_blob_store() -> BlobStore:
    if requested_backend() == "firestore":
        return CloudStorageBlobStore(settings.result_bucket)
    return LocalBlobStore(Path(settings.data_dir) / "artifacts")


def _safe_filename(filename: str) -> str:
    name = os.path.basename(filename.strip()).replace("\r", "").replace("\n", "")
    name = name.replace('"', "")
    return name[:180] or "result.bin"


class ArtifactService:
    def __init__(
        self,
        metadata_store: Optional[BaseStore[ArtifactRecord]] = None,
        blob_store: Optional[BlobStore] = None,
    ):
        self._store = metadata_store or get_store("artifacts", ArtifactRecord)
        self._blob_store = blob_store

    @property
    def blob_store(self) -> BlobStore:
        # Lazy initialization keeps read-only console access available when a production
        # deployment has not configured RESULT_BUCKET yet. Creating/downloading fails closed.
        if self._blob_store is None:
            self._blob_store = get_blob_store()
        return self._blob_store

    @staticmethod
    def can_read(
        record: ArtifactRecord,
        requested_by: str,
        requested_department: Optional[str] = None,
    ) -> bool:
        return (
            record.creator_id == requested_by
            or record.visibility == "organization"
            or (
                record.visibility == "department"
                and bool(requested_department)
                and record.department_id == requested_department
            )
            or requested_by in record.shared_with
        )

    def list_visible(
        self, requested_by: str, requested_department: Optional[str] = None
    ) -> List[ArtifactRecord]:
        return sorted(
            [
                record for record in self._store.list_all()
                if record.deleted_at is None
                and self.can_read(record, requested_by, requested_department)
            ],
            key=lambda record: record.created_at,
            reverse=True,
        )

    def store_result(
        self,
        *,
        content: bytes,
        filename: str,
        media_type: str,
        creator_id: str,
        creator_department: Optional[str] = None,
        visibility: ArtifactVisibility = "private",
        shared_with: Optional[List[str]] = None,
        source_kind: str = "generated",
        source_ref: str = "",
    ) -> ArtifactRecord:
        if not creator_id:
            raise ArtifactAccessError("A verified creator is required")
        if not content:
            raise ValueError("A result document must not be empty")
        if len(content) > settings.max_result_bytes:
            raise ValueError(
                f"Result document exceeds the {settings.max_result_bytes}-byte limit"
            )
        digest = hashlib.sha256(content).hexdigest()
        clean_name = _safe_filename(filename)
        for existing in self._store.list_all():
            if (
                existing.deleted_at is None
                and existing.creator_id == creator_id
                and existing.source_kind == source_kind
                and existing.source_ref == source_ref
                and existing.filename == clean_name
                and existing.sha256 == digest
            ):
                try:
                    # Metadata alone is not durability. Reuse only when the bytes still exist
                    # and pass the same integrity check a later download will enforce.
                    self.download(existing.artifact_id, creator_id)
                    return existing
                except ArtifactBackendError:
                    # Keep the broken record as audit evidence and write a fresh object/record.
                    continue

        artifact_id = f"artifact-{uuid.uuid4().hex}"
        record = ArtifactRecord(
            artifact_id=artifact_id,
            filename=clean_name,
            media_type=media_type or "application/octet-stream",
            byte_size=len(content),
            sha256=digest,
            creator_id=creator_id,
            visibility=visibility,
            department_id=creator_department if visibility == "department" else None,
            shared_with=self._clean_shared_with(shared_with or [], creator_id),
            source_kind=source_kind,
            source_ref=source_ref,
            encryption=(
                "google-managed-aes-256"
                if requested_backend() == "firestore"
                else "development-plaintext-filesystem"
            ),
        )
        object_key = self._object_key(artifact_id)
        self.blob_store.put(object_key, content, record.media_type)
        try:
            self._store.put(artifact_id, record)
        except Exception:
            # A binary without metadata can never be authorized or found. Best-effort rollback.
            try:
                self.blob_store.delete(object_key)
            except ArtifactBackendError:
                pass
            raise
        return record

    def get_record(
        self,
        artifact_id: str,
        requested_by: str,
        requested_department: Optional[str] = None,
    ) -> ArtifactRecord:
        record = self._store.get(artifact_id)
        if record is None:
            raise ArtifactNotFoundError(artifact_id)
        if record.deleted_at is not None:
            raise ArtifactNotFoundError(artifact_id)
        if not self.can_read(record, requested_by, requested_department):
            # Opaque IDs are not an enumeration oracle.
            raise ArtifactNotFoundError(artifact_id)
        return record

    def download(
        self,
        artifact_id: str,
        requested_by: str,
        requested_department: Optional[str] = None,
    ) -> tuple[ArtifactRecord, bytes]:
        record = self.get_record(artifact_id, requested_by, requested_department)
        content = self.blob_store.get(self._object_key(artifact_id))
        digest = hashlib.sha256(content).hexdigest()
        if len(content) != record.byte_size or digest != record.sha256:
            raise ArtifactBackendError("Stored artifact failed its size or SHA-256 integrity check")
        return record, content

    def update_sharing(
        self,
        artifact_id: str,
        *,
        requested_by: str,
        requested_department: Optional[str] = None,
        visibility: ArtifactVisibility,
        shared_with: List[str],
    ) -> ArtifactRecord:
        record = self._store.get(artifact_id)
        if record is None:
            raise ArtifactNotFoundError(artifact_id)
        if record.creator_id != requested_by:
            raise ArtifactAccessError("Only the document creator may change sharing")
        if visibility == "department" and not requested_department:
            raise ArtifactAccessError("A user without a department cannot use department sharing")
        record.visibility = visibility
        record.department_id = requested_department if visibility == "department" else None
        record.shared_with = self._clean_shared_with(shared_with, requested_by)
        self._store.put(artifact_id, record)
        return record

    def delete_result(self, artifact_id: str, *, requested_by: str) -> ArtifactRecord:
        """Make a result inaccessible, then remove its bytes; retain a metadata tombstone."""
        record = self._store.get(artifact_id)
        if record is None:
            raise ArtifactNotFoundError(artifact_id)
        if record.deleted_at is not None:
            if record.deletion_requested_by != requested_by:
                raise ArtifactNotFoundError(artifact_id)
            # A prior byte deletion may have failed after the tombstone was committed.
            self.blob_store.delete(self._object_key(artifact_id))
            return record
        if record.creator_id != requested_by:
            raise ArtifactAccessError("Only the document creator may delete it")
        if record.legal_hold:
            raise ArtifactAccessError("The document is under legal hold and cannot be deleted")
        record.deleted_at = time.time()
        record.deletion_requested_by = requested_by
        self._store.put(artifact_id, record)
        self.blob_store.delete(self._object_key(artifact_id))
        return record

    @staticmethod
    def _clean_shared_with(values: List[str], creator_id: str) -> List[str]:
        cleaned: List[str] = []
        for value in values:
            target = value.strip()
            if not target or target == creator_id or len(target) > 200:
                continue
            if target not in cleaned:
                cleaned.append(target)
            if len(cleaned) >= 50:
                break
        return cleaned

    @staticmethod
    def _object_key(artifact_id: str) -> str:
        return f"results/{artifact_id}.bin"


artifact_service = ArtifactService()
