"""Bounded streaming writes, validated temporary files, atomic no-overwrite publish."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from typing import BinaryIO, Callable, Protocol
from uuid import UUID, uuid4


LEAVES = {"sources": "original", "exports": "artifact.xlsx", "snapshots": "payload.json",
          "extraction_runs": "payload.json", "job_results": "payload.json"}
KEY = re.compile(r"(sources|exports|snapshots|extraction_runs|job_results)/[0-9a-f]{32}/(original|artifact\.xlsx|payload\.json)")
TEMP = re.compile(r"temporary/[0-9a-f]{32}/payload\.part")


class StorageError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class StoredObject:
    key: str
    sha256: str
    byte_size: int


class Storage(Protocol):
    def put(self, stream: BinaryIO, *, namespace: str, object_id: UUID | None = None,
            validate: Callable[[Path], None] | None = None, reuse_identical=False) -> StoredObject: ...
    def open(self, key: str): ...
    def verify(self, key: str, expected_sha256: str) -> StoredObject: ...


class LocalStorage:
    def __init__(self, root: Path, *, max_bytes=20 * 1024 * 1024):
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("Invalid storage byte limit")
        self.root = Path(os.path.abspath(root))
        if str(self.root).startswith(("\\\\", "//")):
            raise StorageError("STORAGE_ROOT_INVALID")
        self.max_bytes = max_bytes
        self._check_components(self.root)

    @staticmethod
    def _check_components(path):
        for item in (path, *path.parents):
            if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
                raise StorageError("STORAGE_LINK_FORBIDDEN")

    def _path(self, key, *, temporary=False):
        if not isinstance(key, str) or not (TEMP.fullmatch(key) if temporary else KEY.fullmatch(key)):
            raise StorageError("STORAGE_KEY_INVALID")
        if not temporary:
            namespace, _, leaf = key.split("/")
            if LEAVES[namespace] != leaf:
                raise StorageError("STORAGE_KEY_INVALID")
        path = self.root.joinpath(*key.split("/"))
        self._check_components(path)
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise StorageError("STORAGE_KEY_INVALID")
        return path

    @contextmanager
    def open(self, key):
        path = self._path(key)
        if not path.is_file():
            raise StorageError("FILE_MISSING")
        with path.open("rb") as stream:
            yield stream

    def verify(self, key, expected_sha256):
        if not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
            raise StorageError("HASH_INVALID")
        digest = hashlib.sha256()
        size = 0
        with self.open(key) as stream:
            while chunk := stream.read(65536):
                size += len(chunk)
                if size > self.max_bytes:
                    raise StorageError("FILE_TOO_LARGE")
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise StorageError("FILE_INTEGRITY_MISMATCH")
        return StoredObject(key, digest.hexdigest(), size)

    def put(self, stream, *, namespace, object_id=None, validate=None, reuse_identical=False):
        if namespace not in LEAVES or (object_id is not None and not isinstance(object_id, UUID)):
            raise StorageError("STORAGE_KEY_INVALID")
        object_id = object_id or uuid4()
        key = f"{namespace}/{object_id.hex}/{LEAVES[namespace]}"
        temporary_key = f"temporary/{uuid4().hex}/payload.part"
        temporary = self._path(temporary_key, temporary=True)
        final = self._path(key)
        temporary.parent.mkdir(parents=True, exist_ok=False)
        self._check_components(temporary.parent)
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary.open("xb") as destination:
                while True:
                    chunk = stream.read(65536)
                    if not isinstance(chunk, bytes):
                        raise StorageError("BINARY_STREAM_REQUIRED")
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise StorageError("FILE_TOO_LARGE")
                    destination.write(chunk)
                    digest.update(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            if validate is not None:
                validate(temporary)  # Validate complete bytes before making them available.
                self._path(temporary_key, temporary=True)
                # A validator must not silently rewrite the bytes being published.
                with temporary.open("rb") as checked:
                    after = hashlib.file_digest(checked, "sha256").hexdigest()
                if after != digest.hexdigest() or temporary.stat().st_size != size:
                    raise StorageError("VALIDATOR_CHANGED_CONTENT")
            final.parent.mkdir(parents=True, exist_ok=True)
            self._check_components(final)
            try:
                if os.name == "nt":
                    os.rename(temporary, final)  # Windows rename refuses replacement.
                else:
                    os.link(temporary, final)  # Same-volume atomic publish without replacement.
            except FileExistsError:
                if not reuse_identical:
                    raise StorageError("OBJECT_ALREADY_EXISTS") from None
                existing = self.verify(key, digest.hexdigest())
                if existing.byte_size != size:
                    raise StorageError("OBJECT_ALREADY_EXISTS")
                return existing
            if os.name != "nt":
                directory_fd = os.open(final.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return StoredObject(key, digest.hexdigest(), size)
        finally:
            # Delete only this generated temporary file and its empty directory.
            checked = self._path(temporary_key, temporary=True)
            if checked.exists():
                checked.unlink()
            checked.parent.rmdir()
