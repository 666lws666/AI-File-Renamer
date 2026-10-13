"""M1 Batch Capture — subprocess: warnings capture, assert_fn execution, golden write."""
import json, os, sys
from pathlib import Path

_PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QUrl, QBuffer
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtQuick import QQuickView

SRC = _PROJECT / "src"
QML_DIR = SRC / "ui_qml"
CASES_JSON = os.environ.get("M1_CASES_JSON")
OUT_DIR = Path(os.environ.get("M1_OUTPUT_DIR", str(_PROJECT / "tests" / "screenshots" / "qa-current" / "m1")))
UPDATE = os.environ.get("UPDATE_GOLDENS", "") in ("1", "true", "yes")
GD = _PROJECT / "tests" / "screenshots" / "golden" / "m1"

if CASES_JSON is None:
    print("FATAL: M1_CASES_JSON not set", file=sys.stderr); sys.exit(1)

# Read case IDs from JSON (not functions — functions come from registry import)
case_specs = json.loads(Path(CASES_JSON).read_text(encoding="utf-8"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Import registry to get callbacks
from tests.screenshots.m1_cases import CANONICAL_CASES
registry = {c.case_id: c for c in CANONICAL_CASES}

app = QGuiApplication(sys.argv)
if os.name == "nt":
    app.setFont(QFont("Microsoft YaHei UI", 10))
results = []

for spec in case_specs:
    cid = spec["case_id"]; fn = spec["filename"]
    w = spec["width"]; h = spec["height"]; loc = spec["locale"]

    case = registry.get(cid)
    if case is None:
        print(f"FAIL {cid}: not in registry", file=sys.stderr); continue

    from src.utils.i18n.service import I18n
    from src.controllers.mock_batch_controller import MockBatchController

    i18n = I18n(); i18n.set_locale(loc)
    ctrl = MockBatchController()
    case.setup_fn(ctrl, i18n)
    if cid.startswith("filter_"):
        print(f"DEBUG {cid}: filter={ctrl.statusFilter} vc={ctrl.visibleCount}", file=sys.stderr)

    v = QQuickView(); v.engine().addImportPath(str(SRC)); v.setResizeMode(QQuickView.SizeRootObjectToView)
    qml_warnings = []
    v.engine().warnings.connect(lambda msgs: [qml_warnings.append(m.toString()) for m in msgs])

    v.rootContext().setContextProperty("i18n", i18n)
    v.rootContext().setContextProperty("batchController", ctrl)
    v.setSource(QUrl.fromLocalFile(str(QML_DIR / "ScreenshotShell.qml")))

    if v.status() != QQuickView.Ready:
        v.close(); print(f"FAIL {cid}: QML error: {[e.toString() for e in v.errors()]}", file=sys.stderr); continue

    # Post-load action
    post_ok = True
    try:
        case.post_fn(v.rootObject(), ctrl, i18n)
    except Exception as e:
        post_ok = False; print(f"FAIL {cid}: post_fn error: {e}", file=sys.stderr)

    v.resize(w, h); v.show(); QGuiApplication.processEvents()

    # Assert state via AssertionRecorder
    assert_ok = True; assertion_records = []; assertion_count = 0; state = {}
    try:
        if cid.startswith("filter_"):
            print(f"DEBUG_PRE_ASSERT {cid}: filter={ctrl.statusFilter} vc={ctrl.visibleCount}", file=sys.stderr)
        recorder = case.assert_fn(v.rootObject(), ctrl, i18n)
        assertion_count = len(recorder.records)
        assertion_records = [{"name": r.name, "actual": str(r.actual), "expected": str(r.expected), "passed": r.passed} for r in recorder.records]
        assert_ok = all(r.passed for r in recorder.records) and assertion_count > 0
        state = {"assertion_count": assertion_count}
    except Exception as e:
        import traceback
        assert_ok = False; state = {"error": str(e), "traceback": traceback.format_exc()[:500], "assertion_count": assertion_count}

    img = v.grabWindow()
    if img is None: v.close(); print(f"FAIL {cid}: grabWindow None", file=sys.stderr); continue

    buf = QBuffer(); buf.open(QBuffer.OpenModeFlag.WriteOnly); img.save(buf, "PNG"); data = bytes(buf.data())
    v.close()

    out_png = OUT_DIR / f"{cid}.png"; out_png.write_bytes(data)

    import hashlib
    # Ensure JSON-serializable state snapshot
    safe_state = {}
    for k, v in state.items():
        try: json.dumps({k: v}); safe_state[k] = v
        except (TypeError, ValueError): safe_state[k] = str(v)

    result = {
        "case_id": cid, "filename": fn, "platform": QGuiApplication.platformName().lower(),
        "executable": sys.executable, "pyside6_path": str(SRC.parent / "Lib" / "site-packages" / "PySide6"),
        "setup_executed": True, "post_executed": post_ok, "assert_executed": True,
        "assert_passed": assert_ok, "assertion_count": assertion_count, "assertions": assertion_records,
        "state_snapshot": safe_state, "warnings": qml_warnings,
        "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
    }

    if UPDATE:
        gp = GD / f"{fn}.png"; gp.parent.mkdir(parents=True, exist_ok=True); gp.write_bytes(data)

    results.append(result)
    status = "OK" if (not qml_warnings and post_ok and assert_ok) else "WARN"
    print(f"{status} {cid} {len(data)}b warnings={len(qml_warnings)} assert_ok={assert_ok}")

# Write manifest
manifest_path = OUT_DIR / "manifest.json"
manifest_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"DONE {len(results)} cases, manifest: {manifest_path}")
sys.exit(0 if all(r["warnings"] == [] and r["assert_passed"] for r in results) else 1)
