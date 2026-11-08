"""Wake connected dashboards after committed issue or operational changes.

Only an opaque revision travels over the public event stream. Each dashboard
fetches its own normal API response, retaining all existing visibility checks.
"""
import secrets
import threading

_CHANGED = threading.Condition()
_revision = secrets.token_hex(16)


def current_revision():
    with _CHANGED:
        return _revision


def publish_dashboard_change():
    """Call after committing SQLite state, never from an open transaction."""
    global _revision
    with _CHANGED:
        _revision = secrets.token_hex(16)
        _CHANGED.notify_all()


def wait_for_change(previous, timeout=15):
    """Release the condition while waiting; no database connection is held."""
    with _CHANGED:
        _CHANGED.wait_for(lambda: _revision != previous, timeout=timeout)
        return _revision
