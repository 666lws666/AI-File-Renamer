"""M4 TemplateImpactAnalyzer — pure analysis of template changes on existing tasks."""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple

from .template_model import Template
from .naming_fields import NamingFields


class ImpactAction(str, Enum):
    RERENDER = "rerender"                   # Fields sufficient, just re-render preview
    NEEDS_REGENERATION = "needs_regeneration"  # Fields insufficient, need AI regeneration
    UNAFFECTED = "unaffected"                # Task already applied or otherwise unaffected


@dataclass(frozen=True)
class ImpactResult:
    """Deterministic impact analysis result for a single task."""

    task_id: str
    action: ImpactAction
    missing_fields: Tuple[str, ...] = ()
    reason: str = ""


class TemplateImpactAnalyzer:
    """Pure analyzer: determines what template changes mean for existing tasks.

    IMPORTANT: This analyzer is strictly read-only. It does NOT:
      - Modify any tasks, files, or undo/history records
      - Initiate AI calls
      - Access the filesystem
      - Mutate any inputs
    """

    @staticmethod
    def analyze(
        template: Template,
        task_fields: dict[str, NamingFields],
        applied_task_ids: set[str],
    ) -> list[ImpactResult]:
        """Analyze impact of a template on each task.

        Args:
            template: The Template whose pattern determines required fields.
            task_fields: Mapping of task_id → NamingFields.
            applied_task_ids: Set of task_ids that are already applied.

        Returns:
            One ImpactResult per task_id in task_fields.
        """
        results: list[ImpactResult] = []

        # Determine which fields are required (enabled + appear in pattern)
        pattern = template.pattern
        placeholders = re.findall(r"\{(\w+)\}", pattern)
        enabled_names = {f.dc_name for f in template.fields if f.enabled}
        required_fields = [ph for ph in placeholders if ph in enabled_names]

        for task_id, fields in task_fields.items():
            # Applied tasks are always unaffected
            if task_id in applied_task_ids:
                results.append(ImpactResult(
                    task_id=task_id,
                    action=ImpactAction.UNAFFECTED,
                    reason="Task is already applied",
                ))
                continue

            # Check which required fields are missing
            field_values = {
                "dcDate": fields.dcDate,
                "dcTitle": fields.dcTitle,
                "dcSubject": fields.dcSubject,
                "dcType": fields.dcType,
                "dcCreator": fields.dcCreator,
                "dcIdentifier": fields.dcIdentifier,
                "extOrganization": fields.extOrganization,
                "extProject": fields.extProject,
                "extStatus": fields.extStatus,
                "extVersion": fields.extVersion,
            }

            missing = []
            for rf in required_fields:
                value = field_values.get(rf)
                if value is None or (isinstance(value, str) and not value.strip()):
                    missing.append(rf)

            if missing:
                results.append(ImpactResult(
                    task_id=task_id,
                    action=ImpactAction.NEEDS_REGENERATION,
                    missing_fields=tuple(missing),
                    reason=f"Missing required fields: {', '.join(missing)}",
                ))
            else:
                results.append(ImpactResult(
                    task_id=task_id,
                    action=ImpactAction.RERENDER,
                    reason="All required fields present — re-render preview only",
                ))

        return results
