"""Wake connected dashboards after committed issue or operational changes.

Only an opaque revision travels over the public event stream. Each dashboard
fetches its own normal API response, retaining all existing visibility checks.
"""
import secrets
import threading
import time

_CHANGED = threading.Condition()
_revision = secrets.token_hex(16)
_monitoring_due = 0
MONITORING_COALESCE_SECONDS = 1


def current_revision():
    with _CHANGED:
        return _revision


def publish_dashboard_change():
    """Call after committing SQLite state, never from an open transaction."""
    global _revision, _monitoring_due
    with _CHANGED:
        _revision = secrets.token_hex(16)
        _monitoring_due = 0
        _CHANGED.notify_all()


def publish_monitoring_change():
    """Coalesce committed polling changes without timers or extra threads.

    The first change sets a fixed deadline; later changes cannot postpone it.
    Interactive actions still use publish_dashboard_change for immediate delivery.
    """
    global _revision, _monitoring_due
    with _CHANGED:
        _revision = secrets.token_hex(16)
        now = time.monotonic()
        if _monitoring_due <= now:
            _monitoring_due = now + MONITORING_COALESCE_SECONDS
        _CHANGED.notify_all()


def wake_waiters():
    """Wake cancelled streams without broadcasting a dashboard data change."""
    with _CHANGED:
        _CHANGED.notify_all()


def wait_for_change(previous, timeout=15, stopped=None):
    """Release the condition while waiting; no database connection is held."""
    with _CHANGED:
        deadline = time.monotonic() + timeout
        monitoring_due = None
        while True:
            if stopped is not None and stopped.is_set():
                return _revision
            now = time.monotonic()
            remaining = deadline - now
            if _revision != previous:
                # A new batch arriving as this one expires must not extend an
                # existing listener's deadline under sustained polling changes.
                monitoring_due = _monitoring_due if monitoring_due is None else min(monitoring_due, _monitoring_due)
                remaining = min(remaining, monitoring_due - now)
            if remaining <= 0:
                return _revision
            _CHANGED.wait(remaining)
