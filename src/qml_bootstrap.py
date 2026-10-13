"""QML runtime bootstrap factory (M6 functional gate).

Wires a real SettingsController into ``main.qml`` BEFORE the component is
created:

- ``main.qml`` declares an injectable ``settingsController`` root property;
- Shell passes it to PageRouter, which hands it to PreferencesPage.ctrl;
- dev mode defaults to the real ``load_config`` + ``SystemCredentialStore``
  and a REAL provider connection service (ConnectionTest over
  OpenAICompatibleAdapter — the existing transport/retry/classification
  safety boundary);
- tests inject a temporary config file, a fresh AppConfig, a
  FakeCredentialStore, and a fake connection service — the user's real
  settings.json, Credential Manager, and network are NEVER touched.

This module never sets QT_QPA_PLATFORM — tests set it themselves.

The production entry (``src.main``) delegates to this QML runtime after the
Product Owner-approved M8 cutover. The retired Qt Widgets runtime is no longer
part of the supported product.
"""

from __future__ import annotations

import os
import sys
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from functools import wraps

from PySide6.QtCore import QUrl, QObject, QEvent, QTimer, QCoreApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtWidgets import QApplication

from src.controllers.settings_controller import SettingsController
from src.models.app_config import AppConfig

QML_DIR = Path(__file__).parent / "ui_qml"
SRC_DIR = Path(__file__).parent

# Sentinel distinguishing "parameter omitted" (build the default recorder)
# from "explicitly passed None" (disable the usage service — used by tests
# and unavailable-state scenarios).
_UNSET = globals().get("_UNSET", object())


def build_default_local_config():
    """Pinned inert product metadata; no adoption, download or readiness."""
    from src.services.local_ai.production_resources import load_production_resources
    from src.services.local_ai.inference_service import LocalInferenceConfig
    product = load_production_resources()
    return LocalInferenceConfig(product.resource_root, product.runtime_root,
                                product.state_root, product.catalog)


def build_default_usage_recorder() -> Any:
    """Composition factory: a UsageRecorder in the OS user-data directory.

    Follows the repo's rename-history precedent (LOCALAPPDATA, else the
    user's home).  Never writes to the program directory and never touches
    the Credential Manager.  Tests inject their own tmp-path recorders.
    """
    from src.core.usage import UsageRecorder

    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return UsageRecorder(Path(base) / "Xuxia" / "usage" / "usage.json")


def build_production_connection_service(
    transport: Any = None,
    retry_executor: Any = None,
):
    """Real connection service: build an OpenAICompatibleAdapter from the
    profile + credential and run ConnectionTest over it (existing transport,
    retry, and error-classification safety boundary — no new HTTP client).

    ``transport`` / ``retry_executor`` are injection points for tests only;
    the default is the real network transport with the standard retry policy.

    The probe path (``ConnectionTest`` -> ``adapter.invoke_probe``) is the
    ONLY bypass of ``needs_connection_verification``, so unverified providers
    can complete their first connection test while business invokes stay
    blocked.  Configuration failures (e.g. an empty key) are returned as a
    structured ``ConnectionResult`` — never a raw exception to QML.
    """
    from src.core.connection_test import (
        ConnectionOutcome,
        ConnectionResult,
        ConnectionTest,
    )
    from src.providers.openai_compatible import OpenAICompatibleAdapter

    def service(profile, credential, *, processing_dispatch):
        try:
            adapter = OpenAICompatibleAdapter(
                profile=profile,
                credential=credential,
                transport=transport,
                retry_executor=retry_executor,
                processing_dispatch=processing_dispatch,
            )
        except Exception:
            return ConnectionResult(outcome=ConnectionOutcome.UNKNOWN_ERROR)
        return ConnectionTest(adapter).execute()

    return service


def build_production_batch_analyzer(catalog_source, credential_store, authority,
                                    local_inference, local_preparation, *,
                                    managed_adapter_factory=None, content_extractor=None):
    """Workers read immutable catalog values, never AppConfig or Qt controllers."""
    from src.controllers.settings_controller import PROVIDER_CREDENTIAL_SERVICE
    from src.core.batch_analysis import BatchAnalysisService
    from src.providers.openai_compatible import OpenAICompatibleAdapter

    def credential_provider(profile):
        account = profile.credential_account_id or f"provider:{profile.id}"
        return credential_store.get(PROVIDER_CREDENTIAL_SERVICE, account) or ""

    options = {} if content_extractor is None else {"content_extractor": content_extractor}
    return BatchAnalysisService(
        profile_provider=lambda: catalog_source.get().active_profile,
        credential_provider=credential_provider,
        config_provider=lambda: catalog_source.get().settings,
        template_provider=lambda template_id: catalog_source.get().template(template_id),
        processing_authority=authority,
        local_inference_service=local_inference,
        local_preparation_service=local_preparation,
        capture_guard=catalog_source.guard,
        managed_adapter_factory=managed_adapter_factory or (
            lambda profile, key, *, processing_dispatch, retry_executor:
            OpenAICompatibleAdapter(profile=profile, credential=key,
                processing_dispatch=processing_dispatch, retry_executor=retry_executor)),
        **options,
    )


@dataclass
class QmlRuntime:
    """Created QML tree + engine + controller with warning capture.

    The ``i18n`` / ``batch_controller`` fields hold strong Python references
    to the injected QObjects — without them Python GC would collect the
    wrappers while the QML engine still references the C++ objects, and QML
    slot dispatch would fail (seen as "Cannot call method 'tr' of null").

    ``cleanup()`` destroys the root and engine in stable order.
    """

    engine: QQmlEngine
    component: QQmlComponent
    root: Any
    controller: SettingsController | None
    warnings: list[str] = field(default_factory=list)
    i18n: Any = None
    batch_controller: Any = None
    template_controller: Any = None
    watch_controller: Any = None
    watch_owner: Any = None
    status_controller: Any = None
    processing_coordinator: Any = None
    catalog_source: Any = None
    analysis_service: Any = None
    local_inference_service: Any = None
    local_preparation_service: Any = None
    local_resources_controller: Any = None
    owns_local_resources_controller: bool = False
    production_resources: Any = None
    resource_manager: Any = None
    trusted_local_anchor: Any = None
    shutdown_owner: Any = None
    probe_runner: Any = None
    owns_batch: bool = False
    file_operation_lane: Any = None
    owns_file_operation_lane: bool = False
    owns_controller: bool = False
    _cleaning: bool = False
    _closing: bool = False
    _batch_close_complete: bool = False
    _close_guard: Any = None
    _close_timer: Any = None
    _disposed: bool = False

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def assert_zero_warnings(self) -> None:
        if self.warnings:
            raise AssertionError(
                f"{len(self.warnings)} QML warning(s):\n"
                + "\n".join(self.warnings[:20])
            )

    def cleanup(self, deadline=None) -> bool:
        """Bounded retryable drain. Owners survive every incomplete cleanup."""
        limit = time.monotonic() + 2.0 if deadline is None else deadline
        if type(limit) not in (float, int) or not math.isfinite(limit):
            raise ValueError("RUNTIME_CLEANUP_DEADLINE_ERROR")
        if self._cleaning:
            return False
        if self._disposed:
            return True
        self._cleaning = True
        try:
            if not self._closing:
                self._closing = True
                # The pure lifetime fence must precede every failure/close signal.
                if self.processing_coordinator is not None:
                    self.processing_coordinator.authority.close_admission()
                if self.local_resources_controller is not None:
                    self.local_resources_controller.begin_close()
                if self.watch_owner is not None:
                    self.watch_owner.begin_close()
                if self.owns_file_operation_lane and self.file_operation_lane is not None:
                    self.file_operation_lane.begin_close()
                if self.processing_coordinator is not None:
                    self.processing_coordinator.begin_close()
                if self.owns_controller and self.controller is not None:
                    self.controller.begin_close()
                if self.probe_runner is not None:
                    self.probe_runner.begin_close()
            while True:
                if self.watch_owner is not None: self.watch_owner.poll()
                if (self.owns_batch and self.batch_controller is not None
                        and not self._batch_close_complete):
                    try:
                        self.batch_controller.close()
                    except OSError:
                        # Cancellation persistence can fail after worker stop
                        # begins. Retain owners and retry, never infer closure.
                        pass
                    else:
                        self._batch_close_complete = True
                writer_done = (self.processing_coordinator is None or
                    self.processing_coordinator.drain_choice_writer(deadline=limit))
                batch_done = (not self.owns_batch or self.batch_controller is None or
                              (self._batch_close_complete and self.batch_controller.workers_idle))
                probe_done = self.probe_runner is None or self.probe_runner.workers_idle
                preparation_done = (self.local_preparation_service is None or
                                    self.local_preparation_service.close(limit))
                file_done = (not self.owns_file_operation_lane or self.file_operation_lane is None
                             or self.file_operation_lane.closed)
                watch_done = self.watch_owner is None or self.watch_owner.workers_idle
                resources_owned_done = (self.local_resources_controller is None or
                    self.local_resources_controller.drain_owned_operations(
                        deadline=min(limit, time.monotonic()+.01)))
                previous_done = (writer_done and batch_done and probe_done and
                    preparation_done and file_done and watch_done and resources_owned_done)
                # Never invoke service cleanup on Qt or before every existing
                # borrower and real resource/callback/Qt/native tail has drained.
                local_done = (self.local_inference_service is None or
                    previous_done and self.shutdown_owner is not None and
                    self.shutdown_owner.close(deadline=limit))
                resources_done = (self.local_resources_controller is None or
                    local_done and self.local_resources_controller.close(
                        deadline=min(limit, time.monotonic()+.01)))
                if previous_done and local_done and resources_done:
                    break
                if time.monotonic() >= limit:
                    return False
                # No authority/catalog lock held; completion consumers stay alive.
                QApplication.processEvents()
            if self._close_timer is not None:
                self._close_timer.stop()
            if self.root is not None:
                self.root.deleteLater()
            QApplication.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.root = None
            self.component = None
            if self.engine is not None:
                self.engine.deleteLater()
            QApplication.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.engine = None
            self.controller = None
            self.batch_controller = None
            self.file_operation_lane = None
            self.template_controller = None
            self.watch_controller = None
            self.watch_owner = None
            self.status_controller = None
            self.i18n = None
            if self.owns_local_resources_controller:
                self.local_resources_controller = None
            self._disposed = True
            if self in _INCOMPLETE_CONSTRUCTIONS:
                _INCOMPLETE_CONSTRUCTIONS.remove(self)
            return True
        finally:
            self._cleaning = False

    def manage_window_close(self, *, quit_application=False):
        """Intercept actual window Close before Qt can destroy callback owners."""
        if self._close_guard is not None:
            self._close_guard.quit_application = quit_application
            return
        self._close_guard = _RuntimeCloseGuard(self, quit_application=quit_application)
        if self.root is not None:
            self.root.installEventFilter(self._close_guard)

    def wait_for_cleanup(self):
        """Keep Qt dispatch alive across finite attempts; no unproven exit."""
        from PySide6.QtCore import QEventLoop
        while self.cleanup(deadline=time.monotonic() + .02) is not True:
            loop = QEventLoop()
            QTimer.singleShot(25, loop.quit)
            loop.exec()


class _RuntimeCloseGuard(QObject):
    def __init__(self, runtime, *, quit_application):
        super().__init__()
        self.runtime = runtime
        self.quit_application = quit_application
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self._poll)
        runtime._close_timer = self.timer

    def _poll(self):
        if self.runtime.cleanup(deadline=time.monotonic() + .02):
            self.timer.stop()
            if self.quit_application:
                QApplication.instance().quit()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Close:
            event.ignore()
            self._poll()
            if self.runtime.root is not None:
                self.timer.start()
            return True
        return False


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


_INCOMPLETE_CONSTRUCTIONS = []


class RuntimeConstructionPending(RuntimeError):
    """Partial owner tree retained until main/caller drains it truthfully."""
    def __init__(self, runtime):
        self.runtime = runtime
        super().__init__("RUNTIME_CONSTRUCTION_CLEANUP_PENDING")


def _safe_construction(build):
    @wraps(build)
    def construct(**kwargs):
        partial = QmlRuntime(None, None, None, None)
        try:
            return build(_construction=partial, **kwargs)
        except BaseException:
            if partial.cleanup(deadline=time.monotonic() + .02) is not True:
                _INCOMPLETE_CONSTRUCTIONS.append(partial)
                raise RuntimeConstructionPending(partial) from None
            raise
    return construct


@_safe_construction
def build_qml_runtime(
    *,
    live_config: AppConfig | None = None,
    config_file: Path | None = None,
    credential_store: Any = None,
    batch_controller: Any = _UNSET,
    i18n: Any = None,
    main_qml: Path | None = None,
    controller: SettingsController | None = None,
    connection_test_service: Any = None,
    usage_recorder: Any = _UNSET,
    template_controller: Any = _UNSET,
    watch_controller: Any = _UNSET,
    status_controller: Any = _UNSET,
    diagnostics_service: Any = _UNSET,
    local_config: Any = None,
    local_inference_factory: Any = None,
    local_preparation_factory: Any = None,
    production_resources: Any = None,
    trusted_local_anchor: Any = None,
    resource_controller: Any = _UNSET,
    resource_controller_factory: Any = None,
    shutdown_owner_factory: Any = None,
    processing_writer_factory: Any = None,
    managed_adapter_factory: Any = None,
    analysis_content_extractor: Any = None,
    connection_transport: Any = None,
    file_operation_lane_factory: Any = None,
    _construction: Any = None,
) -> QmlRuntime:
    """Create the engine and load main.qml with a real SettingsController.

    Dev mode (all parameters None): real ``load_config`` + real
    ``SystemCredentialStore`` + the REAL connection service
    (ConnectionTest over OpenAICompatibleAdapter).  Test mode: pass explicit
    temporary config file, live config, fake credential store, and a fake
    connection service — no real API calls, no real Credential Manager.

    ``usage_recorder``:
    - OMITTED → the bootstrap constructs the default recorder
      (``build_default_usage_recorder()``, OS user-data directory) and wires
      it as the controller's read-only usage service;
    - explicitly ``None`` → no usage service (the card shows its
      unavailable state);
    - any other object → used as the injected usage service.

    ``resource_controller`` omitted builds the single owned product controller;
    explicit None is an unavailable test/unsupported seam. A supplied SAME-graph
    controller borrows QObject lifetime but hands admission sealing and operation
    drain to this runtime. ``resource_controller_factory(coordinator, product,
    manager, service, *, trusted_anchor)`` returns a runtime-owned controller and
    may not substitute graph identities. ``production_resources`` plus an existing
    absolute ``trusted_local_anchor`` is the trusted QA/deployment composition
    seam, never a QML path/manifest/executable authority. A foreign ``local_config``
    needs explicit resource_controller=None or a valid exact product graph.
    ``shutdown_owner_factory(service)`` returns one inert runtime-owned async
    owner for that exact service; construction failure keeps a registered fallback.

    Never touches QT_QPA_PLATFORM — tests set it themselves.
    """
    from src.config import CONFIG_FILE, load_config
    from src.core.provider_manager import SystemCredentialStore
    from src.utils.i18n.service import I18n
    from src.controllers.processing_coordinator import ProcessingCoordinator
    from src.core.processing_intent_store import ProcessingIntentStore, ProcessingIntentWriter
    from src.core.analysis_catalog import AnalysisCatalogSource, build_analysis_catalog
    from src.core.processing_authority import ProcessingMode, LocalReadiness
    from src.services.local_ai.inference_service import LocalInferenceService
    from src.services.local_ai.inference_service import LocalInferenceConfig
    from src.services.local_ai.production_resources import load_production_resources
    from src.services.local_ai.resource_manager import ResourceManager
    from src.services.local_ai.resource_operation_runner import validate_composition
    from src.services.local_ai.runtime_shutdown_owner import RuntimeShutdownOwner
    from src.controllers.local_resources_controller import LocalResourcesController
    from src.services.local_ai.preparation_service import BoundedLocalPreparationService
    from src.controllers.managed_connection_runner import ManagedConnectionRunner

    _ensure_app()

    cfg_file = Path(config_file) if config_file is not None else CONFIG_FILE
    coordinator = ProcessingCoordinator(ProcessingIntentStore(cfg_file.parent / "processing-intent.json"),
        writer_factory=processing_writer_factory or ProcessingIntentWriter)
    _construction.processing_coordinator = coordinator
    live = live_config if live_config is not None else load_config(cfg_file, load_credentials=False)
    product = production_resources
    if product is None and (local_config is None or resource_controller is not None):
        product = load_production_resources()
    _construction.production_resources = product
    local_inference = (local_inference_factory or LocalInferenceService)(
        local_config if local_config is not None else LocalInferenceConfig(
            product.resource_root, product.runtime_root, product.state_root, product.catalog))
    _construction.local_inference_service = local_inference
    # Register an inert fallback before the caller's fallible owner factory.
    # It only runs if construction fails before the replacement is registered.
    _construction.shutdown_owner = RuntimeShutdownOwner(local_inference)
    if shutdown_owner_factory is not None:
        shutdown_owner = shutdown_owner_factory(local_inference)
        if shutdown_owner.service is not local_inference:
            raise ValueError('INVALID_RESOURCE_COMPOSITION')
        _construction.shutdown_owner = shutdown_owner
    if resource_controller is not None:
        try:
            anchor = Path(trusted_local_anchor if trusted_local_anchor is not None
                          else os.environ['LOCALAPPDATA'])
            if not anchor.is_absolute() or anchor.parent == anchor or not anchor.is_dir():
                raise ValueError()
        except (KeyError, TypeError, ValueError, OSError):
            raise ValueError('INVALID_RESOURCE_COMPOSITION') from None
        _construction.trusted_local_anchor = anchor
        supplied = resource_controller is not _UNSET
        manager = (resource_controller.runner.manager if supplied else
                   ResourceManager(product.resource_root, product.catalog))
        _construction.resource_manager = manager
        validate_composition(product, manager, local_inference, anchor)
        if supplied and (resource_controller.coordinator is not coordinator
                or resource_controller.config is not product
                or resource_controller.runner.service is not local_inference
                or resource_controller.runner.authority is not coordinator.authority):
            raise ValueError('INVALID_RESOURCE_COMPOSITION')
        if resource_controller is _UNSET:
            resource_controller = (resource_controller_factory or LocalResourcesController)(
                coordinator, product, manager, local_inference, trusted_anchor=anchor)
            _construction.owns_local_resources_controller = True
        # Attaching borrows QObject lifetime but hands operation sealing/drain to
        # this runtime. Register before validation/any later fallible use.
        _construction.local_resources_controller = resource_controller
        runner = resource_controller.runner
        if (resource_controller.coordinator is not coordinator
                or resource_controller.config is not product
                or runner.config is not product or runner.manager is not manager
                or runner.trusted_anchor != anchor
                or runner.service is not local_inference
                or runner.authority is not coordinator.authority):
            raise ValueError('INVALID_RESOURCE_COMPOSITION')
        validate_composition(product, runner.manager, local_inference, anchor)
    local_preparation = (local_preparation_factory or BoundedLocalPreparationService)()
    _construction.local_preparation_service = local_preparation

    engine = QQmlEngine()
    _construction.engine = engine
    engine.addImportPath(str(SRC_DIR))
    warnings: list[str] = []
    _construction.warnings = warnings
    engine.warnings.connect(lambda msgs: warnings.extend(m.toString() for m in msgs))

    i18n_obj = i18n if i18n is not None else I18n()
    _construction.i18n = i18n_obj

    store = credential_store if credential_store is not None else SystemCredentialStore()
    engine.rootContext().setContextProperty("processingController", coordinator)
    engine.rootContext().setContextProperty("localResourcesController",
                                           _construction.local_resources_controller)

    production_batch = batch_controller is _UNSET
    production_watch = watch_controller is _UNSET
    if production_batch or production_watch:
        from src.controllers.managed_file_operation_lane import ManagedFileOperationLane
        from src.services.file_operation_backend import FileOperationBackend

        history_path = cfg_file.parent / 'rename_history.jsonl'
        factory = file_operation_lane_factory or (lambda path: ManagedFileOperationLane(FileOperationBackend(path)))
        _construction.file_operation_lane = factory(history_path)
        _construction.owns_file_operation_lane = True
    if production_batch:
        from src.controllers.batch_workspace_controller import BatchWorkspaceController
        batch = BatchWorkspaceController(
            workspace_path=cfg_file.parent / "batch_workspace.json",
            history_path=cfg_file.parent / "rename_history.jsonl",
            max_workers=live.max_concurrent_requests,
            file_operation_lane=_construction.file_operation_lane,
        )
    else:
        batch = batch_controller
    _construction.batch_controller = batch
    _construction.owns_batch = production_batch
    engine.rootContext().setContextProperty("batchController", batch)

    # Omitted means a real, local-only template/vocabulary controller rooted
    # beside settings.json.  Tests can pass None to exercise the unavailable
    # state without touching user data.
    if template_controller is _UNSET:
        from src.controllers.template_page_controller import TemplatePageController
        from src.core.template_store import TemplateStore
        from src.core.vocabulary import VocabularyStore

        template_controller = TemplatePageController(
            template_store=TemplateStore(cfg_file.parent / "templates.json"),
            vocabulary_store=VocabularyStore(),
            vocabulary_state_path=cfg_file.parent / "vocabulary.json",
            locale=live.language,
        )
    _construction.template_controller = template_controller

    # Initialize I18n from the live/draft config BEFORE the QML tree is
    # created, so the UI starts in the persisted language.  The I18n
    # boundary accepts the AppConfig spelling (zh_CN/en_US) as an alias of
    # the canonical zh-CN/en-US.
    lang = live.language
    if controller is not None and controller.draft_config is not None:
        lang = controller.draft_config.language
    i18n_obj.set_locale(lang)
    if template_controller is not None and hasattr(template_controller, "setLocale"):
        template_controller.setLocale(i18n_obj.locale)
        i18n_obj.locale_changed.connect(template_controller.setLocale)

    engine.rootContext().setContextProperty("i18n", i18n_obj)

    def actual_templates():
        if template_controller is None:
            return ()
        return tuple(template_controller.get_template_for_analysis(row["id"])
                     for row in template_controller.templates)

    catalog_source = AnalysisCatalogSource(build_analysis_catalog(live, actual_templates()))
    _construction.catalog_source = catalog_source
    coordinator.publish_catalog(catalog_source, catalog_source.get())
    analysis_service = build_production_batch_analyzer(catalog_source, store,
        coordinator.authority, local_inference, local_preparation,
        managed_adapter_factory=managed_adapter_factory, content_extractor=analysis_content_extractor)
    _construction.analysis_service = analysis_service
    if production_watch:
        from src.controllers.managed_watch_runtime import ManagedWatchRuntime
        # Register inert owner before any fallible store/service construction.
        _construction.watch_owner = ManagedWatchRuntime()
        _construction.watch_owner.configure(analysis_service=analysis_service,
            authority=coordinator.authority, catalog_source=catalog_source,
            file_lane=_construction.file_operation_lane, settings_path=cfg_file,
            templates_provider=lambda: template_controller.templates if template_controller is not None else (),
            max_concurrency=live.max_concurrent_requests)
        watch_controller = _construction.watch_owner.page
    _construction.watch_controller = watch_controller

    def credential_read_allowed():
        snapshot = coordinator.snapshot
        return (coordinator.is_open and snapshot.mode is ProcessingMode.CLOUD
                and snapshot.error_code is None and snapshot.persistence_status.value == "saved")

    def prepare_inputs(candidate):
        return build_analysis_catalog(candidate, actual_templates())

    def commit_inputs(candidate, prepared):
        coordinator.publish_catalog(catalog_source, prepared)

    def admission_failed(_reason):
        coordinator.authority.close_admission()
        coordinator.begin_close()

    # A supplied old two-argument service is an intentional legacy test seam.
    # The omitted default always uses managed fixed probes; no signature sniffing.
    probe_runner = None
    owns_controller = controller is None
    if controller is None and connection_test_service is None:
        probe_runner = ManagedConnectionRunner(build_production_connection_service(
            transport=connection_transport))
        _construction.probe_runner = probe_runner

    if controller is not None:
        pass  # caller-provided controller (e.g. with cache/connection services)
    else:
        # usage_recorder: omitted → default recorder in the OS user-data
        # directory; explicit None → disabled; object → injected.
        if usage_recorder is _UNSET:
            usage_recorder = build_default_usage_recorder()
        controller = SettingsController(
            live_config=live,
            config_file_path=cfg_file,
            credential_store=store,
            connection_test_service=connection_test_service,
            usage_service=usage_recorder,
            credential_read_allowed=credential_read_allowed,
            runtime_input_preparer=prepare_inputs,
            runtime_inputs_committed=commit_inputs,
            runtime_admission_failed=admission_failed,
            managed_connection_runner=probe_runner,
            processing_authority=coordinator.authority,
        )
    _construction.controller = controller
    _construction.owns_controller = owns_controller

    controller.localeRestoreRequested.connect(i18n_obj.set_locale)

    if template_controller is not None:
        def sync_runtime_templates() -> None:
            if not coordinator.is_open:
                return
            prepared = prepare_inputs(live)
            if prepared != catalog_source.get():
                try:
                    commit_inputs(live, prepared)
                except Exception:
                    admission_failed("runtime-input-publication-failed")
                    return
            if production_batch:
                selected = batch.selectedTemplateId or live.default_template_id
                batch.configure_templates(template_controller.templates, selected)
            if _construction.watch_owner is not None:
                _construction.watch_owner._changed()

        sync_runtime_templates()
        template_controller.stateChanged.connect(sync_runtime_templates)
        i18n_obj.locale_changed.connect(lambda _locale: sync_runtime_templates())
    if production_batch:
        batch.set_managed_analyzer(analysis_service, coordinator.authority)

    if status_controller is _UNSET:
        from src.controllers.status_controller import (
            ComponentStatus,
            StatusController,
            StatusLevel,
        )

        def active_profile() -> dict[str, Any] | None:
            active_id = controller.activeProviderId if controller is not None else ""
            if not active_id:
                return None
            return next(
                (row for row in controller.providerProfiles if row.get("id") == active_id),
                None,
            )

        def provider_probe(kind: str):
            profile = active_profile()
            component_id = "text" if kind == "text" else "vision"
            name = "status.component.text" if kind == "text" else "status.component.vision"
            if profile is None:
                return ComponentStatus(component_id, name, StatusLevel.UNAVAILABLE,
                                       "status.detail.noProvider")
            supported_key = "textSupported" if kind == "text" else "visionSupported"
            if not bool(profile.get(supported_key)):
                return ComponentStatus(component_id, name, StatusLevel.UNAVAILABLE,
                                       f"status.detail.{kind}Unsupported")
            if profile.get("needsConnectionVerification", True):
                return ComponentStatus(component_id, name, StatusLevel.ATTENTION,
                                       "status.detail.needsVerification")
            return ComponentStatus(component_id, name, StatusLevel.READY,
                                   "status.detail.available")

        def local_probe():
            snapshot = coordinator.snapshot
            ready = (coordinator.is_open and snapshot.mode is ProcessingMode.LOCAL
                and snapshot.local_readiness is LocalReadiness.READY
                and snapshot.engine_fingerprint is not None and snapshot.error_code is None)
            return ComponentStatus("local", "status.component.local",
                StatusLevel.READY if ready else StatusLevel.UNAVAILABLE,
                "status.detail.available" if ready else "status.detail.unavailable")

        status_controller = StatusController({
            "local": local_probe,
            "text": lambda: provider_probe("text"),
            "vision": lambda: provider_probe("vision"),
        })

    if diagnostics_service is _UNSET:
        if controller is not None and controller.diagnosticsAvailable:
            # A caller-provided controller owns its service; never replace it.
            diagnostics_service = None
        else:
            from src.core.diagnostics import DiagnosticsExporter

            exporter = DiagnosticsExporter(app_version="1.0.0")

            def diagnostics_service(destination: str):
                target = QUrl(destination).toLocalFile() if destination.startswith("file:") else destination
                if status_controller is not None:
                    status_controller.check_all()
                    components = status_controller.components
                else:
                    components = []
                settings = live.model_dump(mode="json")
                preview = exporter.preview(components=components, settings=settings, logs=[])
                return exporter.export(target, preview)

    if controller is not None and diagnostics_service is not None:
        controller.set_diagnostics_service(diagnostics_service)

    qml_path = main_qml if main_qml is not None else QML_DIR / "main.qml"
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml_path)))
    _construction.component = component
    if component.isError():
        raise RuntimeError(
            "QML errors:\n" + "\n".join(e.toString() for e in component.errors())
        )

    root = component.createWithInitialProperties({
        "settingsController": controller,
        "templateController": template_controller,
        "watchController": watch_controller,
        "statusController": status_controller,
    })
    _construction.root = root
    if root is None:
        raise RuntimeError("Null root from main.qml")
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    runtime = _construction
    runtime.warnings = warnings
    runtime.watch_controller = watch_controller
    runtime.status_controller = status_controller
    runtime.catalog_source = catalog_source
    runtime.analysis_service = analysis_service
    runtime.manage_window_close()
    if runtime.watch_owner is not None: runtime.watch_owner.start()
    startup = coordinator.snapshot
    if (runtime.local_resources_controller is not None
            and startup.mode is ProcessingMode.LOCAL and startup.error_code is None
            and startup.persistence_status.value == 'saved'):
        def prepare_saved_local():
            if not runtime._closing and coordinator.is_open:
                runtime.local_resources_controller.prepareExisting()
        QTimer.singleShot(0, prepare_saved_local)
    return runtime
