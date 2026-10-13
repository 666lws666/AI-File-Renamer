# 序匣（Xuxia）详细产品、交互与技术设计规格

> **版本**: 1.0 | **日期**: 2026-07-27 | **状态**: 产品设计基线
>
> 本文是序匣新版 UI、交互和服务编排的详细设计依据。后续实施计划、开发、自动化测试和截图验收必须以本文为准。

---

## 1. 文档目的与权威性

本文定义序匣的完整产品、交互和技术设计。与较旧产品文档冲突时，本文中明确标记的最新批准决策优先。

**当前阶段仍未授权功能实现。** 本文不生成实施计划，不包含可执行代码。

---

## 2. 产品目标与非目标

### 目标

- 单机 Windows 个人工具
- AI 文件智能命名和归档
- 高可控、可审阅、可撤销
- 云端 AI（用户自行配置 Provider 和 Key）
- 保留未来团队版和公开产品扩展边界

### 首期非目标

登录、团队协作、云同步、许可证、支付、遥测、后台自动更新、组织后台、商业计费系统。

---

## 3. 被最新设计替代的旧决策

以下决策已被本文件中的最新批准设计替代：

| 旧决策 | 状态 | 新决策 |
|--------|:---:|--------|
| 强制 DeepSeek 文本 + Qwen 视觉双 Provider 默认 | **已废止** | 单一当前 Provider，用户自主选择 |
| DeepSeek 作为"高级文本路由" | **已废止** | 五个 Provider 平级，无"高级"分级 |
| 质量模式跨 Provider 自动切换 | **已废止** | 质量模式在当前 Provider 内工作 |
| 文本自动发 DeepSeek、图片自动发 Qwen | **已废止** | 不隐式跨供应商调用 |

---

## 4. 架构与模块边界

### UI 层

- **PySide6 + QML/Qt Quick** — 声明式 UI
- **自定义窗口 Shell** — 约 32px 标题栏，无系统原生标题栏
- **左侧图标导航** — 约 48px 无文字图标栏
- **Page Router** — Batch / Watch Folders / Templates / Preferences / System Status
- Batch、Watch、Templates 为顶部入口；System Status、Preferences 为底部入口
- UI 不直接调用 AI 或文件系统
- 旧菜单栏、QToolBar、QStatusBar、QTableView 不作为新版基础

### 控制器层

- `BatchWorkspaceController` — 批量任务生命周期
- `TaskQueueController` — 任务队列和执行编排
- `WatchFolderController` — 监控配置和事件处理
- `TemplateController` — 模板 CRUD 和渲染
- `SettingsController` — 配置读写和验证
- 后台任务通过 Qt signals 和明确事件更新 UI

### 领域层

- `FileTask` 状态机
- `NamingFields` / `Template` / `RenamePlan` / `BatchResult`
- `UndoRecord` / `AIConfidence` / `Usage` / `Cost`
- `ControlledVocabulary`

### 服务层

- 配置持久化（JSON）
- Windows Credential Manager（keyring）
- 文件扫描、内容提取、OCR、图片预处理、视频关键帧
- AI Provider 适配层、AI Router / Capability Router
- 文件 Rename / Move / Undo
- 本地多上下文内容哈希缓存
- 用量记录、可取消后台执行器

**关键约束：**
- 单项 Apply 和批量 Apply 共用同一引擎
- 批量是多个 RenamePlan 的逐项执行，每项独立成功或失败
- 新 UI 通过验收后才切换入口；旧实现隔离保留

---

## 5. 统一数据流

```
UI intent
  → Controller
    → File scanning
    → Local extraction / preprocessing
    → Active Provider capability check
    → AI structured output (JSON)
    → Template rendering
    → Review workspace (no disk write)
    → RenamePlan
    → Preflight validation
    → Per-item execution (Apply)
    → History / Undo record
    → UI result
```

**磁盘写入边界：**

| 操作 | 写磁盘 |
|------|:---:|
| Import / Scan | ❌ |
| Extract / Preprocess | ❌ |
| AI Suggest | ❌ |
| Manual Edit | ❌ |
| Apply | ✅ |
| Undo | ✅ |
| Auto Apply（明确开启） | ✅ |
| Clear Workspace | ❌ |

Clear Workspace 不等于 Undo。Undo 历史不因 Clear Workspace 丢失。

---

## 6. 视觉系统与窗口 Shell

| 属性 | 值 |
|------|-----|
| 设计基准窗口 | 1000 × 700 px |
| 最小窗口 | 900 × 640 px |
| 标题栏 | 自定义约 32px |
| 左侧导航 | 约 48px 无文字图标栏 |
| 选中项 | 浅灰圆角底 |
| 背景 | 白色 / 极浅灰 |
| 主按钮 | 黑色 |
| 边框 | 细灰 |
| 卡片 | 圆角、大留白 |
| 图标 | 本地 SVG |
| 字体 | 系统字体 + 可靠回退 |

- 首期浅色主题必须完成
- 深色主题保留结构和国际化能力
- 关键动作在窄窗口不能被隐藏
- 不使用传统菜单栏、工具栏和状态栏

---

## 7. Batch 空态

**顶部操作区：**
- 模板选择下拉
- 添加文件 / 添加文件夹按钮
- 可选目标目录
- 搜索框、状态筛选下拉
- 当前 Provider / 连接状态指示
- 非货币用量与 ResourceGuard 状态入口

**中央拖放区：**
- 支持拖放文件和文件夹
- 显示支持格式列表
- 导入后 Toast 反馈
- 递归导入子文件夹
- 跳过临时文件和不支持格式
- 导入后立即进入任务队列
- **不修改真实文件**

---

## 8. Batch 非空工作区

**布局：全宽滚动任务卡片队列。**

不使用传统固定列 QTableView。不增加固定预览侧栏。

**单张任务卡片（约 68–72px 高）：**

| 元素 | 说明 |
|------|------|
| 复选框 | 支持多选 |
| 状态图标 | 待处理 / 分析中 / 待确认 / 已撤销 / 已应用 / 失败 / 已取消 / 已忽略 |
| 缩略图 | 图片/视频/PDF 预览（如有） |
| 粗体建议名 | AI 生成或用户编辑后的最终文件名 |
| 灰色原文件名 | 原始文件路径或名称 |

**交互：**
- Hover / 选中时显示行操作按钮
- 三态主复选框（全选 / 部分选中 / 全不选）
- 选中 N 项时顶部显示"已选中 N 项"
- 搜索和筛选不改变任务状态，仅控制可见性
- 单项快捷 Apply、批量 Apply
- 内联编辑、Retry、Ignore、Cancel
- Undo、Clear Workspace
- Apply 期间独立进度反馈
- 部分成功逐项报告，每项独立结果

**状态与显示映射：**

| 内部状态 | 显示 |
|----------|------|
| `PENDING` | 待处理 |
| `EXTRACTING` / `ANALYZING` | 分析中 |
| `SUGGESTED` / `REVIEW_PENDING` | 待确认 |
| `UNDONE` | 已撤销 |
| `APPLIED` | 已应用 |
| `FAILED` | 失败 |
| `CANCELLED` | 已取消 |
| `IGNORED` | 已忽略 |

"全部"是筛选选项，不是任务状态。

---

## 9. 文件名内联编辑与验证

- 一次编辑一行
- Enter 或勾号保存；Esc 或叉号取消
- 不修改磁盘
- 保护扩展名（默认不编辑扩展名部分）
- Windows 非法字符检测（`< > : " / \ | ? *`）
- 保留设备名检查（CON、PRN、AUX、NUL、COM1–COM9、LPT1–LPT9）
- 路径长度检查
- 空名称拒绝
- 冲突提示（与同目录已有文件重名）
- 校验错误就地显示在卡片内

---

## 10. Apply、批量执行与 Undo

**Apply = 明确授权。** 不增加无意义二次弹窗（首次使用可显示一次性说明）。

**预检清单（每项 Apply 前）：**
- 源文件存在且未变化（mtime/size 与扫描时一致）
- 目标目录存在或可创建
- 目标路径无冲突（有冲突则自动追加计数器）
- 文件名合法
- 权限可写

**批量执行：**
- 单项快捷 Apply 和选中批量 Apply 共用同一执行引擎
- 批量非原子：每项独立 `os.rename`，独立成功/失败
- 每项结果独立记录

**Undo：**
- LIFO 批次撤销
- 每项独立执行反向 rename
- Undo 失败不伪造成功
- 已撤销项可以重新 Apply，但必须重新预检
- Clear Workspace 保留 Undo 历史；已应用文件的 Undo 记录不受影响

---

## 11. Watch Folders

### 空态

- 添加第一个监控配置的引导卡片

### 监控配置

| 字段 | 说明 |
|------|------|
| 源目录 | 必填 |
| 可选目标目录 | Apply 目标 |
| 模板 | 每个监控可选独立模板 |
| 递归 | 是否包含子文件夹 |
| 模式 | Review First / Auto Apply |

### 监控状态

每个监控卡显示：Active / Paused / Error / ResourcePaused。

单列监控卡，非表格。

### 运行时行为

- 防抖（2s 文件稳定等待）
- 临时文件过滤（`.tmp`、`~$` 前缀等）
- 目标目录回流防护（不监控自身输出目录）
- 独立结果窗口

### Review First

- 新文件 → Extract → AI Suggest → 进入待审阅队列
- 用户在队列中逐项审核

### Auto Apply

- 复用同一 RenamePlan / Undo 引擎
- ResourceGuard：达到并发、队列、文件大小或失败退避限制时暂停并通知

### 配置变更

- 编辑配置前需暂停监控
- 清理未应用任务时显示影响摘要
- 已应用文件和 Undo 历史保留
- 删除配置不删除文件、不 Undo 已应用操作

---

## 12. Templates

### 字段体系

| 字段 | 说明 |
|------|------|
| `dcDate` | 文档日期 |
| `dcTitle` | 文档标题 |
| `dcSubject` | 主题分类 |
| `dcType` | 文档类型 |
| `dcCreator` | 创建者/作者 |
| `dcIdentifier` | 标识符 |
| `extOrganization` | 所属组织 |
| `extProject` | 所属项目 |
| `extStatus` | 文档状态 |
| `extVersion` | 版本号 |

### 默认模板

```
{dcDate}_{dcTitle}
```

### 日期格式

`YYYYMMDD` / `YYYYMM` / `YYYY-MM-DD` / `YYYY-MM`

### 分隔符

Underscore (`_`) / Hyphen (`-`)

### 组织模式

- `flat` — 单层
- `subject_tree` — 按主题分目录
- `type_tree` — 按类型分目录
- `project_tree` — 按项目分目录

### 输出语言

中文 / 英文 / 日文 / 西班牙文

### 交互

- 字段开关和拖动排序
- 实时文件名和路径预览（UI 预览与正式渲染使用同一引擎）
- 模板修改对既有任务影响：
  - 字段齐全 → 仅重渲染预览
  - 字段不足 → 标记需要重新生成
- 删除被引用模板前选择替代模板
- 已应用文件和 Undo 不受模板修改影响

---

## 13. 受控词表

### 分类

`subject` / `organization` / `project` / `status` / `type`

### 来源

系统预设 / 用户创建 / AI 建议 / AI 自动创建

### 预设修订

- 预设词条允许用户编辑和删除
- 使用用户覆盖/隐藏机制保留恢复出厂值能力
- 可恢复单个词条或整类预设

### AI 词条

- AI 可以产生新词条
- 默认先进入候选区
- 用户操作：添加、修改后添加、仅本次使用、映射现有词条、忽略
- 用户可主动开启高置信度自动创建
- 自动创建需要满足：置信度阈值、去重、分类明确、数量限制
- 完全自由自动创建作为非推荐高级开关
- AI 创建记录：来源、模型、时间、文件任务、置信度

### 运行规则

- Review First 中候选由用户处理
- Auto Apply 默认不静默扩充正式词表（开启自动创建后才允许）
- 词条 Undo 与文件 Undo 分离
- 词表变化进入缓存上下文

### 预设内容包

通用个人场景：`personal` / `finance` / `legal` / `health` / `learning` / `research` / `travel` / `home`

常见文档类型：`invoice` / `receipt` / `statement` / `contract` / `proposal` / `report` / `presentation` / `meeting-note` / `minutes`

> 预设词表需要独立内容设计和母语复核。本文不声称已穷尽所有词条。

---

## 14. Preferences

单页滚动卡片布局。

| 卡片 | 内容 |
|------|------|
| 通用 | 语言、主题、默认模板、文件大小限制 |
| 云端 AI | 当前 Provider、模型、Base URL、连接测试、Key 管理 |
| 质量模式 | 经济/均衡/高质量 |
| 资源限制 | 并发、待处理队列、文件大小、页数、帧数和重试上限 |
| 隐私 | 文本/图片/扫描件/视频 云端分析开关 |
| 缓存 | 缓存大小、TTL、清理 |
| 用量 | 今日/本月用量、按 Provider/模型/类型分组 |
| 支持与诊断 | 诊断包导出、日志查看 |

- 原子保存
- SettingsDialog 保存失败 fail-closed
- 保存前不修改全局配置
- 取消恢复原状态

---

## 15. Provider 最终设计

### 当前 Provider

- 用户可以保存多个 Provider Profile
- 同一时间只有一个"当前 Provider"
- 序匣只把任务发送给当前 Provider
- 不隐式跨供应商调用
- 用户切换后新任务使用新 Provider；已发出的调用不迁移

### 平级供应商

**五个首期预设，全部平级，无"高级"分级：**

- **DeepSeek** — 文本分析
- **Qwen（通义千问）** — 推荐：文本与视觉一体（标记 `推荐`）
- **MiMo**
- **智谱（GLM）**
- **Kimi（月之暗面）**

**推荐不代表强制。** 其他 Provider 仍可直接选择。不做未经验证的价格或质量保证。

### 能力不足

当前模型缺少视觉能力时：
- 文档文本仍可正常处理
- 图片、扫描件、视频明确降级
- UI 显示能力 Chip（文本 ✓ / 视觉 ✗）
- 用户可更换模型或 Provider
- 不自动调用第二个 Provider

### Provider Profile 结构

| 字段 | 说明 |
|------|------|
| 名称 | 显示名称 |
| Adapter/协议 | OpenAI 兼容 / 其他 |
| Base URL | API 端点 |
| API Key | 系统凭据管理器存储 |
| 模型 | 用户选择或填写 |
| 文本能力 | 是/否 |
| 视觉能力 | 是/否 |
| JSON 能力 | 是否支持 `response_format` |
| 超时 | 默认 30s |
| 重试 | 次数和策略 |
| 最近连接测试 | 时间戳和结果 |
| 启用状态 | 启用/禁用 |

### 凭据安全

- Provider 独立凭据
- 系统 Credential Manager 存储
- 不写 JSON
- 不记录日志
- 不导出
- 旧 `AIRenamer` 凭据兼容迁移

---

## 16. 质量模式

三种模式：**经济** / **均衡（推荐默认）** / **高质量**。

**核心规则：**

- 模式在当前 Provider 内工作
- 不通过质量模式偷偷切换供应商
- 不存在 DeepSeek"高级路由"
- 不存在固定的跨 Provider 文本/视觉拆分
- 不同模式控制当前 Provider 的模型选择、图片限制、关键帧和升级策略
- 当前 Provider 只有一个模型时，模式可以调整预处理与资源限制，但必须诚实显示实际模型相同
- temperature / max_tokens 不是模式本体

**Qwen 推荐 Profile：**
- 均衡：`qwen3.6-flash`
- 高质量重试：`qwen3.7-plus`

其他 Provider 的具体模型由用户选择，并在实现前核验官方能力。

---

## 17. 图片、扫描件与视频

### 图片

- 本地缩放和压缩（发送前）
- 可配置：最长边上限、总像素上限、编码字节上限、格式/压缩质量
- 不编造未批准的具体像素默认值（正式默认值在实现阶段依据官方限制和测试确定）

### 扫描件 PDF

- 本地渲染需要分析的页面为图像
- 受最大页数、最长边、总像素和 ResourceGuard 安全上限限制
- 可选本地 OCR
- 不默认上传完整 PDF 二进制

### 视频

- 本地读取 → 分析时长和元数据
- 本地抽取约 4–8 个代表性关键帧（非机械首/中/末三帧）
- 本地缩放/压缩
- 发送关键帧与元数据/摘要给视觉 Provider
- **默认不上传完整视频**
- 帧数受质量模式、用户配置和 ResourceGuard 安全上限约束

### 能力不足

Provider 无视觉能力时明确降级，使用文件名/元数据/OCR。

---

## 18. 非货币用量与资源护栏

### 用量可见性

- 记录请求次数、输入 Token、输出 Token 和缓存命中
- 支持按 Provider / 模型以及文本 / 图片 / 扫描件 / 视频关键帧分组
- 明确区分“尚无记录”“统计不可用”和真实零值
- 不展示价格、币种、费用估算、账单或金额预算

### ResourceGuard

- 限制并发调用、待处理队列、单文件大小、扫描页数和视频帧数
- 限制失败重试次数，并支持取消、退避、冷却和安全恢复
- 达到资源上限时 fail-closed，显示可操作原因；不得伪装成金额预算
- Watch 的 Review First 与 Auto Apply 共享可累加的资源计数，不互相覆盖

### 缓存与隐私

- 用量记录区分真实 API 调用与本地缓存命中
- 不保存 API Key、文件正文、完整路径、价格或货币数据到用量记录

---

## 19. 本地多上下文内容哈希缓存

### 缓存键上下文

| 维度 | 内容 |
|------|------|
| 内容 | 文件内容哈希 |
| 类型 | 文件类型 |
| 提取 | 提取器版本 |
| OCR | OCR / 渲染设置 |
| 图片 | 缩放 / 压缩设置 |
| 视频 | 关键帧选择设置 |
| 模板 | 模板 ID 和版本 |
| 词表 | 词表版本 |
| Prompt | Prompt 版本 |
| Schema | 结构化输出 schema 版本 |
| Provider | Provider ID |
| Model | 模型 ID |
| 质量 | 质量模式 |
| 语言 | 输出语言 |

### 运维

- 命中 / 未命中 / 失效记录
- 用户可清理缓存
- 可配置空间上限
- 不保存 API Key
- 缓存清理不删除文件、历史、模板和词表

---

## 20. 隐私设计

### 本地执行

文件扫描、文本提取、元数据提取、图片缩放压缩、扫描页渲染、视频关键帧抽取、内容哈希计算、RenamePlan 生成后的文件操作、Undo 历史、本地缓存与用量记录。

### 云端发送

| 文件类型 | 发送 | 不发送 |
|----------|------|--------|
| 文档 | 必要提取文本 + 元数据 | 完整文档二进制 |
| 图片 | 本地缩放后的图像 | 原始分辨率图片 |
| 扫描件 | 本地渲染的必要页面 | 完整 PDF |
| 视频 | 约 4–8 个缩放关键帧 + 摘要 | 完整视频 |

缩放后的图像和关键帧属于二进制/编码视觉数据。不声称"不发送二进制数据"或"所有处理都在本地"。

### 用户控制

- 可分别关闭文本、图片、扫描件和视频的云端分析
- 关闭后明确降级
- 首次启用视觉分析时披露
- System Status 和设置页可随时查看当前发送策略

---

## 21. 国际化

### 框架策略

- 所有可见文案进入翻译资源
- QML / Python 不散落硬编码用户文案
- 稳定文案 ID、占位符、复数、日期、时间和数字
- Unicode 支持、字体回退、伪本地化
- 布局支持文字扩展（德文比英文长约 30%）
- 缺失翻译回退 `en-US`

### 目标 Locale

`zh-CN` / `en-US` / `ja-JP` / `ko-KR` / `vi-VN` / `th-TH`

### 首期正式交付

简体中文、英语。

### 后续语言包

日语、韩语、越南语、泰语。

### 三种语言概念分离

| 概念 | 说明 |
|------|------|
| UI Language | 界面显示语言 |
| AI Output Language | AI 分析和字段生成语言 |
| Filename/Template Output Language | 最终文件名和路径语言 |

三种语言独立配置。

### 词表国际化

使用稳定概念 ID（如 `subject.finance`、`type.invoice`、`status.draft`）。显示名按 locale 保存。用户自定义词条允许记录语言，但不强制翻译。

---

## 22. System Status

- 居中模态，背景模糊
- 总体状态 Chip：就绪 / 检查中 / 需要注意 / 不可用
- 本地处理组件状态
- 云端 AI 状态
- 文本与视觉能力分别显示
- Provider / Model / 最近测试结果
- 非货币用量与 ResourceGuard 状态
- 操作：重新检查、重载、清缓存、测试连接、打开设置
- 不显示 API Key

---

## 23. 错误呈现

### 四层错误

| 层级 | 场景 |
|------|------|
| 文件卡片内 | 单项失败原因 |
| 批次错误 | 批量操作总结 |
| Toast | 临时通知 |
| 阻断模态 | 需要用户决策的严重错误 |

### 统一错误对象

```
ErrorInfo {
    code: string           // 机器可读错误码
    scope: "item" | "batch" | "system"
    severity: "warning" | "error" | "fatal"
    retryable: boolean
    user_message_id: string  // 国际化 key
    recommended_action: string
    sanitized_detail: string
    correlation_id: string
}
```

### 错误场景覆盖

`401` / `403` / `404` / `429` / `timeout` / `network` / `5xx` / `json_invalid` / `no_vision_capability` / `resource_limit` / `user_cancellation` / `file_missing` / `file_locked` / `file_changed` / `conflict` / `permission_denied`

**不得显示：** API Key、堆栈跟踪、请求正文、敏感文件内容。

---

## 24. 数据恢复

- 配置损坏 → 隔离损坏文件，加载最近有效快照，回退安全默认
- 缓存损坏 → 自动清理重建
- 工作区损坏 → 隔离，提示用户
- Undo 历史损坏 → 隔离损坏批次，暂停新的 Apply/Undo，不静默丢弃
- 凭据不删除（损坏恢复不触碰系统凭据管理器）

---

## 25. 诊断包

### 默认包含

应用版本、Windows/Qt 版本、组件状态、脱敏配置、错误代码、最近日志、schema 版本、Provider/模型、非正文调用统计。

### 默认排除

API Key、文件正文、原始 AI 请求响应、完整路径、图片、视频帧、私有缓存、用户身份信息。

导出前显示内容预览。

---

## 26. 安全不变量

1. API Key 仅存系统凭据（Windows Credential Manager）
2. JSON 不序列化 API Key
3. 日志不含 Key 片段
4. 保存失败 fail-closed
5. AI 不直接操作文件
6. RenamePlan 与文件执行分离
7. Apply 前预检
8. 文件操作限制在用户指定目录
9. Undo 稳定可靠
10. Clear Workspace 不等于 Undo
11. 批量逐项结果，每项独立
12. ResourceGuard 达到安全上限时 fail-closed
13. 诊断脱敏

---

## 27. Definition of Done

每个页面/功能完成必须同时满足：

- 目标行为完整
- 自动化测试通过
- 错误状态覆盖
- 国际化文案就绪（zh-CN + en-US）
- 键盘和鼠标基本可用性
- 性能达标（无卡顿、无泄漏）
- 安全审查通过
- 截图对照验收
- 无旧 UI 结构泄漏（QTableView、QMenuBar 等）
- 无硬编码绝对安装路径
- 无 API Key 泄漏
- 无占位功能伪装已完成
- 无假成功
- 可回滚

---

## 28. 截图与交互验收矩阵

### Shell

- [ ] 默认窗口 1000×700
- [ ] 最小窗口 900×640
- [ ] 导航图标选中态
- [ ] System Status 模态

### Batch

- [ ] 空态
- [ ] 混合状态任务卡片队列
- [ ] 单卡 Hover
- [ ] 多选（复选框 + Shift/Ctrl）
- [ ] 三态主复选框
- [ ] 内联编辑
- [ ] 单项快捷 Apply
- [ ] 选中批量 Apply
- [ ] 部分成功（3 成功 2 失败）
- [ ] Undo（已撤销状态显示）
- [ ] 搜索过滤
- [ ] 每种状态筛选
- [ ] Clear Workspace
- [ ] Apply 独立进度

### Watch

- [ ] 空态
- [ ] 添加配置表单
- [ ] Active / Paused / Error / ResourcePaused
- [ ] Review First 队列
- [ ] Auto Apply 结果
- [ ] 编辑配置影响确认
- [ ] 删除配置确认
- [ ] 重启恢复

### Templates

- [ ] 模板列表
- [ ] 新建/编辑模板
- [ ] 字段拖动排序
- [ ] 实时预览
- [ ] 删除被引用模板 → 选择替代
- [ ] 词表筛选
- [ ] 用户修改预设词条
- [ ] 恢复单个/整类预设
- [ ] AI 候选词条
- [ ] 自动创建确认
- [ ] 去重提示

### Preferences

- [ ] 五个 Provider 可选
- [ ] Custom Provider 表单
- [ ] Qwen 推荐标记
- [ ] 单一当前 Provider 选中
- [ ] 无视觉能力 Provider 的 Chip
- [ ] Key 管理（保存/清空/测试）
- [ ] 三种质量模式
- [ ] 非货币用量与资源限制设置
- [ ] 隐私开关
- [ ] 国际化语言选择
- [ ] 缓存管理
- [ ] 诊断包导出

### System Status / Error

- [ ] 全部正常
- [ ] 本地组件失败
- [ ] Provider 连接失败
- [ ] 文本可用 / 视觉不可用
- [ ] 429 速率限制
- [ ] Timeout
- [ ] 资源限制触发与安全恢复
- [ ] 文件被占用
- [ ] 文件已变化
- [ ] 数据损坏
- [ ] 诊断包脱敏

---

## 29. 测试策略

| 层级 | 内容 |
|------|------|
| Domain unit | FileTask 状态机、NamingFields、Template 渲染、RenamePlan、UndoRecord |
| Controller | BatchWorkspace、TaskQueue、WatchFolder、Template、Settings |
| Provider contract | 每个 Provider 的请求/响应格式验证 |
| Credential | keyring mock 测试，fail-closed 验证 |
| Cache | 命中/未命中/失效/上下文变化 |
| File operations | Rename/Undo 安全性、冲突、权限、文件变化检测 |
| Watch | 防抖、临时文件过滤、回流防护 |
| QML component | 组件隔离渲染测试 |
| Screenshot golden | 每页状态截图对照 |
| Integration | 完整管线端到端 |
| Fault injection | 网络故障、磁盘满、权限拒绝、进程占用 |
| Privacy/Redaction | 诊断包和日志不泄露 Key/路径/正文 |
| i18n | 伪本地化测试，缺失翻译回退 en-US |
| Manual black-box | 完整验收矩阵执行 |

---

## 30. 实施阶段 Gate

以下为未来 Gate 描述。不生成实施计划。

1. 用户审阅并批准本文
2. Codex 生成实施计划
3. Product Owner 批准实施计划
4. Claude Code 按里程碑执行
5. 每个里程碑完成测试和截图
6. Codex 审查
7. Product Owner 验收
8. 通过后才进入下一里程碑
9. 未经批准不切换正式入口
10. 未经批准不发布或 push

---

> **文档结束。** 下一步：Product Owner 和 Codex 审阅书面规格。
