# 序匣有界精简验收报告

日期：2026-10-13。结论：本地候选通过本轮门禁；未替换用户试用版本，未合并、push 或发布。

> 本文是候选验收时的历史记录。随后主分支合并、主目录重新打包及快捷方式验证见[主目录整合报告](2026-10-13-simplification-integration.md)，不要将本页的候选产物哈希当作后来主目录新包的预期值。

## 1. 基线与范围

- 起始基线：`1155cbaa6656dadd9aac2a6e358ee3d8c4d175cf`。
- 候选分支：`codex/code-simplification`；工作区：`.worktrees/code-simplification`。
- 最终代码及测试验证提交：`d8016cd42b9c70aa7108c92cab365d6d2c0b9f64`；本报告及计划勾选随后单独提交，不修改应用源码。
- 不改 QML、三语言文案、手册、配置迁移、凭据保存、正式 Golden、像素容差、打包配置或正式入口。
- 保留防覆盖、同盘移动、目录链接拒绝、扩展名保护、身份/内容证据、部分 Apply/Undo、历史关联、取消/超时及本地隐私隔离。

## 2. 实施结果

### 旧执行链退休

删除正式入口不再使用的 11 个模块：

- `src/core/ai_engine.py`、`rename_engine.py`、`template_engine.py`、`folder_watcher.py`、`organization_engine.py`。
- `src/models/template.py`、`watch_config.py`。
- `src/providers/base.py`、`deepseek.py`、`openai.py`、`claude.py`。

保留当前 Provider 的历史 ID 判断，移除旧工厂构造及模型导出。`RenameHistory` 仅退休旧直接移动/批次撤销方法，其严格读取、原子写入、逐记录标记和补偿操作保留。正式 UndoManager 与原生文件操作实现没有修改。

移除 `requirements.txt` 中闲置的 `openai`、`anthropic`、`httpx` 显式 SDK 声明；未卸载或改动已有运行环境。当前兼容协议适配器不变。

旧接口验收迁到正式 TemplateRenderer、RenameExecutor/UndoManager、WatchController 和 Provider adapter。验收实际检查渲染、合成副本 Apply/Undo、字节恢复、task/batch 关联、防覆盖、扩展名拒绝、Watch 配置及生命周期、离线传输契约，而非只构造类即通过。

只删除专属于退休 AIEngine 的五个用量测试及其独占 helper，其他 UsageRecorder 测试保留；不宣称本轮新增了用量接线。日志保护专项测试迁至正式适配器，保留原全源码扫描及凭据/设置保护。

### 媒体校验去除第二次完整协议往返

新增 `validate_result`，本地分析不再先拼接完整二进制媒体帧，再解码、切片复制图像。真实子进程 IPC 保持不变。

共享原有对象校验，重新检查被绕过冻结的字段、coverage、图像 descriptor、来源/版本、摘要、签名、质量及调用方限制。等效 header/frame/text 字节边界与严格 JSON 重复键拒绝保留。仍计算必要的摘要及小型 header；没有取消安全证据校验，也没有声称零复制或实测提速。

### 推理映射去重

三处相同 cleanup 状态映射改用私有纯函数；仅合并返回相同错误码的分类分支。owner 保存/释放、进程清理、journal、锁、取消、超时、发布及异常重抛顺序不变。

## 3. 真实删减统计

统计范围为 `git diff --numstat 1155cbaa..d8016cd -- src`，不把测试或文档的增减算作应用源码收益。

| 指标 | 结果 |
| --- | --- |
| src 跟踪文件 | 207 → 196（少 11 个） |
| 改动 src 文件 | 17 个（含删除） |
| src 新增 / 删除行 | 60 / 1211 |
| src 净减少 | 1151 行 |

候选安装目录仍有 3323 个文件。与既有试用产物相比，总大小仅减少 2220 字节，不能宣称安装包明显缩小。未做速度/峰值内存基准，不给性能百分比；本轮收益主要是减少维护两套执行逻辑的成本及一次完整媒体帧往返。

## 4. 测试与审查

Windows 运行环境为 Python 3.14.5、PySide6/Qt 6.12.0。测试使用隔离用户数据目录及真实网络/凭据访问阻断器；所有最终测试日志的 forbidden access attempts 均为 0，退出时仅剩 MainThread。正式截图更新变量均关闭。

| 最终门禁 | 原始摘要 | 日志（位于 tests/screenshots/qa-current/local-privacy/） |
| --- | --- | --- |
| 完整非截图 pytest | 6306 passed, 3 skipped, 4 warnings；return 0 | simplification-final-full-rerun.log |
| 完整正式截图 | 54 passed, 1 skipped, 86 warnings；return 0 | simplification-final-screenshots-rerun.log |
| 专项 packaging（亦包含于非截图套件） | 33 passed, 3 warnings；return 0 | simplification-final-packaging.log |
| acceptance | 176/176 passed, 0 failed；return 0 | simplification-final-acceptance.log |
| 干净 Windows 构建 | exit 0；两个既有可选依赖警告 | simplification-final-build.log |
| 隔离候选 EXE smoke | 实际进程 exit 0，QML warnings 0 | simplification-final-exe-smoke-waited/report.json |

176 项验收是迁移后的真实数量；旧 186 项含退休接口/行为，不通过凑数维持旧总量。表中专项 packaging 不应再与非截图总量相加。

三项非截图 skip 均为既有文件符号链接权限不可用：`test_local_resource_store.py:179`、`test_processing_intent_store.py:486`、`test_watch_config.py:223`。未修改系统权限。截图唯一 skip 是更新模式自身的测试在更新关闭时按设计跳过；真实 capture/compare 与突变检测均正常运行。没有新增 skip/xfail、排除失败测试或放宽断言。

逐项独立 spec/quality 审查全部通过；最终全分支审查覆盖全部五个初始提交及修复增量，未发现确定性 P0/P1。报告结论还依赖主控直接核对原始日志、产物和 Git 状态，而非只接受执行者文字。

### 失败记录没有抹去

- 初始隔离工作区缺少产物，另有 Watch 集成测试过早把 APPLIED 当作 owner 已退出。用持有真实 Apply 尾部的负向测试确认 Undo 必须拒绝；修正测试等待真实 owner/lane idle，没有改产品保护或增加超时。复制产物的 LF/CRLF 差异通过同源重新构建解决，没有放宽字节比较。
- 首轮最终完整运行为 `1 failed, 6305 passed`，保留在 `simplification-final-full.log`。新增容量错误测试受既有模块 reload 的类身份影响；按实际服务绑定异常类构造合成异常。先得到同序 RED `1 failed, 59 passed`，再同序 GREEN `60 passed`、原定向 `202 passed`，最后完整重跑得到上表结果。只改新增测试 import，生产代码及所有断言不变。
- 初次用 PowerShell 直接启动 GUI 型 EXE 未取得可靠 LASTEXITCODE，不作通过证据。随后使用 Hidden/Wait/PassThru 等待真实进程退出，在新的隔离目录取得 exit 0 和报告；旧诊断产物保留。

## 5. Windows 候选产物

- 相对工作区路径：`dist/Xuxia/Xuxia.exe`。
- EXE SHA-256：`96d8dc2216bcd4a467be3197b7e80aced9af29a48395042c750c7efe4c9f872c`。
- EXE 大小：11,558,522 字节。
- 完整目录：3323 文件，672,526,908 字节；含原有三语言 HTML 手册及资源。
- 使用既有 `scripts/build_windows.ps1 -PythonPath` 干净构建，未改 spec/脚本。构建发生于 `f60c519`；随后 `d8016cd` 只改测试，两者 `src` tree 均为 `b831bd8cae97ba85b4f2681949f6c3a883d492da`，应用源码及所有构建输入完全相同。最终新 HEAD 的 packaging/验收再次通过。
- 显式隔离 EXE smoke 使用 ephemeral 凭据后端，不访问真实 Credential Manager。图片预处理、PDF 渲染、视频关键帧、诊断导出均 ok；Windows 凭据后端只做 import 检查。stderr 为空，进程已退出。
- 未运行真实模型或云端 API；以上不冒充模型命名语义质量重新验收。

## 6. 保留的试用版本与回滚

主检出仍是 `feature/xuxia-m0-foundation`，HEAD `1155cbaa6656dadd9aac2a6e358ee3d8c4d175cf`。主 EXE SHA-256 仍为 `6b5c64f7984bf91fc10a81fc96c2cc94293321edc6b43b4ff0a8914d5b044331`；`序匣.lnk` 仍指向主目录 `dist/Xuxia/Xuxia.exe`，无参数。未修改模型资源或其他历史 worktree。

Golden tree 与基线相同：`2eeaf100153171d2de3c7ffce50a407e81f47cce`。

本地提交链：`26904e0`（Watch 测试）→ `f1aeafd`（范围设计）→ `ce5e306`（旧链退休）→ `a5af09d`（媒体校验）→ `f60c519`（状态映射）→ `d8016cd`（测试顺序）。删除内容均可从基线 Git 历史恢复。保留候选分支及工作区，不自动替换试用版或推送 GitHub。

候选最终已跟踪文件应无未提交修改；私有 `.superpowers/` 审查材料留在本地且未提交。主目录已有未跟踪的用户快捷方式保留，不声称所有工作区绝对无未跟踪文件。

## 7. 非阻断后续项

- 既有 Pydantic class-config、PyPDF2、Pillow getdata 弃用警告，后续依赖维护处理。
- 两个既有可选构建警告：Qt labs assetdownloader DLL、tzdata hidden import；当前完整打包门禁及 EXE smoke 未因此失败。
- BatchAnalysisService 的历史兼容调用接口及 Watch 测试替身迁出生产目录暂缓，避免扩大异步接线改动。
- 不删除恢复证据，不合并不同时间点的资源/身份复核，不减弱进程树退出及句柄关闭证明。
