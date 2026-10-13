# 序匣产品仓库瘦身设计

## 目标

让 `D:\文件AI-AGENT` 只向普通使用者呈现当前序匣 1.0.0 的正式入口、离线手册与 Windows RC，移除会误导用户启动旧 Qt Widgets 产品或阅读旧开发说明的内容，同时保留可审计历史、构建环境和其他尚未收口的 Git worktree。

## 删除范围

### 已跟踪的过时产品入口

- `AI-文件夹整理程序.bat`
- `AI-文件夹整理程序.vbs`
- `legacy/run_legacy.bat`
- `src/main_legacy.py`
- `src/app.py`
- `src/ui/` 全目录

这些文件仅服务于旧 Qt Widgets 界面。正式入口已经是 `src.main -> src.main_qml`，Windows RC 已由 `Xuxia.exe` 承担。

### 旧入口专属测试

- `tests/test_main_window_import.py`
- `tests/test_settings_dialog_fail_closed.py`
- `tests/unit/test_legacy_provider_isolation.py`
- `acceptance_test.py` 中旧 Qt Widgets 窗口创建段
- `tests/packaging/test_packaged_app.py` 中“必须保留 legacy 回滚入口”的契约

删除后，验收套件仍保留模型、配置、扫描、提取、模板、历史、文件安全、Provider、Watch 和端到端管线验证；QML 正式入口由现有 QML、集成、截图和打包 smoke 测试覆盖。

### 可再生或运行期临时内容

- `build/`
- `.pytest_cache/`
- 全仓 `__pycache__/`
- `logs/`
- `rename_history/`
- `tests/screenshots/qa-current/`
- 已确认为空的 `config/templates/`、实施 evidence 空目录和旧 QML components 空目录

## 改写范围

`README.md` 改为当前产品首页：

- 用户入口只指向 `dist/Xuxia/Xuxia.exe` 与 `序匣用户手册.html`；
- 开发入口只保留 `run.bat` / `python -m src.main`；
- 描述单一当前 Provider、当前多模态、非货币资源护栏和正式 QML UI；
- 不再显示“旧 UI”“尚未实现多模态”“DeepSeek+Qwen 双路由”或开发者安装步骤作为普通用户指南。

## 明确保留

- `.venv/`：测试与构建环境；
- `dist/`：当前 Windows RC；
- `docs/reference-evidence/`：私有交接与恢复证据；
- `docs/implementation/`、产品规格和决策文档：历史审计记录；
- `.worktrees/`、`.claude/worktrees/`：其他独立 Git 工作树；
- 正式 Golden 与视觉测试基础设施；
- 当前核心、Provider 兼容层、配置迁移和安全测试。

## 验收

1. 全仓不再存在旧 Qt Widgets UI、legacy 启动入口或旧品牌启动器。
2. `README.md` 只描述当前正式产品与入口。
3. `python -m src.main --version`、QML 测试、完整 `pytest tests`、截图测试、更新后的 `acceptance_test.py` 和 Windows RC smoke 全部通过。
4. `序匣用户手册.html`、`dist/Xuxia/Xuxia.exe`、`.venv`、私有证据和其他 worktree 不受影响。
5. 不 push，不删除 Git 历史；所有已跟踪删除均可通过 Git 恢复。
