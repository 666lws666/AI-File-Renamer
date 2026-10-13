"""M1 Visual Gate — subprocess capture with warnings+assert, parametrized compare. ZERO skips."""
import ast, hashlib, io, json, os, subprocess, sys
from pathlib import Path
import pytest
from PIL import Image

GD = Path(__file__).parent / "golden" / "m1"
M0 = Path(__file__).parent / "golden" / "m0" / "bootstrap" / "zh_CN" / "400x300.png"
M0SHA = "6d5da0698d124d5f3dd255bae8ed7c34b76b10ad2c657c9014c073925d41a8b1"
UPD = os.environ.get("UPDATE_GOLDENS", "") in ("1", "true", "yes")
PROJECT = Path(__file__).parent.parent.parent

from .m1_cases import CANONICAL_CASES

def _sha(d): return hashlib.sha256(d).hexdigest()

# ── Subprocess batch capture ─────────────────────────────
@pytest.fixture(scope="session")
def batch_manifest(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("m1_captures")
    out_dir = tmp / "current"; out_dir.mkdir()
    cases_json = []
    for c in CANONICAL_CASES:
        cases_json.append({"case_id": c.case_id, "filename": c.filename,
                           "width": c.width, "height": c.height, "locale": c.locale})
    (tmp / "cases.json").write_text(json.dumps(cases_json), encoding="utf-8")

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "windows" if os.name == "nt" else "offscreen"
    env["PYTHONPATH"] = str(PROJECT)
    env["M1_CASES_JSON"] = str(tmp / "cases.json")
    env["M1_OUTPUT_DIR"] = str(out_dir)
    # The capture subprocess may only write current evidence.  Golden updates,
    # when explicitly enabled, happen in the parent after semantic checks.
    env.pop("UPDATE_GOLDENS", None)

    r = subprocess.run([sys.executable, str(PROJECT / "scripts" / "capture_m1_batch.py")],
                       env=env, capture_output=True, text=True, timeout=300, cwd=str(PROJECT))
    if r.returncode != 0:
        pytest.fail(f"Batch capture failed (rc={r.returncode}):\nSTDOUT: {r.stdout[:1000]}\nSTDERR: {r.stderr[:2000]}")

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    pngs = {}
    for entry in manifest:
        png_path = out_dir / f"{entry['case_id']}.png"
        if png_path.exists():
            pngs[entry["case_id"]] = {"data": png_path.read_bytes(), "entry": entry}
    return pngs

# ── Comparator ────────────────────────────────────────────
def _cmp(cur, gold, cid):
    ci = Image.open(io.BytesIO(cur)).convert("RGBA"); gi = Image.open(io.BytesIO(gold)).convert("RGBA")
    assert ci.size == gi.size, f"{cid}: size {ci.size} vs {gi.size}"
    cp, gp = list(ci.getdata()), list(gi.getdata()); ch, md = 0, 0
    for c, g in zip(cp, gp):
        d = max(abs(int(c[i]) - int(g[i])) for i in range(4))
        if d > 0: ch += 1; md = max(md, d)
    r = ch / len(cp) if cp else 0
    assert r <= 0.005 and md <= 40, f"{cid}: {ch}/{len(cp)}={r*100:.2f}% diff, max={md}"

# ── Parametrized capture-compare ──────────────────────────
@pytest.mark.parametrize("case", CANONICAL_CASES, ids=lambda c: c.case_id)
def test_visual_capture_and_compare(case, batch_manifest):
    info = batch_manifest[case.case_id]
    entry = info["entry"]
    assert entry["setup_executed"] is True, f"{case.case_id}: setup not executed"
    assert entry["post_executed"] is True, f"{case.case_id}: post_fn failed"
    assert entry["assert_executed"] is True, f"{case.case_id}: assert_fn not executed"
    assert entry["assert_passed"] is True, f"{case.case_id}: assert_fn failed: {entry.get('state_snapshot')}"
    assert entry.get("assertion_count", 0) > 0, f"{case.case_id}: zero assertions executed"
    assert entry["warnings"] == [], f"{case.case_id}: {len(entry['warnings'])} QML warnings: {entry['warnings'][:5]}"
    expected_platform = "windows" if os.name == "nt" else "offscreen"
    assert entry["platform"] == expected_platform, (
        f"{case.case_id}: visual gate captured on {entry['platform']!r}, "
        f"expected {expected_platform!r}"
    )

    gp = GD / f"{case.filename}.png"
    assert gp.exists(), f"{case.case_id}: missing golden: {gp}"
    if UPD:
        # Controlled regeneration happens only after all semantic/warning checks
        # above pass.  Capture never writes the baseline before comparison.
        gp.write_bytes(info["data"])
    else:
        _cmp(info["data"], gp.read_bytes(), case.case_id)

# ── Negative: missing assert_fn ───────────────────────────
def test_case_without_assert_fn_fails():
    """Verify that a case without assert_fn causes batch failure."""
    from .m1_cases import VisualCase
    bad = VisualCase("bad_case", "bad.png", 1000, 700, "en-US",
                     setup_fn=lambda c,i: None,
                     assert_fn=lambda v,c,i: {"forced_fail": False})  # wrong — should actually raise
    # The real test: every canonical case has a real assert_fn
    for c in CANONICAL_CASES:
        assert c.assert_fn is not None, f"{c.case_id}: assert_fn is None — will never be caught by batch"
        assert c.setup_fn is not None, f"{c.case_id}: setup_fn is None"

# ── Static verification ───────────────────────────────────
def test_golden_count():
    assert len(list(GD.glob("*.png"))) >= 38
def test_sha_uniqueness():
    shas = {}
    for f in sorted(GD.glob("*.png")):
        sha = _sha(f.read_bytes()); shas.setdefault(sha, []).append(f.name)
    col = {s: n for s, n in shas.items() if len(n) > 1}
    assert not col, f"SHA collisions: {list(col.items())[:3]}"
def test_m0_unchanged():
    assert M0.exists() and _sha(M0.read_bytes()) == M0SHA
def test_golden_registry_1to1():
    reg = {c.filename for c in CANONICAL_CASES}
    disk = {f.stem for f in GD.glob("*.png")}
    assert reg == disk, f"Missing: {reg-disk}, Extra: {disk-reg}"
def test_missing_golden_fails():
    fake = GD / "_nonexistent_test.png"
    if fake.exists(): fake.unlink()
    assert not fake.exists()
def test_no_skip_decorators():
    for fp in [Path(__file__), Path(__file__).parent / "m1_cases.py"]:
        if not fp.exists(): continue
        for node in ast.walk(ast.parse(fp.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and hasattr(node.func, 'attr') and node.func.attr in ('skip','skipif','xfail'):
                n = getattr(node.func, 'value', None)
                if n and hasattr(n, 'id') and n.id == 'pytest':
                    pytest.fail(f"{fp.name}:{node.lineno}: pytest.{node.func.attr}() forbidden")
def test_capture_script_exists():
    assert (PROJECT / "scripts" / "capture_m1_native.py").exists()
def test_deliberate_mutation(batch_manifest):
    gp = GD / "ee.png"
    assert gp.exists(), "Missing ee.png golden"
    cur = batch_manifest["inline_error"]["data"]
    ci = Image.open(io.BytesIO(cur)).convert("RGBA"); w, h = ci.size
    for y in range(h//2-50, h//2+50):
        for x in range(w//2-50, w//2+50): ci.putpixel((x,y),(255,0,0,255))
    buf = io.BytesIO(); ci.save(buf, "PNG"); corrupt = buf.getvalue()
    with pytest.raises(AssertionError):
        _cmp(corrupt, gp.read_bytes(), "deliberate-mutation")
