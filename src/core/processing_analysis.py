"""Frozen, secret-free admission values. These values are not bearer permits."""
from __future__ import annotations

from dataclasses import dataclass, field, fields, replace

from src.core.degradation import ContentKind
from src.core.processing_authority import WorkContext
from src.core.processing_identity import cloud_engine_fingerprint
from src.core.provider_profile import ProviderProfile
from src.core.template_model import Template, TemplateField, OutputLanguage, DateFormat, OrgMode, Separator
from src.services.local_ai.preparation_protocol import LocalPreparationLimits, PreparationCoverage


# CPU scan inference has taken ~166s. This is a ceiling, not a speed promise;
# queueing, preparation, attestation, inference and cleanup all share this budget.
LOCAL_ANALYSIS_TIMEOUT_SECONDS = 600.0


def snapshot_template(template: Template) -> Template:
    """Reject typed lookalikes/subclasses and retain only immutable domain values."""
    if (type(template) is not Template or type(template.fields) is not tuple
            or any(type(getattr(template, name)) is not str for name in ("name", "pattern", "id"))
            or type(template.version) is not int
            or type(template.output_language) is not OutputLanguage
            or type(template.date_format) is not DateFormat
            or type(template.org_mode) is not OrgMode
            or type(template.separator) is not Separator):
        raise ValueError("Invalid analysis template")
    for item in template.fields:
        if (type(item) is not TemplateField
                or any(type(getattr(item, name)) is not str for name in ("dc_name", "display_name", "id"))
                or type(item.order) is not int or type(item.enabled) is not bool):
            raise ValueError("Invalid analysis template")
    return replace(template, fields=tuple(replace(item) for item in template.fields))


@dataclass(frozen=True, slots=True)
class AnalysisSettings:
    max_content_chars: int
    max_file_size_mb: int
    max_pdf_pages: int
    max_video_keyframes: int
    quality_mode: str
    request_timeout_seconds: int
    max_retries: int
    allow_text_cloud: bool
    allow_vision_cloud: bool
    allow_video_keyframes_cloud: bool
    max_concurrent_requests: int = 4

    @classmethod
    def capture(cls, config, quality_mode=None):
        # Deliberate field allowlist: never deepcopy AppConfig or its extras.
        values = {name: getattr(config, name) for name in cls.__dataclass_fields__}
        if quality_mode is not None:
            values["quality_mode"] = quality_mode
        result = cls(**values)
        integers = {"max_content_chars": (1, 1_000_000), "max_file_size_mb": (1, 512),
                    "max_pdf_pages": (1, 200), "max_video_keyframes": (1, 32),
                    "request_timeout_seconds": (5, 300), "max_retries": (0, 10),
                    "max_concurrent_requests": (1, 20)}
        if (any(type(getattr(result, k)) is not int or not lo <= getattr(result, k) <= hi
                for k, (lo, hi) in integers.items())
                or type(result.quality_mode) is not str
                or result.quality_mode not in {"economy", "balanced", "high", "quality"}
                or any(type(getattr(result, k)) is not bool for k in (
                    "allow_text_cloud", "allow_vision_cloud", "allow_video_keyframes_cloud"))):
            raise ValueError("Invalid analysis settings")
        return result


@dataclass(frozen=True)
class AnalysisWork:
    context: WorkContext = field(repr=False)
    task_id: str = field(repr=False)
    task_attempt_id: str = field(repr=False)
    source_path: str = field(repr=False)
    settings: AnalysisSettings
    locale: str
    naming_mode: str
    naming_policy_version: str
    template: Template | None = field(repr=False)
    profile: ProviderProfile | None = field(repr=False)
    preparation_limits: LocalPreparationLimits | None
    deadline: float | None
    _seal: object = field(default=None, init=False, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class CloudAnalysisCoverage(PreparationCoverage):
    """Path-free CLOUD summary retaining its existing 200-page text capability.

    This is never a local preparation wire value: that boundary requires the
    exact PreparationCoverage type and retains its reviewed 100-page bound.
    """

    def __post_init__(self):
        indices = self.text_page_indices
        if (type(indices) is not tuple or len(indices) > 200
                or any(type(i) is not int or not 0 <= i <= 2**31-1 for i in indices)
                or tuple(sorted(set(indices))) != indices):
            raise ValueError("Invalid analysis coverage")
        values = {item.name: getattr(self, item.name) for item in fields(PreparationCoverage)}
        # Validate all other dimensions using the unchanged strict wire rules.
        values["text_page_indices"] = indices[:100]
        PreparationCoverage(**values)
        if indices and (self.pdf_total_pages is None or indices[-1] >= self.pdf_total_pages):
            raise ValueError("Invalid analysis coverage")


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    suggested_name: str = field(repr=False)
    context: WorkContext = field(repr=False)
    effective_quality: str
    content_kind: ContentKind
    request_engine_identity: str | None = field(repr=False)
    coverage: PreparationCoverage = field(repr=False)
    warning_codes: tuple[str, ...]
