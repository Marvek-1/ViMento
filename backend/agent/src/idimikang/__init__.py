"""Observer-only IdimIkang data-source integration."""

from .store import IdimikangEventStore, get_store, normalize_event

__all__ = ["IdimikangEventStore", "get_store", "normalize_event"]
