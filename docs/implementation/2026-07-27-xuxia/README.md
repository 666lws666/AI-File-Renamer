# 序匣 (Xuxia) 完整分阶段实施计划

> **状态**: 计划文档 | **日期**: 2026-07-27
>
> 本文档仅供 Product Owner 审查和批准。当前不构成实施授权。

---

## 1. 文档目的与权威来源

本实施计划依据以下权威文档编制：

- **最高权威**: `docs/XUXIA_DETAILED_DESIGN.md`（30 章完整设计）
- 冻结基线: `docs/PRODUCT_SPEC.md` / `docs/CURRENT_STATE_GAP_ANALYSIS.md` / `docs/DECISIONS.md` / `docs/ACCEPTANCE_MATRIX.md`
- 当前仓库代码基线: `src/` / `tests/` / `acceptance_test.py`

冲突时以 `XUXIA_DETAILED_DESIGN` 为准。

---

## 2. 当前仓库基线

| 项目 | 值 |
|------|-----|
| Phase 1A checkpoint | `391c309` — 安全与启动健康（已冻结） |
| 设计基线 | `b24dfcf` — 详细设计文档 |
| 旧 UI | PySide6 QWidget/QTableView（保留至新 UI 验收后切换） |
| 新 UI 隔离 | QML/Qt Quick，独立入口或开关控制 |
| 现有测试 | pytest 28 passed / acceptance 186 passed / 总计 214 |

---

## 3. 全局技术约束

- **UI**: PySide6 + QML/Qt Quick，自定义 Shell，左侧图标导航
- **分层**: UI → Controller → Domain → Service
- **UI 不直接调用 AI 或文件系统**
- **QML 不承载业务规则**
- **领域层不依赖 Qt**
- **Provider 可替换**，单一当前 Provider，不跨供应商隐式调用
- **首期预设**: DeepSeek/Qwen/MiMo/智谱/Kimi + Custom
- **首期不含** OpenAI/Anthropic 品牌预设
- **i18n**: zh-CN + en-US 首期，框架从 M0 建立
- **安全**: Key 仅存 Credential Manager，JSON 不含 Key，日志不含 Key 片段
- **所有 Apply 预检 + Undo + Clear Workspace 不删 Undo**
- **预算 fail-closed**
- **本地多上下文哈希缓存**

---

## 4. 新目录与模块结构总图

```
src/
├── app.py                    # 入口（旧）
├── main.py                   # 启动（旧）
├── config.py                 # 配置持久化（复用 + 扩展）
├── models/                   # 数据模型（复用 + 扩展）
├── core/                     # 领域与服务（复用 + 扩展）
│   ├── file_task.py          # 新: FileTask 状态机
│   ├── rename_plan.py        # 新: RenamePlan
│   ├── batch_workspace.py    # 新: BatchWorkspaceController
│   ├── task_queue.py         # 新: TaskQueueController
│   ├── provider_manager.py   # 新: Provider 管理
│   ├── capability_router.py  # 新: 能力检测与路由
│   ├── budget.py             # 新: 预算控制
│   ├── cache_manager.py      # 新: 多上下文缓存
│   ├── usage.py              # 新: 用量记录
│   ├── vocabulary.py         # 新: 受控词表
│   └── ...
├── providers/                # AI Provider（复用 + 扩展 + 淘汰）
├── ui/                       # 旧 UI（保留）
│   └── ...
├── ui_qml/                   # 新: QML 层
│   ├── main.qml              # Shell
│   ├── pages/                # Batch/Watch/Templates/Preferences/Status
│   ├── components/           # 共享组件
│   ├── icons/                # SVG 图标资源
│   └── controllers/          # QML 端控制器绑定
├── controllers/              # 新: Python 控制器
│   ├── batch_controller.py
│   ├── watch_controller.py
│   ├── template_controller.py
│   ├── settings_controller.py
│   └── status_controller.py
└── utils/
    ├── credential_manager.py  # 安全凭据（复用）
    ├── i18n.py                # 新: 国际化框架
    └── ...

tests/
├── ...                        # 现有测试（保留）
├── unit/                      # 新: 领域单元测试
├── integration/               # 新: 集成测试
├── qml/                       # 新: QML 组件测试
└── screenshots/               # 新: 截图 golden tests
```

---

## 5. 里程碑顺序与依赖

```
M0: Foundation & Safety Net
 └─→ M1: QML Shell + Batch Visual Slice
      └─→ M2: Domain Queue + Apply + Undo
           ├─→ M3: Provider + Multimodal + Budget + Cache
           ├─→ M4: Templates + Vocabulary
           │    └─→ M5: Watch Folders (依赖 M2 + M4)
           └─→ M6: Preferences + Provider Mgmt
                └─→ M7: System Status + Errors + Recovery + Diagnostics
                     └─→ M8: Integration + Cutover + Release Readiness
```

M3/M4/M6 可以部分并行（不同领域），但都依赖 M2。M5 依赖 M2 和 M4。M7 依赖 M3 和 M6。

---

## 6. 各里程碑摘要

| Milestone | 目标 | 产物 | 入口条件 | 退出 Gate |
|-----------|------|------|----------|-----------|
| **M0** | 基础架构、安全网、测试/截图基础设施 | 新目录、i18n 框架、QML 启动、截图自动化、schema 版本 | 计划批准 | QML 窗口渲染 + i18n 切换 + 截图运行 |
| **M1** | QML Shell + Batch 视觉切片 | Shell、导航、Batch 空态/非空卡片、八状态渲染 | M0 通过 | 全部视觉截图 Gate |
| **M2** | 领域状态机、队列、Apply、Undo | FileTask、RenamePlan、Workspace、Queue、预检、持久化 | M1 通过 | 故障注入全绿 |
| **M3** | Provider、多模态、预算、缓存 | Provider 管理、能力检测、经济/均衡/高质量、图片/视频预处理、缓存、预算 fail-closed | M2 通过 | Provider 合约测试 + 预算 fail-closed 测试 |
| **M4** | Templates + Vocabulary | 字段 CRUD、实时预览、词表五类、AI 候选/自动创建 | M2 通过 | 模板渲染 + 词表交互测试 |
| **M5** | Watch Folders | 监控配置、Review First/Auto Apply、防抖、回流防护、预算保护 | M2 + M4 通过 | Watch 端到端测试 |
| **M6** | Preferences + Provider Mgmt | 单页卡片、原子保存、五个 Provider、Custom、Qwen 推荐 | M2 + M3 通过 | 所有设置持久化 + fail-closed |
| **M7** | Status + Errors + Recovery + Diagnostics | 系统状态模态、四层错误、损坏恢复、诊断包、脱敏 | M3 + M6 通过 | 故障注入 + 脱敏验证 |
| **M8** | Integration + Cutover + Release | 全管线集成、性能、打包、旧入口切换、§28 全矩阵 | 全部前序通过 | Product Owner 最终验收 |

---

## 7. Git 策略

- 每个任务独立提交，小步前进
- 不 amend 已冻结基线 (`391c309` 及之前)
- 不自动 push
- 每阶段可独立 `git revert` 回滚
- 新 UI 期间旧入口保持可用

---

## 8. 自动化测试层级

| 层级 | 位置 | 范围 |
|------|------|------|
| Domain unit | `tests/unit/` | FileTask, RenamePlan, NamingFields, Cache, Budget |
| Controller | `tests/unit/` | mock 依赖的控制器测试 |
| Provider contract | `tests/integration/` | 每个 Provider 的请求/响应格式 |
| Credential | `tests/unit/` | keyring mock, fail-closed |
| Cache | `tests/unit/` | 命中/未命中/失效/上下文变化 |
| File ops | `tests/integration/` | Rename/Undo 安全、冲突、权限 |
| Watch | `tests/integration/` | 防抖、过滤、回流防护 |
| QML component | `tests/qml/` | 组件隔离渲染 |
| Screenshot golden | `tests/screenshots/` | 每页每状态截图对照 |
| Fault injection | `tests/integration/` | 网络、磁盘、权限故障 |
| Privacy | `tests/unit/` | 诊断/日志脱敏 |
| i18n | `tests/unit/` | 伪本地化、缺失回退 en-US |

---

## 9. 截图验收流程

1. 运行应用在目标尺寸和 locale
2. 加载确定性 fixture/mock 数据
3. 截取指定页面和状态
4. 保存到 `tests/screenshots/{milestone}/{page}/{state}/{locale}/{size}.png`
5. 与 golden 基准对比
6. 偏差超过阈值 → 失败
7. 截图作为阶段 Gate 证据

---

## 10. 安全与隐私不变量

全部阶段必须遵守 `XUXIA_DETAILED_DESIGN` §26 安全不变量：Key 仅存 Credential Manager、JSON 不含 Key、日志不含 Key、保存 fail-closed、Apply 前预检、Clear Workspace 不删 Undo、预算 fail-closed、诊断脱敏。

---

## 11. 30 章设计覆盖矩阵

| 设计章节 | 主责里程碑 | 覆盖任务 |
|----------|:---:|------|
| §1 文档权威性 | M0 | T00 计划自审 |
| §2 产品目标与非目标 | M0 | T01 架构审计 |
| §3 废止旧决策 | M0 | T01 审计确认 |
| §4 架构与模块边界 | M0 | T01–T04 |
| §5 统一数据流 | M2 | T02–T05 |
| §6 视觉系统与 Shell | M1 | T01–T06 |
| §7 Batch 空态 | M1 | T02–T04 |
| §8 Batch 非空工作区 | M1+M2 | M1: T05–T07, M2: T01–T08 |
| §9 内联编辑与验证 | M2 | T03–T04 |
| §10 Apply/Undo | M2 | T05–T08 |
| §11 Watch Folders | M5 | T01–T08 |
| §12 Templates | M4 | T01–T07 |
| §13 受控词表 | M4 | T08–T14 |
| §14 Preferences | M6 | T01–T06 |
| §15 Provider 设计 | M3 | T01–T06 |
| §16 质量模式 | M3 | T07–T08 |
| §17 图片/扫描件/视频 | M3 | T09–T12 |
| §18 非货币用量/ResourceGuard | M3/M5 | UsageRecorder + WatchResourceGuard |
| §19 缓存 | M3 | T16–T17 |
| §20 隐私设计 | M3+M6 | M3: T09–T12, M6: T05 |
| §21 国际化 | M0 | T03，各阶段持续 |
| §22 System Status | M7 | T01–T03 |
| §23 错误呈现 | M7 | T04–T06 |
| §24 数据恢复 | M7 | T07–T09 |
| §25 诊断包 | M7 | T10–T11 |
| §26 安全不变量 | M0 | T02，各阶段回归 |
| §27 Definition of Done | 全部 | 每阶段 Gate Report |
| §28 截图验收矩阵 | M1–M8 | 每阶段截图任务 |
| §29 测试策略 | M0 | T04 |
| §30 实施 Gate | M8 | T06 |

---

## 12. §28 验收矩阵映射

完整映射见各阶段文件中的 Screenshot Evidence 章节。总计覆盖 M1–M8 全部页面/状态的截图验收。零缺项。

---

## 13. 旧实现处理策略

| 模块 | 策略 | 阶段 |
|------|------|:---:|
| `src/config.py` | 复用 + schema 版本化 | M0 |
| `src/utils/credential_manager.py` | 复用（已验证） | M3 |
| `src/models/` | 审计 → 适配/新建 | M0→M2 |
| `src/core/ai_engine.py` | 适配 → Provider 架构 | M3 |
| `src/core/file_scanner.py` | 复用 | M2 |
| `src/core/content_extractor.py` | 复用 + 扩展多模态 | M3 |
| `src/core/rename_engine.py` | 适配为 RenamePlan 执行器 | M2 |
| `src/core/rename_history.py` | 适配为 UndoRecord 持久化 | M2 |
| `src/core/template_engine.py` | 适配为统一 Renderer | M4 |
| `src/providers/openai.py` / `claude.py` | 隔离，不暴露为首期预设 | M3 |
| `src/providers/deepseek.py` | 适配为 Provider 协议 | M3 |
| `src/ui/` (旧 QWidget) | 保留至 M8 Gate 切换后淘汰 | M8 |
| `tests/` (现有) | 保留，不退化 | 全部 |
| `acceptance_test.py` | 扩展（非重写） | M8 |

---

## 14. 风险登记表

| 风险 | 影响 | 缓解 |
|------|------|------|
| QML/Qt Quick 学习曲线 | 进度延迟 | M0 充分验证技术可行性 |
| 旧 UI 与新 UI 并行维护 | 代码膨胀 | M8 明确切换后淘汰旧代码 |
| Provider API 变化 | 集成失败 | 合约测试 + 官方文档核验 |
| 多模态实现复杂度 | 超出 M3 | M3 分拆图片/扫描/视频为独立子任务 |
| 截图自动化不稳定 | 假失败 | 确定性 fixture + 宽松阈值 |
| 资源护栏/缓存未经验证 | 队列或资源失控 | fail-closed + 小规模试运行 |

---

## 15. 自审结果

| 检查项 | 结果 |
|--------|:--:|
| 30 个设计章节全覆盖 | ✅ |
| §28 验收矩阵全部映射 | ✅ |
| 无 TBD/TODO/同上/略/以后实现/按需 | ✅ |
| 无双 Provider/DeepSeek 高级路由 | ✅ |
| 无 OpenAI/Anthropic 首期品牌预设 | ✅ |
| Qwen 仅推荐非强制 | ✅ |
| Watch 新建在内容区左侧固定宽卡片 | ✅ |
| 所有可见文案进入 i18n | ✅ |
| 所有 Apply 预检 + Undo | ✅ |
| Clear Workspace 不删 Undo | ✅ |
| 预算/凭据/诊断 fail-closed | ✅ |
| 无第三方品牌痕迹 | ✅ |

---

> **当前只是实施计划。任何产品功能均未因此变成"已实现"。**
>
> **下一步**: Product Owner 逐阶段审查并批准后，Claude Code 方可按序执行。
