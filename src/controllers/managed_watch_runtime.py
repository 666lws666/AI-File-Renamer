"""One inertly constructed production Watch composition, borrowing Batch owners."""
from dataclasses import replace
import json
from pathlib import Path
import threading

from PySide6.QtCore import QObject, QTimer

from src.controllers.managed_watch_analysis import ManagedWatchAnalysisDelivery
from src.controllers.managed_watch_results import ManagedWatchResults
from src.controllers.managed_watch_file_operations import ManagedWatchFileOperations
from src.controllers.watch_controller import WatchController, WatchBindingState
from src.controllers.watch_edit_handler import WatchEditHandler
from src.controllers.watch_page_controller import WatchPageController
from src.core.managed_watch_metadata import auto_apply_review_reason
from src.core.watch_config import WatchConfigStore, WatchConfig, WatchStatus, WatchMode
from src.core.watch_review_queue import ReviewQueue, ReviewItemState, ReviewQueueError, ACTIVE_STATES
from src.core.watch_resource_guard import WatchResourceGuard, WatchLimits
from src.core.watch_self_events import WatchSelfEvents


class _UnavailableStore:
    load_errors = ({"id": "store", "error": "queue_unavailable"},)
    def list_all(self): return []
    def _deny(self, *args): raise ValueError("queue_unavailable")
    add = update = remove = _deny


def _load_configs(path):
    """Current schema or the historic Widgets list, without rewriting on load."""
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if type(raw) is list:
            if len(raw) > 1000: raise ValueError("queue_unavailable")
            configs = {}
            for item in raw:
                if type(item) is not dict or set(item) - {"id", "source_dir", "target_dir",
                    "template_id", "recursive", "mode", "active", "file_types"}:
                    raise ValueError("queue_unavailable")
                # Unsupported old extension policy is never silently widened.
                if item.get("file_types", []) != [] or type(item.get("active", True)) is not bool:
                    raise ValueError("queue_unavailable")
                current = {key: value for key, value in item.items() if key not in {"active", "file_types"}}
                current.setdefault("mode", "review_first")
                current["status"] = "active" if item.get("active", True) else "paused"
                config = WatchConfig.from_dict(current)
                if config.id in configs: raise ValueError("queue_unavailable")
                configs[config.id] = config
            # Reuse existing atomic CRUD; no temporary/different store path.
            store = WatchConfigStore.__new__(WatchConfigStore)
            store._file_path, store._lock = path, threading.Lock()
            store._configs, store._load_errors = configs, []
            return store
    store = WatchConfigStore(path, strict=True)
    if store.count() > 1000: raise ValueError("queue_unavailable")
    return store


class _Actions:
    def __init__(self, owner): self.owner = owner
    def _open(self): return not self.owner.closing and self.owner.available
    def approve(self, item_id):
        return self._open() and self.owner.file_actions.apply((item_id,))
    def ignore(self, item_id):
        if not self._open(): return False
        old = self.owner.results.item(item_id)
        if (old is None or old.recovery_required or old.file_operation is not None
                or old.state not in {ReviewItemState.PENDING, ReviewItemState.ANALYZING,
                    ReviewItemState.AWAITING_APPROVAL, ReviewItemState.FAILED, ReviewItemState.CANCELLED}):
            return False
        saved = self.owner.results.ignore(item_id)
        return saved is not old and saved.state is ReviewItemState.IGNORED
    def undo(self, item_id):
        return self._open() and self.owner.file_actions.undo(item_id)
    def retry(self, item_id):
        if not self._open(): return False
        row = self.owner.results.item(item_id)
        if (row is None or row.state not in {ReviewItemState.FAILED, ReviewItemState.CANCELLED}
                or row.file_operation is not None or row.recovery_required
                or row.error_category == "retried"): return False
        admission = self.owner.controller.retry_file(row.watch_id, row.source_path, row.extension)
        if admission is None:
            return False
        try:
            self.owner.results._replace_for_file_operation(((row,
                replace(row, state=ReviewItemState.CANCELLED, error_category="retried")),))
        except Exception:
            self.owner.controller.cancel_retry_admission(admission)
            return False
        self.owner._changed()
        return True
    def get_counts(self, watch_id):
        counts = {"pending": 0, "analyzing": 0, "review_pending": 0, "applied": 0}
        if self.owner.results is None: return counts
        durable_active = 0
        for row in self.owner.results.items(watch_id):
            name = "review_pending" if row.state is ReviewItemState.AWAITING_APPROVAL else row.state.value
            if name in counts: counts[name] += 1
            if row.state in ACTIVE_STATES: durable_active += 1
        executing = self.owner.guard.active_analyses(watch_id)
        counts["analyzing"] += executing
        counts["pending"] += max(0, self.owner.guard.pending_count(watch_id) - durable_active - executing)
        return counts
    def clear_pending(self, watch_id):
        if not self._open(): return 0
        before = self.get_counts(watch_id)
        self.owner.results.cancel_watch(watch_id)
        return before["pending"] + before["analyzing"] + before["review_pending"]


class _Edit(WatchEditHandler):
    def delete_watch(self, watch_id):
        super().delete_watch(watch_id)
        self._task_registry.clear_pending(watch_id)


class ManagedWatchRuntime(QObject):
    """Register this inert owner before configure(), then bind QML before start()."""
    def __init__(self):
        super().__init__()
        self.analysis_service = self.authority = self.catalog_source = self.file_lane = None
        self.controller = self.delivery = self.results = self.file_actions = self.actions = self.page = None
        self.receipts = self.guard = None
        self.closing = self.started = False
        self._available, self._error = False, "queue_unavailable"
        self._snapshot = None
        self._bridge_depth = 0
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self.poll)

    def configure(self, *, analysis_service, authority, catalog_source, file_lane, settings_path,
                  templates_provider, max_concurrency):
        if self.analysis_service is not None: raise ValueError("invalid_watch_runtime")
        self.analysis_service, self.authority = analysis_service, authority
        self.catalog_source, self.file_lane = catalog_source, file_lane
        self.receipts = WatchSelfEvents()
        file_lane.attach_receipts(self.receipts)
        self.guard = WatchResourceGuard(global_limits=WatchLimits(max_pending=1000,
            max_concurrent_analysis=max(1, min(2, max_concurrency)), max_file_size_mb=512))
        base = Path(settings_path).parent
        try:
            store = _load_configs(base / "watch_folders.json")
            queue = ReviewQueue(base / "watch_review_queue.json")
        except (OSError, ValueError, TypeError, ReviewQueueError):
            store, queue = _UnavailableStore(), None
        if queue is not None:
            self.results = ManagedWatchResults(queue=queue, resource_guard=self.guard,
                on_changed=self._changed, on_published=self._published)
            self.results.restore_interrupted()
            self.file_actions = ManagedWatchFileOperations(results=self.results, lane=file_lane)
            self.file_actions.restore_interrupted()
            self.delivery = ManagedWatchAnalysisDelivery(analysis_service, authority,
                capture_guard=catalog_source.guard, is_binding_current=self._binding_current,
                can_start=self._can_start, on_result=self.results.consume_result,
                resource_guard=self.guard, on_resource_blocked=self._resource_blocked)
            self.results.attach_delivery(self.delivery)
            self._available, self._error = True, ""
        self.controller = WatchController(store, resource_guard=self.guard, autostart=False,
            managed_ingress=self.delivery.ingress if self.delivery is not None else None,
            self_events=self.receipts)
        for config in self.controller.list_configs():
            self.guard.set_watch_limits(config.id, WatchLimits(max_pending=1000,
                max_concurrent_analysis=1, max_file_size_mb=512))
        self.actions = _Actions(self)
        self.page = WatchPageController(watch_controller=self.controller,
            edit_handler=_Edit(self.controller, self.actions), review_handler=self.actions,
            templates_provider=templates_provider,
            results_provider=lambda watch: self.results.items(watch) if self.results is not None else (),
            notice_provider=self.notice, availability_provider=lambda: self.available)

    @property
    def available(self):
        return (self._available and self.results is not None and self.results.available
                and self.file_actions is not None and self.file_actions.available)

    def _binding_current(self, event):
        return self.controller is not None and self.controller.managed_binding_state(event) is not WatchBindingState.STALE

    def _can_start(self, event):
        ready = self.controller is not None and self.controller.managed_binding_state(event) is WatchBindingState.READY
        if ready:
            # Newly added watches receive the same fixed finite policy before
            # their first execution. The global admission size/pending limits
            # already enforce these identical bounds before stabilization.
            self.guard.set_watch_limits(event.admission.watch_id, WatchLimits(max_pending=1000,
                max_concurrent_analysis=1, max_file_size_mb=512))
        return ready

    def _resource_blocked(self, event, reason):
        if self.closing or not self._binding_current(event): return
        self.controller.resource_pause(event.admission.watch_id)
        self.results.publish_notice(event.admission.watch_id, reason)

    def _published(self, result, saved):
        def authorized():
            return (not self.closing and self.available
                and self.delivery.is_publishing_result(result)
                and self.controller.managed_binding_state(result.event) is WatchBindingState.READY
                and self.authority.is_current(result.event.admission.work.context)
                and result.event.admission.watch_config.mode is WatchMode.AUTO_APPLY
                and self.file_actions._auto_row_current(saved)
                and auto_apply_review_reason(saved.managed_metadata) == "")
        if authorized():
            self.file_actions.auto_apply(saved.id, is_authorized=authorized)

    def _require_owner(self):
        if not self.thread().isCurrentThread():
            raise RuntimeError("watch_owner_thread_required")

    def _changed(self):
        self._require_owner()
        self._bridge_depth += 1
        try:
            if self.page is not None: self.page.refresh()
        finally:
            self._bridge_depth -= 1

    def notice(self, watch_id):
        if not self.available: return "queue_unavailable"
        if self.controller.self_event_held(watch_id): return "self_event_held"
        if any(row.recovery_required for row in self.results.items(watch_id)): return "recovery_required"
        return self.results.notice(watch_id)

    def start(self):
        if self.closing or self.started: return
        if self.page is None: raise ValueError("invalid_watch_runtime")
        self.started = True
        self._timer.start()
        if self.available: self.controller.start_all()

    def poll(self):
        self._require_owner()
        self._bridge_depth += 1
        try:
            if self.delivery is not None: self.delivery.poll()
            if self.page is not None:
                snapshot = (tuple(self.controller.list_configs()), self.available,
                    tuple((config.id, self.notice(config.id)) for config in self.controller.list_configs()))
                if snapshot != self._snapshot:
                    self._snapshot = snapshot
                    self._changed()
            # Stop only the outermost closing poll, while its real tail is still
            # owned. Public workers_idle never discounts this active frame.
            if self.closing and self._bridge_depth == 1 and self._children_idle():
                self._timer.stop()
        finally:
            self._bridge_depth -= 1

    def begin_close(self):
        if self.closing: return
        self.closing = True
        if self.controller is not None: self.controller.begin_close()
        if self.delivery is not None: self.delivery.begin_close()
        if self.results is not None: self.results.begin_close()
        if self.file_actions is not None: self.file_actions.begin_close()
        if self.receipts is not None: self.receipts.begin_close()

    def _children_idle(self):
        return (all(owner is None or owner.workers_idle for owner in
            (self.controller, self.delivery, self.results, self.file_actions, self.receipts)))

    @property
    def workers_idle(self):
        self._require_owner()
        return self._bridge_depth == 0 and self._children_idle()
