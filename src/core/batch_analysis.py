"""Frozen admission -> explicitly selected LOCAL/CLOUD naming pipeline.

Only locally extracted text/metadata and bounded prepared visual payloads cross
the Provider boundary.  Raw files, source paths, complete PDFs, and complete
videos are never put in a ProviderRequest.
"""
from __future__ import annotations

import uuid
import time
from contextlib import nullcontext
from itertools import islice
from threading import Lock, BoundedSemaphore
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable
from weakref import ref

from src.core.content_extractor import extract
from src.core.analysis_concurrency import (
    CloudAnalysisLane, CloudLaneQueueFull, CloudLaneQueueTimeout,
    CLOUD_QUEUE_TIMEOUT_SECONDS,
)
from src.core.degradation import ContentKind, DegradationHandler
from src.core.naming_fields import NamingFields
from src.core.filename_validator import validate_filename
from src.core.provider_profile import ProviderProfile
from src.core.provider_protocol import ProviderRequest, ProviderResponse
from src.core.smart_naming import SMART_POLICY_VERSION, SmartNamingError, SmartNamingPolicy
from src.core.template_renderer import RenderStatus, TemplateRenderer
from src.core.template_model import naming_locale
from src.core.processing_authority import (
    ProcessingMode, LocalReadiness, LocalProcessingUnavailable,
    ProcessingSuperseded, CloudDispatchBlocked,
)
from src.core.processing_analysis import (
    AnalysisSettings, AnalysisWork, AnalysisOutcome, LOCAL_ANALYSIS_TIMEOUT_SECONDS,
    cloud_engine_fingerprint, snapshot_template, CloudAnalysisCoverage,
)
from src.services.local_ai.inference_request import LocalNamingRequest, LocalInferenceResult
from src.services.local_ai.preparation_protocol import (
    LocalPreparationLimits, LocalPreparationResult, QUALITY_COUNTS,
    validate_result,
)
from src.providers.openai_compatible import ProcessingDispatch
from src.services.retry_policy import RetryExecutor, RetryPolicy
from src.models.app_config import AppConfig
from src.models.file_item import FileItem, FileStatus
from src.services.media.image_preprocessor import ImagePreprocessor
from src.services.media.keyframe_extractor import VideoKeyframeExtractor
from src.services.media.pdf_renderer import PdfRenderer, PdfRenderConfig


_IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif",
})
_VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".ts", ".mts",
    ".m2ts", ".wmv", ".flv", ".3gp", ".3g2", ".mxf", ".mpg", ".mpeg", ".ogv",
})
_NAMING_FIELD_NAMES = tuple(NamingFields.__dataclass_fields__)
_UNSET = object()


class _AnalysisSeal:
    def __init__(self, owner, work, *, deferred=False):
        self.owner, self.work = owner, ref(work)
        self.deferred = deferred
        self._lock = Lock()
        self._started = False
        self._deadline = work.deadline

    def claim_execution(self):
        if not self.deferred:
            return
        with self._lock:
            if self._started:
                raise ProcessingSuperseded()
            self._started = True

    def execution_deadline(self):
        if self.deferred:
            self._deadline = time.monotonic() + LOCAL_ANALYSIS_TIMEOUT_SECONDS
        return self._deadline


class BatchAnalysisError(RuntimeError):
    """Safe pipeline failure whose text contains neither credentials nor paths."""


def _default_extract(
    path: Path,
    max_chars: int,
    *,
    max_pdf_pages: int | None = None,
    cancellation_token: Callable[[], bool] | None = None,
) -> tuple[str, dict[str, Any]]:
    item = FileItem(original_path=path, file_size=path.stat().st_size)
    extract(
        item,
        max_chars=max_chars,
        max_pdf_pages=max_pdf_pages,
        cancellation_token=cancellation_token,
        redacted_diagnostics=True,
    )
    if item.status is FileStatus.FAILED:
        raise BatchAnalysisError("Local content extraction failed")
    return item.extracted_text, dict(item.metadata)


class BatchAnalysisService:
    """Managed immutable work routing, plus deliberate legacy unit compatibility.

    Supplying any managed dependency opts into strict managed construction. The
    legacy two-argument adapter factory is never used by managed operations.
    """

    def __init__(
        self,
        *,
        profile_provider: Callable[[], ProviderProfile | None],
        credential_provider: Callable[[ProviderProfile], str],
        adapter_factory: Callable[[ProviderProfile, str], Any] | None = None,
        config_provider: Callable[[], AppConfig | AnalysisSettings],
        template_provider: Callable[[], Any],
        content_extractor: Callable[[Path, int], tuple[str, dict[str, Any]]] = _default_extract,
        image_preprocessor: Any = None,
        pdf_renderer: Any = None,
        video_extractor: Any = None,
        degradation_handler: DegradationHandler | None = None,
        processing_authority=_UNSET,
        local_inference_service=_UNSET,
        local_preparation_service=_UNSET,
        managed_adapter_factory=None,
        capture_guard=None,
    ) -> None:
        dependencies = (processing_authority, local_inference_service, local_preparation_service)
        self._managed = any(value is not _UNSET for value in dependencies) or managed_adapter_factory is not None
        if self._managed and any(value is _UNSET or value is None for value in dependencies):
            raise ValueError("Managed analysis requires authority, inference and bounded preparation services")
        self._authority = processing_authority
        self._local_inference = local_inference_service
        self._local_preparation = local_preparation_service
        self._managed_adapter_factory = managed_adapter_factory
        self._work_owner = object()
        # Shared across all pools using this service. Only explicitly deferred
        # LOCAL runners enter; admission-based LOCAL remains unchanged.
        self._local_lane = BoundedSemaphore(1)
        self._cloud_lane = CloudAnalysisLane()
        self._local_lane_lock = Lock()
        self._local_waiters = 0
        self._capture_guard = capture_guard or nullcontext
        self._profile_provider = profile_provider
        self._credential_provider = credential_provider
        self._adapter_factory = adapter_factory
        self._config_provider = config_provider
        self._template_provider = template_provider
        self._extract_content = content_extractor
        self._image = image_preprocessor or ImagePreprocessor()
        self._pdf = pdf_renderer or PdfRenderer()
        self._video = video_extractor or VideoKeyframeExtractor()
        self._degradation = degradation_handler or DegradationHandler()
        self._template_id = ""

    def capture_work(
        self, source_path, task_id, *, task_attempt_id, task_cancel_event,
        template_id="", output_language="", naming_mode="template",
        naming_policy_version=SMART_POLICY_VERSION, quality_mode=None,
        defer_execution_deadline=False,
    ) -> AnalysisWork:
        """Admission-only snapshot: no source reads, service I/O or credentials.

        Managed workers must receive this exact work object; they never recapture
        state. Legacy __call__/analyze are deliberately separate compatibility APIs.
        """
        with self._capture_guard():
            return self._capture_work(source_path, task_id, task_attempt_id=task_attempt_id,
                task_cancel_event=task_cancel_event, template_id=template_id,
                output_language=output_language, naming_mode=naming_mode,
                naming_policy_version=naming_policy_version, quality_mode=quality_mode,
                defer_execution_deadline=defer_execution_deadline)

    def _capture_work(self, source_path, task_id, *, task_attempt_id, task_cancel_event,
                      template_id, output_language, naming_mode, naming_policy_version,
                      quality_mode, defer_execution_deadline):
        if not self._managed:
            raise BatchAnalysisError("Managed analysis is not configured")
        if type(defer_execution_deadline) is not bool:
            raise BatchAnalysisError("Invalid analysis admission")
        started = time.monotonic()
        snapshot = self._authority.snapshot()
        if snapshot.mode is ProcessingMode.LOCAL:
            if snapshot.local_readiness is not LocalReadiness.READY or not snapshot.engine_fingerprint:
                raise LocalProcessingUnavailable()
        elif not snapshot.engine_fingerprint:
            raise CloudDispatchBlocked()
        context = self._authority.capture_work(engine_fingerprint=snapshot.engine_fingerprint,
            task_attempt_id=task_attempt_id, task_cancel_event=task_cancel_event)
        if (context.session_id, context.generation, context.mode) != (snapshot.session_id, snapshot.generation, snapshot.mode):
            raise ProcessingSuperseded()
        if (type(task_id) is not str or not task_id or len(task_id) > 128
                or type(source_path) is not str or not source_path):
            raise BatchAnalysisError("Invalid analysis admission")
        if naming_mode not in {"template", "smart"} or naming_policy_version != SMART_POLICY_VERSION:
            raise SmartNamingError("unsupportedPolicy")
        try:
            settings = AnalysisSettings.capture(self._config_provider(), quality_mode)
            self._authority.assert_current(context)
            selected = self._template_provider(template_id) if naming_mode == "template" else None
            self._authority.assert_current(context)
            template = snapshot_template(selected) if naming_mode == "template" else None
            language = output_language or (template.output_language if template else "zh")
            # Canonical values must be plain strings, not saved str-Enum keys.
            explicit_locales = {"zh-CN": "zh-CN", "zh-HK": "zh-HK", "en-US": "en-US"}
            locale = explicit_locales[language] if language in explicit_locales else naming_locale(language)
        except Exception:
            self._authority.assert_current(context)
            raise BatchAnalysisError("Invalid analysis settings or template") from None
        profile = None
        limits = None
        deadline = None
        if context.mode is ProcessingMode.LOCAL:
            count = QUALITY_COUNTS[settings.quality_mode]
            extension = Path(source_path).suffix.lower()
            if extension in _VIDEO_EXTENSIONS and settings.max_video_keyframes < count:
                raise BatchAnalysisError("Video frame limit is below the selected quality requirement")
            limits = LocalPreparationLimits(
                max_file_bytes=settings.max_file_size_mb * 1024 * 1024,
                max_text_chars=settings.max_content_chars,
                # The preparation coverage protocol can enumerate <=100 text
                # pages. Preserve the user's captured value separately.
                max_pdf_pages=min(settings.max_pdf_pages, 100),
                max_visuals=min(6, settings.max_pdf_pages) if extension == ".pdf" else 8,
                max_video_frames=count if extension in _VIDEO_EXTENSIONS else min(8, settings.max_video_keyframes),
                timeout_seconds=300,
            )
            deadline = None if defer_execution_deadline else started + LOCAL_ANALYSIS_TIMEOUT_SECONDS
        else:
            profile = self._capture_cloud_profile(context)
        self._authority.assert_current(context)
        work = AnalysisWork(context, task_id, task_attempt_id, source_path, settings,
            locale, naming_mode, naming_policy_version, template, profile, limits, deadline)
        object.__setattr__(work, "_seal", _AnalysisSeal(self._work_owner, work,
            deferred=defer_execution_deadline and context.mode is ProcessingMode.LOCAL))
        return work

    def _assert_work(self, work, *, current=True):
        if (not self._managed or type(work) is not AnalysisWork
                or type(work._seal) is not _AnalysisSeal
                or work._seal.owner is not self._work_owner or work._seal.work() is not work
                or type(work.settings) is not AnalysisSettings
                or work.task_attempt_id != work.context.task_attempt_id):
            raise ProcessingSuperseded()
        if current:
            self._authority.assert_current(work.context)

    def _capture_cloud_profile(self, context):
        try:
            profile = self._profile_provider()
            self._authority.assert_current(context)
            if (type(profile) is not ProviderProfile or profile.enabled is not True
                    or profile.needs_connection_verification is not False
                    or not profile.id or not profile.model
                    or cloud_engine_fingerprint(profile) != context.engine_fingerprint):
                raise CloudDispatchBlocked()
            if not callable(self._managed_adapter_factory):
                raise BatchAnalysisError("Managed cloud adapter is not configured")
            return replace(profile, capabilities=replace(profile.capabilities))
        except Exception:
            self._authority.assert_current(context)
            raise CloudDispatchBlocked() from None

    def _run_cloud(self, work, source, cancelled, checkpoint):
        settings, profile = work.settings, work.profile
        if self._extract_content is _default_extract:
            text, metadata = self._extract_content(source, settings.max_content_chars,
                max_pdf_pages=settings.max_pdf_pages, cancellation_token=cancelled)
        else:
            text, metadata = self._extract_content(source, settings.max_content_chars)
        checkpoint()
        if self._extract_content is _default_extract and source.suffix.lower() in _IMAGE_EXTENSIONS | _VIDEO_EXTENSIONS:
            text = ""
        if self._extract_content is _default_extract and source.suffix.lower() in {".xlsx", ".xls"}:
            text = "\n".join(line for line in text.splitlines()
                             if not (line.startswith("[Sheet: ") and line.endswith("]")))
        if text.strip() and not settings.allow_text_cloud:
            raise BatchAnalysisError("Text cloud processing is disabled")
        media_coverage = {}
        kind, visuals = self._prepare_visuals(source, text, settings, cancellation_token=cancelled,
                                              coverage_details=media_coverage,
                                              extractor_metadata=metadata,
                                              capabilities=profile.capabilities)
        checkpoint()
        decision = self._degradation.decide(profile.capabilities, kind)
        if decision.degraded:
            raise BatchAnalysisError(decision.user_message_id or decision.reason)
        if len(visuals) > 1 and not profile.capabilities.multi_image:
            raise BatchAnalysisError("capability.multi_image_unavailable")
        if work.naming_mode == "smart" and not text.strip() and not visuals:
            raise SmartNamingError("insufficientContent")
        schema = (SmartNamingPolicy(work.locale).response_schema() if work.naming_mode == "smart"
                  else self._schema_for_template(work.template))
        request = ProviderRequest(request_id=f"batch-{uuid.uuid4().hex}", task_id=work.task_id,
            extracted_text=text or self._content_prompt(kind),
            metadata={"content_kind": kind.value, "prepared_visual_count": len(visuals),
                      "naming_mode": work.naming_mode, "naming_policy_version": work.naming_policy_version},
            visual_payloads=tuple(visuals), requested_schema=schema,
            quality_mode=settings.quality_mode, locale=work.locale, model=profile.model,
            timeout=settings.request_timeout_seconds)
        coverage, warnings = self._cloud_coverage(source, text, metadata, kind, media_coverage)
        checkpoint()
        credential = self._credential_provider(profile)
        checkpoint()
        if type(credential) is not str or not credential:
            raise BatchAnalysisError("The active AI provider has no credential")
        adapter = self._managed_adapter_factory(profile, credential,
            processing_dispatch=ProcessingDispatch(self._authority, work.context),
            retry_executor=RetryExecutor(RetryPolicy(max_retries=settings.max_retries)))
        checkpoint()
        response = adapter.invoke(request, cancellation_token=cancelled)
        checkpoint()
        if response.success is not True or type(response.value) is not ProviderResponse:
            raise BatchAnalysisError("Cloud analysis failed")
        suggested = self._render_managed(work, response.value.fields, text, bool(visuals),
                                         source.suffix.lower(), local=False)
        return AnalysisOutcome(suggested, work.context, settings.quality_mode, kind,
                               work.context.engine_fingerprint, coverage, warnings)

    @staticmethod
    def _pdf_text_pages(text, metadata, total):
        """Unknown/malformed page facts cannot establish text coverage."""
        indices = metadata.get("text_page_indices")
        if (type(total) is not int or not 1 <= total <= 2**31 - 1
                or type(indices) is not tuple or len(indices) > 200
                or any(type(i) is not int or not 0 <= i < total for i in indices)
                or tuple(sorted(set(indices))) != indices
                or (indices and not text.strip())):
            return None
        return indices

    @staticmethod
    def _cloud_coverage(source, text, metadata, kind, media):
        """Only factual allowlisted extractor/renderer values, never source metadata."""
        reason = metadata.get("coverage_reason", "complete")
        if reason not in {"complete", "character_limit", "section_limit"}:
            reason = "complete"
        processed = metadata.get("sections_processed", 0)
        values = dict(content_kind=kind.value, text_source="extracted_text" if text.strip() else "none",
            sections_processed=processed, sections_total=metadata.get("sections_total"),
            text_truncated=reason != "complete", text_limit_reason=reason)
        warnings = [] if reason == "complete" else ["text_character_limit" if reason == "character_limit" else "section_limit"]
        if source.suffix.lower() == ".pdf":
            total = media.get("pdf_total_pages", metadata.get("pages"))
            pages = BatchAnalysisService._pdf_text_pages(text, metadata, total)
            rendered = media.get("rendered_page_indices", ())
            values.update(content_kind="pdf" if text.strip() else "scanned_pdf",
                pdf_total_pages=total, text_page_indices=pages or (),
                rendered_page_indices=rendered)
            if (pages is None and text.strip()) or len(set((pages or ()) + rendered)) != total:
                warnings.append("pdf_page_limit")
        elif kind is ContentKind.VIDEO:
            values.update(video_duration_seconds=media["video_duration_seconds"],
                          video_timestamps_seconds=media["video_timestamps_seconds"])
            warnings.append("video_sampled")
        return CloudAnalysisCoverage(**values), tuple(warnings)

    def run_prepared(self, work: AnalysisWork, *, cancellation_token=None) -> AnalysisOutcome:
        """Run admitted work only. Optional caller cancellation is fail-closed."""
        self._assert_work(work, current=False)  # Authentic object before claim or I/O.
        work._seal.claim_execution()
        deadline = None if work._seal.deferred else work._seal.execution_deadline()
        self._authority.assert_current(work.context)
        latched = False

        def cancelled():
            nonlocal latched
            if latched or not self._authority.is_current(work.context):
                latched = True
                return True
            try:
                latched = bool(cancellation_token and cancellation_token())
            except BaseException:
                latched = True
            # Callbacks may themselves change authority. No callback runs under its lock.
            latched = latched or not self._authority.is_current(work.context)
            return latched

        def checkpoint():
            if cancelled():
                raise ProcessingSuperseded()
            if deadline is not None and time.monotonic() >= deadline:
                raise BatchAnalysisError("Local analysis timed out")

        lane_acquired = False
        cloud_token = None
        try:
            if work._seal.deferred:
                self._acquire_local_lane(cancelled)
                lane_acquired = True
                deadline = work._seal.execution_deadline()
            elif work.context.mode is ProcessingMode.CLOUD:
                try:
                    cloud_token = self._cloud_lane.acquire(
                        work.settings.max_concurrent_requests,
                        cancelled=cancelled,
                        deadline=time.monotonic()+CLOUD_QUEUE_TIMEOUT_SECONDS)
                except CloudLaneQueueFull:
                    raise BatchAnalysisError("Cloud analysis queue is full") from None
                except CloudLaneQueueTimeout:
                    raise BatchAnalysisError("Cloud analysis queue timed out") from None
            checkpoint()
            source = Path(work.source_path)
            self._validate_local_file(source, work.settings)
            checkpoint()
            if work.context.mode is ProcessingMode.LOCAL:
                outcome = self._run_local(work, source, cancelled, checkpoint, deadline)
            else:
                outcome = self._run_cloud(work, source, cancelled, checkpoint)
            checkpoint()
            return outcome
        except Exception as error:
            checkpoint()  # A stale failure may not become a current failure.
            if isinstance(error, (BatchAnalysisError, SmartNamingError, ProcessingSuperseded)):
                raise
            raise BatchAnalysisError("Local analysis failed" if work.context.mode is ProcessingMode.LOCAL else "Cloud analysis failed") from None
        finally:
            if cloud_token is not None:
                self._cloud_lane.release(cloud_token)
            if lane_acquired:
                self._local_lane.release()

    def _acquire_local_lane(self, cancelled):
        if cancelled():
            raise ProcessingSuperseded()
        with self._local_lane_lock:
            if self._local_lane.acquire(blocking=False):
                return
            if self._local_waiters >= 8:
                raise BatchAnalysisError("Local analysis queue is full")
            self._local_waiters += 1
        try:
            while True:
                if cancelled():
                    raise ProcessingSuperseded()
                if self._local_lane.acquire(timeout=.05):
                    return
        finally:
            with self._local_lane_lock:
                self._local_waiters -= 1

    def _run_local(self, work, source, cancelled, checkpoint, deadline):
        result = self._local_preparation.prepare(source, limits=work.preparation_limits,
            quality_mode=work.settings.quality_mode, deadline=deadline, cancelled=cancelled)
        checkpoint()
        if type(result) is not LocalPreparationResult:
            raise BatchAnalysisError("Local analysis failed")
        # Revalidate protocol fakes and the concrete service alike against the
        # captured resource limits; never silently slice excessive visuals/text.
        result = validate_result(result, limits=work.preparation_limits,
                                 quality_mode=work.settings.quality_mode)
        text = result.text
        if source.suffix.lower() in {".xlsx", ".xls"}:
            text = "\n".join(line for line in text.splitlines()
                             if not (line.startswith("[Sheet: ") and line.endswith("]")))
        layout = "contiguous" if text.strip() and not result.visuals else "lines"
        if result.visuals and len(text.splitlines()) > 64:
            # Deterministic grouping preserves every non-newline character and
            # never claims partial coverage when no content was discarded.
            lines = text.splitlines()
            group_size = (len(lines) + 63) // 64
            text = "\n".join(" ".join(lines[i:i+group_size]) for i in range(0, len(lines), group_size))
        request = LocalNamingRequest(text, result.visuals, work.locale, work.naming_mode,
            template=work.template, quality=work.settings.quality_mode, text_layout=layout)
        checkpoint()
        inferred = self._local_inference.infer(request, cancelled=cancelled,
            deadline=deadline, is_current=lambda: self._authority.is_current(work.context))
        checkpoint()
        if type(inferred) is not LocalInferenceResult or inferred.success is not True:
            raise BatchAnalysisError("Local analysis failed")
        suggested = self._render_managed(work, inferred.fields, request.text,
                                         bool(request.visuals), source.suffix.lower(), local=True)
        kind = {"image": ContentKind.IMAGE, "video": ContentKind.VIDEO,
                "scanned_pdf": ContentKind.SCANNED_PDF}.get(result.coverage.content_kind, ContentKind.TEXT)
        return AnalysisOutcome(suggested, work.context, result.effective_quality, kind,
                               inferred.engine_identity, result.coverage, result.warning_codes)

    @staticmethod
    def _render_managed(work, fields, text, has_visuals, extension, *, local):
        from src.core.naming_orthography import NamingOrthographyError, normalize_managed_name

        if work.naming_mode == "smart":
            if not isinstance(fields, Mapping):
                raise BatchAnalysisError("Invalid naming response")
            rendered = SmartNamingPolicy(work.locale, version=work.naming_policy_version).render(
                fields, extracted_text=text, has_visuals=has_visuals, extension=extension)
            try:
                return normalize_managed_name(rendered, work.locale, extension, smart=True)
            except NamingOrthographyError:
                raise BatchAnalysisError("Invalid naming response") from None
        if local:
            if type(fields) is not NamingFields:
                raise BatchAnalysisError("Invalid naming response")
        else:
            if not isinstance(fields, Mapping):
                raise BatchAnalysisError("Invalid naming response")
            fields = NamingFields(**{name: fields[name] for name in _NAMING_FIELD_NAMES if name in fields})
        if any(getattr(fields, name) is not None and type(getattr(fields, name)) is not str for name in _NAMING_FIELD_NAMES):
            raise BatchAnalysisError("Invalid naming response")
        rendered = TemplateRenderer.render(work.template, fields, extension)
        if rendered.status is not RenderStatus.READY or not rendered.rendered_name:
            raise BatchAnalysisError("Naming fields require regeneration")
        components = rendered.rendered_name.split("/")
        if (any(not validate_filename(part).is_valid for part in components[:-1])
                or not validate_filename(components[-1], extension).is_valid):
            raise BatchAnalysisError("Invalid naming response")
        try:
            return normalize_managed_name(rendered.rendered_name, work.locale, extension)
        except NamingOrthographyError:
            raise BatchAnalysisError("Invalid naming response") from None

    def analyze(
        self,
        source_path: str,
        template_id: str = "",
        quality_mode: str = "balanced",
        cancellation_token: Callable[[], bool] | None = None,
    ):
        """Legacy-only Watch adapter; managed callers must explicitly admit work."""
        from src.core.watch_analysis import AnalysisResult

        try:
            suggested = self(
                source_path,
                f"watch-{uuid.uuid4().hex}",
                cancellation_token=cancellation_token,
                template_id=str(template_id or ""),
                naming_mode="template",
                quality_mode=quality_mode,
            )
            return AnalysisResult(
                suggested_name=suggested,
                confidence=1.0,
                content_kind=self._kind_for_path(Path(source_path)).value,
                quality_mode=quality_mode,
            )
        except Exception as error:
            category = "capability_unsupported" if "capability." in str(error) else "analysis_failed"
            return AnalysisResult(
                suggested_name="",
                confidence=0.0,
                quality_mode=quality_mode,
                error_category=category,
            )

    @staticmethod
    def _kind_for_path(path: Path) -> ContentKind:
        extension = path.suffix.lower()
        if extension in _IMAGE_EXTENSIONS:
            return ContentKind.IMAGE
        if extension in _VIDEO_EXTENSIONS:
            return ContentKind.VIDEO
        if extension == ".pdf":
            return ContentKind.SCANNED_PDF
        return ContentKind.TEXT

    def set_template_id(self, template_id: str) -> None:
        self._template_id = str(template_id or "")

    def __call__(
        self,
        path: str,
        task_id: str,
        cancellation_token: Callable[[], bool] | None = None,
        template_id: str | None = None,
        output_language: str = "",
        *,
        naming_mode: str = "template",
        naming_policy_version: str = SMART_POLICY_VERSION,
        quality_mode: str | None = None,
    ) -> str:
        if self._managed:
            raise BatchAnalysisError("Managed analysis requires capture_work and run_prepared")
        if naming_mode not in {"template", "smart"} or naming_policy_version != SMART_POLICY_VERSION:
            raise SmartNamingError("unsupportedPolicy")
        source = Path(path)
        config = self._config_provider()
        if quality_mode is not None:
            config = AnalysisSettings.capture(config, quality_mode)
        self._validate_local_file(source, config)
        policy = None
        if naming_mode == "smart":
            try:
                output_locale = naming_locale(output_language or "zh")
            except (ValueError, TypeError):
                raise SmartNamingError("languageMismatch") from None
            policy = SmartNamingPolicy(locale=output_locale, version=naming_policy_version)
        else:
            template = self._template_provider(
                self._template_id if template_id is None else template_id
            )
            output_locale = naming_locale(output_language or template.output_language)
        profile = self._profile_provider()
        if profile is None:
            raise BatchAnalysisError("No active AI provider is configured")

        self._check_cancelled(cancellation_token)
        if self._extract_content is _default_extract:
            text, metadata = self._extract_content(
                source,
                config.max_content_chars,
                max_pdf_pages=config.max_pdf_pages,
                cancellation_token=cancellation_token,
            )
        else:
            text, metadata = self._extract_content(source, config.max_content_chars)
        self._check_cancelled(cancellation_token)
        if (policy is not None and self._extract_content is _default_extract and
                source.suffix.lower() in _IMAGE_EXTENSIONS | _VIDEO_EXTENSIONS):
            # The default media extractor returns EXIF/file metadata, not OCR or
            # transcript content. Never expose its basename-bearing explanation
            # as text evidence or mistake it for comprehension without visuals.
            # Custom extractors retain their actual OCR/transcript text contract.
            text = ""
        kind, visual_payloads = self._prepare_visuals(
            source, text, config, cancellation_token=cancellation_token,
            extractor_metadata=metadata, capabilities=profile.capabilities,
        )
        if (policy is not None and self._extract_content is _default_extract
                and source.suffix.lower() in {".xlsx", ".xls"}):
            # Empty worksheets still emit a structural label. It is not body
            # content and cannot establish that the document was understood.
            text = "\n".join(line for line in text.splitlines()
                             if not (line.startswith("[Sheet: ") and line.endswith("]")))
        decision = self._degradation.decide(profile.capabilities, kind)
        if decision.degraded:
            raise BatchAnalysisError(decision.user_message_id or decision.reason)
        if len(visual_payloads) > 1 and not profile.capabilities.multi_image:
            raise BatchAnalysisError("capability.multi_image_unavailable")

        if policy is not None and not text.strip() and not visual_payloads:
            raise SmartNamingError("insufficientContent")
        schema = policy.response_schema() if policy is not None else self._schema_for_template(template)
        safe_metadata = self._safe_metadata(metadata, kind, visual_payloads)
        if policy is not None:
            safe_metadata.update(naming_mode="smart", naming_policy_version=policy.version)
        request = ProviderRequest(
            request_id=f"batch-{uuid.uuid4().hex}",
            task_id=task_id,
            extracted_text=text or self._content_prompt(kind),
            metadata=safe_metadata,
            visual_payloads=tuple(visual_payloads),
            requested_schema=schema,
            quality_mode=config.quality_mode,
            locale=output_locale,
            model=profile.model,
            timeout=config.request_timeout_seconds,
        )
        self._check_cancelled(cancellation_token)
        credential = self._credential_provider(profile)
        self._check_cancelled(cancellation_token)
        if not credential:
            raise BatchAnalysisError("The active AI provider has no credential")
        outcome = self._adapter_factory(profile, credential).invoke(
            request, cancellation_token=cancellation_token
        )
        self._check_cancelled(cancellation_token)
        if not outcome.success or not isinstance(outcome.value, ProviderResponse):
            category = getattr(outcome.final_category, "value", "provider_error")
            raise BatchAnalysisError(f"Provider analysis failed: {category}")

        if policy is not None:
            return policy.render(
                outcome.value.fields, extracted_text=text,
                has_visuals=bool(visual_payloads), extension=source.suffix.lower(),
            )

        fields = {
            name: outcome.value.fields.get(name)
            for name in _NAMING_FIELD_NAMES
            if name in outcome.value.fields
        }
        rendered = TemplateRenderer.render(
            template, NamingFields(**fields), source.suffix.lower()
        )
        if rendered.status is not RenderStatus.READY or not rendered.rendered_name:
            missing = ", ".join(rendered.missing_fields)
            raise BatchAnalysisError(
                f"Naming fields require regeneration{': ' + missing if missing else ''}"
            )
        return rendered.rendered_name

    @staticmethod
    def _validate_local_file(path: Path, config: AppConfig | AnalysisSettings) -> None:
        if not path.is_file():
            raise BatchAnalysisError("Source file is unavailable")
        if path.stat().st_size > config.max_file_size_mb * 1024 * 1024:
            raise BatchAnalysisError("Source file exceeds the configured size limit")

    def _prepare_visuals(
        self,
        path: Path,
        text: str,
        config: AppConfig | AnalysisSettings,
        *,
        cancellation_token: Callable[[], bool] | None = None,
        coverage_details: dict | None = None,
        extractor_metadata: dict | None = None,
        capabilities=None,
    ):
        extension = path.suffix.lower()
        if extension in _IMAGE_EXTENSIONS:
            if not config.allow_vision_cloud:
                raise BatchAnalysisError("Vision cloud processing is disabled")
            return ContentKind.IMAGE, (
                self._image.process_file(
                    path, source_index=0, cancellation_token=cancellation_token
                ),
            )
        if extension in _VIDEO_EXTENSIONS:
            if not config.allow_video_keyframes_cloud:
                raise BatchAnalysisError("Video keyframe cloud processing is disabled")
            mode = "quality" if config.quality_mode == "high" else config.quality_mode
            result = self._video.extract_file(
                path,
                quality_mode=mode,
                max_frames=config.max_video_keyframes,
                cancellation_token=cancellation_token,
            )
            if coverage_details is not None:
                coverage_details.update(video_duration_seconds=result.duration_seconds,
                                        video_timestamps_seconds=tuple(result.timestamps_seconds))
            return ContentKind.VIDEO, tuple(result.payloads)
        if extension == ".pdf":
            metadata = extractor_metadata or {}
            total = metadata.get("pages")
            text_pages = self._pdf_text_pages(text, metadata, total)
            selected = None
            render_cap = min(8, config.max_pdf_pages,
                getattr(self._pdf, "config", PdfRenderConfig()).max_pages)
            if text.strip():
                if not config.allow_text_cloud:
                    raise BatchAnalysisError("Text cloud processing is disabled")
                if text_pages is None or len(text_pages) == total or not config.allow_vision_cloud:
                    return ContentKind.TEXT, ()
                # Apply the existing visual capability gate before rendering or
                # any credential/provider action. No silent provider switch.
                decision = self._degradation.decide(capabilities, ContentKind.SCANNED_PDF)
                if decision.degraded:
                    raise BatchAnalysisError(decision.user_message_id or decision.reason)
                text_set = set(text_pages)
                selected = tuple(islice((index for index in range(total)
                                         if index not in text_set), render_cap))
            if not config.allow_vision_cloud:
                raise BatchAnalysisError("Vision cloud processing is disabled")
            kwargs = dict(max_pages=render_cap, cancellation_token=cancellation_token)
            if selected is not None:
                kwargs["page_indices"] = selected
            result = self._pdf.render_file(path, **kwargs)
            rendered = tuple(result.rendered_page_indices)
            actual_total = result.total_page_count
            if (type(actual_total) is not int or not 1 <= actual_total <= 2**31 - 1
                    or len(rendered) > render_cap or len(rendered) != len(result.payloads)
                    or any(type(i) is not int or not 0 <= i < actual_total for i in rendered)
                    or tuple(sorted(set(rendered))) != rendered
                    or any(payload.source_index != index or payload.kind != "rendered_scan_page"
                           for index, payload in zip(rendered, result.payloads))
                    or (selected is not None and (actual_total != total or rendered != selected))):
                raise BatchAnalysisError("Invalid PDF rendering coverage")
            if coverage_details is not None:
                coverage_details.update(pdf_total_pages=actual_total,
                                        rendered_page_indices=rendered)
            # Mixed requests remain text-kind while retaining prepared page
            # images; all-scan requests retain their established scan-kind.
            return (ContentKind.TEXT if text.strip() else ContentKind.SCANNED_PDF), tuple(result.payloads)
        if not config.allow_text_cloud:
            raise BatchAnalysisError("Text cloud processing is disabled")
        return ContentKind.TEXT, ()

    @staticmethod
    def _check_cancelled(cancellation_token: Callable[[], bool] | None) -> None:
        if cancellation_token is not None and cancellation_token():
            raise BatchAnalysisError("Analysis was cancelled")

    @staticmethod
    def _content_prompt(kind: ContentKind) -> str:
        return {
            ContentKind.IMAGE: "Analyze the prepared local image for filename metadata.",
            ContentKind.SCANNED_PDF: "Analyze the prepared scanned document pages for filename metadata.",
            ContentKind.VIDEO: "Analyze locally extracted video keyframes as images for filename metadata.",
        }.get(kind, "Generate structured filename metadata from the extracted content.")

    @staticmethod
    def _safe_metadata(metadata, kind, payloads):
        safe = {
            str(key): value for key, value in metadata.items()
            if "path" not in str(key).casefold()
        }
        safe["content_kind"] = kind.value
        safe["prepared_visual_count"] = len(payloads)
        return safe

    @staticmethod
    def _schema_for_template(template):
        enabled = {
            field.dc_name for field in template.fields
            if field.enabled and field.dc_name in _NAMING_FIELD_NAMES
        }
        required = [
            name for name in _NAMING_FIELD_NAMES
            if name in enabled and f"{{{name}}}" in template.pattern
        ]
        descriptions = {
            "dcDate": f"Document date formatted exactly as {template.date_format.value}",
            "dcTitle": "Concise descriptive title without a file extension",
            "dcSubject": "General subject category",
            "dcType": "General document or media type",
            "dcCreator": "Creator or author when evidenced",
            "dcIdentifier": "Stable identifier when evidenced",
            "extOrganization": "Organization when evidenced",
            "extProject": "Project when evidenced",
            "extStatus": "Lifecycle status when evidenced",
            "extVersion": "Version when evidenced",
        }
        return {
            "type": "object",
            "properties": {
                name: {
                    "type": "string", "maxLength": 200,
                    "description": descriptions[name],
                }
                for name in _NAMING_FIELD_NAMES
            },
            "required": required,
            "additionalProperties": False,
        }
