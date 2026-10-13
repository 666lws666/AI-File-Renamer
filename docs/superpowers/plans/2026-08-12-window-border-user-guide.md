# Window Border and Offline User Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a clearly visible 1px border to the normal frameless Windows window and ship an accurate, fully offline Chinese HTML user manual with the Windows RC.

**Architecture:** The window border is one non-interactive overlay at the QML Shell boundary, driven by the real top-level window visibility. The manual is one authoritative static HTML document plus local screenshot assets, validated by a Python content contract and packaged as PyInstaller data beside `Xuxia.exe`.

**Tech Stack:** PySide6/QML, Python 3.14, pytest, HTML5/CSS, Pillow for privacy-safe screenshot inspection, PyInstaller onedir.

## Global Constraints

- Normal windows show an inset 1px `#94A3B8` outline; maximized and full-screen windows hide it.
- The outline must not change content geometry or consume mouse input.
- The manual is Simplified Chinese, fully offline, and aimed at non-technical Windows users.
- The manual must not require Python/Git, show API prices, require simultaneous providers, or claim multimodal support is unimplemented.
- Screenshots use only the current Xuxia production entry with synthetic data and no real keys/private paths.
- Do not update committed Golden images.
- Do not call real APIs or the real Credential Manager.
- Do not push.

---

### Task 1: QML Window Border

**Files:**
- Modify: `src/ui_qml/DesignTokens.qml`
- Modify: `src/ui_qml/Shell.qml`
- Modify: `tests/qml/test_shell.py`

**Interfaces:**
- Consumes: `shell.Window.window.visibility` from the real `ApplicationWindow`.
- Produces: QML object `windowBoundary`, properties `border.width == 1`, `border.color == #94A3B8`, and `visible == false` for `Window.Maximized`/`Window.FullScreen`.

- [ ] **Step 1: Write failing QML contract tests**

Add tests that load `main.qml`, find `windowBoundary`, assert width/color, assert `enabled == false`, set the root visibility to windowed/maximized/full-screen states, process events, and assert border visibility. Extend `test_design_tokens` to assert `windowBorderWidth == 1` and `windowBorderColor == QColor("#94A3B8")`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\qml\test_shell.py -q
```

Expected: new tests fail because tokens and `windowBoundary` do not exist.

- [ ] **Step 3: Implement the minimal overlay**

Add the two tokens and one final `Rectangle` child in `Shell.qml`:

```qml
Rectangle {
    id: windowBoundary
    objectName: "windowBoundary"
    anchors.fill: parent
    color: "transparent"
    border.width: DesignTokens.windowBorderWidth
    border.color: DesignTokens.windowBorderColor
    enabled: false
    visible: shell.Window.window
             && shell.Window.window.visibility !== Window.Maximized
             && shell.Window.window.visibility !== Window.FullScreen
    z: 1000
}
```

- [ ] **Step 4: Verify GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\qml\test_shell.py tests\qml\test_navigation.py -q
```

Expected: all pass, zero captured QML warnings.

- [ ] **Step 5: Commit**

```powershell
git add src/ui_qml/DesignTokens.qml src/ui_qml/Shell.qml tests/qml/test_shell.py
git commit -m "fix: clarify frameless window boundary"
```

---

### Task 2: Offline Manual Content Contract

**Files:**
- Create: `tests/docs/test_user_guide.py`
- Replace: `USER_GUIDE.html` with `序匣用户手册.html`
- Create: `user-guide-assets/guide.css`

**Interfaces:**
- Consumes: current product behavior documented by `docs/PRODUCT_SPEC.md` and `docs/XUXIA_DETAILED_DESIGN.md`.
- Produces: one UTF-8 HTML file with stable chapter IDs and only relative local resources.

- [ ] **Step 1: Write failing HTML structure/content tests**

The test must parse the HTML with `html.parser.HTMLParser` and assert:

```python
REQUIRED_IDS = {
    "overview", "before-start", "provider", "navigation", "quickstart",
    "batch", "states", "watch", "templates", "multimodal", "limits",
    "privacy", "undo", "troubleshooting", "formats", "faq", "version",
}
FORBIDDEN = {
    "git clone", "python -m venv", "多模态分析尚未实现", "开发状态说明",
    "批次费用", "费用预估", "必须同时配置", "0.001 元",
}
```

Also assert: no `http://`, `https://`, protocol-relative URLs, CDN, remote fonts, inline secrets, `D:\\`, `C:\\Users\\`, placeholder/TODO text; every `href="#..."` resolves; every image/style path exists and stays inside the repo.

- [ ] **Step 2: Verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\docs\test_user_guide.py -q
```

Expected: fail because the new authoritative file/assets do not exist.

- [ ] **Step 3: Implement the complete manual and stylesheet**

Create semantic HTML with a skip link, sticky TOC, responsive tables, print button (`window.print()` only), privacy/error/tip callouts, and all 17 chapters from the approved spec. Replace developer setup with user-facing `Xuxia.exe` launch instructions. Describe one active configurable Provider and capability labels. State exact upload semantics: extracted text, resized images/scanned pages, and locally extracted video keyframes—never a whole video.

- [ ] **Step 4: Verify content contract**

Run the docs test. Expected: all pass with no network dependency or broken anchors.

- [ ] **Step 5: Commit**

```powershell
git add USER_GUIDE.html 序匣用户手册.html user-guide-assets/guide.css tests/docs/test_user_guide.py
git commit -m "docs: replace legacy guide with offline user manual"
```

The deletion of `USER_GUIDE.html` is staged by the same command; no compatibility copy remains.

---

### Task 3: Production Screenshot Assets

**Files:**
- Create: `scripts/capture_user_guide_native.py`
- Create: `user-guide-assets/01-navigation.png`
- Create: `user-guide-assets/02-provider-settings.png`
- Create: `user-guide-assets/03-batch-empty.png`
- Create: `user-guide-assets/04-batch-review.png`
- Create: `user-guide-assets/05-inline-edit.png`
- Create: `user-guide-assets/06-watch-create.png`
- Create: `user-guide-assets/07-watch-results.png`
- Create: `user-guide-assets/08-templates.png`
- Create: `user-guide-assets/09-vocabulary.png`
- Create: `user-guide-assets/10-system-status.png`
- Modify: `序匣用户手册.html`
- Modify: `tests/docs/test_user_guide.py`

**Interfaces:**
- Consumes: `build_qml_runtime` with isolated config, fake credentials, fake Provider connection service, and synthetic task/watch/template data.
- Produces: ten native Windows PNGs and `user-guide-assets/manifest.json` containing dimensions, SHA-256, case ID, QML warning count, and privacy scan result.

- [ ] **Step 1: Add failing asset-manifest tests**

Assert ten unique expected case IDs, PNG existence, dimensions at least 900×640, unique SHA for semantically distinct states, warning count zero, and no known secret/path sentinel in manifest. Verify HTML references each image and provides non-empty Chinese `alt` text.

- [ ] **Step 2: Verify RED**

Run docs tests; expected missing assets/manifest failures.

- [ ] **Step 3: Build the capture script**

Use `QApplication` with native Windows QPA (not offscreen), create a fresh runtime per case, inject only fake local dependencies before QML creation, explicitly set route/state, assert target object state, call `grabWindow`, and write PNG/manifest. Fail nonzero on warnings, duplicate semantic hashes, missing CJK glyph coverage, or privacy sentinel.

- [ ] **Step 4: Capture and visually inspect**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\capture_user_guide_native.py --output user-guide-assets
```

Expected: ten PNGs, warnings 0. Inspect every image for readable Chinese, true state, no clipping, no real keys/paths, and visible normal-window outline.

- [ ] **Step 5: Link screenshots and verify**

Embed figures with captions in the relevant chapters. Run docs tests and open the HTML locally in Edge/Chrome offline at desktop and narrow widths.

- [ ] **Step 6: Commit**

```powershell
git add scripts/capture_user_guide_native.py user-guide-assets 序匣用户手册.html tests/docs/test_user_guide.py
git commit -m "docs: add native user guide evidence"
```

---

### Task 4: Packaging the Manual

**Files:**
- Modify: `packaging/xuxia.spec`
- Modify: `tests/packaging/test_packaged_app.py`

**Interfaces:**
- Consumes: `序匣用户手册.html`, `user-guide-assets/`.
- Produces: `dist/Xuxia/序匣用户手册.html` and `dist/Xuxia/user-guide-assets/*` beside the executable.

- [ ] **Step 1: Write failing packaging tests**

Assert the spec lists the manual and asset tree; after build, assert the packaged HTML and every manifest asset exist, contain no external URLs or developer paths, and their SHA values match source assets.

- [ ] **Step 2: Verify RED**

Run the static packaging subset; expected failure because `xuxia.spec` omits the manual.

- [ ] **Step 3: Add PyInstaller datas**

Append the single HTML file with destination `.` and every asset file with destination `user-guide-assets`, preserving relative paths.

- [ ] **Step 4: Run static packaging tests**

Expected: source/spec checks pass. Artifact checks remain fail-closed until Task 6 rebuilds.

- [ ] **Step 5: Commit**

```powershell
git add packaging/xuxia.spec tests/packaging/test_packaged_app.py
git commit -m "build: package offline user manual"
```

---

### Task 5: Window and Manual Visual Gate

**Files:**
- Create: `tests/screenshots/qa-current/window-guide/`
- Create: `tests/screenshots/qa-current/window-guide/WINDOW_GUIDE_VISUAL_REVIEW.md`

**Interfaces:**
- Consumes: production QML entry and packaged/static manual.
- Produces: ignored QA evidence only; no Golden changes.

- [ ] **Step 1: Capture the native window states**

Capture normal 1000×700 and 900×640 on a white desktop background, maximized, and restored. Verify four continuous `#94A3B8` edges in normal states, none maximized, and correct reappearance after restore.

- [ ] **Step 2: Real interaction checks**

Use real mouse clicks for title drag, minimize, maximize/restore, close guard, and all five navigation entries. Record warning count zero and no input interception by the overlay.

- [ ] **Step 3: Manual browser review**

Open locally with network disabled. Check all navigation anchors, images, horizontal table scrolling, 100%/125% zoom, narrow window, and print preview. Record pass/fail and screenshot paths in the ignored review report.

- [ ] **Step 4: Confirm no Golden change**

Run `git status --short tests/screenshots/golden`; expected empty.

---

### Task 6: Full Regression and Windows RC Rebuild

**Files:**
- Generated ignored artifacts: `build/`, `dist/Xuxia/`

**Interfaces:**
- Consumes: all committed implementation tasks.
- Produces: tested local Windows RC with manual beside the EXE.

- [ ] **Step 1: Run complete source gates**

```powershell
.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/screenshots -q
$env:UPDATE_GOLDENS=''; .\.venv\Scripts\python.exe -m pytest tests\screenshots -q
.\.venv\Scripts\python.exe acceptance_test.py
git diff --check
```

Expected: all new and legacy tests pass; 186/186 acceptance; only existing platform skips.

- [ ] **Step 2: Build current HEAD**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -PythonPath D:\文件AI-AGENT\.venv\Scripts\python.exe
```

- [ ] **Step 3: Run packaging and EXE smoke**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\packaging -q
```

Run `Xuxia.exe --smoke-test` with an isolated temp data directory and report. Require exit 0, QML warnings 0, ephemeral credential backend, and media dependency checks OK.

- [ ] **Step 4: Verify packaged manual**

Open `dist/Xuxia/序匣用户手册.html` offline; ensure all images load and printing works. Calculate EXE SHA-256, bytes, file count, and distribution total bytes.

- [ ] **Step 5: Final repository audit**

Confirm tracked worktree clean, no Golden diffs, no real secrets/private paths, no push, and show final HEAD plus RC absolute path.

