"""Tests for Template domain model — Dublin Core fields, validation, immutability."""

import pytest
from src.core.template_model import (
    Template,
    TemplateField,
    STANDARD_FIELDS,
    DateFormat,
    Separator,
    OrgMode,
    OutputLanguage,
)


class TestTemplateDefaultPattern:
    """Default pattern must be {dcDate}_{dcTitle}."""

    def test_default_pattern_is_dcDate_dcTitle(self):
        t = Template(name="Default")
        assert t.pattern == "{dcDate}_{dcTitle}"

    def test_default_template_has_all_standard_fields(self):
        t = Template(name="Default")
        assert len(t.fields) == 10
        dc_names = {f.dc_name for f in t.fields}
        assert dc_names == {
            "dcDate", "dcTitle", "dcSubject", "dcType", "dcCreator",
            "dcIdentifier", "extOrganization", "extProject", "extStatus", "extVersion",
        }

    def test_default_fields_have_unique_order(self):
        t = Template(name="Default")
        orders = [f.order for f in t.fields]
        assert len(orders) == len(set(orders))


class TestTemplateDateFormats:
    """Only YYYYMMDD, YYYYMM, YYYY-MM-DD, YYYY-MM are allowed."""

    def test_yyyymmdd_accepted(self):
        t = Template(name="T", date_format=DateFormat.YYYYMMDD)
        assert t.date_format == DateFormat.YYYYMMDD

    def test_yyyymm_accepted(self):
        t = Template(name="T", date_format=DateFormat.YYYYMM)
        assert t.date_format == DateFormat.YYYYMM

    def test_yyyy_mm_dd_accepted(self):
        t = Template(name="T", date_format=DateFormat.YYYY_MM_DD)
        assert t.date_format == DateFormat.YYYY_MM_DD

    def test_yyyy_mm_accepted(self):
        t = Template(name="T", date_format=DateFormat.YYYY_MM)
        assert t.date_format == DateFormat.YYYY_MM

    def test_invalid_date_format_rejected(self):
        with pytest.raises(ValueError, match="date_format"):
            Template(name="T", date_format="DD/MM/YYYY")

    def test_empty_date_format_rejected(self):
        with pytest.raises(ValueError, match="date_format"):
            Template(name="T", date_format="")


class TestTemplateSeparators:
    """Only underscore and hyphen are allowed."""

    def test_underscore_accepted(self):
        t = Template(name="T", separator=Separator.UNDERSCORE)
        assert t.separator == Separator.UNDERSCORE

    def test_hyphen_accepted(self):
        t = Template(name="T", separator=Separator.HYPHEN)
        assert t.separator == Separator.HYPHEN

    def test_invalid_separator_rejected(self):
        with pytest.raises(ValueError, match="separator"):
            Template(name="T", separator=".")

    def test_empty_separator_rejected(self):
        with pytest.raises(ValueError, match="separator"):
            Template(name="T", separator="")


class TestTemplateOrgModes:
    """flat, subject_tree, type_tree, project_tree supported."""

    def test_flat_accepted(self):
        t = Template(name="T", org_mode=OrgMode.FLAT)
        assert t.org_mode == OrgMode.FLAT

    def test_subject_tree_accepted(self):
        t = Template(name="T", org_mode=OrgMode.SUBJECT_TREE)
        assert t.org_mode == OrgMode.SUBJECT_TREE

    def test_type_tree_accepted(self):
        t = Template(name="T", org_mode=OrgMode.TYPE_TREE)
        assert t.org_mode == OrgMode.TYPE_TREE

    def test_project_tree_accepted(self):
        t = Template(name="T", org_mode=OrgMode.PROJECT_TREE)
        assert t.org_mode == OrgMode.PROJECT_TREE

    def test_invalid_org_mode_rejected(self):
        with pytest.raises(ValueError, match="org_mode"):
            Template(name="T", org_mode="date_tree")

    def test_default_is_flat(self):
        t = Template(name="T")
        assert t.org_mode == OrgMode.FLAT


class TestTemplateOutputLanguages:
    """zh, en, ja, es supported."""

    def test_zh_accepted(self):
        t = Template(name="T", output_language=OutputLanguage.ZH)
        assert t.output_language == OutputLanguage.ZH

    def test_en_accepted(self):
        t = Template(name="T", output_language=OutputLanguage.EN)
        assert t.output_language == OutputLanguage.EN

    def test_ja_accepted(self):
        t = Template(name="T", output_language=OutputLanguage.JA)
        assert t.output_language == OutputLanguage.JA

    def test_es_accepted(self):
        t = Template(name="T", output_language=OutputLanguage.ES)
        assert t.output_language == OutputLanguage.ES

    def test_invalid_language_rejected(self):
        with pytest.raises(ValueError, match="output_language"):
            Template(name="T", output_language="fr")

    def test_empty_language_rejected(self):
        with pytest.raises(ValueError, match="output_language"):
            Template(name="T", output_language="")


class TestTemplateIdValidation:
    """Template ID must be non-empty."""

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError, match="id must not be empty"):
            Template(id="", name="T")

    def test_whitespace_id_rejected(self):
        with pytest.raises(ValueError, match="id"):
            Template(id="   ", name="T")

    def test_default_id_is_generated(self):
        t = Template(name="T")
        assert len(t.id) > 0
        assert "-" in t.id  # UUID format


class TestTemplateFieldOrderUniqueness:
    """Duplicate field orders must be rejected."""

    def test_duplicate_order_rejected(self):
        with pytest.raises(ValueError, match="order"):
            Template(
                name="T",
                fields=[
                    TemplateField(dc_name="dcDate", display_name="Date", order=1),
                    TemplateField(dc_name="dcTitle", display_name="Title", order=1),
                ],
            )

    def test_unique_orders_accepted(self):
        t = Template(
            name="T",
            fields=[
                TemplateField(dc_name="dcDate", display_name="Date", order=1),
                TemplateField(dc_name="dcTitle", display_name="Title", order=2),
            ],
        )
        assert len(t.fields) == 2


class TestTemplateDuplicateFields:
    """Duplicate dc_name in fields must be rejected."""

    def test_duplicate_dc_name_rejected(self):
        with pytest.raises(ValueError, match="Duplicate field"):
            Template(
                name="T",
                fields=[
                    TemplateField(dc_name="dcDate", display_name="Date", order=1),
                    TemplateField(dc_name="dcDate", display_name="Date Again", order=2),
                ],
            )


class TestTemplateIllegalPattern:
    """Pattern must reference only enabled fields; unresolved placeholders must fail."""

    def test_pattern_with_unknown_field_rejected(self):
        with pytest.raises(ValueError, match="not a recognized field"):
            Template(name="T", pattern="{dcDate}_{unknownField}")

    def test_pattern_with_disabled_field_rejected(self):
        with pytest.raises(ValueError, match="disabled field"):
            Template(
                name="T",
                pattern="{dcDate}_{dcTitle}",
                fields=[
                    TemplateField(dc_name="dcDate", display_name="Date", order=1),
                    TemplateField(dc_name="dcTitle", display_name="Title", order=2, enabled=False),
                ],
            )

    def test_pattern_with_all_enabled_fields_accepted(self):
        t = Template(
            name="T",
            pattern="{dcDate}_{dcTitle}",
            fields=[
                TemplateField(dc_name="dcDate", display_name="Date", order=1),
                TemplateField(dc_name="dcTitle", display_name="Title", order=2),
            ],
        )
        assert t.pattern == "{dcDate}_{dcTitle}"


class TestTemplateImmutability:
    """Template and TemplateField should be immutable."""

    def test_template_is_immutable(self):
        t = Template(name="T")
        with pytest.raises(Exception):
            t.name = "Changed"

    def test_template_field_is_immutable(self):
        f = TemplateField(dc_name="dcDate", display_name="Date", order=1)
        with pytest.raises(Exception):
            f.dc_name = "dcTitle"

    def test_template_fields_collection_is_immutable(self):
        t = Template(name="T")

        assert isinstance(t.fields, tuple)
        with pytest.raises(AttributeError):
            t.fields.append(
                TemplateField(dc_name="dcSubject", display_name="Subject", order=11)
            )

    def test_template_with_version_creates_new_instance(self):
        t = Template(name="T", version=1)
        t2 = t.with_incremented_version()
        assert t2.version == 2
        assert t.version == 1
        assert t2 is not t


class TestTemplateFieldModel:
    """TemplateField basic properties."""

    def test_field_has_id(self):
        f = TemplateField(dc_name="dcDate", display_name="Date", order=1)
        assert len(f.id) > 0

    def test_field_enabled_by_default(self):
        f = TemplateField(dc_name="dcDate", display_name="Date", order=1)
        assert f.enabled is True

    def test_field_can_be_disabled(self):
        f = TemplateField(dc_name="dcDate", display_name="Date", order=1, enabled=False)
        assert f.enabled is False

    def test_field_dc_name_required(self):
        with pytest.raises(ValueError, match="dc_name"):
            TemplateField(dc_name="", display_name="Date", order=1)

    def test_field_display_name_required(self):
        with pytest.raises(ValueError, match="display_name"):
            TemplateField(dc_name="dcDate", display_name="", order=1)

    def test_field_order_must_be_positive(self):
        with pytest.raises(ValueError, match="order"):
            TemplateField(dc_name="dcDate", display_name="Date", order=0)


class TestStandardFields:
    """STANDARD_FIELDS provides the 10 canonical Dublin Core fields."""

    def test_standard_fields_count(self):
        assert len(STANDARD_FIELDS) == 10

    def test_standard_fields_are_template_fields(self):
        for f in STANDARD_FIELDS:
            assert isinstance(f, TemplateField)

    def test_standard_fields_have_unique_orders(self):
        orders = [f.order for f in STANDARD_FIELDS]
        assert len(orders) == len(set(orders))

    def test_standard_fields_have_unique_dc_names(self):
        names = [f.dc_name for f in STANDARD_FIELDS]
        assert len(names) == len(set(names))
