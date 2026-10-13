# M7: System Status, Errors, Recovery & Diagnostics Implementation Plan

> 本计划供 Claude Code 在 Product Owner 明确批准后逐任务执行。当前编写计划不构成实施授权。

**Goal:** 实现 System Status 模态、四层错误呈现、统一错误对象、数据损坏恢复和诊断包导出。

**Architecture:** `StatusController` 聚合各组件健康状态；`ErrorHandler` 统一错误生成和路由；`RecoveryManager` 处理配置/缓存/工作区/Undo 损坏恢复；`DiagnosticsExporter` 生成脱敏诊断包。

**Tech Stack:** PySide6 QML, Python, pytest

**Authority:** XUXIA_DETAILED_DESIGN §22 System Status, §23 Error Presentation, §24 Data Recovery, §25 Diagnostics, §26 Security.

**Prerequisites:** M3（含 RetryExecutor）+ M6 全部通过。

**Global Constraints:** 不显示 Key；诊断脱敏；Undo 损坏时阻止新 Apply/Undo；不静默删除历史。

---

## Task 1: Status Controller

**Purpose:** 聚合各组件健康状态。

**Files:**
- Create: `src/controllers/status_controller.py`, `tests/unit/test_status_controller.py`

**Interfaces:**
- Produces: `StatusController.check_all() → SystemStatus`
- Produces: `SystemStatus(overall: Ready|Checking|Attention|Unavailable, components: list[ComponentStatus])`
- Produces: `ComponentStatus(id, name, status, detail, last_checked)`

**Steps:**
- [ ] 编写 `test_all_components_ready()` — 全部正常 → Ready
- [ ] 编写 `test_local_component_failed()` — 文件扫描失败 → Attention
- [ ] 编写 `test_provider_failed()` — API 连接失败 → Attention
- [ ] 编写 `test_text_ok_vision_unavailable()` — 文本可用视觉不可用
- [ ] 编写 `test_status_cached_with_ttl()` — 状态缓存 60s
- [ ] 实现 `StatusController`
- [ ] 运行: `pytest tests/unit/test_status_controller.py -v`

**Commit:** `feat: add system status controller`

---

## Task 2: Status Modal QML

**Purpose:** System Status 居中模态对话框。

**Files:**
- Create: `src/ui_qml/pages/StatusModal.qml`, `src/ui_qml/components/StatusChip.qml`, `src/ui_qml/components/ComponentStatusRow.qml`
- Test: `tests/qml/test_status_modal.py`

**Steps:**
- [ ] 实现居中模态 + 背景模糊遮罩
- [ ] 实现 StatusChip: Ready (绿) / Checking (蓝动画) / Attention (黄) / Unavailable (红)
- [ ] 实现 ComponentStatusRow: 本地处理 / 云端 AI (文本+视觉分别显示) / Provider/Model
- [ ] 实现操作按钮: 重新检查 / 重载 / 清缓存 / 测试连接 / 打开设置
- [ ] 实现导航栏状态 badge (颜色对应 overall)
- [ ] i18n
- [ ] 截图: 四种总体状态 + 文本可用视觉不可用

**Commit:** `feat: add system status modal`

---

## Task 3: Unified Error Object & Handler

**Purpose:** 实现 `AppError` 和四层错误路由。

**Files:**
- Create: `src/core/app_error.py`, `src/core/error_handler.py`, `tests/unit/test_error_handler.py`

**Interfaces:**
- Produces: `AppError(code, scope, severity, retryable, user_message_id, recommended_action, sanitized_detail, correlation_id)`
- Produces: `ErrorHandler.route(error) → ErrorPresentation`

**Steps:**
- [ ] 编写 `test_app_error_all_fields()` — 全部字段可构造
- [ ] 编写 `test_error_severity_routing()` — scope + severity → 层级
- [ ] 编写 `test_all_error_codes_covered()` — 401/403/404/429/timeout/network/5xx/json_invalid/no_vision/budget/file_*/conflict/permission
- [ ] 编写 `test_retryable_flag()` — 429/timeout/5xx → retryable=true; 401 → false
- [ ] 编写 `test_sanitized_no_key_no_body()` — 不含 Key/堆栈/请求正文
- [ ] 实现 `AppError`, `ErrorHandler`
- [ ] 运行: `pytest tests/unit/test_error_handler.py -v`

**Commit:** `feat: add unified error object and handler`

---

## Task 4: Error Presentation QML

**Purpose:** 四层错误呈现的 QML 组件。

**Files:**
- Create: `src/ui_qml/components/FileCardError.qml`, `src/ui_qml/components/BatchError.qml`, `src/ui_qml/components/AppToast.qml`, `src/ui_qml/components/BlockingModal.qml`
- Test: `tests/qml/test_error_presentation.py`

**Steps:**
- [ ] 实现 FileCardError: 卡片内错误图标 + 简短信息 + 重试按钮
- [ ] 实现 BatchError: 批次结果摘要 (N 成功 M 失败)
- [ ] 实现 AppToast: 顶部滑入通知，3s 自动消失
- [ ] 实现 BlockingModal: 阻断错误模态
- [ ] i18n
- [ ] 截图: 每种错误层级

**Commit:** `feat: add error presentation QML components`

---

## Task 5: Retry State UI & Fault Injection

**Purpose:** 重试状态的 UI 呈现、用户可见错误和已有 RetryExecutor (M3) 的端到端回归测试。RetryExecutor 已在 M3 实现，本任务只负责 UI 和回归验证。

**Files:**
- Test: `tests/integration/test_retry_ui.py`, `tests/integration/test_fault_injection.py`

**Steps:**
- [ ] 编写 `test_retry_progress_visible()` — 重试进行中 UI 显示状态
- [ ] 编写 `test_retry_exhausted_user_error()` — 重试耗尽后用户可见错误信息
- [ ] 编写 `test_429_backoff_end_to_end()` — 模拟 429 → 重试 → 成功或失败
- [ ] 编写 `test_network_timeout_ui()` — 网络超时 UI 反馈
- [ ] 编写 `test_disk_full_blocks_apply()` — 磁盘满阻止 Apply
- [ ] 编写 `test_permission_denied_ui()` — 权限拒绝用户提示
- [ ] 编写 `test_file_locked_ui()` — 文件被占用 UI 反馈
- [ ] 对 M3 RetryExecutor 执行端到端回归
- [ ] 运行: `pytest tests/integration/test_retry_ui.py tests/integration/test_fault_injection.py -v`

**Commit:** `feat: add retry state UI and fault injection`

---

## Task 6: Fault Injection Test Suite

**Purpose:** 故障注入覆盖网络/磁盘/权限/占用场景。

**Files:**
- Create: `tests/integration/test_fault_injection.py`

**Steps:**
- [ ] 编写 `test_network_timeout_handled()` — 模拟超时 → 重试 → 失败 → 用户可见错误
- [ ] 编写 `test_429_rate_limit_handled()` — 模拟限流 → 重试
- [ ] 编写 `test_disk_full_handled()` — 磁盘满 → 阻止 Apply
- [ ] 编写 `test_permission_denied_handled()` — 权限拒绝 → 明确错误
- [ ] 编写 `test_file_locked_handled()` — 文件被占用 → 跳过
- [ ] 运行: `pytest tests/integration/test_fault_injection.py -v`

**Commit:** `test: add fault injection test suite`

---

## Task 7: Config Corruption Recovery

**Purpose:** 配置损坏恢复。

**Files:**
- Create: `src/core/recovery.py`, `tests/unit/test_recovery_config.py`

**Steps:**
- [ ] 编写 `test_corrupt_json_isolated()` — 损坏文件被隔离 (重命名为 `.corrupted`)
- [ ] 编写 `test_load_last_valid_snapshot()` — 加载最近有效快照
- [ ] 编写 `test_no_valid_snapshot_uses_safe_defaults()` — 无快照 → 安全默认值
- [ ] 编写 `test_credentials_not_touched()` — 凭据管理器不受影响
- [ ] 实现 `ConfigRecovery`
- [ ] 运行: `pytest tests/unit/test_recovery_config.py -v`

**Commit:** `feat: add config corruption recovery`

---

## Task 8: Cache Corruption Recovery

**Purpose:** 缓存损坏自动清理重建。

**Files:**
- Modify: `src/core/recovery.py` (扩展), `tests/unit/test_recovery_cache.py`

**Steps:**
- [ ] 编写 `test_corrupt_cache_auto_cleaned()` — 缓存损坏 → 自动清理
- [ ] 编写 `test_cache_rebuilt_on_next_use()` — 清理后下次使用自动重建
- [ ] 实现
- [ ] 运行: `pytest tests/unit/test_recovery_cache.py -v`

**Commit:** `feat: add cache corruption auto-recovery`

---

## Task 9: Workspace & Undo Corruption Recovery

**Purpose:** 工作区和 Undo 历史损坏恢复。

**Files:**
- Modify: `src/core/recovery.py` (扩展), `tests/unit/test_recovery_workspace.py`

**Steps:**
- [ ] 编写 `test_corrupt_workspace_isolated()` — 损坏工作区隔离
- [ ] 编写 `test_corrupt_undo_pauses_apply()` — Undo 损坏 → 阻止新 Apply/Undo
- [ ] 编写 `test_corrupt_undo_does_not_silent_drop()` — 不静默丢弃历史
- [ ] 编写 `test_user_notified_of_corruption()` — 用户收到通知
- [ ] 实现
- [ ] 运行: `pytest tests/unit/test_recovery_workspace.py -v`

**Commit:** `feat: add workspace and undo corruption recovery`

---

## Task 10: Diagnostics Exporter

**Purpose:** 生成脱敏诊断包。

**Files:**
- Create: `src/core/diagnostics.py`, `tests/unit/test_diagnostics.py`

**Steps:**
- [ ] 编写 `test_diagnostics_includes_version_and_components()` — 版本/组件状态
- [ ] 编写 `test_diagnostics_excludes_api_key()` — 不含 Key
- [ ] 编写 `test_diagnostics_excludes_file_content()` — 不含文件正文
- [ ] 编写 `test_diagnostics_excludes_raw_ai_requests()` — 不含原始 AI 请求
- [ ] 编写 `test_diagnostics_excludes_full_paths()` — 路径脱敏
- [ ] 编写 `test_diagnostics_preview_before_export()` — 导出前显示预览
- [ ] 实现 `DiagnosticsExporter`
- [ ] 运行: `pytest tests/unit/test_diagnostics.py -v`

**Commit:** `feat: add redacted diagnostics exporter`

---

## Task 11: Diagnostics QML

**Purpose:** 诊断包导出 UI。

**Files:**
- Create: `src/ui_qml/components/DiagnosticsDialog.qml`
- Test: `tests/qml/test_diagnostics.py`

**Steps:**
- [ ] 实现导出按钮 → 预览对话框 → 确认导出
- [ ] 实现保存文件对话框
- [ ] i18n
- [ ] 截图: 预览 + 导出确认

**Commit:** `feat: add diagnostics export UI`

---

## M7 Gate Report Checklist

- [ ] System Status 四种总体状态
- [ ] 文本/视觉能力分别显示
- [ ] 四层错误呈现全部覆盖
- [ ] 16+ 错误码均有对应处理
- [ ] 429/timeout/5xx 有界重试
- [ ] 配置/缓存/工作区/Undo 损坏恢复
- [ ] 诊断包脱敏
- [ ] 故障注入测试全部通过
- [ ] legacy baseline 214 + 本阶段全部新增测试通过

**自动化测试命令:**
```bash
pytest tests/unit/test_status_controller.py tests/unit/test_error_handler.py tests/unit/test_retry.py tests/unit/test_recovery_*.py tests/unit/test_diagnostics.py -v
pytest tests/integration/test_fault_injection.py -v
pytest tests/qml/test_status_modal.py tests/qml/test_error_presentation.py tests/qml/test_diagnostics.py -v
pytest tests/
python acceptance_test.py
```

**Product Owner 批准栏:**
- [ ] M7 审查通过
- [ ] 批准进入 M8

> **未批准不得进入 M8。**
