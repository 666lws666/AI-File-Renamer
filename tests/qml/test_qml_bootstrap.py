"""M0 Task 4: QML bootstrap tests."""
import os
import sys
import pytest

# Use offscreen platform for headless testing
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def ensure_offscreen():
    """Ensure offscreen platform for all tests."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    yield


def test_qtquick_imports():
    """Verify QtQuick modules can be imported."""
    from PySide6 import QtCore, QtGui, QtQml
    assert QtCore.__name__
    assert QtGui.__name__
    assert QtQml.__name__


def test_main_qml_loads():
    """Verify main.qml can be parsed without errors."""
    from pathlib import Path
    from PySide6.QtQml import QQmlEngine, QQmlComponent
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication

    # QGuiApplication needed for QML engine
    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication(sys.argv)

    qml_path = Path(__file__).parent.parent.parent / "src" / "ui_qml" / "M0Bootstrap.qml"
    assert qml_path.exists(), f"main.qml not found at {qml_path}"

    engine = QQmlEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml_path)))
    if component.isError():
        errors = "\n".join(
            e.toString() for e in component.errors()
        )
        pytest.fail(f"QML component errors:\n{errors}")

    assert component.isReady(), "QML component is not ready"
    assert not component.isError(), f"QML errors: {component.errorString()}"


def test_root_object_creatable():
    """Verify root object can be created with correct size."""
    from pathlib import Path
    from PySide6.QtQuick import QQuickView
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication(sys.argv)

    qml_path = Path(__file__).parent.parent.parent / "src" / "ui_qml" / "M0Bootstrap.qml"

    view = QQuickView()
    view.setSource(QUrl.fromLocalFile(str(qml_path)))
    view.show()

    root = view.rootObject()
    assert root is not None, "Root object is None"

    # Verify size
    assert root.width() == 400, f"Expected width 400, got {root.width()}"
    assert root.height() == 300, f"Expected height 300, got {root.height()}"

    view.close()


def _format_qml_errors(component) -> str:
    """Shared error formatter used by all QML tests."""
    return "\n".join(e.toString() for e in component.errors())


def test_invalid_qml_error_diagnostics_do_not_raise_type_error():
    """Error diagnostics must work on intentionally invalid QML without TypeError."""
    import sys
    from PySide6.QtQml import QQmlEngine, QQmlComponent
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication(sys.argv)

    engine = QQmlEngine()
    # Deliberately invalid QML
    invalid_qml = QUrl.fromLocalFile(__file__)  # Not a QML file
    component = QQmlComponent(engine, invalid_qml)
    # Must be in error state
    assert component.isError(), "Expected component to be in error state"

    # Formatting errors must not raise TypeError
    formatted = _format_qml_errors(component)
    assert len(formatted) > 20, (
        f"Error formatter returned too-short string: '{formatted}'"
    )
    print(f"Invalid QML errors (expected): {formatted}")


def test_no_qml_errors():
    """Verify main.qml has no component errors or warnings."""
    from pathlib import Path
    from PySide6.QtQml import QQmlEngine, QQmlComponent
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication(sys.argv)

    qml_path = Path(__file__).parent.parent.parent / "src" / "ui_qml" / "M0Bootstrap.qml"

    engine = QQmlEngine()
    errors = []
    engine.warnings.connect(lambda msg: errors.append(str(msg)))

    component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml_path)))
    assert not component.isError(), f"QML errors: {component.errorString()}"
    # Warnings are not fatal but should be noted
    if errors:
        print(f"QML warnings (non-fatal): {errors}")


# ============================================================================
# M6 Provider Integration Gate — bootstrap must not force QT_QPA_PLATFORM
# ============================================================================

def test_import_does_not_modify_qt_qpa_platform(monkeypatch):
    """GATE-8: importing qml_bootstrap must not write QT_QPA_PLATFORM."""
    import importlib
    import os
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    assert "QT_QPA_PLATFORM" not in os.environ
    import src.qml_bootstrap as qb
    importlib.reload(qb)
    assert "QT_QPA_PLATFORM" not in os.environ, (
        "qml_bootstrap must not set QT_QPA_PLATFORM"
    )


def test_import_preserves_existing_qt_qpa_platform(monkeypatch):
    """An existing QT_QPA_PLATFORM (e.g. offscreen in tests) is preserved."""
    import importlib
    import os
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    import src.qml_bootstrap as qb
    importlib.reload(qb)
    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"


def test_windows_platform_allowed_explicitly(monkeypatch):
    """Windows QPA can be requested explicitly without bootstrap fighting it."""
    import importlib
    import os
    monkeypatch.setenv("QT_QPA_PLATFORM", "windows")
    import src.qml_bootstrap as qb
    importlib.reload(qb)
    assert os.environ.get("QT_QPA_PLATFORM") == "windows"


def test_production_connection_service_returns_callable():
    """Dev-mode bootstrap wires a REAL connection service built on the
    existing adapter/ConnectionTest boundary (never a new HTTP client)."""
    from src.qml_bootstrap import build_production_connection_service
    service = build_production_connection_service()
    assert callable(service)
    # It must be constructed from ConnectionTest + OpenAICompatibleAdapter
    import inspect
    from src.providers.openai_compatible import OpenAICompatibleAdapter
    from src.core.connection_test import ConnectionTest
    src_code = inspect.getsource(build_production_connection_service)
    assert "OpenAICompatibleAdapter" in src_code
    assert "ConnectionTest" in src_code
    # building an adapter for a profile without a credential fails closed
    from src.core.provider_profile import ProviderProfile
    profile = ProviderProfile(id="x", provider_id="x", base_url="https://x.example.com/v1", model="m")
    result = service(profile, "", processing_dispatch=_fixed_dispatch(profile))
    from src.core.connection_test import ConnectionOutcome
    assert result.outcome is not ConnectionOutcome.SUCCESS


def _fixed_dispatch(profile):
    from src.core.processing_authority import ProcessingAuthority, ProcessingMode
    from src.core.processing_identity import cloud_engine_fingerprint
    from src.providers.openai_compatible import ProcessingDispatch
    authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD)
    context = authority.capture_cloud_probe(candidate_fingerprint=cloud_engine_fingerprint(profile),
        candidate_model=profile.model, request_id="synthetic-fixed-probe")
    return ProcessingDispatch(authority, context)


def _guarded_transport(responses):
    from tests.unit.test_connection_test import _FakeTransport
    class GuardedTransport(_FakeTransport):
        def send(self, *, dispatch_context, **kwargs):
            receipt = dispatch_context.authority.commit_cloud_probe_attempt(
                dispatch_context.context, "synthetic-probe-" + str(len(self.calls)))
            try:
                return super().send(**kwargs)
            finally:
                dispatch_context.authority.finish_attempt(receipt)
    return GuardedTransport(responses)


def test_production_connection_service_executes_unverified_profile(monkeypatch):
    """GATE-P0: the REAL production connection service (ConnectionTest over
    OpenAICompatibleAdapter) must execute an UNVERIFIED profile through the
    probe path with a fake transport — no real network."""
    from dataclasses import replace
    from src.qml_bootstrap import build_production_connection_service
    from src.core.provider_presets import create_custom_provider_profile
    from src.core.provider_protocol import ProviderCapabilities
    from src.core.connection_test import ConnectionOutcome
    from src.services.retry_policy import RetryExecutor, RetryPolicy
    from tests.unit.test_connection_test import _FakeTransport, _minimal_probe_response

    profile = replace(
        create_custom_provider_profile(
            profile_id="prod-svc-custom",
            display_name="Prod service custom",
            base_url="https://prod-svc.test/v1",
            model="test-model",
            capabilities=ProviderCapabilities(text=True),
        ),
        needs_connection_verification=True,
    )
    transport = _guarded_transport([_minimal_probe_response()])
    service = build_production_connection_service(
        transport=transport,
        retry_executor=RetryExecutor(
            RetryPolicy(max_retries=0),
            sleeper=lambda d: None,
        ),
    )
    result = service(profile, "sk-prod-svc-fake-key", processing_dispatch=_fixed_dispatch(profile))
    assert result.outcome is ConnectionOutcome.SUCCESS, (
        f"production service must probe an unverified profile successfully, got {result.outcome.value}"
    )
    assert len(transport.calls) == 1
    body = transport.calls[0]["json_body"]
    assert body["messages"] == [{"role": "user", "content": "ping"}]
    assert "sk-prod-svc-fake-key" not in repr(result)


def test_production_connection_service_empty_key_fail_closed(monkeypatch):
    """GATE-P0: an empty key must fail closed WITHOUT sending any request."""
    from dataclasses import replace
    from src.qml_bootstrap import build_production_connection_service
    from src.core.provider_presets import create_custom_provider_profile
    from src.core.provider_protocol import ProviderCapabilities
    from src.core.connection_test import ConnectionOutcome
    from src.services.retry_policy import RetryExecutor, RetryPolicy
    from tests.unit.test_connection_test import _FakeTransport

    profile = replace(
        create_custom_provider_profile(
            profile_id="prod-svc-empty",
            display_name="Prod empty",
            base_url="https://prod-svc-empty.test/v1",
            model="m",
            capabilities=ProviderCapabilities(text=True),
        ),
        needs_connection_verification=True,
    )
    transport = _guarded_transport([])
    service = build_production_connection_service(
        transport=transport,
        retry_executor=RetryExecutor(RetryPolicy(max_retries=0), sleeper=lambda d: None),
    )
    result = service(profile, "", processing_dispatch=_fixed_dispatch(profile))
    assert result.outcome is not ConnectionOutcome.SUCCESS
    assert transport.calls == [], "no transport request may be sent for an empty key"


def test_production_connection_service_plain_pong_succeeds(monkeypatch):
    """GATE-P0: production service + FakeTransport returning plain "pong"
    must succeed for an unverified profile — the probe does not require a
    business JSON response."""
    from dataclasses import replace
    from src.qml_bootstrap import build_production_connection_service
    from src.core.provider_presets import create_custom_provider_profile
    from src.core.provider_protocol import ProviderCapabilities
    from src.core.connection_test import ConnectionOutcome
    from src.services.retry_policy import RetryExecutor, RetryPolicy
    from tests.unit.test_connection_test import _FakeTransport, _minimal_probe_response

    profile = replace(
        create_custom_provider_profile(
            profile_id="prod-svc-pong",
            display_name="Prod pong",
            base_url="https://prod-svc-pong.test/v1",
            model="test-model",
            capabilities=ProviderCapabilities(text=True),
        ),
        needs_connection_verification=True,
    )
    transport = _guarded_transport([_minimal_probe_response(content="pong")])
    service = build_production_connection_service(
        transport=transport,
        retry_executor=RetryExecutor(
            RetryPolicy(max_retries=0),
            sleeper=lambda d: None,
        ),
    )
    result = service(profile, "sk-prod-svc-pong-key", processing_dispatch=_fixed_dispatch(profile))
    assert result.outcome is ConnectionOutcome.SUCCESS, (
        f"plain 'pong' through the production service must succeed, got {result.outcome.value}"
    )
    assert len(transport.calls) == 1
