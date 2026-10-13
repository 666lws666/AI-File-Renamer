"""Prepared-input contracts; genuine tiny images, no input or output files."""
from dataclasses import FrozenInstanceError, replace
from io import BytesIO
import json

from PIL import Image
import pytest

from src.core.provider_protocol import prepare_visual_payload
from src.core.template_model import Template, TemplateField
from src.core.template_renderer import RenderStatus, TemplateRenderer


def api():
    from src.services.local_ai import inference_request
    return inference_request


def visual(fmt="PNG", kind="resized_image"):
    stream = BytesIO()
    Image.new("RGB", (2, 2), (10, 80, 120)).save(stream, format=fmt)
    return prepare_visual_payload(kind=kind, mime_type={"PNG": "image/png",
        "JPEG": "image/jpeg", "WEBP": "image/webp"}[fmt], data=stream.getvalue(),
        width=2, height=2, source_index=0, preprocessing_version="synthetic-v1",
        provenance="synthetic test")


def request(**kwargs):
    return api().LocalNamingRequest(**({"text": "Campus network maintenance",
        "visuals": (), "locale": "en-US", "naming_mode": "smart"} | kwargs))


def raw(topic="Campus network maintenance", source="text", evidence="T000"):
    return json.dumps({"understood": True, "language": "en-US", "topic": {
        "value": topic, "evidence_source": source, "evidence": evidence},
        "date": None, "version": None}).encode()


@pytest.mark.parametrize("fmt,suffix", [("PNG", "png"), ("JPEG", "jpg"), ("WEBP", "webp")])
@pytest.mark.parametrize("text", ["", "Campus network maintenance"])
def test_genuine_prepared_image_bytes_are_preserved_with_fixed_suffix(fmt, suffix, text):
    payload = visual(fmt)
    prepared = api().prepare_request(request(text=text, visuals=(payload,)))
    assert tuple(item.name for item in prepared.members) == ("prompt.txt", "schema.json", f"visual_00.{suffix}")
    assert prepared.members[2].data is payload.data
    assert prepared.visual_names == (f"visual_00.{suffix}",)
    assert "synthetic test" not in repr(prepared)
    assert "Campus network maintenance" not in repr(prepared)


def test_request_data_is_frozen_repr_hidden_and_high_is_normalized():
    req = request(quality="high", visuals=(visual(),))
    assert req.quality == "quality"
    assert req.text not in repr(req)
    assert "PNG" not in repr(req)
    with pytest.raises(FrozenInstanceError):
        req.quality = "economy"
    result = api().LocalInferenceResult(True, {"nested": [{"value": "private"}]}, None, "public", 1.0)
    assert "private" not in repr(result)
    with pytest.raises(TypeError):
        result.fields["nested"][0]["value"] = "changed"


@pytest.mark.parametrize("changes", [
    {"text": " "}, {"text": b"text"}, {"text": "x" * 32769}, {"text": "\ud800"},
    {"visuals": []}, {"visuals": (b"raw",)}, {"visuals": (visual(),) * 9},
    {"locale": "en"}, {"locale": []}, {"naming_mode": "cloud"},
    {"naming_mode": []}, {"naming_mode": "template"}, {"template": Template(name="Hidden")},
    {"quality": "invalid"}, {"quality": []}, {"text_layout": "invalid"},
    {"text_layout": "contiguous", "visuals": (visual(),)},
])
def test_invalid_requests_have_only_fixed_error(changes):
    with pytest.raises(ValueError, match="^INVALID_REQUEST$"):
        request(**changes)


@pytest.mark.parametrize("field,value", [
    ("mime_type", "image/jpeg"), ("kind", "pdf"), ("content_digest", "0" * 64),
    ("byte_size", True), ("byte_size", 999), ("data", bytearray(b"raw")),
    ("width", True), ("height", 0), ("source_index", True), ("source_index", -1),
    ("provenance", " "), ("preprocessing_version", ""),
])
def test_mutated_product_payload_is_revalidated(field, value):
    payload = visual()
    object.__setattr__(payload, field, value)
    with pytest.raises(ValueError, match="^INVALID_REQUEST$"):
        request(visuals=(payload,))


def test_total_visual_bytes_bound_without_transcoding():
    payload = prepare_visual_payload(kind="resized_image", mime_type="image/png",
        data=b"\x89PNG\r\n\x1a\n" + b"x" * 8388601, width=2, height=2,
        source_index=0, preprocessing_version="synthetic-v1", provenance="synthetic")
    with pytest.raises(ValueError, match="^INVALID_REQUEST$"):
        request(visuals=(payload, payload))


@pytest.mark.parametrize("kwargs", [{"source_path": "private.pdf"}, {"flags": ("--server",)},
                                  {"schema": {}}, {"output_path": "private.json"}])
def test_request_has_no_raw_path_flags_or_schema_surface(kwargs):
    with pytest.raises(TypeError):
        request(**kwargs)


def test_strict_smart_decode_is_frozen_and_uses_actual_policy():
    prepared = api().prepare_request(request())
    fields = api().decode_prepared_response(prepared, raw())
    assert fields["parts"][0]["evidence"] == "Campus network maintenance"
    assert type(fields["parts"]) is tuple
    with pytest.raises(TypeError):
        fields["parts"][0]["value"] = "changed"
    with pytest.raises(ValueError, match="^INVALID_RESPONSE$"):
        api().decode_prepared_response(prepared, raw(topic="Report"))


@pytest.mark.parametrize("output", [b"{} trailing", b"\xff", b" " * 262145,
    b'{"understood":true,"understood":false}', raw(evidence="T099")],
    ids=["trailing", "utf8", "oversize", "duplicate", "evidence"])
def test_strict_response_failures_are_content_free(output):
    with pytest.raises(ValueError, match="^INVALID_RESPONSE$"):
        api().decode_prepared_response(api().prepare_request(request()), output)


def test_insufficient_content_has_distinct_fixed_code():
    with pytest.raises(ValueError, match="^INSUFFICIENT_CONTENT$"):
        api().decode_prepared_response(api().prepare_request(request()),
            b'{"understood":false,"language":"en-US"}')


@pytest.mark.parametrize("layout", ["lines", "contiguous"])
def test_template_missing_date_remains_renderer_needs_regeneration(layout):
    template = Template(name="Private template")
    req = request(text="Campus\nnetwork maintenance", naming_mode="template", template=template,
                  text_layout=layout)
    prepared = api().prepare_request(req)
    fields = api().decode_prepared_response(prepared, json.dumps({"understood": True,
        "language": "en-US", "fields": {"dcTitle": {"value": "Network maintenance",
        "evidence": "T000", "evidence_source": "text"}, "dcDate": None}}).encode())
    assert fields.dcDate is None
    assert TemplateRenderer.render(template, fields, ".txt").status is RenderStatus.NEEDS_REGENERATION
    assert "Private template" not in repr(req)


@pytest.mark.parametrize("builder", ["build_smart_prompt", "local_schema"])
def test_prompt_and_schema_bounds_are_enforced(monkeypatch, builder):
    module = api()
    monkeypatch.setattr(module.protocol, builder, lambda *a, **k:
        "x" * 131073 if builder == "build_smart_prompt" else {"large": "x" * 131073})
    with pytest.raises(ValueError, match="^INVALID_REQUEST$"):
        module.prepare_request(request())


def test_forged_mutable_template_fields_are_not_accepted():
    template = Template(name="Mutable")
    object.__setattr__(template, "fields", list(template.fields))
    with pytest.raises(ValueError, match="^INVALID_REQUEST$"):
        request(naming_mode="template", template=template)


def test_template_is_defensively_snapshotted_for_request_and_prepared_decode():
    template = Template(name="Private template")
    req = request(naming_mode="template", template=template)
    original_pattern = template.pattern
    object.__setattr__(template, "pattern", "{dcTitle}")
    assert req.template.pattern == original_pattern
    prepared = api().prepare_request(req)
    object.__setattr__(req.template, "pattern", "{dcTitle}")
    assert prepared.template.pattern == original_pattern


@pytest.mark.parametrize("field,value", [
    ("enabled", 1), ("order", True), ("dc_name", ("dcTitle",)),
    ("display_name", ("Title",)), ("id", ("forged",)),
])
def test_forged_template_field_scalar_types_are_rejected(field, value):
    template = Template(name="Private template", pattern="{dcTitle}",
                        fields=(TemplateField("dcTitle", "Title"),))
    object.__setattr__(template.fields[0], field, value)
    with pytest.raises(ValueError, match="^INVALID_REQUEST$"):
        request(naming_mode="template", template=template)
