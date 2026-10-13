# 序匣有界精简实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 退休正式入口不再使用的历史执行链，减少重复媒体校验和状态映射，交付通过回归的本地候选，不改变用户当前试用版本。

**Architecture:** 保留正式的 managed Batch/Watch、文件操作与本地隐私链。旧实现的验收迁到正式模块；IPC 和对象校验共享严格校验逻辑；清理状态映射使用一个纯函数。

**Tech Stack:** Windows、Python 3.14.5、PySide6/Qt 6.12.0、pytest、PyInstaller；仅使用既有本地依赖。

## Global Constraints

- 同盘安全移动、目录链接拒绝、防覆盖、扩展名保护、身份及内容证据、部分 Apply/Undo、历史关联和回滚保持不变。
- 切换本地后阻止云端提交、本地失败不回退云端、AppContainer 零能力、进程树退出/句柄关闭证明、下载和处理分离保持不变。
- 不使用真实云端 API、真实 Key、真实 Credential Manager 或私密测试输入。
- 不改 QML、三语言文案、手册、正式 Golden、像素容差或截图断言。
- 不删功能测试来掩盖失败，不新增 skip/xfail，不改系统安全配置，不 push 或发布。
- 不改其他历史 worktree，不改写已有提交，不清理未知恢复证据。
- 当前主检出、已交付 EXE、模型资源、快捷方式和 GitHub 版本保留；在 `D:\文件AI-AGENT\.worktrees\code-simplification` 上顺序实施和提交。

## 验证运行合同

已有可信解释器：`D:\文件AI-AGENT\.worktrees\ai-smart-naming\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe`。

已有 PySide overlay：同一 `qt612-candidate\site`。每次调用设置 `PYTHONPATH` 为当前精简 worktree + 此 site；`TMP/TEMP` 为 `C:\Users\15413\.codex\visualizations\2026\07\26\019f9d36-6e1a-7fd1-89fa-46b48156f6da\local-privacy-final-test-temp`；`PYTHONIOENCODING=utf-8`、`PYTHONDONTWRITEBYTECODE=1`。移除 `UPDATE_GOLDENS` / `UPDATE_SCREENSHOT_GOLDEN`。

用已经检查的同目录 `run_guarded_pytest.py` 运行 pytest，用 `run_guarded_acceptance.py` 运行 acceptance。两者阻断真实网络与凭据访问，并使用临时用户数据目录。所有原始输出保存到当前 worktree 的 `tests/screenshots/qa-current/local-privacy/`；要求 return=0、forbidden access attempts=0。

完整非截图参数：`tests --ignore=tests/screenshots`。正式截图参数从 `git ls-files -- tests/screenshots/test_*.py` 获取目前两个完整文件，不递归收集被忽略的历史 QA 脚本。打包参数：`tests/packaging`。

### Task 1: 退休旧链并迁移验收

**Files:**
- Delete: `src/core/{ai_engine,rename_engine,template_engine,folder_watcher,organization_engine}.py`。
- Delete: `src/models/{template,watch_config}.py`。
- Delete: `src/providers/{base,deepseek,openai,claude}.py`。
- Modify: `src/models/__init__.py`、`src/providers/factory.py`、`src/core/rename_history.py`、`requirements.txt`、`acceptance_test.py`、`tests/unit/test_usage.py`、`tests/test_log_no_leak.py`。
- Create: `tests/unit/test_retired_execution_paths.py`。
- Record: private `.superpowers/sdd/task-1-report.md`，含旧到新验收映射。

**Interfaces:**
- Retain: `is_legacy_provider(provider_name: str) -> bool` 和 `LEGACY_PROVIDER_IDS`。
- Retain: `FileItem`、`RenameRecord`、`AppConfig` 公共导出和所有保存数据迁移。
- Use existing `TemplateRenderer.render(template, fields, extension)`、`RenameExecutor(preflight, history).execute(plans, batch_id)`、`UndoManager`、`WatchController` 与 `create_adapter(profile=..., credential=..., transport=...)`；不得再创建另一套业务实现。

- [x] **Step 1:** 添加退休路径门禁，首次运行应因旧文件仍存在而失败；再补真实正式模板/文件/Watch/Provider验收，不以构造类成功冒充功能通过。

```python
RETIRED = (
    "src/core/ai_engine.py", "src/core/rename_engine.py",
    "src/core/template_engine.py", "src/core/folder_watcher.py",
    "src/core/organization_engine.py", "src/models/template.py",
    "src/models/watch_config.py", "src/providers/base.py",
    "src/providers/deepseek.py", "src/providers/openai.py", "src/providers/claude.py",
)

def test_retired_execution_modules_are_absent():
    assert not [name for name in RETIRED if (ROOT / name).exists()]
```

用 AST/实际 import 确认退休模块无残留消费者，包括 `src/models/__init__.py`。该结构门禁只证明退休，不冒充功能测试。

- [x] **Step 2:** 在上述精确清单中用 apply_patch 删除旧模块，保留 factory 的纯历史 ID 判断，移除 models 的旧类导出。保持配置字段及读取代码完全不变。
- [x] **Step 2a:** 仅移除RenameHistory的旧`undo_batch`和`_rewrite_with_undone`；现存读取、逐记录原子标记、补偿操作逐字保留。新增门禁证明History不再包含直接文件移动API，正式UndoManager的成功/部分失败/关联/LIFO测试保持不变。

```python
"""Historical Provider IDs used by the current preset gate."""
LEGACY_PROVIDER_IDS = frozenset({"openai", "claude"})

def is_legacy_provider(provider_name: str) -> bool:
    return isinstance(provider_name, str) and provider_name.strip().casefold() in LEGACY_PROVIDER_IDS
```

- [x] **Step 3:** 将 acceptance 的旧模板/组织规则改为当前 Template/TemplateRenderer，覆盖准确日期、缺必需字段 NEEDS_REGENERATION、分隔符、扩展名、目录组织。旧 AI/mock 组装改为正式命名渲染和结果校验，明确不是真实模型语义验收。
- [x] **Step 4:** 旧 RenameEngine 验收改为原生 RenameExecutor + UndoManager 在临时合成副本上的 Apply/Undo：正确 task/batch关联、原始内容恢复、冲突不覆盖、错误扩展名拒绝。旧 Watch 验收用临时 WatchConfigStore + WatchController 及现有可注入 observer，验证配置 CRUD、启动/暂停/恢复/停止；禁止真实用户目录监控。
- [x] **Step 5:** 旧 Provider 工厂验收改为现有 preset + create_adapter + fake transport：官方预设构造、未知/历史品牌拒绝、缺凭据拒绝、不验证 profile 时业务调用拒绝；不连接网络。
- [x] **Step 5a:** 检查src/scripts/tests没有旧链之外的openai/anthropic/httpx真实导入后，删除requirements中三项闲置依赖声明；保留当前urllib transport、requests行为测试和所有其他依赖，不卸载既有环境包。新增依赖门禁证明正式源码不再需要上述SDK。
- [x] **Step 5b:** `tests/test_log_no_leak.py` 中直接读取退休deepseek.py的专项日志保护迁移到现存openai_compatible.py，覆盖api_key以及正式credential/_credential的片段日志；保留完整src sentinel/AST扫描及设置/凭据检查，不删除该安全测试或添加skip。正式Provider错误结果脱敏继续由现存动态transport/contract负向测试验证。
- [x] **Step 6:** 仅移除 test_usage 中五项退休 AIEngine 调用边界测试，及经引用核对只服务这五项的 `_FakeProvider` / `_make_file_item` helper；其他 UsageRecorder 测试逐字保留。在报告说明删除原因及现存对应 recorder 测试，不声称正式运行时原来没有接入的记录功能已完成。
- [x] **Step 7:** 定向运行 `tests/unit/test_retired_execution_paths.py tests/unit/test_usage.py tests/unit/test_template_renderer.py tests/unit/test_rename_executor.py tests/unit/test_undo_manager.py tests/providers/contracts`，再运行完整非截图套件。acceptance 需当前 worktree 本地同源 EXE 资源；先运行源代码迁移测试，最终候选构建后再完整验收。不得移除 GUI.windows_rc 断言来绕过缺失构建。
- [x] **Step 8:** diff-check、完整映射、自审并独立提交 `refactor: retire obsolete execution pipelines`。精确暂存文件，不包含私有 QA/ledger。不得 commit 未测试代码。

### Task 2: 去除媒体结果的二次完整协议往返

**Files:**
- Modify: `src/services/local_ai/preparation_protocol.py`、`src/core/batch_analysis.py`。
- Create: `tests/unit/test_local_preparation_validation.py`。
- Modify: `tests/integration/test_local_analysis_routing.py`。
- Record: private `.superpowers/sdd/task-2-report.md`。

**Interfaces:**
- Add: `validate_result(result: LocalPreparationResult, *, limits: LocalPreparationLimits | None = None, quality_mode: str | None = None) -> LocalPreparationResult`。
- Existing `encode_result` / `decode_result` 和子进程 stdout IPC 不变。
- `BatchAnalysisService._run_local` 使用对象 validator，不调用 `encode_result` / `decode_result` 做第二次完整二进制组装。

- [x] **Step 1:** 新增测试：合法结果与旧 roundtrip 完全相等；wrong quality / text / visual bytes / edge / pixels / page / frame / video duration 全部拒绝；被 object.__setattr__ 绕过冻结后的错误 text、visual descriptor/hash/signature、coverage、warnings、effective_quality 全部拒绝；记录首轮因新 validator 缺失的 RED。

```python
def test_validator_matches_wire_roundtrip(valid_result, limits):
    expected = decode_result(encode_result(valid_result), limits=limits, quality_mode="balanced")
    assert protocol.validate_result(valid_result, limits=limits, quality_mode="balanced") == expected
```

- [x] **Step 2:** 复用当前对象/覆盖/visual严格校验及调用方 limits，提取一个同源 validator。保留等效 MAX_HEADER_BYTES/MAX_FRAME_BYTES 和文本UTF-8上限；不得只验证 dataclass type，不放宽重复JSON key等IPC校验。减少的数据复制是图片帧拼接/拆分，不声称取消必要的摘要核验。
- [x] **Step 3:** 将 decoder 的同源 limits/quality逻辑交给 validator；在已有 managed LOCAL 分析测试里阻断二次 encoder/decoder 调用，证明仍通过 validator 后正确生成建议、超限仍拒绝。
- [x] **Step 4:** 定向运行 `tests/unit/test_local_preparation_validation.py tests/unit/test_local_preparation_protocol.py tests/unit/test_local_preparation_service.py tests/integration/test_local_analysis_routing.py`；不启动真实模型。
- [x] **Step 5:** diff-check、自审并独立提交 `refactor: validate prepared media without a second IPC roundtrip`。

### Task 3: 合并相同的本地推理状态映射

**Files:**
- Modify: `src/services/local_ai/inference_service.py`。
- Modify: `tests/unit/test_local_inference_service.py`。
- Record: private `.superpowers/sdd/task-3-report.md`。

**Interfaces:**
- Private pure helper `_cleanup_phase(error) -> str`，不暴露到UI或更改result模型。

- [x] **Step 1:** 先写 `_cleanup_phase` 的直接RED用例；补/保留当前错误分类行为测试，覆盖 `_Failure`、`LocalRequestError`、`HostCapacityError`、journal恢复错误、取消、StoreBusy、超时优先级与未知错误。新helper缺失必须真正失败。

```python
@pytest.mark.parametrize("error, phase", [
    ("RECOVERY_REQUIRED", "RECOVERY_REQUIRED"),
    ("CLEANUP_PENDING", "CLEANUP_PENDING"),
    (None, "CLEANUP_PENDING"),
])
def test_cleanup_phase(error, phase):
    assert service_module._cleanup_phase(error) == phase
```

- [x] **Step 2:** 合并仅相同的 isinstance 分类，并把三处相同映射改为helper，不移动任何清理操作或owner/journal/exception步骤。

```python
def _cleanup_phase(error):
    return "RECOVERY_REQUIRED" if error == "RECOVERY_REQUIRED" else "CLEANUP_PENDING"
```

- [x] **Step 3:** 定向运行 `tests/unit/test_local_inference_service.py tests/unit/test_local_inference_owner.py tests/unit/test_local_inference_journal.py`。
- [x] **Step 4:** diff-check、自审并独立提交 `refactor: share local inference failure state mappings`。

### Task 4: 最终 Gate 与候选交付

**Files:**
- Create: `docs/reports/2026-10-13-code-simplification.md`。
- Update checkboxes: 本计划。
- Outputs only: 当前 worktree 的 ignored `build/`、`dist/Xuxia/`、`tests/screenshots/qa-current/local-privacy/`。

**Interfaces:** 正式入口和PyInstaller spec完全不变；`src/main.py` 构建候选 `dist/Xuxia/Xuxia.exe`。

- [x] **Step 1:** 对三项任务做全分支独立审查；确定性P0/P1修复并补负向回归，其余记录，不扩大精简范围。
- [x] **Step 2:** 用既有解释器通过 `scripts/build_windows.ps1 -PythonPath <trusted interpreter>` 做干净构建（脚本调用 `python -m PyInstaller --noconfirm --clean packaging/xuxia.spec` 并管理Windows运行库PATH与手册资源），仅在隔离worktree产生新构建，不覆盖主目录产物。
- [x] **Step 3:** 在当前精简HEAD重新运行完整非截图pytest、两个正式截图文件（更新关闭）、完整acceptance和packaging测试，记录原始摘要与已知平台skip具体理由，不沿用旧数量。基线缺的runtime诊断fixture先从既有已验证固定runtime复制并核对，禁止把缺fixture的skip当安全验证通过。
- [x] **Step 4:** 运行候选EXE `--smoke-test --data-dir <explicit temporary directory> --report <ignored QA json>`，按main_qml实际argparse精确参数执行。检查退出0、QML warning0、临时凭据后端及媒体/诊断结果，记录SHA256/大小/完整产物数量。不运行真实模型、不宣称命名语义重新验收。
- [x] **Step 5:** 确认Golden tree与1155一致；主检出HEAD、EXE SHA和shortcut目标不变；diff-check/trackedclean。统计 `git diff --numstat 1155 HEAD -- src` 及文件数，区分新增功能测试与退休接口测试，不夸大速度/体积收益。
- [x] **Step 6:** 完成报告与检查清单，独立docs提交。保留候选分支/worktree和原版本，不自动合并、push或发布；交付简明结果和回滚基线。
