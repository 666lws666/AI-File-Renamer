# CURRENT_STATE_GAP_ANALYSIS.md — 当前实现 vs 序匣目标规格差距分析

> **版本**: 3.0 | **日期**: 2026-07-27 | **状态**: 产品基线
>
> 每个差距条目包含：证据、当前行为、目标行为（来自 `PRODUCT_SPEC.md`）、优先级、验收方式、状态。
>
> **历史快照说明（2026-08-12）**：本文保留 2026-07-27 的实施前差距结构，条目状态不代表 M8 当前完成度。当前实现与发布结论以 `docs/implementation/reports/M8_RELEASE_CANDIDATE_AUDIT.md` 为准；最新产品决策已取消价格、费用估算与金额预算。

---

## 优先级定义

| 级别 | 含义 |
|------|------|
| **P0** | 阻断启动 — 安全漏洞、数据丢失风险、核心功能不可用 |
| **P1** | 核心体验缺失 — 关键工作流不可用或严重不符合规格 |
| **P2** | 功能不完整 — 边缘场景未覆盖、UX 打磨不足 |

---

## 一、旧 GAP（GAP-001 至 GAP-038）

### GAP-001: API Key 明文存储于 JSON 配置文件

| 字段 | 内容 |
|------|------|
| **证据** | `src/models/app_config.py` — `api_key` 使用 `Field(default="", exclude=True)` 排除序列化；`src/config.py` — `save_config()` 不把 API Key 写入 JSON，凭据通过 `keyring`/Windows Credential Manager 保存，凭据保存或删除失败时 `CredentialSaveError` fail-closed，`load_config()` 支持旧明文 Key 自动迁移至凭据管理器；`src/utils/credential_manager.py` — `get_credential`/`set_credential`/`delete_credential` 封装 keyring；`tests/test_config_no_key.py` — 验证 JSON 不序列化 API Key、keyring 保存/读取、fail-closed 写入/删除；`tests/test_credential_migration.py` — 验证旧明文 Key 迁移及迁移失败时保留原 Key；`tests/test_settings_dialog_fail_closed.py` — 验证保存失败时对话框不关闭、全局配置不变；`tests/test_main_window_import.py` — AppConfig 序列化排除 API Key 的结构检查 |
| **当前行为** | API Key 运行时存在于 `AppConfig`，但序列化时排除；持久凭据保存在系统凭据管理器（Windows Credential Manager）；`settings.json` 不保存 `api_key`；旧明文 Key 在 `load_config()` 时自动迁移至凭据管理器并回写不含 Key 的 JSON；凭据或 JSON 保存失败时拒绝关闭设置对话框并明确报错；清空 Key 时删除旧凭据 |
| **目标行为** | API Key 仅存储于 Windows Credential Manager，不在 `settings.json` 中明文出现；日志不含 Key 片段；凭据保存失败时 fail-closed。当前已满足 |
| **优先级** | P0 — 阻断安全合规 |
| **验收方式** | 检查 `config/settings.json` 不含 `sk-` 前缀明文；API Key 通过 `keyring` 库存储于 Windows Credential Manager；日志不含 Key 片段；设置对话框中清空 Key 后保存，凭据管理器中原 Key 被删除；凭据管理器不可用时保存失败并提示用户 |
| **风险（修复前）** | 恶意软件、屏幕共享、备份泄露均可获取 API Key；违反安全约束 |
| **状态** | 已修复 |

### GAP-002: API Key 前缀/后缀写入日志

| 字段 | 内容 |
|------|------|
| **证据** | `src/providers/deepseek.py` — 已无 API Key 前缀/后缀日志（原 `api_key[:8]...api_key[-4:]` 已删除）；`src/ui/settings_dialog.py` — 已无 API Key 切片日志（原 `api_key[:8]...api_key[-4:]` 已删除）；`tests/test_log_no_leak.py` — AST 扫描所有 `logger` 调用，禁止 `api_key[...]` 切片进入日志参数；`test_deepseek_source_has_no_key_logging` 和 `test_settings_dialog_source_has_no_key_logging` 对源码做专项检查 |
| **当前行为** | 不记录 API Key 的完整值；不记录 API Key 的前缀、后缀或任何片段；自动化测试扫描所有源码日志调用，防止回归 |
| **目标行为** | 日志绝不得打印 Key 的任何部分。当前已满足 |
| **优先级** | P0 — 阻断安全合规 |
| **验收方式** | AST sentinel 扫描确认源码中无 `api_key` 切片进入日志调用；`test_connection` 后检查 `logs/*.log` 无 Key 信息 |
| **风险（修复前）** | 日志文件泄露 API Key 片段，降低暴力破解难度；违反约束 |
| **状态** | 已修复 |

### GAP-003: AI API 未强制严格 JSON 输出

| 字段 | 内容 |
|------|------|
| **证据** | `src/providers/deepseek.py:35-42` — 调用 `chat.completions.create()` 时无 `response_format: {"type": "json_object"}` 参数；仅使用 `temperature=0.3` 作为弱约束 |
| **当前行为** | API 可能返回 markdown 包裹的 JSON、纯文本、或其他非结构化输出；解析依赖 regex 容错 |
| **目标行为** | AI 调用必须使用严格 JSON 输出（`response_format` 或 tool/function calling）；AI 输出必须是可预测的结构化 JSON |
| **优先级** | P1 — 核心 AI 可靠性 |
| **验收方式** | 检查 API 调用参数包含 `response_format={"type": "json_object"}` 或等效约束；用 20+ 个不同类型文件测试，JSON 解析成功率 ≥ 95% |
| **风险** | JSON 解析失败时用原始文本作标题（`ai_engine.py:129`），产生不可用的文件名建议 |
| **状态** | 未实现 |

### GAP-004: 模板未参与批量重命名管线

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/batch_rename_panel.py:258` — `ai_engine.suggest(item)` 调用未传 `template` 参数；`src/core/ai_engine.py:32` — `suggest()` 的 `template` 参数有默认值 `None`，此时走 `_build_default_name()` 固定格式 |
| **当前行为** | 用户在模板编辑器中创建的模板不会影响实际 AI 建议文件名；所有文件使用硬编码 `{date}_{title}.{ext}` |
| **目标行为** | 当前选中的模板必须参与：1) AI 字段提取（告知 AI 需要哪些字段）；2) 文件名渲染（按 pattern 拼接）；3) 模板编辑结果应立即反映到工作区已有建议的预览 |
| **优先级** | P1 — 核心功能不可用 |
| **验收方式** | 创建自定义模板 `{type}_{title}_{date}.{ext}`，执行管线后建议文件名符合该 pattern；切换模板后已有 SUGGESTED 项的预览立即更新 |
| **状态** | 未实现 |

### GAP-005: 模板编辑不即时生效

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/template_editor.py:212-236` — `_save_current()` 保存到文件但未通知 `BatchRenamePanel` 更新；`BatchRenamePanel` 未监听模板变更事件 |
| **当前行为** | 模板保存后，工作区中的 `SUGGESTED` 项的 `suggested_name` 不会更新；需重新执行管线才生效 |
| **目标行为** | 模板编辑结果必须立刻生效 — 保存模板后，所有 `SUGGESTED` 项的预览文件名应立即用新模板重新渲染 |
| **优先级** | P1 — 违反不可妥协行为 #6 |
| **验收方式** | 执行管线获得建议 → 打开模板编辑器修改 pattern → 保存 → 工作区预览自动更新为新格式 |
| **状态** | 未实现 |

### GAP-006: Watch Folder Review First 模式不产生审阅队列

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/watch_folder_panel.py:164-174` — `_on_file_ready()` 仅在 `WatchMode.AUTO_APPLY` 时调用 `_auto_process()`；`REVIEW_FIRST` 模式无任何处理 |
| **当前行为** | Review First 模式下，新文件被检测到后仅记录日志，不加入任何审阅队列；用户看不到待审阅文件 |
| **目标行为** | Review First 模式必须产出可审阅队列：新文件自动 Extract → AI Suggest → 进入 UI 可见的待审阅列表，用户可逐项审核（编辑/Ignore/Approve） |
| **优先级** | P0 — Review First 模式完全不可用 |
| **验收方式** | 配置 Review First 监控 → 放入文件 → 待审阅列表出现新项（状态 待确认）→ 用户可 Approve 触发磁盘写入 |
| **状态** | 未实现 |

### GAP-007: Auto Apply 不复用预检/冲突处理/历史记录/Undo

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/watch_folder_panel.py:195-197` — `_auto_process()` 创建 `RenameEngine()` 未传入 `history` 参数 → 使用默认 `RenameHistory()`，与批量重命名的 history 隔离；`src/core/rename_engine.py:17` — `RenameEngine.__init__` 的 `history` 参数可选 |
| **当前行为** | Auto Apply 的 rename 操作记录到独立的（默认路径的）history 实例；用户看不到这些操作的历史，无法 Undo；不执行 `_resolve_conflicts` 预检 |
| **目标行为** | Auto Apply 必须复用同一套：预检（sanitize、冲突检测、文件存在性）、历史记录（共享 history 实例）、Undo 机制 |
| **优先级** | P0 — 数据安全风险 + 违反不可妥协行为 #7 |
| **验收方式** | Auto Apply 重命名后 → 主窗口 Undo 可恢复；历史记录视图包含 Auto Apply 批次 |
| **状态** | 未实现 |

### GAP-008: 不可按选中项 Apply（仅全部 SUGGESTED）

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/batch_rename_panel.py:191` — `_on_apply_rename()` 调用 `self.table.get_suggested_items()` 返回 ALL SUGGESTED 项，忽略表格选择；`src/ui/preview_table.py:204` — `get_suggested_items()` 无选择过滤 |
| **当前行为** | 无论用户选中哪些行，Apply 总是对所有 SUGGESTED 项执行 |
| **目标行为** | 支持「按选中项 Apply」和「Apply 全部已审核项」两种模式；单项快捷 Apply 和选中批量 Apply 共用同一执行引擎 |
| **优先级** | P1 — 违反不可妥协行为 #5 |
| **验收方式** | 3 个文件 SUGGESTED → 选中其中 2 个 → Apply → 仅 2 个被重命名 |
| **状态** | 未实现 |

### GAP-009: 无单项/批量 Retry、Ignore、搜索、筛选

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/preview_table.py` — 表格支持多选但无右键菜单；`src/ui/batch_rename_panel.py` — 无搜索框、无筛选下拉、无 Retry/Ignore 按钮 |
| **当前行为** | 用户只能：全量扫描、全量 Apply、全量 Undo。失败项无法单独 Retry；不需要的文件无法 Ignore；无法搜索文件名 |
| **目标行为** | 每项可单独 Ignore、Retry；支持多选批量操作；支持文件名搜索和状态筛选（全部/待处理/分析中/待确认/已应用/失败/已取消/已忽略/已撤销） |
| **优先级** | P0 — 违反不可妥协行为 #5（多个子功能缺失） |
| **验收方式** | 搜索 "报告" → 仅显示含 "报告" 的项；筛选 "失败" → 仅显示失败项；右键菜单包含 Ignore/Retry/Edit 选项 |
| **状态** | 未实现 |

### GAP-010: 无 Cancel 操作

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/batch_rename_panel.py:224-262` — `PipelineWorker(QThread)` 无取消机制；`QThread.terminate()` 仅在被强制终止时调用，且不安全 |
| **当前行为** | 管线执行中用户无法取消；只能等待完成或强制关闭应用 |
| **目标行为** | 管线执行中提供「取消」按钮；取消后已处理项保留结果，未处理项回退到 PENDING |
| **优先级** | P1 — 用户体验 + 可靠性 |
| **验收方式** | 添加 100 个文件 → 启动管线 → 途中点取消 → 已提取/已建议项保留，剩余项为 PENDING |
| **状态** | 未实现 |

### GAP-011: 管线不支持暂停/恢复

| 字段 | 内容 |
|------|------|
| **证据** | `PipelineWorker` 无暂停标志 |
| **当前行为** | 管线一旦启动就不可中断 |
| **目标行为** | 支持管线暂停/恢复；暂停时保存当前进度，恢复后从断点继续 |
| **优先级** | P2 — 增强功能 |
| **验收方式** | 启动管线 → 暂停 → 检查进度保留 → 恢复 → 从断点继续执行 |
| **状态** | 未实现 |

### GAP-012: 工作区状态无持久化（重启丢失）

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/batch_rename_panel.py` — `FileItem` 列表仅存在于 `FileItemTableModel._items`（内存）；应用关闭时不保存 |
| **当前行为** | 应用重启后，导入的文件、AI 建议、编辑的 final_name 全部丢失 |
| **目标行为** | 应用重启后恢复工作区（至少恢复文件列表和 SUGGESTED 建议名）；未 APPLY 的项保留 |
| **优先级** | P1 — 可靠性 |
| **验收方式** | 导入 5 个文件 → 执行管线 → 关闭应用 → 重新打开 → 5 个文件仍在工作区，建议名保留 |
| **状态** | 未实现 |

### GAP-013: Undo 历史无 UI 浏览（仅支持「撤销上次」）

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/batch_rename_panel.py:53` — 仅有 `btn_undo` 按钮调用 `undo_last()`；`src/core/rename_history.py` — 数据层支持查询所有批次，但 UI 未暴露 |
| **当前行为** | 用户只能看到「撤销上次」按钮；无法查看历史操作列表、无法选择撤销特定批次 |
| **目标行为** | 提供历史操作视图：显示每次 Apply 的批次（时间、文件数、是否已撤销），支持选择性 Undo |
| **优先级** | P1 — 违反不可妥协行为 #5（Undo 范围不可控） |
| **验收方式** | 执行 3 次 Apply → 打开历史视图 → 看到 3 个批次 → 选择第 2 个撤销 → 仅撤销该批次 |
| **状态** | 未实现 |

### GAP-014: 文件在管线中变化无检测

| 字段 | 内容 |
|------|------|
| **证据** | `src/core/rename_engine.py:60-96` — `execute()` 在执行 `os.rename()` 前不比较 `file_mtime` 或 `file_size`；`src/models/file_item.py:28` — `file_mtime` 已存储但未用于变更检测 |
| **当前行为** | 如果文件在 Import 后被外部修改或删除，Apply 时可能：静默失败（文件不存在）、覆盖外部修改（文件已变更） |
| **目标行为** | Apply 前比较当前 `stat()` 与 `FileItem.file_mtime` / `file_size`；变化则标记 FAILED 并警告用户 |
| **优先级** | P1 — 数据完整性 |
| **验收方式** | Import 文件 → 外部修改文件 → Apply → 检测到变化 → 标记 FAILED + 显示 "文件已被外部修改" |
| **状态** | 未实现 |

### GAP-015: 文件被占用时无检测

| 字段 | 内容 |
|------|------|
| **证据** | `src/core/rename_engine.py:76` — `os.rename()` 无前置文件占用检测；仅依赖 try/except 捕获 `PermissionError` |
| **当前行为** | 文件被其他程序打开时，`os.rename()` 可能失败（Windows 文件锁定）；错误被捕获但用户收到的是通用 "重命名失败" 消息 |
| **目标行为** | Apply 前尝试检测文件占用状态（打开句柄检查）；被占用文件标记为 FAILED 并提示用户关闭占用程序 |
| **优先级** | P2 — 错误体验增强 |
| **验收方式** | 用 Word 打开 .docx 文件 → Apply → 检测到占用 → 跳过 + 清晰提示 "文件被占用，请关闭后重试" |
| **状态** | 未实现 |

### GAP-016: 目标目录不存在时无自动创建

| 字段 | 内容 |
|------|------|
| **证据** | `src/core/rename_engine.py:66` — `parent.mkdir(parents=True, exist_ok=True)` 已实现 |
| **当前行为** | 目标目录自动创建 |
| **目标行为** | 目标目录自动创建（当前已满足） |
| **优先级** | 无差距 |
| **验收方式** | Apply 到不存在的目录 → 目录自动创建 → 文件正确移入 |
| **状态** | 已实现 |

### GAP-017: 部分成功时无逐项 Retry

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/batch_rename_panel.py:206-218` — Apply 完成后仅显示 "成功 X 个，失败 Y 个"，不提供失败项列表或 Retry 入口 |
| **当前行为** | Apply 失败的文件保持 FAILED 状态，但 UI 无「重试失败项」按钮 |
| **目标行为** | Apply 后列出失败项及原因；提供「重试失败项」按钮；支持逐项 Retry |
| **优先级** | P1 — 不可妥协行为 #8 |
| **验收方式** | Apply 时 3 个成功 2 个失败 → 显示 "3 成功, 2 失败" → 点击「重试失败项」→ 仅处理 2 个 FAILED 文件 |
| **状态** | 未实现 |

### GAP-018: 无「Clear Workspace」功能且需保证行为正确

| 字段 | 内容 |
|------|------|
| **证据** | 当前代码库无 Clear Workspace 按钮或逻辑 |
| **当前行为** | 用户无法清空工作区（只能逐个移除或重新扫描覆盖） |
| **目标行为** | 提供 Clear Workspace 按钮；清空工作区时：1) 不撤销已 APPLY 的改名；2) 提示用户确认；3) 仅移除未 APPLY 的项；4) Undo 历史不丢失 |
| **优先级** | P1 — 违反不可妥协行为 #3 |
| **验收方式** | 5 个文件（3 个 APPLIED, 2 个 SUGGESTED）→ Clear Workspace → 3 个 APPLIED 的文件不受影响，工作区清空，Undo 历史仍可访问 |
| **状态** | 未实现 |

### GAP-019: 无可视化状态筛选

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/preview_table.py` — 表格仅显示原始数据，无筛选栏；`src/ui/batch_rename_panel.py` — 无筛选控件 |
| **当前行为** | 所有状态的文件混在一起显示；用户无法只查看 FAILED 或 SUGGESTED 项 |
| **目标行为** | 状态列可筛选（下拉：全部 / 待处理 / 分析中 / 待确认 / 已应用 / 失败 / 已取消 / 已忽略 / 已撤销） |
| **优先级** | P1 — 基本可用性 |
| **验收方式** | 筛选 "失败" → 仅显示失败项；筛选 "待确认" → 仅显示待审核项；筛选 "已撤销" → 仅显示已撤销项 |
| **状态** | 未实现 |

### GAP-020: 无导出改名对照表

| 字段 | 内容 |
|------|------|
| **证据** | 代码库无导出功能 |
| **当前行为** | 无法导出改名前后对照 |
| **目标行为** | 支持导出为 CSV/Excel：原文件名、新文件名、状态、文件大小、日期 |
| **优先级** | P2 — 增强功能 |
| **验收方式** | 执行重命名 → 导出 CSV → 文件包含 5 列正确数据；导出不含 API Key |
| **状态** | 未实现 |

### GAP-021: 模板无专属 AI 提示词

| 字段 | 内容 |
|------|------|
| **证据** | `src/models/template.py:28-40` — `NamingTemplate` 无 `system_prompt_override` 字段；`src/core/ai_engine.py:49` — `system_prompt = self.config.system_prompt or DEFAULT_SYSTEM_PROMPT`，始终使用全局提示词 |
| **当前行为** | 所有模板共用同一个全局 system prompt |
| **目标行为** | 每个模板可配置独立的 AI 提示词；模板专属提示词覆盖全局设置，使不同命名场景可获得针对性的 AI 分析 |
| **优先级** | P1 — 模板功能完整性 |
| **验收方式** | 创建「合同模板」配置 "重点关注合同编号、签约方、签署日期" → 管线用此模板时 AI 返回字段包含合同编号 |
| **状态** | 未实现 |

### GAP-022: 模板未与 AI 字段需求联动

| 字段 | 内容 |
|------|------|
| **证据** | `src/core/ai_engine.py:82-98` — `_build_user_prompt()` 不根据模板的 `fields` 动态调整 AI 请求的字段列表；始终请求 title, date, type, tags, language |
| **当前行为** | AI 总是收到相同的输出格式要求，无论模板需要什么字段 |
| **目标行为** | 根据模板 `fields` 动态构建 AI 输出格式要求（模板需要 `project` 字段时，AI prompt 应要求输出 `project`） |
| **优先级** | P1 — 模板-AI 联动 |
| **验收方式** | 创建模板包含 `{creator}_{project}_{title}.{ext}` → AI prompt 要求输出 creator, project, title → AI 返回包含这些字段 |
| **状态** | 未实现 |

### GAP-023: 图片/视频无视觉理解 & 无降级提示

| 字段 | 内容 |
|------|------|
| **证据** | `src/core/content_extractor.py:219-259` — 图片仅提取 EXIF 元数据；`src/core/content_extractor.py:264-276` — 视频仅提取文件属性；`src/ui/preview_table.py` — 无视觉内容能力提示 |
| **当前行为** | 图片和视频文件在管线中处理，但 AI 收到的信息非常有限（仅文件名 + 元数据）；UI 不告知用户此限制 |
| **目标行为** | 根据已批准多模态架构（`PRODUCT_SPEC.md` §6.3）：图片使用 `qwen3.6-flash` 视觉模型分析内容；视频抽取约 4–8 个代表性关键帧发送视觉模型。视觉 Provider 不可用时显示明确降级状态，仅使用文件名/元数据/OCR |
| **优先级** | P1 — 违反不可妥协行为 #10 |
| **验收方式** | 添加 .jpg 文件 → 执行管线 → 发送至视觉模型分析 → 建议文件名基于图像内容理解（非仅元数据） |
| **状态** | 未实现 |

### GAP-024: 组织引擎未接入主工作流

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/batch_rename_panel.py:189-213` — `_on_apply_rename()` 调用 `rename_engine.execute()` 但未调用 `organize_batch()`；`src/core/organization_engine.py` — 完整实现但无调用方 |
| **当前行为** | 设置中可配置 `auto_organize` 和归类规则，但 Apply 后文件不会自动归类移动 |
| **目标行为** | 当 `auto_organize=True` 时，Apply 后将文件按规则移动到目标目录 |
| **优先级** | P1 — 功能未接通 |
| **验收方式** | 设置 `auto_organize=True`, rule=`by_type`, target_root=`D:/organized` → Apply → 文件移至 `D:/organized/report/xxx.pdf` |
| **状态** | 未实现 |

### GAP-025: 组织引擎配置完全未持久化

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/settings_dialog.py:237-248` — `_on_save()` 无 `organization_rule` 赋值；`_load_settings()` 无 `organization_rule` 加载；UI 下拉框存在但从不读默认值也从不写入配置 |
| **当前行为** | `organization_rule` 下拉框是纯展示组件 — 无论用户选什么，配置永远不会保存，重启后恢复默认值；同时 combo 文本含括号（`by_type (按文件类型)`），即使保存也与 `RULE_HANDLERS` key 不匹配 |
| **目标行为** | `organization_rule` 正确使用 `currentData()` 而非 `currentText()` 存储；`_on_save()` 和 `_load_settings()` 中包含该字段 |
| **优先级** | P1 — 功能断裂（UI 存在但数据流未接通） |
| **验收方式** | 在设置中选择 "by_type" → 保存 → 检查 settings.json 中 `organization_rule: "by_type"` → 重启 → 设置中仍显示 "by_type" |
| **状态** | 未实现 |

### GAP-026: Watch Folder 崩溃后需手动重启

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/watch_folder_panel.py:97-98` — `observer.join(timeout=5)` 非守护线程；watcher 崩溃后不自动恢复 |
| **当前行为** | watchdog observer 如果崩溃，监控静默停止，用户无感知 |
| **目标行为** | watcher 崩溃后自动重启（指数退避）并通知用户 |
| **优先级** | P2 — 可靠性增强 |
| **验收方式** | 模拟 watcher 崩溃 → 自动重启 → 用户收到通知 → 监控恢复 |
| **状态** | 未实现 |

### GAP-027: Dead Code — 重复异常处理

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/watch_folder_panel.py` — 原重复且不可达的 `except Exception as e:` 分支（引用未定义变量 `file_path`）已删除；当前 `_auto_process` 中仅保留一个 Exception handler，使用 `item.original_name` 正确记录错误；`tests/test_main_window_import.py` — `test_watch_folder_panel_no_unreachable_except` 使用 AST 检查 `_auto_process` 内每个 try 块的 Exception handler 数量，禁止重复/不可达分支；模块导入测试通过 |
| **当前行为** | 不可达重复 handler 已不存在；`watch_folder_panel` 可正常导入；AST 结构化检查防止重复不可达异常分支回归 |
| **目标行为** | 移除死代码。当前已满足 |
| **优先级** | P1 — 代码质量 |
| **验收方式** | AST 扫描确认 `_auto_process` 中每个 try 块最多一个 Exception handler；`test_watch_folder_panel_no_unreachable_except` 通过 |
| **风险（修复前）** | 不可达代码块编译通过但从不执行，引用未定义变量 |
| **状态** | 已修复 |

### GAP-028: 硬编码路径导致不可移植

| 字段 | 内容 |
|------|------|
| **证据** | `src/config.py:14` — `CONFIG_DIR = Path("D:/文件AI-AGENT/config")`；`src/main.py:11` — `_CRASH_LOG = Path(r"D:\文件AI-AGENT\logs\_startup.log")`；`src/core/rename_history.py:20` — 默认路径 `D:/文件AI-AGENT/rename_history/history.jsonl`；`src/utils/logger.py:28` — `log_dir = Path("D:/文件AI-AGENT/logs")` |
| **当前行为** | 应用仅在 `D:\文件AI-AGENT` 路径下正常工作 |
| **目标行为** | 所有路径相对于应用安装目录或用户数据目录，不使用硬编码绝对路径 |
| **优先级** | P2 — 可移植性 |
| **验收方式** | 将应用目录重命名或移动到其他路径 → 应用仍正常工作；配置/日志/历史文件创建在新路径下 |
| **状态** | 未实现 |

### GAP-029: 无首次启动引导

| 字段 | 内容 |
|------|------|
| **证据** | `src/app.py:27` — `load_config()` 返回默认 `AppConfig()` 时无引导流程；`src/ui/batch_rename_panel.py:126-140` — 仅在点击分析时检查 API Key |
| **当前行为** | 首次启动无 API Key 时，用户看到空白界面，无引导 |
| **目标行为** | 首次启动检测无 API Key → 自动打开设置向导/引导页，帮助用户配置 Provider 和 API Key |
| **优先级** | P2 — 首次用户体验 |
| **验收方式** | 删除 settings.json → 启动应用 → 自动显示引导页 → 完成配置后可正常使用 |
| **状态** | 未实现 |

### GAP-030: 无 Dark Mode

| 字段 | 内容 |
|------|------|
| **证据** | `src/models/app_config.py:23` — `theme: str = "light"` 已预留配置项；但所有 UI 组件未响应 theme 设置 |
| **当前行为** | 始终使用浅色主题 |
| **目标行为** | 支持 light/dark 主题切换 |
| **优先级** | P2 — UI 增强 |
| **验收方式** | 设置中选择 "dark" → 全部 UI 切换为深色主题 → 重启后保持 |
| **状态** | 未实现 |

### GAP-031: 模板字段体系需扩展

| 字段 | 内容 |
|------|------|
| **证据** | `src/models/template.py:16-22` — `BUILTIN_FIELDS` 仅有 date, title, type, tags, language |
| **当前行为** | 字段体系为中文简化版 |
| **目标行为** | 扩展字段体系：支持 dcDate, dcTitle, dcSubject, dcType, dcCreator, extProject, extOrganization 等 Dublin Core 风格字段；同时兼容现有中文字段，提升与主流文件管理工具的互操作性 |
| **优先级** | P2 — 增强功能 |
| **验收方式** | 模板编辑器中可选 dcDate, dcCreator 等扩展字段 → AI 可提取对应值 |
| **状态** | 未实现 |

### GAP-032: 无模板导入/导出

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/template_editor.py` — 无导入/导出按钮 |
| **当前行为** | 模板仅本地存储 |
| **目标行为** | 支持导入/导出模板为 JSON，便于分享 |
| **优先级** | P2 — 增强功能 |
| **验收方式** | 导出一个模板 → 得到合法 JSON 文件 → 在另一个实例中导入 → 模板正确加载并可用 |
| **状态** | 未实现 |

### GAP-033: 无多语言国际化框架

| 字段 | 内容 |
|------|------|
| **证据** | 所有 UI 字符串硬编码中文 |
| **当前行为** | 仅支持中文界面 |
| **目标行为** | 支持中文/英文切换（配置中已有 language 字段） |
| **优先级** | P2 — 国际化 |
| **验收方式** | 切换 language="en" → 界面切换为英文 → 重启后保持 |
| **状态** | 未实现 |

### GAP-034: acceptance_test.py 覆盖不足

| 字段 | 内容 |
|------|------|
| **证据** | `acceptance_test.py` — 16 个测试部分覆盖基本模块导入和单元功能，但未覆盖：真实文件冲突、部分失败场景、Undo 后历史一致性、模板实时更新、并发场景 |
| **当前行为** | 测试主要验证 happy path |
| **目标行为** | 验收测试覆盖所有 GAP 对应的恢复路径 |
| **优先级** | P1 — 质量保障 |
| **验收方式** | 测试套件包含：冲突文件名测试、部分失败测试、Undo 完整性测试、Cancel 测试、模板联调测试 |
| **状态** | 未实现 |

### GAP-035: 通过 UI 添加首个监控后 Watcher 不启动

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/watch_folder_panel.py:128-139` — `_add_watch()` 调用 `self.watcher.add_watch(config)` 后不调用 `self.watcher.start()`；`src/core/folder_watcher.py:43-57` — `FolderWatcher.add_watch()` 仅在 `self._running == True` 时启动 observer；`_load_saved_configs()` 在循环结束后调用了 `start()`，但 `_add_watch()` 未调用 |
| **当前行为** | 用户首次通过 UI 添加监控文件夹后，watcher 静默不启动（仅记录到内部数据结构）；只有重启应用或从未调用过 `start()` 时才生效 |
| **目标行为** | `_add_watch()` 中，如果 watcher 未运行则自动调用 `start()` |
| **优先级** | P0 — 用户反馈缺失（静默失败无提示） |
| **验收方式** | 不重启应用 → 通过 UI 添加监控 → 放入文件 → 活动日志出现 "发现新文件" |
| **状态** | 未实现 |

### GAP-036: `_pending_files` 字段声明但从未使用

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/watch_folder_panel.py:34` — `self._pending_files: list[str] = []` 声明后全文仅此一处，从未被读写 |
| **当前行为** | Review First 模式下无任何数据结构存储待审阅文件 |
| **目标行为** | `_pending_files` 作为 Review First 的待审阅队列，存储 `FileItem` 列表并在 UI 中展示 |
| **优先级** | P1 — 数据结构就绪但未使用（Review First 的基础设施） |
| **验收方式** | Review First 模式放置文件 → `_pending_files` 列表增长 → UI 中显示待审阅项 |
| **状态** | 未实现 |

### GAP-037: AI 调用无超时配置

| 字段 | 内容 |
|------|------|
| **证据** | `src/providers/deepseek.py:35-42` — `client.chat.completions.create()` 无 `timeout` 参数；`src/providers/openai.py:24-32` — 同样无 `timeout`；`src/providers/claude.py:24-29` — 同样无 `timeout`；`AppConfig` 无 `api_timeout` 配置项 |
| **当前行为** | 依赖 OpenAI SDK 默认超时（~60 秒）；用户无法配置；网络问题时 UI 冻结等待超时 |
| **目标行为** | `AppConfig` 增加 `api_timeout` 配置项（默认 30s）；所有 provider 调用传入 `timeout`；超时后自动重试 |
| **优先级** | P1 — 可靠性（管线失控等待） |
| **验收方式** | 设置 `api_timeout=5` → 模拟慢速 API → 5 秒后超时 → 自动重试 |
| **状态** | 未实现 |

### GAP-038: AI 调用无重试机制

| 字段 | 内容 |
|------|------|
| **证据** | `src/providers/deepseek.py:78-83` — `RateLimitError` 仅捕获报告，不重试；`src/core/ai_engine.py:77-80` — `suggest()` 的 except 直接设 FAILED，不重试；全文无 `max_retries`、指数退避、`tenacity` 库使用 |
| **当前行为** | 任何 API 错误（429 速率限制、网络抖动、5xx 服务端错误）直接标记为 FAILED，无重试 |
| **目标行为** | 瞬时错误（429, 5xx, 超时）自动重试 3 次，指数退避（1s, 2s, 4s）；认证错误（401）不重试 |
| **优先级** | P1 — 可靠性 |
| **验收方式** | 模拟 429 错误 → 自动重试 3 次 → 第 3 次成功 → SUGGESTED；模拟 401 错误 → 不重试 → 直接 FAILED |
| **状态** | 已修复 |

---

## 二、新增品牌与 UI 差距

### GAP-B01: 当前运行时仍使用旧品牌

| 字段 | 内容 |
|------|------|
| **证据** | `src/app.py`、`src/main.py` — 窗口标题；`src/utils/credential_manager.py` — `SERVICE_NAME: str = "AIRenamer"` |
| **当前行为** | 应用窗口标题为 "AI File Renamer"；Windows Credential Manager 使用 "AIRenamer" service name |
| **目标行为** | 运行时品牌迁移为「序匣/Xuxia」 |
| **优先级** | P2 — 品牌迁移需兼容旧凭据，不得破坏已有迁移 |
| **验收方式** | 窗口标题显示「序匣」；旧 `AIRenamer` 凭据自动迁移至新 service name；设置中仍能读取之前保存的 Key |
| **状态** | 未实现 |

### GAP-B02: 当前遗留默认模型不是已批准文本默认

| 字段 | 内容 |
|------|------|
| **证据** | `src/providers/deepseek.py:24` — 默认 `model="deepseek-v4-pro"`；`src/models/app_config.py:8` — `model: str = "deepseek-v4-pro"`；`src/ui/settings_dialog.py` — 模型下拉列表中 `deepseek-v4-pro` 为第一选项 |
| **当前行为** | 应用代码中文本默认模型硬编码为 `deepseek-v4-pro`，设置界面也以此为首选 |
| **目标行为** | 序匣文本默认模型为 `deepseek-v4-flash`（`PRODUCT_SPEC.md` §1.5 已批准） |
| **优先级** | P1 — 与批准基线不一致 |
| **验收方式** | 全新安装启动 → 打开设置 → 默认模型显示 `deepseek-v4-flash` → 文本分析实际使用 `deepseek-v4-flash` |
| **状态** | 未实现 |

---

## 三、新增 AI Provider 差距

### GAP-P01: 遗留代码包含非首期品牌 Provider

| 字段 | 内容 |
|------|------|
| **证据** | `src/providers/openai.py` — 完整 OpenAI Provider 实现；`src/providers/claude.py` — 完整 Anthropic/Claude Provider 实现；`src/providers/factory.py` — OpenAI、Claude 在 factory 注册为可选 Provider；`src/ui/settings_dialog.py` — 设置下拉包含 OpenAI、Claude 选项 |
| **当前行为** | 用户可在设置中选择 OpenAI、Claude 作为 AI 供应商 |
| **目标行为** | 首期不提供 OpenAI、Anthropic/Claude 品牌预设。是否删除或保留为隐藏兼容层待后续实施计划决定（`PRODUCT_SPEC.md` §1.3 已批准） |
| **优先级** | P2 — 与批准基线不一致但非阻断（代码未声称这些是首期目标） |
| **验收方式** | 打开设置 → Provider 下拉列表中不含 OpenAI、Anthropic、Claude 品牌选项 |
| **状态** | 未实现 |

### GAP-P02: MiMo、智谱、Kimi 预设尚未实现

| 字段 | 内容 |
|------|------|
| **证据** | `src/providers/factory.py` — 当前仅注册 DeepSeek、OpenAI、Claude 三种 Provider；无 MiMo/智谱/Kimi 相关代码 |
| **当前行为** | 无 MiMo、智谱、Kimi Provider 实现，用户无法选择这些供应商 |
| **目标行为** | 提供 MiMo、智谱、Kimi 首期预设，实现 `BaseProvider` 接口（`PRODUCT_SPEC.md` §1.3 已批准） |
| **优先级** | P1 — 首期目标功能缺失 |
| **验收方式** | 设置下拉中出现 MiMo、智谱、Kimi 选项 → 选择后填入正确的默认 Base URL → 测试连接成功 |
| **状态** | 未实现 |

### GAP-P03: 自定义 Provider 配置界面未完成

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/settings_dialog.py` — 设置界面仅有固定 Provider 下拉框，无可编辑 Base URL 文本框外的自定义提供商添加入口；无名称/超时/重试/兼容参数的自定义表单 |
| **当前行为** | 用户只能从预置列表选择 Provider，无法添加自己的兼容供应商 |
| **目标行为** | 支持用户添加自定义 Provider：显示名称、Base URL、Model、API Key、超时、重试策略、是否兼容 OpenAI 接口参数（`PRODUCT_SPEC.md` §1.4 已批准） |
| **优先级** | P1 — Provider 可替换架构的关键入口 |
| **验收方式** | 设置中点击「添加自定义供应商」→ 填写名称/URL/Model/Key → 测试连接 → 保存后在 Provider 列表中可选 |
| **状态** | 未实现 |

---

## 四、新增 AI 架构差距

### GAP-A01: AI Router 尚未实现

| 字段 | 内容 |
|------|------|
| **证据** | `src/providers/factory.py` — `create_provider()` 仅根据 `config.provider` 字符串创建单一 Provider 实例；`src/core/ai_engine.py` — `suggest()` 直接使用传入的单一 provider，无文件类型判断或模型路由逻辑 |
| **当前行为** | 所有文件使用同一个 Provider 和模型处理，无文本/视觉分离 |
| **目标行为** | 实现 AI Router：根据文件类型（文本/图片/扫描件/视频）和质量模式自动路由到对应模型。文本 → `deepseek-v4-flash`；图片/扫描件/视频关键帧 → `qwen3.6-flash`（`PRODUCT_SPEC.md` §6.3–§6.4 已批准） |
| **优先级** | P0 — 多模态架构基础 |
| **验收方式** | 导入混合文件（PDF + JPG + MP4）→ 管线执行 → 文本文件调用 DeepSeek → 图片和视频调用 Qwen |
| **状态** | 未实现 |

### GAP-A02: 多模态视觉分析尚未实现

| 字段 | 内容 |
|------|------|
| **证据** | `src/core/content_extractor.py:219-259` — `_extract_image()` 仅使用 Pillow 读取 EXIF 标签，无图像内容发送至视觉 API 的逻辑；无 Qwen Provider 实现 |
| **当前行为** | 图片文件仅提取 EXIF 元数据（拍摄日期、相机型号等），不分析图像内容 |
| **目标行为** | 图片内容通过 `qwen3.6-flash` 视觉模型分析；提取图像描述、场景、文字等语义信息用于命名建议（`PRODUCT_SPEC.md` §6.3 已批准） |
| **优先级** | P0 — 核心架构缺失 |
| **验收方式** | 添加 .jpg 风景照 → 管线执行 → AI 建议文件名包含图像内容描述（非仅日期/相机型号） |
| **状态** | 未实现 |

### GAP-A03: 视频代表性关键帧抽取尚未实现

| 字段 | 内容 |
|------|------|
| **证据** | `src/core/content_extractor.py:264-276` — `_extract_video()` 仅使用 `ffprobe`/`moviepy` 等读取文件属性和元数据，无帧抽取代码 |
| **当前行为** | 视频文件仅提取时长、分辨率、编码等元数据 |
| **目标行为** | 本地抽取约 4–8 个代表性关键帧 → 本地缩放/压缩 → 发送至 `qwen3.6-flash` 视觉分析。关键帧选择基于场景变化/时间分布，不机械固定为首/中/末三帧。数量受用户配置上限、质量模式和预算上限三重约束。默认不发送完整视频（`PRODUCT_SPEC.md` §6.7 已批准） |
| **优先级** | P1 — 视频处理核心功能 |
| **验收方式** | 添加 .mp4 视频 → 管线执行 → 网络请求仅含关键帧图像数据，不含完整视频 → 文件名建议含视频内容描述 |
| **状态** | 未实现 |

### GAP-A04: 图片/扫描页本地缩放限制尚未实现

| 字段 | 内容 |
|------|------|
| **证据** | `src/core/content_extractor.py` — 图片提取无缩放/压缩步骤；无最长边、总像素或文件大小上限的配置项或检查逻辑 |
| **当前行为** | 图片按原始分辨率读取和处理（当前仅 EXIF），无尺寸控制 |
| **目标行为** | 图片发送视觉 API 前本地缩放。可配置：最长边尺寸上限、总像素量上限、编码后字节大小上限、格式/压缩质量、单文件最多发送图像数量（`PRODUCT_SPEC.md` §6.6 已批准） |
| **优先级** | P1 — 隐私与成本控制 |
| **验收方式** | 设置缩放限制 → 导入大尺寸图片 → 检查网络请求中图像数据 ≤ 用户配置值 |
| **状态** | 未实现 |

### GAP-A05: 扫描页渲染及限制尚未实现或不完整

| 字段 | 内容 |
|------|------|
| **证据** | `src/core/content_extractor.py` — PDF 提取仅使用 `PyPDF2` 等库读取文本层；无页面渲染为图像的逻辑；无最大页数/尺寸检查 |
| **当前行为** | 扫描版 PDF（无文本层）提取结果为空或仅有元数据 |
| **目标行为** | 扫描版 PDF 在本地渲染必要页面为图像 → 本地缩放 → 发送至视觉模型。受最大页数、最长边、总像素和预算限制。不默认上传完整 PDF 二进制（`PRODUCT_SPEC.md` §6.6 已批准） |
| **优先级** | P1 — 扫描件处理缺失 |
| **验收方式** | 导入扫描版 PDF → 仅渲染的页面图像被发送 → 文件名建议基于扫描内容 |
| **状态** | 未实现 |

---

## 五、新增质量模式与预算差距

### GAP-Q01: 三种质量模式路由尚未实现

| 字段 | 内容 |
|------|------|
| **证据** | `src/models/app_config.py` — `AppConfig` 无 `quality_mode` 字段；`src/core/ai_engine.py` — 无质量模式判断逻辑；所有 API 调用使用相同配置 |
| **当前行为** | 无质量模式概念；所有分析使用固定模型和参数 |
| **目标行为** | 经济/均衡/高质量三种模式，独立路由文本和视觉模型。均衡为推荐默认。模式控制模型选择、图片尺寸、关键帧数量和升级策略（`PRODUCT_SPEC.md` §6.4 已批准） |
| **优先级** | P1 — 核心差异化功能 |
| **验收方式** | 设置中切换三种模式 → 经济模式使用更低成本模型和更严格限制 → 高质量模式使用 qwen3.7-plus → 检查实际 API 调用参数 |
| **状态** | 未实现 |

### GAP-Q02: 非货币用量与资源护栏尚未实现（历史快照）

| 字段 | 内容 |
|------|------|
| **证据** | 2026-07-27 基线尚无统一 UsageRecorder 或 ResourceGuard；该证据已由后续 M3/M5 实现替代 |
| **当前行为** | 历史基线无法统计请求/Token/缓存命中，也没有统一并发、队列、文件大小、页数、帧数和重试上限 |
| **目标行为** | 记录请求次数、输入/输出 Token 与缓存命中；以 ResourceGuard 对本地资源和队列 fail-closed；不展示价格、币种、账单或金额预算 |
| **优先级** | P1 — 云端 AI 透明度与资源安全 |
| **验收方式** | 查看非货币 UsageCard；触发并发、队列、文件、页数、帧数和重试上限；确认阻止新工作并可安全恢复 |
| **状态** | 未实现（仅指 2026-07-27 历史基线；M8 当前状态见发布审计） |

### GAP-Q03: 云端发送内容披露 UI 尚未实现

| 字段 | 内容 |
|------|------|
| **证据** | `src/ui/batch_rename_panel.py` — 管线执行前无披露对话框；无发送内容摘要显示 |
| **当前行为** | 用户点击「扫描并 AI 分析」后直接执行，不知道将发送什么数据到哪个供应商 |
| **目标行为** | 调用前披露目标供应商和模型、发送的数据类型、当前质量模式、是否可能升级模型与适用的本地资源上限；不展示价格或金额预算 |
| **优先级** | P1 — 透明度合规 |
| **验收方式** | 执行管线 → 弹出披露摘要 → 用户确认后才发送 API 请求 → 信息与实际请求一致 |
| **状态** | 未实现 |

### GAP-Q04: 视觉 Provider 不可用时降级状态未实现

| 字段 | 内容 |
|------|------|
| **证据** | 无视觉 Provider 健康检查或降级逻辑；无 Qwen Provider 实现 |
| **当前行为** | 无视觉分析能力，因此也无降级场景（当前仅文本） |
| **目标行为** | 视觉 Provider 不可用时显示明确降级状态；说明仅使用了文件名、元数据或 OCR 信息；不伪装成完整视觉分析。降级后的文件在 UI 中标注「视觉分析不可用」（`PRODUCT_SPEC.md` §10.4 已批准） |
| **优先级** | P1 — 用户体验诚信 |
| **验收方式** | 断开 Qwen API 连接 → 导入图片 → 管线执行 → 文件标记降级状态 → 建议名基于文件名/EXIF → UI 提示 "视觉分析当前不可用" |
| **状态** | 未实现 |

---

## 六、新增缓存差距

### GAP-C01: 本地多上下文内容哈希缓存尚未实现

| 字段 | 内容 |
|------|------|
| **证据** | 全文无缓存相关代码；无缓存索引文件；无 `CacheManager` 类；每次管线执行都会重新调用 AI API |
| **当前行为** | 同一文件每次扫描都重新调用 AI，无缓存复用 |
| **目标行为** | 本地内容哈希缓存。缓存键包含：文件内容哈希、文件类型、提取器版本、OCR/扫描页渲染设置、图片缩放/压缩设置、视频关键帧选择设置、模板 ID/版本、Prompt 版本、结构化输出 schema 版本、Provider、Model、质量模式、输出语言。上下文变化时缓存失效；记录命中/未命中/失效原因；用户可清理缓存；用量记录区分真实调用与缓存命中（`PRODUCT_SPEC.md` §6.8 已批准） |
| **优先级** | P1 — 成本控制与性能 |
| **验收方式** | 分析文件 → 记录 API 调用次数 → 再次分析同一文件 → 无新 API 调用 → 用量记录显示 "缓存命中" → 修改模板后 → 缓存失效 → 重新调用 API |
| **状态** | 未实现 |

---

## 七、新增隐私与安全差距

### GAP-S01: 多模态网络数据边界尚未实现与测试

| 字段 | 内容 |
|------|------|
| **证据** | 当前无网络请求内容过滤/验证；无发送数据尺寸检查；无视频文件上传防护；无隐私披露检查 |
| **当前行为** | 应用当前仅发送文本内容至 API（纯文本架构），尚无图片/视频/扫描件发送路径，因此多模态数据边界未建立 |
| **目标行为** | 默认不发送完整视频；图片发送前缩放至用户配置上限；关键帧不超过用户配置数量和像素限制；扫描页不超过最大页数。所有发送受配置、质量模式和预算三重约束。隐私文档和 UI 不得包含「不发送二进制数据」等与多模态架构矛盾的表述（`PRODUCT_SPEC.md` §6.6–§6.7、§10 已批准） |
| **优先级** | P0 — 隐私合规（多模态架构的前置安全条件） |
| **验收方式** | 配置图片最长边 1024px → 导入 4000px 图片 → 检查实际发送数据 ≤ 1024px → 视频请求不含完整视频文件 → 扫描 PDF 请求不含完整 PDF |
| **状态** | 未实现 |

---

## 优先级统计

| 优先级 | 数量 | GAP ID |
|--------|------|--------|
| **P0** | 9 | GAP-001, GAP-002, GAP-006, GAP-007, GAP-009, GAP-035, GAP-A01, GAP-A02, GAP-S01 |
| **P1** | 32 | GAP-003, GAP-004, GAP-005, GAP-008, GAP-010, GAP-012, GAP-013, GAP-014, GAP-017, GAP-018, GAP-019, GAP-021, GAP-022, GAP-023, GAP-024, GAP-025, GAP-027, GAP-034, GAP-036, GAP-037, GAP-038, GAP-B02, GAP-P02, GAP-P03, GAP-A03, GAP-A04, GAP-A05, GAP-Q01, GAP-Q02, GAP-Q03, GAP-Q04, GAP-C01 |
| **P2** | 12 | GAP-011, GAP-015, GAP-020, GAP-026, GAP-028, GAP-029, GAP-030, GAP-031, GAP-032, GAP-033, GAP-B01, GAP-P01 |
| **无差距** | 1 | GAP-016 |
| **合计** | **54** | 54 个唯一 ID |

> 9 (P0) + 32 (P1) + 12 (P2) + 1 (GAP-016) = 54。

## 状态统计

| 状态 | 数量 | GAP ID |
|------|------|--------|
| **已修复** | 3 | GAP-001, GAP-002, GAP-027 |
| **已实现** | 1 | GAP-016 |
| **未实现** | 50 | 除 GAP-001、GAP-002、GAP-016、GAP-027 外的其余 50 个 GAP |
| **合计** | **54** | 54 个唯一 ID |

---

> **目标规格**: 见 `PRODUCT_SPEC.md`。验收用例: 见 `ACCEPTANCE_MATRIX.md`。
