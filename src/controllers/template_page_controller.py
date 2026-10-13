"""QML-facing controller for Templates and Controlled Vocabulary.

The controller contains presentation state only.  Template rendering, template
validation, persistence, vocabulary semantics, and AI-candidate decisions stay
in their existing domain services.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Property, Signal, Slot

from src.core.naming_fields import NamingFields
from src.core.template_model import (
    STANDARD_FIELDS,
    DateFormat,
    OrgMode,
    OutputLanguage,
    Separator,
    Template,
    TemplateField,
)
from src.core.template_renderer import TemplateRenderer
from src.core.template_presets import SCENARIO_PRESETS, PRESETS_BY_ID
from src.core.template_store import TemplateStore
from src.core.vocabulary import (
    VocabularyCategory,
    VocabularyEntry,
    VocabularySource,
    VocabularyStore,
)
from src.core.vocabulary_ai import VocabularyAIManager
from src.core.vocabulary_presets import get_general_presets


_SAMPLE_VALUES = {
    "dcDate": "2025-07-26",
    "dcTitle": "Quarterly Report",
    "dcSubject": "finance",
    "dcType": "report",
    "dcCreator": "Alex",
    "dcIdentifier": "DOC-2025-042",
    "extOrganization": "Xuxia",
    "extProject": "general",
    "extStatus": "final",
    "extVersion": "v1",
}


def _default_fields() -> tuple[TemplateField, ...]:
    return tuple(
        replace(field, enabled=field.dc_name in {"dcDate", "dcTitle"})
        for field in STANDARD_FIELDS
    )


BUILTIN_DEFAULT_NAME = "General Naming (Default)"
BUILTIN_DEFAULT_PATTERN = "{dcDate}_{dcTitle}"


class TemplatePageController(QObject):
    """Stable Qt boundary for the combined Templates/Vocabulary page."""

    stateChanged = Signal()

    def __init__(
        self,
        *,
        template_store: TemplateStore,
        vocabulary_store: VocabularyStore,
        vocabulary_manager: VocabularyAIManager | None = None,
        vocabulary_state_path: Path | None = None,
        locale: str = "en",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._template_store = template_store
        self._vocabulary_store = vocabulary_store
        self._vocabulary_state_path = (
            Path(vocabulary_state_path) if vocabulary_state_path is not None else None
        )
        self._error_message = ""
        if self._vocabulary_state_path is not None:
            try:
                self._vocabulary_store.load_state(self._vocabulary_state_path)
            except Exception as exc:
                # Keep the validated in-memory state and surface the load failure;
                # never replace it with partially parsed content.
                self._error_message = str(exc)
        self._vocabulary_manager = vocabulary_manager or VocabularyAIManager(
            vocabulary_store
        )
        self._locale = "zh" if locale.lower().startswith("zh") else "en"
        self._hong_kong = str(locale).lower().replace('_', '-') == 'zh-hk'
        self._active_tab = "templates"
        self._vocabulary_category = VocabularyCategory.SUBJECT
        self._vocabulary_query = ""
        self._vocabulary_source = "all"
        self._editor_open = False
        self._editor_mode = "create"
        self._editing_id = ""
        self._draft_name = ""
        self._draft_options: dict[str, str] = {}
        self._draft_fields: list[dict[str, Any]] = []
        self._preview_text = ""
        self._seed_domain_defaults()
        self._refresh_preview_from_template(self._template_store.list_all()[0])

    def get_template_for_analysis(self, template_id: str = ""):
        """Return the configured template for the non-QML naming pipeline."""
        if template_id:
            try:
                return self._template_store.get(template_id)
            except (KeyError, ValueError):
                pass
        templates = self._template_store.list_all()
        if not templates:
            raise RuntimeError("No naming template is configured")
        return templates[0]

    @property
    def vocabularyManager(self) -> VocabularyAIManager:
        return self._vocabulary_manager

    def _seed_domain_defaults(self) -> None:
        if not self._template_store.list_all():
            self._template_store.create(
                Template(
                    name=BUILTIN_DEFAULT_NAME,
                    pattern=BUILTIN_DEFAULT_PATTERN,
                    fields=_default_fields(),
                )
            )
        self._template_store.install_presets(tuple(preset.template() for preset in SCENARIO_PRESETS))
        existing_keys = {
            (entry.concept_id, entry.locale)
            for entry in self._vocabulary_store.list_all()
        }
        for entry in get_general_presets().entries:
            if (entry.concept_id, entry.locale) not in existing_keys:
                self._vocabulary_store.add_entry(entry)

    def _display_template_name(self, template: Template) -> str:
        from src.utils.i18n.hk_templates import DEFAULT_NAME, PRESET_LABELS
        preset = PRESETS_BY_ID.get(template.id)
        if preset and template == preset.template():
            if self._hong_kong:
                return PRESET_LABELS[preset.slug][0]
            return preset.chinese_name if self._locale == "zh" else preset.name
        is_builtin_default = (
            template.name == BUILTIN_DEFAULT_NAME
            and template.pattern == BUILTIN_DEFAULT_PATTERN
            and template.version == 1
        )
        if not is_builtin_default:
            return template.name
        if self._hong_kong:
            return DEFAULT_NAME
        return "通用命名（默认）" if self._locale == "zh" else BUILTIN_DEFAULT_NAME

    def _template_row(self, template: Template) -> dict[str, Any]:
        preset = PRESETS_BY_ID.get(template.id)
        unchanged = preset and template == preset.template()
        default = (template.name == BUILTIN_DEFAULT_NAME
                   and template.pattern == BUILTIN_DEFAULT_PATTERN and template.version == 1)
        if unchanged:
            description = preset.description_zh if self._locale == "zh" else preset.description_en
        elif default:
            description = "日常文件：日期＋标题；不确定选哪个时，先用这个。" if self._locale == "zh" else "Everyday files: date and title. Start here when unsure."
        else:
            description = "按当前字段规则命名；可编辑调整字段与顺序。" if self._locale == "zh" else "Uses your current naming fields; edit to change fields and order."
        sample = preset or SCENARIO_PRESETS[0]
        example = TemplateRenderer.render(template, sample.sample_fields(template), sample.extension).rendered_name
        if self._hong_kong:
            from src.utils.i18n.hk_templates import DEFAULT_DESCRIPTION, CUSTOM_DESCRIPTION, PRESET_LABELS
            description = PRESET_LABELS[preset.slug][1] if unchanged else (
                DEFAULT_DESCRIPTION if default else CUSTOM_DESCRIPTION)
        return {
            "id": template.id,
            "name": self._display_template_name(template),
            "pattern": template.pattern,
            "formula": template.pattern,
            "dateFormat": template.date_format.value,
            "separator": template.separator.value,
            "orgMode": template.org_mode.value,
            "outputLanguage": template.output_language.value,
            "version": template.version,
            "description": description,
            "example": example,
        }

    @staticmethod
    def _entry_row(entry: VocabularyEntry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "category": entry.category.value,
            "conceptId": entry.concept_id,
            "displayName": entry.display_name,
            "locale": entry.locale,
            "source": entry.source.value,
            "confidence": entry.confidence,
            "model": entry.created_by_model,
        }

    @Property("QVariantList", notify=stateChanged)
    def templates(self) -> list[dict[str, Any]]:
        return [self._template_row(item) for item in self._template_store.list_all()]

    @Property(int, notify=stateChanged)
    def templateCount(self) -> int:
        return len(self._template_store.list_all())

    @Property(str, notify=stateChanged)
    def activeTab(self) -> str:
        return self._active_tab

    @Property(bool, notify=stateChanged)
    def editorOpen(self) -> bool:
        return self._editor_open

    @Property(str, notify=stateChanged)
    def editorMode(self) -> str:
        return self._editor_mode

    @Property(str, notify=stateChanged)
    def draftName(self) -> str:
        return self._draft_name

    @Property("QVariantMap", notify=stateChanged)
    def draftOptions(self) -> dict[str, str]:
        return dict(self._draft_options)

    @Property("QVariantList", notify=stateChanged)
    def draftFields(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._draft_fields]

    @Property(str, notify=stateChanged)
    def previewText(self) -> str:
        return self._preview_text

    @Property(str, notify=stateChanged)
    def errorMessage(self) -> str:
        return self._error_message

    @Property(str, notify=stateChanged)
    def vocabularyCategory(self) -> str:
        return self._vocabulary_category.value

    @Property(str, notify=stateChanged)
    def vocabularyQuery(self) -> str:
        return self._vocabulary_query

    @Property(str, notify=stateChanged)
    def vocabularySource(self) -> str:
        return self._vocabulary_source

    @Property("QVariantList", notify=stateChanged)
    def allVocabularyEntries(self) -> list[dict[str, Any]]:
        return [self._entry_row(item) for item in self._vocabulary_store.list_all()]

    @Property(int, notify=stateChanged)
    def vocabularyCount(self) -> int:
        return len(self._vocabulary_store.list_all())

    @Property("QVariantList", notify=stateChanged)
    def vocabularyEntries(self) -> list[dict[str, Any]]:
        rows = [
            self._entry_row(item)
            for item in self._vocabulary_store.get_entries(
                self._vocabulary_category,
                self._locale,
                include_ai_suggestions=True,
            )
        ]
        query = self._vocabulary_query.casefold().strip()
        if query:
            rows = [
                row
                for row in rows
                if query in row["displayName"].casefold()
                or query in row["conceptId"].casefold()
            ]
        if self._vocabulary_source != "all":
            rows = [row for row in rows if row["source"] == self._vocabulary_source]
        return rows

    @Property("QVariantList", notify=stateChanged)
    def candidateEntries(self) -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "category": item.category.value,
                "conceptId": item.concept_id,
                "displayName": item.display_name,
                "locale": item.locale,
                "confidence": item.confidence,
                "model": item.source_model,
            }
            for item in self._vocabulary_manager.list_candidates(
                category=self._vocabulary_category,
                locale=self._locale,
            )
        ]

    @Property(int, notify=stateChanged)
    def candidateCount(self) -> int:
        return len(self.candidateEntries)

    @Slot()
    def refresh(self) -> None:
        self.stateChanged.emit()

    @Slot(str)
    def setLocale(self, locale: str) -> None:
        resolved = "zh" if str(locale).lower().replace("_", "-").startswith("zh") else "en"
        hong_kong = str(locale).lower().replace('_', '-') == 'zh-hk'
        if resolved != self._locale or hong_kong != self._hong_kong:
            self._locale = resolved
            self._hong_kong = hong_kong
            self.stateChanged.emit()

    @Slot(str)
    def setActiveTab(self, tab: str) -> None:
        if tab not in {"templates", "vocabulary"}:
            return
        self._active_tab = tab
        self._error_message = ""
        self.stateChanged.emit()

    def _begin_draft(self, template: Template | None) -> None:
        if template is None:
            fields = _default_fields()
            self._editor_mode = "create"
            self._editing_id = ""
            self._draft_name = ""
            options = {
                "dateFormat": DateFormat.YYYY_MM_DD.value,
                "separator": Separator.UNDERSCORE.value,
                "orgMode": OrgMode.FLAT.value,
                "outputLanguage": OutputLanguage.ZH.value,
            }
        else:
            fields = template.fields
            self._editor_mode = "edit"
            self._editing_id = template.id
            self._draft_name = self._display_template_name(template)
            options = {
                "dateFormat": template.date_format.value,
                "separator": template.separator.value,
                "orgMode": template.org_mode.value,
                "outputLanguage": template.output_language.value,
            }
        self._draft_options = options
        self._draft_fields = [
            {
                "id": field.id,
                "dcName": field.dc_name,
                "displayName": field.display_name,
                "enabled": field.enabled,
                "order": field.order,
            }
            for field in sorted(fields, key=lambda item: item.order)
        ]
        self._editor_open = True
        self._error_message = ""
        self._refresh_draft_preview()
        self.stateChanged.emit()

    @Slot()
    def beginCreateTemplate(self) -> None:
        self._begin_draft(None)

    @Slot(str)
    def beginEditTemplate(self, template_id: str) -> None:
        try:
            self._begin_draft(self._template_store.get(template_id))
        except Exception as exc:
            self._error_message = str(exc)
            self.stateChanged.emit()

    @Slot()
    def cancelDraft(self) -> None:
        self._editor_open = False
        self._error_message = ""
        self.stateChanged.emit()

    @Slot(str)
    def setDraftName(self, name: str) -> None:
        self._draft_name = name
        self._error_message = ""
        self.stateChanged.emit()

    @Slot(str, str)
    def setDraftOption(self, key: str, value: str) -> None:
        if key not in {"dateFormat", "separator", "orgMode", "outputLanguage"}:
            return
        self._draft_options[key] = value
        self._error_message = ""
        self._refresh_draft_preview()
        self.stateChanged.emit()

    @Slot(str, bool)
    def setDraftFieldEnabled(self, dc_name: str, enabled: bool) -> None:
        for item in self._draft_fields:
            if item["dcName"] == dc_name:
                item["enabled"] = enabled
                break
        self._error_message = ""
        self._refresh_draft_preview()
        self.stateChanged.emit()

    @Slot(str, int)
    def moveDraftField(self, dc_name: str, delta: int) -> None:
        index = next(
            (i for i, item in enumerate(self._draft_fields) if item["dcName"] == dc_name),
            -1,
        )
        target = index + delta
        if index < 0 or target < 0 or target >= len(self._draft_fields):
            return
        self._draft_fields[index], self._draft_fields[target] = (
            self._draft_fields[target],
            self._draft_fields[index],
        )
        for order, item in enumerate(self._draft_fields, start=1):
            item["order"] = order
        self._refresh_draft_preview()
        self.stateChanged.emit()

    def _draft_template(self) -> Template:
        enabled = [item for item in self._draft_fields if item["enabled"]]
        if not enabled:
            raise ValueError("At least one naming field must be enabled")
        separator = Separator(self._draft_options["separator"])
        pattern = separator.value.join(f"{{{item['dcName']}}}" for item in enabled)
        fields = tuple(
            TemplateField(
                id=item["id"],
                dc_name=item["dcName"],
                display_name=item["displayName"],
                enabled=item["enabled"],
                order=item["order"],
            )
            for item in self._draft_fields
        )
        return Template(
            id=self._editing_id or None,
            name=self._draft_name.strip() or "Untitled",
            pattern=pattern,
            date_format=DateFormat(self._draft_options["dateFormat"]),
            separator=separator,
            org_mode=OrgMode(self._draft_options["orgMode"]),
            output_language=OutputLanguage(self._draft_options["outputLanguage"]),
            fields=fields,
        )

    @staticmethod
    def _sample_fields(date_format: DateFormat) -> NamingFields:
        date_values = {
            DateFormat.YYYYMMDD: "20250726",
            DateFormat.YYYYMM: "202507",
            DateFormat.YYYY_MM_DD: "2025-07-26",
            DateFormat.YYYY_MM: "2025-07",
        }
        return NamingFields(**{**_SAMPLE_VALUES, "dcDate": date_values[date_format]})

    def _render_preview(self, template: Template) -> str:
        return TemplateRenderer.render(
            template,
            self._sample_fields(template.date_format),
            ".pdf",
        ).rendered_name

    def _refresh_draft_preview(self) -> None:
        try:
            self._preview_text = self._render_preview(self._draft_template())
        except Exception:
            self._preview_text = ""

    def _refresh_preview_from_template(self, template: Template) -> None:
        self._preview_text = self._render_preview(template)

    @Slot(result=bool)
    def saveDraft(self) -> bool:
        try:
            if not self._draft_name.strip():
                raise ValueError("Template name must not be empty")
            template = self._draft_template()
            if self._editor_mode == "edit":
                template = self._template_store.update(
                    self._editing_id,
                    name=template.name,
                    pattern=template.pattern,
                    date_format=template.date_format,
                    separator=template.separator,
                    org_mode=template.org_mode,
                    output_language=template.output_language,
                    fields=template.fields,
                )
            else:
                template = self._template_store.create(template)
            self._editor_open = False
            self._error_message = ""
            self._refresh_preview_from_template(template)
            self.stateChanged.emit()
            return True
        except Exception as exc:
            self._error_message = str(exc)
            self.stateChanged.emit()
            return False

    @Slot(str, result=bool)
    def deleteTemplate(self, template_id: str) -> bool:
        try:
            if self.templateCount <= 1:
                raise ValueError("At least one template must remain")
            self._template_store.delete(template_id)
            self._error_message = ""
            self.stateChanged.emit()
            return True
        except Exception as exc:
            self._error_message = str(exc)
            self.stateChanged.emit()
            return False

    def _mutate_vocabulary(self, action: Callable[[], Any]) -> Any:
        """Apply one vocabulary decision and durably save it as one transaction."""
        store_snapshot = self._vocabulary_store.snapshot()
        manager_snapshot = self._vocabulary_manager.snapshot()
        try:
            result = action()
            if self._vocabulary_state_path is not None:
                self._vocabulary_store.save_state(self._vocabulary_state_path)
            return result
        except Exception:
            self._vocabulary_store.restore_snapshot(store_snapshot)
            self._vocabulary_manager.restore_snapshot(manager_snapshot)
            raise

    @Slot(str)
    def setVocabularyCategory(self, category: str) -> None:
        try:
            self._vocabulary_category = VocabularyCategory(category)
            self._error_message = ""
        except ValueError:
            return
        self.stateChanged.emit()

    @Slot(str)
    def setVocabularyQuery(self, query: str) -> None:
        self._vocabulary_query = query
        self.stateChanged.emit()

    @Slot(str)
    def setVocabularySource(self, source: str) -> None:
        if source not in {"all", "system", "user", "ai_suggestion", "ai_auto"}:
            return
        self._vocabulary_source = source
        self.stateChanged.emit()

    @Slot(str, str, result=bool)
    def addVocabularyEntry(self, display_name: str, concept_id: str) -> bool:
        try:
            entry = VocabularyEntry(
                category=self._vocabulary_category,
                concept_id=concept_id.strip(),
                display_name=display_name.strip(),
                locale=self._locale,
                source=VocabularySource.USER,
            )
            self._mutate_vocabulary(lambda: self._vocabulary_store.add_entry(entry))
            self._error_message = ""
            self.stateChanged.emit()
            return True
        except Exception as exc:
            self._error_message = str(exc)
            self.stateChanged.emit()
            return False

    @Slot(str, str, result=bool)
    def overrideVocabularyEntry(self, entry_id: str, display_name: str) -> bool:
        try:
            self._mutate_vocabulary(
                lambda: self._vocabulary_store.override_entry(entry_id, display_name.strip())
            )
            self._error_message = ""
            self.stateChanged.emit()
            return True
        except Exception as exc:
            self._error_message = str(exc)
            self.stateChanged.emit()
            return False

    @Slot(str, result=bool)
    def deleteVocabularyEntry(self, entry_id: str) -> bool:
        try:
            original = self._vocabulary_store.get_entry(entry_id)
            if original.source == VocabularySource.SYSTEM:
                self._mutate_vocabulary(
                    lambda: self._vocabulary_store.tombstone_entry(entry_id)
                )
            else:
                self._mutate_vocabulary(
                    lambda: self._vocabulary_store.remove_entry(entry_id)
                )
            self._error_message = ""
            self.stateChanged.emit()
            return True
        except Exception as exc:
            self._error_message = str(exc)
            self.stateChanged.emit()
            return False

    @Slot(result=int)
    def restoreVocabularyCategory(self) -> int:
        try:
            restored = self._mutate_vocabulary(
                lambda: self._vocabulary_store.restore_category(self._vocabulary_category)
            )
            self._error_message = ""
            self.stateChanged.emit()
            return restored
        except Exception as exc:
            self._error_message = str(exc)
            self.stateChanged.emit()
            return 0

    @Slot(str, result=bool)
    def acceptCandidate(self, candidate_id: str) -> bool:
        return self._candidate_action(self._vocabulary_manager.accept, candidate_id)

    @Slot(str, str, result=bool)
    def modifyCandidate(self, candidate_id: str, display_name: str) -> bool:
        return self._candidate_action(
            self._vocabulary_manager.modify_and_accept,
            candidate_id,
            display_name,
        )

    @Slot(str, str, result=bool)
    def mapCandidate(self, candidate_id: str, entry_id: str) -> bool:
        return self._candidate_action(
            self._vocabulary_manager.map_to_existing,
            candidate_id,
            entry_id,
        )

    @Slot(str, result=bool)
    def useCandidateOnce(self, candidate_id: str) -> bool:
        return self._candidate_action(self._vocabulary_manager.use_once, candidate_id)

    @Slot(str, result=bool)
    def ignoreCandidate(self, candidate_id: str) -> bool:
        return self._candidate_action(self._vocabulary_manager.ignore, candidate_id)

    def _candidate_action(self, action, *args) -> bool:
        try:
            self._mutate_vocabulary(lambda: action(*args))
            self._error_message = ""
            self.stateChanged.emit()
            return True
        except Exception as exc:
            self._error_message = str(exc)
            self.stateChanged.emit()
            return False
