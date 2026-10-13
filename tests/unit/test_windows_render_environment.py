"""Process-local render-loop policy at the official desktop entry."""

from types import SimpleNamespace

import pytest

from src import main_qml


@pytest.fixture(autouse=True)
def isolated_render_environment(monkeypatch):
    """Track even an initially absent key so production insertion is undone."""
    original = main_qml.os.environ.get("QSG_RENDER_LOOP")
    monkeypatch.setenv("QSG_RENDER_LOOP", original if original is not None else "")
    if original is None:
        monkeypatch.delenv("QSG_RENDER_LOOP")


def test_windows_defaults_to_basic(monkeypatch):
    monkeypatch.setattr(main_qml.sys, "platform", "win32")
    monkeypatch.delenv("QSG_RENDER_LOOP", raising=False)

    main_qml.configure_render_environment()

    assert main_qml.os.environ["QSG_RENDER_LOOP"] == "basic"


@pytest.mark.parametrize("explicit", ["threaded", "basic", "", "custom"])
def test_windows_preserves_explicit_render_loop(monkeypatch, explicit):
    monkeypatch.setattr(main_qml.sys, "platform", "win32")
    monkeypatch.setenv("QSG_RENDER_LOOP", explicit)

    main_qml.configure_render_environment()

    assert main_qml.os.environ["QSG_RENDER_LOOP"] == explicit


@pytest.mark.parametrize("platform", ["linux", "darwin"])
@pytest.mark.parametrize("explicit", [None, "threaded"])
def test_non_windows_environment_is_untouched(monkeypatch, platform, explicit):
    monkeypatch.setattr(main_qml.sys, "platform", platform)
    if explicit is None:
        monkeypatch.delenv("QSG_RENDER_LOOP", raising=False)
    else:
        monkeypatch.setenv("QSG_RENDER_LOOP", explicit)
    before = dict(main_qml.os.environ)

    main_qml.configure_render_environment()

    assert dict(main_qml.os.environ) == before


def test_windows_policy_is_idempotent(monkeypatch):
    monkeypatch.setattr(main_qml.sys, "platform", "win32")
    monkeypatch.delenv("QSG_RENDER_LOOP", raising=False)
    main_qml.configure_render_environment()
    before = dict(main_qml.os.environ)

    main_qml.configure_render_environment()

    assert dict(main_qml.os.environ) == before


def test_application_selects_render_loop_before_construction(monkeypatch):
    monkeypatch.setattr(main_qml.sys, "platform", "win32")
    monkeypatch.delenv("QSG_RENDER_LOOP", raising=False)
    app = object()

    class ControlledApplication:
        @staticmethod
        def instance():
            return None

        def __new__(cls, argv):
            assert main_qml.os.environ.get("QSG_RENDER_LOOP") == "basic"
            return app

    monkeypatch.setattr(main_qml, "QApplication", ControlledApplication)
    monkeypatch.setattr(main_qml, "_configure_application", lambda selected: None)

    assert main_qml._application() is app


def test_application_reuses_existing_instance(monkeypatch):
    app = object()

    class ExistingApplication:
        @staticmethod
        def instance():
            return app

        def __new__(cls, argv):
            pytest.fail("Existing QApplication must not be replaced")

    monkeypatch.setattr(main_qml, "QApplication", ExistingApplication)
    monkeypatch.setattr(main_qml, "_configure_application", lambda selected: None)

    assert main_qml._application() is app


@pytest.mark.parametrize("smoke", [False, True])
def test_official_entry_applies_policy_before_runtime(monkeypatch, tmp_path, smoke):
    from src import main

    monkeypatch.setattr(main_qml.sys, "platform", "win32")
    monkeypatch.delenv("QSG_RENDER_LOOP", raising=False)
    app = SimpleNamespace(exec=lambda: 0, processEvents=lambda: None)
    current = None

    class ControlledApplication:
        @staticmethod
        def instance():
            return current

        def __new__(cls, argv):
            nonlocal current
            assert main_qml.os.environ.get("QSG_RENDER_LOOP") == "basic"
            current = app
            return app

    def builder(**kwargs):
        assert current is app
        assert main_qml.os.environ["QSG_RENDER_LOOP"] == "basic"
        return SimpleNamespace(
            root=SimpleNamespace(show=lambda: None),
            warnings=[],
            manage_window_close=lambda **kwargs: None,
            assert_zero_warnings=lambda: None,
            cleanup=lambda **kwargs: True,
        )

    monkeypatch.setattr(main_qml, "QApplication", ControlledApplication)
    monkeypatch.setattr(main_qml, "_configure_application", lambda selected: None)
    monkeypatch.setattr(main_qml, "_verify_media_dependencies", lambda directory: {})
    monkeypatch.setattr(main_qml.run_application, "__kwdefaults__", {"runtime_builder": builder})
    monkeypatch.setattr(main_qml.run_smoke_test, "__kwdefaults__", {
        "report_path": None, "runtime_builder": builder,
    })

    args = ["--smoke-test", "--data-dir", str(tmp_path / "smoke")] if smoke else []
    assert main.main(args) == 0
