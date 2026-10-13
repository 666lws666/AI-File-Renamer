# 序匣 M8 发布候选自审报告

**审计日期：** 2026-08-12
**审计分支：** `codex/m8-release-readiness`
**受审代码 HEAD：** `20bc197e315cbd019c5044d645f12cd1fa468703`
**产品范围：** 个人使用的 Windows 桌面发布候选（RC），不是已签名的公开发行包
**结论：** 本地 Windows RC Gate 通过；等待 Product Owner 最终验收。未 push、未发布。

## 1. 审计边界与权威决策

本报告以 `docs/XUXIA_DETAILED_DESIGN.md`、Product Owner 的后续明确决策和实际可复现测试为依据。若早期计划与后续决策冲突，以后续决策为准：

- 正式品牌为“序匣 / Xuxia”。
- 用户只选择一个当前 Provider；不要求同时配置 DeepSeek 与 Qwen。
- 首期提供 DeepSeek、Qwen、MiMo、智谱、Kimi 和 Custom 预设；不提供 OpenAI/Anthropic 品牌预设。
- 不展示 API 价格、币种、费用估算、账单或金额预算；保留非货币 UsageRecorder、ResourceGuard、缓存、并发/尺寸/页数/帧数/重试上限。
- 图片和扫描页可发送缩放后的视觉载荷；视频仅在本地提取关键帧后按图片分析，绝不上传完整视频。
- 当前只判定个人 Windows RC；登录、团队后台、授权计费、遥测、自动更新服务、签名和公开安装器均不是本阶段交付物。

所有自动化与原生 QA 均使用本地合成数据、Fake Credential Store 或隔离临时目录；没有真实 API 请求、真实 Key 或真实 Credential Manager 写入。

## 2. 发布候选产物

| 项目 | 结果 |
|---|---|
| 正式入口 | `python -m src.main` → QML Shell |
| 版本命令 | `python -m src.main --version` → `序匣 1.0.0` |
| Windows onedir | `dist/Xuxia/Xuxia.exe` |
| EXE 大小 | 10,889,579 bytes |
| 包内文件数 | 3,047 |
| 包总体积 | 566,275,430 bytes |
| 正式打包入口 | `packaging/xuxia.spec` → `src/main.py` |
| 旧 UI 回滚入口 | `legacy/run_legacy.bat` → `src.main_legacy` |
| 用户数据目录 | 与程序目录分离；打包冒烟使用隔离目录验证 |
| Git 状态 | 受审时 tracked clean；未 push |

## 3. 最终自动化证据

所有下列命令均在 `D:/文件AI-AGENT/.worktrees/m8-release-readiness` 使用项目虚拟环境运行。

| Gate | 命令 | 原始结果 | 判定 |
|---|---|---|---|
| 打包与正式入口 | `pytest tests/packaging/test_packaged_app.py -q` | 16 passed，3 warnings | PASS |
| 完整非截图测试 | `pytest tests --ignore=tests/screenshots -q` | 1610 passed，1 skipped，3 warnings | PASS |
| 正式截图回归 | `UPDATE_GOLDENS` 未设置；`pytest tests/screenshots -q` | 54 passed，1 skipped，86 warnings | PASS |
| 旧基线验收 | `python acceptance_test.py` | 186/186，0 failed，100% | PASS |
| Git 格式 | `git diff --check` | exit 0 | PASS |

跳过项均为既有、明确的测试条件：Windows symlink 平台跳过，以及截图 update-mode 测试在更新模式未开启时按设计跳过。没有排除失败测试。

警告不影响当前 RC：3 条为 Pydantic v2 class-based `Config` 的未来 v3 迁移提示；86 条为 Pillow `Image.getdata()` 的 2027 年弃用提示。两者均登记在第 8 节。

## 4. 原生 Windows 视觉与交互证据

### 4.1 正式 Golden

- 40 个 Shell/Batch 语义案例映射到 38 个去重后的实际 Golden 文件。
- Golden 由 Windows QPA 和 `Microsoft YaHei UI` 捕获，不使用会产生中文 tofu 的 offscreen 字体结果。
- 覆盖 1000×700、900×640、zh-CN、en-US、空态、混合队列、筛选、选择、搜索、内联编辑错误、Apply 进度等。
- 本轮最终以 `UPDATE_GOLDENS` 关闭运行，54 个截图测试全部通过；M0 Golden 未被修改。

### 4.2 阶段原生 QA（不作为正式 Golden 提交）

这些证据仅写入被忽略的 `tests/screenshots/qa-current/`，对应捕获脚本保留为可复现测试入口：

| 阶段 | 证据 | 结论 |
|---|---|---|
| M6 Preferences | 主检出 `qa-current/m6/` 44 个文件，含 `M6_NATIVE_VISUAL_REVIEW.md` | Provider、语言、数值校验、Usage、隐私、保存反馈、CJK、滚动/遮挡 PASS |
| M7 Status/Error | `qa-current/m7/` 8 PNG + manifest | 4 状态、900×640、分层错误、阻断模态、诊断预览、warnings=0 PASS |
| M8 Batch | `qa-current/m8/` 10 PNG + manifests | 真实鼠标点击、选择、内联编辑、进度、滚动、CJK、warnings=0 PASS |
| M8 Pages | `qa-current/m8/pages/` 7 PNG + manifest | Watch 空态/左侧表单、Templates、Vocabulary、Preferences、900×640、warnings=0 PASS |

这里明确记录证据模型的偏差：§28 并非每个非 Batch 页面都建立永久正式 Golden；M6/M7/Watch/Templates/Vocabulary/Preferences 使用可复现的原生 Windows QA 证据。Product Owner 已批准本轮受控 M8 Golden 范围，因此该偏差不阻断个人 Windows RC，但在未来公开发布前应决定是否把这些页面升级为长期 Golden。

## 5. 30 章设计覆盖矩阵

| 章节 | 主要实现/验证证据 | 状态 |
|---|---|---|
| 1 文档目的与权威性 | 设计文档、后续决策覆盖规则、本报告 | PASS |
| 2 产品目标与非目标 | 单机 Windows RC；登录/计费/团队/更新服务未提前实现 | PASS |
| 3 旧决策替代 | 单一 Provider、非货币护栏、视频关键帧语义已落地 | PASS |
| 4 架构与模块边界 | QML、Controller、Domain、Service 分层；QML 不直接执行文件 I/O | PASS |
| 5 统一数据流 | `test_full_pipeline.py`、Batch analysis/Watch integration | PASS |
| 6 视觉系统与 Shell | QML Shell、5 个导航入口、正式 Windows Golden/原生截图 | PASS |
| 7 Batch 空态 | `test_batch_empty.py`、空态 Golden | PASS |
| 8 Batch 非空工作区 | `test_batch_nonempty.py`、`test_task_card.py`、混合队列 Golden | PASS |
| 9 内联编辑与验证 | `test_inline_edit.py`、Windows 文件名校验、原生点击证据 | PASS |
| 10 Apply/批量/Undo | RenamePlan/Preflight/RenameExecutor/UndoManager 单元与集成测试 | PASS |
| 11 Watch Folders | Watch controller、Review First、Auto Apply、恢复与资源护栏测试、原生页面证据 | PASS |
| 12 Templates | store/renderer/impact/controller/QML 测试与原生页面证据 | PASS |
| 13 受控词表 | presets/override/AI candidates/use-once/cache context/QML 测试 | PASS |
| 14 Preferences | Settings transaction/controller/QML 195 项阶段回归及 M6 原生 Gate | PASS |
| 15 Provider | 5 家 + Custom 合约、单一 active manager、连接测试、无真实网络 | PASS |
| 16 质量模式 | QualityRouter、低置信度重试、明确非“高级文本 Provider” | PASS |
| 17 图片/扫描件/视频 | Pillow、PyMuPDF、关键帧、取消/超时/降级及真实合成媒体 QA | PASS |
| 18 非货币用量与资源护栏 | UsageRecorder、ResourceGuard；金额预算/价格模块已删除 | PASS |
| 19 本地哈希缓存 | CacheManager、Vocabulary cache context、失效集成测试 | PASS |
| 20 隐私设计 | 安全 Provider payload、完整视频/PDF不出进程、诊断脱敏测试 | PASS |
| 21 国际化 | zh-CN/en-US、locale completeness、语言切换、Unicode/伪本地化测试 | PASS |
| 22 System Status | status controller/modal、4 状态、M7 原生证据 | PASS |
| 23 错误呈现 | ErrorHandler、文件/批次/Toast/阻断模态与故障注入 | PASS |
| 24 数据恢复 | workspace/Watch/Undo restart recovery 测试 | PASS |
| 25 诊断包 | diagnostics 单元、settings integration、打包 smoke、M7 原生预览 | PASS |
| 26 安全不变量 | API Key 日志 AST、隔离配置、future schema、路径/扩展名/预检测试 | PASS |
| 27 Definition of Done | 自动化、原生视觉、打包、回滚与偏差均有证据 | PASS |
| 28 截图/交互矩阵 | 正式 Batch Golden + M6/M7/M8 原生证据；证据模型偏差已披露 | PASS（有记录偏差） |
| 29 测试策略 | unit/QML/provider contract/integration/screenshot/packaging/acceptance 全层覆盖 | PASS |
| 30 阶段 Gate | M0–M8 分阶段提交与验收；本报告完成 Task 8 | PASS |

## 6. 关键安全与隐私断言

- API Key 使用系统凭据抽象；JSON 不序列化 Key；设置保存采用跨 JSON/凭据补偿事务。
- 连接测试、Provider 合约、打包 smoke 和视觉 QA 均使用 fake transport/fake credential/临时目录，不访问真实服务。
- ProviderRequest 只接受提取文本、元数据、缩放图片/扫描页/视频帧等安全 payload；不接受任意原文件对象。
- 图片有尺寸/字节限制；PDF 有安全页数和渲染边界；视频有 4/6/8 帧、去黑帧/重复帧、取消和 deadline；完整 PDF/视频及源路径不进入云端 payload。
- Apply/Undo 的唯一 I/O 边界为执行器；Preflight 校验 allowed roots、扩展名、冲突与路径安全；批量逐项记录结果，不伪装原子成功。
- 配置 schema 版本化，未来版本在任何迁移/凭据写入前 fail-closed。
- 诊断包执行脱敏；日志 AST 测试禁止 API Key 片段输出。

## 7. 入口、回滚与分发边界

- 默认 BAT/VBS、Python 模块和 PyInstaller spec 均进入 QML Shell。
- `legacy/run_legacy.bat` 保留旧 Qt Widgets UI，作为无需重写 Git 历史的本地回滚入口。
- 本报告不批准 push、GitHub release 或对外分发；这些仍需 Product Owner 最终决定。
- 当前产物是 onedir 文件夹，不是签名安装器；若公开分发，仍需代码签名、安装器/卸载流程和目标机器矩阵验证。

## 8. 已知偏差与风险登记

| ID | 事项 | 影响 | RC 判定 | 后续动作 |
|---|---|---|---|---|
| R-01 | Pydantic class-based `Config` 弃用提示 | Pydantic 3 才会移除 | 非阻断 | 升级前迁移到 `ConfigDict` |
| R-02 | Pillow `getdata()` 测试 API 弃用提示 | 2027-10-15 后需更新测试 | 非阻断 | 改用 `get_flattened_data()` |
| R-03 | PyInstaller 报告可选 Qt Labs AssetDownloader/tzdata 缺失 | 当前正式 QML 和打包 smoke 均不依赖 | 非阻断 | 若引入相应模块再纳入包 |
| R-04 | §28 非 Batch 页面使用 QA-current 原生证据而非永久 Golden | 长期视觉漂移自动检测较弱 | 个人 RC 非阻断 | 公开发布前决定是否扩展正式矩阵 |
| R-05 | onedir 包约 566 MB | 分发体积较大 | 个人 RC 非阻断 | 后续做依赖裁剪，不得以删功能换体积 |
| R-06 | 包未签名、无安装器 | Windows SmartScreen/安装体验未完成 | 公开分发阻断；个人本机非阻断 | 发布前签名并建立安装器 |
| R-07 | 历史兼容代码仍含 OpenAI/Claude adapter | 不在首期 UI 预设，不影响已批准 Provider 范围 | 非阻断 | 保持隔离；公开文档不宣称首期支持 |
| R-08 | `decide()` 对不可转换的任意 content-kind 字符串仍可能抛 `ValueError` | 内部调用受枚举约束；外部滥用才触发 | 非阻断 | 后续统一输入防御 |

## 9. 发布阻断判定

### 个人 Windows RC

未发现安全、数据一致性、核心功能、打包启动或已批准视觉范围内的阻断项。判定：**READY FOR PRODUCT OWNER ACCEPTANCE**。

### 公开分发

仍有明确阻断：Product Owner 尚未最终批准；没有代码签名和正式安装器；尚未执行公开发布目标机器矩阵。判定：**NOT YET APPROVED FOR PUBLIC RELEASE**。

## 10. 最终 Gate

- [x] 默认入口切换到 QML Shell
- [x] 旧 UI 回滚入口保留
- [x] Windows onedir 重新构建并通过隔离 smoke
- [x] 完整非截图测试通过
- [x] 截图测试在更新关闭时通过
- [x] 186/186 旧基线验收通过
- [x] 五 Provider + Custom 合约与连接边界已覆盖
- [x] 文件操作、Undo、恢复、故障注入、安全和隐私测试已覆盖
- [x] zh-CN/en-US、Unicode、CJK 原生渲染与 900×640 遮挡检查已覆盖
- [x] 已知偏差、风险、回滚和分发边界已记录
- [ ] Product Owner 最终验收
- [ ] Product Owner 明确授权后再 push/release

**审计结论：** 序匣已形成可供 Product Owner 本机验收的 Windows 发布候选。该结论只覆盖本报告列明的代码、测试、原生证据和 onedir 构建，不等同于已经公开发布。
