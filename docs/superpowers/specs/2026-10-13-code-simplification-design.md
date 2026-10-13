# 序匣：行为不变的有界精简

## 已批准目标

Product Owner 在代码审查后授权自主设置精简目标并实施。本轮减少历史执行链和重复实现，不新增功能、不重新设计界面，不削减文件安全或本地隐私保护。

从 `1155cbaa6656dadd9aac2a6e358ee3d8c4d175cf` 建立独立分支 `codex/code-simplification`。主检出、已交付 EXE、模型资源、快捷方式和 GitHub 当前版本保留。交付经过验证、可回滚的本地候选提交；不自动替换用户正在试用的程序。

## 方案与取舍

1. 仅删除重复行：风险低，但不能解决两套执行链并存，收益太小。
2. 有界退休旧链，并复用纯校验与状态映射：本轮采用。把验收迁到正式模块，保留配置迁移与全部核心安全测试。
3. 重写所有兼容接口和测试替身：会牵动大量异步测试接线，精简可能演变成架构重写，本轮不采用。

## 范围

### 退休不再由正式入口使用的旧模块

- `src/core/ai_engine.py`
- `src/core/rename_engine.py`
- `src/core/template_engine.py`
- `src/core/folder_watcher.py`
- 上述旧链独占、并经调用核对的 `src/core/organization_engine.py`、`src/models/template.py`、`src/models/watch_config.py`、`src/providers/base.py`、`src/providers/deepseek.py`、`src/providers/openai.py`、`src/providers/claude.py`。

`src/providers/factory.py` 保留 `LEGACY_PROVIDER_IDS` / `is_legacy_provider()`，去掉旧客户端构造及 SDK 导入；现有 preset gate 仍可拒绝历史品牌预设。`AppConfig` 和配置迁移不改；旧 JSON 数据迁移仍由现有正式代码处理。保留共享 `FileItem`、扫描和提取功能。

随退休链移除 `requirements.txt` 中仅旧客户端使用的 `openai`、`anthropic`，以及源码/脚本均未使用的 `httpx` 声明。现有 urllib Provider transport 不变，不卸载当前测试环境中的包，不加入替代依赖。

`RenameHistory.undo_batch()` / `_rewrite_with_undone()` 仅被旧 RenameEngine 调用，也随旧链退休；前者另行直接移动文件，后者会整批标记。保留正式的 `UndoManager` / native executor 路径，以及历史读取、原子写、逐记录标记与补偿方法。历史模块只承担持久化，不再保留第二个撤销执行器。

将 `acceptance_test.py` 中旧类导入、旧渲染、旧工厂、旧 Watch 与模拟集成验收迁到实际 `TemplateRenderer`、`RenameExecutor`、`UndoManager`、`WatchController` 和当前 Provider contract。删除 `test_usage.py` 仅面向已退休 AIEngine 的五项测试，保留所有 UsageRecorder 的存储、脱敏、时间、统计和失败测试。报告旧断言到现有/新增断言的对应关系，不维持虚假的历史 186 数字。

### 本地媒体校验

在 `preparation_protocol.py` 内增加同一份对象校验入口，供协议解码和分析边界使用。分析服务不再将已经解码的全部图片字节拼成新的 IPC 帧后再拆开。仍需校验完整对象、描述符/摘要/签名、覆盖信息、协议帧等效大小、质量和调用方资源限制。不得信任调用方用 `object.__setattr__` 修改过的 frozen 对象，也不得用只检查类型代替校验。

保持原有真实子进程 IPC 解码与严格 JSON 检查。以旧 `decode_result(encode_result(result), ...)` 的行为作为等价比较基线，覆盖正确结果、对象绕过修改和所有大小/页数/帧数/质量限制。

### 状态映射

仅在 `inference_service.py` 合并相同异常分类分支，提取三处相同的清理错误到阶段映射。不得移动清理调用、owner 保存/释放、journal 操作、锁、取消/超时检查或异常重抛。

## 不变约束

- 同盘安全移动、目录链接拒绝、防覆盖、扩展名保护、身份及内容证据、部分 Apply/Undo、历史关联和回滚保持不变。
- 切换本地后阻止云端提交、本地失败不回退云端、AppContainer 零能力、进程树退出/句柄关闭证明、下载和处理分离保持不变。
- 不使用真实云端 API、真实 Key、真实 Credential Manager 或私密测试输入。
- 不改 QML、三语言文案、手册、正式 Golden、像素容差或截图断言。
- 不删功能测试来掩盖失败，不新增 skip/xfail，不改系统安全配置，不 push 或发布。
- 不改其他历史 worktree，不改写已有提交，不清理未知恢复证据。

## 验收与交付

先验证当前源码基线；缺少隔离工作区构建产物/诊断 runtime 时记录失败原文并补齐同源本地测试资源，不修改产品代码来通过基线。

每项先有失败测试，再实施、定向回归和独立审查。最后运行完整非截图 pytest、Git 跟踪的完整截图套件（更新关闭）、当前 acceptance、packaging tests、候选 EXE 构建与隔离 smoke。测试数量从实际输出取得，不沿用历史数量。

记录源码净减少行数、文件数、保留边界、测试迁移清单、原始结果和未处理的维护候选。新候选程序保存在隔离 worktree，主目录可试用版本不替换。
