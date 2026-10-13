"""Synthetic routing/security evidence, never real-model quality evidence."""
from dataclasses import FrozenInstanceError, replace, dataclass, field
from threading import Event
from types import SimpleNamespace
import copy
import io
import time

import pytest
from PIL import Image

from src.core.batch_analysis import BatchAnalysisError, BatchAnalysisService
from src.core.naming_fields import NamingFields
from src.core.processing_authority import (
    LocalReadiness, ProcessingAuthority, ProcessingMode, ProcessingSuperseded, CloudDispatchBlocked,
)
from src.core.provider_profile import ProviderProfile
from src.core.provider_protocol import ProviderCapabilities, ProviderResponse, prepare_visual_payload
from src.core.template_model import OutputLanguage, Template, TemplateField
from src.models.app_config import AppConfig
from src.services.local_ai.inference_request import LocalInferenceResult, LocalNamingRequest, prepare_request
from src.services.local_ai.preparation_protocol import LocalPreparationResult, PreparationCoverage
from src.services.retry_policy import RetryExecutionResult


def template():
    return Template(name="Private template", pattern="{dcTitle}",
                    fields=(TemplateField("dcTitle", "Title"),))


def visual(kind="resized_image", index=0):
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(stream, "PNG")
    version, provenance = {
        "resized_image": ("image-v1", "local-image"),
        "rendered_scan_page": ("pdf-v1+image-v1", "local-pdf-page"),
        "video_keyframe": ("video-v1+image-v1", "local-video-frame"),
    }[kind]
    return prepare_visual_payload(kind=kind, mime_type="image/png", data=stream.getvalue(),
        width=8, height=8, source_index=index, preprocessing_version=version, provenance=provenance)


class Preparation:
    def __init__(self):
        self.calls = []
        self.result = LocalPreparationResult("项目报告", (), PreparationCoverage("text", sections_processed=1), (), "balanced")
        self.hook = lambda: None

    def prepare(self, path, **kwargs):
        self.calls.append((path, kwargs))
        self.hook()
        return replace(self.result, effective_quality=kwargs["quality_mode"])


class Inference:
    def __init__(self):
        self.calls = []
        self.result = LocalInferenceResult(True, NamingFields(dcTitle="项目报告"), None, "b" * 64, .1)
        self.hook = lambda: None

    def infer(self, request, **kwargs):
        prepare_request(request)  # Exercise real bounds/evidence protocol.
        self.calls.append((request, kwargs))
        self.hook()
        return self.result


def setup_service(tmp_path, *, mode=ProcessingMode.LOCAL, ready=True, **overrides):
    authority = ProcessingAuthority(initial_mode=mode)
    if ready and mode is ProcessingMode.LOCAL:
        authority.set_local_state(authority.snapshot().generation, LocalReadiness.READY, engine_fingerprint="a" * 64)
    config = AppConfig(allow_text_cloud=False, allow_vision_cloud=False, allow_video_keyframes_cloud=False)
    preparation, inference, calls = Preparation(), Inference(), []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("cloud boundary touched")

    options = dict(profile_provider=forbidden, credential_provider=forbidden,
        adapter_factory=forbidden, managed_adapter_factory=forbidden,
        config_provider=lambda: config, template_provider=lambda _: template(),
        processing_authority=authority, local_inference_service=inference,
        local_preparation_service=preparation)
    options.update(overrides)
    service = BatchAnalysisService(**options)
    source = tmp_path / "unrelated-private-source.txt"
    source.write_text("synthetic input", encoding="utf-8")
    return SimpleNamespace(service=service, source=source, authority=authority,
        config=config, preparation=preparation, inference=inference, cloud_calls=calls)


def capture(env, **kwargs):
    return env.service.capture_work(str(env.source), "task", task_attempt_id="attempt", task_cancel_event=Event(), **kwargs)


@pytest.mark.parametrize("language,locale", [
    (OutputLanguage.ZH, "zh-CN"), (OutputLanguage.ZH_HK, "zh-HK"),
    (OutputLanguage.EN, "en-US"), (OutputLanguage.JA, "ja-JP"),
    (OutputLanguage.ES, "es-ES"),
])
@pytest.mark.parametrize("override", [False, True])
def test_saved_language_and_enum_override_admit_plain_local_locale(tmp_path, language, locale, override):
    selected = replace(template(), output_language=language)
    env = setup_service(tmp_path, template_provider=lambda _: selected)
    work = capture(env, output_language=language if override else "")
    assert type(work.locale) is str and work.locale == locale
    assert work.template.output_language is language
    request = LocalNamingRequest("synthetic evidence", (), work.locale, "template", template=work.template)
    assert request.locale == locale
    env.service.run_prepared(work)
    assert type(env.inference.calls[0][0].locale) is str
    assert env.cloud_calls == []


@pytest.mark.parametrize("locale", ["zh-CN", "zh-HK", "en-US"])
def test_explicit_locale_override_preserves_saved_hk_template(tmp_path, locale):
    selected = replace(template(), output_language=OutputLanguage.ZH_HK)
    env = setup_service(tmp_path, template_provider=lambda _: selected)
    work = capture(env, output_language=locale)
    assert type(work.locale) is str and work.locale == locale
    assert work.template.output_language is OutputLanguage.ZH_HK
    env.service.run_prepared(work)
    assert env.inference.calls[0][0].locale == locale
    assert env.cloud_calls == []


@pytest.mark.parametrize("language", ["not-a-language", "ja-JP", "es-ES", 42, object()])
def test_invalid_language_overrides_remain_rejected_at_admission(tmp_path, language):
    env = setup_service(tmp_path)
    with pytest.raises(BatchAnalysisError, match="Invalid analysis settings or template"):
        capture(env, output_language=language)
    assert not env.preparation.calls and not env.inference.calls and not env.cloud_calls


def test_local_runs_without_any_cloud_boundary_and_preserves_authentic_context(tmp_path):
    env = setup_service(tmp_path)
    work = capture(env)
    outcome = env.service.run_prepared(work)
    assert outcome.suggested_name == "项目报告.txt"
    assert outcome.context is work.context
    assert outcome.request_engine_identity == "b" * 64
    assert env.authority.is_current(work.context)
    assert env.authority.snapshot().engine_fingerprint == "a" * 64
    assert env.cloud_calls == []
    request, infer_kw = env.inference.calls[0]
    _, prep_kw = env.preparation.calls[0]
    assert request.text == "项目报告" and request.visuals == ()
    assert infer_kw["deadline"] == prep_kw["deadline"] == work.deadline
    assert 500 < work.deadline - time.monotonic() <= 600
    assert infer_kw["is_current"]() and not infer_kw["cancelled"]()


def test_not_ready_rejects_before_settings_or_profile(tmp_path):
    env = setup_service(tmp_path, ready=False, config_provider=lambda: pytest.fail("settings read"))
    with pytest.raises(Exception, match="LOCAL_PROCESSING_UNAVAILABLE"):
        capture(env)
    assert env.cloud_calls == []


@pytest.mark.parametrize("missing", ["processing_authority", "local_inference_service", "local_preparation_service"])
def test_partial_managed_constructor_never_downgrades(tmp_path, missing):
    with pytest.raises(ValueError, match="Managed analysis requires"):
        setup_service(tmp_path, **{missing: None})


def test_capture_has_no_file_or_preparation_io_and_freezes_allowlist(tmp_path):
    env = setup_service(tmp_path)
    env.config.api_key = "secret-marker"
    env.config.arbitrary_extra = {"nested": ["secret-marker"]}
    env.source.unlink()
    work = capture(env)
    env.config.max_content_chars = 42
    env.config.quality_mode = "high"
    assert work.settings.max_content_chars == 4000
    assert work.settings.quality_mode == "balanced"
    assert not hasattr(work.settings, "api_key") and not hasattr(work.settings, "arbitrary_extra")
    assert "secret-marker" not in repr(work)
    assert "Private template" not in repr(work) and str(env.source) not in repr(work)
    assert not env.preparation.calls
    with pytest.raises(FrozenInstanceError):
        work.task_id = "other"


def test_generation_switch_during_capture_rejects_no_retry(tmp_path):
    env = setup_service(tmp_path)
    calls = []
    def config():
        calls.append(1)
        env.authority.select_local()
        return env.config
    env.service._config_provider = config
    with pytest.raises(ProcessingSuperseded):
        capture(env)
    assert calls == [1] and not env.preparation.calls


@pytest.mark.parametrize("change", ["queue", "prepare", "infer", "cancel"])
def test_stale_or_cancelled_work_is_never_a_value(tmp_path, change):
    env = setup_service(tmp_path)
    work = capture(env)
    if change == "queue":
        env.authority.select_local()
    elif change == "prepare":
        env.preparation.hook = env.authority.select_local
    elif change == "infer":
        env.inference.hook = env.authority.select_local
    else:
        work.context.task_cancel_event.set()
    with pytest.raises(ProcessingSuperseded):
        env.service.run_prepared(work)
    assert env.cloud_calls == []
    if change in ("queue", "cancel"):
        assert not env.preparation.calls


@pytest.mark.parametrize("mutation", ["copy", "replace", "context", "settings", "attempt"])
def test_forged_work_rejected_before_file_or_credential_work(tmp_path, mutation):
    env = setup_service(tmp_path)
    work = capture(env)
    forged = {
        "copy": lambda: copy.copy(work),
        "replace": lambda: replace(work),
        "context": lambda: replace(work, context=replace(work.context)),
        "settings": lambda: replace(work, settings=replace(work.settings, max_content_chars=20)),
        "attempt": lambda: replace(work, task_attempt_id="other"),
    }[mutation]()
    env.source.unlink()
    with pytest.raises(ProcessingSuperseded):
        env.service.run_prepared(forged)
    assert not env.preparation.calls and not env.cloud_calls


@pytest.mark.parametrize("error", ["NOT_READY", "RESOURCE_MISSING", "ENGINE_FAILED"])
def test_local_failure_is_fixed_safe_and_never_falls_back(tmp_path, error):
    env = setup_service(tmp_path)
    env.inference.result = LocalInferenceResult(False, None, error + str(env.source), None, .1)
    with pytest.raises(BatchAnalysisError, match="^Local analysis failed$"):
        env.service.run_prepared(capture(env))
    assert env.cloud_calls == []


def test_quality_override_and_video_limits_control_actual_preparation(tmp_path):
    env = setup_service(tmp_path)
    env.source = env.source.with_suffix(".mp4")
    env.source.write_bytes(b"not-video-synthetic")
    env.preparation.result = LocalPreparationResult("", tuple(visual("video_keyframe", i) for i in range(4)),
        PreparationCoverage("video", text_source="none", video_duration_seconds=10,
                            video_timestamps_seconds=(0., 2., 4., 6.)), ("video_sampled",), "economy")
    outcome = env.service.run_prepared(capture(env, quality_mode="economy"))
    _, kw = env.preparation.calls[0]
    assert kw["quality_mode"] == outcome.effective_quality == "economy"
    assert kw["limits"].max_video_frames == 4
    request = env.inference.calls[0][0]
    assert request.quality == "economy" and len(request.visuals) == 4 and request.text == ""
    assert str(env.source) not in repr(request) and env.source.name not in request.text


def test_insufficient_video_cap_is_specific_safe_error(tmp_path):
    env = setup_service(tmp_path)
    env.source = env.source.with_suffix(".mp4")
    env.config.max_video_keyframes = 3
    with pytest.raises(BatchAnalysisError, match="Video frame limit is below the selected quality requirement"):
        capture(env, quality_mode="economy")


def test_pdf_default_page_and_visual_limits_are_usable_and_independent(tmp_path):
    env = setup_service(tmp_path)
    env.source = env.source.with_suffix(".pdf")
    env.source.write_bytes(b"synthetic-source-pdf")
    env.preparation.result = LocalPreparationResult("", (visual("rendered_scan_page", 0),),
        PreparationCoverage("scanned_pdf", text_source="none", sections_processed=1,
            sections_total=3, pdf_total_pages=3, text_page_indices=(0,), rendered_page_indices=(0,)),
        ("pdf_page_limit", "no_text_content"), "balanced")
    outcome = env.service.run_prepared(capture(env))
    limits = env.preparation.calls[0][1]["limits"]
    assert limits.max_pdf_pages == 50 and limits.max_visuals == 6
    assert outcome.content_kind.value == "scanned_pdf"
    assert outcome.coverage.rendered_page_indices == (0,) and outcome.coverage.pdf_total_pages == 3
    assert "pdf_page_limit" in outcome.warning_codes
    assert env.inference.calls[0][0].text == ""


def test_text_at_utf8_boundary_is_not_automatically_partial(tmp_path):
    env = setup_service(tmp_path)
    env.config.max_content_chars = 32768
    env.preparation.result = LocalPreparationResult("a" * 32768, (), PreparationCoverage("text", sections_processed=1), (), "balanced")
    outcome = env.service.run_prepared(capture(env))
    request = env.inference.calls[0][0]
    assert len(request.text.encode("utf-8")) == 32768 and request.text_layout == "contiguous"
    assert not outcome.coverage.text_truncated and outcome.warning_codes == ()


def test_visual_and_long_line_text_is_grouped_without_discarding_content(tmp_path):
    env = setup_service(tmp_path)
    env.source = env.source.with_suffix(".png")
    env.source.write_bytes(b"synthetic-image")
    text = "\n".join(f"actual-{i}" for i in range(90))
    env.preparation.result = LocalPreparationResult(text, (visual(),), PreparationCoverage("image"), (), "balanced")
    outcome = env.service.run_prepared(capture(env))
    request = env.inference.calls[0][0]
    assert len(request.text.splitlines()) <= 64
    for i in range(90):
        assert f"actual-{i}" in request.text
    assert not outcome.coverage.text_truncated


def test_managed_wrappers_do_not_implicitly_recapture(tmp_path):
    env = setup_service(tmp_path)
    with pytest.raises(BatchAnalysisError, match="capture_work and run_prepared"):
        env.service(str(env.source), "task")
    assert not env.preparation.calls and not env.cloud_calls


def cloud_env(tmp_path, **overrides):
    import src.core.processing_analysis as contracts
    assert hasattr(contracts, "cloud_engine_fingerprint"), "canonical cloud fingerprint missing"
    profile = ProviderProfile(id="safe", model="synthetic", base_url="https://example.invalid/v1",
        needs_connection_verification=False, capabilities=ProviderCapabilities(text=True, json_schema=True))
    calls = []
    response = ProviderResponse(fields={"dcTitle": "项目报告"})
    def factory(selected, credential, *, processing_dispatch, retry_executor):
        calls.append(("factory", selected, credential, processing_dispatch, retry_executor))
        def invoke(request, *, cancellation_token):
            calls.append(("invoke", request, cancellation_token))
            # Exercise the actual authority commitment contract; no network.
            receipt = processing_dispatch.authority.commit_cloud_attempt(processing_dispatch.context, "send-1")
            processing_dispatch.authority.finish_attempt(receipt)
            return RetryExecutionResult(True, response, (), None, None)
        return SimpleNamespace(invoke=invoke)
    env = setup_service(tmp_path, mode=ProcessingMode.CLOUD,
        profile_provider=lambda: profile, credential_provider=lambda selected: calls.append(("credential", selected)) or "ephemeral-test-key",
        managed_adapter_factory=factory, **overrides)
    env.authority.bind_cloud_engine(contracts.cloud_engine_fingerprint(profile))
    env.config.allow_text_cloud = True
    env.profile, env.calls = profile, calls
    return env


def synthetic_pdf(path, *, text_pages=1, scan_pages=1):
    """Real selectable-text pages and raster-only pages; no private input."""
    import pymupdf
    image = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(image, "PNG")
    with pymupdf.open() as document:
        for _ in range(text_pages):
            page = document.new_page(width=120, height=120)
            page.insert_text((10, 20), "Synthetic cover title", fontsize=8)
        for _ in range(scan_pages):
            page = document.new_page(width=120, height=120)
            page.insert_image(page.rect, stream=image.getvalue())
        document.save(path)


def mixed_cloud_env(tmp_path, *, vision=True, text_pages=1, scan_pages=1, **overrides):
    from src.core.processing_analysis import cloud_engine_fingerprint
    env = cloud_env(tmp_path, **overrides)
    profile = replace(env.profile, capabilities=ProviderCapabilities(
        text=True, vision=vision, multi_image=True, json_schema=True))
    env.service._profile_provider = lambda: profile
    env.authority.bind_cloud_engine(cloud_engine_fingerprint(profile))
    env.config.allow_vision_cloud = True
    env.source = env.source.with_suffix(".pdf")
    synthetic_pdf(env.source, text_pages=text_pages, scan_pages=scan_pages)
    return env


def test_real_mixed_cloud_pdf_sends_only_cover_text_and_missing_page_image(tmp_path):
    from src.core.managed_watch_metadata import ManagedWatchMetadata, auto_apply_review_reason
    env = mixed_cloud_env(tmp_path)
    outcome = env.service.run_prepared(capture(env))
    request = next(call[1] for call in env.calls if call[0] == "invoke")
    assert request.extracted_text.strip() == "Synthetic cover title"
    assert len(request.visual_payloads) == 1
    payload, = request.visual_payloads
    assert payload.source_index == 1 and payload.kind == "rendered_scan_page"
    assert payload.data != env.source.read_bytes() and not payload.data.startswith(b"%PDF")
    assert str(env.source) not in repr(request) and env.source.name not in repr(request)
    assert outcome.coverage.text_page_indices == (0,)
    assert outcome.coverage.rendered_page_indices == (1,)
    assert outcome.coverage.sections_processed == outcome.coverage.pdf_total_pages == 2
    assert outcome.warning_codes == ()
    assert auto_apply_review_reason(ManagedWatchMetadata(outcome.content_kind.value,
        "balanced", "balanced", outcome.coverage, outcome.warning_codes)) == ""


@pytest.mark.parametrize("case", ["vision-off", "legacy", "malformed", "render-cap"])
def test_mixed_cloud_partial_evidence_never_grants_auto_apply(tmp_path, case):
    from src.core.managed_watch_metadata import ManagedWatchMetadata, auto_apply_review_reason
    env = mixed_cloud_env(tmp_path, scan_pages=7 if case == "render-cap" else 1)
    if case == "vision-off":
        env.config.allow_vision_cloud = False
    elif case in {"legacy", "malformed"}:
        metadata = {"pages": 2, "pages_processed": 2, "sections_processed": 2,
                    "sections_total": 2, "coverage_reason": "complete"}
        if case == "malformed": metadata["text_page_indices"] = (False, 1)
        env.service._extract_content = lambda *_: ("Synthetic cover title", metadata)
    outcome = env.service.run_prepared(capture(env))
    record = ManagedWatchMetadata(outcome.content_kind.value, "balanced", "balanced",
                                  outcome.coverage, outcome.warning_codes)
    assert auto_apply_review_reason(record) == "partial_content"
    assert "pdf_page_limit" in outcome.warning_codes
    assert outcome.coverage.text_page_indices == ((0,) if case in {"vision-off", "render-cap"} else ())
    if case == "render-cap":
        assert outcome.coverage.rendered_page_indices == tuple(range(1, 7))
    else:
        assert outcome.coverage.rendered_page_indices == ()


def test_mixed_pdf_unsupported_vision_fails_before_credentials(tmp_path):
    env = mixed_cloud_env(tmp_path, vision=False)
    with pytest.raises(BatchAnalysisError, match="capability.vision_unavailable_scanned_pdf"):
        env.service.run_prepared(capture(env))
    assert env.calls == []


def test_legacy_mixed_pdf_degradation_also_precedes_credential_read(tmp_path):
    profile = ProviderProfile(id="synthetic", model="synthetic", capabilities=ProviderCapabilities(
        text=True, json_schema=True))
    calls = []
    source = tmp_path / "legacy-mixed.pdf"
    synthetic_pdf(source)
    service = BatchAnalysisService(profile_provider=lambda: profile,
        credential_provider=lambda _: calls.append("credential") or "synthetic-key",
        adapter_factory=lambda *_: pytest.fail("unsupported provider invoked"),
        config_provider=lambda: AppConfig(), template_provider=lambda _: template())
    with pytest.raises(BatchAnalysisError, match="capability.vision_unavailable_scanned_pdf"):
        service(str(source), "synthetic-legacy")
    assert calls == []


@pytest.mark.parametrize("facts", [(True,), (0, 0), (1, 0), (-1,), (2,), (0.0,), [0], "0"])
def test_malformed_actual_text_page_facts_remain_partial(tmp_path, facts):
    from src.core.managed_watch_metadata import ManagedWatchMetadata, auto_apply_review_reason
    env = mixed_cloud_env(tmp_path)
    env.service._extract_content = lambda *_: ("Synthetic cover title", {
        "pages": 2, "pages_processed": 2, "sections_processed": 2,
        "sections_total": 2, "coverage_reason": "complete", "text_page_indices": facts})
    result = env.service.run_prepared(capture(env))
    assert result.coverage.text_page_indices == result.coverage.rendered_page_indices == ()
    assert auto_apply_review_reason(ManagedWatchMetadata(result.content_kind.value,
        "balanced", "balanced", result.coverage, result.warning_codes)) == "partial_content"


def test_real_all_scan_pdf_retains_bounded_prepared_visual_behavior(tmp_path):
    env = mixed_cloud_env(tmp_path, text_pages=0, scan_pages=2)
    result = env.service.run_prepared(capture(env))
    request = next(call[1] for call in env.calls if call[0] == "invoke")
    assert result.content_kind.value == "scanned_pdf"
    assert result.coverage.text_page_indices == ()
    assert result.coverage.rendered_page_indices == (0, 1)
    assert [payload.source_index for payload in request.visual_payloads] == [0, 1]
    assert result.warning_codes == ()


@pytest.mark.parametrize("limit,reason", [(1, "section_limit"), (2, "character_limit")])
def test_real_mixed_pdf_page_and_character_limits_remain_explicit(tmp_path, limit, reason):
    env = mixed_cloud_env(tmp_path)
    env.config.max_pdf_pages = limit
    if reason == "character_limit": env.config.max_content_chars = 5
    result = env.service.run_prepared(capture(env))
    assert result.coverage.text_limit_reason == reason and result.coverage.text_truncated
    assert ("section_limit" if reason == "section_limit" else "text_character_limit") in result.warning_codes


def test_cancel_between_mixed_pdf_text_and_render_never_dispatches_provider(tmp_path):
    from src.core.batch_analysis import _default_extract
    env = mixed_cloud_env(tmp_path)
    cancel = Event()
    def extracted(path, limit):
        result = _default_extract(path, limit, max_pdf_pages=2)
        cancel.set()
        return result
    env.service._extract_content = extracted
    with pytest.raises(ProcessingSuperseded):
        env.service.run_prepared(capture(env), cancellation_token=cancel.is_set)
    assert env.calls == []


def test_real_all_text_150_page_pdf_keeps_cloud_200_allowance_without_vision(tmp_path):
    env = mixed_cloud_env(tmp_path, vision=False, text_pages=150, scan_pages=0)
    env.config.max_content_chars = 10000
    env.config.max_pdf_pages = 200
    env.config.allow_vision_cloud = False
    outcome = env.service.run_prepared(capture(env))
    assert outcome.coverage.text_page_indices == tuple(range(150))
    assert outcome.coverage.rendered_page_indices == () and outcome.warning_codes == ()
    assert not next(call[1] for call in env.calls if call[0] == "invoke").visual_payloads


def test_cloud_profile_settings_retry_timeout_are_captured_without_credentials(tmp_path):
    env = cloud_env(tmp_path)
    work = capture(env)
    assert not env.calls and work.profile == env.profile
    env.config.request_timeout_seconds = 60
    env.config.max_retries = 0
    env.service._profile_provider = lambda: pytest.fail("profile recaptured")
    outcome = env.service.run_prepared(work)
    assert outcome.suggested_name == "项目报告.txt"
    credential, factory, invoke = env.calls
    assert credential[1] is work.profile and factory[1] is work.profile
    assert factory[3].context is work.context and factory[4]._policy.max_retries == 3
    assert invoke[1].timeout == 30 and invoke[1].quality_mode == "balanced"
    assert not env.preparation.calls and not env.inference.calls


@pytest.mark.parametrize("invalid", ["missing", "unverified", "unbound", "switch"])
def test_cloud_capture_invalid_profiles_cannot_rebind_or_read_credentials(tmp_path, invalid):
    env = cloud_env(tmp_path)
    before = env.authority.snapshot()
    if invalid == "missing":
        env.service._profile_provider = lambda: None
    elif invalid == "unverified":
        env.service._profile_provider = lambda: replace(env.profile, needs_connection_verification=True)
    elif invalid == "unbound":
        env.service._profile_provider = lambda: replace(env.profile, model="different")
    else:
        def switched():
            env.authority.select_local()
            return env.profile
        env.service._profile_provider = switched
    with pytest.raises((BatchAnalysisError, ProcessingSuperseded, CloudDispatchBlocked)):
        capture(env)
    assert not env.calls
    if invalid != "switch":
        assert env.authority.snapshot() == before


def test_cloud_switch_in_credential_callback_blocks_factory(tmp_path):
    env = cloud_env(tmp_path)
    work = capture(env)
    def credential(_profile):
        env.authority.select_local()
        return "ephemeral-key"
    env.service._credential_provider = credential
    with pytest.raises(ProcessingSuperseded):
        env.service.run_prepared(work)
    assert not env.calls


def test_cloud_consent_still_required(tmp_path):
    env = cloud_env(tmp_path)
    env.config.allow_text_cloud = False
    with pytest.raises(BatchAnalysisError, match="Text cloud processing is disabled"):
        env.service.run_prepared(capture(env))
    assert not env.calls


@pytest.mark.parametrize("mode", ["smart", "template"])
@pytest.mark.parametrize("locale,title", [("zh-CN", "校园网络维护合同"), ("zh-HK", "校園網絡維護合同"), ("en-US", "Campus network maintenance contract")])
def test_modes_and_locales_use_exact_submitted_text_and_protect_extension(tmp_path, mode, locale, title):
    env = setup_service(tmp_path)
    env.preparation.result = replace(env.preparation.result, text=title)
    fields = NamingFields(dcTitle=title) if mode == "template" else {
        "understood": True, "language": locale,
        "parts": [{"role": "topic", "value": title, "evidence": title, "evidence_source": "text"}],
    }
    env.inference.result = LocalInferenceResult(True, fields, None, "c"*64, .1)
    outcome = env.service.run_prepared(capture(env, naming_mode=mode, output_language=locale))
    expected = title.replace(" ", "_") if mode == "template" else title
    assert outcome.suggested_name == expected + ".txt"
    request = env.inference.calls[0][0]
    assert request.locale == locale and request.naming_mode == mode


@pytest.mark.parametrize("fields", [None, {"dcTitle": "wrong-type"}, NamingFields(dcTitle=""), NamingFields(dcTitle=42)])
def test_template_success_requires_strict_nonblank_fields(tmp_path, fields):
    env = setup_service(tmp_path)
    env.inference.result = LocalInferenceResult(True, fields, None, "c"*64, .1)
    with pytest.raises(BatchAnalysisError):
        env.service.run_prepared(capture(env))


def test_stale_failure_is_superseded_not_local_failure(tmp_path):
    env = setup_service(tmp_path)
    env.inference.hook = env.authority.select_local
    env.inference.result = LocalInferenceResult(False, None, "failure", None, 0)
    with pytest.raises(ProcessingSuperseded):
        env.service.run_prepared(capture(env))


def test_caller_callback_switch_blocks_preparation_without_authority_deadlock(tmp_path):
    env = setup_service(tmp_path)
    work = capture(env)
    def cancelled():
        env.authority.select_local()
        return False
    with pytest.raises(ProcessingSuperseded):
        env.service.run_prepared(work, cancellation_token=cancelled)
    assert not env.preparation.calls


def test_admission_deadline_includes_queue(tmp_path, monkeypatch):
    env = setup_service(tmp_path)
    work = capture(env)
    monkeypatch.setattr("src.core.batch_analysis.time.monotonic", lambda: work.deadline + 1)
    with pytest.raises(BatchAnalysisError, match="Local analysis timed out"):
        env.service.run_prepared(work)
    assert not env.preparation.calls


@pytest.mark.parametrize("stage", ["config", "template", "prepare", "infer"])
def test_callback_errors_are_redacted_and_never_include_path_or_secret(tmp_path, stage):
    env = setup_service(tmp_path)
    def broken(*args, **kwargs):
        raise RuntimeError("secret-marker " + str(env.source))
    if stage == "config":
        env.service._config_provider = broken
    elif stage == "template":
        env.service._template_provider = broken
    elif stage == "prepare":
        env.preparation.prepare = broken
    else:
        env.inference.infer = broken
    with pytest.raises(BatchAnalysisError) as caught:
        env.service.run_prepared(capture(env))
    assert "secret-marker" not in str(caught.value) and str(env.source) not in str(caught.value)


def test_template_snapshot_does_not_retain_mutable_typed_lookalikes(tmp_path):
    env = setup_service(tmp_path)
    selected = template()
    # Template itself is frozen, but an invalid mutable field can be supplied
    # because the older domain constructor only checks selected attributes.
    invalid = replace(selected, fields=(SimpleNamespace(dc_name="dcTitle", display_name="Title", order=1, enabled=True, id="x"),))
    env.service._template_provider = lambda _: invalid
    with pytest.raises(BatchAnalysisError):
        capture(env)


@pytest.mark.parametrize("case", ["text-limit", "visual-limit", "quality-mismatch"])
def test_preparation_is_validated_against_captured_limits_before_inference(tmp_path, case):
    env = setup_service(tmp_path)
    if case == "text-limit":
        env.config.max_content_chars = 3
        env.preparation.result = replace(env.preparation.result, text="four")
    elif case == "visual-limit":
        env.source = env.source.with_suffix(".pdf")
        env.source.write_bytes(b"synthetic")
        env.config.max_pdf_pages = 1
        env.preparation.result = LocalPreparationResult("", tuple(visual("rendered_scan_page", i) for i in range(2)),
            PreparationCoverage("scanned_pdf", text_source="none", pdf_total_pages=2,
                sections_total=2, rendered_page_indices=(0, 1)), (), "balanced")
    else:
        env.preparation.prepare = lambda *a, **kw: replace(env.preparation.result, effective_quality="economy")
    with pytest.raises(BatchAnalysisError):
        env.service.run_prepared(capture(env))
    assert not env.inference.calls


@pytest.mark.parametrize("mode", ["smart", "template"])
def test_empty_sheet_labels_do_not_prove_understanding(tmp_path, mode):
    env = setup_service(tmp_path)
    env.source = env.source.with_suffix(".xlsx")
    env.source.write_bytes(b"synthetic-sheet")
    env.preparation.result = replace(env.preparation.result, text="[Sheet: fake-secret-source]")
    with pytest.raises(BatchAnalysisError):
        env.service.run_prepared(capture(env, naming_mode=mode))
    assert not env.inference.calls


def test_same_ready_service_mixed_requests_does_not_change_generation(tmp_path):
    env = setup_service(tmp_path)
    generation = env.authority.snapshot().generation
    for mode in ("smart", "template"):
        for images in (False, True):
            text = "校园网络维护合同"
            env.preparation.result = LocalPreparationResult(text, (visual(),) if images else (),
                PreparationCoverage("image" if images else "text"), (), "balanced")
            fields = NamingFields(dcTitle=text) if mode == "template" else {"understood": True, "language": "zh-CN",
                "parts": [{"role": "topic", "value": text, "evidence": text, "evidence_source": "text"}]}
            env.inference.result = LocalInferenceResult(True, fields, None, ("c" if images else "d") * 64, .1)
            env.service.run_prepared(capture(env, naming_mode=mode))
            assert env.authority.snapshot().generation == generation


def test_cloud_media_outcome_uses_actual_rendered_page_selection(tmp_path):
    env = cloud_env(tmp_path)
    from src.core.processing_analysis import cloud_engine_fingerprint
    profile = replace(env.profile, capabilities=ProviderCapabilities(text=True, vision=True, multi_image=True, json_schema=True))
    env.service._profile_provider = lambda: profile
    env.authority.bind_cloud_engine(cloud_engine_fingerprint(profile))
    env.config.allow_vision_cloud = True
    env.source = env.source.with_suffix(".pdf")
    env.source.write_bytes(b"synthetic-not-pdf")
    env.service._extract_content = lambda *a: ("", {"pages": 9, "pages_processed": 2,
        "sections_processed": 2, "sections_total": 9, "coverage_reason": "section_limit"})
    env.service._pdf = SimpleNamespace(render_file=lambda *a, **kw: SimpleNamespace(
        payloads=(visual("rendered_scan_page", 0), visual("rendered_scan_page", 3)),
        rendered_page_indices=(0, 3), total_page_count=9))
    outcome = env.service.run_prepared(capture(env))
    assert outcome.coverage.content_kind == "scanned_pdf"
    assert outcome.coverage.rendered_page_indices == (0, 3)
    assert outcome.coverage.text_page_indices == () and outcome.coverage.pdf_total_pages == 9
    assert outcome.coverage.sections_processed == 2
    assert "pdf_page_limit" in outcome.warning_codes


def test_pdf_requested_200_retains_setting_but_prepares_bounded_100_with_factual_coverage(tmp_path):
    env = setup_service(tmp_path)
    env.config.max_pdf_pages = 200
    env.source = env.source.with_suffix(".pdf")
    env.source.write_bytes(b"synthetic")
    env.preparation.result = LocalPreparationResult("项目报告", (visual("rendered_scan_page", 0),),
        PreparationCoverage("pdf", sections_processed=100, sections_total=150,
            text_truncated=True, text_limit_reason="section_limit", pdf_total_pages=150,
            text_page_indices=tuple(range(100)), rendered_page_indices=(0,)),
        ("section_limit", "pdf_page_limit"), "balanced")
    work = capture(env)
    assert work.settings.max_pdf_pages == 200 and work.preparation_limits.max_pdf_pages == 100
    outcome = env.service.run_prepared(work)
    assert outcome.coverage.sections_processed == 100 and outcome.coverage.sections_total == 150
    assert outcome.coverage.text_truncated and "pdf_page_limit" in outcome.warning_codes
    assert outcome.content_kind.value == "text"  # Mixed PDF mapped deliberately, visuals retained.
    assert env.inference.calls[0][0].visuals


@pytest.mark.parametrize("title", ["CON", "NUL.txt", "a" * 260])
def test_template_rendered_filename_passes_existing_safety_validator(tmp_path, title):
    env = setup_service(tmp_path)
    env.inference.result = LocalInferenceResult(True, NamingFields(dcTitle=title), None, "b" * 64, .1)
    with pytest.raises(BatchAnalysisError, match="Invalid naming response"):
        env.service.run_prepared(capture(env))


@pytest.mark.parametrize("locale,source_title,expected_title", [
    ("zh-HK", "山岚社区雨水花园维护指引", "山嵐社區雨水花園維護指引"),
    ("zh-CN", "山嵐社區雨水花園維護指引", "山岚社区雨水花园维护指引"),
])
@pytest.mark.parametrize("mode", ["template", "smart"])
def test_managed_render_normalizes_after_grounded_fields_without_rewriting_evidence(
        tmp_path, locale, source_title, expected_title, mode):
    env = setup_service(tmp_path)
    text = source_title + " 2026-10-12 v1.2"
    env.preparation.result = replace(env.preparation.result, text=text)
    if mode == "template":
        fields = NamingFields(dcTitle=source_title)
        expected = expected_title + ".txt"
        cloud_fields = {"dcTitle": source_title}
    else:
        topic = "雨水花園" if locale == "zh-HK" else "雨水花园"
        entity = "山岚社区" if locale == "zh-HK" else "山嵐社區"
        fields = {"understood": True, "language": locale, "parts": [
            {"role": role, "value": value, "evidence": text, "evidence_source": "text"}
            for role, value in (("date", "2026-10-12"), ("entity", entity),
                                ("topic", topic), ("version", "v1.2"))]}
        expected = "2026-10-12_" + expected_title[:4] + "_" + topic + "_v1.2.txt"
        cloud_fields = fields
    before = copy.deepcopy(fields)
    env.inference.result = LocalInferenceResult(True, fields, None, "b" * 64, .1)
    work = capture(env, naming_mode=mode, output_language=locale)
    outcome = env.service.run_prepared(work)
    assert outcome.suggested_name == expected
    assert env.service._render_managed(work, cloud_fields, text, False, ".txt", local=False) == expected
    assert fields == before and env.inference.calls[0][0].text == text
    assert env.source.read_text(encoding="utf-8") == "synthetic input"
    assert not env.cloud_calls


@pytest.mark.parametrize("language", [OutputLanguage.EN, OutputLanguage.JA, OutputLanguage.ES])
def test_managed_other_locale_template_output_is_not_script_normalized(tmp_path, language):
    env = setup_service(tmp_path, template_provider=lambda _: replace(template(), output_language=language))
    title = "大学校園_Study_日本語_Español_v2.1"
    env.inference.result = LocalInferenceResult(True, NamingFields(dcTitle=title), None, "b" * 64, .1)
    assert env.service.run_prepared(capture(env)).suggested_name == title + ".txt"


@pytest.mark.parametrize("mode", ["template", "smart"])
@pytest.mark.parametrize("failure", ["unsafe", "overlong", "missing"])
def test_managed_conversion_failure_never_exposes_apply_eligible_name(tmp_path, monkeypatch, mode, failure):
    import opencc
    env = setup_service(tmp_path)
    fields = NamingFields(dcTitle="河流生态") if mode == "template" else {
        "understood": True, "language": "zh-HK", "parts": [{"role": "topic", "value": "河流生态",
        "evidence": "项目报告", "evidence_source": "text"}]}
    env.inference.result = LocalInferenceResult(True, fields, None, "b" * 64, .1)
    if failure == "missing":
        def fail(config):
            raise FileNotFoundError("private-marker")
        monkeypatch.setattr(opencc, "OpenCC", fail)
    else:
        converter = opencc.OpenCC("s2hk")
        output = "../逃逸" if failure == "unsafe" else "雨" * (256 if mode == "template" else 181)
        monkeypatch.setattr(converter, "convert", lambda value: output)
        monkeypatch.setattr(opencc, "OpenCC", lambda config: converter)
    with pytest.raises(BatchAnalysisError, match="^Invalid naming response$"):
        env.service.run_prepared(capture(env, naming_mode=mode, output_language="zh-HK"))
    assert not env.cloud_calls


def test_smart_grounding_rejects_raw_evidence_before_loading_converter(tmp_path, monkeypatch):
    import opencc
    env = setup_service(tmp_path)
    fields = {"understood": True, "language": "zh-HK", "parts": [{"role": "topic", "value": "河流生态",
        "evidence": "absent evidence", "evidence_source": "text"}]}
    env.inference.result = LocalInferenceResult(True, fields, None, "b" * 64, .1)
    monkeypatch.setattr(opencc, "OpenCC", lambda config: pytest.fail("conversion preceded evidence validation"))
    with pytest.raises(Exception, match="smart.error.ungrounded"):
        env.service.run_prepared(capture(env, naming_mode="smart", output_language="zh-HK"))


def test_source_size_guard_precedes_preparation(tmp_path):
    env = setup_service(tmp_path)
    env.config.max_file_size_mb = 1
    env.source.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(BatchAnalysisError, match="size limit"):
        env.service.run_prepared(capture(env))
    assert not env.preparation.calls


@pytest.mark.parametrize("mode", ["smart", "template"])
def test_image_metadata_has_no_text_prompt_or_source_name_in_either_mode(tmp_path, mode):
    env = setup_service(tmp_path)
    env.source = env.source.with_suffix(".png")
    env.source.write_bytes(b"synthetic-only")
    env.preparation.result = LocalPreparationResult("", (visual(),),
        PreparationCoverage("image", text_source="metadata_only"), ("metadata_only",), "balanced")
    fields = NamingFields(dcTitle="红色自行车停靠路边") if mode == "template" else {
        "understood": True, "language": "zh-CN", "parts": [{"role": "topic", "value": "红色自行车停靠路边",
            "evidence": "图像中有一辆红色自行车", "evidence_source": "visual"}]}
    env.inference.result = LocalInferenceResult(True, fields, None, "b" * 64, .1)
    env.service.run_prepared(capture(env, naming_mode=mode))
    request = env.inference.calls[0][0]
    assert request.text == "" and not hasattr(request, "source_path")
    assert not hasattr(request, "extension") and not hasattr(request, "api_key")


@pytest.mark.parametrize("kind", ["over-bytes", "over-count"])
def test_protocol_rejects_oversized_payload_before_inference(tmp_path, kind):
    env = setup_service(tmp_path)
    result = env.preparation.result
    if kind == "over-bytes":
        object.__setattr__(result, "text", "界" * 10923)  # 32,769 UTF8 bytes, not chars.
    else:
        object.__setattr__(result, "visuals", tuple(visual() for _ in range(9)))
    # Malformed injected result must not bypass the concrete protocol boundary.
    env.preparation.prepare = lambda *a, **kw: result
    with pytest.raises(BatchAnalysisError):
        env.service.run_prepared(capture(env))
    assert not env.inference.calls


def test_template_subclass_cannot_smuggle_mutable_extras_into_work(tmp_path):
    @dataclass(frozen=True)
    class ExtendedTemplate(Template):
        extra: dict = field(default_factory=lambda: {"secret": ["secret-marker"]})
    env = setup_service(tmp_path)
    env.service._template_provider = lambda _: ExtendedTemplate(name="Extended", pattern="{dcTitle}")
    with pytest.raises(BatchAnalysisError):
        capture(env)


def test_cloud_visual_ocr_requires_text_consent_too(tmp_path):
    env = cloud_env(tmp_path)
    from src.core.processing_analysis import cloud_engine_fingerprint
    profile = replace(env.profile, capabilities=ProviderCapabilities(text=True, vision=True, json_schema=True))
    env.service._profile_provider = lambda: profile
    env.authority.bind_cloud_engine(cloud_engine_fingerprint(profile))
    env.config.allow_text_cloud = False
    env.config.allow_vision_cloud = True
    env.source = env.source.with_suffix(".png")
    env.source.write_bytes(b"synthetic")
    env.service._extract_content = lambda *a: ("genuine private OCR", {})
    env.service._image = SimpleNamespace(process_file=lambda *a, **kw: visual())
    with pytest.raises(BatchAnalysisError, match="Text cloud processing is disabled"):
        env.service.run_prepared(capture(env))
    assert not env.calls


def test_eight_visuals_exact_16mib_aggregate_is_accepted(tmp_path):
    import struct
    import zlib
    env = setup_service(tmp_path)
    env.source = env.source.with_suffix(".mp4")
    env.source.write_bytes(b"synthetic-video")
    original = visual("video_keyframe").data
    # Valid PNG ancillary chunk, not fabricated image bytes or original video.
    data_size = 2 * 1024 * 1024 - len(original) - 12
    chunk = b"tEXt" + b"note\x00" + b"x" * (data_size - 5)
    png = original[:-12] + struct.pack(">I", data_size) + chunk + struct.pack(">I", zlib.crc32(chunk)) + original[-12:]
    Image.open(io.BytesIO(png)).load()
    payloads = tuple(prepare_visual_payload(kind="video_keyframe", mime_type="image/png", data=png,
        width=8, height=8, source_index=i, preprocessing_version="video-v1+image-v1", provenance="local-video-frame") for i in range(8))
    env.preparation.result = LocalPreparationResult("", payloads,
        PreparationCoverage("video", text_source="none", video_duration_seconds=10,
            video_timestamps_seconds=tuple(float(i) for i in range(8))), ("video_sampled",), "high")
    outcome = env.service.run_prepared(capture(env, quality_mode="high"))
    request = env.inference.calls[0][0]
    assert len(request.visuals) == 8 and sum(p.byte_size for p in request.visuals) == 16 * 1024 * 1024
    assert request.quality == "quality" and outcome.effective_quality == "high"


def test_exact_64_lines_are_not_grouped_or_marked_partial(tmp_path):
    env = setup_service(tmp_path)
    text = "\n".join(f"actual-{i}" for i in range(64))
    env.preparation.result = LocalPreparationResult(text, (visual(),), PreparationCoverage("image"), (), "balanced")
    outcome = env.service.run_prepared(capture(env))
    assert env.inference.calls[0][0].text == text
    assert not outcome.coverage.text_truncated


def test_managed_cloud_factory_never_drops_guard_keywords(tmp_path):
    env = cloud_env(tmp_path)
    unguarded = []
    env.service._managed_adapter_factory = lambda p, key: unguarded.append((p, key))
    with pytest.raises(BatchAnalysisError, match="Cloud analysis failed"):
        env.service.run_prepared(capture(env))
    assert not unguarded and not env.cloud_calls


def test_cloud_exact_character_limit_uses_actual_extractor_coverage(tmp_path):
    env = cloud_env(tmp_path)
    env.config.max_content_chars = len("synthetic input")
    outcome = env.service.run_prepared(capture(env))
    assert not outcome.coverage.text_truncated and outcome.coverage.sections_processed == 1
    assert outcome.warning_codes == ()


def test_cloud_200_page_setting_does_not_inherit_local_wire_100_page_cap(tmp_path):
    env = cloud_env(tmp_path)
    env.config.max_pdf_pages = 200
    env.source = env.source.with_suffix(".pdf")
    env.source.write_bytes(b"synthetic")
    env.service._extract_content = lambda *args, **kwargs: ("项目报告", {
        "pages": 150, "pages_processed": 150, "sections_processed": 150,
        "sections_total": 150, "coverage_reason": "complete",
        "text_page_indices": tuple(range(150))})
    outcome = env.service.run_prepared(capture(env))
    assert outcome.coverage.text_page_indices == tuple(range(150))
    assert not outcome.coverage.text_truncated and outcome.warning_codes == ()


def test_deferred_local_deadline_starts_once_at_first_execution(tmp_path, monkeypatch):
    env = setup_service(tmp_path)
    now = [100.]
    monkeypatch.setattr("src.core.batch_analysis.time.monotonic", lambda: now[0])
    work = capture(env, defer_execution_deadline=True)
    assert work.deadline is None
    now[0] = 900.
    outcome = env.service.run_prepared(work)
    assert outcome.context is work.context and work.deadline is None
    assert env.preparation.calls[0][1]["deadline"] == 1500.
    assert env.inference.calls[0][1]["deadline"] == 1500.
    now[0] = 1600.
    with pytest.raises(ProcessingSuperseded):
        env.service.run_prepared(work)
    assert len(env.preparation.calls) == len(env.inference.calls) == 1


@pytest.mark.parametrize("first", ["failed", "cancelled", "stale"])
def test_deferred_work_cannot_renew_after_failure_or_cancellation(tmp_path, first):
    env = setup_service(tmp_path)
    work = capture(env, defer_execution_deadline=True)
    if first == "failed":
        env.inference.result = LocalInferenceResult(False, None, "synthetic", None, 0)
    elif first == "cancelled":
        work.context.task_cancel_event.set()
    else:
        env.authority.select_local()
    with pytest.raises((ProcessingSuperseded, BatchAnalysisError)):
        env.service.run_prepared(work)
    before = len(env.preparation.calls)
    work.context.task_cancel_event.clear()
    with pytest.raises(ProcessingSuperseded):
        env.service.run_prepared(work)
    assert len(env.preparation.calls) == before


def test_concurrent_deferred_execution_is_rejected_before_io(tmp_path):
    from threading import Thread
    env = setup_service(tmp_path)
    entered, release = Event(), Event()
    env.preparation.hook = lambda: (entered.set(), release.wait(3))
    work = capture(env, defer_execution_deadline=True)
    values = []
    runner = Thread(target=lambda: values.append(env.service.run_prepared(work)))
    runner.start()
    try:
        assert entered.wait(2)
        with pytest.raises(ProcessingSuperseded):
            env.service.run_prepared(work)
        assert len(env.preparation.calls) == 1
    finally:
        release.set()
        runner.join(3)
    assert len(values) == 1


def test_capture_holds_shared_catalog_guard_before_authority_and_all_reads(tmp_path):
    from contextlib import contextmanager
    active = []
    @contextmanager
    def guard():
        active.append(True)
        try:
            yield
        finally:
            active.pop()
    env = setup_service(tmp_path, capture_guard=guard)
    original = env.authority.snapshot
    def snapshot():
        assert active == [True]
        return original()
    env.authority.snapshot = snapshot
    env.service._config_provider = lambda: (active == [True] or pytest.fail("unguarded config")) and env.config
    env.service._template_provider = lambda _: (active == [True] or pytest.fail("unguarded template")) and template()
    work = capture(env)
    assert not active
    env.authority.snapshot = original
    env.preparation.hook = lambda: not active or pytest.fail("I/O under catalog guard")
    env.service.run_prepared(work)


def test_deferred_budget_is_one_absolute_deadline_across_preparation_and_inference(tmp_path, monkeypatch):
    env = setup_service(tmp_path)
    now = [100.]
    monkeypatch.setattr("src.core.batch_analysis.time.monotonic", lambda: now[0])
    work = capture(env, defer_execution_deadline=True)
    now[0] = 1000.
    env.preparation.hook = lambda: now.__setitem__(0, 1601.)
    with pytest.raises(BatchAnalysisError, match="^Local analysis timed out$"):
        env.service.run_prepared(work)
    assert env.preparation.calls[0][1]["deadline"] == 1600.
    assert not env.inference.calls
    with pytest.raises(ProcessingSuperseded):
        env.service.run_prepared(work)
    assert len(env.preparation.calls) == 1


@pytest.mark.parametrize("deferred", [False, True])
def test_deferred_option_does_not_change_cloud_execution_behavior(tmp_path, monkeypatch, deferred):
    env = cloud_env(tmp_path)
    work = capture(env, defer_execution_deadline=deferred)
    assert work.deadline is None
    monkeypatch.setattr("src.core.batch_analysis.time.monotonic", lambda: 1_000_000.)
    assert env.service.run_prepared(work).context is work.context
    # Existing fake transport deliberately reuses send-1; the genuine authority
    # refuses that duplicate receipt equally with or without local deferral.
    with pytest.raises(BatchAnalysisError, match="^Cloud analysis failed$"):
        env.service.run_prepared(work)
    assert sum(call[0] == "invoke" for call in env.calls) == 2


def test_deferred_lane_shared_across_pools_starts_budget_after_wait(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    env = setup_service(tmp_path)
    entered, release, second_entered = Event(), Event(), Event()
    now = [100.]
    monkeypatch.setattr("src.core.batch_analysis.time.monotonic", lambda: now[0])
    env.inference.hook = lambda: (entered.set(), release.wait(3))
    first, second = capture(env, defer_execution_deadline=True), capture(env, defer_execution_deadline=True)
    with ThreadPoolExecutor(1) as pool_a, ThreadPoolExecutor(1) as pool_b:
        running = pool_a.submit(env.service.run_prepared, first)
        assert entered.wait(2)
        env.preparation.hook = second_entered.set
        waiting = pool_b.submit(env.service.run_prepared, second)
        try:
            assert not second_entered.wait(.15), "queued runner entered preparation"
            now[0] = 900.  # >600 synthetic queue seconds; first must time out and release.
        finally:
            release.set()
        with pytest.raises(BatchAnalysisError, match="Local analysis timed out"):
            running.result(2)
        assert waiting.result(2).context is second.context
    assert env.preparation.calls[1][1]["deadline"] == 1500.
    assert env.inference.calls[1][1]["deadline"] == 1500.


@pytest.mark.parametrize("change", ["cancel", "generation"])
def test_deferred_lane_wait_cancellation_rejects_before_io(tmp_path, change):
    from concurrent.futures import ThreadPoolExecutor
    env = setup_service(tmp_path)
    entered, release = Event(), Event()
    env.inference.hook = lambda: (entered.set(), release.wait(3))
    first, second = capture(env, defer_execution_deadline=True), capture(env, defer_execution_deadline=True)
    with ThreadPoolExecutor(1) as pool_a, ThreadPoolExecutor(1) as pool_b:
        active = pool_a.submit(env.service.run_prepared, first)
        assert entered.wait(2)
        queued = pool_b.submit(env.service.run_prepared, second)
        try:
            time.sleep(.1)
            assert len(env.preparation.calls) == 1
            if change == "cancel":
                second.context.task_cancel_event.set()
            else:
                env.authority.select_local()
            with pytest.raises(ProcessingSuperseded):
                queued.result(.5)  # Must leave while active runner is still blocked.
            with pytest.raises(ProcessingSuperseded):
                env.service.run_prepared(second)  # Claim was consumed before waiting.
            assert len(env.preparation.calls) == 1
        finally:
            release.set()
        if change == "generation":
            with pytest.raises(ProcessingSuperseded):
                active.result(2)
        else:
            active.result(2)


def test_deferred_lane_eight_waiters_overflow_consumes_claim_and_finally_releases(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    env = setup_service(tmp_path)
    entered, release = Event(), Event()
    env.inference.hook = lambda: (entered.set(), release.wait(5))
    works = [capture(env, defer_execution_deadline=True) for _ in range(10)]
    with ThreadPoolExecutor(1) as pool_a, ThreadPoolExecutor(9) as pool_b:
        active = pool_a.submit(env.service.run_prepared, works[0])
        assert entered.wait(2)
        waiters = [pool_b.submit(env.service.run_prepared, work) for work in works[1:9]]
        try:
            until = time.monotonic() + 2
            while getattr(env.service, "_local_waiters", 0) != 8 and time.monotonic() < until:
                time.sleep(.005)
            assert len(env.preparation.calls) == 1, "waiting runners performed I/O"
            overflow = pool_b.submit(env.service.run_prepared, works[9])
            with pytest.raises(BatchAnalysisError, match="^Local analysis queue is full$"):
                overflow.result(.5)
            with pytest.raises(ProcessingSuperseded):
                env.service.run_prepared(works[9])
        finally:
            release.set()
        active.result(2)
        for waiter in waiters:
            waiter.result(2)
    assert len(env.preparation.calls) == 9


def test_default_local_caller_does_not_join_deferred_lane(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    env = setup_service(tmp_path)
    entered, release = Event(), Event()
    env.inference.hook = lambda: (entered.set(), release.wait(3))
    with ThreadPoolExecutor(2) as pool:
        deferred = pool.submit(env.service.run_prepared, capture(env, defer_execution_deadline=True))
        assert entered.wait(2)
        env.inference.hook = lambda: None
        ordinary = pool.submit(env.service.run_prepared, capture(env))
        try:
            assert ordinary.result(.5).suggested_name == "项目报告.txt"
        finally:
            release.set()
        deferred.result(2)
