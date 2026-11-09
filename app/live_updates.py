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


def wake_waiters():
    """Wake cancelled streams without broadcasting a dashboard data change."""
    with _CHANGED:
        _CHANGED.notify_all()


def wait_for_change(previous, timeout=15, stopped=None):
    """Release the condition while waiting; no database connection is held."""
    with _CHANGED:
        _CHANGED.wait_for(lambda: _revision != previous or (stopped is not None and stopped.is_set()), timeout=timeout)
        return _revision
