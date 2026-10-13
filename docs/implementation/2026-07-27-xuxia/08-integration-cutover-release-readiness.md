# M8: Integration, Cutover & Release Readiness Implementation Plan

> 本计划供 Claude Code 在 Product Owner 明确批准后逐任务执行。当前编写计划不构成实施授权。

**Goal:** 完成全管线集成、性能优化、旧 UI 入口切换、打包验证、§28 全矩阵截图和发布候选自审。

**Architecture:** 集成所有 M0–M7 交付物；`NewEntryPoint` 启动 QML Shell；旧 `src/app.py` 保留可用直至 Gate 批准切换。

**Tech Stack:** PySide6 QML, PyInstaller, pytest, screenshot automation

**Authority:** XUXIA_DETAILED_DESIGN §27 DoD, §28 Screenshot Matrix, §29 Test Strategy, §30 Gate.

**Prerequisites:** M0–M7 全部通过。

**Global Constraints:** 无硬编码绝对路径；无 API Key 泄漏；无 QTableView/QMenuBar 泄漏；legacy baseline 214 + new tests all pass。

---

## Task 1: Full Pipeline Integration Test

**Purpose:** Batch + Watch + Templates + Preferences + Status 全管线端到端测试。

**Files:**
- Create: `tests/integration/test_full_pipeline.py`

**Steps:**
- [ ] 编写端到端测试: 创建 Provider → 导入混合文件 → 选择模板 → 管线执行 → Apply → Undo → 验证
- [ ] 编写端到端测试: Watch (Review First) → 放入文件 → 审阅 → Approve
- [ ] 编写端到端测试: Watch (Auto Apply) → 放入文件 → 自动完成 → Undo
- [ ] 编写端到端测试: 修改设置 → 保存 → 重启 → 验证持久化
- [ ] 运行: `pytest tests/integration/test_full_pipeline.py -v`

**Commit:** `test: add full pipeline integration tests`

---

## Task 2: Process Restart Recovery

**Purpose:** 重启后工作区和 Watch 状态恢复。

**Files:**
- Test: `tests/integration/test_restart_recovery.py`

**Steps:**
- [ ] 编写测试: Batch 导入 5 个文件 → 关闭 → 重启 → 5 个文件仍在
- [ ] 编写测试: 2 个 Watch 配置 → 重启 → 自动恢复监控
- [ ] 编写测试: Undo 历史 → 重启 → 仍可撤销
- [ ] 实现恢复逻辑
- [ ] 运行: `pytest tests/integration/test_restart_recovery.py -v`

**Commit:** `feat: add process restart recovery`

---

## Task 3: Performance & Memory Test

**Purpose:** 性能基准测试。

**Files:**
- Create: `tests/integration/test_performance.py`

**Steps:**
- [ ] 编写 `test_scan_1000_files_under_5s()` — 1000 文件扫描 < 5s
- [ ] 编写 `test_batch_card_virtualization_1000_items()` — 1000 卡片不卡顿
- [ ] 编写 `test_memory_no_leak_100_batches()` — 100 批次无内存泄漏
- [ ] 运行: `pytest tests/integration/test_performance.py -v`

**Commit:** `test: add performance benchmarks`

---

## Task 4: Unicode & i18n Validation

**Purpose:** Unicode 文件名和国际化全路径验证。

**Files:**
- Test: `tests/integration/test_unicode_i18n.py`

**Steps:**
- [ ] 编写 `test_unicode_filenames()` — 中文/日文/韩文/泰文/越南文文件名
- [ ] 编写 `test_zh_cn_full_ui()` — zh-CN 全覆盖
- [ ] 编写 `test_en_us_full_ui()` — en-US 全覆盖
- [ ] 编写 `test_pseudo_locale_text_expansion()` — 伪本地化文本膨胀
- [ ] 运行: `pytest tests/integration/test_unicode_i18n.py -v`

**Commit:** `test: add Unicode and i18n validation`

---

## Task 5: §28 Screenshot Matrix

**Purpose:** 完成 §28 全部截图验收矩阵。

**Files:**
- Create: `tests/screenshots/test_full_matrix.py`

**Steps:**
- [ ] Shell: 默认 1000×700, 900×640, 导航选中态 (zh_CN + en_US)
- [ ] Batch: 空态, 混合队列, 8 种状态筛选, hover, 多选, 内联编辑, 部分成功, Undo, Clear Workspace
- [ ] Watch: 空态, 新建表单, Active/Paused/Error/预算暂停, Review First, Auto Apply, 结果窗口
- [ ] Templates: 列表, 新建, 编辑, 字段排序, 实时预览, 删除引用替换
- [ ] Vocabulary: 列表, 筛选, 候选审核, 恢复预设, 去重提示
- [ ] Preferences: 全部卡片 (zh_CN + en_US), Provider 列表, Qwen 推荐, 保存失败
- [ ] System Status: 四种状态, 文本可用视觉不可用
- [ ] Error: 卡片内错误, 批次错误, Toast, 阻断模态
- [ ] 运行: `pytest tests/screenshots/test_full_matrix.py -v`

**Commit:** `test: complete §28 screenshot acceptance matrix`

---

## Task 6: Windows Packaging & QML Candidate Entry

**Purpose:** 先创建并测试 QML candidate entry，再以它为入口打包。打包前不切换默认入口。

**Files:**
- Create: `src/main_qml.py` — QML candidate entry（创建 QApplication，初始化所有 Service/Controller，注册 QML context，加载正式 Shell，处理启动失败）
- Create: `packaging/xuxia.spec`
- Create: `scripts/build_windows.ps1`
- Create: `tests/packaging/test_packaged_app.py`
- Modify: `requirements.txt` 或相应打包依赖清单

**Steps:**
- [ ] 创建 `src/main_qml.py`：初始化所有 M0–M7 服务和 Controller，注册 QML context，加载正式 Shell
- [ ] 验证 candidate entry 可独立启动（不替换当前默认入口）
- [ ] 创建 `xuxia.spec`：含 PySide6 QML import、QML pages/components、5 正式 SVG 图标、zh_CN/en_US locale JSON、locale metadata、PyMuPDF、Pillow、视频关键帧依赖、OCR 依赖、keyring
- [ ] 创建 `build_windows.ps1` 一键构建
- [ ] 打包冒烟测试：干净临时目录启动、首次启动、重启、设置保存、QML 页面加载、图片预处理、扫描 PDF 页面渲染(PyMuPDF)、视频关键帧、凭据读取、诊断包
- [ ] 验证不含 API Key 或测试凭据、不含开发机绝对路径
- [ ] 验证程序目录与用户数据目录分离
- [ ] 验证打包产物版本信息和序匣品牌
- [ ] 运行: `pytest tests/packaging/test_packaged_app.py -v`

**Verification:** candidate entry 可独立启动；打包产物在干净环境运行正常。

**Failure/Stop:** 打包产物任一冒烟测试失败 → 停止，不进行入口切换。

**Commit:** `feat: add Windows packaging with QML candidate entry`

---

## Task 7: Official Entry Point Switch (Product Owner Gate)

**Purpose:** 在 Product Owner 单独批准后，把用户默认启动路径切换至已验证的 QML candidate entry。本 Task 不创建 `src/main_qml.py`（已在 Task 6 创建）。

**Files:**
- Modify: `src/main.py` — 默认入口切换为 QML Shell
- Modify: `run.bat`
- Modify: `AI-文件夹整理程序.bat`
- Modify: `AI-文件夹整理程序.vbs`
- Modify/Confirm: PyInstaller 正式 entry 指向 QML candidate
- Create: `legacy/run_legacy.bat` — 保留可运行旧 UI 回滚入口

**Steps:**
- [ ] 以 Product Owner 单独批准为前置条件（未经批准不得执行本 Task）
- [ ] 切换正式启动入口到 QML，修改全部已审计启动路径
- [ ] 保留 `legacy/run_legacy.bat` 作为可运行回滚入口
- [ ] 验证默认启动进入 QML
- [ ] 验证 legacy 回滚仍可启动
- [ ] 不删除 legacy 代码（除非另有单独批准）
- [ ] 回滚不使用 `git reset --hard`

**Verification:** 默认启动进入 QML Shell；legacy entry 仍可启动旧 UI。

**Failure/Stop:** 默认入口启动失败 → 立即回滚到旧入口，不继续。

**Commit:** `feat: switch official entry point to QML Shell (Product Owner gated)`

---

## Task 8: Release Candidate Self-Audit

**Purpose:** 发布候选完整自审，生成结构化审计报告。不包含创建 main_qml 或入口切换正文。

**Files:**
- Create: `docs/implementation/reports/M8_RELEASE_CANDIDATE_AUDIT.md`（未来执行 M8 时创建）

**Steps:**
- [ ] 逐项验证 XUXIA_DETAILED_DESIGN 30 章节全部覆盖
- [ ] §28 全截图矩阵 golden 对比全部通过
- [ ] legacy baseline 214 passed
- [ ] 全部新增测试通过（M0–M8）
- [ ] 当前完整测试集通过
- [ ] QML 测试全部通过
- [ ] 五 Provider 合约测试全部通过
- [ ] 文件操作和 Undo 测试全部通过
- [ ] 故障注入测试全部通过
- [ ] 隐私和脱敏测试全部通过
- [ ] i18n zh_CN/en_US 全覆盖
- [ ] 性能和内存基准达标
- [ ] 打包产物冒烟测试通过
- [ ] 默认入口进入 QML
- [ ] legacy rollback 可启动
- [ ] 记录已知偏差清单
- [ ] 更新风险登记表
- [ ] 标注发布阻断项
- [ ] 生成 `M8_RELEASE_CANDIDATE_AUDIT.md`
- [ ] Product Owner 最终批准

**Verification:** 自审报告完整；所有 Gate 项通过。

**Failure/Stop:** 任一 Gate 项未通过 → 记录为阻断项，不声称发布就绪。

**Commit:** `docs: add M8 release candidate self-audit`

## M8 Gate Report Checklist

- [ ] 全管线集成测试通过 (Batch + Watch + Templates + Preferences + Status)
- [ ] 重启恢复: 工作区 + Watch + Undo
- [ ] 性能: 1000 文件 < 5s, 虚拟化, 无泄漏
- [ ] Unicode + i18n: zh_CN + en_US + 伪本地化
- [ ] §28 全矩阵截图: ¥ 全部通过 golden 对比
- [ ] legacy baseline 214 + new tests all pass
- [ ] 无硬编码路径
- [ ] 无 API Key 泄漏
- [ ] 无 QTableView/QMenuBar/QToolBar/QStatusBar
- [ ] 无 OpenAI/Anthropic 品牌预设
- [ ] 打包验证 (Task 6)
- [ ] 正式入口切换 (Task 7, Product Owner Gate)

**自动化测试命令:**
```bash
pytest tests/integration/ -v
pytest tests/screenshots/test_full_matrix.py -v
pytest tests/
python acceptance_test.py
```

**Product Owner 批准栏:**
- [ ] M8 审查通过
- [ ] 批准发布候选

---

> **未经 Product Owner 最终验收不得 push 或 release。**
>
> **旧代码淘汰前必须有全部回归证据。**
