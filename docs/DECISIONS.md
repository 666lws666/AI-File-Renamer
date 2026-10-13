# DECISIONS.md — 架构决策记录

> **版本**: 1.0 | **日期**: 2026-07-26 | **状态**: 审计基线
>
> 每条决策记录: 背景 → 候选方案 → 决策 → 理由 → 后果。

---

## DEC-001: AI 供应商架构 — 可替换 Provider 适配层

**背景**: 产品要求「可配置的云端 AI」，并批准了五个首期供应商预设。

**候选方案**:
1. 仅支持 DeepSeek
2. 固定多供应商列表
3. 可替换 Provider 适配层 + 首期预设 + 自定义供应商入口

**决策**: 选择方案 3。首期提供 DeepSeek、Qwen、MiMo、智谱、Kimi 五家供应商预设。用户可通过自定义入口添加兼容供应商。首期不提供 OpenAI 或 Anthropic/Claude 品牌预设。

> **当前代码事实**: `factory.py` 中仍包含 OpenAI 和 Claude 适配器实现。这是遗留代码，不代表首期产品预设。是否删除或保留为隐藏兼容层待后续实施计划决定。

**理由**:
- 可替换架构降低供应商锁定风险
- 五个首期预设覆盖文本和视觉需求
- 自定义入口使用户可接入任何兼容供应商

**后果**:
- 所有 provider 必须实现 `BaseProvider` 接口
- 需新增 MiMo/智谱/Kimi Provider 实现
- 需新增自定义 Provider 配置 UI
- 文本模型默认 `deepseek-v4-flash`，视觉默认 `qwen3.6-flash`

---

## DEC-002: API Key 存储 — 当前明文的纠正路径

**背景**: 当前 `AppConfig.api_key` 明文存储在 `config/settings.json`。`.gitignore` 已排除此文件，但不解决本地安全。产品要求「API key 只能保存在系统凭据库或用户配置中」。

**候选方案**:
1. Windows Credential Manager (via `keyring` 库)
2. DPAPI 加密文件（via `cryptography` 库）
3. 环境变量
4. 保持明文 JSON（当前）

**决策**: 选择方案 1（Windows Credential Manager）+ 方案 2 作为非 Windows 回退。API Key 不再出现在 `settings.json` 中。

**理由**:
- Windows Credential Manager 是 Windows 桌面应用的标准凭据存储
- `keyring` 库跨平台，macOS Keychain / Linux Secret Service 自动适配
- DPAPI 加密作为回退（当 keyring 后端不可用时）
- 环境变量不适用于桌面应用

**后果**:
- 新增 `keyring` 依赖
- `load_config()` / `save_config()` 需要改造：`api_key` 字段不再序列化到 JSON
- 需实现凭据读写接口：`CredentialStore.get(key)` / `CredentialStore.set(key, value)`
- 迁移逻辑：首次升级时从旧 `settings.json` 读取 Key 并迁移到凭据库

---

## DEC-003: 文件操作安全模型 — 最小写入原则

**背景**: 产品要求明确的「读/写磁盘」边界。用户需要信任 Import/Extract/AI/Edit 阶段绝不修改文件。

**候选方案**:
1. 全权委托 — 管线完成直接 Apply（无审阅步骤）
2. 严格分阶段 — Import/Extract/AI/Review 不写盘，仅 Apply/Undo 写盘（当前方向）
3. 沙箱模式 — 所有操作先在临时副本上执行

**决策**: 选择方案 2。在代码层面通过以下方式强制执行：
- `FileScanner`、`ContentExtractor`、`AIEngine`、`TemplateEngine` 不包含任何文件写入调用
- `os.rename()` / `shutil.move()` 仅出现在 `RenameEngine` 和 `RenameHistory.undo_batch()`
- 代码审查 checklist 中强制检查新代码无意外文件写入

**理由**:
- 方案 3 磁盘和性能开销过大
- 方案 1 不可接受（用户失去控制权）
- 方案 2 在安全性和用户体验间取得平衡

**后果**:
- 所有新功能必须通过「是否写入磁盘」审查
- `RenameEngine` 和 `RenameHistory` 是磁盘写入的唯二入口
- 未来如有其他磁盘写入需求（如文件复制模式），需在架构层面讨论

---

## DEC-004: 状态管理 — 内存 + JSONL 混合

**背景**: FileItem 在工作流中经历多个状态转换。需要支持应用重启后恢复、跨会话 Undo。

**候选方案**:
1. SQLite 数据库
2. 纯内存（当前）
3. 内存 + JSONL 持久化（操作日志）

**决策**: 选择方案 3。当前 `RenameHistory` 使用 JSONL 记录已执行的操作（支持 Undo），但工作区（FileItem 列表）仅存内存。需扩展为工作区状态也持久化。

**理由**:
- SQLite 增加复杂度（schema 迁移、并发管理），对当前规模过度
- JSONL 追加写入极快，适合操作日志
- 工作区状态可用 JSON 快照（`config/workspace_snapshot.json`）在管线关键节点保存
- 纯内存导致重启丢失（GAP-012）

**后果**:
- 新增 `WorkspaceStore` 类，管线节点（EXTRACTED, SUGGESTED）自动保存快照
- 快照文件需加入 `.gitignore`
- 启动时检测未完成的工作区并恢复

---

## DEC-005: 模板引擎 — Pattern 字符串替换 vs AST

**背景**: 模板 pattern 如 `{date}_{title}_{tags}.{ext}` 需要渲染为实际文件名。

**候选方案**:
1. 正则替换（当前实现）
2. Jinja2 模板引擎
3. 自定义 AST 解析器

**决策**: 保持方案 1（正则替换）。当前 `TemplateEngine` 使用 `re.findall(r'\{(\w+)\}', pattern)` + `str.replace()`。

**理由**:
- 模板语法简单（仅 `{field}` 替换），不需要 Jinja2 的条件/循环/过滤器
- 正则替换可预测、无注入风险、无需额外依赖
- Jinja2 的灵活性在此场景是风险（用户可能注入 `{{ config.api_key }}`）

**后果**:
- 模板功能受限于简单变量替换
- 如需条件逻辑（如 `{date|%Y%m}`），需扩展 `TemplateEngine` 语法
- 模板编辑器的预览功能只做简单 mock 替换

---

## DEC-006: DeepSeek API 输出约束 — response_format vs tool_calling

**背景**: 产品要求「DeepSeek 调用必须使用严格 JSON 输出」。当前仅用 `temperature=0.3` 弱约束。

**候选方案**:
1. `response_format={"type": "json_object"}` (OpenAI 兼容参数)
2. Tool calling — 定义 `extract_metadata` function，强制 AI 调用
3. 后处理 regex + 重试（当前）
4. 两者组合：优先 tool calling，回退 response_format

**决策**: 选择方案 1（`response_format`），因为 DeepSeek API 支持此 OpenAI 兼容参数。如果后续发现 JSON 合规率不足（<95%），升级到方案 4。

**理由**:
- `response_format` 是 OpenAI SDK 原生支持的最简方案
- Tool calling 增加 prompt token 消耗
- 需先验证 DeepSeek 对 `response_format` 的支持程度

**后果**:
- `DeepSeekProvider.suggest_filename()` 需增加 `response_format` 参数
- `_parse_response()` 仍需保留 regex 回退（防御性编程）
- 启用 `response_format` 后，`_build_user_prompt()` 的 prompt 文本可简化

---

## DEC-007: GUI 框架 — PySide6 保持不变

**背景**: 当前使用 PySide6 (Qt 6)。需要评估是否需要迁移到其他框架。

**候选方案**:
1. PySide6（当前）
2. PyQt6（商业许可）
3. Electron / Tauri（Web 技术栈）
4. WPF / WinUI 3（仅 Windows）

**决策**: 保持 PySide6。

**理由**:
- PySide6 是 Qt 官方支持的 Python 绑定（LGPL 许可）
- 当前代码已基于 PySide6 完整实现
- 跨平台能力（Windows/macOS/Linux）
- 原生 Windows 控件和主题支持
- Web 框架增加复杂度（进程管理、本地文件访问）

**后果**:
- 继续使用 `QTableView` + `QAbstractTableModel` 模式
- Qt 样式表 (QSS) 实现 light/dark 主题切换
- 打包使用 PyInstaller + pyside6-deploy

---

## DEC-008: 文件监控 — watchdog 保持不变

**背景**: 当前使用 watchdog 库进行文件系统监控。

**决策**: 保持 watchdog。

**理由**:
- watchdog 跨平台，API 成熟
- 当前实现已验证去抖 (2s)、临时文件过滤
- 与 PySide6 的 `QObject` 信号系统兼容

**后果**:
- 需处理 watchdog Observer 的崩溃恢复（GAP-026）
- 去抖时间可配置化（当前硬编码 2s）

---

## DEC-009: 图片/视频/扫描件 — 多模态架构

**背景**: 产品批准了多模态架构。文本分析使用文本模型（`deepseek-v4-flash`），图片/扫描件/视频关键帧使用视觉模型（`qwen3.6-flash`）。

**决策**: 采用多模态架构。图片提取 EXIF 元数据 + 视觉内容理解；扫描件 PDF 本地渲染页面后发送视觉模型；视频本地抽取约 4–8 个代表性关键帧发送视觉模型。视觉 Provider 不可用时明确降级。

**理由**:
- 文本模型无法理解图像内容和视频帧
- 独立视觉 Provider 提供真正的多模态能力
- 诚实标注能力边界，不假装文本模型支持视觉

**后果**:
- 需实现 AI Router 根据文件类型路由模型
- 图片/扫描页/关键帧需本地缩放预处理
- 视频需本地关键帧抽取逻辑
- 视觉 Provider 不可用时需降级 UI

---

## DEC-010: 分期策略 — 按批准基线调整

**背景**: 审计发现差距需有序推进。分期内含已按 Product Owner 批准基线调整。

**决策**: 三期计划（概要，详见 `CURRENT_STATE_GAP_ANALYSIS.md`）：

### Phase 1 — 安全 + 核心可用 (P0 + 关键 P1) ✅ 已完成
1. GAP-001/002: API Key 安全存储 + 日志清理
2. GAP-027: 死代码清理
3. GAP-035: Watcher 首次添加自动启动
4. GAP-037/038: AI 超时 + 重试

### Phase 2 — 多模态架构 + Provider 扩展 (P0 + P1)
1. GAP-A01: AI Router
2. GAP-A02: 多模态视觉分析
3. GAP-S01: 网络边界
4. GAP-P02/P03: MiMo/智谱/Kimi 预设 + 自定义 Provider UI
5. GAP-A03/A04/A05: 视频关键帧 + 图片缩放 + 扫描页渲染
6. GAP-Q01–Q04: 质量模式、非货币用量/ResourceGuard、披露 UI、降级
7. GAP-C01: 内容哈希缓存
8. GAP-B02: 默认模型改为 deepseek-v4-flash

### Phase 3 — 工作流完整 + 打磨
- 模板参与管线、按选中项 Apply、管线 Cancel、工作区持久化、历史浏览、文件变化检测、Clear Workspace、状态筛选、组织引擎、Dublin Core 字段、i18n 等（详见 GAP 文档原有条目）

**后果**:
- 每期可独立验证
- Phase 2 完成后具备完整多模态能力

---

## DEC-011: 对话框 vs 内联面板 — 统一为面板

**背景**: 当前模板编辑器是模态对话框（`QDialog`），设置也是模态对话框。这打断了主工作流。

**决策**: 模板编辑器保持模态对话框（创作型任务），但增加「应用模板」按钮在主面板。设置保持模态对话框（配置型任务）。

**理由**:
- 模板编辑是低频创作任务，模态合理
- 模板选择和应用是高频操作，应在主面板
- 设置是低频配置，模态合理

**后果**:
- 批量重命名面板增加「模板选择」下拉
- 模板编辑器保存时 emit 信号通知面板刷新

---

## DEC-012: 视频处理 — 本地关键帧抽取

**背景**: 产品要求默认不上传完整视频，在本地抽取代表性关键帧。

**决策**: 视频处理流程：本地读取 → 分析时长与元数据 → 本地抽取约 4–8 个代表性关键帧（非机械首/中/末三帧）→ 本地缩放/压缩 → 发送关键帧与元数据给视觉 Provider。关键帧数量受用户配置上限、质量模式和 ResourceGuard 安全上限三重约束。

**后果**:
- 需实现本地视频帧抽取逻辑
- 需实现代表性帧选择策略（场景变化/时间分布等）
- 抽帧失败需降级 UI

---

## DEC-013: 隐私边界 — 本地预处理 + 透明披露

**背景**: 多模态架构下需向云端发送图像数据。不得使用"不发送二进制数据"等与架构矛盾的表述。

**决策**: 始终本地执行扫描/提取/缩放/渲染/抽帧/哈希/文件操作。向云端仅发送必要的提取文本、缩放图像、渲染页面或关键帧。每次调用前向用户披露发送内容。不得声称"不发送二进制数据"或"AI 仅发送提取文本"。

**后果**:
- 需实现发送内容披露 UI
- 隐私文档不得包含矛盾表述
- 缩放后的图像仍属二进制/编码视觉数据

---

## DEC-014: 缓存 — 本地内容哈希缓存

**背景**: 避免重复 AI 调用，但需在上下文变化时正确失效。

**决策**: 本地内容哈希缓存。缓存匹配上下文至少包含：文件内容哈希、文件类型、提取器版本、缩放设置、模板/Prompt/schema 版本、Provider/Model/质量模式/语言等。上下文变化时失效；记录命中/未命中/失效；用户可清理；用量区分缓存与真实调用。不依赖供应商语义缓存。

**后果**:
- 需实现多因素缓存键
- 需缓存管理 UI（查看/清理）
- 用量记录需区分缓存命中

---

## DEC-015: 质量模式 + 非货币 ResourceGuard（覆盖旧金额预算决策）

**背景**: 质量模式不是 temperature/max_tokens 调节。Product Owner 后续明确取消价格、费用估算、账单、币种和金额预算。

**决策**: 三种质量模式（经济/均衡/高质量）在当前 Provider 内控制模型、缩放和帧数。UsageRecorder 仅记录请求、Token 与缓存命中；ResourceGuard 对并发、队列、文件大小、页面/帧数和失败重试 fail-closed。产品不展示或计算货币金额。

**后果**:
- 保留质量模式路由与非货币用量记录
- 以 ResourceGuard 承担安全和可控性，不伪装为金额预算
- 删除未集成的 BudgetManager、CostEstimator 与 Provider 价格资源
- 设置中仅提供质量、资源限制、缓存和用量 UI

---

## 决策矩阵

| ID | 域 | 决策 | 可逆? |
|----|-----|------|:-----:|
| DEC-001 | AI 后端 | 可替换 Provider 适配层；首期 DeepSeek/Qwen/MiMo/智谱/Kimi；自定义入口 | ✅ |
| DEC-002 | 安全 | Windows Credential Manager + keyring | ❌ |
| DEC-003 | 安全 | 最小写入原则 (仅 RenameEngine/History) | ❌ |
| DEC-004 | 存储 | 内存 + JSONL + 工作区快照 JSON | ✅ |
| DEC-005 | 模板 | 正则替换（非 Jinja2） | ✅ |
| DEC-006 | AI | response_format JSON 约束 | ✅ |
| DEC-007 | GUI | PySide6 不变 | ❌ |
| DEC-008 | 监控 | watchdog 不变 | ✅ |
| DEC-009 | AI | 多模态架构：文本 deepseek-v4-flash + 视觉 qwen3.6-flash | ❌ |
| DEC-010 | 计划 | 三期递进（按批准基线调整） | ✅ |
| DEC-011 | UX | 模板编辑→模态，模板选择→面板 | ✅ |
| DEC-012 | 视频 | 本地抽取约 4–8 代表性关键帧；不上传完整视频 | ❌ |
| DEC-013 | 隐私 | 本地预处理 + 发送内容披露 UI；不声称"不发送二进制" | ❌ |
| DEC-014 | 缓存 | 本地内容哈希缓存（多上下文）；不依赖供应商语义缓存 | ✅ |
| DEC-015 | 质量 | 经济/均衡/高质量模式路由；预算 fail-closed | ❌ |

---

> **审计阶段完成。** 所有文档就绪，等待审批进入 Phase 1 实施。
