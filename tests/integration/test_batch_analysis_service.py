"""M8 production analysis boundary tests; all Provider calls are in memory."""

from types import SimpleNamespace

from src.core.batch_analysis import BatchAnalysisError, BatchAnalysisService
from src.core.provider_profile import ProviderProfile
from src.core.provider_protocol import ProviderCapabilities, ProviderResponse, prepare_visual_payload
from src.core.template_model import DateFormat, Template, TemplateField
from src.models.app_config import AppConfig
from src.services.retry_policy import RetryExecutionResult


def _template():
    return Template(
        name="Default",
        pattern="{dcDate}_{dcTitle}",
        date_format=DateFormat.YYYYMMDD,
        fields=(
            TemplateField("dcDate", "Date", order=1, enabled=True),
            TemplateField("dcTitle", "Title", order=2, enabled=True),
        ),
    )


def _profile(**capabilities):
    return ProviderProfile(
        id="qwen", display_name="Qwen", provider_id="qwen",
        base_url="https://example.invalid/v1", model="qwen-test",
        needs_connection_verification=False,
        capabilities=ProviderCapabilities(
            text=True, json_schema=True, **capabilities,
        ),
    )


class _Adapter:
    def __init__(self): self.requests = []

    def invoke(self, request, *, cancellation_token=None):
        self.requests.append(request)
        return RetryExecutionResult(
            True,
            ProviderResponse(fields={"dcDate": "20260809", "dcTitle": "项目资料"}),
            (), None, None,
        )


def _payload(kind="resized_image", index=0):
    from PIL import Image
    import io

    image = Image.new("RGB", (8, 6), "white")
    output = io.BytesIO(); image.save(output, format="JPEG")
    data = output.getvalue()
    return prepare_visual_payload(
        kind=kind, mime_type="image/jpeg", data=data, width=8, height=6,
        source_index=index, preprocessing_version="test-v1", provenance="synthetic-test",
    )


def _service(profile, adapter, *, extractor, image=None, pdf=None, video=None, config=None):
    return BatchAnalysisService(
        profile_provider=lambda: profile,
        credential_provider=lambda _profile: "fake-key",
        adapter_factory=lambda _profile, _key: adapter,
        config_provider=lambda: config or AppConfig(),
        template_provider=lambda _template_id: _template(),
        content_extractor=extractor,
        image_preprocessor=image,
        pdf_renderer=pdf,
        video_extractor=video,
    )


def test_text_pipeline_returns_template_filename_without_path_leak(tmp_path):
    source = tmp_path / "机密原名.txt"; source.write_text("项目摘要", encoding="utf-8")
    adapter = _Adapter()
    service = _service(
        _profile(), adapter,
        extractor=lambda _path, _limit: ("项目摘要", {"pages": 1}),
    )

    assert service(str(source), "task-1") == "20260809_项目资料.txt"
    request = adapter.requests[0]
    assert request.extracted_text == "项目摘要"
    assert request.visual_payloads == ()
    assert str(tmp_path) not in repr(request.metadata)


def test_image_pipeline_sends_only_prepared_payload(tmp_path):
    source = tmp_path / "照片.png"; source.write_bytes(b"not-decoded-by-fake")
    adapter = _Adapter()
    prepared = _payload()
    image = SimpleNamespace(process_file=lambda _path, source_index, **_kwargs: prepared)
    service = _service(
        _profile(vision=True), adapter,
        extractor=lambda _path, _limit: ("", {"width": 8, "height": 6}),
        image=image,
    )

    assert service(str(source), "task-image").endswith(".png")
    request = adapter.requests[0]
    assert request.visual_payloads == (prepared,)
    assert request.metadata["content_kind"] == "image"
    assert source.read_bytes() not in tuple(item.data for item in request.visual_payloads)


def test_scanned_pdf_and_video_never_send_complete_source_bytes(tmp_path):
    profile = _profile(vision=True, multi_image=True)
    for extension, renderer_name, kind in ((".pdf", "pdf", "rendered_scan_page"), (".mp4", "video", "video_keyframe")):
        source = tmp_path / f"source{extension}"
        raw = (b"complete-source-binary-" + extension.encode()) * 20
        source.write_bytes(raw)
        adapter = _Adapter()
        payloads = (_payload(kind, 0), _payload(kind, 1))
        result = SimpleNamespace(payloads=payloads)
        if renderer_name == "pdf":
            result.total_page_count = 2
            result.rendered_page_indices = (0, 1)
        kwargs = {
            renderer_name: SimpleNamespace(**(
                {"render_file": lambda _path, result=result, **_kwargs: result}
                if renderer_name == "pdf" else
                {"extract_file": lambda _path, quality_mode, result=result, **_kwargs: result}
            ))
        }
        service = _service(
            profile, adapter, extractor=lambda _path, _limit: ("", {}), **kwargs,
        )

        service(str(source), f"task-{renderer_name}")
        request = adapter.requests[0]
        assert len(request.visual_payloads) == 2
        assert all(payload.data != raw for payload in request.visual_payloads)
        assert str(source) not in repr(request.metadata)


def test_configured_pdf_and_video_limits_reach_media_services(tmp_path):
    profile = _profile(vision=True, multi_image=True)
    config = AppConfig(max_pdf_pages=1, max_video_keyframes=1)
    calls = {}

    class Pdf:
        def render_file(self, _path, *, max_pages, cancellation_token=None):
            calls["pdf"] = (max_pages, cancellation_token)
            return SimpleNamespace(payloads=(_payload("rendered_scan_page", 0),),
                                   total_page_count=1, rendered_page_indices=(0,))

    class Video:
        def extract_file(self, _path, *, quality_mode, max_frames, cancellation_token=None):
            calls["video"] = (quality_mode, max_frames, cancellation_token)
            return SimpleNamespace(payloads=(_payload("video_keyframe", 0),))

    for extension, kwargs in ((".pdf", {"pdf": Pdf()}), (".mp4", {"video": Video()})):
        source = tmp_path / f"source{extension}"
        source.write_bytes(b"safe-local-fixture")
        service = _service(
            profile, _Adapter(), extractor=lambda *_: ("", {}), config=config, **kwargs,
        )
        service(str(source), f"task-{extension}")

    assert calls["pdf"][0] == 1
    assert calls["video"][:2] == ("balanced", 1)


def test_cancellation_reaches_media_and_provider_boundary(tmp_path):
    source = tmp_path / "image.png"; source.write_bytes(b"image")
    cancelled = lambda: True
    calls = []

    class Image:
        def process_file(self, _path, *, source_index, cancellation_token=None):
            calls.append(("image", cancellation_token))
            if cancellation_token and cancellation_token():
                raise BatchAnalysisError("cancelled")
            return _payload()

    adapter = _Adapter()
    service = _service(
        _profile(vision=True), adapter, extractor=lambda *_: ("", {}), image=Image(),
    )
    try:
        service(str(source), "task-image", cancellation_token=cancelled)
    except BatchAnalysisError as error:
        assert "cancelled" in str(error)
    else:
        raise AssertionError("cancelled analysis must stop before provider invocation")
    assert calls == []  # cancelled before any media decoder is entered
    assert adapter.requests == []


def test_visual_content_fails_closed_for_text_only_provider(tmp_path):
    source = tmp_path / "image.png"; source.write_bytes(b"image")
    service = _service(
        _profile(), _Adapter(), extractor=lambda _path, _limit: ("", {}),
        image=SimpleNamespace(process_file=lambda *_args, **_kw: _payload()),
    )

    try:
        service(str(source), "task-1")
    except BatchAnalysisError as error:
        assert str(error) == "capability.vision_unavailable_image"
    else:
        raise AssertionError("vision-incompatible provider must fail closed")


def test_legacy_watch_quality_override_controls_actual_preprocessing(tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"synthetic-video")
    calls = []
    video = SimpleNamespace(extract_file=lambda _path, **kwargs:
        calls.append(kwargs) or SimpleNamespace(payloads=(_payload("video_keyframe"),)))
    adapter = _Adapter()
    service = _service(_profile(vision=True), adapter, extractor=lambda *_: ("", {}), video=video)
    result = service.analyze(str(source), quality_mode="economy")
    assert result.suggested_name
    assert calls[0]["quality_mode"] == "economy"
    assert adapter.requests[0].quality_mode == result.quality_mode == "economy"
