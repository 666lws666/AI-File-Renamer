"""Native Qt binding regressions using production bootstrap and ordinary GC."""

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
    prefix='qt-native-lifetime-', dir=os.environ['XUXIA_QT_LIFETIME_TEST_ROOT']))
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

def test_application_survives_repeated_transient_owner_gc(tmp_path):
    _run_child(tmp_path, """
        import gc
        from PySide6.QtCore import QObject, QThread
        from shiboken6 import getCppPointer, isValid
        from src.qml_bootstrap import _ensure_app
        assert gc.isenabled()
        app = _ensure_app()
        app.thread()
        native_pointer = getCppPointer(QThread.currentThread())
        # Only native integer identity crosses GC, never a strong QThread pin.
        for _ in range(10):
            transient = QObject()
            transient.self_cycle = transient
            transient.thread()
            del transient
            gc.collect()
            assert isValid(app)
            assert app.thread() is not None, 'native main thread disappeared'
            assert QThread.currentThread() is not None
            assert getCppPointer(QThread.currentThread()) == native_pointer
            assert app.thread().isCurrentThread()
        assert _ensure_app() is app
    """)

def test_returned_wrapper_stays_valid_after_query_owner_gc(tmp_path):
    _run_child(tmp_path, """
        import gc
        from PySide6.QtCore import QObject, QThread
        from shiboken6 import getCppPointer, isValid
        from src.qml_bootstrap import _ensure_app
        app = _ensure_app()
        retained = QThread.currentThread()
        native_pointer = getCppPointer(retained)
        for _ in range(3):
            transient = QObject()
            transient.self_cycle = transient
            assert getCppPointer(transient.thread()) == native_pointer
            del transient
            gc.collect()
            assert isValid(retained), 'query owner invalidated non-owning QThread wrapper'
            assert getCppPointer(retained) == native_pointer
            assert retained.isCurrentThread()
            assert app.thread() is not None
    """)

def test_main_thread_survives_two_real_runtime_cleanups(tmp_path):
    _run_child(tmp_path, """
        import gc
        from PySide6.QtCore import QObject, QThread
        from shiboken6 import getCppPointer
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
        native_pointer = getCppPointer(QThread.currentThread())
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
            assert QThread.currentThread() is not None
            assert getCppPointer(QThread.currentThread()) == native_pointer
            assert app.thread().isCurrentThread()
    """)
