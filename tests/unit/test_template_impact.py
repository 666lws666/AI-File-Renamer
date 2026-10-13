"""Tests for TemplateImpactAnalyzer — pure analysis, no mutations."""

import pytest
from src.core.template_model import Template, TemplateField
from src.core.naming_fields import NamingFields
from src.core.template_impact import (
    TemplateImpactAnalyzer,
    ImpactResult,
    ImpactAction,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_template(**kwargs):
    defaults = dict(
        name="Test",
        pattern="{dcDate}_{dcTitle}",
        fields=[
            TemplateField(dc_name="dcDate", display_name="Date", order=1),
            TemplateField(dc_name="dcTitle", display_name="Title", order=2),
        ],
    )
    defaults.update(kwargs)
    return Template(**defaults)


# ── Field-sufficient unapplied → rerender only ──────────────────────────────

class TestFieldSufficientRerender:
    def test_all_fields_present_returns_rerender(self):
        t = make_template()
        fields = {"task-1": NamingFields(dcDate="2025-07-26", dcTitle="Report")}
        results = TemplateImpactAnalyzer.analyze(t, fields, applied_task_ids=set())
        assert results[0].action == ImpactAction.RERENDER
        assert results[0].task_id == "task-1"
        assert len(results[0].missing_fields) == 0

    def test_multiple_tasks_all_sufficient_rerender(self):
        t = make_template()
        fields = {
            "task-1": NamingFields(dcDate="2025-01-01", dcTitle="A"),
            "task-2": NamingFields(dcDate="2025-02-02", dcTitle="B"),
        }
        results = TemplateImpactAnalyzer.analyze(t, fields, applied_task_ids=set())
        assert len(results) == 2
        assert all(r.action == ImpactAction.RERENDER for r in results)


# ── Field-insufficient → NEEDS_REGENERATION ──────────────────────────────────

class TestFieldInsufficientRegenerate:
    def test_missing_field_returns_needs_regeneration(self):
        t = make_template()
        fields = {"task-1": NamingFields(dcDate="2025-07-26")}  # dcTitle missing
        results = TemplateImpactAnalyzer.analyze(t, fields, applied_task_ids=set())
        assert results[0].action == ImpactAction.NEEDS_REGENERATION
        assert "dcTitle" in results[0].missing_fields

    def test_missing_field_explicitly_listed(self):
        t = make_template(pattern="{dcDate}_{dcTitle}_{extStatus}", fields=[
            TemplateField(dc_name="dcDate", display_name="Date", order=1),
            TemplateField(dc_name="dcTitle", display_name="Title", order=2),
            TemplateField(dc_name="extStatus", display_name="Status", order=3),
        ])
        fields = {"task-1": NamingFields(dcDate="2025-07-26")}
        results = TemplateImpactAnalyzer.analyze(t, fields, applied_task_ids=set())
        assert results[0].action == ImpactAction.NEEDS_REGENERATION
        assert "dcTitle" in results[0].missing_fields
        assert "extStatus" in results[0].missing_fields

    def test_no_auto_ai_call_triggered(self):
        """The analyzer must NOT trigger AI calls — it's pure analysis."""
        t = make_template()
        fields = {"task-1": NamingFields()}  # all missing
        results = TemplateImpactAnalyzer.analyze(t, fields, applied_task_ids=set())
        assert results[0].action == ImpactAction.NEEDS_REGENERATION
        # No side effects, no AI calls — analyzer is pure


# ── Applied tasks unaffected ─────────────────────────────────────────────────

class TestAppliedTasksUnaffected:
    def test_applied_task_always_unaffected(self):
        t = make_template()
        fields = {"task-1": NamingFields(dcDate="2025-07-26", dcTitle="Report")}
        results = TemplateImpactAnalyzer.analyze(t, fields, applied_task_ids={"task-1"})
        assert results[0].action == ImpactAction.UNAFFECTED

    def test_applied_task_unaffected_even_if_fields_missing(self):
        t = make_template()
        fields = {"task-1": NamingFields()}  # all missing
        results = TemplateImpactAnalyzer.analyze(t, fields, applied_task_ids={"task-1"})
        assert results[0].action == ImpactAction.UNAFFECTED

    def test_mixed_applied_and_unapplied(self):
        t = make_template()
        fields = {
            "task-1": NamingFields(dcDate="2025-01-01", dcTitle="A"),  # sufficient
            "task-2": NamingFields(dcDate="2025-02-02"),  # insufficient
            "task-3": NamingFields(dcDate="2025-03-03", dcTitle="C"),  # sufficient, applied
        }
        results = TemplateImpactAnalyzer.analyze(t, fields, applied_task_ids={"task-3"})
        result_map = {r.task_id: r for r in results}
        assert result_map["task-1"].action == ImpactAction.RERENDER
        assert result_map["task-2"].action == ImpactAction.NEEDS_REGENERATION
        assert result_map["task-3"].action == ImpactAction.UNAFFECTED


# ── Undo/History records unaffected ──────────────────────────────────────────

class TestUndoAndHistoryUnaffected:
    def test_analysis_does_not_modify_task_data(self):
        """The analyzer must not modify any input data."""
        t = make_template()
        fields = {"task-1": NamingFields(dcDate="2025-07-26", dcTitle="Report")}
        fields_copy = {"task-1": NamingFields(dcDate="2025-07-26", dcTitle="Report")}

        _ = TemplateImpactAnalyzer.analyze(t, fields, applied_task_ids=set())
        # fields should be unchanged
        assert fields["task-1"].dcDate == fields_copy["task-1"].dcDate
        assert fields["task-1"].dcTitle == fields_copy["task-1"].dcTitle

    def test_empty_task_list_returns_empty(self):
        t = make_template()
        results = TemplateImpactAnalyzer.analyze(t, {}, applied_task_ids=set())
        assert results == []

    def test_analysis_pure_no_filesystem_access(self, tmp_path):
        """The analysis should not touch the filesystem."""
        t = make_template()
        fields = {"task-1": NamingFields(dcDate="2025-07-26", dcTitle="Report")}
        results = TemplateImpactAnalyzer.analyze(t, fields, applied_task_ids=set())
        assert len(results) == 1


# ── ImpactResult model ───────────────────────────────────────────────────────

class TestImpactResult:
    def test_rerender_result(self):
        r = ImpactResult(task_id="t1", action=ImpactAction.RERENDER)
        assert r.action == ImpactAction.RERENDER

    def test_needs_regeneration_result(self):
        r = ImpactResult(
            task_id="t1",
            action=ImpactAction.NEEDS_REGENERATION,
            missing_fields=("dcTitle",),
            reason="Missing required field: dcTitle",
        )
        assert r.action == ImpactAction.NEEDS_REGENERATION
        assert "dcTitle" in r.missing_fields

    def test_unaffected_result(self):
        r = ImpactResult(
            task_id="t1",
            action=ImpactAction.UNAFFECTED,
            reason="Task is already applied",
        )
        assert r.action == ImpactAction.UNAFFECTED
