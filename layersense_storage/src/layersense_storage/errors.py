class ObjectStoreError(RuntimeError):
    """Base error for object-store operations."""


class ObjectNotFoundError(ObjectStoreError):
    """Raised when an object key is not present."""
