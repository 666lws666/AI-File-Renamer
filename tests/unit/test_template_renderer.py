"""Tests for Unified Template Renderer — preview and formal render share one path."""

import pytest
from src.core.template_model import (
    Template, TemplateField, DateFormat, Separator, OrgMode, OutputLanguage,
)
from src.core.naming_fields import NamingFields
from src.core.template_renderer import (
    TemplateRenderer,
    TemplateRenderResult,
    RenderStatus,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_template(**kwargs) -> Template:
    defaults = dict(
        name="Test",
        pattern="{dcDate}_{dcTitle}",
        date_format=DateFormat.YYYY_MM_DD,
        separator=Separator.UNDERSCORE,
        org_mode=OrgMode.FLAT,
        output_language=OutputLanguage.ZH,
        fields=[
            TemplateField(dc_name="dcDate", display_name="Date", order=1),
            TemplateField(dc_name="dcTitle", display_name="Title", order=2),
        ],
    )
    defaults.update(kwargs)
    return Template(**defaults)


# ── Basic rendering ──────────────────────────────────────────────────────────

class TestBasicPatternRendering:
    def test_basic_pattern_renders_correctly(self):
        t = make_template(pattern="{dcDate}_{dcTitle}")
        fields = NamingFields(dcDate="2025-07-26", dcTitle="报告")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.rendered_name == "2025-07-26_报告.pdf"
        assert result.status == RenderStatus.READY
        assert result.can_apply is True
        assert len(result.missing_fields) == 0
        assert len(result.errors) == 0

    def test_basic_pattern_yyyymmdd(self):
        t = make_template(pattern="{dcDate}_{dcTitle}", date_format=DateFormat.YYYYMMDD)
        fields = NamingFields(dcDate="20250726", dcTitle="报告")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.rendered_name == "20250726_报告.pdf"
        assert result.status == RenderStatus.READY

    def test_render_with_hyphen_separator(self):
        t = make_template(pattern="{dcDate}_{dcTitle}", separator=Separator.HYPHEN)
        fields = NamingFields(dcDate="2025-07-26", dcTitle="报告")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.rendered_name == "2025-07-26-报告.pdf"
        assert result.status == RenderStatus.READY

    def test_render_with_custom_pattern(self):
        t = make_template(
            pattern="{dcDate}_{dcTitle}_{extStatus}",
            fields=[
                TemplateField(dc_name="dcDate", display_name="Date", order=1),
                TemplateField(dc_name="dcTitle", display_name="Title", order=2),
                TemplateField(dc_name="extStatus", display_name="Status", order=3),
            ],
        )
        fields = NamingFields(dcDate="2025-07-26", dcTitle="报告", extStatus="final")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.rendered_name == "2025-07-26_报告_final.pdf"
        assert result.status == RenderStatus.READY


# ── Date format rendering ────────────────────────────────────────────────────

class TestDateFormatRendering:
    def test_yyyymmdd_format(self):
        t = make_template(date_format=DateFormat.YYYYMMDD)
        fields = NamingFields(dcDate="20250726", dcTitle="Doc")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert "20250726" in result.rendered_name

    def test_yyyymm_format(self):
        t = make_template(date_format=DateFormat.YYYYMM)
        fields = NamingFields(dcDate="202507", dcTitle="Doc")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert "202507" in result.rendered_name

    def test_yyyy_mm_dd_format(self):
        t = make_template(date_format=DateFormat.YYYY_MM_DD)
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert "2025-07-26" in result.rendered_name

    def test_yyyy_mm_format(self):
        t = make_template(date_format=DateFormat.YYYY_MM)
        fields = NamingFields(dcDate="2025-07", dcTitle="Doc")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert "2025-07" in result.rendered_name


# ── Organization mode — path safety ──────────────────────────────────────────

class TestOrgModeRendering:
    def test_flat_no_prefix(self):
        t = make_template(org_mode=OrgMode.FLAT)
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert "/" not in result.rendered_name
        assert "\\" not in result.rendered_name

    def test_subject_tree_prefix(self):
        t = make_template(
            org_mode=OrgMode.SUBJECT_TREE,
            fields=[
                TemplateField(dc_name="dcDate", display_name="Date", order=1),
                TemplateField(dc_name="dcTitle", display_name="Title", order=2),
                TemplateField(dc_name="dcSubject", display_name="Subject", order=3),
            ],
        )
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc", dcSubject="finance")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.rendered_name.startswith("finance/")
        assert ".." not in result.rendered_name

    def test_subject_tree_missing_subject_uses_default(self):
        t = make_template(
            org_mode=OrgMode.SUBJECT_TREE,
            fields=[
                TemplateField(dc_name="dcDate", display_name="Date", order=1),
                TemplateField(dc_name="dcTitle", display_name="Title", order=2),
                TemplateField(dc_name="dcSubject", display_name="Subject", order=3),
            ],
        )
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc")
        result = TemplateRenderer.render(t, fields, ".pdf")
        # Should still render with a default category
        assert result.status == RenderStatus.READY

    def test_type_tree_prefix(self):
        t = make_template(
            org_mode=OrgMode.TYPE_TREE,
            fields=[
                TemplateField(dc_name="dcDate", display_name="Date", order=1),
                TemplateField(dc_name="dcTitle", display_name="Title", order=2),
                TemplateField(dc_name="dcType", display_name="Type", order=3),
            ],
        )
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc", dcType="invoice")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.rendered_name.startswith("invoice/")

    def test_project_tree_prefix(self):
        t = make_template(
            org_mode=OrgMode.PROJECT_TREE,
            fields=[
                TemplateField(dc_name="dcDate", display_name="Date", order=1),
                TemplateField(dc_name="dcTitle", display_name="Title", order=2),
                TemplateField(dc_name="extProject", display_name="Project", order=3),
            ],
        )
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc", extProject="xuxia")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.rendered_name.startswith("xuxia/")


# ── Path safety ──────────────────────────────────────────────────────────────

class TestPathSafety:
    def test_subject_tree_rejects_absolute_path_in_value(self):
        t = make_template(
            org_mode=OrgMode.SUBJECT_TREE,
            fields=[
                TemplateField(dc_name="dcDate", display_name="Date", order=1),
                TemplateField(dc_name="dcTitle", display_name="Title", order=2),
                TemplateField(dc_name="dcSubject", display_name="Subject", order=3),
            ],
        )
        # Subject value tries path traversal
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc", dcSubject="../escape")
        result = TemplateRenderer.render(t, fields, ".pdf")
        # Must sanitize the path component
        assert ".." not in result.rendered_name

    def test_subject_tree_rejects_drive_letter(self):
        t = make_template(
            org_mode=OrgMode.SUBJECT_TREE,
            fields=[
                TemplateField(dc_name="dcDate", display_name="Date", order=1),
                TemplateField(dc_name="dcTitle", display_name="Title", order=2),
                TemplateField(dc_name="dcSubject", display_name="Subject", order=3),
            ],
        )
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc", dcSubject="C:evil")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert ":" not in result.rendered_name.split("/")[-1]
        # Drive letter should be sanitized out
        assert "C:" not in result.rendered_name

    def test_project_tree_no_path_escape(self):
        t = make_template(
            org_mode=OrgMode.PROJECT_TREE,
            fields=[
                TemplateField(dc_name="dcDate", display_name="Date", order=1),
                TemplateField(dc_name="dcTitle", display_name="Title", order=2),
                TemplateField(dc_name="extProject", display_name="Project", order=3),
            ],
        )
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc", extProject="..\\..\\windows")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert ".." not in result.rendered_name


# ── Missing required fields ──────────────────────────────────────────────────

class TestMissingRequiredFields:
    def test_missing_date_returns_needs_regeneration(self):
        t = make_template(pattern="{dcDate}_{dcTitle}")
        fields = NamingFields(dcTitle="Doc")  # dcDate missing
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.status == RenderStatus.NEEDS_REGENERATION
        assert result.can_apply is False
        assert "dcDate" in result.missing_fields

    def test_missing_title_returns_needs_regeneration(self):
        t = make_template(pattern="{dcDate}_{dcTitle}")
        fields = NamingFields(dcDate="2025-07-26")  # dcTitle missing
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.status == RenderStatus.NEEDS_REGENERATION
        assert result.can_apply is False
        assert "dcTitle" in result.missing_fields

    def test_missing_field_result_cannot_apply(self):
        t = make_template(pattern="{dcDate}_{dcTitle}")
        fields = NamingFields()  # both missing
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.can_apply is False
        assert len(result.missing_fields) > 0

    def test_missing_optional_field_still_ready(self):
        """Field in pattern that's disabled should not cause NEEDS_REGENERATION."""
        t = make_template(
            pattern="{dcDate}_{dcTitle}",
            fields=[
                TemplateField(dc_name="dcDate", display_name="Date", order=1),
                TemplateField(dc_name="dcTitle", display_name="Title", order=2),
                TemplateField(dc_name="dcSubject", display_name="Subject", order=3, enabled=False),
            ],
        )
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.status == RenderStatus.READY
        assert result.can_apply is True


# ── Complete fields → READY ──────────────────────────────────────────────────

class TestCompleteFieldsReady:
    def test_all_fields_present_returns_ready(self):
        t = make_template(pattern="{dcDate}_{dcTitle}")
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.status == RenderStatus.READY
        assert result.can_apply is True
        assert len(result.missing_fields) == 0

    def test_multi_field_all_present_ready(self):
        t = make_template(
            pattern="{dcDate}_{dcTitle}_{extStatus}",
            fields=[
                TemplateField(dc_name="dcDate", display_name="Date", order=1),
                TemplateField(dc_name="dcTitle", display_name="Title", order=2),
                TemplateField(dc_name="extStatus", display_name="Status", order=3),
            ],
        )
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc", extStatus="draft")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.status == RenderStatus.READY
        assert result.can_apply is True


# ── Invalid field values ─────────────────────────────────────────────────────

class TestInvalidFieldValues:
    def test_date_not_matching_format_returns_invalid(self):
        t = make_template(pattern="{dcDate}_{dcTitle}", date_format=DateFormat.YYYYMMDD)
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc")  # wrong format
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.status == RenderStatus.INVALID
        assert result.can_apply is False

    def test_invalid_date_format_returns_invalid(self):
        t = make_template(pattern="{dcDate}_{dcTitle}", date_format=DateFormat.YYYYMM)
        fields = NamingFields(dcDate="not-a-date", dcTitle="Doc")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.status == RenderStatus.INVALID
        assert result.can_apply is False

    def test_field_with_illegal_chars_sanitized_not_invalid(self):
        """Illegal filename chars should be sanitized, not make the result INVALID."""
        t = make_template(pattern="{dcDate}_{dcTitle}")
        fields = NamingFields(dcDate="2025-07-26", dcTitle="test<file>")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert "<" not in result.rendered_name
        assert ">" not in result.rendered_name
        # Should still be READY after sanitization
        assert result.status == RenderStatus.READY


# ── Preview consistency ──────────────────────────────────────────────────────

class TestPreviewConsistency:
    def test_preview_and_formal_render_identical(self):
        """Preview and formal rendering must use the same code path."""
        t = make_template(pattern="{dcDate}_{dcTitle}")
        fields = NamingFields(dcDate="2025-07-26", dcTitle="报告")
        # Both calls use the same static method
        result1 = TemplateRenderer.render(t, fields, ".pdf")
        result2 = TemplateRenderer.render(t, fields, ".pdf")
        assert result1.rendered_name == result2.rendered_name
        assert result1.status == result2.status
        assert result1.can_apply == result2.can_apply

    def test_preview_consistent_across_multiple_calls(self):
        t = make_template(pattern="{dcDate}_{dcTitle}_{extStatus}", fields=[
            TemplateField(dc_name="dcDate", display_name="Date", order=1),
            TemplateField(dc_name="dcTitle", display_name="Title", order=2),
            TemplateField(dc_name="extStatus", display_name="Status", order=3),
        ])
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc", extStatus="final")
        r1 = TemplateRenderer.render(t, fields, ".docx")
        r2 = TemplateRenderer.render(t, fields, ".docx")
        assert r1 == r2  # dataclass equality


# ── Extension protection ─────────────────────────────────────────────────────

class TestExtensionProtection:
    def test_extension_preserved_pdf(self):
        t = make_template()
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.rendered_name.endswith(".pdf")

    def test_extension_preserved_docx(self):
        t = make_template()
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc")
        result = TemplateRenderer.render(t, fields, ".docx")
        assert result.rendered_name.endswith(".docx")

    def test_extension_preserved_no_ext(self):
        t = make_template()
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc")
        result = TemplateRenderer.render(t, fields, "")
        assert not result.rendered_name.endswith(".")

    def test_template_cannot_change_extension(self):
        """The pattern should not be able to change the file extension."""
        t = make_template(pattern="{dcDate}_{dcTitle}.xyz")
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Doc")
        result = TemplateRenderer.render(t, fields, ".pdf")
        assert result.rendered_name.endswith(".pdf")
        assert not result.rendered_name.endswith(".xyz")


# ── TemplateRenderResult model ───────────────────────────────────────────────

class TestTemplateRenderResult:
    def test_ready_result(self):
        r = TemplateRenderResult(
            rendered_name="2025-07-26_Doc.pdf",
            missing_fields=(),
            status=RenderStatus.READY,
            errors=(),
        )
        assert r.can_apply is True

    def test_needs_regeneration_result(self):
        r = TemplateRenderResult(
            rendered_name="__Doc.pdf",
            missing_fields=("dcDate",),
            status=RenderStatus.NEEDS_REGENERATION,
            errors=("Missing required field: dcDate",),
        )
        assert r.can_apply is False

    def test_invalid_result(self):
        r = TemplateRenderResult(
            rendered_name="",
            missing_fields=(),
            status=RenderStatus.INVALID,
            errors=("Date value does not match format",),
        )
        assert r.can_apply is False

    def test_result_immutable(self):
        r = TemplateRenderResult("name.pdf", (), RenderStatus.READY, ())
        with pytest.raises(Exception):
            r.rendered_name = "changed"
