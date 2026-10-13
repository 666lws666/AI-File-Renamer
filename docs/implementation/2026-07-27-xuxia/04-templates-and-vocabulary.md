# M4: Templates & Controlled Vocabulary Implementation Plan

> 本计划供 Claude Code 在 Product Owner 明确批准后逐任务执行。当前编写计划不构成实施授权。

**Goal:** 实现模板系统（Dublin Core 字段、实时预览、CRUD）和受控词表（五类、预设、AI 候选、自动创建）。

**Architecture:** `TemplateEngine` (现有) 适配为统一 Renderer；`VocabularyStore` 管理五类词表持久化。UI 预览与正式渲染共用同一引擎。

**Tech Stack:** Python, JSON persistence, pytest

**Authority:** XUXIA_DETAILED_DESIGN §12 Templates, §13 Controlled Vocabulary, §21 i18n.

**Prerequisites:** M2 全部通过。

**Global Constraints:** 模板修改不丢失已有任务数据；词表版本进入缓存 key；词表 Undo 与文件 Undo 分离。

---

## Task 1: Template Domain Model

**Purpose:** 定义模板数据模型（Dublin Core 字段）。

**Files:**
- Create: `src/core/template_model.py`, `tests/unit/test_template_model.py`

**Interfaces:**
- Produces: `Template(id, name, pattern, date_format, separator, org_mode, output_language, fields: list[TemplateField], version)`
- Produces: `TemplateField(id, dc_name, display_name, enabled, order)`
- Produces: 10 个标准字段: dcDate, dcTitle, dcSubject, dcType, dcCreator, dcIdentifier, extOrganization, extProject, extStatus, extVersion

**Steps:**
- [ ] 编写 `test_template_default_pattern()` — 默认 `{dcDate}_{dcTitle}`
- [ ] 编写 `test_template_date_formats()` — YYYYMMDD/YYYYMM/YYYY-MM-DD/YYYY-MM
- [ ] 编写 `test_template_separators()` — underscore/hyphen
- [ ] 编写 `test_template_org_modes()` — flat/subject_tree/type_tree/project_tree
- [ ] 编写 `test_template_output_languages()` — zh/en/ja/es
- [ ] 实现 `Template`, `TemplateField`
- [ ] 运行: `pytest tests/unit/test_template_model.py -v`

**Commit:** `feat: add template domain model with Dublin Core fields`

---

## Task 2: Unified Template Renderer

**Purpose:** 实现 UI 预览和正式命名共用的渲染引擎。

**Files:**
- Create: `src/core/template_renderer.py`, `tests/unit/test_template_renderer.py`
- Modify: `src/core/template_engine.py` (适配)

**Interfaces:**
- Consumes: `Template`, `NamingFields`, `FileTask`
- Produces: `TemplateRenderer.render(template, fields, task) → TemplateRenderResult`
- Produces: `TemplateRenderResult(rendered_name, missing_fields, status: READY|NEEDS_REGENERATION|INVALID, errors, can_apply)` — 必需字段缺失时 status=NEEDS_REGENERATION, can_apply=false

**Steps:**
- [ ] 编写 `test_render_basic_pattern()` — `{dcDate}_{dcTitle}` → "2025-07-26_报告.pdf", status=READY
- [ ] 编写 `test_render_with_tree_org()` — subject_tree → "subject/2025-07-26_报告.pdf"
- [ ] 编写 `test_render_date_yyyymmdd()` — YYYYMMDD → "20250726_报告.pdf"
- [ ] 编写 `test_missing_required_field_returns_needs_regeneration()` — 必需字段缺失 → NEEDS_REGENERATION, can_apply=false
- [ ] 编写 `test_missing_field_result_cannot_apply()` — missing_fields 非空 → can_apply=false
- [ ] 编写 `test_invalid_field_returns_invalid()` — 字段值非法 → INVALID, can_apply=false
- [ ] 编写 `test_complete_fields_returns_ready()` — 全部必需字段齐全 → READY, can_apply=true
- [ ] 编写 `test_preview_and_execution_use_same_render_result()` — 预览与渲染一致
- [ ] 编写 `test_batch_blocks_apply_when_render_needs_regeneration()` — Batch 收到 NEEDS_REGENERATION 时阻止 Apply
- [ ] 实现 `TemplateRenderer` 和 `TemplateRenderResult`（适配现有 `template_engine.py`）
- [ ] 运行: `pytest tests/unit/test_template_renderer.py -v`

**Commit:** `feat: add unified template renderer`

---

## Task 3: Template CRUD & Persistence

**Purpose:** 模板创建、读取、更新、删除和 JSON 持久化。

**Files:**
- Create: `src/core/template_store.py`, `tests/unit/test_template_store.py`

**Steps:**
- [ ] 编写 `test_create_template()` — 新建 → 持久化
- [ ] 编写 `test_update_template_version()` — 修改 → version++
- [ ] 编写 `test_delete_unreferenced_template()` — 未被引用可删除
- [ ] 编写 `test_delete_referenced_template_requires_replacement()` — 被引用 → 必须指定替代
- [ ] 编写 `test_load_templates_on_startup()` — 启动加载
- [ ] 实现 `TemplateStore`
- [ ] 运行: `pytest tests/unit/test_template_store.py -v`

**Commit:** `feat: add template CRUD with persistence`

---

## Task 4: Template Change Impact

**Purpose:** 模板修改后判断既有任务的重新渲染/重新生成。

**Files:**
- Create: `src/core/template_impact.py`, `tests/unit/test_template_impact.py`

**Steps:**
- [ ] 编写 `test_field_sufficient_rerender_only()` — 字段齐全 → 仅重渲染预览
- [ ] 编写 `test_field_insufficient_mark_regenerate()` — 缺少字段 → 标记需重新 AI
- [ ] 编写 `test_applied_tasks_unaffected()` — 已应用任务不受模板变化影响
- [ ] 编写 `test_undo_records_unaffected()` — Undo 记录不受影响
- [ ] 实现 `TemplateImpactAnalyzer`
- [ ] 运行: `pytest tests/unit/test_template_impact.py -v`

**Commit:** `feat: add template change impact analysis`

---

## Task 5: Template QML UI

**Purpose:** 模板列表、创建、编辑 QML 页面。

**Files:**
- Create: `src/ui_qml/pages/TemplatesPage.qml`, `src/ui_qml/components/TemplateEditor.qml`, `src/ui_qml/components/FieldSorter.qml`
- Create: `src/controllers/template_page_controller.py`
- Test: `tests/qml/test_templates.py`

**Steps:**
- [ ] 编写组件测试: 字段拖动排序
- [ ] 编写组件测试: 实时预览更新
- [ ] 实现 TemplatesPage (列表 + 新建/编辑表单)
- [ ] 实现 FieldSorter (拖动排序)
- [ ] 实现 TemplateEditor (模式/日期/分隔符/组织/语言选择)
- [ ] 实现实时预览面板
- [ ] 截图: 模板列表、新建、编辑、字段排序、预览

**Commit:** `feat: add template QML UI with live preview`

---

## Task 6: Controlled Vocabulary Domain Model

**Purpose:** 实现五类受控词表的数据模型。

**Files:**
- Create: `src/core/vocabulary.py`, `tests/unit/test_vocabulary.py`

**Interfaces:**
- Produces: `VocabularyCategory(subject|organization|project|status|type)`
- Produces: `VocabularyEntry(id, category, concept_id, display_name, locale, source, confidence, created_by_model, created_at)`
- Produces: `VocabularyStore.get_entries(category, locale)`, `.add_entry()`, `.remove_entry()`

**Steps:**
- [ ] 编写 `test_five_categories_exist()` — 五类词表
- [ ] 编写 `test_entry_has_concept_id()` — 稳定概念 ID (如 `type.invoice`)
- [ ] 编写 `test_display_name_by_locale()` — 按 locale 返回显示名
- [ ] 编写 `test_entry_source_tracking()` — system/user/ai_suggestion/ai_auto
- [ ] 实现 `VocabularyEntry`, `VocabularyCategory`, `VocabularyStore`
- [ ] 运行: `pytest tests/unit/test_vocabulary.py -v`

**Commit:** `feat: add controlled vocabulary domain model`

---

## Task 7: Vocabulary Presets

**Purpose:** 创建 General 预设词表包。

**Files:**
- Create: `src/core/vocabulary_presets.py`, `tests/unit/test_vocabulary_presets.py`

**Steps:**
- [ ] 编写 `test_presets_loadable()` — 预设词表可加载
- [ ] 编写 `test_presets_include_subjects()` — personal/finance/legal/health/learning/research/travel/home
- [ ] 编写 `test_presets_include_types()` — invoice/receipt/statement/contract/proposal/report/presentation/meeting-note/minutes
- [ ] 编写 `test_presets_versioned()` — 预设含版本号, 用于缓存失效
- [ ] 实现预设 JSON 数据文件和加载器
- [ ] 运行: `pytest tests/unit/test_vocabulary_presets.py -v`

**Commit:** `feat: add general vocabulary preset pack`

---

## Task 8: User Vocabulary Override & Restore

**Purpose:** 用户覆盖预设词条并支持恢复。

**Files:**
- Modify: `src/core/vocabulary.py` (扩展), `tests/unit/test_vocabulary_override.py`

**Steps:**
- [ ] 编写 `test_edit_preset_entry()` — 编辑预设词条 → 创建用户覆盖
- [ ] 编写 `test_delete_preset_entry()` — 删除 → tombstone 标记
- [ ] 编写 `test_restore_single_entry()` — 恢复单个词条为预设值
- [ ] 编写 `test_restore_entire_category()` — 恢复整类为预设
- [ ] 编写 `test_user_override_persists_across_restart()` — 覆盖持久化
- [ ] 实现覆盖/tombstone 机制
- [ ] 运行: `pytest tests/unit/test_vocabulary_override.py -v`

**Commit:** `feat: add user vocabulary override and restore`

---

## Task 9: AI Vocabulary Suggestion

**Purpose:** AI 建议词条进入候选区。

**Files:**
- Create: `src/core/vocabulary_ai.py`, `tests/unit/test_vocabulary_ai.py`

**Steps:**
- [ ] 编写 `test_ai_suggestion_goes_to_candidate()` — AI 建议 → 候选区, 不直接入正式词表
- [ ] 编写 `test_accept_suggestion()` — 用户确认 → 正式词表
- [ ] 编写 `test_modify_then_accept()` — 修改后确认
- [ ] 编写 `test_map_to_existing()` — 映射到已有词条
- [ ] 编写 `test_use_once()` — 仅本次使用
- [ ] 编写 `test_ignore_suggestion()` — 忽略
- [ ] 实现 `VocabularyAIManager`
- [ ] 运行: `pytest tests/unit/test_vocabulary_ai.py -v`

**Commit:** `feat: add AI vocabulary suggestion with review workflow`

---

## Task 10: Auto-Create Vocabulary (Opt-in)

**Purpose:** 高置信度自动创建词条（非默认）。

**Files:**
- Modify: `src/core/vocabulary_ai.py` (扩展), `tests/unit/test_vocabulary_auto.py`

**Steps:**
- [ ] 编写 `test_auto_create_disabled_by_default()` — 默认不自动创建
- [ ] 编写 `test_opt_in_auto_create()` — 用户开启后高置信度词条自动添加
- [ ] 编写 `test_auto_create_requires_confidence_threshold()` — 低置信度不自动创建
- [ ] 编写 `test_auto_create_dedup()` — 重复词条不创建
- [ ] 编写 `test_auto_create_rate_limited()` — 频率限制
- [ ] 编写 `test_auto_create_audit_log()` — 记录来源/模型/时间/文件任务/置信度
- [ ] 实现自动创建逻辑（需用户主动开启）
- [ ] 实现 Watch Auto Apply 默认不扩展词表
- [ ] 运行: `pytest tests/unit/test_vocabulary_auto.py -v`

**Commit:** `feat: add opt-in auto vocabulary creation`

---

## Task 11: Vocabulary Undo

**Purpose:** 词条变更的独立 Undo（与文件 Undo 分离）。

**Files:**
- Create: `src/core/vocabulary_undo.py`, `tests/unit/test_vocabulary_undo.py`

**Steps:**
- [ ] 编写 `test_undo_add_entry()` — 撤销添加
- [ ] 编写 `test_undo_edit_entry()` — 撤销编辑
- [ ] 编写 `test_undo_delete_entry()` — 撤销删除 (恢复 tombstone)
- [ ] 编写 `test_vocab_undo_independent_of_file_undo()` — 两个 Undo 独立
- [ ] 实现 `VocabularyUndoManager`
- [ ] 运行: `pytest tests/unit/test_vocabulary_undo.py -v`

**Commit:** `feat: add vocabulary undo (independent of file undo)`

---

## Task 12: Vocabulary Tab in Templates Page

**Purpose:** 受控词表管理 UI，作为 Templates 页面内容区的第二个页签（与"模板"页签并列），不是独立主页面。不新增左侧导航入口，不创建独立 VocabularyPage。

**Files:**
- Create: `src/ui_qml/components/VocabTab.qml`, `src/ui_qml/components/VocabList.qml`, `src/ui_qml/components/VocabCandidatePanel.qml`
- Modify: `src/ui_qml/pages/TemplatesPage.qml` — 添加"模板"和"受控词表"两个页签
- Modify: `src/ui_qml/components/NavBar.qml` — 确认仍为 5 个导航入口
- Test: `tests/qml/test_vocabulary.py`

**Steps:**
- [ ] 编写测试: 五类词表 Tab 切换
- [ ] 编写测试: 筛选 (system/user/ai candidate)
- [ ] 编写测试: 候选区审核 (accept/modify/map/ignore)
- [ ] 实现 VocabularyPage
- [ ] 截图: 列表、编辑覆盖、候选审核、恢复预设、去重提示

**Commit:** `feat: add vocabulary QML UI`

---

## Task 13: Template-Vocabulary QML Integration

**Purpose:** 模板页面集成词表选择器。

**Files:**
- Modify: `src/ui_qml/pages/TemplatesPage.qml`
- Test: `tests/qml/test_template_vocab_integration.py`

**Steps:**
- [ ] 编写测试: 模板编辑器中字段下拉从词表填充
- [ ] 编写测试: 新增字段类型时显示可用词表分类
- [ ] 实现集成

**Commit:** `feat: integrate vocabulary into template editor`

---

## Task 14: Vocabulary CacheContextContributor

**Purpose:** VocabularyStore 实现 CacheContextContributor 协议，提供 vocabulary_version。M4 不修改 M3 的 CacheManager。

**Files:**
- Create: `tests/unit/test_vocabulary_cache_context.py`
- Modify: `src/core/vocabulary.py` — 实现 CacheContextContributor 协议

**Steps:**
- [ ] 编写 test_vocabulary_version_changes_on_add() — 新增词条 -> version 变化
- [ ] 编写 test_vocabulary_version_changes_on_edit() — 编辑词条 -> version 变化
- [ ] 编写 test_vocabulary_version_changes_on_delete() — 删除词条 -> version 变化
- [ ] 编写 test_vocabulary_version_changes_on_restore_default() — 恢复默认 -> version 变化
- [ ] 编写 test_vocabulary_version_stable_when_unchanged() — 未变化时版本稳定
- [ ] 实现 VocabularyStore 的 CacheContextContributor 接口
- [ ] M3/M4 集成测试：词表变化 -> 缓存失效（在两者均完成后执行）
- [ ] 运行: pytest tests/unit/test_vocabulary_cache_context.py -v

**Commit:** feat: add vocabulary cache context contributor
---

## M4 Gate Report Checklist

- [ ] 10 个 Dublin Core 字段 + 默认模板
- [ ] UI 预览与渲染引擎一致
- [ ] 模板 CRUD + 删除引用保护
- [ ] 字段齐全重渲染 vs 字段不足重新生成
- [ ] 五类词表 + General 预设
- [ ] 用户覆盖/恢复
- [ ] AI 候选审核工作流
- [ ] 可选自动创建 (默认关闭)
- [ ] 词表 Undo 独立
- [ ] 词表版本进缓存 key
- [ ] legacy baseline 214 + 本阶段全部新增测试通过

**自动化测试命令:**
```bash
pytest tests/unit/test_template_*.py tests/unit/test_vocabulary*.py -v
pytest tests/qml/test_templates.py tests/qml/test_vocabulary.py -v
pytest tests/
python acceptance_test.py
```

**Product Owner 批准栏:**
- [ ] M4 审查通过
- [ ] 批准进入 M5

> **未批准不得进入 M5。**
