# 序匣产品仓库瘦身实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除旧 Qt Widgets 产品入口和可再生临时内容，重写当前产品 README，并保持正式 QML 产品、RC、手册、证据及其他 worktree 完整可用。

**Architecture:** 把旧 UI 当成一个完整、已退役的纵向切片删除，而不是逐文件留下半套回滚入口。同步调整只为旧 UI 存在的测试和验收段；当前产品继续通过 QML、集成、截图和打包 smoke 测试保障。

**Tech Stack:** Python 3.14、PySide6/QML、pytest、PowerShell、Git。

## Global Constraints

- 不删除 `.venv/`、`dist/`、正式 Golden、私有证据或任何 Git worktree。
- 不修改当前领域核心、Provider、多模态、Watch、Apply/Undo 或配置安全逻辑。
- 不 push，不改写历史。

---

### Task 1: 先建立当前入口的反回归契约

**Files:**
- Modify: `tests/packaging/test_packaged_app.py`
- Modify: `acceptance_test.py`

- [ ] 删除“legacy 回滚入口必须存在”的测试，改为断言正式入口仅委托 QML，旧模块/启动器/旧品牌脚本不存在。
- [ ] 将 `acceptance_test.py` 的旧 Qt Widgets 窗口创建段替换为 QML 正式入口的无真实凭据 smoke。
- [ ] 运行定向测试，确认在删除旧文件前“旧文件必须不存在”的契约先失败。

### Task 2: 删除旧产品纵向切片并重写 README

**Files:**
- Delete: `AI-文件夹整理程序.bat`
- Delete: `AI-文件夹整理程序.vbs`
- Delete: `legacy/run_legacy.bat`
- Delete: `src/main_legacy.py`
- Delete: `src/app.py`
- Delete: `src/ui/**`
- Delete: `tests/test_main_window_import.py`
- Delete: `tests/test_settings_dialog_fail_closed.py`
- Delete: `tests/unit/test_legacy_provider_isolation.py`
- Rewrite: `README.md`

- [ ] 删除精确文件清单，不触碰其他源码。
- [ ] README 只保留当前 QML 正式产品、RC、离线手册、开发测试与构建入口。
- [ ] 全仓搜索旧入口和旧品牌启动器，结果只允许出现在历史设计/实施文档中。

### Task 3: 清理可再生产物

**Files:**
- Remove ignored runtime/build directories only.

- [ ] 逐一验证目标绝对路径位于 `D:\文件AI-AGENT` 内。
- [ ] 删除 `build/`、`.pytest_cache/`、`__pycache__/`、`logs/`、`rename_history/`、`tests/screenshots/qa-current/` 和已确认空目录。
- [ ] 保留 `dist/`、`.venv/`、私有证据和所有 worktree。

### Task 4: 验证、提交与报告

**Files:**
- All modified/deleted files from Tasks 1–3.

- [ ] 运行完整 `pytest tests -q`，UPDATE_GOLDENS 关闭。
- [ ] 运行更新后的 `python acceptance_test.py`。
- [ ] 运行 `Xuxia.exe --smoke-test` 对应的打包测试与 `git diff --check`。
- [ ] 检查主工作树只有预期 tracked 变更，提交一次仓库瘦身 commit，不 push。
- [ ] 报告删除清单、保留清单、测试原始摘要和 Git 可恢复性。
