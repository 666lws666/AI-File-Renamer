# Qt native thread ownership fix — superseding failed Python pin

**Status: scoped implementation and verification complete.** This fixes the
reproduced binding lifetime defect. It does not complete managed Watch,
local-resource UI, user manuals, or the complete local-privacy product Gate.
> For agentic workers: use subagent-driven-development and test-driven-development for this bounded task.
Goal: eliminate the reproducible QObject.thread return-owner main-thread loss without retaining arbitrary objects, disabling GC or weakening safety checks.
Architecture: use official PySide6 6.12.0's return-ownership exemption, exactly pinned. Ordinary production bootstrap remains unchanged. Native fresh-child regressions prove the real non-owning lifetime and actual runtime cleanup.
Tech: project Python 3.14.5 / PySide6 6.12.0 Windows x64 candidate.

## Global constraints
- Worktree only D:/文件AI-AGENT/.worktrees/ai-smart-naming, branch codex/local-privacy-mode, HEAD f1a2e8f2b44735117ea41c2839624a3a7e630256.
- Root owns Git and review; implementer may not stage/commit/amend/push/merge or alter shared venv.
- Prior four-file app-owner patch FAILED. Snapshot it first, then withdraw only those root-owned edits via apply_patch; preserve all unrelated/private artifacts.
- No real network/API/credentials during tests; use existing guarded candidate runner and ordinary GC. No Golden or main changes.
- Official candidate six wheels259201855bytes with SHA source/provenance in ignored qt612-candidate/manifest.json. Existing project venv remains6.11.1, candidate6.12.0 only.
- This supersedes the app-level helper/owner-cache/session-fixture design, not application safety or existing tests. No new thread cache/helper/fixture is introduced.
- No Watch/resource/model activation; full branch and packaged/native Gates remain root responsibilities.

## Task 1: withdraw failed pin; pin verified binding; keep real native regressions
Files allowed:
- requirements.txt: replace PySide6>=6.8.0 with PySide6==6.12.0 and comment explaining non-owning QObject.thread regression.
- src/qml_bootstrap.py: withdraw only import retain_application_thread and restore original return app in _ensure_app. Exact remaining tracked diff must be zero.
- tests/conftest.py: withdraw only appended qt_application_lifetime session fixture. Exact remaining tracked diff must be zero.
- src/utils/qt_application.py: delete newly introduced untracked failed helper; after ignored backup exists.
- tests/unit/test_qt_application_lifetime.py: replace new untracked failed helper tests with complete native regression code below.
- Only ignored QA backup/private report may be added outside the named paths; no other tracked files.
Interfaces: consumes existing production _ensure_app(), build_qml_runtime(); no product interface changes.

Steps:
- [x] Copy exact four failed files into ignored qa-current/local-privacy/qt612-candidate/failed-pin-backup; no wildcard. Record hashes. Do not delete until backup verified.
- [x] Withdraw failed source/fixture/helper only, write regression code below while requirements still old.
- [x] Execute only first native regression with old project Python and guarded runner: actual failure expected, native1, no external access. Record raw RED.
- [x] Update requirements exact code:
```text
# GUI Framework
# QObject.thread() must not transfer main-thread wrapper ownership to its caller.
PySide6==6.12.0
```
- [x] Run guarded candidate five-file covering suite, exact command below, require no failures/native0/forbidden0. Report project-shared interpreter remains6.11.1.
- [x] Self-review: bootstrap/conftest zero tracked diff; failed helper absent; native regression assertions unchanged; no source beyond scope. Root commits after independent review/Gates.

Complete test file:
```python
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
```

Commands (PowerShell cwd active worktree, require_escalated if sandbox executor setup fails):
```powershell
& 'D:/文件AI-AGENT/.venv/Scripts/python.exe' -B 'tests/screenshots/qa-current/local-privacy/qt612-candidate/run_guarded_pytest.py' tests/unit/test_qt_application_lifetime.py -k application_survives_repeated_transient_owner_gc
Write-Output ('RED_NATIVE_EXIT=' + $LASTEXITCODE)
exit $LASTEXITCODE
```
```powershell
& 'D:/文件AI-AGENT/.worktrees/ai-smart-naming/tests/screenshots/qa-current/local-privacy/qt612-candidate/venv/Scripts/python.exe' -B 'tests/screenshots/qa-current/local-privacy/qt612-candidate/run_guarded_pytest.py' tests/unit/test_qt_application_lifetime.py tests/integration/test_managed_batch_file_operations.py tests/integration/test_managed_file_operation_lane.py tests/integration/test_managed_file_operation_runtime.py tests/qml/test_file_operation_row_locks.py
Write-Output ('GREEN_NATIVE_EXIT=' + $LASTEXITCODE)
exit $LASTEXITCODE
```
Expected candidate cover79tests (previous80 minus one helper-specific test), but report actual raw pytest count; any mismatch must be explained, never assume expectedcount PASS.
Report .superpowers/sdd/qt-native-binding-fix-report.md; return only status/brief actual tests/concerns, no Git.

## Task 2: preserve ICU compatibility Gate across the observed Windows layouts

Evidence: the first candidate package Gate returned 22 passed, 1 failed. The
failure was the hard-coded `PySide6/Qt6Core.dll` location, not a symbol check.
Read-only inspection found the candidate DLL at `_internal/Qt6Core.dll`;
its PE import table still requires the Windows `icuuc.dll` symbols. The real
candidate EXE smoke passed, but this does not waive the ICU Gate.

Allowed tracked file: `tests/packaging/test_qt_icu_compatibility.py` only.
Add a local `_packaged_qt_core_path(internal)` resolver for precisely the two
observed layouts: `internal / 'Qt6Core.dll'` and
`internal / 'PySide6/Qt6Core.dll'`. Require exactly one existing file; missing
or ambiguous candidates must fail. Do not search arbitrary DLLs or omit the
non-empty imports / required-symbol-subset assertions. Keep the existing ICU
selection and PE symbol validation unchanged.

Add focused tests in the same file using synthetic temporary paths for both
layouts, no DLL present, and both DLLs present. First run these resolver tests
before implementing the resolver and retain the failing output. Then implement
the resolver and replace only the original hard-coded Qt path with its result.
Run the guarded candidate packaging Gate against the freshly built QA package,
not the pre-existing dist. No skip, xfail, network, credentials, Golden change,
staging or commit by the implementer. Root owns the artifact-input adapter and
installed-to-bundled binary inventory, independent review and final Git checkpoint.

The failure and correction must both remain in the validation record. This is
a test-layout compatibility correction, not a new product feature or a claim
that all local privacy-mode integration is complete.

## Verified results (2026-10-11)

- Failed Python-held reference proposal was backed up and withdrawn. Production
  bootstrap and the shared pytest fixture have no change; no pin/helper remains.
- Same native regression: original Qt6.11.1 fails; isolated official6.12.0 passes.
  Covering suite:79passed, three existing Pydantic warnings, native exit0.
- Final non-screenshot suite:4520passed,3existing skips,4existing warnings;
  native exit0 and forbidden external-access attempts0.
- Formal screenshot suite, UPDATE_GOLDENS absent:66passed,1designed skip,
  86existing Pillow warnings; native exit0 and no baseline/assertion changes.
- Acceptance:186/186, native exit0, using the existing in-memory credential
  fixture with native Credential Manager access denied.
- Candidate-only Windows build and all27packaging tests pass, including actual
  isolated EXE smoke and unchanged ICU symbol validation. Six critical bundled
  Qt/Shiboken binaries exactly match the installed verified candidate hashes.
  Original22pass/1fail old-layout Gate remains a recorded failure.
- Twelve native row-lock screenshots (three locales, two widths, two lock
  states) have clear CJK and no row clipping. Real Win32 clicks include an
  unlocked positive control and locked-action negatives, zero QML warnings.
  This is row-level evidence, not a whole-window local-mode acceptance claim.
- Shared project venv remains6.11.1. All passing Qt validation used the separate
  same-Python3.14.5 candidate environment. No main checkout or installed EXE
  was upgraded, and no formal Golden was regenerated.
- Final full-suite atexit still contains one daemon2-second Timer targeting
  `DebounceScheduler._on_fire`. Its source/lifecycle will be investigated in
  the subsequent Watch work; this is not a global-drain PASS.

Both bounded tasks received independent spec-compliance and code-quality
approval. Preserve the old native failures; do not reclassify them as passes.
