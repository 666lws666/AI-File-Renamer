# M2: Domain Queue, Apply & Undo Implementation Plan

> 本计划供 Claude Code 在 Product Owner 明确批准后逐任务执行。当前编写计划不构成实施授权。

**Goal:** 实现 FileTask 状态机、BatchWorkspace、TaskQueue、RenamePlan、Apply 预检引擎和 UndoRecord 持久化。本阶段不调用 AI，使用确定性 mock provider 返回结构化字段。

**Architecture:** 领域层（`src/core/file_task.py`, `rename_plan.py`, `batch_workspace.py`, `task_queue.py`）不依赖 Qt。控制器层（`src/controllers/batch_controller.py`）通过 Qt signals 连接领域和 QML UI。Apply/Undo 复用现有 `rename_engine.py` 和 `rename_history.py` 并适配新版接口。

**Tech Stack:** Python dataclasses/pydantic, pytest, 现有 `os.rename` 和 `RenameHistory`

**Authority:** XUXIA_DETAILED_DESIGN §5 Data Flow, §8 Batch Non-Empty, §9 Inline Edit, §10 Apply/Undo, §26 Security Invariants.

**Prerequisites:** M1 全部通过。

**Global Constraints:** 无 AI 调用（mock provider）；Apply 前预检；Undo 稳定；Clear Workspace 不删 Undo；批量逐项执行。

---

## Task 1: FileTask State Machine

**Purpose:** 实现 FileTask 领域对象及其严格状态转换。

**Files:**
- Create: `src/core/file_task.py`, `tests/unit/test_file_task.py`

**Interfaces:**
- Produces: `FileTask(id, original_path, original_name, ext, size, mtime, state, suggested_fields, final_name, error_info)`
- Produces: `FileTaskState` enum: PENDING, EXTRACTING, EXTRACTED, SUGGESTING, SUGGESTED, APPLIED, FAILED, CANCELLED, IGNORED, UNDONE
- Produces: `FileTask.transition(new_state) → FileTask` — 非法转换抛 `InvalidStateTransitionError`

**Steps:**
- [ ] 编写 `test_valid_transitions()` — 所有合法状态转换
- [ ] 编写 `test_invalid_transition_raises()` — PENDING→APPLIED 抛异常
- [ ] 编写 `test_applied_to_undone_valid()` — APPLIED→UNDONE
- [ ] 编写 `test_undone_can_reapply()` — UNDONE→PENDING→...→APPLIED
- [ ] 编写 `test_display_state_mapping()` — 内部状态→显示名映射（待处理/分析中/待确认/已撤销/已应用/失败/已取消/已忽略）
- [ ] 实现 `FileTask` 和 `FileTaskState`
- [ ] 运行: `pytest tests/unit/test_file_task.py -v`

**Verification:** 非法状态转换一律抛异常，显示映射八态完整。

**Commit:** `feat: add FileTask state machine with strict transitions`

---

## Task 2: NamingFields & RenamePlan (Pure Data)

**Purpose:** 定义 AI 输出的结构化字段和纯数据重命名计划。RenamePlan 是不可变数据对象，不执行 I/O。

**Files:**
- Create: `src/core/naming_fields.py`, `src/core/rename_plan.py`
- Test: `tests/unit/test_naming_fields.py`, `tests/unit/test_rename_plan.py`

**Interfaces:**
- Produces: `NamingFields(dcDate, dcTitle, dcSubject, dcType, dcCreator, dcIdentifier, extOrganization, extProject, extStatus, extVersion, confidence)` — frozen dataclass
- Produces: `RenamePlan(task_id, source_path, target_path, expected_source_fingerprint, template_context)` — frozen/immutable dataclass, 纯数据
- Produces: `PreflightResult(can_execute, errors, warnings, resolved_source, resolved_target)` — 预检服务生成的纯数据结果
- RenamePlan 不含 execute/apply/undo 方法, 不含 os/pathlib 写操作, 不含任何文件执行服务依赖

**Steps:**
- [ ] 编写 `test_naming_fields_from_json()` — 解析 AI JSON 输出
- [ ] 编写 `test_naming_fields_missing_optional()` — 可选字段缺失不抛异常
- [ ] 编写 `test_rename_plan_is_immutable()` — frozen dataclass, 构造后不可修改
- [ ] 编写 `test_rename_plan_has_no_execute_method()` — 不含 execute/apply/undo
- [ ] 编写 `test_rename_plan_construction_performs_no_io()` — 构造时不访问文件系统
- [ ] 编写 `test_rename_plan_contains_expected_source_fingerprint()` — 含源文件指纹 (size + mtime)
- [ ] 实现 `NamingFields` 和 `RenamePlan` 为 frozen dataclass
- [ ] 运行: `pytest tests/unit/test_naming_fields.py tests/unit/test_rename_plan.py -v`

**Commit:** `feat: add NamingFields and RenamePlan pure data models`

---

## Task 3: Inline Filename Validator

**Purpose:** 实现文件名合法性校验，保护扩展名，检测非法字符和设备名。

**Files:**
- Create: `src/core/filename_validator.py`, `tests/unit/test_filename_validator.py`

**Interfaces:**
- Produces: `validate_filename(name: str, original_ext: str) → list[ValidationError]`
- Produces: `ValidationError(field, code, message_id, detail)`

**Steps:**
- [ ] 编写 `test_empty_name_rejected()`
- [ ] 编写 `test_windows_reserved_names()` — CON/PRN/AUX/NUL/COM1–9/LPT1–9
- [ ] 编写 `test_illegal_chars()` — `< > : " / \ | ? *`
- [ ] 编写 `test_path_too_long()` — > 260 字符
- [ ] 编写 `test_ext_protected()` — 编辑不改变扩展名部分
- [ ] 编写 `test_conflict_detection()` — 同目录已存在同名文件
- [ ] 实现 `filename_validator.py`
- [ ] 连接 `InlineEdit.qml` 验证反馈（显示/隐藏错误）
- [ ] 运行: `pytest tests/unit/test_filename_validator.py -v`

**Commit:** `feat: add filename validator with Windows safety checks`

---

## Task 4: BatchWorkspaceController

**Purpose:** 实现批量工作区控制器：导入、搜索、筛选、选中管理。

**Files:**
- Create: `src/controllers/batch_workspace_controller.py`, `tests/unit/test_batch_workspace_controller.py`

**Interfaces:**
- Consumes: `FileScanner` (现有)
- Produces: `BatchWorkspaceController.add_files(paths)`, `.search(query)`, `.filter_by_state(state)`, `.selection_model`
- Events: `tasks_changed`, `selection_changed`, `import_completed`

**Steps:**
- [ ] 编写 `test_import_files_creates_pending_tasks()` — mock scanner
- [ ] 编写 `test_search_filters_by_name()` — "报告" 仅匹配含有关键词的任务
- [ ] 编写 `test_filter_by_state()` — 筛选 "失败" 仅返回 FAILED
- [ ] 编写 `test_selection_count_tracking()` — 选中 3 项 → 计数 3
- [ ] 编写 `test_clear_workspace_preserves_undo()` — 清空后 UndoRecord 仍可访问
- [ ] 实现 `BatchWorkspaceController`
- [ ] 运行: `pytest tests/unit/test_batch_workspace_controller.py -v`

**Commit:** `feat: add BatchWorkspaceController with search and filter`

---

## Task 5: TaskQueueController & Cancel/Retry/Ignore

**Purpose:** 实现任务队列编排、取消、重试和忽略。

**Files:**
- Create: `src/controllers/task_queue_controller.py`, `tests/unit/test_task_queue_controller.py`

**Interfaces:**
- Consumes: `BatchWorkspaceController`
- Produces: `TaskQueueController.enqueue(tasks)`, `.cancel()`, `.retry(task)`, `.ignore(task)`
- Events: `progress_changed(current, total)`, `task_state_changed(task)`, `queue_completed`

**Steps:**
- [ ] 编写 `test_enqueue_processes_all()` — mock provider 返回确定字段
- [ ] 编写 `test_cancel_preserves_completed()` — 取消后已处理项保留结果
- [ ] 编写 `test_retry_single_task()` — 单个 FAILED 任务重试
- [ ] 编写 `test_ignore_removes_from_active()` — Ignore 后任务状态 IGNORED
- [ ] 编写 `test_progress_updates()` — 进度信号正确触发
- [ ] 实现 `TaskQueueController`
- [ ] 运行: `pytest tests/unit/test_task_queue_controller.py -v`

**Commit:** `feat: add TaskQueueController with cancel, retry, ignore`

---

## Task 6: RenameExecutor — Sole File I/O Boundary

**Purpose:** RenameExecutor 是文件 I/O 的唯一执行边界。接收已通过预检的 RenamePlan，执行 rename/move，生成逐项结果和 UndoRecord。RenamePlan 本身是纯数据，不执行 I/O。

**Files:**
- Create: `src/core/rename_executor.py`, `src/core/preflight_service.py`, `tests/unit/test_rename_executor.py`, `tests/unit/test_preflight_service.py`

**Interfaces:**
- Consumes: `RenamePlan` (纯数据), `PreflightResult`, `RenameHistory` (现有适配)
- Produces: `RenameExecutor.execute(plans: list[RenamePlan]) → list[BatchResult]`
- Produces: `BatchResult(task_id, success, error, new_path)`
- Produces: `PreflightService.check(plan: RenamePlan) → PreflightResult`

**Steps:**
- [ ] 编写 `test_executor_single_apply_creates_undo_record()` — Apply 后 UndoRecord 存在
- [ ] 编写 `test_executor_batch_apply_partial_success()` — 3 成功 2 失败，每项独立，不伪报成功
- [ ] 编写 `test_executor_permission_denied()` — 权限拒绝 → FAILED
- [ ] 编写 `test_executor_file_changed_detected()` — mtime/size 变化 → FAILED
- [ ] 编写 `test_executor_conflict_auto_counter()` — 同名 → `_1`, `_2`
- [ ] 编写 `test_preflight_blocks_invalid_name()` — 文件名非法 → can_execute=false
- [ ] 编写 `test_preflight_blocks_locked_file()` — 文件被占用 → 拒绝
- [ ] 编写 `test_preflight_creates_target_dir()` — 目标目录不存在 → 自动创建
- [ ] 实现 `RenameExecutor` 和 `PreflightService`
- [ ] 适配现有 `rename_history.py`
- [ ] 运行: `pytest tests/unit/test_rename_executor.py tests/unit/test_preflight_service.py -v`

**Commit:** `feat: add RenameExecutor as sole file I/O boundary`

---

## Task 7: Undo Engine & Persistence

**Purpose:** 实现批次 Undo、UndoRecord 持久化和 Clear Workspace 隔离。

**Files:**
- Create: `src/core/undo_manager.py`, `tests/unit/test_undo_manager.py`
- Modify: `src/core/rename_history.py` (适配)

**Interfaces:**
- Consumes: `RenameHistory` (现有)
- Produces: `UndoManager.undo_last_batch() → list[BatchResult]`, `.get_undoable_batches()`, `.clear_workspace_preserves_history()`

**Steps:**
- [ ] 编写 `test_undo_single_batch()` — Apply 后 Undo → 文件名恢复
- [ ] 编写 `test_undo_multi_batch_lifo()` — 3 批 Apply → Undo 反序恢复
- [ ] 编写 `test_undo_failure_partial()` — Undo 第 2 个文件失败，第 1 个保持已撤销
- [ ] 编写 `test_undo_persisted_across_restart()` — JSONL 持久化可恢复
- [ ] 编写 `test_clear_workspace_does_not_remove_undo()` — 清空工作区后 Undo 仍可用
- [ ] 编写 `test_undone_items_can_reapply()` — 已撤销项重新 Apply 需预检
- [ ] 实现 `UndoManager`
- [ ] 运行: `pytest tests/unit/test_undo_manager.py -v`

**Commit:** `feat: add undo engine with persistence`

---

## Task 8: Batch Page Controller Binding

**Purpose:** 将领域控制器绑定到 QML Batch 页面。

**Files:**
- Create: `src/controllers/batch_page_controller.py`
- Modify: `src/ui_qml/pages/BatchPage.qml`
- Test: `tests/integration/test_batch_page_flow.py`

**Steps:**
- [ ] 编写集成测试: 导入 5 个 mock 文件 → 显示 5 张待处理卡片
- [ ] 编写集成测试: 选中 2 个 Apply → 仅 2 个状态变为已应用
- [ ] 编写集成测试: Apply 后 Undo → 状态变为已撤销
- [ ] 编写集成测试: 搜索 + 筛选 + 编辑 + Apply 全流程
- [ ] 实现 `BatchPageController` 连接 QML 信号和领域层
- [ ] 运行: `pytest tests/integration/test_batch_page_flow.py -v`

**Verification:** 端到端 mock 流程通过：Import → Suggest → Review → Apply → Undo。

**Commit:** `feat: bind batch page controller to domain layer`

---

## M2 Gate Report Checklist

- [ ] FileTask 八状态严格转换，非法转换抛异常
- [ ] RenamePlan 预检 6 项全部覆盖
- [ ] 文件名校验: 非法字符/保留名/长度/扩展名保护/冲突
- [ ] 批量 Apply 部分成功逐项报告
- [ ] Undo LIFO + 持久化 + 重启恢复
- [ ] Clear Workspace 不删 Undo 历史
- [ ] 搜索、筛选、选择、编辑、Retry、Ignore、Cancel
- [ ] 故障注入: 权限拒绝/文件变化/文件占用
- [ ] 无 AI 调用（全部 mock）
- [ ] legacy baseline 214 + 本阶段全部新增测试通过

**自动化测试命令:**
```bash
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest tests/
python acceptance_test.py
```

**Product Owner 批准栏:**
- [ ] M2 审查通过
- [ ] 批准进入 M3/M4/M6

> **未批准不得进入后续里程碑。**
