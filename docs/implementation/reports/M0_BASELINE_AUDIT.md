# M0 Baseline Module Audit Report

> **日期**: 2026-07-27 | **基线**: Phase 1A checkpoint `391c309` + 实施计划 `c2fc862`
>
> 本报告记录当前仓库全部模块的复用/适配/隔离/淘汰决策，作为 M0 及后续实施的架构边界参考。

---

## 分类定义

| 分类 | 含义 |
|------|------|
| **复用** | 已验证正确，新架构直接使用，无需修改 |
| **适配** | 核心逻辑正确，需要接口调整或扩展后在新架构中使用 |
| **隔离** | 保留但不在新 UI 中暴露；旧入口可用，不进入首期预设 |
| **淘汰** | 新架构验收后移除；当前保留以保证旧入口可用 |

---

## 一、安全凭据层

| 文件 | 路径 | 关键符号 | 分类 | 说明 |
|------|------|----------|:---:|------|
| credential_manager.py | `src/utils/credential_manager.py:1-71` | `get_credential`, `set_credential`, `delete_credential`, `SERVICE_NAME`, `ACCOUNT_NAME` | **复用** | Phase 1A 已加固。使用 keyring/Windows Credential Manager。新 UI SettingsController 和 ProviderManager 直接调用。需注意 service name `AIRenamer` 为历史值，品牌迁移时保留兼容。 |
| 测试 | `tests/test_config_no_key.py:1-266` | 全部 | **复用** | 安全基线测试，不修改 |
| 测试 | `tests/test_credential_migration.py:1-105` | 全部 | **复用** | 迁移测试，不修改 |
| 测试 | `tests/test_log_no_leak.py:1-114` | 全部 | **复用** | 日志脱敏测试，不修改 |
| 测试 | `tests/test_settings_dialog_fail_closed.py:1-274` | 全部 | **复用** | fail-closed 测试，不修改 |

---

## 二、配置层

| 文件 | 路径 | 关键符号 | 分类 | 说明 |
|------|------|----------|:---:|------|
| config.py | `src/config.py:1-195` | `load_config`, `save_config`, `_atomic_write_json`, `CredentialSaveError`, `ConfigSaveError`, `CONFIG_DIR`, `CONFIG_FILE` | **适配** | Phase 1A 已加固（keyring 集成、fail-closed、原子写入）。M0 Task 6 添加 schema version。后续 M6 需改为补偿事务。硬编码路径 `D:/文件AI-AGENT/config` 为已知可移植性问题（GAP-028）。 |
| app_config.py | `src/models/app_config.py:1-25` | `AppConfig`, `api_key: Field(exclude=True)` | **适配** | api_key 已排除序列化。M6 需扩展 Provider/视觉/质量/预算/缓存字段。 |

---

## 三、AI Provider 层

| 文件 | 路径 | 关键符号 | 分类 | 说明 |
|------|------|----------|:---:|------|
| base.py | `src/providers/base.py:1-31` | `BaseProvider` | **适配** | 抽象基类。M3 需扩展为 `ProviderProtocol` 含能力检测。 |
| factory.py | `src/providers/factory.py:1-46` | `create_provider` | **适配** | M3 替换为 ProviderManager + presets。当前注册 DeepSeek/OpenAI/Claude。 |
| deepseek.py | `src/providers/deepseek.py:1-89` | `DeepSeekProvider` | **适配** | M3 重构为通用 OpenAICompatibleAdapter 的配置实例。Phase 1A 已移除 Key 日志。 |
| openai.py | `src/providers/openai.py:1-37` | `OpenAIProvider` | **隔离** | 首期不提供 OpenAI 品牌预设。代码保留，不在新 UI 预设列表暴露。 |
| claude.py | `src/providers/claude.py:1-34` | `ClaudeProvider` | **隔离** | 同上，首期不提供 Anthropic/Claude 品牌预设。 |

---

## 四、领域/核心层

| 文件 | 路径 | 关键符号 | 分类 | 说明 |
|------|------|----------|:---:|------|
| ai_engine.py | `src/core/ai_engine.py:1-150` | `AIEngine`, `suggest` | **适配** | M2/M3 重构为 TaskQueueController + Provider 调用链。当前无模板参与、无 response_format、无超时/重试。 |
| file_scanner.py | `src/core/file_scanner.py:1-45` | `scan_directory` | **复用** | 纯文件系统扫描，无副作用。新架构直接使用。 |
| content_extractor.py | `src/core/content_extractor.py:1-290` | `extract_content` | **适配** | 文本提取可复用。M3 需扩展图片预处理、扫描页渲染(PyMuPDF)、视频关键帧。 |
| rename_engine.py | `src/core/rename_engine.py:1-100` | `RenameEngine`, `execute` | **适配** | M2 拆分为 RenamePlan(纯数据) + RenameExecutor(I/O 边界) + PreflightService。当前逻辑作为执行器基础。 |
| rename_history.py | `src/core/rename_history.py:1-80` | `RenameHistory`, `record`, `undo_batch` | **适配** | M2 适配为 UndoRecord 持久化层。JSONL 追加写入模式保留。 |
| template_engine.py | `src/core/template_engine.py:1-90` | `TemplateEngine`, `render` | **适配** | M4 重构为统一 TemplateRenderer 含 TemplateRenderResult。当前正则替换逻辑保留。 |
| organization_engine.py | `src/core/organization_engine.py:1-58` | `organize_batch` | **适配** | 完整实现但无调用方。M2 后接入 Apply 管线。 |
| folder_watcher.py | `src/core/folder_watcher.py:1-105` | `FolderWatcher`, `add_watch`, `start`, `stop` | **适配** | M5 重构。GAP-035 尚未修复：`watch_folder_panel.py:_add_watch()` 仅调用 `watcher.add_watch(config)` 未调用 `watcher.start()`，该缺口留待 M5 按计划实现和测试。M0 未修改 watcher。M5 需增加防抖/过滤/回流防护/预算保护。 |

---

## 五、数据模型层

| 文件 | 路径 | 关键符号 | 分类 | 说明 |
|------|------|----------|:---:|------|
| file_item.py | `src/models/file_item.py:1-40` | `FileItem`, `FileStatus` | **适配** | M2 替换为 `FileTask` 状态机含八态+显示映射。 |
| rename_record.py | `src/models/rename_record.py:1-30` | `RenameRecord` | **适配** | M2 扩展为 `UndoRecord`。 |
| template.py | `src/models/template.py:1-45` | `NamingTemplate`, `BUILTIN_FIELDS` | **适配** | M4 替换为 Dublin Core 字段体系。 |
| watch_config.py | `src/models/watch_config.py:1-25` | `WatchConfig`, `WatchMode` | **适配** | M5 扩展为含 status/template/recursive 字段。 |

---

## 六、旧 UI 层 (QWidget)

| 文件 | 路径 | 分类 | 说明 |
|------|------|:---:|------|
| app.py | `src/app.py:1-50` | **淘汰** | 旧 QWidget 应用入口。M8 切换后淘汰。当前保留。 |
| main.py | `src/main.py:1-20` | **淘汰** | 旧启动入口。 |
| main_window.py | `src/ui/main_window.py:1-120` | **淘汰** | QMainWindow + QToolBar + QStatusBar。 |
| batch_rename_panel.py | `src/ui/batch_rename_panel.py:1-300` | **淘汰** | QTableView 批量面板。 |
| preview_table.py | `src/ui/preview_table.py:1-250` | **淘汰** | QAbstractTableModel 预览表。 |
| settings_dialog.py | `src/ui/settings_dialog.py:1-280` | **淘汰** | QDialog 设置(Phase 1A 已加固 fail-closed)。M6 替换为 QML Preferences。 |
| template_editor.py | `src/ui/template_editor.py:1-260` | **淘汰** | QDialog 模板编辑器。M4 替换为 QML。 |
| watch_folder_panel.py | `src/ui/watch_folder_panel.py:1-220` | **淘汰** | QWidget 监控面板。M5 替换为 QML。Phase 1A 已清理重复 except。 |

---

## 七、工具层

| 文件 | 路径 | 分类 | 说明 |
|------|------|:---:|------|
| constants.py | `src/utils/constants.py:1-90` | **复用** | 支持文件格式、MIME 映射、模板常量。新架构直接使用。 |
| file_utils.py | `src/utils/file_utils.py:1-50` | **复用** | 文件名 sanitize、路径安全。 |
| logger.py | `src/utils/logger.py:1-40` | **复用** | loguru 配置。Phase 1A 已确认无 Key 泄露。 |

---

## 八、测试层

| 目录/文件 | 分类 | 说明 |
|-----------|:---:|------|
| `tests/conftest.py` | **复用** | mock keyring + temp config dir fixtures |
| `tests/test_*.py` (8 文件) | **复用** | Phase 1A 安全测试，28 项 |
| `acceptance_test.py` | **复用** | 186 项验收测试 |

---

## 九、其他文件

| 文件 | 分类 | 说明 |
|------|:---:|------|
| `requirements.txt` | **适配** | M0 可能增加 pytest-qt；M3 增加 PyMuPDF/opencv-python |
| `run.bat`, `.bat`, `.vbs` | **淘汰** | M8 入口切换后更新为 QML entry |
| `.gitignore` | **复用** | 已含 `/.claude/` 和 `/docs/reference-evidence/` |

---

## 十、隔离边界总图

```
新 UI (QML/Qt Quick)          旧 UI (QWidget)
├── src/ui_qml/                     ├── src/ui/          ← 淘汰(M8)
│   ├── main.qml (M0)               │   ├── main_window.py
│   ├── Shell.qml (M1)              │   ├── batch_rename_panel.py
│   ├── pages/ (M1-M7)              │   ├── preview_table.py
│   └── components/ (M1-M7)         │   ├── settings_dialog.py
├── src/controllers/ (M1-M7)        │   ├── template_editor.py
│                                   │   └── watch_folder_panel.py
├── src/core/          ← 适配/复用
├── src/providers/     ← 适配(M3) + 隔离(OpenAI/Claude)
├── src/models/        ← 适配(M2/M4/M5)
├── src/utils/
│   ├── credential_manager.py ← 复用(Phase 1A)
│   └── i18n/          ← 新建(M0)
└── src/config.py      ← 适配(M0/M6)
```

---

> **审计完成。** 复用: 7 模块 | 适配: 17 模块 | 隔离: 2 模块 | 淘汰: 8 模块。不包含第三方蓝本名称、网址、版本或私有证据引用。不包含绝对用户路径。
