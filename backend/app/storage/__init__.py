"""Private immutable object storage; never mounted as a static web directory."""
from .local import LocalStorage, StoredObject, StorageError

__all__ = ["LocalStorage", "StoredObject", "StorageError"]
