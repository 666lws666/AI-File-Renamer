# 首页易用性 B：实现与验收

日期：2026-09-12。源码检查点：`b1c9dee`，分支 `feature/xuxia-m0-foundation`。本轮沿用用户批准的当前检出直接实施方式；不创建发布、不开新分支、不 push。

## 交付范围

- 80px 导航栏，5 个入口保留图标并新增常驻本地化名称；鼠标、Tab、Space、Return、Enter 均走原路由信号。
- Batch 工具栏为两行、144px 高；模板、文件保存位置、搜索、状态均有标签。关键操作在 900×640 和 1000×700 下保持完整文字、12px 字号和至少 32px 控件高度。
- 明示已选数量、当前显示/总数量；目标目录为空时说明在原目录重命名，有目标时可鼠标或键盘打开完整路径。弹窗只读、PlainText、可换行、Escape 关闭且不改变路径。
- 模板宽度固定 224px，长路径不再挤压模板名称。原导入语言选择、卡片、状态机、文件操作、Provider 与配置协议未修改。
- 跨页检查发现英文服务商名称被视频说明挤至 0px；仅将长视频能力说明放至第二行，恢复 Qwen 名称和操作可见性。未改能力判定或连接行为。
- 原有空态三步指引保留。

## 技能如何影响实现

使用已安装的 `ui-ux-pro-max`，采用其常驻导航标签、避免仅靠 hover、键盘可操作、紧凑控件保留完整含义、只读与编辑区分的指导。检索 `compact label overflow` 的 Compact Label Overflow 结果适用；导航查询两次未命中精确桌面规则，因此导航依据明确标为 `quick-reference.md` 的 `nav-label-icon` 通用规则，而非伪称检索命中。未把网页 CSS 或移动端 44pt 标准照搬进 Qt 桌面布局。

TDD：11 项首页测试先在旧界面失败；另有长路径挤压模板、英文服务商名称宽度为零的失败回归，再实施修复。独立只读审查未发现阻断缺陷；其两项证据建议（真实全选/搜索、按实际144px验证）均已落实。

## 原生视觉与交互

脚本：`scripts/capture_home_usability_b_native.py`。
证据：`tests/screenshots/qa-current/home-usability-b/manifest-{zh-CN,zh-HK,en-US}.json`。

- Windows QPA；三种语言 × 两种逻辑窗口尺寸 × 12 个场景 = 72 张 PNG。
- 场景包括空态、模板下拉、四个其他入口、设置滚动终点、完整路径、已选、搜索、筛选及应用进度。
- 全选、导航、筛选和应用使用真实 QTest 鼠标事件；搜索和路径弹窗使用键盘事件。每张记录尺寸、SHA-256、QML warnings；均为零 warning。
- Windows 125% 下实际截图为1250×875/1125×800；已实看简中/繁中/英文代表图、900px长路径、设置顶部/底部、混合与筛选队列，中文清晰，无关键按钮遮挡。
- 所有配置与目录为临时数据；Synthetic Mock 用于队列，实际生产控制器用于空态与路径验证。无真实 API、Key 或 Credential Manager 操作。

## 最终测试原始摘要

| 命令/检查 | 结果 |
|---|---|
| `.venv/Scripts/python.exe -m pytest tests/qml -q` | 296 passed |
| `.venv/Scripts/python.exe -m pytest tests/ --ignore=tests/screenshots -q --tb=short` | 1750 passed, 1 skipped |
| M1 完整文件，更新模式关闭（环境见下） | 49 passed |
| M0 完整文件，原 offscreen 环境 | 5 passed, 1 skipped |
| `.venv/Scripts/python.exe -m pytest tests/packaging -q` | 23 passed |
| `.venv/Scripts/python.exe acceptance_test.py` | Passed: 186/186; Failed: 0/186 |
| `scripts/build_windows.ps1` | exit 0 |
| 新 EXE `--smoke-test`，Windows QPA、隔离 data-dir | exit 0；ephemeral credentials；QML warning=0 |
| `git diff --check` | exit 0 |

非截图 skip 是既有 Windows symlink 条件；M0 skip 是更新模式测试。Pydantic/Pillow 弃用警告不是 QML runtime warning，未隐藏或删除。

## Golden 与 DPI

用户单独批准仅受控更新38张 M1 PNG，对应40个语义场景。M0与所有截图断言/容差均未改；更新后再次关闭更新模式完整运行。

当前显示器125%，旧 Golden 为100%像素尺寸。直接运行时先发现尺寸不一致；不能据此更新成125%图。已实测 Windows 进程 `QT_SCALE_FACTOR=0.8` 的 DPR=1、logical DPI=96，用此参数保持旧 M1 尺寸。M0 使用原 offscreen 环境，因此完整截图套件按两个文件分开运行，没有排除任何案例：

```powershell
$env:QT_SCALE_FACTOR='0.8'
Remove-Item Env:UPDATE_GOLDENS -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest tests/screenshots/test_m1_visuals.py -q
Remove-Item Env:QT_SCALE_FACTOR -ErrorAction SilentlyContinue
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest tests/screenshots/test_screenshot_infra.py -q
```

不要把0.8用于其他显示缩放；这是当前机器125%的进程级补偿，不改变 Windows 设置。M0 SHA-256 仍为 `6d5da0698d124d5f3dd255bae8ed7c34b76b10ad2c657c9014c073925d41a8b1`。M1受控变更通过 `git diff --numstat -- tests/screenshots` 核实为38张，无测试脚本变化。

## Windows 产物

- `dist/Xuxia/Xuxia.exe`：10,951,018 bytes。
- SHA-256：`B9B4BAFBCA209C9435D7BF0490158709A8C6A64B30887D48434DF0C1F4324E23`。
- 完整 onedir：3,081 文件，567,790,875 bytes。应用依赖 `_internal`，不要只搬动 EXE。
- 根目录既有 `序匣.lnk` 经只读确认指向此 EXE；未修改或提交用户快捷方式。
- Build 的可选 assetdownloader/tzdata 警告未阻止构建；23项打包检查和媒体 smoke 实际通过。

## 非阻断后续项

- 截图 harness 的跨显示缩放自动标准化可独立改进；当前有明确可复现环境，不以改变容差掩盖差异。
- 用户手册已有截图未在本轮重新拍摄；流程仍适用，导航及工具栏外观图可在下次文档维护更新。
- 非首页控件的一致性（例如旧数字步进器）不属于本轮 B，不扩展改造。

本轮不声称真实云端连接验收；测试不调用真实服务。没有 push 或公开发布。
