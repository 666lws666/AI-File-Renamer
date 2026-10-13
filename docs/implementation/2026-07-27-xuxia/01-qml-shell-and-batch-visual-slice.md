# M1: QML Shell & Batch Visual Slice Implementation Plan

> 本计划供 Claude Code 在 Product Owner 明确批准后逐任务执行。当前编写计划不构成实施授权。

**Goal:** 交付序匣 QML Shell（自定义窗口、左侧导航、页面路由）和 Batch 页面的完整视觉切片，全部使用 mock 数据，不调用 AI 或文件系统。

**Architecture:** `src/ui_qml/main.qml` 作为新 Shell 入口（与旧 `src/app.py` 并行）。Batch 页面内所有数据来自确定性 mock controller，无网络或磁盘副作用。

**Tech Stack:** PySide6 QML/Qt Quick, Qt Quick Controls, Qt Quick Layouts, SVG icons

**Authority:** XUXIA_DETAILED_DESIGN §6 Visual System, §7 Batch Empty, §8 Batch Non-Empty, §21 i18n.

**Prerequisites:** M0 全部通过。

**Global Constraints:** Shell: 1000×700 基准, 900×640 最小, 32px 标题栏, 48px 左侧导航, 无 QMenuBar/QToolBar/QStatusBar/QTableView。Batch: 全宽任务卡片队列, 68–72px 卡片。i18n 所有可见文案。不写文件。

---

## Task 1: Custom Window Shell

**Purpose:** 实现无系统标题栏的自定义窗口框架。

**Files:**
- Create: `src/ui_qml/Shell.qml`, `src/ui_qml/TitleBar.qml`, `src/ui_qml/NavBar.qml`
- Modify: `src/ui_qml/main.qml`
- Test: `tests/qml/test_shell.py`
- Assets: `src/ui_qml/icons/nav_*.svg` (5 个 SVG)

**Interfaces:**
- Consumes: (none)
- Produces: `Shell` — 自定义窗口容器, `TitleBar` — 32px 标题栏, `NavBar` — 48px 左侧图标栏
- Events: `pageChanged(page: string)`, `windowStateChanged(state: int)`

**Steps:**
- [ ] 编写 QML 组件测试: Shell 渲染后尺寸 ≥ 900×640
- [ ] 编写测试: TitleBar 高度 = 32px, NavBar 宽度 = 48px
- [ ] 编写测试: 窗口状态按钮（最小化/最大化/关闭）触发预期信号
- [ ] 实现 `Shell.qml`: 无边框窗口 + 自定义标题栏 + 内容区
- [ ] 实现 `TitleBar.qml`: 拖拽移动, 最小化/最大化/关闭按钮
- [ ] 实现 `NavBar.qml`: 5 图标（Batch/Watch/Templates 顶, Status/Preferences 底）
- [ ] 截图: `m1/shell/default/zh_CN/1000x700.png`
- [ ] 截图: `m1/shell/default/en_US/1000x700.png`
- [ ] 截图: `m1/shell/min_size/zh_CN/900x640.png`

**Verification:** 窗口可拖拽、缩放；按钮功能正常；截图几何尺寸精确。

**Commit:** `feat: add custom window shell with nav bar`

---

## Task 2: Page Router & Navigation State

**Purpose:** 实现页面切换路由和导航选中态。

**Files:**
- Create: `src/ui_qml/PageRouter.qml`, `src/ui_qml/pages/DeferredPage.qml`
- Modify: `src/ui_qml/NavBar.qml`
- Test: `tests/qml/test_navigation.py`

**Interfaces:**
- Consumes: `NavBar.pageChanged`
- Produces: `PageRouter` — StackView 封装, `currentPage: string`
- Events: `pageChanging(from, to)`, `pageChanged(page)`

**Steps:**
- [ ] 编写测试: 点击 Batch 图标 → `pageChanged("batch")`
- [ ] 编写测试: 点击 Watch → `pageChanged("watch")`
- [ ] 编写测试: 当前页图标浅灰圆角底高亮
- [ ] 实现 NavBar 点击信号 + 选中态样式
- [ ] 实现 PageRouter (StackView)：Batch 路由进入真实 Batch 页面；Watch/Templates/Status/Preferences 四页路由在 M1 返回 `DeferredPage`（development-only 脚手架，明确标记 `developmentScaffold: true`，使用 i18n 文案显示该页属于后续里程碑，不计入 Watch/Templates/Status/Preferences DoD，不进入正式截图验收，分别由 M5/M4/M7/M6 替换）
- [ ] 截图: 每种导航选中态

**Verification:** 点击各图标切换页面，选中态视觉正确。

**Commit:** `feat: add page router with navigation state`

---

## Task 3: Batch Empty State

**Purpose:** 实现 Batch 页面空态：顶部工具栏 + 中央拖放区。

**Files:**
- Create: `src/ui_qml/pages/BatchPage.qml`, `src/ui_qml/components/BatchToolbar.qml`, `src/ui_qml/components/DropZone.qml`
- Test: `tests/qml/test_batch_empty.py`

**Steps:**
- [ ] 编写测试: 空态渲染模板选择下拉、添加文件/文件夹按钮、搜索框、状态筛选
- [ ] 编写测试: DropZone 接受文件拖放事件
- [ ] 编写测试: Provider/连接状态指示可见
- [ ] 实现 `BatchToolbar.qml`: 单行操作区
- [ ] 实现 `DropZone.qml`: 中央拖放区 + 支持格式列表
- [ ] 实现 `BatchPage.qml` 空态组合
- [ ] i18n: 所有文案使用 `I18n.tr()`
- [ ] 截图: `m1/batch/empty/zh_CN/1000x700.png`
- [ ] 截图: `m1/batch/empty/en_US/1000x700.png`

**Verification:** 拖放区接受文件事件（mock）；工具栏所有控件可用。

**Commit:** `feat: add batch empty state with drop zone`

---

## Task 4: Batch Task Card Component

**Purpose:** 实现单张任务卡片的完整视觉。

**Files:**
- Create: `src/ui_qml/components/TaskCard.qml`
- Test: `tests/qml/test_task_card.py`

**Interfaces:**
- Consumes: mock `FileTask` data (确定性 fixture)
- Produces: `TaskCard` — 复选框, 状态图标, 缩略图, 建议名, 原名
- Events: `checkedChanged`, `cardClicked`, `applyRequested`

**Steps:**
- [ ] 编写测试: 卡片高度 68–72px
- [ ] 编写测试: 八种状态各自渲染正确的图标和颜色
- [ ] 编写测试: hover 显示操作按钮, 离开隐藏
- [ ] 编写测试: 三态主复选框（全选/部分/全不选）
- [ ] 编写测试: 选中 N 项显示 "已选中 N 项" 提示
- [ ] 实现 `TaskCard.qml` 带 mock 数据绑定
- [ ] 截图: 每种状态的单张卡片 (8 张)
- [ ] 截图: hover 态卡片

**Verification:** 所有八状态视觉正确，hover 显示操作，复选框三态。

**Commit:** `feat: add batch task card component`

---

## Task 5: Batch Non-Empty Queue

**Purpose:** 组合全宽滚动任务卡片队列。

**Files:**
- Modify: `src/ui_qml/pages/BatchPage.qml` — 添加非空态
- Create: `src/ui_qml/components/TaskQueue.qml`
- Test: `tests/qml/test_batch_nonempty.py`

**Steps:**
- [ ] 编写测试: 10 张卡片渲染在可滚动 ListView 中
- [ ] 编写测试: 搜索过滤（输入 "报告" → 仅显示匹配卡片）
- [ ] 编写测试: 状态筛选（选择 "失败" → 仅显示失败卡片）
- [ ] 编写测试: 多选 + 主复选框三态联动
- [ ] 实现 `TaskQueue.qml`: ListView + 虚拟化
- [ ] 实现搜索和筛选逻辑（mock controller）
- [ ] 截图: 混合状态队列 `m1/batch/nonempty/mixed/zh_CN/1000x700.png`
- [ ] 截图: 每种筛选态 (9 张)

**Verification:** 滚动流畅，筛选正确，选择状态与工具栏联动。

**Commit:** `feat: add batch non-empty task queue`

---

## Task 6: Inline Edit & Apply Progress

**Purpose:** 实现内联编辑和 Apply 独立进度指示。

**Files:**
- Create: `src/ui_qml/components/InlineEdit.qml`, `src/ui_qml/components/ApplyProgress.qml`
- Modify: `src/ui_qml/components/TaskCard.qml`
- Test: `tests/qml/test_inline_edit.py`, `tests/qml/test_apply_progress.py`

**Steps:**
- [ ] 编写测试: 双击建议名进入编辑模式，Esc 取消恢复原名
- [ ] 编写测试: Enter 保存编辑值，扩展名不可编辑
- [ ] 编写测试: 非法字符就地显示错误
- [ ] 编写测试: Apply 进度条 0→100% 动画
- [ ] 编写测试: 进度条显示 "3/10 已完成"
- [ ] 实现 `InlineEdit.qml`: 编辑/确认/取消三态
- [ ] 实现 `ApplyProgress.qml`: 确定进度条
- [ ] 截图: inline edit 编辑态 + 错误态
- [ ] 截图: Apply 进度 50%

**Verification:** 编辑取消恢复原名，非法字符被拦截，进度条显示正确。

**Commit:** `feat: add inline edit and apply progress`

---

## Task 7: Mock Data Controller

**Purpose:** 为 M1 所有视觉测试提供确定性 mock 数据。

**Files:**
- Create: `src/controllers/mock_batch_controller.py`
- Create: `tests/qml/fixtures.py`
- Test: `tests/qml/test_with_mock_data.py`

**Interfaces:**
- Produces: `MockBatchController` — 提供 `tasks: list[dict]`, `filter(state)`, `search(query)`, `selection_model`
- Consumed by: 所有 QML 测试使用统一 fixture

**Steps:**
- [ ] 创建 `MockBatchController` 类：预生成 20 个覆盖八种状态的确定性任务
- [ ] 创建 `tests/qml/fixtures.py`: pytest fixture 注入 mock controller
- [ ] 重写之前 QML 测试使用 mock fixture
- [ ] 验证全部 20 个任务状态正确渲染
- [ ] 运行: `pytest tests/qml/ -v`

**Verification:** 所有 QML 测试使用统一 mock 数据，无随机值。

**Commit:** `feat: add mock data controller for QML testing`

---

## M1 Gate Report Checklist

- [ ] Shell 1000×700 + 900×640 截图
- [ ] 导航 5 图标 + 选中态截图
- [ ] Batch 空态 zh_CN + en_US 截图
- [ ] 8 种状态单卡截图
- [ ] 混合队列 + 9 种筛选截图
- [ ] inline edit / Apply 进度截图
- [ ] zh_CN + en_US 双语言截图
- [ ] 无 QTableView/QMenuBar/QToolBar/QStatusBar
- [ ] 无真实 AI 调用
- [ ] 无文件写入
- [ ] 全部 QML 测试通过（含 DeferredPage 脚手架测试）
- [ ] legacy baseline 214 + 本阶段全部新增测试通过
- [ ] i18n 所有可见文案使用 `I18n.tr()`
- [ ] 五个导航入口存在；Batch 路由进入真实页面；其余四页为 DeferredPage
- [ ] DeferredPage 标记 `developmentScaffold: true`，不计入 Watch/Templates/Status/Preferences DoD
- [ ] M1 Gate 仅批准 Shell 和 Batch 视觉切片

**自动化测试命令:**
```bash
pytest tests/qml/ -v
pytest tests/
python acceptance_test.py
```

**Placeholder 分类:**
1. 禁止的内容占位（TBD/TODO/同上/略/见上版/伪完成）: **0**
2. 合法的运行时插值（i18n `{name}` 占位符、模板字段表达式）: 不属于缺失内容
3. 开发脚手架: `DeferredPage` — 四页（Watch→M5, Templates→M4, Status→M7, Preferences→M6），development-only, 不计入 DoD, 不进入正式截图

**Product Owner 批准栏:**
- [ ] M1 审查通过（视觉截图对照验收）
- [ ] 批准进入 M2

> **未批准不得进入 M2。**
