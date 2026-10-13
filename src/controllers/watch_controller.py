"""M5 Watch Folder Controller — lifecycle management for folder watches.

- add_watch auto-starts monitoring (GAP-035 fix)
- pause/resume/remove lifecycle
- Debounce (2s stable wait, resets on file change)
- Temp file filtering
- Observer exception backoff with max retry
- Cancel/stop semantics (no stale callbacks)
- Error messages use reason codes, not full paths

No real watchdog daemon in tests; injectable observer, clock, scheduler.
"""

from __future__ import annotations

import os
import re
import stat
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

from src.core.rename_plan import SourceFingerprint
from src.core.watch_work import StableWatchEvent, WatchAdmission, WatchAdmissionFailure, valid_admission_fields

from src.core.watch_config import (
    WatchConfig,
    WatchConfigStore,
    WatchConfigPersistenceError,
    WatchMode,
    WatchStatus,
)


# ── Errors ─────────────────────────────────────────────────────────────────────

class WatchControllerError(RuntimeError):
    """Raised for controller-level errors. Messages contain reason codes, not full paths."""


# ── File Event Types ───────────────────────────────────────────────────────────

class WatchBindingState(Enum):
    STALE = "stale"
    HELD = "held"
    READY = "ready"


class FileEvent(Enum):
    CREATED = auto()
    MODIFIED = auto()
    DELETED = auto()
    MOVED = auto()


# ── Temp File Patterns ─────────────────────────────────────────────────────────

# Extensions and prefixes for temporary/incomplete files that must be filtered
_TEMP_EXTENSIONS = {".tmp", ".part", ".crdownload", ".download"}
_TEMP_PREFIX = "~$"

# Regex for temp detection (case-insensitive extension match)
_TEMP_EXT_RE = re.compile(
    r"\.(tmp|part|crdownload|download)$", re.IGNORECASE
)


def is_temp_file(filename: str) -> bool:
    """Check if a filename indicates a temporary or incomplete file.

    Filters: .tmp, .part, .crdownload, .download extensions,
    and ~$ prefix (Office lock files).
    """
    basename = os.path.basename(filename)
    if basename.startswith(_TEMP_PREFIX):
        return True
    if _TEMP_EXT_RE.search(basename):
        return True
    return False


# ── Clocks & Schedulers (Injectable) ───────────────────────────────────────────

class FakeClock:
    """Injectable clock for deterministic testing."""

    def __init__(self, start: float = 0.0):
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds

    @property
    def now(self) -> float:
        return self._now


class FakeScheduler:
    """Injectable scheduler that runs callbacks when clock advances."""

    def __init__(self, clock: FakeClock):
        self._clock = clock
        self._pending: list[tuple[float, Callable[[], None], str]] = []  # (fire_time, callback, id)
        self._callbacks = 0

    def schedule(self, delay_seconds: float, callback: Callable[[], None],
                 task_id: str = "") -> str:
        """Schedule a callback after delay_seconds."""
        fire_time = self._clock.now + delay_seconds
        tid = task_id or str(id(callback))
        self.cancel(tid)
        self._pending.append((fire_time, callback, tid))
        # Sort by fire time
        self._pending.sort(key=lambda x: x[0])
        return tid

    def cancel(self, task_id: str) -> None:
        """Cancel a scheduled task by ID."""
        self._pending = [(t, cb, tid) for t, cb, tid in self._pending if tid != task_id]

    def cancel_all(self) -> None:
        """Cancel all pending tasks."""
        self._pending.clear()

    def run_pending(self) -> int:
        """Run all callbacks whose time has come. Returns count of executed callbacks."""
        now = self._clock.now
        ready = [(t, cb, tid) for t, cb, tid in self._pending if t <= now]
        self._pending = [(t, cb, tid) for t, cb, tid in self._pending if t > now]
        for _, cb, tid in ready:
            self._callbacks += 1
            try:
                cb()
            except Exception:
                pass
            finally:
                self._callbacks -= 1
        return len(ready)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def workers_idle(self) -> bool:
        return not self._pending and self._callbacks == 0

    def drain(self, deadline: float) -> bool:
        return self.workers_idle


class DebounceScheduler:
    """Production scheduler using threading.Timer."""

    def __init__(self):
        self._timers = {}
        self._owned = set()
        self._lock = threading.Lock()
        self._callbacks = 0

    def schedule(self, delay_seconds: float, callback: Callable[[], None],
                 task_id: str = "") -> str:
        tid = task_id or str(id(callback))
        token = object()
        timer = threading.Timer(delay_seconds, self._on_fire, args=[tid, token, callback])
        timer.daemon = True
        with self._lock:
            self._prune_owned_locked()
            previous = self._timers.get(tid)
            if previous is not None:
                previous[1].cancel()
            self._timers[tid] = (token, timer)
            self._owned.add(timer)
            # Installed before start, so an immediate callback can only claim its own token.
            try:
                timer.start()
            except Exception:
                self._timers.pop(tid, None)
                self._owned.discard(timer)
                raise
        return tid

    def cancel(self, task_id: str) -> None:
        with self._lock:
            self._prune_owned_locked()
            pair = self._timers.pop(task_id, None)
            if pair is not None:
                pair[1].cancel()

    def cancel_all(self) -> None:
        with self._lock:
            self._prune_owned_locked()
            scheduled = list(self._timers.values())
            self._timers.clear()
            for _, timer in scheduled:
                timer.cancel()

    def _on_fire(self, task_id: str, token: object, callback: Callable[[], None]) -> None:
        with self._lock:
            self._prune_owned_locked()
            pair = self._timers.get(task_id)
            if pair is None or pair[0] is not token:
                return
            self._timers.pop(task_id)
            self._callbacks += 1
        try:
            callback()
        except Exception:
            pass
        finally:
            with self._lock:
                self._callbacks -= 1
                self._prune_owned_locked()
            # The actual Timer remains strongly owned through this callback's tail.

    @property
    def workers_idle(self) -> bool:
        with self._lock:
            self._prune_owned_locked()
            return not self._owned and not self._timers and self._callbacks == 0

    def _prune_owned_locked(self):
        # ident=None is not proof of exit: installation precedes Timer.start.
        self._owned = {timer for timer in self._owned
                       if timer.ident is None or timer.is_alive()}

    def drain(self, deadline: float) -> bool:
        while not self.workers_idle:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(.005, remaining))
        return True


# ── Mock Observer (Test Double) ────────────────────────────────────────────────

class MockObserver:
    """Controllable mock for testing — no real watchdog daemon."""

    def __init__(self):
        self.handlers: dict[str, Any] = {}       # path → handler
        self.running: bool = False
        self.always_fail: bool = False
        self.scheduled_paths: list[str] = []
        self.unscheduled_paths: list[str] = []

    def schedule(self, handler: Any, path: str, recursive: bool = True) -> None:
        if self.always_fail:
            raise RuntimeError("MockObserver: simulated schedule failure")
        self.handlers[path] = handler
        self.scheduled_paths.append(path)

    def unschedule(self, handler: Any) -> None:
        for path, h in list(self.handlers.items()):
            if h is handler:
                del self.handlers[path]
                self.unscheduled_paths.append(path)

    def unschedule_all(self) -> None:
        self.handlers.clear()

    def start(self) -> None:
        if self.always_fail:
            raise RuntimeError("MockObserver: simulated start failure")
        self.running = True

    def stop(self) -> None:
        self.running = False

    def join(self, timeout: float = 0) -> None:
        self.stop()

    def is_alive(self) -> bool:
        return self.running

    def simulate_event(self, path: str, event_type: FileEvent) -> None:
        """Simulate a file event, calling the registered handler."""
        for handler_path, handler in self.handlers.items():
            # Check if path is under handler_path
            try:
                Path(path).relative_to(Path(handler_path))
                if hasattr(handler, 'on_file_event'):
                    handler.on_file_event(path, event_type)
                elif hasattr(handler, 'dispatch'):
                    handler.dispatch(path, event_type)
                break
            except ValueError:
                continue


# ── Observer Factory ───────────────────────────────────────────────────────────

class ObserverFactory:
    """Creates observer instances. In tests, use mock observers. In production, creates watchdog observers."""

    def __init__(self, use_mock: bool = False):
        self._use_mock = use_mock
        self._created: list[MockObserver] = []
        self.always_fail: bool = False

    def create(self) -> Any:
        """Create an observer. Returns MockObserver in test mode, real watchdog Observer in production."""
        if self._use_mock:
            obs = MockObserver()
            obs.always_fail = self.always_fail
            self._created.append(obs)
            return obs
        else:
            # Production: use watchdog
            try:
                from watchdog.observers import Observer
                obs = Observer()
                self._created.append(obs)
                return obs
            except ImportError:
                raise WatchControllerError(
                    "watchdog_not_installed",
                )

    @property
    def created_observers(self) -> list:
        return list(self._created)


# ── Internal Watch State ───────────────────────────────────────────────────────

@dataclass
class _WatchState:
    """Internal runtime state for one active watch."""
    config: WatchConfig
    observer: Any = None
    handler: Any = None
    retry_count: int = 0
    pending_debounce_id: str = ""
    pending_retry_id: str = ""
    retry_token: object | None = None
    incarnation: str = field(default_factory=lambda: uuid4().hex)
    starting: bool = False
    installation: _ObserverOwner | None = None


@dataclass(eq=False)
class _ObserverOwner:
    watch_id: str
    incarnation: str
    observer: Any
    starting: bool = True
    emitters: tuple = ()
    teardown_thread: threading.Thread | None = None
    teardown_starting: bool = False
    teardown_required: bool = False
    teardown_complete: bool = False


@dataclass(eq=False)
class _StartAttempt:
    incarnation: str


@dataclass(eq=False)
class _DebounceEntry:
    config: WatchConfig
    incarnation: str
    path: str
    token: object = field(default_factory=object)
    admission: Any = None
    task_id: str = ""
    fingerprint: SourceFingerprint | None = None
    claimed: bool = False


# ── File Event Handler (Internal) ──────────────────────────────────────────────

class _WatchEventHandler:
    """Internal event handler that feeds events to the controller."""

    def __init__(self, config_id: str, controller: WatchController, incarnation: str | None = None):
        self.config_id = config_id
        self.controller = controller
        self.incarnation = incarnation

    def on_file_event(self, path: str, event_type: FileEvent) -> None:
        if self.incarnation is None:
            self.controller._on_raw_file_event(self.config_id, path, event_type)
        else:
            self.controller._on_raw_file_event(self.config_id, path, event_type,
                                               incarnation=self.incarnation)

    def dispatch(self, event) -> None:
        """watchdog-compatible dispatch."""
        if event.is_directory:
            return
        event_type = getattr(event, "event_type", "created")
        path = (
            getattr(event, "dest_path", event.src_path)
            if event_type == "moved"
            else event.src_path
        )
        if hasattr(event, 'event_type'):
            etype = {
                'created': FileEvent.CREATED,
                'modified': FileEvent.MODIFIED,
                'deleted': FileEvent.DELETED,
                'moved': FileEvent.MOVED,
            }.get(event.event_type, FileEvent.CREATED)
        else:
            etype = FileEvent.CREATED
        self.on_file_event(path, etype)


# ── WatchController ────────────────────────────────────────────────────────────

class WatchController:
    """Manages watch lifecycle: add, pause, resume, remove, start_all, stop_all.

    All external dependencies (observer, clock, scheduler) are injectable
    for deterministic testing without background watchdog daemons.
    """

    DEFAULT_DEBOUNCE_SECONDS = 2.0
    DEFAULT_BACKOFF_BASE = 2.0
    DEFAULT_MAX_RETRIES = 5

    def __init__(
        self,
        config_store: WatchConfigStore,
        observer_factory: ObserverFactory | None = None,
        clock: Callable[[], float] | None = None,
        scheduler: Any = None,
        debounce_seconds: float | None = None,
        backoff_base: float | None = None,
        max_retries: int | None = None,
        recovery_errors: dict | None = None,
        review_first_handler: Any = None,
        auto_apply_handler: Any = None,
        resource_guard: Any = None,
        *,
        managed_ingress: Any = None,
        autostart: bool = True,
        self_events: Any = None,
    ):
        self._recovery_errors: dict = recovery_errors if recovery_errors is not None else {}
        self._store = config_store
        self._observer_factory = observer_factory or ObserverFactory(use_mock=False)
        self._clock = clock or time.monotonic
        self._debounce_seconds = debounce_seconds if debounce_seconds is not None else self.DEFAULT_DEBOUNCE_SECONDS
        self._backoff_base = backoff_base if backoff_base is not None else self.DEFAULT_BACKOFF_BASE
        self._max_retries = max_retries if max_retries is not None else self.DEFAULT_MAX_RETRIES
        # Pipeline handlers (M5 pipelines): dispatched by watch mode.
        self._review_first_handler = review_first_handler
        self._auto_apply_handler = auto_apply_handler
        # Resource gate (WatchResourceGuard): RESOURCE_PAUSED watches may
        # only be re-activated after the guard confirms recovery.
        self._resource_guard = resource_guard
        self._managed_ingress = managed_ingress
        self._self_events = self_events
        self._autostart = autostart
        self._closed = False
        self._stopped = not autostart

        # Scheduler: use injected or create production one
        self._scheduler = scheduler
        if self._scheduler is None:
            self._scheduler = DebounceScheduler()

        # Active watches
        self._watches: dict[str, _WatchState] = {}
        self._lock = threading.RLock()
        self._observer_owners: dict[int, _ObserverOwner] = {}
        self._starting_count = 0
        self._start_reservations = {}
        self._event_callbacks = 0

        # Exact entry identities are fenced by both timer token and observer incarnation.
        self._pending_debounce: dict[tuple[str, str], _DebounceEntry] = {}

        # Callback for file-ready events (injectable for testing)
        self.on_file_ready: Callable[[str, str], None] = lambda config_id, file_path: None

        # Load stored configs and restore state
        self._restore_stored_configs()

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def debounce_seconds(self) -> float:
        return self._debounce_seconds

    # ── Public API ─────────────────────────────────────────────────────────────

    @staticmethod
    def _managed_binding_key(config):
        return (config.id, config.source_dir, config.target_dir,
                config.template_id, config.recursive, config.mode)

    def managed_binding_state(self, event) -> WatchBindingState:
        """Pure current installation/policy query; no filesystem or inference."""
        ingress = self._managed_ingress
        if ingress is None or type(event) not in (StableWatchEvent, WatchAdmissionFailure):
            return WatchBindingState.STALE
        # Never enter ingress/authority callbacks while holding the Watch lock.
        try:
            if not ingress.is_current(event):
                return WatchBindingState.STALE
        except Exception:
            return WatchBindingState.STALE
        admitted = event.admission if type(event) is StableWatchEvent else event
        with self._lock:
            state = self._watches.get(admitted.watch_id)
            if (self._closed or self._stopped or state is None
                    or state.incarnation != admitted.incarnation
                    or state.config.status not in
                        (WatchStatus.ACTIVE, WatchStatus.RESOURCE_PAUSED)
                    or self._managed_binding_key(state.config)
                        != self._managed_binding_key(admitted.watch_config)):
                return WatchBindingState.STALE
            if state.starting:
                return (WatchBindingState.HELD
                        if self._start_reservations.get(admitted.incarnation) == admitted.watch_id
                        else WatchBindingState.STALE)
            installed = state.installation
            if (installed is None or state.observer is not installed.observer
                    or installed.incarnation != admitted.incarnation
                    or self._observer_owners.get(id(installed.observer)) is not installed
                    or installed.teardown_required or installed.teardown_starting
                    or installed.teardown_complete):
                return WatchBindingState.STALE
            if state.config.status is WatchStatus.RESOURCE_PAUSED:
                return WatchBindingState.HELD
            return WatchBindingState.READY

    def add_watch(self, config: WatchConfig) -> None:
        """Add a watch config and auto-start monitoring (GAP-035 fix).

        Raises WatchControllerError on duplicate ID.
        """
        with self._lock:
            if self._closed:
                raise WatchControllerError("closed")
            if config.id in self._watches:
                raise WatchControllerError(f"Watch already exists: {config.id}")

            # Persist
            try:
                self._store.add(config)
            except WatchConfigPersistenceError as e:
                raise WatchControllerError(f"Failed to persist watch config: {e}")

            # Create runtime state
            state = _WatchState(config=config)
            self._watches[config.id] = state
            attempt = _StartAttempt(state.incarnation)

        if not self._stopped and config.status == WatchStatus.ACTIVE:
            try:
                self._start_observer(config.id, state, expected_config=config, attempt=attempt)
            except Exception:
                self._record_start_failure(config.id, state, config, attempt)

    def pause_watch(self, config_id: str) -> None:
        """Pause a watch — stops observer, updates status to PAUSED.

        Raises WatchControllerError if not found.
        """
        with self._lock:
            state = self._get_state(config_id)
            updated = state.config.with_status(WatchStatus.PAUSED)

            # Persist first.  A write failure leaves the running observer and
            # in-memory status untouched.
            self._store.update(updated)
            observer = self._detach_observer_locked(state)
            self._cancel_debounce_for_watch(config_id)
            self._cancel_retry(config_id)
            state.retry_count = 0
            state.config = updated
        self._stop_owned_observer(observer)

    def resume_watch(self, config_id: str) -> None:
        """Resume a paused watch — restarts observer, updates status to ACTIVE.

        Also resumes from ERROR / RESOURCE_PAUSED; the pipeline handler is
        told to re-process its held items (safe recovery, no duplicates).

        A RESOURCE_PAUSED watch is only re-activated after the resource
        guard confirms recovery (``guard.recover``).  Until then the status
        stays RESOURCE_PAUSED and the observer keeps collecting, so held
        files are never lost.  Without an injected guard the plain resume
        path applies (backward compatible).

        Raises WatchControllerError if not found.
        """
        with self._lock:
            if self._closed:
                raise WatchControllerError("closed")
            state = self._get_state(config_id)
            original = state.config
        if original.status == WatchStatus.RESOURCE_PAUSED:
            if self._resource_guard is None or not self._resource_guard.recover(config_id):
                return
        with self._lock:
            if self._watches.get(config_id) is not state or state.config is not original:
                return
            if state.config.status == WatchStatus.ACTIVE:
                observer = state.observer
                if observer is not None and (
                    not hasattr(observer, "is_alive") or observer.is_alive()
                ):
                    return
            elif state.config.status not in (WatchStatus.PAUSED, WatchStatus.ERROR, WatchStatus.RESOURCE_PAUSED):
                return
            updated = state.config.with_status(WatchStatus.ACTIVE)
            attempt = _StartAttempt(state.incarnation)
        installation = self._start_observer(config_id, state, expected_config=original, attempt=attempt)
        if installation is None:
            return
        failed = None
        persistence_error = False
        with self._lock:
            if not self._installation_current_locked(config_id, state, original, installation):
                return
            try:
                self._store.update(updated)
            except Exception:
                persistence_error = True
                if self._installation_current_locked(config_id, state, original, installation):
                    failed = self._detach_observer_locked(state)
            else:
                state.config = updated
                self._cancel_retry(config_id)
                state.retry_count = 0
        if persistence_error:
            self._stop_owned_observer(failed)
            raise WatchControllerError("watch_config_update_failed") from None
        self._notify_resumed(config_id)

    def update_watch(self, config: WatchConfig) -> None:
        """Replace a paused watch configuration transactionally.

        Editing an active or resource-paused watch is rejected.  Callers must
        pause first so no observer can race the persisted configuration.  The
        store writes its candidate snapshot before this controller swaps the
        live state, so a save failure leaves both layers unchanged.
        """
        with self._lock:
            state = self._get_state(config.id)
            if state.config.status is not WatchStatus.PAUSED:
                raise WatchControllerError("watch_must_be_paused_before_update")
            if config.status is not WatchStatus.PAUSED:
                raise WatchControllerError("updated_watch_must_remain_paused")
            if state.observer is not None:
                raise WatchControllerError("observer_must_be_stopped_before_update")
            try:
                self._store.update(config)
            except Exception as error:
                raise WatchControllerError("watch_config_update_failed") from error
            self._cancel_debounce_for_watch(config.id)
            self._cancel_retry(config.id)
            state.incarnation = uuid4().hex
            state.config = config

    def resource_pause(self, config_id: str) -> None:
        """Mark a watch RESOURCE_PAUSED (non-monetary resource protection).

        The observer keeps running so files arriving while paused are still
        collected and held by the pipeline — nothing is lost.
        """
        with self._lock:
            state = self._get_state(config_id)
            if state.config.status == WatchStatus.RESOURCE_PAUSED:
                return
            updated = state.config.with_status(WatchStatus.RESOURCE_PAUSED)
            self._store.update(updated)
            state.config = updated
            self._cancel_retry(config_id)

    def _notify_resumed(self, config_id: str) -> None:
        if self._managed_ingress is not None:
            return
        for handler in (self._review_first_handler, self._auto_apply_handler):
            if handler is not None and hasattr(handler, "on_watch_resumed"):
                try:
                    handler.on_watch_resumed(config_id)
                except Exception:
                    pass

    def remove_watch(self, config_id: str) -> None:
        """Remove a watch — stops observer, removes config from store.

        NEVER deletes user files, target directories, templates, or undo history.

        Raises WatchControllerError if not found.
        """
        with self._lock:
            state = self._get_state(config_id)

            # Persist removal before stopping runtime state.  A write failure
            # therefore leaves the watch fully active and recoverable.
            self._store.remove(config_id)
            observer = self._detach_observer_locked(state)
            self._cancel_debounce_for_watch(config_id)
            self._cancel_retry(config_id)
            del self._watches[config_id]
        self._stop_owned_observer(observer)

        # Notify the pipeline handler: unapplied review items follow the
        # edit-impact policy (cancelled); files and history stay untouched.
        for handler in (() if self._managed_ingress is not None else
                        (self._review_first_handler, self._auto_apply_handler)):
            if handler is not None and hasattr(handler, "on_watch_removed"):
                try:
                    handler.on_watch_removed(config_id)
                except Exception:
                    pass

    def start_all(self) -> None:
        """Start observers for all Active configs."""
        with self._lock:
            if self._closed:
                return
            self._stopped = False
            candidates = [(cid, state, state.config) for cid, state in self._watches.items()
                          if state.config.status == WatchStatus.ACTIVE]
        for cid, state, config in candidates:
            self._start_observer(cid, state, expected_config=config)

    def stop_all(self) -> None:
        """Stop all observers and cancel all pending timers/debounce."""
        with self._lock:
            self._stopped = True
            observers = []
            for config_id, state in self._watches.items():
                self._cancel_retry(config_id)
                observers.append(self._detach_observer_locked(state))
                self._cancel_debounce_for_watch(config_id)
            # Cancel all pending debounce
            if hasattr(self._scheduler, 'cancel_all'):
                self._scheduler.cancel_all()
            self._pending_debounce.clear()
        for observer in observers:
            self._stop_owned_observer(observer)

    def is_watching(self, config_id: str) -> bool:
        """Check if a config ID is currently managed."""
        with self._lock:
            return config_id in self._watches

    def get_status(self, config_id: str) -> WatchStatus:
        """Get the current status of a watch.

        Raises WatchControllerError if not found.
        """
        with self._lock:
            return self._get_state(config_id).config.status

    def get_config(self, config_id: str) -> WatchConfig:
        """Get the current config for a watch.

        Raises WatchControllerError if not found.
        """
        with self._lock:
            return self._get_state(config_id).config

    def list_configs(self) -> list[WatchConfig]:
        """Return an immutable snapshot of all managed watch configs."""
        with self._lock:
            return [state.config for state in self._watches.values()]

    def restart_after_failure(self, config_id: str, *, retry_token: object | None = None) -> None:
        """Attempt to restart a watch after observer failure.

        Called by the backoff scheduler; implements exponential backoff.
        """
        with self._lock:
            if self._closed or self._stopped or config_id not in self._watches:
                return
            state = self._watches[config_id]
            # A dispatched Timer may outlive cancellation, or even a newer
            # failure of the same watch. Only its original retry can run.
            if retry_token is not None and retry_token is not state.retry_token:
                return
            if state.config.status is not WatchStatus.ERROR:
                return
            self._cancel_retry(config_id)
            if state.retry_count >= self._max_retries:
                # Stay in ERROR, don't retry further
                return

            state.retry_count += 1
            original = state.config
            attempt = _StartAttempt(state.incarnation)
        installation = None
        try:
            installation = self._start_observer(config_id, state, expected_config=original, attempt=attempt)
            if installation is None:
                return
            with self._lock:
                if not self._installation_current_locked(config_id, state, original, installation):
                    return
                updated = state.config.with_status(WatchStatus.ACTIVE)
                self._store.update(updated)
                state.config = updated
                state.retry_count = 0
        except Exception:
            with self._lock:
                if installation is not None:
                    if not self._installation_current_locked(config_id, state, original, installation):
                        return
                    observer = self._detach_observer_locked(state)
                else:
                    if not self._start_failure_current_locked(config_id, state, original, attempt):
                        return
                    observer = None  # failed start owns its exact created observer's cleanup
                if state.retry_count < self._max_retries:
                    delay = self._backoff_base * (2 ** (state.retry_count - 1))
                    self._schedule_retry(config_id, delay)
            self._stop_owned_observer(observer)

    # ── Internal: Observer Management ──────────────────────────────────────────

    def _start_observer(self, config_id: str, state: _WatchState, *, expected_config=None,
                        attempt=None) -> _ObserverOwner | None:
        """Create and start an observer for a watch. Raises on failure."""
        with self._lock:
            if (self._closed or self._stopped or self._watches.get(config_id) is not state
                    or (expected_config is not None and state.config is not expected_config)):
                return None
            if attempt is None:
                attempt = _StartAttempt(state.incarnation)
            if state.incarnation != attempt.incarnation or state.starting:
                return None
            previous_observer = None
            if state.observer is not None and not state.observer.is_alive():
                previous_observer = self._detach_observer_locked(state)
                self._cancel_debounce_for_watch(config_id)
                attempt.incarnation = state.incarnation
        # Dispatcher exit alone is not emitter exit or completed teardown.
        # Queue cleanup before checking replacement eligibility, outside this lock.
        self._stop_owned_observer(previous_observer)
        with self._lock:
            if self._closed or self._stopped or self._watches.get(config_id) is not state:
                return None
            if expected_config is not None and state.config is not expected_config:
                return None
            if attempt is None:
                attempt = _StartAttempt(state.incarnation)
            if state.incarnation != attempt.incarnation:
                return None
            if state.starting:
                return None
            if state.observer is not None and state.observer.is_alive():
                return state.installation
            self._prune_observers_locked()
            if (config_id in self._start_reservations.values()
                    or any(owner.watch_id == config_id for owner in self._observer_owners.values())):
                raise WatchControllerError("observer_retiring")
            retired_observer = self._detach_observer_locked(state)
            self._cancel_debounce_for_watch(config_id)
            state.starting = True
            state.incarnation = incarnation = uuid4().hex
            attempt.incarnation = incarnation
            original = state.config
            self._starting_count += 1
            self._start_reservations[incarnation] = config_id
        observer = owner = None
        invalidated = False
        try:
            self._stop_owned_observer(retired_observer)
            observer = self._observer_factory.create()
            owner = _ObserverOwner(config_id, incarnation, observer)
            handler = _WatchEventHandler(config_id, self, incarnation)
            with self._lock:
                self._observer_owners[id(observer)] = owner
                invalidated = (self._closed or self._stopped or self._watches.get(config_id) is not state
                               or state.incarnation != incarnation or state.config is not original)
            if invalidated:
                return None
            observer.schedule(handler, original.source_dir, recursive=original.recursive)
            emitters = tuple(getattr(observer, "emitters", ()))
            with self._lock:
                owner.emitters = emitters
            observer.start()
            with self._lock:
                invalidated = (self._closed or self._stopped or self._watches.get(config_id) is not state
                               or state.incarnation != incarnation or state.config is not original)
                if not invalidated:
                    state.observer = observer
                    state.handler = handler
                    state.installation = owner
            return owner if not invalidated else None
        except Exception:
            invalidated = True
            with self._lock:
                if state.incarnation == incarnation:
                    self._detach_observer_locked(state)
                    self._cancel_debounce_for_watch(config_id)
                    attempt.incarnation = state.incarnation
            raise
        finally:
            # Stop outside the controller lock: watchdog may be entering its handler.
            if invalidated:
                self._stop_owned_observer(observer)
            with self._lock:
                if owner is not None:
                    owner.starting = False
                state.starting = False
                self._starting_count -= 1
                self._start_reservations.pop(incarnation, None)

    def _detach_observer_locked(self, state: _WatchState):
        observer = state.observer
        owner = state.installation
        if owner is not None:
            # An actually exited owner may have been reaped while the live state
            # still held its exact installation. Cleanup becomes owned before
            # detachment; idle polling cannot discard the pending teardown gap.
            owner.teardown_required = True
            self._observer_owners[id(observer)] = owner
        state.observer = None
        state.handler = None
        state.installation = None
        if self._managed_ingress is not None:
            self._managed_ingress.cancel_incarnation(state.config.id, state.incarnation)
        state.incarnation = uuid4().hex
        return observer

    def _stop_owned_observer(self, observer) -> None:
        if observer is None:
            return
        with self._lock:
            owner = self._observer_owners[id(observer)]
            if owner.teardown_thread is not None or owner.teardown_starting:
                return
            owner.teardown_starting = owner.teardown_required = True

        def teardown():
            # Real watchdog unschedule_all AND stop may synchronously join emitters.
            # This worker owns that wait; the lifecycle/Qt caller never performs it.
            completed = True
            try:
                observer.unschedule_all()
            except Exception:
                completed = False
            try:
                observer.stop()
            except Exception:
                completed = False
            finally:
                with self._lock:
                    owner.teardown_complete = completed
                    owner.teardown_required = not completed

        if type(observer) is MockObserver:
            # Only this exact, explicit pure adapter has a known nonblocking contract.
            # Subclasses and real/unknown observers always use an owned worker.
            try:
                teardown()
            finally:
                with self._lock:
                    owner.teardown_starting = False
            return
        thread = threading.Thread(target=teardown,
                                  name="watch-observer-retirement", daemon=True)
        with self._lock:
            owner.teardown_thread = thread
        try:
            thread.start()
        finally:
            with self._lock:
                owner.teardown_starting = False

    def _prune_observers_locked(self):
        self._observer_owners = {key: owner for key, owner in self._observer_owners.items()
                                if (owner.starting or owner.teardown_starting or owner.teardown_required
                                    or not owner.teardown_complete
                                    or (owner.teardown_thread is not None and owner.teardown_thread.is_alive())
                                    or owner.observer.is_alive()
                                    or any(emitter.is_alive() for emitter in owner.emitters))}

    def _installation_current_locked(self, config_id, state, config, installation):
        return (not self._closed and not self._stopped
                and self._watches.get(config_id) is state and state.config is config
                and state.installation is installation and state.observer is installation.observer
                and state.incarnation == installation.incarnation
                and not installation.starting and not installation.teardown_required
                and installation.observer.is_alive())

    def _start_failure_current_locked(self, config_id, state, config, attempt):
        return (not self._closed and not self._stopped
                and self._watches.get(config_id) is state and state.config is config
                and state.incarnation == attempt.incarnation
                and not state.starting and state.observer is None and state.installation is None)

    def _record_start_failure(self, config_id, state, expected_config, attempt):
        with self._lock:
            if not self._start_failure_current_locked(config_id, state, expected_config, attempt):
                return
            updated = state.config.with_status(WatchStatus.ERROR)
            try:
                self._store.update(updated)
            except Exception:
                pass
            state.config = updated
            self._schedule_retry(config_id, self._backoff_base)

    def _schedule_retry(self, config_id: str, delay: float) -> None:
        """Schedule a retry attempt after delay seconds."""
        self._cancel_retry(config_id)
        state = self._watches.get(config_id)
        if self._closed or self._stopped or state is None or state.config.status is not WatchStatus.ERROR:
            return
        token = object()
        state.retry_token = token

        def _retry():
            self.restart_after_failure(config_id, retry_token=token)

        tid = self._scheduler.schedule(delay, _retry, task_id=f"retry_{config_id}")
        state.pending_retry_id = tid

    def _cancel_retry(self, config_id: str) -> None:
        """Cancel pending retry for a watch."""
        state = self._watches.get(config_id)
        if state is not None:
            state.retry_token = None
            state.pending_retry_id = ""
        if hasattr(self._scheduler, 'cancel'):
            self._scheduler.cancel(f"retry_{config_id}")

    # ── Internal: File Event Handling ──────────────────────────────────────────

    def _on_raw_file_event(self, config_id: str, file_path: str, event_type: FileEvent,
                           *, incarnation: str | None = None) -> None:
        with self._lock:
            if self._closed:
                return
            self._event_callbacks += 1
        try:
            self._admit_raw_file_event(config_id, file_path, event_type, incarnation=incarnation)
        finally:
            with self._lock:
                self._event_callbacks -= 1

    def _admit_raw_file_event(self, config_id, file_path, event_type, *, incarnation=None):
        """Handle a raw file event from the observer. Applies filtering and debounce."""
        if type(file_path) is not str or len(file_path) > 32768 or is_temp_file(file_path):
            return

        # Skip if watch is not collecting events.  RESOURCE_PAUSED keeps
        # collecting so files arriving while paused are held, never lost.
        with self._lock:
            if self._closed or self._stopped or config_id not in self._watches:
                return
            state = self._watches[config_id]
            if state.config.status not in (WatchStatus.ACTIVE, WatchStatus.RESOURCE_PAUSED):
                return
            if incarnation is not None and incarnation != state.incarnation:
                return
            config, incarnation = state.config, state.incarnation
            event_id = uuid4().hex
            if not valid_admission_fields(config, incarnation, file_path, event_id):
                return
            key = (config_id, os.path.normcase(os.path.normpath(file_path)))
            if event_type is FileEvent.DELETED:
                old = self._pending_debounce.pop(key, None)
                self._retire_entry_locked(old)
                return
            if event_type not in (FileEvent.CREATED, FileEvent.MODIFIED, FileEvent.MOVED):
                return
        # Capture first, on the admitting thread, with no controller/catalog inversion.
        admission = None
        if self._managed_ingress is not None:
            admission = self._managed_ingress.capture(config, incarnation, file_path, event_id)
            if admission is None:
                return
        elif os.path.isdir(file_path):
            return
        entry = _DebounceEntry(config, incarnation, file_path, admission=admission,
                               task_id="debounce_" + event_id)
        with self._lock:
            if (self._closed or self._stopped or self._watches.get(config_id) is not state
                    or state.config is not config or state.incarnation != incarnation):
                self._retire_entry_locked(entry)
                return
            old = self._pending_debounce.get(key)
            self._retire_entry_locked(old)
            self._pending_debounce[key] = entry
        if type(admission) is WatchAdmissionFailure:
            # Private failure callback only; never run the legacy pipeline on this thread.
            with self._lock:
                current = self._pending_debounce.get(key) is entry
                if current:
                    self._pending_debounce.pop(key)
            if current:
                if not self._managed_ingress.post_failure(admission):
                    self._managed_ingress.retire(admission)
            return
        self._schedule_entry(key, entry)
        return admission

    def _schedule_entry(self, key, entry):
        self._scheduler.schedule(self._debounce_seconds,
            lambda: self._on_debounce_ready(entry.config.id, entry.path, token=entry.token,
                                             incarnation=entry.incarnation), task_id=entry.task_id)
        with self._lock:
            if self._pending_debounce.get(key) is not entry:
                self._scheduler.cancel(entry.task_id)

    def retry_file(self, config_id, file_path, extension):
        """New explicit current admission, never reconstructed persisted work."""
        if self._managed_ingress is None or os.path.splitext(file_path)[1] != extension:
            return None
        key = (config_id, os.path.normcase(os.path.normpath(file_path)))
        with self._lock:
            state = self._watches.get(config_id)
            if (self._closed or self._stopped or state is None or state.starting
                    or state.config.status is not WatchStatus.ACTIVE
                    or state.installation is None or key in self._pending_debounce):
                return None
            incarnation = state.incarnation
        admission = self._admit_raw_file_event(config_id, file_path, FileEvent.CREATED,
                                              incarnation=incarnation)
        return admission if type(admission) is WatchAdmission else None

    def cancel_retry_admission(self, admission):
        with self._lock:
            for key, entry in tuple(self._pending_debounce.items()):
                if entry.admission is admission:
                    self._pending_debounce.pop(key)
                    self._retire_entry_locked(entry)
                    return True
        return False

    def self_event_held(self, config_id):
        with self._lock:
            return any(entry.config.id == config_id and getattr(entry, "self_held", False)
                       for entry in self._pending_debounce.values())

    def _entry_current_locked(self, entry):
        state = self._watches.get(entry.config.id)
        return (not self._closed and not self._stopped and state is not None
                and state.incarnation == entry.incarnation
                and state.config.status in (WatchStatus.ACTIVE, WatchStatus.RESOURCE_PAUSED))

    def _on_debounce_ready(self, config_id: str, file_path: str, *, token=None,
                           incarnation=None) -> None:
        """Called when debounce period expires and file is considered stable."""
        key = (config_id, os.path.normcase(os.path.normpath(file_path)))
        with self._lock:
            entry = self._pending_debounce.get(key)
            if (entry is None or token is not entry.token or incarnation != entry.incarnation
                    or entry.claimed or not self._entry_current_locked(entry)):
                return
            entry.claimed = True
        if self._self_events is not None:
            decision = self._self_events.decision(file_path)
            with self._lock:
                if self._pending_debounce.get(key) is not entry or not self._entry_current_locked(entry):
                    self._retire_entry_locked(entry)
                    return
                entry.self_held = decision == "hold"
                if decision == "hold": entry.claimed = False
                elif decision == "suppress":
                    self._pending_debounce.pop(key)
                    self._retire_entry_locked(entry)
            if decision == "hold":
                self._schedule_entry(key, entry)
                return
            if decision == "suppress": return
        fingerprint = None
        changing = False
        try:
            observed = os.stat(file_path)
            if stat.S_ISREG(observed.st_mode) and observed.st_size > 0:
                fingerprint = SourceFingerprint(observed.st_size, observed.st_mtime_ns)
                # A write during the stability interval keeps the original admission.
                changing = time.time_ns() - observed.st_mtime_ns < int(self._debounce_seconds * 1e9)
        except OSError:
            pass
        with self._lock:
            if self._pending_debounce.get(key) is not entry or not self._entry_current_locked(entry):
                self._retire_entry_locked(entry)
                return
            # Legacy deterministic clocks retain their historic one-tick dispatch behavior.
            if (self._managed_ingress is not None and fingerprint is not None
                    and (changing or (entry.fingerprint is not None and entry.fingerprint != fingerprint))):
                entry.fingerprint = fingerprint
                entry.claimed = False
                reset = True
            else:
                self._pending_debounce.pop(key)
                reset = False
        if reset:
            self._schedule_entry(key, entry)
            return
        if self._managed_ingress is not None:
            if fingerprint is None or not self._managed_ingress.post_stable(entry.admission, fingerprint):
                self._managed_ingress.retire(entry.admission)
        elif fingerprint is not None:
            self._dispatch_file_ready(config_id, file_path)

    def _dispatch_file_ready(self, config_id: str, file_path: str) -> None:
        """Dispatch a stable file to the watch's pipeline handler by mode."""
        handler = None
        with self._lock:
            state = self._watches.get(config_id)
            if state is None:
                return
            if state.config.mode == WatchMode.REVIEW_FIRST:
                handler = self._review_first_handler
            elif state.config.mode == WatchMode.AUTO_APPLY:
                handler = self._auto_apply_handler
        try:
            if handler is not None:
                handler.handle_file_ready(config_id, file_path)
            else:
                self.on_file_ready(config_id, file_path)
        except Exception:
            pass

    def _cancel_debounce_for_watch(self, config_id: str) -> None:
        """Cancel all pending debounce timers for a watch."""
        to_remove = [k for k in self._pending_debounce if k[0] == config_id]
        for key in to_remove:
            self._retire_entry_locked(self._pending_debounce.pop(key))

    def _retire_entry_locked(self, entry):
        if entry is None:
            return
        self._scheduler.cancel(entry.task_id)
        if self._managed_ingress is not None and entry.admission is not None:
            self._managed_ingress.retire(entry.admission)

    # ── Internal: State Management ─────────────────────────────────────────────

    def _get_state(self, config_id: str) -> _WatchState:
        """Get watch state, raising if not found."""
        if config_id not in self._watches:
            raise WatchControllerError(f"Watch not found: {config_id}")
        return self._watches[config_id]

    def _restore_stored_configs(self) -> None:
        """Restore all configs from store on startup.

        Active → auto-start observer
        Paused → load without starting
        Error / ResourcePaused → load without auto-activation

        Non-strict load errors are collected in self._recovery_errors.
        Initial-scan strategy: only process events after recovery;
        pre-existing files do not generate events.
        """
        # Collect load errors from non-strict store
        if hasattr(self._store, 'load_errors'):
            for err in self._store.load_errors:
                self._recovery_errors[err.get("id", f"unknown-{err.get('index', '?')}")] = err

        for cfg in self._store.list_all():
            state = _WatchState(config=cfg)
            self._watches[cfg.id] = state
            if self._autostart and cfg.status == WatchStatus.ACTIVE:
                attempt = _StartAttempt(state.incarnation)
                try:
                    self._start_observer(cfg.id, state, expected_config=cfg, attempt=attempt)
                except Exception:
                    self._record_start_failure(cfg.id, state, cfg, attempt)

    @property
    def recovery_errors(self) -> dict:
        """Return recovery errors (populated during restore)."""
        return dict(self._recovery_errors)

    @property
    def observers_idle(self) -> bool:
        with self._lock:
            self._prune_observers_locked()
            return self._starting_count == 0 and not self._observer_owners

    @property
    def workers_idle(self) -> bool:
        with self._lock:
            if self._pending_debounce or self._event_callbacks:
                return False
        return (self.observers_idle and self._scheduler.workers_idle
                and (self._managed_ingress is None or self._managed_ingress.workers_idle))

    def begin_close(self) -> None:
        with self._lock:
            self._closed = True
        self.stop_all()
        if self._managed_ingress is not None:
            self._managed_ingress.begin_close()

    def drain(self, deadline: float) -> bool:
        while not self.workers_idle:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(.005, remaining))
        return True

    # ── Test Helpers (NOT for production use) ──────────────────────────────────

    def _get_observer(self, config_id: str) -> Any:
        """Test helper: get the observer for a watch."""
        with self._lock:
            if config_id in self._watches:
                return self._watches[config_id].observer
            return None

    def _simulate_file_event(self, config_id: str, file_path: str, event_type: FileEvent) -> None:
        """Test helper: simulate a file event."""
        self._on_raw_file_event(config_id, file_path, event_type)

    def _simulate_observer_error(self, config_id: str, error: Exception) -> None:
        """Test helper: simulate an observer crashing."""
        with self._lock:
            if config_id not in self._watches:
                return
            state = self._watches[config_id]
            observer = self._detach_observer_locked(state)
            self._cancel_debounce_for_watch(config_id)
            updated = state.config.with_status(WatchStatus.ERROR)
            state.config = updated
            try:
                self._store.update(updated)
            except Exception:
                pass
            delay = self._backoff_base * (2 ** state.retry_count)
            self._schedule_retry(config_id, delay)
        self._stop_owned_observer(observer)

    @staticmethod
    def _is_temp_file(filename: str) -> bool:
        """Public access to temp file filter for testing."""
        return is_temp_file(filename)
