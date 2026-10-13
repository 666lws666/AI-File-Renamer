# M6: Preferences & Provider Management Implementation Plan

> 本计划供 Claude Code 在 Product Owner 明确批准后逐任务执行。当前编写计划不构成实施授权。

**Goal:** 实现单页滚动卡片式设置页面，覆盖通用、AI Provider 管理、质量模式、预算、隐私、缓存、用量和诊断入口。原子保存 fail-closed。

**Architecture:** `SettingsController` 管理所有配置读写；QML 单页 `PreferencesPage` 含多个 `SettingsCard` 组件。保存时通过 `SettingsController.save_all()` 原子写入。

**Tech Stack:** PySide6 QML, keyring, pytest

**Authority:** XUXIA_DETAILED_DESIGN §14 Preferences, §15 Provider Design, §18 Budget, §20 Privacy, §21 i18n.

**Prerequisites:** M2 + M3 全部通过。

**Global Constraints:** 原子保存；fail-closed；保存前不修改全局配置；取消恢复原状态；Key 仅存 Credential Manager。

---

## Task 1: SettingsSaveTransaction — 跨存储补偿事务

**Purpose:** JSON 和 Windows Credential Manager 是两个独立存储系统，无法原生共同事务。实现补偿事务协议确保 all-or-nothing 语义。不得虚构两个存储具有原生共同事务。

**Files:**
- Create: `src/controllers/settings_transaction.py`, `tests/unit/test_settings_transaction.py`

**Interfaces:**
- Consumes: `src/config.py`, `src/utils/credential_manager.py`
- Produces: `SettingsSaveTransaction.commit(candidate: AppConfig) -> SettingsSaveResult`
- Produces: `SettingsSaveResult(success, errors, rollback_errors)`
- Events: `settings_saved(AppConfig)`, `settings_save_failed(AppError)`

**补偿事务顺序（固定，不可重排）：**
1. 从当前全局配置创建 candidate deep copy
2. 将表单更改只应用到 candidate
3. 完整预验证 candidate
4. 将不含 API Key 的 candidate JSON 序列化到目标目录同盘临时文件
5. flush/fsync 临时文件
6. 快照所有将被修改/删除的旧凭据值及"原先不存在"状态，只保存在内存（不记录日志）
7. 逐项写入或删除新凭据
8. 凭据失败 -> 按快照补偿回滚已改变凭据 -> 删除临时 JSON -> 不替换正式 JSON -> 不修改全局 app_config -> 对话框不关闭
9. 凭据全部成功 -> 用 os.replace 原子替换正式 settings JSON
10. JSON replace 失败 -> 按快照补偿回滚全部凭据 -> 保留旧 settings JSON -> 删除临时文件 -> 不修改全局 app_config -> 对话框不关闭
11. JSON replace 成功 -> 一次性替换内存中全局 app_config
12. 成功后清理快照和临时数据
13. 发布 settings-saved 事件

**Steps:**
- [ ] 编写 test_candidate_validation_fails_blocks_all() — candidate 预验证失败，不执行后续
- [ ] 编写 test_temp_serialization_fails_rollback() — 临时文件写入失败，正确报告
- [ ] 编写 test_temp_fsync_fails_rollback() — fsync 失败，正确报告
- [ ] 编写 test_first_credential_write_fails_rollback() — 第一个凭据写入失败，补偿回滚
- [ ] 编写 test_mid_credential_write_fails_rollback() — 中间凭据写入失败，补偿已写凭据
- [ ] 编写 test_credential_delete_fails_rollback() — 凭据删除失败，补偿
- [ ] 编写 test_json_replace_fails_rollback_all_credentials() — JSON 替换失败，补偿全部凭据
- [ ] 编写 test_rollback_failure_reports_high_severity() — 补偿本身失败，高严重度错误，阻止关闭设置页
- [ ] 编写 test_json_success_updates_global_once() — JSON 成功后全局状态只更新一次
- [ ] 编写 test_any_failure_does_not_mutate_global() — 任一失败不污染原 app_config
- [ ] 编写 test_any_failure_does_not_report_success() — 任一失败不虚报成功
- [ ] 编写 test_key_never_in_json_log_diag() — Key 不进入 JSON、日志或诊断包
- [ ] 编写 test_clear_key_deletes_correct_credential() — 清空 Key 能恢复/删除正确凭据
- [ ] 实现 SettingsSaveTransaction
- [ ] 运行: pytest tests/unit/test_settings_transaction.py -v

**Commit:** feat: add cross-storage compensation transaction for settings save

---

## Task 2: General Settings Card

**Purpose:** 通用设置卡片：语言、主题、默认模板、文件大小限制。

**Files:**
- Create: `src/ui_qml/components/GeneralSettingsCard.qml`
- Test: `tests/qml/test_general_settings.py`

**Steps:**
- [ ] 实现语言选择下拉 (zh-CN / en-US)
- [ ] 实现主题选择 (light)
- [ ] 实现默认模板选择
- [ ] 实现文件大小限制滑块
- [ ] i18n 所有文案
- [ ] 截图: General card zh_CN + en_US

**Commit:** `feat: add general settings card`

---

## Task 3: Provider Settings Card

**Purpose:** Provider 管理卡片：列表、当前激活、添加、测试连接。

**Files:**
- Create: `src/ui_qml/components/ProviderSettingsCard.qml`, `src/ui_qml/components/ProviderForm.qml`
- Test: `tests/qml/test_provider_settings.py`

**Steps:**
- [ ] 实现 5 个预设 + Custom 的列表渲染
- [ ] 实现 Qwen 推荐标记 (badge)
- [ ] 实现当前 Provider 选中态
- [ ] 实现添加 Custom Provider 表单
- [ ] 实现 Key 输入/保存/清空/测试连接
- [ ] 实现能力 Chip (文本 ✓ / 视觉 ✗)
- [ ] 实现连接测试按钮和结果反馈
- [ ] i18n 所有文案
- [ ] 截图: Provider 列表、Qwen 推荐、Custom 表单、无视觉 Chip、连接测试成功/失败

**Commit:** `feat: add provider settings card with management`

---

## Task 4: Quality, Budget, Privacy, Cache Cards

**Purpose:** 质量模式、预算、隐私开关、缓存管理卡片。

**Files:**
- Create: `src/ui_qml/components/QualityCard.qml`, `src/ui_qml/components/BudgetCard.qml`, `src/ui_qml/components/PrivacyCard.qml`, `src/ui_qml/components/CacheCard.qml`
- Test: `tests/qml/test_settings_cards.py`

**Steps:**
- [ ] 实现 QualityCard: 经济/均衡/高质量三选一
- [ ] 实现 BudgetCard: 月度上限、单批次上限、Watch 可选上限
- [ ] 实现 PrivacyCard: 文本/图片/扫描件/视频云端分析开关
- [ ] 实现 CacheCard: 空间上限、TTL、清理、当前使用量
- [ ] i18n
- [ ] 截图: 每种卡片 zh_CN + en_US

**Commit:** `feat: add quality, budget, privacy, and cache settings cards`

---

## Task 5: Usage & Diagnostics Cards

**Purpose:** 用量统计和诊断入口卡片。

**Files:**
- Create: `src/ui_qml/components/UsageCard.qml`, `src/ui_qml/components/DiagnosticsCard.qml`
- Test: `tests/qml/test_usage_diag.py`

**Steps:**
- [ ] 实现 UsageCard: 今日/本月用量, 按 Provider/模型/类型分组, 缓存节省标注
- [ ] 实现 DiagnosticsCard: 导出诊断包按钮, 内容预览
- [ ] i18n
- [ ] 截图

**Commit:** `feat: add usage and diagnostics settings cards`

---

## Task 6: Preferences Page Assembly

**Purpose:** 将所有设置卡片组装为单页滚动页面。

**Files:**
- Create: `src/ui_qml/pages/PreferencesPage.qml`
- Test: `tests/qml/test_preferences_page.py`

**Steps:**
- [ ] 组装全部卡片到 ScrollView
- [ ] 实现保存/取消按钮（底栏固定）
- [ ] 实现保存失败错误提示（fail-closed）
- [ ] 实现原子保存：任一 Key 操作失败 → 全部不保存
- [ ] 集成测试: 修改多项 → 保存 → 关闭重启 → 修改保留
- [ ] i18n
- [ ] 截图: 完整页面滚动前/后, zh_CN + en_US
- [ ] 截图: 保存失败错误状态

**Commit:** `feat: assemble preferences page`

---

## M6 Gate Report Checklist

- [ ] 全部 7 张设置卡片功能正常
- [ ] Provider 列表: 5 个预设 + Custom + Qwen 推荐
- [ ] 无 OpenAI/Anthropic 品牌预设
- [ ] Key 仅存 Credential Manager
- [ ] 原子保存 fail-closed
- [ ] 取消恢复原状态
- [ ] legacy baseline 214 + 本阶段全部新增测试通过

**自动化测试命令:**
```bash
pytest tests/unit/test_settings_controller.py -v
pytest tests/qml/test_general_settings.py tests/qml/test_provider_settings.py tests/qml/test_settings_cards.py tests/qml/test_usage_diag.py tests/qml/test_preferences_page.py -v
pytest tests/
python acceptance_test.py
```

**Product Owner 批准栏:**
- [ ] M6 审查通过
- [ ] 批准进入 M7 (可与 M5 并行)

> **未批准不得将 Preferences 标记为已完成。**
