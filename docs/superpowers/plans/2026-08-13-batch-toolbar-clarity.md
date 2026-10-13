# Batch Toolbar Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Batch 顶部工具栏改成无需悬停即可理解的完整中文操作区，并确保模板/状态下拉框只在点击时展开，1000×700 与 900×640 均保持单行可用。

**Architecture:** 保持现有 `BatchToolbar.qml → BatchWorkspaceController` 业务接口不变，只调整显示名称、可见文字、Tooltip 策略和响应式几何。默认模板的持久化名称继续保持兼容，由 `TemplatePageController` 在显示行中识别内置默认模板并按 locale 返回本地化名称；用户自建名称原样显示。

**Tech Stack:** Python 3.14、PySide6、Qt Quick/QML、Qt Test、pytest、JSON i18n、Windows 原生 GUI 验收。

## Global Constraints

- 中文界面使用完整、直接的中文动作名称。
- 带文字标签的按钮不得显示 Tooltip。
- ComboBox 只允许点击展开；悬停不得展开或出现重复选项。
- 1000×700 使用完整文字；900×640 优先压缩搜索框，再把右侧批量操作切为纯图标。
- “添加文件”“添加文件夹”“目标目录”在所有支持宽度下不得缩写。
- 不修改 Batch 状态机、导入、分析、Apply/Undo、Watch 或模板公式。
- 截图仅写入 `tests/screenshots/qa-current/batch-toolbar/`；不得更新正式 Golden。
- 根目录 `序匣.lnk` 属于本机便利文件，不纳入 Git。

---

### Task 1: 本地化内置默认模板显示名

**Files:**
- Modify: `src/controllers/template_page_controller.py:59-168`
- Modify: `src/controllers/mock_batch_controller.py:80-86`
- Modify: `src/utils/i18n/locales/zh_CN.json:29-65`
- Modify: `src/utils/i18n/locales/en_US.json:29-65`
- Test: `tests/unit/test_template_page_controller.py`
- Test: `tests/qml/test_batch_runtime_wiring.py`

**Interfaces:**
- Consumes: `TemplatePageController.setLocale(locale: str)`, `TemplatePageController.templates`, `BatchWorkspaceController.configure_templates(options, selected_id)`。
- Produces: `TemplatePageController.templates[*]["name"]` 的 locale-aware 显示值；内置默认模板仍保留原 `id`、`pattern` 和持久化 `name`。

- [ ] **Step 1: 写默认模板本地化失败测试**

在 `tests/unit/test_template_page_controller.py` 增加：

```python
def test_builtin_default_template_name_follows_locale_without_mutating_store(tmp_path):
    controller = _controller(tmp_path)
    stored = controller.get_template_for_analysis()
    assert stored.name == "General Naming (Default)"

    controller.setLocale("zh-CN")
    assert controller.templates[0]["name"] == "通用命名（默认）"
    assert controller.get_template_for_analysis().name == "General Naming (Default)"

    controller.setLocale("en-US")
    assert controller.templates[0]["name"] == "General Naming (Default)"
```

另加用户模板保护测试：创建名为 `General Naming (Default) copy` 的模板后，切换 locale 时其名称保持不变。

- [ ] **Step 2: 运行测试确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\unit\test_template_page_controller.py -q -k "builtin_default_template_name or user_template_name"`

Expected: FAIL，中文 locale 仍返回英文默认名称。

- [ ] **Step 3: 实现显示层本地化**

在 `TemplatePageController` 增加稳定常量与显示函数：

```python
BUILTIN_DEFAULT_NAME = "General Naming (Default)"
BUILTIN_DEFAULT_PATTERN = "{dcDate}_{dcTitle}"

def _display_template_name(self, template: Template) -> str:
    is_builtin_default = (
        template.name == BUILTIN_DEFAULT_NAME
        and template.pattern == BUILTIN_DEFAULT_PATTERN
        and template.version == 1
    )
    if not is_builtin_default:
        return template.name
    return "通用命名（默认）" if self._locale == "zh" else BUILTIN_DEFAULT_NAME
```

把 `_template_row` 从静态方法改为实例方法，仅让 `"name"` 调用 `_display_template_name(template)`；不要修改 store 中的模板对象。`MockBatchController` 的默认显示名改为“通用命名（默认）”，用于中文默认截图/测试；英文测试通过显式 fixture 设置英文显示。

- [ ] **Step 4: 补齐 i18n key 并验证 GREEN**

新增：

```json
"batch.template.generalDefault": "通用命名（默认）"
```

英文对应 `General Naming (Default)`。实现中优先通过既有 locale 状态返回上述确定文案，不把用户模板送入翻译器。

Run: `.\.venv\Scripts\python.exe -m pytest tests\unit\test_template_page_controller.py tests\qml\test_batch_runtime_wiring.py -q`

Expected: 全部 PASS，QML warnings 为 0。

- [ ] **Step 5: 提交**

```powershell
git add src/controllers/template_page_controller.py src/controllers/mock_batch_controller.py src/utils/i18n/locales/zh_CN.json src/utils/i18n/locales/en_US.json tests/unit/test_template_page_controller.py tests/qml/test_batch_runtime_wiring.py
git commit -m "fix: localize built-in naming template"
```

---

### Task 2: 完整中文文字与文字按钮 Tooltip 清理

**Files:**
- Modify: `src/ui_qml/BatchToolbar.qml`
- Modify: `src/utils/i18n/locales/zh_CN.json`
- Modify: `src/utils/i18n/locales/en_US.json`
- Test: `tests/qml/test_batch_runtime_wiring.py`
- Test: `tests/qml/test_locale_completeness.py`

**Interfaces:**
- Consumes: 现有信号 `addFilesRequested()`、`addFolderRequested()`、`targetDirectoryRequested()` 及 controller slots。
- Produces: 完整文字按钮和 `batchToolbarCompactActions: bool` 可观察属性；业务信号签名不变。

- [ ] **Step 1: 写文案和 Tooltip 契约失败测试**

在 `tests/qml/test_batch_runtime_wiring.py` 创建中文 1000×700 handle，断言：

```python
expected = {
    "batchAddFilesButton": "添加文件",
    "batchAddFolderButton": "添加文件夹",
    "batchTargetDirectoryButton": "目标目录",
    "batchStatusFilter": "全部状态",
    "batchApplySelectedButton": "应用所选",
    "batchStopButton": "停止任务",
    "batchClearButton": "清空工作区",
}
for object_name, text in expected.items():
    item = handle.root.findChild(QQuickItem, object_name)
    assert item.property("text") == text or item.property("currentText") == text
```

再读取 `BatchToolbar.qml` 源码，逐个确认上述六个文字按钮区块不含 `ToolTip.visible: hovered`。这是一条源码契约，用来防止未来给文字按钮重新加重复解释；ComboBox 的动态行为由 Task 3 覆盖。

- [ ] **Step 2: 运行测试确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\qml\test_batch_runtime_wiring.py -q -k "complete_chinese or text_buttons_have_no_tooltips"`

Expected: FAIL，当前仍显示缩写且 QML 含文字按钮 Tooltip。

- [ ] **Step 3: 调整 i18n 文案**

中文：

```json
"batch.toolbar.addFilesCompact": "添加文件",
"batch.toolbar.addFolderCompact": "添加文件夹",
"batch.toolbar.targetDirCompact": "目标目录",
"batch.toolbar.targetSetCompact": "已选目标目录",
"batch.toolbar.filterAll": "全部状态",
"batch.actions.applyAllCompact": "应用所选",
"batch.actions.stopCompact": "停止任务",
"batch.actions.clearWorkspaceCompact": "清空工作区"
```

英文对应：`Add Files`、`Add Folder`、`Target Folder`、`Target Selected`、`All Statuses`、`Apply Selected`、`Stop Tasks`、`Clear Workspace`。

- [ ] **Step 4: 删除文字按钮 Tooltip**

从添加文件、添加文件夹、目标目录、应用所选、停止任务、清空工作区按钮移除 `ToolTip.visible` 与 `ToolTip.text`。保留按钮本身的文字和现有 `onClicked`。

为所有操作按钮设置与文字一致的 `Accessible.name`；后续 900px 图标模式仍复用该可访问名称。

- [ ] **Step 5: 验证 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\qml\test_batch_runtime_wiring.py tests\qml\test_locale_completeness.py -q`

Expected: 全部 PASS，warnings=0。

- [ ] **Step 6: 提交**

```powershell
git add src/ui_qml/BatchToolbar.qml src/utils/i18n/locales/zh_CN.json src/utils/i18n/locales/en_US.json tests/qml/test_batch_runtime_wiring.py tests/qml/test_locale_completeness.py
git commit -m "fix: clarify batch toolbar actions"
```

---

### Task 3: 点击展开下拉框与 900px 响应式几何

**Files:**
- Modify: `src/ui_qml/BatchToolbar.qml`
- Reuse: `src/ui_qml/icons/` 内现有批量动作图标；若缺失则 Create 三个本地 SVG：`apply_selected.svg`、`stop_tasks.svg`、`clear_workspace.svg`
- Test: `tests/qml/test_batch_runtime_wiring.py`

**Interfaces:**
- Consumes: `ComboBox.popup.visible`、QML `hovered`、现有按钮 clicked signals。
- Produces: `BatchToolbar.compactActions`（当有效宽度不足时为 true）以及三个批量按钮的文字/图标响应式呈现。

- [ ] **Step 1: 写真实悬停/点击下拉测试**

扩充测试 helper，使用 `QTest.mouseMove` 将鼠标移到 `batchTemplateSelector` 和 `batchStatusFilter` 中心，等待 650ms 并处理事件，断言各自 `popup.visible is False`；随后 `QTest.mouseClick`，断言对应 popup 变为可见。每个 case 创建全新 handle，避免弹层状态串扰。

- [ ] **Step 2: 写 1000/900 几何与响应式失败测试**

在两种窗口尺寸检查：

```python
assert toolbar.property("height") == 44
assert add_files.property("text") == "添加文件"
assert add_folder.property("text") == "添加文件夹"
assert target.property("text") == "目标目录"
assert search.property("width") >= 72
```

对每个关键控件计算 scene rect，断言不重叠、左边不进入 48px nav rail、右边不超过窗口宽度。1000px 时 `compactActions == False` 且右侧三按钮显示完整文字；900px 时 `compactActions == True`，右侧三按钮显示图标、文字为空，但 `Accessible.name` 分别为“应用所选”“停止任务”“清空工作区”。

- [ ] **Step 3: 运行测试确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\qml\test_batch_runtime_wiring.py -q -k "combobox or supported_widths or responsive"`

Expected: 当前完整文案在 900px 溢出，且没有 `compactActions` 契约。

- [ ] **Step 4: 实现响应式布局**

在 `BatchToolbar.qml`：

```qml
property bool compactActions: width < 930
```

- 模板选择器宽 150px；中文名称使用 ElideRight，但完整名称可在展开列表中显示。
- 添加文件 76px、添加文件夹 88px、目标目录 76px，所有宽度固定且不缩写。
- 搜索框 `Layout.preferredWidth: compactActions ? 76 : 150`，`Layout.minimumWidth: 72`。
- 状态筛选 92px。
- 右侧批量按钮在 normal 模式显示完整文字和合适宽度；compact 模式宽 30px、文字为空、使用本地 SVG 图标、提供 `ToolTip.delay: 500` 与 `Accessible.name`。
- ComboBox 不添加任何 HoverHandler 打开逻辑；保持 Qt Controls 默认的点击展开。

如果 900px 实测仍不足，按顺序压缩模板到 138px、控件间距从 6px 到 4px；不得缩写三项导入/目标动作，也不得隐藏状态筛选。

- [ ] **Step 5: 验证 GREEN 与交互接线**

Run: `.\.venv\Scripts\python.exe -m pytest tests\qml\test_batch_runtime_wiring.py tests\qml\test_batch_empty.py tests\qml\test_batch_nonempty.py -q`

Expected: 全部 PASS，0 QML warning；真实点击仍调用原有导入/目标/筛选/批量动作。

- [ ] **Step 6: 提交**

```powershell
git add src/ui_qml/BatchToolbar.qml src/ui_qml/icons tests/qml/test_batch_runtime_wiring.py
git commit -m "fix: make batch toolbar responsive"
```

---

### Task 4: 完整自动化与原生 Windows 视觉交互 Gate

**Files:**
- Create: `tests/screenshots/qa-current/batch-toolbar/`（仅运行产物，不提交）
- Modify only if a deterministic defect is found: files owned by Tasks 1–3

**Interfaces:**
- Consumes: 正式 `src.main → src.main_qml` 入口和新建 RC。
- Produces: 本地 QA 截图、鼠标悬停/点击记录与最终通过/失败结论；不更新 Golden。

- [ ] **Step 1: 运行定向和完整自动化测试**

```powershell
Remove-Item Env:UPDATE_GOLDENS -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest tests\unit\test_template_page_controller.py tests\qml\test_batch_runtime_wiring.py tests\qml\test_batch_empty.py tests\qml\test_batch_nonempty.py tests\qml\test_locale_completeness.py -q
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe acceptance_test.py
git diff --check
```

Expected: 全部新增测试通过；完整 pytest 0 failed，仅保留既有平台 skip；acceptance 186/186；Golden 无改动。

- [ ] **Step 2: 原生 Windows 中文 1000×700 验收**

通过可复现 QA capture 脚本启动正式 QML runtime，窗口设为 1000×700。使用真实鼠标依次悬停模板、添加文件、添加文件夹、目标目录、状态筛选、应用所选、停止任务、清空工作区：

- 文字按钮 650ms 后仍无 Tooltip；
- 模板/状态 popup 仍关闭；
- 点击模板/状态后 popup 打开；
- 中文文字完整可读，无英文默认模板、重复第二行、tofu 或裁切。

保存到 `tests/screenshots/qa-current/batch-toolbar/zh-1000x700.png`。

- [ ] **Step 3: 原生 Windows 中文 900×640 验收**

窗口设为 900×640，确认三项导入/目标动作仍为完整中文；搜索和状态可见；右侧三项为图标且 Tooltip 延迟显示正确中文；各控件不重叠、不越界。保存 `zh-900x640.png`。

- [ ] **Step 4: 英文与语言切换验收**

切换到 en-US，确认英文文案完整、默认模板显示 `General Naming (Default)`；切回 zh-CN，模板即时显示“通用命名（默认）”。保存 `en-1000x700.png` 和 `zh-restored-1000x700.png`。

- [ ] **Step 5: 受控重建 RC 和 smoke**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -PythonPath .venv\Scripts\python.exe
.\.venv\Scripts\python.exe -m pytest tests\packaging\test_packaged_app.py -q
Get-FileHash -Algorithm SHA256 dist\Xuxia\Xuxia.exe
```

Expected: build exit 0；打包测试 0 failed；报告新 SHA-256。

- [ ] **Step 6: 最终提交**

先确认 `git status --short tests/screenshots/golden` 为空，且 `qa-current` 未被暂存。若 Tasks 1–3 已逐项提交且 Task 4 未修代码，则不创建空提交；否则只提交 Task 4 确定性修复。

最终报告必须列出：中文映射、Tooltip/ComboBox 行为、1000/900 原生结果、pytest/acceptance/packaging 原始摘要、RC 路径与 SHA、未更新 Golden、未 push。
