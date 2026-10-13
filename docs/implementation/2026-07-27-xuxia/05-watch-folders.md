# M5: Watch Folders Implementation Plan

> 本计划供 Claude Code 在 Product Owner 明确批准后逐任务执行。当前编写计划不构成实施授权。

**Goal:** 实现 Watch Folders 完整功能：配置管理、Review First/Auto Apply、防抖、回流防护、预算保护、结果窗口。复用 Batch 卡片和 Apply/Undo 引擎。

**Architecture:** `WatchFolderController` 管理配置和监控生命周期；`FolderWatcher` (现有) 适配新版接口。每个 Watch 独立配置和结果窗口。

**Tech Stack:** watchdog, pytest, Qt signals

**Authority:** XUXIA_DETAILED_DESIGN §11 Watch Folders, §10 Apply/Undo, §18 Budget.

**Prerequisites:** M2 + M3 + M4 全部通过。

**Global Constraints:** 复用 Batch Apply/Undo 引擎；防抖 + 临时文件过滤 + 回流防护；预算 fail-closed；编辑配置前暂停。

---

## Task 1: Watch Config Domain Model

**Purpose:** 定义监控配置数据模型。

**Files:**
- Create: `src/core/watch_config.py`, `tests/unit/test_watch_config.py`

**Interfaces:**
- Produces: `WatchConfig(id, source_dir, target_dir, template_id, recursive, mode: ReviewFirst|AutoApply, status: Active|Paused|Error|BudgetPaused)`

**Steps:**
- [ ] 编写 `test_watch_config_serialization()` — JSON 持久化不含 Key
- [ ] 编写 `test_watch_config_validation()` — source_dir 必填
- [ ] 编写 `test_mode_enum()` — ReviewFirst / AutoApply
- [ ] 编写 `test_status_enum()` — Active/Paused/Error/BudgetPaused
- [ ] 实现 `WatchConfig`
- [ ] 运行: `pytest tests/unit/test_watch_config.py -v`

**Commit:** `feat: add watch config domain model`

---

## Task 2: Watch Folder Controller

**Purpose:** 监控生命周期管理。

**Files:**
- Create: `src/controllers/watch_controller.py`, `tests/unit/test_watch_controller.py`
- Modify: `src/core/folder_watcher.py` (适配)

**Steps:**
- [ ] 编写 `test_add_watch_auto_starts()` — 添加配置 → 自动启动 (修复 GAP-035)
- [ ] 编写 `test_pause_resume()` — Pause → 停止监控; Resume → 恢复
- [ ] 编写 `test_remove_watch_stops_observer()` — 删除配置 → 停止
- [ ] 编写 `test_restart_recovery()` — 崩溃后自动重启（指数退避）
- [ ] 编写 `test_debounce_file_stable()` — 2s 文件稳定等待
- [ ] 编写 `test_temp_file_filter()` — `.tmp` / `~$` 前缀过滤
- [ ] 编写 `test_output_dir_recursion_guard()` — 不监控自身输出目录
- [ ] 实现 `WatchController`
- [ ] 运行: `pytest tests/unit/test_watch_controller.py -v`

**Commit:** `feat: add watch folder controller with lifecycle management`

---

## Task 3: Review First Pipeline

**Purpose:** 实现 Review First 模式：检测 → 提取 → AI → 审阅队列。

**Files:**
- Create: `src/controllers/review_first_handler.py`, `tests/integration/test_review_first.py`

**Steps:**
- [ ] 编写集成测试: 放入文件 → 2s 后进入待审阅队列
- [ ] 编写测试: 队列项出现在独立结果窗口
- [ ] 编写测试: 用户 Approve → 复用 Batch Apply 引擎
- [ ] 编写测试: 用户 Ignore → 标记忽略
- [ ] 实现 `ReviewFirstHandler`
- [ ] 运行: `pytest tests/integration/test_review_first.py -v`

**Commit:** `feat: add Review First watch pipeline`

---

## Task 4: Auto Apply Pipeline

**Purpose:** 实现 Auto Apply 模式：全自动管线。

**Files:**
- Create: `src/controllers/auto_apply_handler.py`, `tests/integration/test_auto_apply.py`

**Steps:**
- [ ] 编写测试: 放入文件 → 自动 Extract → AI → Apply
- [ ] 编写测试: 复用 Batch 的 RenamePlan/Undo 引擎
- [ ] 编写测试: 失败文件保留在队列中可 Retry
- [ ] 编写测试: 低置信度 → 按质量模式升级重试
- [ ] 编写测试: 超预算 → 暂停并通知
- [ ] 实现 `AutoApplyHandler`
- [ ] 运行: `pytest tests/integration/test_auto_apply.py -v`

**Commit:** `feat: add Auto Apply watch pipeline`

---

## Task 5: Watch Config Edit Impact

**Purpose:** 编辑监控配置前的影响确认。

**Files:**
- Create: `src/controllers/watch_edit_handler.py`, `tests/unit/test_watch_edit.py`

**Steps:**
- [ ] 编写 `test_edit_config_pauses_first()` — 编辑前自动暂停
- [ ] 编写 `test_clear_pending_shows_impact_summary()` — 显示将被清理的未应用任务数
- [ ] 编写 `test_applied_and_undo_preserved()` — 已应用和 Undo 历史保留
- [ ] 编写 `test_delete_config_does_not_delete_files()` — 删除配置不删文件
- [ ] 编写 `test_delete_config_does_not_undo()` — 删除配置不 Undo
- [ ] 实现 `WatchEditHandler`
- [ ] 运行: `pytest tests/unit/test_watch_edit.py -v`

**Commit:** `feat: add watch config edit impact handling`

---

## Task 6: Watch Budget Protection

**Purpose:** Watch 的独立预算保护。

**Files:**
- Modify: `src/controllers/watch_controller.py` (扩展)
- Test: `tests/unit/test_watch_budget.py`

**Steps:**
- [ ] 编写 `test_watch_budget_limit_blocks_auto()` — Auto Apply 超预算 → 暂停
- [ ] 编写 `test_watch_budget_warning_in_review()` — Review First 超预算 → 提示但仍可手动 Approve
- [ ] 编写 `test_watch_budget_reset_on_new_month()` — 月度重置
- [ ] 实现
- [ ] 运行: `pytest tests/unit/test_watch_budget.py -v`

**Commit:** `feat: add watch folder budget protection`

---

## Task 7: Watch QML UI

**Purpose:** Watch Folders 页面 QML 实现。

**Files:**
- Create: `src/ui_qml/pages/WatchPage.qml`, `src/ui_qml/components/WatchCard.qml`, `src/ui_qml/components/WatchForm.qml`
- Test: `tests/qml/test_watch.py`

**Steps:**
- [ ] 编写测试: 空态引导卡片
- [ ] 编写测试: 新建表单渲染（内容区左侧固定宽度表单卡，非居中弹窗）
- [ ] 编写测试: Active/Paused/Error/BudgetPaused 四种状态卡
- [ ] 编写测试: 结果窗口展示
- [ ] 实现 WatchPage + WatchCard + WatchForm
- [ ] 截图: 空态、新建表单、四种状态卡、结果窗口

**Commit:** `feat: add watch folders QML UI`

---

## Task 8: Watch Restart Recovery

**Purpose:** 重启后恢复监控配置。

**Files:**
- Modify: `src/controllers/watch_controller.py`
- Test: `tests/integration/test_watch_recovery.py`

**Steps:**
- [ ] 编写集成测试: 创建 2 个 Watch → 关闭应用 → 重启 → 2 个 Watch 自动恢复
- [ ] 编写测试: 恢复后配置匹配（source/target/template/mode）
- [ ] 实现
- [ ] 运行: `pytest tests/integration/test_watch_recovery.py -v`

**Commit:** `feat: add watch folder restart recovery`

---

## M5 Gate Report Checklist

- [ ] Watch 配置 CRUD + 持久化
- [ ] 添加首个监控 → watcher 自动启动 (GAP-035 fixed)
- [ ] Review First: 检测 → 队列 → 审核 → Apply/Undo
- [ ] Auto Apply: 全自动 + 复用 Batch 引擎
- [ ] 防抖 + 临时文件过滤 + 回流防护
- [ ] 预算保护 (fail-closed)
- [ ] 编辑前暂停 + 影响摘要
- [ ] 删除配置不删文件/不 Undo
- [ ] 重启恢复
- [ ] legacy baseline 214 + 本阶段全部新增测试通过

**自动化测试命令:**
```bash
pytest tests/unit/test_watch_*.py -v
pytest tests/integration/test_review_first.py tests/integration/test_auto_apply.py tests/integration/test_watch_recovery.py -v
pytest tests/qml/test_watch.py -v
pytest tests/
python acceptance_test.py
```

**Product Owner 批准栏:**
- [ ] M5 审查通过
- [ ] 批准进入 M6 (可与 M5 并行但 M6 不依赖 M5)

> **未批准不得将 Watch 标记为已完成。**
