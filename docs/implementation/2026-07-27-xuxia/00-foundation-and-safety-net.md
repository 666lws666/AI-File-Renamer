# M0: Foundation & Safety Net Implementation Plan

> 本计划供 Claude Code 在 Product Owner 明确批准后逐任务执行。当前编写计划不构成实施授权。

**Goal:** 建立新 UI 开发所需的基础架构、安全网、测试基础设施和截图自动化，不修改任何现有功能行为。

**Architecture:** 在现有仓库中新增 `src/ui_qml/`、`src/controllers/`、`tests/unit/`、`tests/qml/`、`tests/screenshots/` 目录。旧代码和测试完全保留。QML 通过独立启动入口加载。

**Tech Stack:** PySide6 QML/Qt Quick, pytest, pytest-qt (可选), Python 3.11+

**Authority:** XUXIA_DETAILED_DESIGN §4 Architecture, §6 Visual System, §21 i18n, §26 Security Invariants, §27 DoD, §29 Test Strategy.

**Prerequisites:** 本阶段无前置依赖（M0 是起点）。

**Global Constraints:** 安全不变量全覆盖；i18n 从第一天建立；不切换正式入口；旧 UI 保持可用。

---

## Task 1: Repository Audit & Module Boundary Map

**Purpose:** 建立新旧代码边界，确认复用/适配/隔离/淘汰清单。

**Files:**
- Create: `docs/implementation/reports/M0_BASELINE_AUDIT.md`（审计产物，未来执行 M0 时创建，代表复用/适配/隔离/淘汰四类结论）
- Read: `src/` 全部 `.py` 文件，`tests/` 全部，`acceptance_test.py`，`requirements.txt`
- Record: 审计结果写入 `docs/implementation/reports/M0_BASELINE_AUDIT.md`

**Interfaces:**
- Produces: 模块审计报告（复用/适配/隔离/淘汰清单 + 行号证据）

**Steps:**
- [ ] 只读遍历 `src/` 下每个模块，记录类名、公开方法、依赖关系
- [ ] 识别与 Phase 1A 安全凭据代码（`credential_manager.py`）的集成点
- [ ] 识别 `config.py` 的 schema 和序列化路径
- [ ] 识别旧 UI (`src/ui/`) 与核心逻辑的耦合点
- [ ] 生成 `docs/implementation/reports/M0_BASELINE_AUDIT.md`，记录复用、适配、隔离、淘汰四类结论（该文件在未来执行 M0 时创建，本轮不创建）
- [ ] 验证 214 个现有测试仍通过

**Verification:** `pytest tests/ && python acceptance_test.py` — legacy baseline 214 + new tests all pass.

**Failure/Stop:** 任何现有测试失败 → 停止，不修改代码。

**Rollback:** 审计为只读操作，无需回滚。

**Commit:** `docs: add module audit for M0 foundation`

---

## Task 2: Security Regression Test Suite

**Purpose:** 将 Phase 1A 安全不变量固化为可自动运行的回归测试套件。

**Files:**
- Create: `tests/unit/security/test_security_invariants.py`
- Read: `tests/test_config_no_key.py`, `tests/test_credential_migration.py`, `tests/test_log_no_leak.py`, `tests/test_settings_dialog_fail_closed.py`

**Interfaces:**
- Consumes: `src.config.save_config`, `src.config.load_config`, `src.utils.credential_manager`
- Produces: `SecurityRegressionSuite` (pytest class)

**Steps:**
- [ ] 编写 `test_api_key_never_in_json()` — 保存后检查 JSON 不含 `api_key`
- [ ] 编写 `test_api_key_never_in_logs()` — AST 扫描 logger 调用
- [ ] 编写 `test_save_fail_closed()` — keyring 失败时 save_config 抛异常且 JSON 未写入
- [ ] 编写 `test_clear_key_deletes_credential()` — 清空 Key 后凭据管理器无残留
- [ ] 运行: `pytest tests/unit/security/test_security_invariants.py -v`
- [ ] 预期: 全部通过（当前代码已满足）

**Verification:** `pytest tests/unit/security/test_security_invariants.py -v` — all pass.

**Failure/Stop:** 任何测试失败 → 停止，Phase 1A 基线可能已退化。

**Commit:** `test: add security invariant regression suite`

---

## Task 3: i18n Framework & zh-CN / en-US Baseline

**Purpose:** 从第一天建立国际化框架，所有新 UI 文案进入翻译资源。只创建有完整翻译内容的 locale 文件；planned locale 通过元数据记录，不创建空资源文件。

**Files:**
- Create: `src/utils/i18n/__init__.py`
- Create: `src/utils/i18n/service.py`
- Create: `src/utils/i18n/locale_metadata.py`
- Create: `src/utils/i18n/locales/zh_CN.json`（含完整翻译内容）
- Create: `src/utils/i18n/locales/en_US.json`（含完整翻译内容，兼作 fallback）
- Test: `tests/unit/i18n/test_service.py`
- Test: `tests/unit/i18n/test_fallback.py`
- Test: `tests/unit/i18n/test_locale_metadata.py`

**Interfaces:**
- Consumes: (none — new module)
- Produces: `I18n.tr(key, locale, **kwargs) → str`; `I18n.available_locales → list`
- Produces: `LocaleMetadata` — 记录 supported/planned locale 状态
- Events: `locale_changed(locale: str)` signal

**Steps:**
- [ ] 编写 `test_zh_cn_resource_loadable()` — zh_CN.json 可加载，返回非空字符串
- [ ] 编写 `test_en_us_resource_loadable()` — en_US.json 可加载，作为 fallback
- [ ] 编写 `test_missing_key_falls_back_to_en()` — 缺失 key 回退 en-US
- [ ] 编写 `test_planned_locale_without_resource_falls_back_to_en()` — planned locale 没有资源文件时回退 en-US
- [ ] 编写 `test_placeholder_substitution()` — `{name}` 等插值参数正确替换（运行时语法，非内容占位）
- [ ] 编写 `test_pseudo_locale_text_expansion()` — 伪本地化验证布局扩展
- [ ] 编写 `test_locale_metadata_six_targets()` — zh-CN=supported, en-US=supported+fallback, ja-JP=planned, ko-KR=planned, vi-VN=planned, th-TH=planned
- [ ] 编写 `test_no_empty_locale_files_for_planned()` — planned locale 目录下不存在空 JSON 文件
- [ ] 实现 `I18n` service、`LocaleMetadata`、`zh_CN.json`、`en_US.json`
- [ ] 运行: `pytest tests/unit/i18n/ -v`

**Verification:** `pytest tests/unit/i18n/ -v` — all pass. zh_CN/en_US 加载成功，fallback 链正确，planned locale 无空文件。

**Commit:** `feat: add i18n framework with zh-CN and en-US baseline`

---

## Task 4: QML Bootstrap & Headless Test Harness

**Purpose:** 验证 PySide6 QML 可在当前环境加载、渲染，并建立无头测试能力。

**Files:**
- Create: `src/ui_qml/main.qml` (最小窗口)
- Create: `tests/qml/test_qml_bootstrap.py`
- Modify: `requirements.txt` (如需要 pytest-qt)

**Interfaces:**
- Produces: `QQuickView` 最小窗口 (400×300)，显示 "Xuxia M0 OK"

**Steps:**
- [ ] 编写 `test_qml_engine_imports()` — 验证 QtQuick 等模块可导入
- [ ] 编写 `test_main_qml_loads()` — 加载 main.qml 无 QML 解析错误
- [ ] 编写 `test_window_renders_minimal()` — 创建 QQuickView 并验证尺寸
- [ ] 创建最小 `main.qml`：白色背景，居中文字 "序匣 M0 OK"
- [ ] 运行: `pytest tests/qml/test_qml_bootstrap.py -v`
- [ ] 预期: 全部通过

**Verification:** `pytest tests/qml/test_qml_bootstrap.py -v` — all pass.

**Failure/Stop:** QML 模块导入失败 → 检查 PySide6 安装（可能需要 `pip install PySide6` 完整版）。

**Commit:** `feat: add QML bootstrap and headless test harness`

---

## Task 5: Screenshot Automation Infrastructure

**Purpose:** 建立确定性 fixture 驱动截图采集和 golden 对比基础设施。

**Files:**
- Create: `tests/screenshots/conftest.py`
- Create: `tests/screenshots/test_screenshot_infra.py`
- Create: `tests/screenshots/golden/` 目录

**Interfaces:**
- Consumes: `QQuickView.grabWindow()` → `QImage`
- Produces: `capture(page, state, locale, size)` → PNG 路径

**Steps:**
- [ ] 编写 `test_screenshot_capture_m0_bootstrap()` — 截取 M0 最小窗口
- [ ] 保存为 `tests/screenshots/golden/m0/bootstrap/zh_CN/400x300.png`
- [ ] 编写 `test_golden_comparison_passes()` — 同窗口二次截图与 golden 对比
- [ ] 编写 `test_golden_comparison_detects_change()` — 修改后截图检测到差异
- [ ] 运行: `pytest tests/screenshots/test_screenshot_infra.py -v`
- [ ] 预期: 3 passed

**Verification:** golden 对比机制正常工作。命名规则: `{milestone}/{page}/{state}/{locale}/{size}.png`。

**Commit:** `feat: add screenshot automation and golden comparison`

---

## Task 6: Config Schema Versioning & Migration Test

**Purpose:** 为 `settings.json` 添加 schema 版本号，防止未来升级时静默不兼容。

**Files:**
- Create: `tests/unit/test_config_schema.py`
- Modify: `src/config.py` — 添加 `SCHEMA_VERSION = 1` 和版本检查

**Interfaces:**
- Consumes: 现有 `src/config.save_config`, `src/config.load_config`
- Produces: `config["schema_version"]` → int

**Steps:**
- [ ] 编写 `test_new_config_has_schema_version()` — 新建配置含 `schema_version: 1`
- [ ] 编写 `test_old_config_without_version_loads_and_migrates()` — 无版本旧配置加载后自动写入版本
- [ ] 编写 `test_future_version_rejected()` — 版本高于当前抛出明确错误
- [ ] 实现: `save_config` 写入 `schema_version`; `load_config` 容错处理无版本旧配置
- [ ] 验证所有现有测试仍通过
- [ ] 运行: `pytest tests/unit/test_config_schema.py -v && pytest tests/`

**Verification:** schema 版本正确写入，旧配置向后兼容，高版本安全拒绝。

**Commit:** `feat: add config schema versioning with migration`

---

## M0 Gate Report Checklist

- [ ] 模块审计报告完成，复用/适配/隔离/淘汰清单明确
- [ ] 安全回归测试套件 4 tests passed
- [ ] i18n 框架可用，zh_CN + en_US 加载
- [ ] QML 最小窗口渲染成功
- [ ] 截图基础设施 golden 对比正常
- [ ] Config schema 版本化
- [ ] 遗留基线: pytest 28 + acceptance 186 = 214 passed
- [ ] M0 本阶段全部新增测试通过（安全不变量、i18n、config schema、QML bootstrap、screenshot infra）
- [ ] 当前完整测试集全部通过
- [ ] 无正式入口切换
- [ ] 无现有功能退化

**自动化测试命令:**
```bash
pytest tests/unit/security/ tests/unit/i18n/ tests/unit/test_config_schema.py tests/qml/test_qml_bootstrap.py tests/screenshots/test_screenshot_infra.py -v
pytest tests/
python acceptance_test.py
```

**Product Owner 批准栏:**
- [ ] M0 审查通过
- [ ] 批准进入 M1

> **未批准不得进入 M1。**
