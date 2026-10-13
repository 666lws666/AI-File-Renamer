# Qt Application Main-Thread Lifetime Implementation Plan

**Status: FAILED and superseded.** The application-held wrapper proposal below failed its native GC regression and was withdrawn; moving the reference to a global/local also failed repeated GC. Do not execute this historical hypothesis. Continue with [Qt native thread ownership fix](2026-10-11-qt-native-thread-ownership.md), which validates the official binding correction and does not introduce a thread pin or session fixture. A prior diagnostic full-suite pass did not establish this plan's lifetime contract.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with TDD, fresh scoped spec/quality review and root-owned verification/Git.

**Goal:** Keep the native main Qt thread valid through ordinary garbage collection and multiple runtime lifetimes without weakening native affinity checks.

**Architecture:** A small application-lifetime helper holds the actual main QThread wrapper on QApplication. Production bootstrap and the test session enter the same contract. The retained reference is not an authorization token; current native affinity is still checked on every call.

**Tech Stack:** Project Windows Python3.14.5/PySide6 6.11.1, shiboken6, pytest fresh subprocess regressions and existing runtime cleanup.

## Global Constraints

- Work only in the existing isolated codex/local-privacy-mode checkout after checkpoint492114d. One source writer; root owns Git. No main edits, merge, push or release.
- Preserve all current native Qt affinity checks, managed processing authority, file-operation lane, Watch lifecycle, configuration and user consent. Do not use Python thread IDs or a cached wrapper as an authority substitute.
- Preserve ordinary GC. No dependency upgrade/install, native Qt deletion/patching, OS/firewall/ACL changes, model/API/credential/private-input access or Golden updates.
- Own the reference for the QApplication lifetime, not for a QmlRuntime/controller lifetime. Acquire via QThread.currentThread and validate native main/current affinity before publication. Repeated calls keep the same valid reference; wrong-thread/invalid application calls fail with QT_APPLICATION_THREAD_ERROR and do not replace the existing owner.
- Tests use production _ensure_app, not a fixture-only workaround. Every fresh subprocess isolates user/temp directories and denies network and real native credentials. A caught forbidden call still causes failure.
- Original native access-violation and null-thread failures remain failures. A diagnostic full-suite strong-reference experiment is not the durable regression Gate.

## Evidence and scope

On the current runtime, QApplication.thread followed by cyclic temporary QObject.thread and ordinary gc.collect can leave a still-valid application with both native affinity accessors returning None. The private diagnostic records a fresh failing child exit1 and control exit0, without product modules. Exact native deallocation stack and the earlier full-suite transient owner were not instrumented. This application-side mitigation must first pass the same collection sequence via actual production bootstrap.

Qt documents currentThread as the actual current QThread and isMainThread/isCurrentThread as native checks:
https://doc.qt.io/qt-6/qthread.html

## Task 1: production lifetime owner with guarded native regression

**Files:**
- Create src/utils/qt_application.py.
- Modify src/qml_bootstrap.py: one helper import and _ensure_app return.
- Modify tests/conftest.py: one session autouse fixture.
- Create tests/unit/test_qt_application_lifetime.py.
No other source/test files.

**Interfaces:**
- Consumes existing _ensure_app() -> QApplication and build_qml_runtime(...), QmlRuntime.cleanup() -> bool and assert_zero_warnings().
- Produces retain_application_thread(app: QApplication) -> QApplication.
- Existing public bootstrap API and Qt environment behavior are unchanged. Only the test fixture sets offscreen when no explicit platform is set.

- [ ] Step1: create the following complete regression file, before changing production or shared conftest:

```python
"""Native fresh-process regressions for application-owned Qt thread lifetime."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[2]

_GUARDS = r"""
import os, sys, pathlib, tempfile, socket, atexit, threading, faulthandler
sys.dont_write_bytecode = True
isolated = pathlib.Path(tempfile.mkdtemp(
    prefix='qt-app-lifetime-', dir=os.environ['XUXIA_QT_LIFETIME_TEST_ROOT']))
for name in ('LOCALAPPDATA', 'APPDATA', 'TMP', 'TEMP'):
    directory = isolated / name.lower()
    directory.mkdir()
    os.environ[name] = str(directory)
tempfile.tempdir = str(isolated / 'temp')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ.pop('UPDATE_GOLDENS', None)
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
blocked_calls = []
def forbidden(*args, **kwargs):
    blocked_calls.append('forbidden external access')
    raise AssertionError('Real network and credential access are forbidden')
for name in ('connect', 'connect_ex', 'sendto'):
    setattr(socket.socket, name, forbidden)
for name in ('getaddrinfo', 'create_connection'):
    setattr(socket, name, forbidden)
import keyring, keyring.core
from keyring.backends import Windows
from keyring.backends.fail import Keyring
keyring.set_keyring(Keyring())
for owner in (keyring, keyring.core):
    for name in ('get_password', 'set_password', 'delete_password', 'get_credential'):
        if hasattr(owner, name):
            setattr(owner, name, forbidden)
for name in ('get_password', 'set_password', 'delete_password', 'get_credential',
             '_read_credential', '_resolve_credential', '_set_password', '_delete_password'):
    setattr(Windows.WinVaultKeyring, name, forbidden)
for name in ('CredRead', 'CredWrite', 'CredDelete', 'CredEnumerate'):
    if hasattr(Windows.win32cred, name):
        setattr(Windows.win32cred, name, forbidden)
faulthandler.enable(all_threads=True)
def exit_evidence():
    print('CHILD_FORBIDDEN_ACCESS_ATTEMPTS=' + str(len(blocked_calls)), flush=True)
    print('CHILD_ATEXIT_THREADS=' +
          repr([(t.name, t.is_alive(), t.daemon) for t in threading.enumerate()]),
          flush=True)
atexit.register(exit_evidence)
"""


def _run_child(tmp_path, body):
    env = os.environ.copy()
    env.pop("UPDATE_GOLDENS", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["XUXIA_QT_LIFETIME_TEST_ROOT"] = str(tmp_path)
    script = _GUARDS + "\n" + textwrap.dedent(body) + (
        "\nprint('CHILD_CASE_PASSED', flush=True)\n"
        "raise SystemExit(97 if blocked_calls else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=ROOT, env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "CHILD_CASE_PASSED" in result.stdout, output
    assert "CHILD_FORBIDDEN_ACCESS_ATTEMPTS=0" in result.stdout, output
    assert "CHILD_ATEXIT_THREADS=[('MainThread', False, False)]" in result.stdout, output
    return output


def test_application_survives_transient_owner_gc(tmp_path):
    _run_child(tmp_path, """
        import gc
        from PySide6.QtCore import QObject, QThread
        from shiboken6 import isValid
        from src.qml_bootstrap import _ensure_app
        assert gc.isenabled()
        app = _ensure_app()
        # No local strong QThread reference is held across these collections.
        app.thread()
        for _ in range(3):
            transient = QObject()
            transient.self_cycle = transient
            transient.thread()
            del transient
            gc.collect()
            assert isValid(app)
            assert app.thread() is not None, 'native main thread disappeared'
            assert QThread.currentThread() is not None
            assert app.thread().isCurrentThread()
        assert _ensure_app() is app
    """)


def test_repeated_bootstrap_preserves_native_main_thread(tmp_path):
    _run_child(tmp_path, """
        from PySide6.QtCore import QThread
        from src.qml_bootstrap import _ensure_app
        app = _ensure_app()
        native_id = id(QThread.currentThread())
        for _ in range(5):
            assert _ensure_app() is app
            assert id(QThread.currentThread()) == native_id
            assert app.thread() == QThread.currentThread()
            assert app.thread().isCurrentThread()
    """)


def test_wrong_thread_rejected_without_changing_app_owner(tmp_path):
    _run_child(tmp_path, """
        import threading
        from PySide6.QtCore import QObject, QThread
        from src.qml_bootstrap import _ensure_app
        from src.utils.qt_application import retain_application_thread
        app = _ensure_app()
        original = app._xuxia_main_thread_lifetime_owner
        failures = []
        def wrong_thread():
            try:
                _ensure_app()
            except RuntimeError as exc:
                failures.append(str(exc))
            else:
                failures.append('unexpected success')
        worker = threading.Thread(target=wrong_thread)
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert failures == ['QT_APPLICATION_THREAD_ERROR']
        assert app._xuxia_main_thread_lifetime_owner is original
        assert app.thread() == QThread.currentThread()
        for invalid in (None, object(), QObject()):
            try:
                retain_application_thread(invalid)
            except RuntimeError as exc:
                assert str(exc) == 'QT_APPLICATION_THREAD_ERROR'
            else:
                raise AssertionError('invalid application was accepted')
        assert app._xuxia_main_thread_lifetime_owner is original
    """)


def test_owner_survives_two_real_runtime_cleanups(tmp_path):
    _run_child(tmp_path, """
        import gc
        from PySide6.QtCore import QObject, QThread
        from src.models.app_config import AppConfig
        from src.qml_bootstrap import _ensure_app, build_qml_runtime
        class FakeCredentials:
            def get(self, service, account):
                return None
            def set(self, service, account, value):
                raise AssertionError('unexpected credential write')
            def delete(self, service, account):
                raise AssertionError('unexpected credential deletion')
        class NoConnection:
            def execute(self, *args, **kwargs):
                raise AssertionError('unexpected connection test')
        app = _ensure_app()
        native_id = id(QThread.currentThread())
        for index in range(2):
            runtime = build_qml_runtime(
                live_config=AppConfig(),
                config_file=isolated / ('runtime-' + str(index)) / 'settings.json',
                credential_store=FakeCredentials(),
                connection_test_service=NoConnection(),
                usage_recorder=None,
            )
            runtime.assert_zero_warnings()
            assert runtime.cleanup() is True
            runtime.assert_zero_warnings()
            del runtime
            transient = QObject()
            transient.self_cycle = transient
            transient.thread()
            del transient
            gc.collect()
            assert _ensure_app() is app
            assert id(QThread.currentThread()) == native_id
            assert app.thread().isCurrentThread()
    """)

```

- [ ] Step2: run only test_application_survives_transient_owner_gc with the root-supplied complete strong Windows guard. Expected real RED is a valid QApplication with disappeared native main thread, not a missing import, test typo, skip or a native crash called passing. Retain raw output and actual pytest/native exit.

- [ ] Step3: add the complete helper below:

```python
"""Keep the native Qt main-thread wrapper alive for the application lifetime.

This reference is lifetime ownership only. Callers must still perform their
native Qt affinity checks; it is not a permission or processing-authority token.
"""

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

_OWNER_ATTRIBUTE = "_xuxia_main_thread_lifetime_owner"
_MISSING = object()


def retain_application_thread(app: QApplication) -> QApplication:
    """Retain the current native main QThread on an existing live QApplication."""
    if (not isinstance(app, QApplication) or not isValid(app)
            or not QThread.isMainThread()):
        raise RuntimeError("QT_APPLICATION_THREAD_ERROR")
    current = QThread.currentThread()
    if (current is None or not isValid(current) or not current.isCurrentThread()
            or app.thread() != current):
        raise RuntimeError("QT_APPLICATION_THREAD_ERROR")
    retained = getattr(app, _OWNER_ATTRIBUTE, _MISSING)
    if retained is not _MISSING:
        if (not isinstance(retained, QThread) or not isValid(retained)
                or retained != current):
            raise RuntimeError("QT_APPLICATION_THREAD_ERROR")
    else:
        setattr(app, _OWNER_ATTRIBUTE, current)
    return app

```

Add this import to src/qml_bootstrap.py:

```python
from src.utils.qt_application import retain_application_thread
```

Replace only the existing _ensure_app return statement:

```python
def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return retain_application_thread(app)
```

Append only this fixture to existing tests/conftest.py:

```python
@pytest.fixture(scope="session", autouse=True)
def qt_application_lifetime():
    """Use the production Qt lifetime contract before transient test objects."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from src.qml_bootstrap import _ensure_app
    app = _ensure_app()
    yield app

```

- [ ] Step4: run all four new native subprocess tests and existing managed Batch file-operation/thread-affinity tests under the root-supplied guard. Each child must exit0, preserve ordinary GC, deny all external access, assert real native affinity and actual thread exit. Both real runtime creation/cleanup cycles must assert warnings0 and cleanup True.
- [ ] Step5: self-review exact four paths; retain source hashes and full commands/output/native exits/forbidden counters in the private report. Obtain fresh scoped spec/quality review. Root independently re-runs covering tests, complete non-screenshot tests, existing screenshots with UPDATE absent and acceptance with isolated in-memory credentials. Root checkpoints only these four paths after actual verification.

Covering tests:
- tests/unit/test_qt_application_lifetime.py
- tests/integration/test_managed_batch_file_operations.py
- tests/integration/test_managed_file_operation_lane.py
- tests/integration/test_managed_file_operation_runtime.py
- tests/qml/test_file_operation_row_locks.py

The root-provided guarded command must first verify those existing test paths; no guessed test path, alternate runtime, GC disablement or warning suppression.

Checkpoint: fix: retain Qt main thread for application lifetime

## Remaining work

Managed Watch analysis/file-operation composition and resource UI/manual/package completion are independent unfinished tasks. This task does not claim global application-thread drain, real model quality or final product completion.
